"""Legacy /v1/quote endpoint.

Kept for UAT clients. Internally delegates to the resource-oriented endpoints
in quotes.py: one POST /v1/quote call = price_and_persist + render(pdf) +
render(xlsx) + render(json), packaged into the legacy response envelope.
"""
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.auth import TokenInfo, verify_token
from app.audit import log_request
from app.config import settings
from app.domain.pricing_baseline import load_baseline, pricing_version
from app.domain.quote_service import (
    build_preview,
    price_and_persist,
    render_format,
    render_to_file_ref,
)
from app.domain.schema import FileRef, QuoteForm, QuoteResponse
from app.errors import PricingError
from app.storage import LocalDiskStorage

router = APIRouter()


def _gen_request_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"req_{ts}_{secrets.token_hex(4)}"


def _get_storage() -> LocalDiskStorage:
    return LocalDiskStorage(
        root=settings.data_root / "files",
        base_url=settings.api_base_url,
        ttl_days=settings.file_ttl_days,
    )


def _get_baseline() -> dict:
    repo_root = Path(__file__).resolve().parent.parent.parent
    return load_baseline(
        json_path=settings.data_root / "pricing_baseline.json",
        obf_path=repo_root / "references" / "pricing_baseline_v5.obf",
    )


def _get_product_catalog_path() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "references" / "product_catalog.md",
        Path("/opt/quanlaidian-quote/references/product_catalog.md"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise PricingError(message="未找到产品目录文件 product_catalog.md")


@router.post("/v1/quote", response_model=QuoteResponse)
def create_quote_legacy(
    form: QuoteForm,
    request: Request,
    token_info: TokenInfo = Depends(verify_token(settings.data_root / "quote.db")),
):
    request_id = _gen_request_id()
    request.state.request_id = request_id
    start_time = time.monotonic()
    form_dict = form.model_dump()
    db_path = settings.data_root / "quote.db"

    quote, approval, config = price_and_persist(
        form=form_dict,
        org=token_info.org,
        db_path=db_path,
        baseline=_get_baseline(),
        product_catalog_path=_get_product_catalog_path(),
    )

    storage = _get_storage()
    fonts_dir = settings.data_root / "fonts"
    files: dict[str, FileRef] = {}
    for fmt in ("pdf", "xlsx", "json"):
        render = render_format(
            quote=quote,
            format=fmt,
            db_path=db_path,
            storage=storage,
            fonts_dir=fonts_dir,
        )
        files[fmt] = render_to_file_ref(render, settings.api_base_url)

    preview = build_preview(config, form_dict)

    duration_ms = int((time.monotonic() - start_time) * 1000)
    pricing_info = config.get("pricing_info", {})
    log_request(settings.data_root / "audit", {
        "ts": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "quote_id": quote.id,
        "org": token_info.org,
        "token_id": token_info.token_id,
        "brand": form.客户品牌名称,
        "stores": form.门店数量,
        "package": form.门店套餐,
        "discount": pricing_info.get("final_factor", 1.0),
        "final": preview.totals.final,
        "pricing_version": pricing_version(),
        "status": "ok",
        "duration_ms": duration_ms,
    })

    return QuoteResponse(
        request_id=request_id,
        preview=preview,
        files=files,
        pricing_version=pricing_version(),
    )
