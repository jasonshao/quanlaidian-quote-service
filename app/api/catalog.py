"""Product catalog endpoint — single source of truth for skill clients.

Parses references/product_catalog.md into structured JSON so skill repos can
consume it via HTTP instead of shipping their own copy of the md file. Pricing
drift between skill preview and service reality is eliminated at the source.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.auth import TokenInfo, verify_token
from app.config import settings
from app.domain.pricing import load_product_catalog
from app.domain.pricing_baseline import pricing_version
from app.errors import NotFoundError, PricingError

router = APIRouter()


def _product_catalog_path() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "references" / "product_catalog.md",
        Path("/opt/quanlaidian-quote/references/product_catalog.md"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise PricingError(message="未找到产品目录文件 product_catalog.md")


@router.get("/v1/catalog")
def get_catalog(
    request: Request,
    meal_type: str | None = None,
    token_info: TokenInfo = Depends(verify_token(settings.data_root / "quote.db")),
):
    """Return product list parsed from product_catalog.md.

    Query params:
      meal_type: "轻餐" | "正餐" | None (all)

    Response:
      {
        "pricing_version": "small-segment-v2.3",
        "meal_type": "正餐" | null,
        "items": [{meal_type, group, name, unit, price (or "赠送")}...]
      }
    """
    if meal_type is not None and meal_type not in {"轻餐", "正餐"}:
        raise NotFoundError("meal_type", meal_type)

    products = load_product_catalog(_product_catalog_path())
    if meal_type is not None:
        products = [p for p in products if p["meal_type"] in {meal_type, "通用"}]

    return {
        "pricing_version": pricing_version(),
        "meal_type": meal_type,
        "items": products,
    }
