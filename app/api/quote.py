import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.auth import TokenInfo, verify_token
from app.audit import log_request
from app.config import settings
from app.domain.pricing import build_quotation_config
from app.domain.pricing_baseline import load_baseline, pricing_version
from app.domain.render_pdf import render_pdf
from app.domain.render_xlsx import render_xlsx
from app.domain.schema import QuoteForm, QuoteResponse, QuotePreview, QuoteTotals, QuoteItemPreview, FileRef
from app.errors import OutOfRangeError, PricingError, RenderError
from app.storage import LocalDiskStorage

router = APIRouter()

def _gen_request_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = secrets.token_hex(4)
    return f"req_{ts}_{rand}"

def _sanitize(name: str) -> str:
    return str(name).strip().replace("/", "-")

def _today() -> str:
    return datetime.now().strftime("%Y%m%d")

def _get_storage() -> LocalDiskStorage:
    return LocalDiskStorage(
        root=settings.data_root / "files",
        base_url=settings.api_base_url,
        ttl_days=settings.file_ttl_days,
    )

def _get_baseline() -> dict:
    return load_baseline(settings.data_root / "pricing_baseline.json")

def _get_product_catalog_path() -> Path:
    # Product catalog lives alongside the app's references
    # In production: /opt/quanlaidian-quote/references/product_catalog.md
    # For dev/test: check a few common locations
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "references" / "product_catalog.md",
        Path("/opt/quanlaidian-quote/references/product_catalog.md"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise PricingError(message="未找到产品目录文件 product_catalog.md")

@router.post("/v1/quote", response_model=QuoteResponse)
def create_quote(
    form: QuoteForm,
    request: Request,
    token_info: TokenInfo = Depends(verify_token(settings.data_root / "tokens.json")),
):
    request_id = _gen_request_id()
    request.state.request_id = request_id
    start_time = time.monotonic()

    # 1. Build quotation config
    baseline = _get_baseline()
    product_catalog_path = _get_product_catalog_path()
    form_dict = form.model_dump()
    config = build_quotation_config(form_dict, baseline, product_catalog_path)

    # 2. Render files
    try:
        pdf_bytes = render_pdf(config, fonts_dir=settings.data_root / "fonts")
    except Exception as e:
        raise RenderError(message=f"PDF 生成失败: {e}")

    try:
        xlsx_bytes = render_xlsx(config)
    except Exception as e:
        raise RenderError(message=f"XLSX 生成失败: {e}")

    config_json_bytes = json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")

    # 3. Save files
    storage = _get_storage()
    brand = _sanitize(form.客户品牌名称)
    today = _today()

    pdf_url, pdf_expires = storage.save(f"{brand}-全来店-报价单-{today}.pdf", pdf_bytes)
    xlsx_url, xlsx_expires = storage.save(f"{brand}-全来店-报价单-{today}.xlsx", xlsx_bytes)
    json_url, json_expires = storage.save(f"{brand}-全来店-报价配置-{today}.json", config_json_bytes)

    # 4. Build preview from config
    items_preview = []
    for item in config.get("报价项目", []):
        items_preview.append(QuoteItemPreview(
            name=item["商品名称"],
            qty=item["数量"],
            list=int(item.get("标准价", 0) if item.get("标准价") != "赠送" else 0),
            final=int(item.get("报价小计", 0)),
        ))

    pricing_info = config.get("pricing_info", {})
    total_list = sum(i.list * i.qty for i in items_preview)
    total_final = sum(i.final for i in items_preview)

    preview = QuotePreview(
        brand=form.客户品牌名称,
        meal_type=form.餐饮类型,
        stores=form.门店数量,
        package=form.门店套餐,
        discount=pricing_info.get("final_factor", 1.0),
        totals=QuoteTotals(list=total_list, final=total_final),
        items=items_preview,
    )

    # 5. Audit log
    duration_ms = int((time.monotonic() - start_time) * 1000)
    log_request(settings.data_root / "audit", {
        "ts": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "org": token_info.org,
        "brand": form.客户品牌名称,
        "stores": form.门店数量,
        "package": form.门店套餐,
        "discount": pricing_info.get("final_factor", 1.0),
        "final": total_final,
        "pricing_version": pricing_version(),
        "status": "ok",
        "duration_ms": duration_ms,
    })

    # 6. Response
    return QuoteResponse(
        request_id=request_id,
        preview=preview,
        files={
            "pdf": FileRef(url=pdf_url, filename=f"{brand}-全来店-报价单-{today}.pdf", expires_at=pdf_expires),
            "xlsx": FileRef(url=xlsx_url, filename=f"{brand}-全来店-报价单-{today}.xlsx", expires_at=xlsx_expires),
            "json": FileRef(url=json_url, filename=f"{brand}-全来店-报价配置-{today}.json", expires_at=json_expires),
        },
        pricing_version=pricing_version(),
    )
