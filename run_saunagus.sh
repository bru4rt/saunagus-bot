#!/usr/bin/env bash
set -euo pipefail

# Resolve the project directory dynamically so the script works on both macOS and Linux hosts.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/run.log"

# Truncate yesterday's log so each day starts fresh
if [ -f "$LOG_FILE" ] && [ "$(date -r "$LOG_FILE" +%Y-%m-%d)" != "$(date +%Y-%m-%d)" ]; then
  : > "$LOG_FILE"
fi

echo "$(date) run_saunagus.sh started" >> "$LOG_FILE"
cd "$SCRIPT_DIR"

exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/saunagus_book.py"
