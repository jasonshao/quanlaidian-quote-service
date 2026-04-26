#!/usr/bin/env python3
"""bump_version.py — bump VERSION + sync pyproject.toml + insert CHANGELOG stub.

Usage:
    python3 scripts/bump_version.py --level {major,minor,patch}
    python3 scripts/bump_version.py --set X.Y.Z
    python3 scripts/bump_version.py --level patch --dry-run

Always run from the repo root or anywhere — it resolves the repo root via
this script's location.

Workflow after running this:
    1. Edit CHANGELOG.md, fill in the new version's bullet points (each
       prefixed with "[#PR号]" where applicable).
    2. git add VERSION pyproject.toml CHANGELOG.md
    3. git commit -m "chore: bump to X.Y.Z"

This script does NOT git-add / commit / tag — that stays manual so you can
review the CHANGELOG body before publishing.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO / "VERSION"
PYPROJECT = REPO / "pyproject.toml"
CHANGELOG = REPO / "CHANGELOG.md"

CHANGELOG_STUB = """## {version} ({date})

### Features

-

### Fixes

-

"""


def _read_version() -> tuple[int, int, int]:
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    parts = raw.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"VERSION file content {raw!r} is not X.Y.Z")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def _next_version(current: tuple[int, int, int], level: str) -> str:
    major, minor, patch = current
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"unknown level {level!r}")


def _validate_explicit(version: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"--set value {version!r} is not X.Y.Z")
    return version


def _patch_pyproject(new_version: str) -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise SystemExit("pyproject.toml: could not locate `version = \"...\"` line")
    return new_text


def _insert_changelog_stub(new_version: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    today = _dt.date.today().isoformat()
    stub = CHANGELOG_STUB.format(version=new_version, date=today)
    # Insert before the first existing "## " heading.
    m = re.search(r"^##\s", text, re.MULTILINE)
    if not m:
        # No existing entries — append after the document's intro paragraph.
        return text.rstrip() + "\n\n" + stub
    return text[: m.start()] + stub + text[m.start() :]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--level", choices=["major", "minor", "patch"])
    grp.add_argument("--set", dest="explicit", metavar="X.Y.Z")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the planned changes, do not write any files")
    args = ap.parse_args()

    current = _read_version()
    if args.explicit:
        new_version = _validate_explicit(args.explicit)
    else:
        new_version = _next_version(current, args.level)

    current_str = ".".join(str(x) for x in current)
    print(f"VERSION:        {current_str} → {new_version}")

    new_pyproject = _patch_pyproject(new_version)
    new_changelog = _insert_changelog_stub(new_version)

    if args.dry_run:
        print(f"pyproject.toml: would update version line")
        print(f"CHANGELOG.md:   would insert stub for {new_version}")
        print()
        print("--- CHANGELOG stub preview ---")
        today = _dt.date.today().isoformat()
        print(CHANGELOG_STUB.format(version=new_version, date=today).rstrip())
        return 0

    VERSION_FILE.write_text(new_version + "\n", encoding="utf-8")
    PYPROJECT.write_text(new_pyproject, encoding="utf-8")
    CHANGELOG.write_text(new_changelog, encoding="utf-8")

    print()
    print("Done. Next steps:")
    print(f"  1. Edit {CHANGELOG.relative_to(REPO)} — fill in bullets under {new_version}")
    print(f"  2. git add VERSION pyproject.toml CHANGELOG.md")
    print(f"  3. git commit -m 'chore: bump to {new_version}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
