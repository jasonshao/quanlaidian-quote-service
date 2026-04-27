#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DATA_DIR="${QUOTE_DATA_ROOT:-$PROJECT_ROOT/data}/files"
find "$DATA_DIR" -mindepth 1 -mtime +7 -exec rm -rf {} +
