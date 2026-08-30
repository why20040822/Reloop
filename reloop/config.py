"""统一配置: 从环境变量/.env 读取, 全局单例。

仅保留三个外部接口:
  1. TTC 私域人才库 (数据源)
  2. 大模型 (OpenAI 兼容通用接口)
  3. RDS MySQL (唯一数据库)

所有变量使用 BRAINX_ 前缀。使用: from reloop.config import settings
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BRAINX_",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "Reloop"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "INFO"
    # 允许跨域的前端来源, 逗号分隔; "*" = 全部放通(开发期默认)。
    # 生产收紧示例: BRAINX_CORS_ALLOW_ORIGINS=https://your-frontend.example.com
    cors_allow_origins: str = "*"
    # 是否允许未知 X-Owner-User-Id 自动注册用户。
    # 开发期 True(联调方便); 生产设 False -> 未注册用户返回 401, 防止任填任进(无鉴权)。
    auth_auto_register: bool = True
    # 是否强制要求飞书扫码登录态(X-Auth-Token)。
    # True(生产默认): 任何请求必须带有效登录态, X-Owner-User-Id 不再作为鉴权 fallback,
    #   杜绝任填隔离键伪造他人数据; 未登录直接 401。
    # False(开发期): 允许 X-Owner-User-Id 直接指定隔离键(配合 auth_auto_register 联调)。
    auth_require_token: bool = True
    # 是否允许访客(未登录)访问共享人才库。True=未登录时用 guest_owner_id 隔离访问。
    auth_allow_guest: bool = True
    # 访客隔离键(未登录时的共享池 owner)
    guest_owner_id: str = "guest_shared"

    # ---------- 前端静态托管（前后端合并单进程部署） ----------
    serve_webapp: bool = True      # True=后端直接伺服 webapp/ 静态前端, 一条命令起前后端
    webapp_dir: str = ""           # 留空=自动取项目根目录下的 webapp/; 也可填绝对路径覆盖

    # ---------- RDS MySQL (唯一数据库) ----------
    # 安全: 凭据无默认值, 必须经环境变量/.env 注入, 禁止写进代码仓库。
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = ""
    # ⚠️ 密码只从 .env 的 BRAINX_MYSQL_PASSWORD 读取, 禁止硬编码默认值(曾泄漏公网仓库)
    mysql_password: str = ""
    mysql_database: str = "reloop"
    mysql_pool_size: int = 10
    mysql_charset: str = "utf8mb4"
    # 测试/本地调试可覆盖为 sqlite (如 sqlite:///./test.db); 留空则用上面的 MySQL
    database_url: str = ""

    # ---------- 大模型 (OpenAI 兼容通用接口) ----------
    # DashScope 示例: https://dashscope.aliyuncs.com/compatible-mode/v1
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen-plus"
    llm_embedding_model: str = "text-embedding-v3"
    # 改造②(2026-08-28): 向量独立端点 —— chat 与 embed 可分属不同厂商
    # (如 chat=stepfun step_plan, embed=BigModel embedding-3)。
    # 留空则回落到 llm_base_url/llm_api_key(旧行为)。
    llm_embed_base_url: str = ""
    llm_embed_api_key: str = ""
    llm_timeout: int = 30

    # ---------- DeepSeek JD 解析 (仅后端使用) ----------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 30

    # ---------- 飞书扫码登录 ----------
    # 自建飞书应用凭证(开放平台-凭证与基础信息)。未配置时 /auth/feishu/* 返回未启用。
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    # 登录态会话签名密钥: 留空自动用飞书 App Secret 兜底, 再兜底固定串(仅开发)。
    auth_session_secret: str = ""
    # 登录态有效期(小时), 默认 7 天
    auth_session_ttl_hours: int = 168
    # OAuth/TTC 登录回跳域名。后端在其下生成固定 provider callback 地址。
    auth_public_base_url: str = ""
    # TTC 一键扫码自动绑定(Playwright 无头登录抓 Token): TTC 站点登录页地址。
    # 该通道驱动 TTC 站点自身登录流程, 不经官方授权页, 不受其回调白名单限制。
    auth_login_url: str = "https://app.ttcadvisory.com/"
    # 加密存储和用户级 TTC token 必须使用独立 Fernet 密钥，禁止从公开默认值派生。
    auth_vault_key: str = ""
    auth_vault_path: str = ".auth/ttc_state.enc"

    # ---------- TTC 私域人才库 (数据源) ----------
    ttc_talent_base_url: str = "https://app.ttcadvisory.com"
    ttc_talent_api_base_url: str = "https://gateway.ttcadvisory.com"
    # TTC 官方登录授权页(前端 SPA 路由, 客户端完成授权后回跳 callback_url)。
    # 2026-08-27 实测: gateway 子域 /auth/authorize 503(ALB 后端宕), app 子域同路径 200 可用。
    ttc_authorize_url: str = "https://app.ttcadvisory.com/auth/authorize"
    ttc_talent_space_id: str = "U2034543869059211264"
    # 站点需飞书登录, 抓取接口需带登录态; 填写后 client 才会真正拉取
    ttc_talent_auth_token: str = ""
    # Service-owned token for the guest shared pool. Personal users never fall back to it.
    ttc_shared_auth_token: str = ""
    # 列表接口路径(按站点真实 XHR 补全)
    ttc_talent_api_path: str = "/api/private-talent/v1"

    # ---------- 推荐结果缓存(性能核心) ----------
    # 同一(owner+岗位+JD+数据版本)命中缓存直接返回最终结果, 不再重算。
    # 单位秒, 默认 7 天; 人才库/互动变化会自动失效(池版本号变化)。
    recommend_cache_ttl: int = 7 * 24 * 3600
    # 后台精算超过该秒数仍 running 视为僵死任务, 允许重新触发。默认 15 分钟。
    recommend_run_stale_seconds: int = 900
    # ---------- 同步限流(R6 2026-08-28) ----------
    # 同 owner 两次成功同步的最小间隔(秒), 防全量重拉 + LLM 费用放大
    sync_min_interval_seconds: int = 600

    # ---------- 匹配算法版本护栏(框架改造① 2026-08-28) ----------
    # True=v2 新算法(jd_analysis 解析特征直通+覆盖率+命中清单, 默认),
    # 每次出结果过结构自检, 自检不过/抛异常自动回退 v1(旧: 原文分词+Jaccard+正则)。
    # 出问题可置 False 一键切回旧算法, 无需回滚代码。
    match_algo_v2: bool = True

    # ---------- 评分权重 (双因子加权乘法模型: 活跃度 + 岗位匹配度) ----------
    score_w_activity: float = 0.3
    score_w_match: float = 0.4
    # (2026-08-28 R5) DEPRECATED 权重 score_w_value/relation/tendency 已删除;
    # 旧 .env 里的同名变量由 pydantic extra=ignore 静默忽略, 无需清理。
    # 噪声阈值: 综合分低于此值视为噪声剔除。match 改用 max(0,cos) 后分数体系更贴近真实
    # (不再虚高), 阈值相应下调到 0.1; 过高会误杀正常候选人, 过低则放进 match≈0 的真不匹配者。
    score_noise_threshold: float = 0.1
    recommend_top_n: int = 10
    activity_decay: float = 0.1
    # 活跃度 v3(2026-08-28): 纯绝对衰减。批内 min-max 相对归一化已废除——
    # 它保证池内必有人得高分, 是"全员活跃"假分布的算法级放大器。
    activity_absolute_weight: float = 1.0
    # 绝对活跃窗口(天): 距最近事件超过该天数活跃分触底(原 180 过宽, 收紧到 90)
    activity_abs_window: int = 90
    # 活跃门禁: 距最近事件超过该天数视为"不活跃"(软门禁: 综合分乘 penalty 降权;
    # 观察期后可收紧为直接排除)
    activity_inactive_days: int = 90
    activity_gate_penalty: float = 0.1

    # ---------- 派生 ----------
    @property
    def auth_secret(self) -> str:
        """登录态签名密钥: 显式配置 > 飞书 App Secret。

        强制登录(auth_require_token=True, 生产默认)下未配置密钥直接报错——
        历史上兜底固定串意味着任何人可伪造任意用户的 X-Auth-Token。
        仅开发降级(auth_require_token=False)允许用固定兜底串。
        """
        if self.auth_session_secret:
            return self.auth_session_secret
        if self.feishu_app_secret:
            return self.feishu_app_secret
        if self.auth_require_token:
            raise RuntimeError(
                "BRAINX_AUTH_REQUIRE_TOKEN=true 时必须配置 "
                "BRAINX_AUTH_SESSION_SECRET 或 BRAINX_FEISHU_APP_SECRET; "
                "拒绝使用公开兜底串签发登录态"
            )
        return "reloop-dev-secret"

    def validate_security(self) -> None:
        """启动期安全自检: 强制登录必须有签名密钥; 走 MySQL 必须有完整凭据。"""
        if self.auth_require_token:
            # 触发 auth_secret 的强制校验
            _ = self.auth_secret
        if not self.database_url and not (self.mysql_user and self.mysql_password):
            raise RuntimeError(
                "未配置数据库: 请设置 BRAINX_DATABASE_URL, 或 "
                "BRAINX_MYSQL_USER / BRAINX_MYSQL_PASSWORD"
            )

    @property
    def feishu_enabled(self) -> bool:
        return bool(self.feishu_app_id and self.feishu_app_secret)

    @property
    def cors_origins_list(self) -> list[str]:
        """把逗号分隔的来源解析成列表; "*" 单独返回 ["*"]。"""
        raw = (self.cors_allow_origins or "").strip()
        if raw in ("", "*"):
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def webapp_path(self) -> Path:
        """前端静态目录的绝对路径(serve_webapp 用)。"""
        if self.webapp_dir:
            return Path(self.webapp_dir).resolve()
        return Path(__file__).resolve().parent.parent / "webapp"

    @property
    def sync_dsn(self) -> str:
        """实际使用的数据库 DSN (database_url 优先, 便于测试切 SQLite)。"""
        if self.database_url:
            return self.database_url
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset={self.mysql_charset}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
