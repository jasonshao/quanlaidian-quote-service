import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def log_request(audit_dir: Path, record: dict) -> None:
    """Append one JSON line to today's audit log file.

    Audit is a side channel — a failure here must never fail the caller's
    request, since by this point pricing/persistence/render have all already
    succeeded. Catch and log to stderr instead of propagating.
    """
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = audit_dir / f"{today}.jsonl"
        line = json.dumps(record, ensure_ascii=False)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:
        request_id = record.get("request_id", "?")
        print(f"[audit] log_request failed (request_id={request_id}): {exc!r}", file=sys.stderr)
