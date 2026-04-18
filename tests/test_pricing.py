import json
import pytest
from pathlib import Path
from app.domain.pricing import build_quotation_config, load_product_catalog
from app.domain.pricing_baseline import load_baseline

FIXTURES_DIR = Path(__file__).parent / "fixtures"
# Use the product catalog from the old repo
PRODUCT_CATALOG = Path("/Users/sqb/ai/quanlaidian-quotation-skill/references/product_catalog.md")


@pytest.fixture
def empty_baseline():
    return {"items": []}


def _load_form(name):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_light_meal_5_stores(empty_baseline):
    form = _load_form("form_light_meal_5_stores.json")
    config = build_quotation_config(form, empty_baseline, PRODUCT_CATALOG)
    assert config["餐饮类型"] == "轻餐"
    assert config["门店数量"] == 5
    assert config["客户信息"]["公司名称"] == "测试轻餐5店"
    assert len(config["报价项目"]) >= 1  # at least the package
    assert config["pricing_info"]["route_strategy"] == "small-segment"


def test_full_meal_10_stores(empty_baseline):
    form = _load_form("form_full_meal_10_stores.json")
    config = build_quotation_config(form, empty_baseline, PRODUCT_CATALOG)
    assert config["餐饮类型"] == "正餐"
    assert config["门店数量"] == 10
    assert len(config["报价项目"]) >= 2  # package + KDS module


def test_with_delivery_center(empty_baseline):
    form = _load_form("form_with_delivery_center.json")
    config = build_quotation_config(form, empty_baseline, PRODUCT_CATALOG)
    # Should have package + delivery center module
    item_names = [item["商品名称"] for item in config["报价项目"]]
    assert "配送中心" in item_names


def test_31_stores_rejected(empty_baseline):
    form = _load_form("form_light_meal_5_stores.json")
    form["门店数量"] = 31
    from app.errors import OutOfRangeError
    with pytest.raises((OutOfRangeError, ValueError)):
        build_quotation_config(form, empty_baseline, PRODUCT_CATALOG)


def test_config_structure(empty_baseline):
    """Verify the output config has all expected top-level keys"""
    form = _load_form("form_light_meal_5_stores.json")
    config = build_quotation_config(form, empty_baseline, PRODUCT_CATALOG)
    assert "客户信息" in config
    assert "报价日期" in config
    assert "报价项目" in config
    assert "pricing_info" in config
    assert "条款" in config
    assert "internal_financials" in config
