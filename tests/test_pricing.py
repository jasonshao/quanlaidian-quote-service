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


def test_301_stores_rejected(empty_baseline):
    """边界搬:31+ 现在走大客户段(tier 对比),只有 301+ 拒绝。"""
    form = _load_form("form_light_meal_5_stores.json")
    form["门店数量"] = 301
    from app.errors import OutOfRangeError
    with pytest.raises((OutOfRangeError, ValueError)):
        build_quotation_config(form, empty_baseline, PRODUCT_CATALOG)


def test_large_segment_150_stores_pricing_info(empty_baseline):
    """150 店走大客户段: pricing_info 标记 route=large-segment, effective=100(tier 下锚)。"""
    form = _load_form("form_light_meal_5_stores.json")
    form["门店数量"] = 150
    config = build_quotation_config(form, empty_baseline, PRODUCT_CATALOG)
    pi = config["pricing_info"]
    assert pi["route_strategy"] == "large-segment"
    assert pi["algorithm_version"] == "large-segment-v1"
    assert pi["original_requested_store_count"] == 150
    assert pi["effective_store_count"] == 100


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


# ============================================================================
# Large-segment (31-300 stores) tests — independent of product_catalog fixture.
# ============================================================================


class TestLargeSegmentFactors:
    """Anchor factors at 50/100/200/300 stores."""

    def test_factor_light_50(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert recommend_base_deal_price_factor_smooth(50, "轻餐") == 0.15

    def test_factor_full_50(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert recommend_base_deal_price_factor_smooth(50, "正餐") == 0.18

    def test_factor_light_100(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert recommend_base_deal_price_factor_smooth(100, "轻餐") == 0.13

    def test_factor_full_100(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert recommend_base_deal_price_factor_smooth(100, "正餐") == 0.16

    def test_factor_light_200(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert recommend_base_deal_price_factor_smooth(200, "轻餐") == 0.12

    def test_factor_full_200(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert recommend_base_deal_price_factor_smooth(200, "正餐") == 0.14

    def test_factor_light_300(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert recommend_base_deal_price_factor_smooth(300, "轻餐") == 0.11

    def test_factor_full_300(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert recommend_base_deal_price_factor_smooth(300, "正餐") == 0.13


class TestSmallSegmentRegression:
    """Pin 1-30 curve values so large-segment changes don't silently alter old segment."""

    def test_factor_1_store_full(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        # start_factor = 3000 / 11120
        assert abs(recommend_base_deal_price_factor_smooth(1, "正餐") - 3000 / 11120) < 1e-9

    def test_factor_1_store_light(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert abs(recommend_base_deal_price_factor_smooth(1, "轻餐") - 1800 / 7600) < 1e-9

    def test_factor_20_stores_full(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        assert abs(recommend_base_deal_price_factor_smooth(20, "正餐") - (3000 / 11120 - 0.05)) < 1e-9

    def test_factor_30_stores_full(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth, round_factor
        # 20 店因子 - 10 × step; 现有公式末端 ≈ 0.1936
        assert round_factor(recommend_base_deal_price_factor_smooth(30, "正餐")) == 0.19

    def test_factor_30_stores_light(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth, round_factor
        assert round_factor(recommend_base_deal_price_factor_smooth(30, "轻餐")) == 0.16


class TestLargeSegmentNonAnchorRejected:
    """31-300 non-anchor values must not be fed into factor function — factor is only
    defined at anchors. Large-segment code path picks an anchor via resolve_tier_window."""

    def test_31_stores_raises(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        with pytest.raises(ValueError):
            recommend_base_deal_price_factor_smooth(31, "正餐")

    def test_56_stores_raises(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        with pytest.raises(ValueError):
            recommend_base_deal_price_factor_smooth(56, "正餐")

    def test_150_stores_raises(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        with pytest.raises(ValueError):
            recommend_base_deal_price_factor_smooth(150, "轻餐")

    def test_301_stores_raises_out_of_range(self):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        from app.errors import OutOfRangeError
        with pytest.raises(OutOfRangeError):
            recommend_base_deal_price_factor_smooth(301, "正餐")


class TestResolveTierWindow:
    """resolve_tier_window(n) — picks the [lower, upper] anchor pair covering n."""

    def test_30_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(30) == [30, 50]

    def test_31_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(31) == [30, 50]

    def test_50_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(50) == [50, 100]

    def test_56_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(56) == [50, 100]

    def test_99_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(99) == [50, 100]

    def test_100_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(100) == [100, 200]

    def test_150_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(150) == [100, 200]

    def test_199_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(199) == [100, 200]

    def test_200_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(200) == [200, 300]

    def test_250_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(250) == [200, 300]

    def test_300_stores(self):
        from app.domain.pricing import resolve_tier_window
        assert resolve_tier_window(300) == [200, 300]

    def test_301_stores_raises(self):
        from app.domain.pricing import resolve_tier_window
        from app.errors import OutOfRangeError
        with pytest.raises(OutOfRangeError):
            resolve_tier_window(301)

    def test_29_stores_raises(self):
        """< 30 不应该走 tier window(属于 small-segment 单点)"""
        from app.domain.pricing import resolve_tier_window
        with pytest.raises(ValueError):
            resolve_tier_window(29)


class TestBuildTierConfigLargeSegment:
    """build_tier_config with store_count >=31 generates 2-tier comparison,
    ignoring the enabled flag."""

    def test_56_stores_gives_50_100_tiers_full(self):
        from app.domain.pricing import build_tier_config
        tiers = build_tier_config(False, "正餐", 56)  # enabled=False, but >=31 forces tiers
        assert [t["门店数"] for t in tiers] == [50, 100]
        assert tiers[0]["成交价系数"] == 0.18
        assert tiers[1]["成交价系数"] == 0.16

    def test_56_stores_gives_50_100_tiers_light(self):
        from app.domain.pricing import build_tier_config
        tiers = build_tier_config(False, "轻餐", 56)
        assert [t["门店数"] for t in tiers] == [50, 100]
        assert tiers[0]["成交价系数"] == 0.15
        assert tiers[1]["成交价系数"] == 0.13

    def test_250_stores_gives_200_300_tiers(self):
        from app.domain.pricing import build_tier_config
        tiers = build_tier_config(False, "正餐", 250)
        assert [t["门店数"] for t in tiers] == [200, 300]

    def test_small_segment_enabled_still_10_20_30(self):
        """≤30 + enabled=True: 保留现状 [10, 20, 30]"""
        from app.domain.pricing import build_tier_config
        tiers = build_tier_config(True, "正餐", 15)
        assert [t["门店数"] for t in tiers] == [10, 20, 30]

    def test_small_segment_disabled_returns_empty(self):
        """≤30 + enabled=False: 保留现状 no tiers"""
        from app.domain.pricing import build_tier_config
        assert build_tier_config(False, "正餐", 15) == []


class TestFactorMonotonic:
    """因子随门店数严格单调递减(全段,含锚点和 1-30 段)"""

    @pytest.mark.parametrize("meal_type", ["轻餐", "正餐"])
    def test_monotonic_small_segment(self, meal_type):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        factors = [recommend_base_deal_price_factor_smooth(n, meal_type) for n in range(1, 31)]
        for i in range(len(factors) - 1):
            assert factors[i] > factors[i + 1], (
                f"{meal_type} non-monotonic at n={i + 1} → n={i + 2}: "
                f"{factors[i]} ≤ {factors[i + 1]}"
            )

    @pytest.mark.parametrize("meal_type", ["轻餐", "正餐"])
    def test_monotonic_anchors(self, meal_type):
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        anchors = [50, 100, 200, 300]
        factors = [recommend_base_deal_price_factor_smooth(n, meal_type) for n in anchors]
        for i in range(len(factors) - 1):
            assert factors[i] > factors[i + 1], (
                f"{meal_type} anchors non-monotonic {anchors[i]}→{anchors[i + 1]}"
            )

    @pytest.mark.parametrize("meal_type", ["轻餐", "正餐"])
    def test_30_to_50_is_descending(self, meal_type):
        """30 店(公式末端)到 50 店(锚点)必须单调递减"""
        from app.domain.pricing import recommend_base_deal_price_factor_smooth
        f30 = recommend_base_deal_price_factor_smooth(30, meal_type)
        f50 = recommend_base_deal_price_factor_smooth(50, meal_type)
        assert f30 > f50, f"{meal_type}: 30 店 {f30} 应 > 50 店 {f50}"


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


# ============================================================
# 功能说明 & 附加说明 (new feature)
# ============================================================
REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_CATALOG = REPO_ROOT / "references" / "product_catalog.md"
LOCAL_DESCRIPTIONS = REPO_ROOT / "references" / "product_descriptions.json"


def _load_descriptions():
    from app.domain.product_descriptions import load_descriptions
    return load_descriptions(LOCAL_DESCRIPTIONS)


def test_build_quote_item_includes_description_field():
    from app.domain.pricing import build_quote_item
    product = {"name": "X", "unit": "店/年", "meal_type": "轻餐", "group": "门店增值模块"}
    item = build_quote_item(product, 100, 50, 1, 1.0, "增值模块", "门店增值模块", description="hello")
    assert item["功能说明"] == "hello"


def test_build_quote_item_description_defaults_to_empty():
    from app.domain.pricing import build_quote_item
    product = {"name": "X", "unit": "店/年", "meal_type": "轻餐", "group": "门店增值模块"}
    item = build_quote_item(product, 100, 50, 1, 1.0, "增值模块", "门店增值模块")
    assert item["功能说明"] == ""


def test_build_quotation_config_attaches_descriptions(empty_baseline):
    form = _load_form("form_light_meal_5_stores.json")
    desc = _load_descriptions()
    config = build_quotation_config(form, empty_baseline, LOCAL_CATALOG, descriptions=desc)
    # Every line item should carry a 功能说明 key (possibly empty, but present).
    for item in config["报价项目"]:
        assert "功能说明" in item
    # The package row has sub-rows (子项), so its own 功能说明 is cleared and
    # each sub-row carries the individual module description instead.
    first = config["报价项目"][0]
    if first["子项"]:
        assert first["功能说明"] == ""
        for sub in first["子项"]:
            assert sub.get("功能说明"), f"sub-row {sub.get('商品名称')} missing 功能说明"
    else:
        assert first["功能说明"], f"expected non-empty 功能说明 for {first['商品名称']}"


def test_build_quotation_config_expands_package_into_sub_items(empty_baseline):
    form = _load_form("form_light_meal_5_stores.json")
    desc = _load_descriptions()
    config = build_quotation_config(form, empty_baseline, LOCAL_CATALOG, descriptions=desc)
    package_item = config["报价项目"][0]
    assert package_item["模块分类"] == "门店软件套餐"
    assert len(package_item["子项"]) >= 3  # 轻餐标准/基础版 includes 3~4 modules
    names = {sub["商品名称"] for sub in package_item["子项"]}
    assert any("点餐收银" in n or "商户中心" in n for n in names)


def test_build_quotation_config_attaches_annotation(empty_baseline):
    form = _load_form("form_light_meal_5_stores.json")
    desc = _load_descriptions()
    config = build_quotation_config(form, empty_baseline, LOCAL_CATALOG, descriptions=desc)
    assert "附加说明" in config
    blocks = config["附加说明"]
    assert any(b and b.get("title") == "权益类自助充值模块" for b in blocks)
    block = next(b for b in blocks if b.get("title") == "权益类自助充值模块")
    joined = "\n".join(block["text_lines"])
    assert "0.039" in joined and "0.032" in joined and "0.021" in joined


def test_build_quotation_config_without_descriptions_skips_annotation(empty_baseline):
    form = _load_form("form_light_meal_5_stores.json")
    config = build_quotation_config(form, empty_baseline, LOCAL_CATALOG)
    assert "附加说明" not in config
    for item in config["报价项目"]:
        assert item["功能说明"] == ""
        assert item["子项"] == []
