import pytest

def test_catalog_returns_products(api_client):
    client, token = api_client
    resp = client.get("/v1/catalog", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["pricing_version"]
    assert len(body["items"]) >= 10
    names = {p["name"] for p in body["items"]}
    assert "正餐连锁营销旗舰版" in names or "轻餐连锁营销旗舰版" in names


def test_catalog_filter_by_meal_type(api_client):
    client, token = api_client
    resp = client.get("/v1/catalog?meal_type=正餐", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["meal_type"] == "正餐"
    # only 正餐 or 通用 items
    meal_types = {p["meal_type"] for p in body["items"]}
    assert meal_types.issubset({"正餐", "通用"})


def test_catalog_invalid_meal_type_404(api_client):
    client, token = api_client
    resp = client.get(
        "/v1/catalog?meal_type=不存在", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


def test_catalog_requires_auth(api_client):
    client, _ = api_client
    resp = client.get("/v1/catalog")
    assert resp.status_code == 401


def test_healthz(api_client):
    client, _ = api_client
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "pricing_version" in body

def test_quote_200_returns_files(api_client, sample_form):
    client, token = api_client
    resp = client.post(
        "/v1/quote",
        json=sample_form,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "request_id" in body
    assert "preview" in body
    assert "files" in body
    assert "pdf" in body["files"]
    assert "xlsx" in body["files"]
    assert "json" in body["files"]
    # Check preview fields
    assert body["preview"]["brand"] == "集成测试品牌"
    assert body["preview"]["stores"] == 5
    assert body["pricing_version"] is not None

def test_quote_400_factor_without_reason(api_client, sample_form):
    """Regression for issue #1: providing 成交价系数 without 人工改价原因
    must return 400 OUT_OF_RANGE, not 500 INTERNAL_ERROR."""
    client, token = api_client
    sample_form["成交价系数"] = 0.25
    resp = client.post(
        "/v1/quote",
        json=sample_form,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["error"]["code"] == "OUT_OF_RANGE"
    assert body["error"]["field"] == "人工改价原因"

def test_quote_manual_factor_no_approval_gate(api_client, sample_form):
    """Manual 成交价系数 (even 0.25 for new client) must NOT trigger approval.

    As of 2026-04-20, approval gating was removed by business decision — the
    system outputs files directly regardless of the factor. Legacy /v1/quote
    must return 200 with files, never 409 APPROVAL_PENDING.
    """
    client, token = api_client
    sample_form["成交价系数"] = 0.25
    sample_form["人工改价原因"] = "总部战略客户"
    resp = client.post(
        "/v1/quote",
        json=sample_form,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["files"].keys()) == {"pdf", "xlsx", "json"}


def test_new_quotes_renders_without_approval(api_client, sample_form):
    """Resource-oriented: POST /v1/quotes always state=not_required, render OK."""
    client, token = api_client
    sample_form["成交价系数"] = 0.25
    sample_form["人工改价原因"] = "总部战略客户"
    auth = {"Authorization": f"Bearer {token}"}

    r = client.post("/v1/quotes", json=sample_form, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    qid = body["quote_id"]
    assert body["approval"]["state"] == "not_required"
    assert body["approval"]["required"] is False

    rendered = client.post(f"/v1/quotes/{qid}/render/pdf", headers=auth)
    assert rendered.status_code == 200
    assert rendered.json()["filename"].endswith(".pdf")


def test_quote_explain_returns_cost_and_margin(api_client, sample_form):
    client, token = api_client
    auth = {"Authorization": f"Bearer {token}"}
    created = client.post("/v1/quotes", json=sample_form, headers=auth)
    assert created.status_code == 200
    qid = created.json()["quote_id"]

    explain = client.post(f"/v1/quotes/{qid}/explain", headers=auth)
    assert explain.status_code == 200
    body = explain.json()
    assert body["quote_id"] == qid
    assert len(body["items"]) >= 1
    # explain surfaces internal cost/margin fields
    item = body["items"][0]
    assert "cost_unit_price" in item
    assert "margin_pct" in item


def test_quote_get_after_create(api_client, sample_form):
    client, token = api_client
    auth = {"Authorization": f"Bearer {token}"}
    created = client.post("/v1/quotes", json=sample_form, headers=auth)
    qid = created.json()["quote_id"]

    fetched = client.get(f"/v1/quotes/{qid}", headers=auth)
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["quote_id"] == qid
    assert body["preview"]["stores"] == sample_form["门店数量"]


def test_quotes_idempotency_key_header_dedups(api_client, sample_form):
    """Two POSTs with same Idempotency-Key + same form = one quote."""
    import sqlite3
    client, token = api_client
    auth = {"Authorization": f"Bearer {token}", "Idempotency-Key": "client-uuid-abc"}
    r1 = client.post("/v1/quotes", json=sample_form, headers=auth)
    r2 = client.post("/v1/quotes", json=sample_form, headers=auth)
    assert r1.json()["quote_id"] == r2.json()["quote_id"]


def test_quotes_idempotency_key_replay_with_different_form_rejected(api_client, sample_form):
    """Same key + different form = 400 (client bug)."""
    client, token = api_client
    auth = {"Authorization": f"Bearer {token}", "Idempotency-Key": "client-uuid-xyz"}
    r1 = client.post("/v1/quotes", json=sample_form, headers=auth)
    assert r1.status_code == 200

    different = dict(sample_form)
    different["门店数量"] = 7
    r2 = client.post("/v1/quotes", json=different, headers=auth)
    assert r2.status_code == 400
    assert r2.json()["error"]["field"] == "Idempotency-Key"


def test_quote_get_cross_org_is_404(api_client, sample_form):
    """Quotes are org-scoped: another org's id returns 404."""
    client, token = api_client
    auth = {"Authorization": f"Bearer {token}"}
    client.post("/v1/quotes", json=sample_form, headers=auth)

    resp = client.get("/v1/quotes/q_nonexistent_0000", headers=auth)
    assert resp.status_code == 404

def test_quote_401_missing_token(api_client, sample_form):
    client, _ = api_client
    resp = client.post("/v1/quote", json=sample_form)
    assert resp.status_code == 401

def test_quote_401_wrong_token(api_client, sample_form):
    client, _ = api_client
    resp = client.post(
        "/v1/quote",
        json=sample_form,
        headers={"Authorization": "Bearer wrong-token-xyz"},
    )
    assert resp.status_code == 401

def test_quote_422_invalid_form(api_client):
    client, token = api_client
    # Missing required fields
    resp = client.post(
        "/v1/quote",
        json={"客户品牌名称": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "INVALID_FORM"

def test_quote_31_stores_rejected_at_schema_layer(api_client, sample_form):
    """31+ stores must be rejected.

    Two-layer defense: Pydantic schema (le=30, returns 422) is the outer
    guard; pricing layer's OutOfRangeError (returns 400) is an inner guard
    covered by tests/test_pricing.py::test_31_stores_rejected. If the
    schema constraint ever drops, this test switches to 400 and the
    pricing layer catches the request — either way 31 stores never
    succeeds.
    """
    client, token = api_client
    sample_form["门店数量"] = 31
    resp = client.post(
        "/v1/quote",
        json=sample_form,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "INVALID_FORM"

def test_quote_persists_to_db(api_client, sample_form, test_data_root):
    """POST /v1/quote must write a row to quote + 3 renders + approval row."""
    import sqlite3
    client, token = api_client
    resp = client.post(
        "/v1/quote",
        json=sample_form,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    db = sqlite3.connect(str(test_data_root / "quote.db"))
    try:
        quotes = db.execute("SELECT id, org, total_final FROM quote").fetchall()
        assert len(quotes) == 1
        quote_id = quotes[0][0]
        assert quotes[0][1] == "test-org"

        renders = db.execute(
            "SELECT format FROM quote_render WHERE quote_id=?", (quote_id,)
        ).fetchall()
        assert sorted(r[0] for r in renders) == ["json", "pdf", "xlsx"]

        approvals = db.execute(
            "SELECT state FROM approval WHERE quote_id=?", (quote_id,)
        ).fetchall()
        assert len(approvals) == 1
        assert approvals[0][0] == "not_required"
    finally:
        db.close()


def test_quote_same_form_is_idempotent(api_client, sample_form, test_data_root):
    """Two identical POSTs must produce one DB row (idempotency)."""
    import sqlite3
    client, token = api_client
    for _ in range(2):
        resp = client.post(
            "/v1/quote",
            json=sample_form,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
    db = sqlite3.connect(str(test_data_root / "quote.db"))
    try:
        count = db.execute("SELECT count(*) FROM quote").fetchone()[0]
        assert count == 1
    finally:
        db.close()


def test_quote_200_29_stores(api_client, sample_form):
    client, token = api_client
    sample_form["门店数量"] = 29
    resp = client.post(
        "/v1/quote",
        json=sample_form,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["preview"]["stores"] == 29
