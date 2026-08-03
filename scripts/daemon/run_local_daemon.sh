#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${TTC_DAEMON_PORT:-8766}"

cd "$APP_DIR"

# Source local .env first; allow overriding via exported env vars.
if [[ -f "$APP_DIR/.env" ]]; then
  set -a
  source "$APP_DIR/.env"
  set +a
fi

if [[ -f "$APP_DIR/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$APP_DIR/venv/bin/activate"
fi

if [[ -f "$HOME/.ttc/mysql.env" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.ttc/mysql.env"
fi

export TTC_SOURCE_TALENT_ENABLED="${TTC_SOURCE_TALENT_ENABLED:-true}"
export TTC_API_TOKEN="${TTC_API_TOKEN:-localtest}"
export TTC_FEISHU_NOTIFY_ENABLED="${TTC_FEISHU_NOTIFY_ENABLED:-true}"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/tmp/ttc_port_check.$$ 2>/dev/null; then
  echo "Port $PORT is already in use:" >&2
  cat /tmp/ttc_port_check.$$ >&2
  rm -f /tmp/ttc_port_check.$$
  echo "Stop the old process first, for example: kill <PID>" >&2
  exit 1
fi
rm -f /tmp/ttc_port_check.$$

echo "Starting TTC Daemon on http://127.0.0.1:$PORT"
echo "Source talent enabled: $TTC_SOURCE_TALENT_ENABLED"
echo "MySQL host: ${TTC_MYSQL_HOST:-not-set}"
python3 scripts/daemon/run_ttc_daemon.py
