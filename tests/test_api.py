import pytest

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

def test_quote_400_31_stores(api_client, sample_form):
    client, token = api_client
    sample_form["门店数量"] = 31
    resp = client.post(
        "/v1/quote",
        json=sample_form,
        headers={"Authorization": f"Bearer {token}"},
    )
    # Should be 400 OUT_OF_RANGE (via schema validation le=30 → 422)
    assert resp.status_code in (400, 422)

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
