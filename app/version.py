"""Service version exposed via /healthz.

Source of truth is the repository-root VERSION file. We read it lazily and
cache the result — VERSION cannot change at runtime (deploy is a cold restart),
so the cache is safe.
"""
from functools import lru_cache
from pathlib import Path

_VERSION_PATH = Path(__file__).resolve().parent.parent / "VERSION"


@lru_cache(maxsize=1)
def service_version() -> str:
    try:
        return _VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
