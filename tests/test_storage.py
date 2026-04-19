import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from app.storage import LocalDiskStorage

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
