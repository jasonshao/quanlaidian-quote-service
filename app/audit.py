import json
from datetime import datetime, timezone
from pathlib import Path


def log_request(audit_dir: Path, record: dict) -> None:
    """Append one JSON line to today's audit log file."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = audit_dir / f"{today}.jsonl"
    line = json.dumps(record, ensure_ascii=False)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")
