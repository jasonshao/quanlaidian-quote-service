import json
from datetime import datetime, timezone
from app.audit import log_request
from app.timezone import today_east8


def test_log_request_creates_jsonl(tmp_path):
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "request_id": "req_test123",
        "org": "demo-org",
        "brand": "黑马汇",
        "stores": 10,
        "package": "旗舰版",
        "discount": 0.85,
        "final": 142800,
        "pricing_version": "small-segment-v2.3",
        "status": "ok",
        "duration_ms": 420,
    }
    log_request(tmp_path, record)

    today = today_east8()
    log_file = tmp_path / f"{today}.jsonl"
    assert log_file.exists()

    line = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert line["request_id"] == "req_test123"
    assert line["brand"] == "黑马汇"


def test_log_request_appends(tmp_path):
    record1 = {"request_id": "req_1", "status": "ok"}
    record2 = {"request_id": "req_2", "status": "ok"}
    log_request(tmp_path, record1)
    log_request(tmp_path, record2)

    today = today_east8()
    log_file = tmp_path / f"{today}.jsonl"
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
