"""TTC 私域人才库客户端 (数据源接入)。

人才库网站(需飞书登录):
  https://app.ttcadvisory.com/app/private-talent/talents/all-talents/<space_id>

两种取数方式:
  1. fetch_talents(): 带 Bearer Token 调站点接口(接口路径/字段按真实 XHR 在
     .env 的 BRAINX_TTC_TALENT_API_PATH 和 normalizer.FIELD_ALIASES 中补全)。
  2. ingest_talents(): 直接灌入从页面上导出/复制的 JSON(开发期最实用)。

取出后统一走 normalizer.normalize_batch -> 标准结构化格式。
"""

import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Optional

import httpx

from reloop.config import settings
from reloop.db.engine import SessionLocal
from reloop.modules.profile.structuring import structuring_service
from reloop.modules.sync.normalizer import normalize_batch
from reloop.db.models import TalentProfile

logger = logging.getLogger(__name__)

# 同步进度存储: {sync_id: {"total": int, "current": int, "status": str, "message": str}}
_SYNC_PROGRESS: dict[str, dict] = {}
_SYNC_LOCK = threading.Lock()


class TTCAuthRequired(RuntimeError):
    """TTC API requires a valid service or user authentication token."""


class TTCFetchError(RuntimeError):
    """TTC API returned a non-authentication failure."""


def _make_sync_id(owner: str) -> str:
    return f"{owner}:{uuid.uuid4().hex}"


def get_sync_progress(sync_id: str) -> dict:
    with _SYNC_LOCK:
        return dict(_SYNC_PROGRESS.get(sync_id, {"status": "not_found"}))


def _update_progress(sync_id: str, **kwargs):
    with _SYNC_LOCK:
        p = _SYNC_PROGRESS.get(sync_id, {})
        p.update(kwargs)
        _SYNC_PROGRESS[sync_id] = p


def _source_hash(talent: dict) -> str:
    """ talents 内容 hash(用于去重: 同 source_id 且内容不变则 skip)。"""
    raw = json.dumps(talent, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class TTCClient:
    """TTC 私域人才库数据源客户端。"""

    def __init__(self) -> None:
        self.base_url = settings.ttc_talent_api_base_url
        self.default_space_id = settings.ttc_talent_space_id
        self.auth_token = settings.ttc_shared_auth_token or settings.ttc_talent_auth_token
        self.api_path = settings.ttc_talent_api_path

    def fetch_talents(self, space_id: Optional[str] = None,
                      auth_token: Optional[str] = None,
                      source: str = "owned",
                      progress_callback=None) -> list[dict]:
        """从站点接口拉取人才列表 -> 标准结构化格式列表。

        progress_callback(total, current) 可传入以获取拉取进度。
        """
        token = auth_token or self.auth_token
        if not token:
            raise TTCAuthRequired("TTC 人才库需要有效登录态；请先登录飞书或配置共享库只读凭据")
        if source not in {"owned", "shared"}:
            raise ValueError(f"未知 TTC 数据源: {source}")
        space_id = space_id or self.default_space_id
        if source == "shared" and not space_id:
            raise TTCFetchError("共享人才库缺少空间 ID")
        base_path = self.api_path.rstrip("/")
        page, page_size = 1, 100
        all_items: list[dict] = []
        total = None
        try:
            while True:
                url = (
                    f"{self.base_url}{base_path}/all-talents/{space_id}/talents"
                    if source == "shared"
                    else f"{self.base_url}{base_path}/talents"
                )
                resp = self._request_with_retry(
                    url,
                    params={"page": page, "page_size": page_size},
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                )
                if resp.status_code in {401, 403}:
                    raise TTCAuthRequired("TTC 登录态已失效，请重新登录飞书")
                if resp.status_code != 200:
                    raise TTCFetchError(f"TTC 人才库请求失败（HTTP {resp.status_code}）")
                resp_json = resp.json() or {}
                data = resp_json.get("data") or resp_json
                # 兼容多种响应格式
                items = (
                    data.get("list")
                    or data.get("items")
                    or data.get("records")
                    or data.get("talents")
                    or []
                )
                if not items and isinstance(data, list):
                    items = data
                if not items and isinstance(resp_json, list):
                    items = resp_json
                if total is None:
                    total = data.get("total") or data.get("count") or resp_json.get("total")
                all_items.extend(items)
                if progress_callback and total:
                    progress_callback(total, len(all_items))
                logger.info("[ttc] page=%s got=%s total=%s", page, len(items), total)
                if not items or len(items) < page_size:
                    break
                if total and len(all_items) >= total:
                    break
                page += 1
            return normalize_batch(all_items)
        except (TTCAuthRequired, TTCFetchError):
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[ttc] fetch error: %s", e)
            raise TTCFetchError("TTC 人才库网络请求失败") from e

    def _request_with_retry(self, url, params=None, headers=None, max_retries=3):
        """带重试和指数退避的 HTTP GET 请求。"""
        import time as _time
        last_resp, last_exc = None, None
        for attempt in range(max_retries):
            try:
                resp = httpx.get(url, params=params, headers=headers, timeout=30)
                if resp.status_code < 500:
                    return resp
                last_resp = resp
                logger.warning("[ttc] attempt %d/%d server error status=%s", attempt + 1, max_retries, resp.status_code)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                last_exc = e
                logger.warning("[ttc] attempt %d/%d network error: %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                _time.sleep(2 ** attempt)
        if last_resp:
            return last_resp
        if last_exc:
            raise last_exc
        raise RuntimeError("[ttc] all retries exhausted")

    def ingest_talents(self, raw_payload) -> list[dict]:
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
        auth_token: Optional[str] = None,
        source: str = "owned",
        db=None,
        progress_callback=None,
    ) -> int:
        """为指定用户同步人才库数据(隔离写入)。

        raw_payload 传入时走 ingest(页面导出 JSON); 否则尝试接口拉取。
        auth_token/space_id 未传时用 .env 全局配置。
        progress_callback(current, total) 用于实时进度。
        返回新增/更新的人才数。
        """
        if raw_payload is not None:
            talents = self.client.ingest_talents(raw_payload)
        else:
            talents = self.client.fetch_talents(
                space_id, auth_token=auth_token, source=source,
                progress_callback=lambda t, c: progress_callback and progress_callback(c, t)
            )
        if not talents:
            logger.info("[sync] no talents for owner=%s", owner_user_id)
            return 0

        own_session = db is None
        db = db or SessionLocal()
        try:
            count = 0
            skipped = 0
            for t in talents:
                sid = t.get("source_id") or None
                # 去重: 同 source_id 且 source_payload 内容不变则 skip
                if sid:
                    existing = (
                        db.query(TalentProfile)
                        .filter(
                            TalentProfile.owner_user_id == owner_user_id,
                            TalentProfile.source_id == sid,
                        )
                        .first()
                    )
                    if existing and _source_hash(existing.source_payload or {}) == _source_hash(t.get("source_payload") or {}):
                        skipped += 1
                        if progress_callback:
                            progress_callback(count + skipped, len(talents))
                        continue
                    if existing:
                        from reloop.modules.profile.structuring import structuring_service as _ss
                        _ss.enrich_and_save(db, owner_user_id, t, source_id=sid, commit=False)
                        count += 1
                        if progress_callback:
                            progress_callback(count + skipped, len(talents))
                        continue
                row = structuring_service.enrich_and_save(
                    db, owner_user_id, t, source_id=sid, commit=False
                )
                if row:
                    count += 1
                if progress_callback:
                    progress_callback(count + skipped, len(talents))
            if own_session:
                db.commit()
            else:
                db.flush()
            logger.info("[sync] owner=%s synced=%d skipped=%d total=%d",
                        owner_user_id, count, skipped, len(talents))
            return count
        except Exception:  # noqa: BLE001
            if own_session:
                db.rollback()
            raise
        finally:
            if own_session:
                db.close()

    def sync_for_user_async(self, owner_user_id: str, **kwargs) -> str:
        """后台异步同步: 返回 sync_id, 前端轮询进度。"""
        sync_id = _make_sync_id(owner_user_id)
        _update_progress(sync_id, total=0, current=0, status="running",
                         message="准备中…", owner=owner_user_id)

        def _bg():
            try:
                def prog(current, total):
                    _update_progress(sync_id, current=current, total=total,
                                     status="running", message=f"同步中 ({current}/{total})…")
                count = self.sync_for_user(owner_user_id, progress_callback=prog, **kwargs)
                current = get_sync_progress(sync_id).get("current", 0)
                _update_progress(sync_id, status="done", message=f"同步完成: {count} 人",
                                 current=max(current, count), synced=count)
            except Exception as e:  # noqa: BLE001
                logger.exception("[sync] async failed owner=%s", owner_user_id)
                _update_progress(sync_id, status="failed", message=str(e)[:200])

        threading.Thread(target=_bg, daemon=True).start()
        return sync_id


talent_sync_service = TalentSyncService()
