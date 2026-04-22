import pytest
import types
from datetime import datetime, timezone, timedelta
from app.storage import LocalDiskStorage, OssStorage
from app.domain.quote_service import render_to_file_ref
from app.persistence.models import QuoteRender

@pytest.fixture
def storage(tmp_path):
    return LocalDiskStorage(root=tmp_path, base_url="https://example.com", ttl_days=7)

def test_save_creates_file(storage, tmp_path):
    url, expires_at, token = storage.save("test.pdf", b"hello pdf")
    files = list(tmp_path.rglob("test.pdf"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"hello pdf"

def test_save_returns_url_with_token(storage):
    url, _, token = storage.save("report.pdf", b"data")
    assert "https://example.com/files/" in url
    assert "report.pdf" in url
    parts = url.split("/files/")[1].split("/")
    assert len(parts) == 2
    assert parts[0] == token
    assert len(token) > 20

def test_save_returns_correct_expiry(storage):
    _, expires_at, _ = storage.save("test.pdf", b"data")
    expected = datetime.now(timezone.utc) + timedelta(days=7)
    assert abs((expires_at - expected).total_seconds()) < 5

def test_save_unique_tokens(storage):
    _, _, token1 = storage.save("a.pdf", b"data1")
    _, _, token2 = storage.save("b.pdf", b"data2")
    assert token1 != token2


def test_oss_storage_save_returns_signed_url(monkeypatch):
    calls = {}

    class FakeBucket:
        def __init__(self, auth, endpoint, bucket_name):
            calls["bucket_name"] = bucket_name
            calls["endpoint"] = endpoint

        def put_object(self, key, content):
            calls["put_key"] = key
            calls["put_size"] = len(content)

        def sign_url(self, method, key, expires_in):
            calls["sign_method"] = method
            calls["sign_key"] = key
            calls["expires_in"] = expires_in
            return f"https://private-wosai-statics.oss-cn-hangzhou.aliyuncs.com/{key}?signed=1"

    fake_oss2 = types.SimpleNamespace(
        Auth=lambda *_args, **_kwargs: object(),
        Bucket=FakeBucket,
    )
    monkeypatch.setitem(__import__("sys").modules, "oss2", fake_oss2)

    storage = OssStorage(
        endpoint="oss-cn-hangzhou.aliyuncs.com",
        bucket_name="private-wosai-statics",
        access_key_id="ak",
        access_key_secret="sk",
        prefix="quanlaidian-quote",
        public_base_url="https://private-resource.shouqianba.com",
        ttl_days=7,
    )
    url, expires_at, token = storage.save("quote.pdf", b"hello")

    assert calls["bucket_name"] == "private-wosai-statics"
    assert calls["endpoint"] == "https://oss-cn-hangzhou.aliyuncs.com"
    assert calls["put_key"].startswith("quanlaidian-quote/")
    assert calls["put_key"].endswith("/quote.pdf")
    assert calls["put_size"] == 5
    assert calls["sign_method"] == "GET"
    assert calls["sign_key"] == calls["put_key"]
    assert calls["expires_in"] > 0
    assert token == calls["put_key"]
    assert url.startswith("https://private-resource.shouqianba.com/")
    expected = datetime.now(timezone.utc) + timedelta(days=7)
    assert abs((expires_at - expected).total_seconds()) < 5


def test_render_to_file_ref_refreshes_oss_signed_url(monkeypatch):
    class FakeBucket:
        def __init__(self, *_args, **_kwargs):
            pass

        def sign_url(self, _method, key, _expires_in):
            return f"https://private-wosai-statics.oss-cn-hangzhou.aliyuncs.com/{key}?fresh=1"

    fake_oss2 = types.SimpleNamespace(
        Auth=lambda *_args, **_kwargs: object(),
        Bucket=FakeBucket,
    )
    monkeypatch.setitem(__import__("sys").modules, "oss2", fake_oss2)

    storage = OssStorage(
        endpoint="oss-cn-hangzhou.aliyuncs.com",
        bucket_name="private-wosai-statics",
        access_key_id="ak",
        access_key_secret="sk",
        prefix="quanlaidian-quote",
        public_base_url="https://private-resource.shouqianba.com",
        ttl_days=7,
    )
    render = QuoteRender(
        id="r1",
        quote_id="q1",
        format="pdf",
        file_token="quanlaidian-quote/token/quote.pdf",
        filename="quote.pdf",
        created_at=datetime.now(timezone.utc).isoformat(),
        expires_at="2000-01-01T00:00:00+00:00",
    )
    file_ref = render_to_file_ref(render, "https://api.example.com", storage)
    assert file_ref.url.startswith("https://private-resource.shouqianba.com/")
    assert "fresh=1" in file_ref.url
    assert file_ref.expires_at > datetime.now(timezone.utc)
