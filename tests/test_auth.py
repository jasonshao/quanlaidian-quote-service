"""Tests for app.auth.verify_token — DB-backed bearer auth."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import TokenInfo, verify_token
from app.persistence import init_db, get_conn
from app.persistence.token_repo import (
    create_token,
    find_by_id,
    hash_token,
    new_token_id,
)


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "quote.db"
    init_db(p)
    return p


@pytest.fixture
def app_with_auth(db_path):
    """Minimal FastAPI app exposing a protected endpoint.

    Also includes an endpoint that echoes TokenInfo so we can assert
    token_id flows through to handlers.
    """
    app = FastAPI()

    @app.get("/protected")
    def protected(token_info: TokenInfo = Depends(verify_token(db_path))):
        return {"org": token_info.org, "token_id": token_info.token_id}

    return app


def _seed_token(db_path, *, org="test-org", expires_at=None, revoked=False,
                plaintext=None, token_id=None):
    """Insert a token into the test DB and return (plaintext, token_id)."""
    plaintext = plaintext or "test-token-abc123"
    token_id = token_id or new_token_id()
    h = hash_token(plaintext)
    with get_conn(db_path) as conn:
        create_token(
            conn,
            token_id=token_id,
            token_hash=h,
            org=org,
            expires_at=expires_at,
        )
        if revoked:
            from app.persistence.token_repo import revoke_token
            revoke_token(conn, token_id)
    return plaintext, token_id


@pytest.fixture
def active_token(db_path):
    plaintext, token_id = _seed_token(db_path)
    return plaintext, token_id


# --- Bearer parsing ----------------------------------------------------------


def test_valid_token_passes(app_with_auth, active_token):
    plaintext, token_id = active_token
    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["org"] == "test-org"
    assert body["token_id"] == token_id


def test_missing_auth_header_returns_401(app_with_auth):
    client = TestClient(app_with_auth)
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_wrong_token_returns_401(app_with_auth, active_token):
    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_malformed_auth_header_returns_401(app_with_auth, active_token):
    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": "Basic abc123"})
    assert resp.status_code == 401


# --- Revocation / expiry -----------------------------------------------------


def test_revoked_token_returns_401(app_with_auth, db_path):
    plaintext, _ = _seed_token(db_path, revoked=True)
    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 401


def test_expired_token_returns_401(app_with_auth, db_path):
    plaintext, _ = _seed_token(db_path, expires_at="2020-01-01T00:00:00+00:00")
    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 401


def test_non_expired_token_passes(app_with_auth, db_path):
    plaintext, _ = _seed_token(db_path, expires_at="2099-01-01T00:00:00+00:00")
    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 200


def test_missing_db_file_returns_401(tmp_path):
    """Graceful 401 when the DB doesn't exist yet (e.g. fresh install)."""
    missing = tmp_path / "does-not-exist.db"
    app = FastAPI()

    @app.get("/p")
    def p(t: TokenInfo = Depends(verify_token(missing))):
        return {"org": t.org}

    client = TestClient(app)
    resp = client.get("/p", headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 401


# --- last_used_on side effect ------------------------------------------------


def test_successful_auth_updates_last_used_on(app_with_auth, db_path, active_token):
    plaintext, token_id = active_token
    # Before: last_used_on is None
    with get_conn(db_path) as conn:
        assert find_by_id(conn, token_id).last_used_on is None

    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 200

    with get_conn(db_path) as conn:
        row = find_by_id(conn, token_id)
    # Must be a YYYY-MM-DD string now.
    assert row.last_used_on is not None
    assert len(row.last_used_on) == 10
    assert row.last_used_on[4] == "-" and row.last_used_on[7] == "-"


def test_failed_auth_does_not_update_last_used_on(app_with_auth, db_path, active_token):
    _, token_id = active_token
    client = TestClient(app_with_auth)
    client.get("/protected", headers={"Authorization": "Bearer garbage"})
    with get_conn(db_path) as conn:
        assert find_by_id(conn, token_id).last_used_on is None
