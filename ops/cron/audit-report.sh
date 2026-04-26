#!/usr/bin/env bash
# 全来店报价服务 — 每日调用统计报告
# 每日凌晨 6:00 定时运行，分析过去 24 小时的 API 调用数据并生成 Markdown 报告。
#
# 报告输出路径: ${QUOTE_DATA_ROOT:-/opt/quanlaidian-quote/data}/reports/audit-report-YYYY-MM-DD.md
# 日志输出到 stdout，由 cron 捕获写入 /var/log/quanlaidian-audit-report.log
#
# 安装方法（复制到 /etc/cron.d/ 或手动添加到 crontab）:
#   0 6 * * *  deploy /opt/quanlaidian-quote/.venv/bin/python /opt/quanlaidian-quote/ops/audit_report.py >> /var/log/quanlaidian-audit-report.log 2>&1
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_ROOT="${QUOTE_DATA_ROOT:-/opt/quanlaidian-quote/data}"

VENV_PYTHON="${VIRTUAL_ENV:-/opt/quanlaidian-quote/.venv/bin/python}"
if [ ! -x "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

exec "$VENV_PYTHON" \
    "$PROJECT_ROOT/ops/audit_report.py" \
    --hours 24 \
    --output both
