"""同步路由: TTC 私域人才库 -> 标准结构化 -> 统一人才画像库。

TTC Token 统一由服务端 .env 的 BRAINX_TTC_TALENT_AUTH_TOKEN 提供(全局, 不再由用户粘贴绑定);
所有用户共用同一数据源, 各自同步进自己隔离的 owner_user_id 人才池。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.config import settings
from reloop.modules.sync.client import talent_sync_service
from reloop.schemas.talent import SyncIngestBody

router = APIRouter(prefix="/sync", tags=["数据同步"])


@router.post("/ttc", summary="从 TTC 人才库接口拉取并同步(服务端全局 Token)")
def sync_from_ttc(
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    token = settings.ttc_talent_auth_token
    if not token:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置全局 TTC Token(BRAINX_TTC_TALENT_AUTH_TOKEN)",
        )
    space_id = settings.ttc_talent_space_id or None
    count = talent_sync_service.sync_for_user(
        owner,
        db=db,
        space_id=space_id,
        auth_token=token,
    )
    return {
        "ok": True,
        "synced": count,
        "mode": "api",
        "token_source": "global",
        "space_id": space_id,
    }


@router.post("/ttc/ingest", summary="导入 TTC 页面导出/复制的原始 JSON")
def ingest_ttc(
    body: SyncIngestBody,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    count = talent_sync_service.sync_for_user(owner, raw_payload=body.talents, db=db)
    return {"ok": True, "synced": count, "mode": "ingest"}
