"""Resource-oriented quote endpoints introduced in Wave B.

Legacy POST /v1/quote lives in app/api/quote.py and now delegates here.
"""
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Request, Response

from app.auth import TokenInfo, verify_token
from app.config import settings
from app.domain.pricing_baseline import load_baseline, pricing_version
from app.domain.quote_service import (
    approval_to_state,
    build_breakdown,
    build_preview,
    fetch_approval,
    fetch_quote_or_404,
    price_and_persist,
    render_format,
    render_to_file_ref,
)
from app.domain.schema import (
    FileRef,
    QuoteCreated,
    QuoteDetail,
    QuoteExplain,
    QuoteForm,
    QuoteTotals,
)
from app.errors import NotFoundError, PricingError
from app.persistence import get_conn
from app.persistence.quote_repo import list_renders
from app.storage import LocalDiskStorage

router = APIRouter()


def _gen_request_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"req_{ts}_{secrets.token_hex(4)}"


def _storage() -> LocalDiskStorage:
    return LocalDiskStorage(
        root=settings.data_root / "files",
        base_url=settings.api_base_url,
        ttl_days=settings.file_ttl_days,
    )


def _baseline() -> dict:
    repo_root = Path(__file__).resolve().parent.parent.parent
    return load_baseline(
        json_path=settings.data_root / "pricing_baseline.json",
        obf_path=repo_root / "references" / "pricing_baseline_v5.obf",
    )


def _product_catalog_path() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "references" / "product_catalog.md",
        Path("/opt/quanlaidian-quote/references/product_catalog.md"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise PricingError(message="未找到产品目录文件 product_catalog.md")


@router.post("/v1/quotes", response_model=QuoteCreated)
def create_quote_resource(
    form: QuoteForm,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    token_info: TokenInfo = Depends(verify_token(settings.data_root / "tokens.json")),
):
    """Price + persist only — no files. Idempotent per (org, form).

    Clients MAY supply an `Idempotency-Key` header for retry-safe creation.
    Replaying the same key with a different form returns 400 OUT_OF_RANGE.
    """
    request_id = _gen_request_id()
    request.state.request_id = request_id
    form_dict = form.model_dump()

    try:
        quote, approval, config = price_and_persist(
            form=form_dict,
            org=token_info.org,
            db_path=settings.data_root / "quote.db",
            baseline=_baseline(),
            product_catalog_path=_product_catalog_path(),
            idempotency_key=idempotency_key,
        )
    except ValueError as e:
        from app.errors import OutOfRangeError
        raise OutOfRangeError(field="Idempotency-Key", message=str(e))

    response.headers["X-Quote-ID"] = quote.id
    response.headers["Idempotency-Key"] = idempotency_key or quote.form_hash

    return QuoteCreated(
        request_id=request_id,
        quote_id=quote.id,
        preview=build_preview(config, form_dict),
        approval=approval_to_state(approval),
        pricing_version=pricing_version(),
    )


@router.get("/v1/quotes/{quote_id}", response_model=QuoteDetail)
def get_quote_resource(
    quote_id: str,
    request: Request,
    token_info: TokenInfo = Depends(verify_token(settings.data_root / "tokens.json")),
):
    request.state.request_id = _gen_request_id()
    try:
        quote = fetch_quote_or_404(settings.data_root / "quote.db", quote_id, token_info.org)
    except PricingError:
        raise NotFoundError("quote", quote_id)

    approval = fetch_approval(settings.data_root / "quote.db", quote_id)
    with get_conn(settings.data_root / "quote.db") as conn:
        renders = list_renders(conn, quote_id)

    form = json.loads(quote.form_json)
    config = json.loads(quote.config_json)

    renders_map: dict[str, FileRef] = {}
    for r in renders:
        renders_map.setdefault(r.format, render_to_file_ref(r, settings.api_base_url))

    return QuoteDetail(
        quote_id=quote.id,
        org=quote.org,
        preview=build_preview(config, form),
        approval=approval_to_state(approval),
        renders=renders_map,
        pricing_version=quote.pricing_version,
        created_at=quote.created_at,
    )


@router.post("/v1/quotes/{quote_id}/render/{format}", response_model=FileRef)
def render_quote_format(
    quote_id: str,
    format: str,
    request: Request,
    force: bool = False,
    token_info: TokenInfo = Depends(verify_token(settings.data_root / "tokens.json")),
):
    """Render on demand."""
    request.state.request_id = _gen_request_id()
    if format not in {"pdf", "xlsx", "json"}:
        raise NotFoundError("render-format", format)

    try:
        quote = fetch_quote_or_404(settings.data_root / "quote.db", quote_id, token_info.org)
    except PricingError:
        raise NotFoundError("quote", quote_id)

    render = render_format(
        quote=quote,
        format=format,
        db_path=settings.data_root / "quote.db",
        storage=_storage(),
        fonts_dir=settings.data_root / "fonts",
        force=force,
    )
    return render_to_file_ref(render, settings.api_base_url)


@router.post("/v1/quotes/{quote_id}/explain", response_model=QuoteExplain)
def explain_quote(
    quote_id: str,
    request: Request,
    token_info: TokenInfo = Depends(verify_token(settings.data_root / "tokens.json")),
):
    """Per-item cost/profit breakdown. Internal-use — shows wholesale cost."""
    request.state.request_id = _gen_request_id()
    try:
        quote = fetch_quote_or_404(settings.data_root / "quote.db", quote_id, token_info.org)
    except PricingError:
        raise NotFoundError("quote", quote_id)

    config = json.loads(quote.config_json)
    items = build_breakdown(config)
    totals = QuoteTotals(list=quote.total_list, final=quote.total_final)
    return QuoteExplain(
        quote_id=quote.id,
        items=items,
        totals=totals,
        pricing_info=config.get("pricing_info", {}),
        internal_financials=config.get("internal_financials", {}),
    )


