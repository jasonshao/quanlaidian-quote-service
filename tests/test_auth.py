import hashlib
import json
import pytest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import verify_token, TokenInfo

@pytest.fixture
def tokens_file(tmp_path):
    return tmp_path / "tokens.json"

@pytest.fixture
def app_with_auth(tokens_file):
    """Create a minimal FastAPI app with auth dependency for testing"""
    from fastapi import Depends
    app = FastAPI()

    @app.get("/protected")
    def protected(token_info: TokenInfo = Depends(verify_token(tokens_file))):
        return {"org": token_info.org}

    return app

@pytest.fixture
def client_with_token(app_with_auth, tokens_file):
    """Set up a valid token and return (client, token_plaintext)"""
    plaintext = "test-token-abc123"
    token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    tokens_file.write_text(json.dumps({
        token_hash: {"org": "test-org", "created_at": "2026-01-01T00:00:00Z", "rate_limit_per_min": 60}
    }))
    client = TestClient(app_with_auth)
    return client, plaintext

def test_valid_token_passes(client_with_token):
    client, token = client_with_token
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["org"] == "test-org"

def test_missing_token_returns_401(app_with_auth):
    client = TestClient(app_with_auth)
    resp = client.get("/protected")
    assert resp.status_code == 401

def test_wrong_token_returns_401(client_with_token):
    client, _ = client_with_token
    resp = client.get("/protected", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401

def test_malformed_auth_header_returns_401(client_with_token):
    client, _ = client_with_token
    resp = client.get("/protected", headers={"Authorization": "Basic abc123"})
    assert resp.status_code == 401

def test_add_token_cli(tmp_path):
    from app.cli import add_token
    tokens_path = tmp_path / "tokens.json"
    # Just verify it creates the file and doesn't crash
    import io, contextlib
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        add_token("demo-org", tokens_path=tokens_path)
    output = f.getvalue()
    assert "demo-org" in output
    assert tokens_path.exists()
    tokens = json.loads(tokens_path.read_text())
    assert len(tokens) == 1
    stored = list(tokens.values())[0]
    assert stored["org"] == "demo-org"
