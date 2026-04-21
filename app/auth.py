"""Bearer-token authentication.

Tokens live in the `api_token` table of the service's SQLite DB. This module
provides a FastAPI dependency factory `verify_token(db_path)` that:

1. Parses `Authorization: Bearer <plaintext>`.
2. Looks up sha256(plaintext) in the table.
3. Rejects revoked / expired / unknown hashes with 401.
4. On success, updates `last_used_on` to today (day-sampled in-process so
   the same token authenticated multiple times the same day writes to the
   DB only once).

The `TokenInfo` returned to handlers carries `org` (for resource isolation)
and `token_id` (for audit trails).
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request

from app.persistence.db import get_conn
from app.persistence.token_repo import find_active_by_hash, hash_token, touch_last_used


@dataclass
class TokenInfo:
    org: str
    token_id: str


# In-process day-sample cache: set of (token_id, YYYY-MM-DD) pairs for which
# we've already written last_used_on today. Cleared when we see a new day.
#
# Single-process uvicorn (the deployment pattern here) means this cache is
# effective. Multi-worker deployments would see redundant writes — still
# bounded (at most one per worker per token per day), still acceptable.
_touched_today_lock = threading.Lock()
_touched_today: set[tuple[str, str]] = set()
_current_day: str | None = None


def _mark_touched(token_id: str, today: str) -> bool:
    """Return True if this is the first touch for (token_id, today) in
    this process. Caller writes to DB only if True."""
    global _current_day
    with _touched_today_lock:
        if _current_day != today:
            _touched_today.clear()
            _current_day = today
        key = (token_id, today)
        if key in _touched_today:
            return False
        _touched_today.add(key)
        return True


def verify_token(db_path: Path):
    """Return a FastAPI dependency that verifies Bearer tokens against
    `db_path`'s api_token table."""
    def _verify(request: Request) -> TokenInfo:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        plaintext = auth[7:]

        if not db_path.exists():
            raise HTTPException(status_code=401, detail="Unauthorized")

        token_hash = hash_token(plaintext)
        try:
            with get_conn(db_path) as conn:
                row = find_active_by_hash(conn, token_hash)
                if row is None:
                    raise HTTPException(status_code=401, detail="Unauthorized")

                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if _mark_touched(row.token_id, today):
                    touch_last_used(conn, row.token_id, today=today)

                return TokenInfo(org=row.org, token_id=row.token_id)
        except sqlite3.DatabaseError:
            # Corrupt / non-SQLite file at db_path → treat as auth failure
            # rather than leak a 500.
            raise HTTPException(status_code=401, detail="Unauthorized")

    return _verify
