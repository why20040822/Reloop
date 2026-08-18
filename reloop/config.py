"""统一配置: 从环境变量/.env 读取, 全局单例。

仅保留三个外部接口:
  1. TTC 私域人才库 (数据源)
  2. 大模型 (OpenAI 兼容通用接口)
  3. RDS MySQL (唯一数据库)

所有变量使用 BRAINX_ 前缀。使用: from reloop.config import settings
"""

from functools import lru_cache

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

    # ---------- RDS MySQL (唯一数据库) ----------
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "hayden"
    mysql_password: str = "Haydenmia2026"
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
    llm_timeout: int = 30

    # ---------- TTC 私域人才库 (数据源) ----------
    ttc_talent_base_url: str = "https://app.ttcadvisory.com"
    ttc_talent_space_id: str = "U2034543869059211264"
    # 站点需飞书登录, 抓取接口需带登录态; 填写后 client 才会真正拉取
    ttc_talent_auth_token: str = ""
    # 列表接口路径(按站点真实 XHR 补全)
    ttc_talent_api_path: str = "/api/talents"

    # ---------- 评分权重 (加权乘法模型) ----------
    score_w_activity: float = 0.3
    score_w_match: float = 0.4
    score_w_value: float = 0.15
    score_w_relation: float = 0.1
    score_w_tendency: float = 0.05
    # 噪声阈值: 综合分低于此值视为噪声剔除。match 改用 max(0,cos) 后分数体系更贴近真实
    # (不再虚高), 阈值相应下调到 0.1; 过高会误杀正常候选人, 过低则放进 match≈0 的真不匹配者。
    score_noise_threshold: float = 0.1
    recommend_top_n: int = 10
    activity_decay: float = 0.1

    # ---------- 派生 ----------
    @property
    def cors_origins_list(self) -> list[str]:
        """把逗号分隔的来源解析成列表; "*" 单独返回 ["*"]。"""
        raw = (self.cors_allow_origins or "").strip()
        if raw in ("", "*"):
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

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
