#!/usr/bin/env bash
set -euo pipefail

# Resolve the project directory dynamically so the script works on both macOS and Linux hosts.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/run.log"

echo "$(date) run_saunagus.sh started" >> "$LOG_FILE"
cd "$SCRIPT_DIR"

exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/saunagus_book.py"
