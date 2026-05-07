"""CRUD for the api_token table.

Public surface:
    hash_token(plaintext)          → sha256 hex of the bearer token
    new_token_id()                 → 'tok_<8 hex>' identifier
    create_token(conn, ...)        → persist a new row, return ApiToken
    find_by_id(conn, token_id)     → ApiToken | None  (for CLI / revoke)
    find_active_by_hash(conn, h)   → ApiToken | None  (for auth; filters
                                      out revoked + expired)
    list_tokens(conn)              → list[ApiToken] (all rows; CLI filters
                                      token_hash before printing)
    revoke_token(conn, token_id)   → bool (True if row existed)
    touch_last_used(conn, id, day) → update last_used_on if not already
                                      today; day-sampled to minimise writes

Time is injected (`now=` / `today=`) for deterministic tests; timestamp
fields use UTC, while default day-sampled dates use UTC+08:00.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.persistence.models import ApiToken
from app.timezone import today_east8


def hash_token(plaintext: str) -> str:
    """Return sha256 hex of the bearer token plaintext.

    Used symmetrically at token creation (CLI) and verification (auth).
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def new_token_id() -> str:
    """Return 'tok_<8 hex>' — a short human-readable identifier.

    8 hex = 32 bits = ~4 billion ids. Collision probability against a
    population of 1000 tokens is < 10^-7; PRIMARY KEY would catch any
    collision with an IntegrityError, prompting a retry at the caller.
    """
    return f"tok_{secrets.token_hex(4)}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_token(
    conn: sqlite3.Connection,
    *,
    token_id: str,
    token_hash: str,
    org: str,
    created_at: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> ApiToken:
    created_at = created_at or _now_iso()
    conn.execute(
        """
        INSERT INTO api_token (token_id, token_hash, org, created_at, expires_at,
                               revoked_at, last_used_on)
        VALUES (?, ?, ?, ?, ?, NULL, NULL)
        """,
        (token_id, token_hash, org, created_at, expires_at),
    )
    return ApiToken(
        token_id=token_id,
        token_hash=token_hash,
        org=org,
        created_at=created_at,
        expires_at=expires_at,
        revoked_at=None,
        last_used_on=None,
    )


def find_by_id(conn: sqlite3.Connection, token_id: str) -> Optional[ApiToken]:
    row = conn.execute(
        "SELECT * FROM api_token WHERE token_id=?", (token_id,)
    ).fetchone()
    return _row_to_token(row) if row else None


def find_active_by_hash(
    conn: sqlite3.Connection,
    token_hash: str,
    *,
    now: Optional[str] = None,
) -> Optional[ApiToken]:
    """Return the token if it exists, is not revoked, and is not expired.

    `now` is ISO-8601 UTC; comparison is lexicographic, which is correct
    for ISO-8601 with fixed UTC offset.
    """
    now = now or _now_iso()
    row = conn.execute(
        """
        SELECT * FROM api_token
         WHERE token_hash = ?
           AND revoked_at IS NULL
           AND (expires_at IS NULL OR expires_at > ?)
        """,
        (token_hash, now),
    ).fetchone()
    return _row_to_token(row) if row else None


def list_tokens(conn: sqlite3.Connection) -> list[ApiToken]:
    rows = conn.execute(
        "SELECT * FROM api_token ORDER BY created_at ASC"
    ).fetchall()
    return [_row_to_token(r) for r in rows]


def revoke_token(
    conn: sqlite3.Connection,
    token_id: str,
    *,
    now: Optional[str] = None,
) -> bool:
    """Set revoked_at on the row. Returns True if a row was updated."""
    now = now or _now_iso()
    cur = conn.execute(
        "UPDATE api_token SET revoked_at = ? WHERE token_id = ?",
        (now, token_id),
    )
    return cur.rowcount > 0


def touch_last_used(
    conn: sqlite3.Connection,
    token_id: str,
    *,
    today: Optional[str] = None,
) -> None:
    """Update last_used_on to `today` iff it's not already `today`.

    Day-sampled: at most one write per token per UTC+08:00 day. Silent no-op
    if the token_id doesn't exist.
    """
    today = today or today_east8()
    conn.execute(
        """
        UPDATE api_token
           SET last_used_on = ?
         WHERE token_id = ?
           AND (last_used_on IS NULL OR last_used_on != ?)
        """,
        (today, token_id, today),
    )


def _row_to_token(row: sqlite3.Row) -> ApiToken:
    return ApiToken(
        token_id=row["token_id"],
        token_hash=row["token_hash"],
        org=row["org"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        last_used_on=row["last_used_on"],
    )
