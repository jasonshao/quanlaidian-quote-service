import sqlite3

import pytest

from app.persistence import init_db
from app.persistence.quote_repo import (
    canonical_form_hash,
    create_quote,
    find_by_form_hash,
    get_quote,
    latest_render,
    persist_render,
    upsert_approval,
)


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "quote.db"
    init_db(p)
    return p


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.close()


@pytest.fixture
def sample_config():
    return {
        "报价项目": [
            {"商品名称": "套餐A", "标准价": 100, "数量": 10, "报价小计": 200},
        ],
        "internal_financials": {"quote_total": 200},
        "pricing_info": {"final_factor": 0.2},
    }


@pytest.fixture
def sample_form():
    return {
        "客户品牌名称": "品牌X",
        "餐饮类型": "轻餐",
        "门店数量": 10,
        "门店套餐": "轻餐连锁营销基础版",
    }


def test_canonical_hash_order_independent(sample_form):
    h1 = canonical_form_hash(sample_form)
    h2 = canonical_form_hash({k: v for k, v in reversed(list(sample_form.items()))})
    assert h1 == h2


def test_canonical_hash_value_sensitive(sample_form):
    other = dict(sample_form)
    other["门店数量"] = 11
    assert canonical_form_hash(sample_form) != canonical_form_hash(other)


def test_create_quote_roundtrip(conn, sample_form, sample_config):
    q = create_quote(conn, org="acme", form=sample_form, config=sample_config, pricing_version="v1")
    assert q.id.startswith("q_")
    assert q.org == "acme"
    assert q.total_final == 200
    assert q.factor == 0.2

    fetched = get_quote(conn, q.id)
    assert fetched is not None
    assert fetched.id == q.id
    assert fetched.total_final == 200


def test_create_quote_idempotent_per_org_form(conn, sample_form, sample_config):
    q1 = create_quote(conn, org="acme", form=sample_form, config=sample_config, pricing_version="v1")
    q2 = create_quote(conn, org="acme", form=sample_form, config=sample_config, pricing_version="v1")
    assert q1.id == q2.id


def test_create_quote_different_org_splits(conn, sample_form, sample_config):
    q_a = create_quote(conn, org="acme", form=sample_form, config=sample_config, pricing_version="v1")
    q_b = create_quote(conn, org="other", form=sample_form, config=sample_config, pricing_version="v1")
    assert q_a.id != q_b.id


def test_persist_and_latest_render(conn, sample_form, sample_config):
    q = create_quote(conn, org="acme", form=sample_form, config=sample_config, pricing_version="v1")
    persist_render(conn, quote_id=q.id, format="pdf", file_token="t1", filename="a.pdf", expires_at="2099-01-01")
    persist_render(conn, quote_id=q.id, format="xlsx", file_token="t2", filename="a.xlsx", expires_at="2099-01-01")
    pdf = latest_render(conn, q.id, "pdf")
    assert pdf is not None and pdf.file_token == "t1"


def test_approval_not_required_when_no_reasons(conn, sample_form, sample_config):
    """After approval flow removal, upsert_approval is only called with required=False."""
    q = create_quote(conn, org="acme", form=sample_form, config=sample_config, pricing_version="v1")
    approval = upsert_approval(conn, quote_id=q.id, required=False, reasons=[])
    assert approval.state == "not_required"
    assert approval.required is False
    assert approval.reasons == []


def test_find_by_form_hash(conn, sample_form, sample_config):
    q = create_quote(conn, org="acme", form=sample_form, config=sample_config, pricing_version="v1")
    form_hash = canonical_form_hash(sample_form)
    found = find_by_form_hash(conn, "acme", form_hash)
    assert found is not None and found.id == q.id

    miss = find_by_form_hash(conn, "other", form_hash)
    assert miss is None
