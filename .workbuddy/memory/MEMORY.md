# Reloop 项目长期备忘

## 技术栈与关键约定
- **conda 环境 `reloop`**（Python 3.11, environment.yml）——用户明确不装系统 Python；不要用 venv。
- FastAPI + SQLAlchemy 2.0；唯一数据库 RDS MySQL(reloop 库, 账号 hayden)。
- 环境变量统一 `BRAINX_` 前缀；配置入口 `reloop/config.py`(pydantic-settings)。
- **外部接口只有三类**：TTC 私域人才库(数据源) / 大模型(OpenAI 兼容通用接口) / RDS MySQL。OSS、外部活跃信号、飞书均已移除（用户 2026-08-14 明确要求）。
- 数据隔离键 = 通用 user_id，存为各表 `owner_user_id`；生产由飞书登录态 `X-Auth-Token` 解析(2026-08-21 后 `auth_require_token=True` 强制)，`X-Owner-User-Id` 仅开发期 fallback。`reloop/api/deps.py::get_current_user` 是唯一鉴权入口。
- 目录按模块：`reloop/modules/{sync,profile,scoring,recommend}` + api/db/schemas/utils。
- 评分核心：`modules/scoring/`(factors.py 五因子 + priority.py 加权乘法模型)。权重 .env 的 `BRAINX_SCORE_W_*`。
- **算法 v2/v3(2026-08-19)**：活跃度=分事件半衰期冷却+绝对/相对混合归一化(α=0.4, `BRAINX_ACTIVITY_ABSOLUTE_WEIGHT`)；匹配度=五维加权(title/skill/semantic/years/edu, 缺失维度权重重归一)，title 维度优先 **LLM 职位语义相似度**(`llm.title_similarity`, 去重分批+进程内缓存, "AI研发工程师"↔"算法工程师"≈0.7)，离线降级 bigram。
- **大模型 = 智谱 BigModel**（2026-08-19 用户指定）：`https://open.bigmodel.cn/api/paas/v4`，glm-4-flash(chat) + embedding-3(2048维)。glm-4.5 实测 60s 超时不可用。
- **不推 GitHub**（用户 2026-08-19 明确：接口不稳定，改本地+云端保持一致即可；本地 commit 照常，推送用户手动）。
- 无原生向量库：embedding 存 JSON、应用层算余弦；LLM 无 Key 时哈希向量兜底，全流程离线可跑。
- **两阶段推荐引擎(2026-08-20)**：`recommend_runs` 表持久缓存(cache_key=sha256(owner|岗位|JD|池版本)，命中 0.02s 秒回)；未命中先回本地快速初筛(无LLM)，LLM 精算后台线程完成后前端轮询 `GET /recommend/result` 更新；精算只对 TopN 生成 LLM 理由。岗位输入=岗位名称+JD，`POST /positions` 同名同JD幂等。
- **飞书扫码登录 + 数据隔离(2026-08-20 起, 2026-08-21 强化)**：自建 app `cli_aa0f743112789cfd`；`/auth/feishu/*`(QR=segno SVG)+`X-Auth-Token`(HMAC 会话)；user_id=`fs_<我方app的open_id>`。**严格 per-user 隔离(2026-08-21)**：生产 `auth_require_token=True` 强制 X-Auth-Token, 否则 401；`X-Owner-User-Id` 仅开发期(auth_require_token=False) fallback, 杜绝伪造越权。`/auth/ttc/bind` 已删除(用户粘贴 TTC Token 绑定流程下线)。**TTC 同步改服务端全局 Token**：`/sync/ttc` 只用 `BRAINX_TTC_TALENT_AUTH_TOKEN`+`BRAINX_TTC_TALENT_SPACE_ID`(不再读 user.ttc_auth_token)；users.ttc_* 列 DEPRECATED 保留不删。飞书控制台需配重定向 URL `https://reloop.yorkteam.cn/#/auth/callback`。
- **生产库= `reloop_app`**（同实例内网地址 `rm-bp12ok9so2ma3i3j7` = 公网 `ttc-rds-public-0707`，2026-08-20 修正：服务器 .env 原误指 `reloop` 空库）。users.ttc_auth_token 已扩为 TEXT。依赖新增 `segno`。
- **HTTPS = Let's Encrypt 正式证书(2026-08-20)**：acme.sh(DNS-01, dns_ali) 签发，证书在 `/etc/nginx/ssl/reloop.yorkteam.cn.le.{crt,key}`，自动续期 cron 已装。**80 端口对外被阿里云 ICP 备案拦截（域名未备案），ACME HTTP-01 不可用、必须 DNS-01**；服务器本机测不出该拦截。HTTPS 不受备案拦截影响。
- **nginx 配置(2026-08-25 更新)**：`/etc/nginx/sites-available/reloop.yorkteam.cn` 包含 HTTP→HTTPS 301 重定向 + SSL 终结 + 反代到 127.0.0.1:8000。使用 `listen 443 ssl` (非 http2)。证书路径：`/etc/nginx/ssl/reloop.yorkteam.cn.le.{crt,key}`。

## 数据源
- TTC 私域人才库: https://app.ttcadvisory.com/app/private-talent/talents/all-talents/U2034543869059211264
- 页面需飞书登录（实测）。同步双通道：接口拉取(client.py, 需 Token) / 页面导出 JSON 导入(POST /sync/ttc/ingest)。
- 字段映射集中在 `modules/sync/normalizer.py::FIELD_ALIASES`，拿到真实 XHR 后在此补。

## 云端部署(实测 2026-08-19，已成功同步一次)
- ECS：实例 `i-bp1dgg3rzmehc33fwpsn`，地域 `cn-hangzhou`，公网 IP `47.110.93.137`。阿里云账号 `17610493778`（密码不写入记忆）。
- **实例是 PrePaid（包年包月）**：到期会 `Stopped` + `OperationLocks.financial` 锁、公网 IP 在宽限期内保留（实测 8/19 到期→用户续费→8/20 恢复 Running，IP 不变）。连不上先 `aliyun ecs DescribeInstances --InstanceIds '["i-bp1dgg3rzmehc33fwpsn"]'` 查 `Status`/`ExpiredTime`/`OperationLocks`；续费后 `Status` 回 Running。本机 `aliyun` CLI 已配置默认 profile（可 `DescribeRenewalPrice` 询价/`StartInstance`/查状态），无需另装。
- 访问：`http://47.110.93.137/`（80）。链路：**nginx(:80) → gunicorn(:127.0.0.1:8000) → Reloop**。`/health`=`{"status":"ok","app":"Reloop","env":"prod"}`（实测 8/20 部署后为 prod），`/docs`=200。⚠️ **nginx `:80` 是 HTTP→HTTPS 强制跳转（`return 301 https://$host$request_uri`），真实 App 在 `:443 reloop.yorkteam.cn`（自签名证书）反代 `:8000`**；裸 IP 走 80 会 301 到 HTTPS IP 后落到默认 server（不返 App）。要裸 HTTP 直出 App 需改 `:80` server 块为 `proxy_pass http://127.0.0.1:8000`（牺牲 ACME/HTTPS 强制，需用户确认）。
- 进程：systemd 单元 `reloop.service`（User=`reloop`），ExecStart=`/opt/reloop/.venv/bin/gunicorn reloop.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 127.0.0.1:8000`，`Restart=always`。管理：`systemctl restart reloop`。
- 代码目录 `/opt/reloop`；虚拟环境 `/opt/reloop/.venv`（Python 3.11.16，系统 python 是 3.14，**别动 venv、也别用系统 python 跑**）。
- **`.env` 是服务器本地配置（含真实 RDS/LLM/TTC 凭据），同步时务必保留、不要被本地 .env 覆盖**；每次同步前会自动备份为 `.env.bak.<ts>`。
- 免密登录：本机 `~/.ssh/id_ed25519.pub` 已加入服务器 `/root/.ssh/authorized_keys`（用户用控制台 Workbench 加的）。日常：`ssh -i ~/.ssh/id_ed25519 root@47.110.93.137`。
- 磁盘曾 100% 满（20G 盘，与 recruit-bot/brainx/ttc-automation 等多服务共存）。安全清理：`apt-get clean` + `journalctl --vacuum-size=100M` + 删旧 rotated 日志（`/var/log/*.1`/`*.gz`）。根分区 5% 保留块归 root（约 1GB 可用），部署够用；部署后清 `/tmp` 临时包。
- 本机 `/tmp` 跨回合会被清空 → **打包与 scp 必须在同一条命令内完成**。
- 同步流程（本地→云）：`tar` 打包 `/f/ttc/Reloop`，排除 `.git/.workbuddy/.env/venv/__pycache__/*.pyc/tests/*.db/*.log` → `scp` 到服务器 `/tmp` → `tar -xz` → 删解压出的 `.env` → 备份服务器 `.env` → `cp -rf` 进 `/opt/reloop` → `chown -R reloop:reloop` → venv 内 `pip install -r requirements.txt --no-cache-dir`（通常已满足）→ `systemctl restart reloop` → 验证 `127.0.0.1:8000/health` 与公网 `/health`。

## 服务器跑同步/脚本的两个必踩坑（2026-08-19 实测）
1. **pydantic-settings `env_file=".env"` 是相对路径**：在服务器上跑独立脚本必须先 `os.chdir('/opt/reloop')`（再加 `sys.path.insert(0,'/opt/reloop')`），否则 .env 完全读不到——表现为 TTC token 为空、静默同步 0 条、DB 走 127.0.0.1 默认值。
2. **`sync_for_user(db=...)` 传外部 session 只 flush 不 commit**：独立脚本必须自己 `db.commit()`，否则 close 时整体回滚（表现为 synced=368 但库里 0 条）。
- 全量同步脚本模板：见 `.workbuddy/tmp_sync_script.py`（chdir + commit + OWNER=ou_ff894386d0ca340dcc2f7bdc53c57a81）。
- 本地连 RDS 需把本机公网 IP（当前 162.210.155.12）加入 RDS 白名单，否则 2003 超时。

## 测试
- `python tests/test_pipeline.py`（SQLite 覆盖 + LLM 离线，无需任何凭据）。

## 已修复问题(2026-08-25)
- **talents.py 路由顺序**：`/followed/list` 必须在 `/{talent_id}` 之前，否则 "followed" 被解析为 talent_id 导致 422 错误。
- **recommend.py 标签一致性**：feedback fav/unfav 统一使用 "已关注" 标签（之前用 "收藏"）。
- **app.js 变量名错误**：rowHTML 中 `isFollowed` → `isFaved`。
- **app.js 重复声明**：移除 noPosMsg 重复声明。
- **app.js 错误处理**：recommend API 返回错误结构时前端不再崩溃。

## 待办/已知缺口
- TTC 真实接口路径已验证可用（gateway.ttcadvisory.com/api/private-talent/v1/all-talents/<space>/talents?page=&page_size=100）。
- 后期前端：契约在 schemas/talent.py + api/ 路由，Swagger /docs。
- 前端 talent detail 新增展示字段：projects（项目经验）、delivery_records（投递记录），normalizer 已支持字段映射。
- 岗位上限已从 5 调整为 10（`reloop/api/positions.py`）。
- `/recommend/cache/clear` API 已删除（前端 provider.js 同步移除）。
- LLM batch_match_scores 添加分位校准（映射到 [0.1, 0.9]），避免全员分数偏高/偏低。
- 前端登录态保护：`api.me()` 失败时保留 localStorage 登录态，不从 UI 清除。
- GitHub 前端仓库 `why20040822/reloop-talent-workbench` 当前不可访问（404），需用户确认仓库状态。

## 2026-08-26 本地大改：人才字段格式重构 + 详情全字段 + LLM 熔断
- **TTC 真实字段路径(实测 XHR)**：工作经历在 `work.items[]`（不是旧 normalizer 假设的 `work.detail.experiences`），项目在 `project.items[]`（不是 `item.projects`），技能在 `skill.ai_ability`（不是 `skill.language`），备注在 `dynamic.macro.concern_reason`（不是 `notes/remark`）。**`work.items[]` 每段含** `company_name/company_name_std/business_line/position/position_std/job_level/start_time/end_time/tenure_months/description(职责长文本)/management_scale/has_management/company_category/business_domain_category/is_internship`——正是 Hayden.md 2.1 要求的格式。
- **models.py 新增 8 列（v4.1）**：`contact_phone/contact_email/seek_status/current_salary/expected_salary/target_positions( JSON list)/education_history(JSON list)/contact_status`。`engine.py::_ensure_columns()` 同步补列(MySQL+SQLite 兼容)。新列顺序在 `_ensure_columns` 末尾追加即可自动 ALTER。
- **structuring.contact_status 默认"未联系"**；**更新时保留人工已设置的状态**(不覆盖)；教育经历明细 `education_history` 是新增 JSON list 字段，与顶层 `education`(最高学历 macro)并存。
- **算法细节**：活跃度 `build_activity_events` 当 `last_active_at == resume_updated_at` 时**不重复计数**(避免同源 last_updated_at 双倍权重虚高活跃度)；匹配度 `match_score_structured` 已有 base=0.3 + 五维权重重归一 + 分位校准 [0.1, 0.9] 满足 Hayden.md 规则 B；`recommend_engine.DEFAULT_TOP_SIZES = (3, 10, None)` 生成 top3/top10/top_n(测试断言 top3, 2026-08-25 缺)。
- **LLM 熔断**(`modules/profile/llm.py`)：连续 3 次 `chat`/`embed` 网络/接口失败自动 `_available=False` 离线模式, 后续直接走降级(哈希向量/模板理由)，避免 LLM 不可用时同步 378 条每条都等网络超时。熔断是进程内、单例共享 `llm_service`。
- **本地 .env LLM 配置注意**：本地 .env `BRAINX_LLM_BASE_URL=https://api.stepfun.com/step_plan/v1` 是错的(404), 正确路径是 `/v1`（服务器用 `/v1`, 用户 8/19 配的）。但即便 `/v1`, chat 端点对当前 stepfun key 也 404, embeddings 返回 400(模型名 `embedding-3` 不被 stepfun 识别)——**该 key 实际不可用, 全流程靠熔断+降级跑通**。智谱 BigModel(`https://open.bigmodel.cn/api/paas/v4`, glm-4-flash + embedding-3)是之前 8/19 配置, 服务器 .env 被改过, 本地 .env 与服务器 .env 不一致, 建议用户决定统一到哪个 LLM 厂商。
- **前端详情页全字段**：重写 `renderTalentDetail`（webapp/app.js）展示联系方式/求职状态/薪资/目标岗位/教育经历明细/工作经历多段完整(起止时间/公司/业务线/岗位·职级/职责长文本/管理规模/是否实习)/项目经验完整(技术栈/场景/成果/AI 0→1 标签)/稳定性(平均/最长/最近任期+公司数+大厂经验+管理规模)/投递/备注+联系状态徽章。**修复 v4.0 遗留 bug**：`renderTalentDetail` 模板用 `isFaved` 但变量是 `isFollowed` → ReferenceError 详情页卡"加载中"；同时给行内加"查看完整档案"按钮跳 `#/talent/{id}`。人才库列表 `titem` 加 seek_status/contact_status 标签。styles.css 补 `.wh-desc`/`.edu-item`/`.tag.st-*` 样式。
- **数据同步新模板** `.workbuddy/tmp_sync_new_format.py`：流程 init_db 补列 → 清目标 owner 子表（先 recommendations/recommend_runs/feedback_logs/interaction_records 再 talent_profiles, 避免外键约束）→ `talent_sync_service.sync_for_user` → 校验。`OWNER=guest_shared`（本地访客池, 未登录前端可看）。**首次跑已成功：378 人新格式入 RDS, work_history 330/378, projects 264, education_history 328, notes 100, seek_status 146, contact_phone 298, contact_email 245, contact_status 357（补默认"未联系"）**。脚本可复用: `D:/enviroment/anaconda/envs/reloop/python.exe .workbuddy/tmp_sync_new_format.py`。
- **测试**：跑 `python tests/test_pipeline.py` 全通过(归一化/结构化/隔离/设岗/互动/两阶段引擎+缓存+持久化+auth/API smoke)，其中 `engine.compute(wait=True)` 必须返回 `top3/top10/top_n` 三个 key（已通过 `DEFAULT_TOP_SIZES = (3, 10, None)` 修复）。
- **git 仓库恢复**（重要）：8/26 拉服务器代码覆盖时本地 .git 的 refs 目录和 objects/pack 文件丢失/损坏，git 命令报 "bad object HEAD" / "not a git repository"。**通过将 remote URL 从含 token 的 `https://x-access-token:gh...@github.com/...` 改为公开 `https://github.com/why20040822/Reloop.git` 后 `git fetch origin` 成功恢复所有对象**。之前 remote token 可能失效/被 GitHub 拒绝。`git status` 现正常显示所有本地修改(未 commit), main 分支指回 9087212 v4.0。
- **代码同步约定变更**：8/26 用户明确"只本地修改测试, 不要上 github, 不要重新上云"——本次所有改动只在本地工作区, 不 push。`.env` 本地版本(包含真实凭据)同步前后未动。
