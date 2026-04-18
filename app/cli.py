"""CLI for token management. Usage: python -m app.cli add-token --org demo-org"""
import argparse
import hashlib
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


def add_token(org: str, tokens_path: Path | None = None):
    if tokens_path is None:
        tokens_path = settings.data_root / "tokens.json"

    plaintext = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plaintext.encode()).hexdigest()

    if tokens_path.exists():
        tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
    else:
        tokens_path.parent.mkdir(parents=True, exist_ok=True)
        tokens = {}

    tokens[token_hash] = {
        "org": org,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rate_limit_per_min": 60,
    }
    tokens_path.write_text(json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Token created for org '{org}':")
    print(f"  {plaintext}")
    print(f"  (This is the only time the token will be shown)")


def main():
    parser = argparse.ArgumentParser(description="Quanlaidian Quote Service CLI")
    sub = parser.add_subparsers(dest="command")

    add_cmd = sub.add_parser("add-token", help="Create a new API token")
    add_cmd.add_argument("--org", required=True, help="Organization name")

    args = parser.parse_args()
    if args.command == "add-token":
        add_token(args.org)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
