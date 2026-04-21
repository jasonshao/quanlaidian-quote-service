"""Pricing + persistence + render business logic, shared by legacy and
resource-split endpoints."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.domain.pricing import build_quotation_config
from app.domain.pricing_baseline import load_baseline, pricing_version
from app.domain.render_pdf import render_pdf
from app.domain.render_xlsx import render_xlsx
from app.domain.schema import (
    ApprovalState,
    FileRef,
    QuoteItemBreakdown,
    QuoteItemPreview,
    QuotePreview,
    QuoteTotals,
)
from app.errors import OutOfRangeError, PricingError, RenderError
from app.persistence import get_conn
from app.persistence.models import Approval, Quote, QuoteRender
from app.persistence.quote_repo import (
    create_quote as _persist_quote,
    get_approval,
    get_quote,
    latest_render,
    persist_render as _persist_render,
    upsert_approval,
)
from app.storage import LocalDiskStorage


def sanitize(name: str) -> str:
    return str(name).strip().replace("/", "-")


def today_stamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def price_and_persist(
    *,
    form: dict,
    org: str,
    db_path: Path,
    baseline: dict,
    product_catalog_path: Path,
    idempotency_key: Optional[str] = None,
) -> tuple[Quote, Approval, dict]:
    """Price the form, persist quote + approval rows, return (quote, approval, config_dict).

    Idempotent on (org, form_hash) by default. If `idempotency_key` is supplied,
    it takes precedence — replaying the same key must use the same form or we
    raise ValueError (client bug).
    """
    try:
        config = build_quotation_config(form, baseline, product_catalog_path)
    except ValueError as e:
        msg = str(e)
        field = "人工改价原因" if "人工改价" in msg else None
        hint = "提供 成交价系数 时必须同时填写 人工改价原因" if field else None
        raise OutOfRangeError(field=field or "form", message=msg, hint=hint)

    pricing_info = config.get("pricing_info", {})
    with get_conn(db_path) as conn:
        quote = _persist_quote(
            conn,
            org=org,
            form=form,
            config=config,
            pricing_version=pricing_version(),
            idempotency_key=idempotency_key,
        )
        approval = upsert_approval(
            conn,
            quote_id=quote.id,
            required=bool(pricing_info.get("approval_required")),
            reasons=list(pricing_info.get("approval_reason") or []),
            requested_by=org,
        )
    return quote, approval, config


def render_format(
    *,
    quote: Quote,
    format: str,
    db_path: Path,
    storage: LocalDiskStorage,
    fonts_dir: Path,
    force: bool = False,
) -> QuoteRender:
    """Render one format for a persisted quote. Reuse existing render if `force` is False.

    `format` ∈ {"pdf", "xlsx", "json"}. Raises RenderError on failure.
    """
    if format not in {"pdf", "xlsx", "json"}:
        raise ValueError(f"unsupported format: {format}")

    if not force:
        with get_conn(db_path) as conn:
            existing = latest_render(conn, quote.id, format)
            if existing is not None:
                return existing

    form = json.loads(quote.form_json)
    config = json.loads(quote.config_json)
    brand = sanitize(form["客户品牌名称"])
    today = today_stamp()

    if format == "pdf":
        suffix = "报价单"
        content = render_pdf(config, fonts_dir=fonts_dir)
    elif format == "xlsx":
        suffix = "报价单"
        content = render_xlsx(config)
    else:
        suffix = "报价配置"
        content = json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")

    filename = f"{brand}-全来店-{suffix}-{today}.{format}"
    try:
        _, expires_at, file_token = storage.save(filename, content)
    except Exception as e:
        raise RenderError(message=f"{format.upper()} 保存失败: {e}")

    with get_conn(db_path) as conn:
        return _persist_render(
            conn,
            quote_id=quote.id,
            format=format,
            file_token=file_token,
            filename=filename,
            expires_at=expires_at.isoformat(),
        )


def render_to_file_ref(render: QuoteRender, base_url: str) -> FileRef:
    return FileRef(
        url=f"{base_url.rstrip('/')}/files/{render.file_token}/{render.filename}",
        filename=render.filename,
        expires_at=datetime.fromisoformat(render.expires_at),
    )


def build_preview(config: dict, form: dict) -> QuotePreview:
    items_preview: list[QuoteItemPreview] = []
    for item in config.get("报价项目", []):
        items_preview.append(
            QuoteItemPreview(
                name=item["商品名称"],
                qty=item["数量"],
                list=int(item.get("标准价", 0) if item.get("标准价") != "赠送" else 0),
                final=int(item.get("报价小计", 0)),
            )
        )
    total_list = sum(i.list * i.qty for i in items_preview)
    total_final = sum(i.final for i in items_preview)
    pricing_info = config.get("pricing_info", {})
    # preview.stores 反映实际报价使用的门店数。对于大客户段(31-300),
    # config["门店数量"] 已被 build_quotation_config 替换为 effective
    # store count(tier_window[0]);小段情况下 config["门店数量"] ==
    # form["门店数量"]。两种场景都优先用 config。
    effective_stores = int(config.get("门店数量", form["门店数量"]))
    return QuotePreview(
        brand=form["客户品牌名称"],
        meal_type=form["餐饮类型"],
        stores=effective_stores,
        package=form["门店套餐"],
        discount=float(pricing_info.get("final_factor", 1.0)),
        totals=QuoteTotals(list=total_list, final=total_final),
        items=items_preview,
    )


def build_breakdown(config: dict) -> list[QuoteItemBreakdown]:
    items: list[QuoteItemBreakdown] = []
    for item in config.get("报价项目", []):
        standard = item.get("标准价", 0)
        list_price = int(standard) if standard != "赠送" else 0
        items.append(
            QuoteItemBreakdown(
                name=item["商品名称"],
                category=item.get("商品分类", ""),
                module_category=item.get("模块分类", ""),
                unit=item.get("单位", ""),
                qty=int(item.get("数量", 0)),
                list_price=list_price,
                unit_price=int(item.get("商品单价", 0)),
                subtotal=int(item.get("报价小计", 0)),
                cost_unit_price=int(item.get("成本单价", 0)),
                cost_subtotal=int(item.get("成本小计", 0)),
                profit=int(item.get("利润", 0)),
                margin_pct=float(item.get("利润率", 0)),
                protected=bool(item.get("protected_item_bypass", False)),
                factor=float(item.get("成交价系数", 1.0)),
            )
        )
    return items


def approval_to_state(approval: Optional[Approval]) -> ApprovalState:
    if approval is None:
        return ApprovalState(required=False, state="not_required", reasons=[])
    return ApprovalState(
        required=approval.required,
        state=approval.state,
        reasons=approval.reasons,
        decided_by=approval.decided_by,
        decision_reason=approval.decision_reason,
        decided_at=approval.decided_at,
    )


def fetch_quote_or_404(db_path: Path, quote_id: str, org: str) -> Quote:
    """Fetch a quote by id, enforce org scoping. Raises PricingError if not found."""
    with get_conn(db_path) as conn:
        q = get_quote(conn, quote_id)
    if q is None or q.org != org:
        raise PricingError(message=f"quote {quote_id} 不存在或不属于当前 org")
    return q


def fetch_approval(db_path: Path, quote_id: str) -> Optional[Approval]:
    with get_conn(db_path) as conn:
        return get_approval(conn, quote_id)
