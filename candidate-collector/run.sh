#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -n "${TTC_PYTHON:-}" ]; then
  PY="$TTC_PYTHON"
elif [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3.12
fi
"$PY" -c 'import fastapi, fitz, multipart, pydantic, uvicorn' 2>/dev/null || {
  echo "依赖未安装。请先运行: python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
}
exec "$PY" -m uvicorn app:app --host 127.0.0.1 --port 8765
