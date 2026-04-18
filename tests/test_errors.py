import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from app.errors import (
    OutOfRangeError, PricingError, RenderError,
    register_exception_handlers,
)

@pytest.fixture
def app():
    app = FastAPI()
    register_exception_handlers(app)

    # Middleware to set request_id
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = "req_test123"
        response = await call_next(request)
        return response

    class StrictModel(BaseModel):
        count: int = Field(ge=1, le=30)

    @app.post("/test-validation")
    def test_validation(data: StrictModel):
        return {"ok": True}

    @app.get("/test-out-of-range")
    def test_oor():
        raise OutOfRangeError(field="门店数量", message="门店数量需在 1–30 之间", hint="31 店及以上请走人工报价")

    @app.get("/test-pricing-error")
    def test_pricing():
        raise PricingError(message="算法内部异常")

    @app.get("/test-render-error")
    def test_render():
        raise RenderError(message="PDF 生成失败")

    @app.get("/test-unhandled")
    def test_unhandled():
        raise RuntimeError("unexpected")

    return app

@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)

def test_out_of_range_returns_400(client):
    resp = client.get("/test-out-of-range")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "OUT_OF_RANGE"
    assert body["error"]["field"] == "门店数量"
    assert "request_id" in body["error"]

def test_validation_error_returns_422(client):
    resp = client.post("/test-validation", json={"count": 50})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "INVALID_FORM"
    assert "request_id" in body["error"]

def test_pricing_error_returns_500(client):
    resp = client.get("/test-pricing-error")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "PRICING_FAILED"

def test_render_error_returns_500(client):
    resp = client.get("/test-render-error")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "RENDER_FAILED"

def test_unhandled_error_returns_500(client):
    resp = client.get("/test-unhandled")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"

def test_all_errors_have_request_id(client):
    for path in ["/test-out-of-range", "/test-pricing-error", "/test-render-error", "/test-unhandled"]:
        resp = client.get(path)
        body = resp.json()
        assert "request_id" in body["error"], f"Missing request_id for {path}"
