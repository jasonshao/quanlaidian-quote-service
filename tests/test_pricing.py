import json
import pytest
from pathlib import Path
from app.domain.pricing import build_quotation_config, load_product_catalog
from app.domain.pricing_baseline import (
    KEY_ENV,
    STRICT_ENV,
    decode_payload,
    encode_payload,
    load_baseline,
)

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


def test_load_baseline_missing_file_raises(tmp_path):
    """Missing baseline file must fail loudly, not silently fall back to empty items.

    Silent fallback previously caused fallback pricing (cost_price = catalog list),
    which combined with the cost-plus markup produced quote unit prices ABOVE list.
    """
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError):
        load_baseline(missing)


def _write_obf(path: Path, items, secret_key: str):
    plain = json.dumps({"items": items}, ensure_ascii=False)
    payload = encode_payload(plain, secret_key)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_encode_decode_roundtrip():
    original = '{"items": [{"name": "foo", "cost_price": 123.45}]}'
    payload = encode_payload(original, "test-key")
    assert payload["format"] == "pricing-baseline-obf-v1"
    assert decode_payload(payload, "test-key") == original


def test_load_baseline_decodes_obf(tmp_path, monkeypatch):
    obf = tmp_path / "baseline.obf"
    items = [{"meal_type": "正餐", "group": "总部模块", "name": "配送中心", "cost_price": 20000}]
    _write_obf(obf, items, "real-key")

    monkeypatch.setenv(KEY_ENV, "real-key")
    baseline = load_baseline(json_path=tmp_path / "missing.json", obf_path=obf)
    assert baseline["items"] == items


def test_load_baseline_strict_requires_key(tmp_path, monkeypatch):
    obf = tmp_path / "baseline.obf"
    _write_obf(obf, [], "real-key")
    monkeypatch.setenv(STRICT_ENV, "1")
    with pytest.raises(RuntimeError, match=KEY_ENV):
        load_baseline(json_path=tmp_path / "missing.json", obf_path=obf)


def test_load_baseline_strict_requires_obf_file(tmp_path, monkeypatch):
    monkeypatch.setenv(STRICT_ENV, "1")
    monkeypatch.setenv(KEY_ENV, "real-key")
    with pytest.raises(RuntimeError, match="混淆基线"):
        load_baseline(json_path=tmp_path / "missing.json", obf_path=tmp_path / "missing.obf")


def test_load_baseline_prefers_obf_over_plaintext(tmp_path, monkeypatch):
    obf = tmp_path / "baseline.obf"
    items = [{"name": "from_obf", "cost_price": 1}]
    _write_obf(obf, items, "real-key")

    plaintext = tmp_path / "baseline.json"
    plaintext.write_text(json.dumps({"items": [{"name": "from_plaintext", "cost_price": 2}]}), encoding="utf-8")

    monkeypatch.setenv(KEY_ENV, "real-key")
    baseline = load_baseline(json_path=plaintext, obf_path=obf)
    assert baseline["items"][0]["name"] == "from_obf"


def test_load_baseline_falls_back_to_plaintext_when_no_key(tmp_path):
    obf = tmp_path / "baseline.obf"
    _write_obf(obf, [{"name": "from_obf"}], "real-key")

    plaintext = tmp_path / "baseline.json"
    plaintext.write_text(json.dumps({"items": [{"name": "from_plaintext"}]}), encoding="utf-8")

    baseline = load_baseline(json_path=plaintext, obf_path=obf)
    assert baseline["items"][0]["name"] == "from_plaintext"


def test_module_unit_price_follows_markup_rule(empty_baseline):
    """门店增值模块 / 总部模块 商品单价 = 底价 × 固定倍数（毛利保护）.

    - 增值模块: cost × 1.20
    - 总部模块: cost × 1.50

    定价故意让商品单价可以高于"标准价"（= cost × 1.10 / 1.20），深度折扣只
    吸收在套餐上；增值/总部走成本加成。resolve_product_pricing 的 catalog
    fallback 分支会让 cost=目录标价，此时商品单价达到 120-150% of list，
    属于"基线漏收商品"的告警信号，不是算法 bug。
    """
    form = _load_form("form_with_delivery_center.json")
    config = build_quotation_config(form, empty_baseline, PRODUCT_CATALOG)
    expected_markup = {"门店增值模块": 1.20, "总部模块": 1.50}
    for item in config["报价项目"]:
        cat = item["模块分类"]
        if cat not in expected_markup or item.get("protected_item_bypass"):
            continue
        # 这里是 fallback 分支 (cost=目录价)：unit = 目录价 × markup
        expected = item["成本单价"] * expected_markup[cat]
        assert abs(item["商品单价"] - expected) < 0.01, (
            f"{item['商品名称']} ({cat}): unit {item['商品单价']} != "
            f"cost {item['成本单价']} × {expected_markup[cat]}"
        )
