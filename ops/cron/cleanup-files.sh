#!/usr/bin/env bash
set -euo pipefail
DATA_DIR="${QUOTE_DATA_ROOT:-/opt/quanlaidian-quote/data}/files"
find "$DATA_DIR" -mindepth 1 -mtime +7 -exec rm -rf {} +
