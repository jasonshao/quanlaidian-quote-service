import json
from datetime import datetime, timezone

import ops.audit_report as audit_report


def test_audit_log_dates_to_check_includes_utc8_tomorrow_file():
    now = datetime(2026, 5, 7, 16, 30, tzinfo=timezone.utc)

    assert audit_report.audit_log_dates_to_check(24, now=now) == [
        "2026-05-08",
        "2026-05-07",
    ]


def test_read_audit_records_scans_utc8_tomorrow_file(tmp_path, monkeypatch):
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    record = {
        "ts": "2026-05-07T16:30:00+00:00",
        "request_id": "req_utc8_tomorrow",
        "status": "ok",
    }
    (audit_dir / "2026-05-08.jsonl").write_text(
        json.dumps(record) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(audit_report, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(
        audit_report,
        "utc_now",
        lambda: datetime(2026, 5, 7, 17, 0, tzinfo=timezone.utc),
    )

    assert audit_report.read_audit_records(hours=24) == [record]
