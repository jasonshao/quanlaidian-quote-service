#!/usr/bin/env python3
"""
Obfuscate a plaintext pricing baseline JSON into a .obf file.

Use when baseline costs change: extract fresh plaintext from xlsx
(via ops/extract_baseline_from_xlsx.py), then re-obfuscate with this tool
using the same PRICING_BASELINE_KEY.
"""
import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.pricing_baseline import KEY_ENV, encode_payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Obfuscate plaintext pricing baseline JSON into .obf format"
    )
    parser.add_argument("--input", required=True, help="Plaintext baseline JSON path")
    parser.add_argument("--output", required=True, help="Output .obf path")
    parser.add_argument("--key", help=f"Secret key (or set env {KEY_ENV})")
    args = parser.parse_args(argv)

    secret_key = args.key or os.getenv(KEY_ENV)
    if not secret_key:
        print(f"Error: missing key. Pass --key or set {KEY_ENV}", file=sys.stderr)
        return 1

    src = Path(args.input)
    dst = Path(args.output)
    if not src.exists():
        print(f"Error: input not found: {src}", file=sys.stderr)
        return 1
    dst.parent.mkdir(parents=True, exist_ok=True)

    plain = src.read_text(encoding="utf-8")
    payload = encode_payload(plain, secret_key)
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote obfuscated baseline: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
