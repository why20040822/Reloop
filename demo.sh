#!/bin/sh
# Reloop 精品库 demo 一键拉起（本地演示用）
# 用法：./demo.sh        起后端 :18765 + 前端 :3200（生产构建，演示稳定）
#       ./demo.sh dev    前端用开发模式（改代码热更新）
#       ./demo.sh stop   停掉两个服务
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=18765
FRONTEND_PORT=3200

stop_all() {
  lsof -tiTCP:$BACKEND_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  lsof -tiTCP:$FRONTEND_PORT -sTCP:LISTEN | xargs kill 2>/dev/null || true
  if [ -f /tmp/reloop-worker.pid ]; then
    kill "$(cat /tmp/reloop-worker.pid)" 2>/dev/null || true
    rm -f /tmp/reloop-worker.pid
  fi
}

if [ "${1:-}" = "stop" ]; then
  stop_all
  echo "已停止 :$BACKEND_PORT、:$FRONTEND_PORT 和 worker"
  exit 0
fi

# 前置检查：LLM key（jd-match 需要，列表浏览不需要）
set -a; . "$ROOT/.env"; set +a
if [ -z "${TTC_LLM_API_KEY:-}" ]; then
  echo "⚠️  .env 里 TTC_LLM_API_KEY 为空：JD 匹配演示不可用，候选人列表可正常看"
fi

stop_all

# 后端（云端 reloop 库）
cd "$ROOT"
PYTHONPATH=. nohup reloop/.venv/bin/python -m uvicorn reloop.api.main:app \
  --host 127.0.0.1 --port $BACKEND_PORT > /tmp/reloop-backend.log 2>&1 &

# outbox worker 常驻循环：每 5 秒把队列里的候选人投递到云端精品库（再投影飞书）
# 没有它，录入的简历会永远积压在本地 outbox（queued）
nohup sh -c 'while true; do PYTHONPATH=. reloop/.venv/bin/python -m reloop.ops.worker --limit 10 >> /tmp/reloop-worker.log 2>&1; sleep 5; done' > /dev/null 2>&1 &
echo $! > /tmp/reloop-worker.pid

# 前端
cd "$ROOT/frontend"
if [ "${1:-}" = "dev" ]; then
  nohup pnpm exec vinext dev --port $FRONTEND_PORT > /tmp/reloop-frontend.log 2>&1 &
else
  [ -d dist ] || pnpm run build
  nohup pnpm exec vinext start --port $FRONTEND_PORT > /tmp/reloop-frontend.log 2>&1 &
fi

sleep 5
curl -sf "http://127.0.0.1:$BACKEND_PORT/api/health" > /dev/null && echo "✅ 后端 :$BACKEND_PORT 已起（云端 reloop 库）" || { echo "❌ 后端启动失败，看 /tmp/reloop-backend.log"; exit 1; }
echo "✅ worker 常驻中（outbox → 云端，5s 一轮；日志 /tmp/reloop-worker.log）"
echo ""
echo "演示入口： http://localhost:$FRONTEND_PORT/talent"
echo "停止：     ./demo.sh stop"
