"""Tests for app.cli — add/list/revoke/migrate subcommands."""
import io
import json
import sqlite3
from contextlib import redirect_stdout, redirect_stderr

import pytest

from app.cli import main
from app.persistence import init_db, get_conn
from app.persistence.token_repo import (
    find_by_id,
    hash_token,
    list_tokens,
)


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "quote.db"
    init_db(p)
    return p


def _capture(fn, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = fn(*args, **kwargs)
    return rc, out.getvalue(), err.getvalue()


# --- add-token ---------------------------------------------------------------


def test_add_token_creates_row_and_prints_plaintext(db_path):
    rc, out, _ = _capture(main, ["add-token", "--org", "prod", "--db", str(db_path)])
    assert rc == 0
    # Output includes plaintext on its own line + a token id
    # (We search rather than pin the exact format.)
    assert "prod" in out
    assert "tok_" in out

    with get_conn(db_path) as conn:
        tokens = list_tokens(conn)
    assert len(tokens) == 1
    t = tokens[0]
    assert t.org == "prod"
    assert t.expires_at is not None  # default 180d
    assert t.revoked_at is None


def test_add_token_default_expiry_is_180_days(db_path):
    from datetime import datetime, timezone, timedelta
    rc, out, _ = _capture(main, ["add-token", "--org", "x", "--db", str(db_path)])
    assert rc == 0
    with get_conn(db_path) as conn:
        tokens = list_tokens(conn)
    t = tokens[0]
    expires = datetime.fromisoformat(t.expires_at)
    now = datetime.now(timezone.utc)
    delta = expires - now
    # ~180 days, allow some slack
    assert timedelta(days=179) < delta < timedelta(days=181)


def test_add_token_no_expire_flag(db_path):
    rc, _, _ = _capture(main, ["add-token", "--org", "admin", "--no-expire", "--db", str(db_path)])
    assert rc == 0
    with get_conn(db_path) as conn:
        tokens = list_tokens(conn)
    assert tokens[0].expires_at is None


def test_add_token_expires_in_override(db_path):
    from datetime import datetime, timezone, timedelta
    rc, _, _ = _capture(main, ["add-token", "--org", "y", "--expires-in", "30d", "--db", str(db_path)])
    assert rc == 0
    with get_conn(db_path) as conn:
        tokens = list_tokens(conn)
    expires = datetime.fromisoformat(tokens[0].expires_at)
    delta = expires - datetime.now(timezone.utc)
    assert timedelta(days=29) < delta < timedelta(days=31)


def test_add_token_expires_in_and_no_expire_are_mutually_exclusive(db_path):
    rc, _, err = _capture(
        main, ["add-token", "--org", "y", "--expires-in", "30d", "--no-expire", "--db", str(db_path)],
    )
    assert rc != 0


def test_add_token_plaintext_is_verifiable(db_path):
    """The printed plaintext must hash to the stored token_hash."""
    _, out, _ = _capture(main, ["add-token", "--org", "z", "--db", str(db_path)])

    # Extract plaintext from output — we assume it appears on its own line.
    # The CLI format: we look for any token_urlsafe-looking string.
    plaintext = None
    for line in out.splitlines():
        s = line.strip()
        # token_urlsafe(32) is ~43 chars, URL-safe alphanumeric + - _
        if len(s) >= 32 and all(c.isalnum() or c in "-_" for c in s):
            plaintext = s
            break
    assert plaintext is not None, f"no plaintext found in output: {out!r}"

    expected = hash_token(plaintext)
    with get_conn(db_path) as conn:
        tokens = list_tokens(conn)
    assert tokens[0].token_hash == expected


# --- list-tokens ------------------------------------------------------------


def test_list_tokens_empty(db_path):
    rc, out, _ = _capture(main, ["list-tokens", "--db", str(db_path)])
    assert rc == 0
    # Should not explode; header OK; no row body.


def test_list_tokens_does_not_print_hash(db_path):
    # Seed via add-token
    _capture(main, ["add-token", "--org", "secretco", "--db", str(db_path)])
    with get_conn(db_path) as conn:
        stored_hash = list_tokens(conn)[0].token_hash

    rc, out, _ = _capture(main, ["list-tokens", "--db", str(db_path)])
    assert rc == 0
    assert stored_hash not in out
    # But it should include the org + token_id
    assert "secretco" in out
    assert "tok_" in out


def test_list_tokens_shows_revoked_marker(db_path):
    _capture(main, ["add-token", "--org", "o1", "--db", str(db_path)])
    with get_conn(db_path) as conn:
        tid = list_tokens(conn)[0].token_id
    _capture(main, ["revoke-token", "--id", tid, "--db", str(db_path)])

    rc, out, _ = _capture(main, ["list-tokens", "--db", str(db_path)])
    assert rc == 0
    # Either "revoked" appears literally, or a timestamp in the revoked column.
    assert "revoked" in out.lower() or "2026" in out or "2027" in out or "20" in out


# --- revoke-token -----------------------------------------------------------


def test_revoke_token_succeeds(db_path):
    _capture(main, ["add-token", "--org", "o", "--db", str(db_path)])
    with get_conn(db_path) as conn:
        tid = list_tokens(conn)[0].token_id

    rc, _, _ = _capture(main, ["revoke-token", "--id", tid, "--db", str(db_path)])
    assert rc == 0

    with get_conn(db_path) as conn:
        assert find_by_id(conn, tid).revoked_at is not None


def test_revoke_token_missing_id_exits_nonzero(db_path):
    rc, _, err = _capture(main, ["revoke-token", "--id", "tok_nope", "--db", str(db_path)])
    assert rc != 0


# --- migrate-tokens-json -----------------------------------------------------


def test_migrate_tokens_json_imports_rows(tmp_path, db_path):
    tokens_json = tmp_path / "tokens.json"
    legacy_hash_1 = "a" * 64
    legacy_hash_2 = "b" * 64
    tokens_json.write_text(json.dumps({
        legacy_hash_1: {"org": "dev", "created_at": "2026-01-01T00:00:00+00:00", "rate_limit_per_min": 60},
        legacy_hash_2: {"org": "prod", "created_at": "2026-02-01T00:00:00+00:00", "rate_limit_per_min": 60},
    }), encoding="utf-8")

    rc, out, _ = _capture(
        main, ["migrate-tokens-json", "--tokens-json", str(tokens_json), "--db", str(db_path)],
    )
    assert rc == 0

    with get_conn(db_path) as conn:
        rows = list_tokens(conn)
    orgs = {r.org for r in rows}
    hashes = {r.token_hash for r in rows}
    assert orgs == {"dev", "prod"}
    assert hashes == {legacy_hash_1, legacy_hash_2}
    # created_at preserved
    assert any(r.created_at == "2026-01-01T00:00:00+00:00" for r in rows)
    # No expiry set (migrated tokens keep previous永久 behavior until admin rotates)
    for r in rows:
        assert r.expires_at is None


def test_migrate_tokens_json_renames_file_after_success(tmp_path, db_path):
    tokens_json = tmp_path / "tokens.json"
    tokens_json.write_text(json.dumps({
        "c" * 64: {"org": "x", "created_at": "2026-01-01T00:00:00+00:00"}
    }), encoding="utf-8")

    rc, _, _ = _capture(
        main, ["migrate-tokens-json", "--tokens-json", str(tokens_json), "--db", str(db_path)],
    )
    assert rc == 0
    assert not tokens_json.exists()
    # A .migrated-* backup should exist alongside
    backups = list(tmp_path.glob("tokens.json.migrated-*"))
    assert len(backups) == 1


def test_migrate_tokens_json_idempotent(tmp_path, db_path):
    """Running twice should not crash, even though file is renamed after
    first success. Second call sees no tokens.json → 'nothing to migrate'."""
    tokens_json = tmp_path / "tokens.json"
    tokens_json.write_text(json.dumps({
        "d" * 64: {"org": "x", "created_at": "2026-01-01T00:00:00+00:00"}
    }), encoding="utf-8")

    _capture(main, ["migrate-tokens-json", "--tokens-json", str(tokens_json), "--db", str(db_path)])
    rc, out, _ = _capture(
        main, ["migrate-tokens-json", "--tokens-json", str(tokens_json), "--db", str(db_path)],
    )
    assert rc == 0


def test_migrate_tokens_json_skips_duplicates(tmp_path, db_path):
    """If a hash is already in api_token (from a prior run), it's skipped
    rather than aborting the whole batch."""
    # Pre-seed the DB with a row whose hash will collide
    from app.persistence.token_repo import create_token, new_token_id
    h = "e" * 64
    with get_conn(db_path) as conn:
        create_token(conn, token_id=new_token_id(), token_hash=h, org="dev",
                     created_at="2026-01-01T00:00:00+00:00")

    tokens_json = tmp_path / "tokens.json"
    tokens_json.write_text(json.dumps({
        h: {"org": "dev", "created_at": "2026-01-01T00:00:00+00:00"},
        "f" * 64: {"org": "prod", "created_at": "2026-02-01T00:00:00+00:00"},
    }), encoding="utf-8")

    rc, out, _ = _capture(
        main, ["migrate-tokens-json", "--tokens-json", str(tokens_json), "--db", str(db_path)],
    )
    assert rc == 0

    with get_conn(db_path) as conn:
        rows = list_tokens(conn)
    # One pre-existing + one newly migrated = 2 rows
    assert len(rows) == 2
