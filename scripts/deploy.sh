#!/usr/bin/env bash
# Reloop 一键部署脚本(2026-08-28 固化, 替代此前逐次手敲的 tar+scp 流程)
#
# 用法(项目根目录):
#   bash scripts/deploy.sh              # 标准部署: 本地重新构建前端 -> 打包 -> 上传 -> 重启 -> 健康检查
#   SKIP_BUILD=1 bash scripts/deploy.sh # 前端无改动时跳过构建
#
# 修复记录: 此前 macOS bsdtar 会把扩展属性打成 AppleDouble(._*) 垃圾文件
# 带上服务器, 打包命令必须加 COPYFILE_DISABLE=1; 服务器端另有 find 兜底清理。
set -euo pipefail

SERVER="${DEPLOY_SERVER:-root@47.110.93.137}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE_DIR="/opt/reloop"
SKIP_BUILD="${SKIP_BUILD:-0}"

cd "$(dirname "$0")/.."   # 项目根

echo "== 1/6 前端构建 =="
if [ "$SKIP_BUILD" != "1" ]; then
  npm run build:web
else
  echo "(SKIP_BUILD=1, 沿用磁盘上现有 webapp/)"
fi

echo "== 2/6 打包(COPYFILE_DISABLE=1 禁 macOS AppleDouble 垃圾) =="
PKG=/tmp/reloop_deploy.tgz
COPYFILE_DISABLE=1 tar czf "$PKG" \
  --exclude='.git' --exclude='.env' --exclude='.env.*' --exclude='.workbuddy' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='tests' --exclude='*.db' \
  --exclude='node_modules' --exclude='webapp.before-*' --exclude='hanyu*' \
  --exclude='.auth' --exclude='.pytest_cache' --exclude='.venv*' --exclude='.DS_Store' \
  --exclude='._*' \
  .
echo "包大小: $(du -h "$PKG" | cut -f1 | tr -d ' ')"

echo "== 3/6 上传 =="
scp -q -i "$KEY" "$PKG" "$SERVER:/tmp/"

echo "== 4/6 服务器: 解压/清理/重启/健康检查 =="
ssh -i "$KEY" "$SERVER" 'bash -s' <<'REMOTE'
set -euo pipefail
cd /tmp && rm -rf reloop_incoming && mkdir reloop_incoming
tar xzf /tmp/reloop_deploy.tgz -C reloop_incoming
rm -f reloop_incoming/.env reloop_incoming/.env.*
cp -a reloop_incoming/. /opt/reloop/
# 兜底清理历史 macOS AppleDouble 垃圾(根治后应为 0, 此行保险)
find /opt/reloop -name '._*' -delete 2>/dev/null || true
chown -R reloop:reloop /opt/reloop
systemctl restart reloop
sleep 4
HEALTH=$(curl -s -m 10 http://127.0.0.1:8000/health || true)
echo "[health] $HEALTH"
echo "$HEALTH" | grep -q '"status":"ok"' || { echo "!! 部署后健康检查失败"; exit 1; }
BUNDLE=$(grep -o 'index-[^"]*\.js' /opt/reloop/webapp/index.html | head -1)
echo "[bundle] $BUNDLE"
test -f "/opt/reloop/webapp/assets/$BUNDLE" || { echo "!! bundle 文件缺失"; exit 1; }
APPLE=$(find /opt/reloop/webapp -name '._*' | wc -l | tr -d ' ')
echo "[apple-double] $APPLE 个(应为 0)"
[ "$APPLE" = "0" ] || { echo "!! AppleDouble 垃圾未清干净"; exit 1; }
REMOTE

echo "== 5/6 清理服务器临时包 =="
ssh -i "$KEY" "$SERVER" 'rm -f /tmp/reloop_deploy.tgz && rm -rf /tmp/reloop_incoming'

echo "== 6/6 完成 =="
echo "部署成功。建议: 浏览器打开 https://reloop.yorkteam.cn 强刷一次验证"
