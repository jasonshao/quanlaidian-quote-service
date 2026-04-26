"""Cross-consistency checks between VERSION, pyproject.toml, and CHANGELOG.md.

These three files are the contract for the project's release machinery; if
they drift out of sync someone forgot a step in the bump workflow. Failing
loudly here is cheaper than discovering it post-deploy via /healthz.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _read_version_file() -> str:
    return (REPO / "VERSION").read_text(encoding="utf-8").strip()


def test_version_file_is_semver():
    v = _read_version_file()
    assert re.fullmatch(r"\d+\.\d+\.\d+", v), (
        f"VERSION must be MAJOR.MINOR.PATCH, got {v!r}"
    )


def test_version_file_matches_pyproject():
    version_file = _read_version_file()
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert m, "pyproject.toml is missing `version = \"...\"`"
    assert m.group(1) == version_file, (
        f"VERSION ({version_file!r}) != pyproject.toml version ({m.group(1)!r}) — "
        "run scripts/bump_version.py to keep them in sync"
    )


def test_changelog_top_entry_matches_version():
    version_file = _read_version_file()
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^##\s+(\S+)\b", changelog, re.MULTILINE)
    assert m, "CHANGELOG.md has no `## X.Y.Z` heading"
    assert m.group(1) == version_file, (
        f"VERSION ({version_file!r}) != top CHANGELOG entry ({m.group(1)!r}) — "
        "every bump needs a CHANGELOG section with the same version number"
    )
