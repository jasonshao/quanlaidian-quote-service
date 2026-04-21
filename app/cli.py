"""CLI for token management.

Usage:
    python -m app.cli add-token --org <name> [--expires-in 180d | --no-expire]
    python -m app.cli list-tokens
    python -m app.cli revoke-token --id tok_xxxxxxxx
    python -m app.cli migrate-tokens-json

Tokens live in the `api_token` table of the service's SQLite DB
(default: `data/quote.db`, overridable with `--db`). The CLI never
prints `token_hash` for existing tokens — only the plaintext, once,
at creation time.

`migrate-tokens-json` imports an existing `data/tokens.json` (legacy
format, key = sha256 hex, value = {org, created_at, ...}) into the
table and renames the file to `tokens.json.migrated-<ts>` once done.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

from app.config import settings
from app.persistence.db import get_conn, init_db
from app.persistence.token_repo import (
    create_token,
    find_by_id,
    hash_token,
    list_tokens,
    new_token_id,
    revoke_token,
)


# --- helpers ----------------------------------------------------------------


_DURATION_RE = re.compile(r"^(\d+)d$")


def _parse_duration_to_days(s: str) -> int:
    m = _DURATION_RE.match(s)
    if not m:
        raise ValueError(f"invalid duration {s!r} (expected e.g. '180d')")
    return int(m.group(1))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_offset(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _resolve_db_path(args) -> Path:
    if getattr(args, "db", None):
        return Path(args.db)
    return settings.data_root / "quote.db"


# --- subcommands ------------------------------------------------------------


def cmd_add_token(args) -> int:
    if args.expires_in and args.no_expire:
        print("error: --expires-in and --no-expire are mutually exclusive", file=sys.stderr)
        return 2

    if args.no_expire:
        expires_at: Optional[str] = None
    else:
        days = _parse_duration_to_days(args.expires_in) if args.expires_in else 180
        expires_at = _iso_offset(days)

    plaintext = secrets.token_urlsafe(32)
    token_id = new_token_id()
    token_hash = hash_token(plaintext)

    db_path = _resolve_db_path(args)
    init_db(db_path)  # ensure schema exists (idempotent)
    with get_conn(db_path) as conn:
        # On the (astronomically rare) id collision, retry once.
        try:
            create_token(
                conn, token_id=token_id, token_hash=token_hash, org=args.org,
                created_at=_iso_now(), expires_at=expires_at,
            )
        except sqlite3.IntegrityError:
            token_id = new_token_id()
            create_token(
                conn, token_id=token_id, token_hash=token_hash, org=args.org,
                created_at=_iso_now(), expires_at=expires_at,
            )

    print(f"Token created for org '{args.org}':")
    print(f"  token_id: {token_id}")
    print(f"  plaintext (shown only once, save it now):")
    print(f"  {plaintext}")
    if expires_at:
        print(f"  expires_at: {expires_at}")
    else:
        print(f"  expires_at: (never)")
    return 0


def cmd_list_tokens(args) -> int:
    db_path = _resolve_db_path(args)
    init_db(db_path)
    with get_conn(db_path) as conn:
        tokens = list_tokens(conn)

    if not tokens:
        print("(no tokens)")
        return 0

    # Header
    print(f"{'TOKEN_ID':<14} {'ORG':<16} {'CREATED':<28} {'EXPIRES':<28} {'STATUS':<20} {'LAST_USED':<12}")
    now = _iso_now()
    for t in tokens:
        if t.revoked_at:
            status = f"revoked@{t.revoked_at[:10]}"
        elif t.expires_at and t.expires_at <= now:
            status = "expired"
        else:
            status = "active"
        print(
            f"{t.token_id:<14} "
            f"{t.org:<16} "
            f"{t.created_at:<28} "
            f"{(t.expires_at or '(never)'):<28} "
            f"{status:<20} "
            f"{(t.last_used_on or '-'):<12}"
        )
    return 0


def cmd_revoke_token(args) -> int:
    db_path = _resolve_db_path(args)
    init_db(db_path)
    with get_conn(db_path) as conn:
        existing = find_by_id(conn, args.id)
        if existing is None:
            print(f"error: no token with id {args.id!r}", file=sys.stderr)
            return 1
        if existing.revoked_at:
            print(f"note: token {args.id} was already revoked at {existing.revoked_at}", file=sys.stderr)
        revoke_token(conn, args.id)
    print(f"Revoked {args.id}")
    return 0


def cmd_migrate_tokens_json(args) -> int:
    """Read legacy data/tokens.json → api_token table, rename file after success."""
    tokens_json = Path(args.tokens_json) if args.tokens_json else settings.data_root / "tokens.json"
    db_path = _resolve_db_path(args)
    init_db(db_path)

    if not tokens_json.exists():
        print(f"nothing to migrate (no {tokens_json})")
        return 0

    try:
        raw = json.loads(tokens_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: {tokens_json} is not valid JSON: {e}", file=sys.stderr)
        return 1

    if not isinstance(raw, dict):
        print(f"error: {tokens_json} is not a JSON object", file=sys.stderr)
        return 1

    migrated = 0
    skipped = 0
    with get_conn(db_path) as conn:
        for legacy_hash, info in raw.items():
            if not isinstance(info, dict):
                continue
            org = info.get("org")
            if not org:
                continue
            created_at = info.get("created_at", _iso_now())
            # Detect duplicates by looking up the hash.
            existing = conn.execute(
                "SELECT token_id FROM api_token WHERE token_hash = ?",
                (legacy_hash,),
            ).fetchone()
            if existing is not None:
                skipped += 1
                continue
            try:
                create_token(
                    conn,
                    token_id=new_token_id(),
                    token_hash=legacy_hash,
                    org=org,
                    created_at=created_at,
                    expires_at=None,  # migrated tokens keep permanent status until rotated
                )
                migrated += 1
            except sqlite3.IntegrityError:
                # Rare token_id collision — retry once.
                create_token(
                    conn,
                    token_id=new_token_id(),
                    token_hash=legacy_hash,
                    org=org,
                    created_at=created_at,
                    expires_at=None,
                )
                migrated += 1

    # Rename file so a re-run is a no-op.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = tokens_json.with_name(f"{tokens_json.name}.migrated-{ts}")
    tokens_json.rename(backup)

    print(f"migrated {migrated} token(s), skipped {skipped} duplicate(s)")
    print(f"legacy file renamed: {tokens_json} → {backup}")
    return 0


# --- entry point ------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Quanlaidian Quote Service CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add-token", help="Create a new API token")
    add.add_argument("--org", required=True, help="Organization name")
    add.add_argument("--expires-in", help="Expiry duration, e.g. '180d'. Default: 180d")
    add.add_argument("--no-expire", action="store_true", help="Token never expires")
    add.add_argument("--db", help="Path to quote.db (default: settings.data_root / 'quote.db')")
    add.set_defaults(func=cmd_add_token)

    lst = sub.add_parser("list-tokens", help="List all tokens (does NOT print hashes)")
    lst.add_argument("--db", help="Path to quote.db")
    lst.set_defaults(func=cmd_list_tokens)

    rev = sub.add_parser("revoke-token", help="Revoke a token by id")
    rev.add_argument("--id", required=True, help="token_id (e.g. tok_a3f9c1b2)")
    rev.add_argument("--db", help="Path to quote.db")
    rev.set_defaults(func=cmd_revoke_token)

    mig = sub.add_parser("migrate-tokens-json", help="Import legacy data/tokens.json into api_token table")
    mig.add_argument("--tokens-json", help="Path to legacy tokens.json (default: settings.data_root / 'tokens.json')")
    mig.add_argument("--db", help="Path to quote.db")
    mig.set_defaults(func=cmd_migrate_tokens_json)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
