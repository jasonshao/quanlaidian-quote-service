import json
from pathlib import Path

import pytest

from app.domain.product_descriptions import (
    get_annotation_block,
    get_description,
    get_package_contents,
    load_descriptions,
)


EMPTY_ENVELOPE = {"descriptions": {}, "annotations": {}, "package_contents": {}}


@pytest.fixture
def sample_map():
    return {
        "descriptions": {
            "轻餐|轻餐连锁标准版": "一体化收银",
            "轻餐|宴秘书标准版套餐": "宴席预定",
            "正餐|厨房KDS": "正餐版 KDS",
        },
        "annotations": {
            "权益类自助充值模块": {
                "category": "短信与聚合外卖",
                "text_lines": ["* 短信充值说明", "* 外卖通道费说明"],
            }
        },
    }


def test_load_descriptions_missing_path_returns_empty_envelope():
    data = load_descriptions(Path("/tmp/nonexistent-descriptions.json"))
    assert data == EMPTY_ENVELOPE


def test_load_descriptions_none_path():
    assert load_descriptions(None) == EMPTY_ENVELOPE


def test_load_descriptions_reads_json(tmp_path):
    fp = tmp_path / "d.json"
    fp.write_text(json.dumps({"descriptions": {"a|b": "c"}, "annotations": {}}), encoding="utf-8")
    data = load_descriptions(fp)
    assert data["descriptions"] == {"a|b": "c"}


def test_load_descriptions_malformed(tmp_path):
    fp = tmp_path / "bad.json"
    fp.write_text("{not json", encoding="utf-8")
    assert load_descriptions(fp) == EMPTY_ENVELOPE


def test_get_description_exact_hit(sample_map):
    assert get_description(sample_map, "轻餐", "轻餐连锁标准版") == "一体化收银"


def test_get_description_miss_returns_empty(sample_map):
    assert get_description(sample_map, "轻餐", "不存在的模块") == ""


def test_get_description_normalizes_full_width_parens(sample_map):
    # caller passes full-width parens, map stores half-width
    sample_map["descriptions"]["正餐|易订套餐(win/安卓)"] = "易订"
    assert get_description(sample_map, "正餐", "易订套餐（win/安卓）") == "易订"


def test_get_description_strips_trailing_parenthesized_suffix(sample_map):
    sample_map["descriptions"]["正餐|宴秘书标准版套餐"] = "宴席 (with suffix)"
    # xlsx sometimes has the suffix in the name
    assert get_description(sample_map, "正餐", "宴秘书标准版套餐(标准版)") == "宴席 (with suffix)"


def test_get_description_empty_map():
    assert get_description({}, "轻餐", "anything") == ""
    assert get_description(None, "轻餐", "anything") == ""


def test_get_annotation_block_hit(sample_map):
    block = get_annotation_block(sample_map, "权益类自助充值模块")
    assert block is not None
    assert block["title"] == "权益类自助充值模块"
    assert block["category"] == "短信与聚合外卖"
    assert block["text_lines"] == ["* 短信充值说明", "* 外卖通道费说明"]


def test_get_annotation_block_miss(sample_map):
    assert get_annotation_block(sample_map, "不存在的块") is None


def test_get_annotation_block_empty_text_lines(sample_map):
    sample_map["annotations"]["空块"] = {"category": "x", "text_lines": []}
    assert get_annotation_block(sample_map, "空块") is None


def test_get_package_contents_hit():
    desc_map = {
        "package_contents": {
            "轻餐|轻餐连锁营销基础版": [
                {"商品分类": "商户中心", "商品名称": "商户中心-轻餐版", "单位": "店/年", "功能说明": "品牌组织"},
                {"商品分类": "收银系统", "商品名称": "点餐收银", "单位": "店/年", "功能说明": "先付后吃"},
            ]
        }
    }
    subs = get_package_contents(desc_map, "轻餐", "轻餐连锁营销基础版")
    assert len(subs) == 2
    assert subs[0]["商品名称"] == "商户中心-轻餐版"
    assert subs[1]["功能说明"] == "先付后吃"


def test_get_package_contents_miss():
    assert get_package_contents({"package_contents": {}}, "轻餐", "不存在") == []


def test_get_package_contents_normalizes_parens():
    desc_map = {
        "package_contents": {
            "正餐|易订套餐(win/安卓)": [
                {"商品分类": "预定系统", "商品名称": "易订", "单位": "店/年", "功能说明": "PC 版"},
            ]
        }
    }
    # caller uses full-width parens
    subs = get_package_contents(desc_map, "正餐", "易订套餐（win/安卓）")
    assert len(subs) == 1
    assert subs[0]["商品名称"] == "易订"


def test_get_package_contents_strips_trailing_suffix():
    desc_map = {
        "package_contents": {
            "正餐|宴秘书标准版套餐": [
                {"商品分类": "预定系统", "商品名称": "宴秘书", "单位": "店/年", "功能说明": "包房预定"},
            ]
        }
    }
    subs = get_package_contents(desc_map, "正餐", "宴秘书标准版套餐(标准版)")
    assert len(subs) == 1


def test_get_package_contents_empty_map():
    assert get_package_contents({}, "轻餐", "anything") == []
    assert get_package_contents(None, "轻餐", "anything") == []
