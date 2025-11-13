
set -euo pipefail
echo "$(date) run_saunagus.sh started" >> /Users/axelbrugger/saunagus-bot/run.log

cd /Users/axelbrugger/saunagus-bot

exec /Users/axelbrugger/saunagus-bot/.venv/bin/python /Users/axelbrugger/saunagus-bot/saunagus_book.py
