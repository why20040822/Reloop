# Automation Memory — Reloop 三方一致性巡检

## 2026-08-30 运行
- 本地 HEAD=de2e682，领先 origin/main(6b96abd) 6 个提交（待推送：jd-parser 原子化、talents 简历文本、LLM 潜伏 bug 修复等）。
- 工作区未提交改动：reloop/main.py（代码）+ .workbuddy 记忆/automations 目录（非代码）。
- 服务器全部正常：reloop active、health {"status":"ok","env":"prod"}、指纹 company_pool=1、llm.py=2（/opt/reloop 无 git，经 tar 部署，代码版本≈v2.1.0）。
- 测试冒烟：71 passed（4 warnings）。/tmp/reloop_patrol.db 已清理。
- 网络：git fetch 直连 GitHub 失败（SSL_ERROR_SYSCALL），走 7897 代理成功；指纹抽查改用 ls-remote 实证远端 SHA。
- 结论：⚠️ 待用户确认后推送 6 提交 + 部署（bash scripts/deploy.sh）；未自动执行任何写操作。

## 运行要点（复用）
- SSH 批量一次取回 service/health/指纹/git，减少往返。
- pytest 冒烟耗时 ~2 分钟（71 用例），偶发超 2 分钟被 auto-background，用 TaskOutput 等结果即可。
- 临时库 /tmp/reloop_patrol.db 跑完必须删除。
