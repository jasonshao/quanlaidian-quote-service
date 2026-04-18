import json
from pathlib import Path

_PRICING_VERSION = "small-segment-v2.3"


def load_baseline(path: Path) -> dict:
    """Load plaintext pricing baseline JSON."""
    if not path.exists():
        return {"items": []}
    return json.loads(path.read_text(encoding="utf-8"))


def pricing_version() -> str:
    return _PRICING_VERSION
