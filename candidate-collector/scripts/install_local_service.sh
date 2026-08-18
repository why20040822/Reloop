#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
LABEL=com.ttc.candidate-collector
DOMAIN="gui/$(id -u)"
SOURCE="$ROOT/launchd/$LABEL.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON="$ROOT/.venv/bin/python"
LOG_DIR="$ROOT/logs"
LOG_OUT="$LOG_DIR/local-service.out.log"
LOG_ERR="$LOG_DIR/local-service.err.log"
SERVICE_PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

test -x "$PYTHON" || {
  echo "Python 虚拟环境不存在：$PYTHON" >&2
  exit 1
}
"$PYTHON" -c 'import fastapi, fitz, multipart, pydantic, uvicorn'
plutil -lint "$SOURCE" >/dev/null
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
chmod 700 "$LOG_DIR"
touch "$LOG_OUT" "$LOG_ERR"
chmod 600 "$LOG_OUT" "$LOG_ERR"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
install -m 600 "$SOURCE" "$DEST"
plutil -replace ProgramArguments.0 -string "$PYTHON" "$DEST"
plutil -replace WorkingDirectory -string "$ROOT" "$DEST"
plutil -replace EnvironmentVariables.PATH -string "$SERVICE_PATH" "$DEST"
plutil -replace StandardOutPath -string "$LOG_OUT" "$DEST"
plutil -replace StandardErrorPath -string "$LOG_ERR" "$DEST"
plutil -lint "$DEST" >/dev/null
launchctl bootstrap "$DOMAIN" "$DEST"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"

attempt=0
while [ "$attempt" -lt 20 ]; do
  if curl -fsS --max-time 1 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    echo "candidate-collector 已安装为常驻服务：http://127.0.0.1:8765"
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 0.5
done

echo "服务未在 10 秒内就绪，请查看：$ROOT/logs/local-service.err.log" >&2
exit 1
