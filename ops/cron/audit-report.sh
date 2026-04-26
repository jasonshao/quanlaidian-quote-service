#!/usr/bin/env bash
# 全来店报价服务 — 每日调用统计报告
# 每日凌晨 6:00 定时运行，分析过去 24 小时的 API 调用数据并生成 Markdown 报告。
#
# 报告输出路径: ${QUOTE_DATA_ROOT:-<repo>/data}/reports/audit-report-YYYY-MM-DD.md
# 日志: 由调用方的 cron 行重定向，本脚本只输出到 stdout/stderr。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# audit_report.py 内 DATA_ROOT 默认 Path("data") 是相对路径，必须先 cd 到仓库根
cd "$PROJECT_ROOT"

# 选 Python：优先仓内 venv，其次外层激活的 venv，最后回退 python3
if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PYTHON="$VIRTUAL_ENV/bin/python"
else
    PYTHON="python3"
fi

exec "$PYTHON" "$PROJECT_ROOT/ops/audit_report.py" --hours 24 --output both
