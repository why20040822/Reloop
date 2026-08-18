"""TTC 私域人才库客户端 (数据源接入)。

人才库网站(需飞书登录):
  https://app.ttcadvisory.com/app/private-talent/talents/all-talents/<space_id>

两种取数方式:
  1. fetch_talents(): 带 Bearer Token 调站点接口(接口路径/字段按真实 XHR 在
     .env 的 BRAINX_TTC_TALENT_API_PATH 和 normalizer.FIELD_ALIASES 中补全)。
  2. ingest_talents(): 直接灌入从页面上导出/复制的 JSON(开发期最实用)。

取出后统一走 normalizer.normalize_batch -> 标准结构化格式。
"""

import logging
from typing import Optional

import httpx

from reloop.config import settings
from reloop.db.engine import SessionLocal
from reloop.modules.profile.structuring import structuring_service
from reloop.modules.sync.normalizer import normalize_batch

logger = logging.getLogger(__name__)


class TTCClient:
    """TTC 私域人才库数据源客户端。"""

    def __init__(self) -> None:
        self.base_url = settings.ttc_talent_base_url
        self.default_space_id = settings.ttc_talent_space_id
        self.auth_token = settings.ttc_talent_auth_token
        self.api_path = settings.ttc_talent_api_path

    # ---------------- 拉取 (接口方式) ----------------
    def fetch_talents(self, space_id: Optional[str] = None) -> list[dict]:
        """从站点接口拉取人才列表 -> 标准结构化格式列表。

        真实接口(gateway.ttcadvisory.com, 需飞书登录态):
          GET {base_url}{api_path}/{space_id}/talents?page=N&page_size=M
          返回 {code, message, data:{list:[...], total:N}}
        .env 配 BRAINX_TTC_TALENT_AUTH_TOKEN(浏览器 F12 -> Network 复制 Authorization)。
        未配置时返回空列表(不报错, 框架可独立运行)。
        """
        if not self.auth_token:
            logger.info("[ttc] 未配置 auth token, 跳过接口拉取(可用 ingest 方式导入)")
            return []
        space_id = space_id or self.default_space_id
        base_path = self.api_path.rstrip("/")
        page, page_size = 1, 100
        all_items: list[dict] = []
        try:
            while True:
                url = f"{self.base_url}{base_path}/{space_id}/talents"
                resp = httpx.get(
                    url,
                    params={"page": page, "page_size": page_size},
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.auth_token}",
                    },
                    timeout=20,
                )
                if resp.status_code != 200:
                    logger.warning("[ttc] fetch page=%s status=%s url=%s",
                                   page, resp.status_code, url)
                    break
                data = (resp.json() or {}).get("data") or {}
                items = data.get("list") or []
                all_items.extend(items)
                total = data.get("total")
                logger.info("[ttc] page=%s got=%s total=%s", page, len(items), total)
                if not items or len(items) < page_size:
                    break
                if total and len(all_items) >= total:
                    break
                page += 1
            return normalize_batch(all_items)
        except Exception as e:  # noqa: BLE001
            logger.warning("[ttc] fetch error: %s", e)
            return []

    # ---------------- 导入 (页面导出 JSON) ----------------
    def ingest_talents(self, raw_payload) -> list[dict]:
        """把页面导出/复制的原始 JSON 转成标准结构化格式。"""
        return normalize_batch(raw_payload)


class TalentSyncService:
    """同步编排: 取数(TTCClient) -> 入库(talent_profiles, 按用户隔离)。"""

    def __init__(self, client: Optional[TTCClient] = None) -> None:
        self.client = client or TTCClient()

    def sync_for_user(
        self,
        owner_user_id: str,
        raw_payload=None,
        space_id: Optional[str] = None,
        db=None,
    ) -> int:
        """为指定用户同步人才库数据(隔离写入)。

        raw_payload 传入时走 ingest(页面导出 JSON); 否则尝试接口拉取。
        返回新增/更新的人才数。
        """
        if raw_payload is not None:
            talents = self.client.ingest_talents(raw_payload)
        else:
            talents = self.client.fetch_talents(space_id)
        if not talents:
            logger.info("[sync] no talents for owner=%s", owner_user_id)
            return 0

        own_session = db is None
        db = db or SessionLocal()
        try:
            count = 0
            for t in talents:
                row = self._upsert(db, owner_user_id, t)
                if row:
                    count += 1
            if own_session:
                db.commit()
            logger.info("[sync] owner=%s synced %d talents", owner_user_id, count)
            return count
        except Exception:  # noqa: BLE001
            if own_session:
                db.rollback()
            raise
        finally:
            if own_session:
                db.close()

    @staticmethod
    def _upsert(db, owner_user_id: str, t: dict) -> Optional[TalentProfile]:
        """同 owner 下 source_id 去重 upsert (source_id 为空则按姓名+公司)。"""
        q = db.query(TalentProfile).filter(
            TalentProfile.owner_user_id == owner_user_id
        )
        if t.get("source_id"):
            existing = q.filter(TalentProfile.source_id == t["source_id"]).first()
        else:
            existing = q.filter(
                TalentProfile.name == t["name"],
                TalentProfile.company == (t.get("company") or ""),
            ).first()

        fields = dict(
            name=t["name"],
            base_location=t.get("base_location"),
            company=t.get("company"),
            position=t.get("position"),
            work_years=t.get("work_years"),
            education=t.get("education"),
            skills=t.get("skills"),
            resume_text=t.get("summary"),
            last_active_at=t.get("last_active_at"),
            tags=t.get("tags") or [],
            source_payload=t.get("raw"),
        )
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            return existing
        profile = TalentProfile(owner_user_id=owner_user_id, source_id=t.get("source_id") or None, **fields)
        db.add(profile)
        return profile


talent_sync_service = TalentSyncService()
