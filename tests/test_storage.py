import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from app.storage import LocalDiskStorage

@pytest.fixture
def storage(tmp_path):
    return LocalDiskStorage(root=tmp_path, base_url="https://example.com", ttl_days=7)

def test_save_creates_file(storage, tmp_path):
    url, expires_at = storage.save("test.pdf", b"hello pdf")
    # Find the file on disk (it's under a random token dir)
    files = list(tmp_path.rglob("test.pdf"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"hello pdf"

def test_save_returns_url_with_token(storage):
    url, _ = storage.save("report.pdf", b"data")
    assert "https://example.com/files/" in url
    assert "report.pdf" in url
    # URL should have a token segment between /files/ and /filename
    parts = url.split("/files/")[1].split("/")
    assert len(parts) == 2  # token/filename
    assert len(parts[0]) > 20  # token is long enough

def test_save_returns_correct_expiry(storage):
    _, expires_at = storage.save("test.pdf", b"data")
    expected = datetime.now(timezone.utc) + timedelta(days=7)
    assert abs((expires_at - expected).total_seconds()) < 5

def test_save_unique_tokens(storage):
    url1, _ = storage.save("a.pdf", b"data1")
    url2, _ = storage.save("b.pdf", b"data2")
    token1 = url1.split("/files/")[1].split("/")[0]
    token2 = url2.split("/files/")[1].split("/")[0]
    assert token1 != token2
