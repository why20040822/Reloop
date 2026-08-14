"""同步路由: TTC 私域人才库 -> 标准结构化 -> 统一人才画像库。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.modules.sync.client import talent_sync_service
from reloop.schemas.talent import SyncIngestBody

router = APIRouter(prefix="/sync", tags=["数据同步"])


@router.post("/ttc", summary="从 TTC 人才库接口拉取并同步(需配置登录态 Token)")
def sync_from_ttc(
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    count = talent_sync_service.sync_for_user(owner, db=db)
    return {"ok": True, "synced": count, "mode": "api"}


@router.post("/ttc/ingest", summary="导入 TTC 页面导出/复制的原始 JSON")
def ingest_ttc(
    body: SyncIngestBody,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    count = talent_sync_service.sync_for_user(owner, raw_payload=body.talents, db=db)
    return {"ok": True, "synced": count, "mode": "ingest"}
