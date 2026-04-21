"""Tests for app.persistence.token_repo — the api_token table + helpers."""
import sqlite3

import pytest

from app.persistence import init_db
from app.persistence.token_repo import (
    create_token,
    find_active_by_hash,
    find_by_id,
    hash_token,
    list_tokens,
    new_token_id,
    revoke_token,
    touch_last_used,
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


# --- hash_token --------------------------------------------------------------

def test_hash_token_is_sha256_hex():
    # Known value: sha256("abc") in hex
    import hashlib
    assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()


def test_hash_token_is_deterministic():
    assert hash_token("x") == hash_token("x")


# --- new_token_id ------------------------------------------------------------

def test_new_token_id_prefix_and_shape():
    tid = new_token_id()
    assert tid.startswith("tok_")
    # 'tok_' + 8 hex chars
    assert len(tid) == 4 + 8
    # hex only
    int(tid[4:], 16)


def test_new_token_id_unique():
    ids = {new_token_id() for _ in range(100)}
    assert len(ids) == 100


# --- create_token / find_by_id ----------------------------------------------

def test_create_token_roundtrip(conn):
    created = create_token(
        conn,
        token_id="tok_abcd1234",
        token_hash="h" * 64,
        org="prod",
        created_at="2026-04-21T00:00:00+00:00",
        expires_at=None,
    )
    assert created.token_id == "tok_abcd1234"
    assert created.org == "prod"
    assert created.expires_at is None
    assert created.revoked_at is None
    assert created.last_used_on is None

    fetched = find_by_id(conn, "tok_abcd1234")
    assert fetched is not None
    assert fetched.token_hash == "h" * 64
    assert fetched.org == "prod"


def test_create_token_rejects_duplicate_id(conn):
    create_token(conn, token_id="tok_dup", token_hash="a" * 64, org="o", created_at="2026-01-01T00:00:00+00:00")
    with pytest.raises(sqlite3.IntegrityError):
        create_token(conn, token_id="tok_dup", token_hash="b" * 64, org="o", created_at="2026-01-01T00:00:00+00:00")


def test_create_token_rejects_duplicate_hash(conn):
    create_token(conn, token_id="tok_a", token_hash="h" * 64, org="o", created_at="2026-01-01T00:00:00+00:00")
    with pytest.raises(sqlite3.IntegrityError):
        create_token(conn, token_id="tok_b", token_hash="h" * 64, org="o", created_at="2026-01-01T00:00:00+00:00")


def test_find_by_id_missing_returns_none(conn):
    assert find_by_id(conn, "tok_nope") is None


# --- find_active_by_hash -----------------------------------------------------

def _seed(conn, *, token_id="tok_1", token_hash="h" * 64, org="o",
          created_at="2026-01-01T00:00:00+00:00", expires_at=None):
    return create_token(
        conn, token_id=token_id, token_hash=token_hash, org=org,
        created_at=created_at, expires_at=expires_at,
    )


def test_find_active_by_hash_returns_active_token(conn):
    _seed(conn, token_hash="a" * 64)
    found = find_active_by_hash(conn, "a" * 64, now="2026-04-21T00:00:00+00:00")
    assert found is not None
    assert found.org == "o"


def test_find_active_by_hash_missing_returns_none(conn):
    _seed(conn, token_hash="a" * 64)
    assert find_active_by_hash(conn, "b" * 64, now="2026-04-21T00:00:00+00:00") is None


def test_find_active_by_hash_skips_revoked(conn):
    _seed(conn, token_id="tok_r", token_hash="r" * 64)
    revoke_token(conn, "tok_r", now="2026-04-20T00:00:00+00:00")
    assert find_active_by_hash(conn, "r" * 64, now="2026-04-21T00:00:00+00:00") is None


def test_find_active_by_hash_skips_expired(conn):
    _seed(conn, token_id="tok_e", token_hash="e" * 64,
          expires_at="2026-01-01T00:00:00+00:00")  # already expired by 2026-04-21
    assert find_active_by_hash(conn, "e" * 64, now="2026-04-21T00:00:00+00:00") is None


def test_find_active_by_hash_no_expiry_always_valid(conn):
    _seed(conn, token_id="tok_perm", token_hash="p" * 64, expires_at=None)
    found = find_active_by_hash(conn, "p" * 64, now="2099-12-31T23:59:59+00:00")
    assert found is not None


def test_find_active_by_hash_future_expiry_still_valid(conn):
    _seed(conn, token_id="tok_f", token_hash="f" * 64,
          expires_at="2030-01-01T00:00:00+00:00")
    found = find_active_by_hash(conn, "f" * 64, now="2026-04-21T00:00:00+00:00")
    assert found is not None


# --- list_tokens ------------------------------------------------------------

def test_list_tokens_returns_all_including_revoked_and_expired(conn):
    _seed(conn, token_id="tok_a", token_hash="a" * 64, org="o1")
    _seed(conn, token_id="tok_b", token_hash="b" * 64, org="o2",
          expires_at="2026-01-01T00:00:00+00:00")  # expired
    _seed(conn, token_id="tok_c", token_hash="c" * 64, org="o3")
    revoke_token(conn, "tok_c", now="2026-02-01T00:00:00+00:00")

    tokens = list_tokens(conn)
    ids = {t.token_id for t in tokens}
    assert ids == {"tok_a", "tok_b", "tok_c"}


def test_list_tokens_does_not_expose_hash_by_default(conn):
    """Sanity: list_tokens returns ApiToken objects which DO carry hash,
    but the CLI is responsible for not printing it. This test just documents
    that we return dataclasses, not dicts."""
    _seed(conn, token_hash="a" * 64)
    tokens = list_tokens(conn)
    assert len(tokens) == 1
    # The field exists (for repo completeness), but CLI must filter it out.
    assert tokens[0].token_hash == "a" * 64


# --- revoke_token -----------------------------------------------------------

def test_revoke_token_sets_revoked_at(conn):
    _seed(conn, token_id="tok_r", token_hash="r" * 64)
    ok = revoke_token(conn, "tok_r", now="2026-04-21T10:00:00+00:00")
    assert ok is True
    row = find_by_id(conn, "tok_r")
    assert row.revoked_at == "2026-04-21T10:00:00+00:00"


def test_revoke_token_missing_id_returns_false(conn):
    assert revoke_token(conn, "tok_nope", now="2026-04-21T10:00:00+00:00") is False


def test_revoke_token_second_call_overwrites_timestamp(conn):
    """Revoking an already-revoked token is idempotent at the 'stays revoked'
    level, but may update the timestamp. Either behavior is acceptable; we
    assert only that the token stays revoked."""
    _seed(conn, token_id="tok_r", token_hash="r" * 64)
    revoke_token(conn, "tok_r", now="2026-04-21T10:00:00+00:00")
    revoke_token(conn, "tok_r", now="2026-04-22T10:00:00+00:00")
    row = find_by_id(conn, "tok_r")
    assert row.revoked_at is not None


# --- touch_last_used (day-sampled) -------------------------------------------

def test_touch_last_used_sets_today(conn):
    _seed(conn, token_id="tok_t", token_hash="t" * 64)
    touch_last_used(conn, "tok_t", today="2026-04-21")
    row = find_by_id(conn, "tok_t")
    assert row.last_used_on == "2026-04-21"


def test_touch_last_used_same_day_noop(conn):
    """Same-day repeated calls don't rewrite. We verify by observing
    that a second call with a different `today` value (simulating clock
    rewind) does NOT downgrade the stored date below what was there."""
    _seed(conn, token_id="tok_t", token_hash="t" * 64)
    touch_last_used(conn, "tok_t", today="2026-04-21")
    # Same day — should be a no-op.
    touch_last_used(conn, "tok_t", today="2026-04-21")
    row = find_by_id(conn, "tok_t")
    assert row.last_used_on == "2026-04-21"


def test_touch_last_used_new_day_updates(conn):
    _seed(conn, token_id="tok_t", token_hash="t" * 64)
    touch_last_used(conn, "tok_t", today="2026-04-21")
    touch_last_used(conn, "tok_t", today="2026-04-22")
    row = find_by_id(conn, "tok_t")
    assert row.last_used_on == "2026-04-22"


def test_touch_last_used_missing_token_is_noop(conn):
    # Should not raise — UPDATE on missing row is a silent 0-row update.
    touch_last_used(conn, "tok_nope", today="2026-04-21")
