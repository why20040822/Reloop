"""Sync the guest shared talent pool or a logged-in user's personal TTC pool."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from reloop.api.deps import get_current_user, get_db, owner_user_id
from reloop.config import settings
from reloop.db.models import User
from reloop.modules.auth.vault import VaultError, unseal_user_token
from reloop.modules.sync.client import get_sync_progress, talent_sync_service
from reloop.schemas.talent import SyncIngestBody

router = APIRouter(prefix="/sync", tags=["数据同步"])


@router.post("/ttc", summary="从 TTC 人才库接口拉取并同步(访客共享库/登录用户个人库, 异步)")
def sync_from_ttc(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owner = user.user_id
    if owner == settings.guest_owner_id:
        token = settings.ttc_shared_auth_token or settings.ttc_talent_auth_token
        if not token:
            raise HTTPException(status_code=409, detail="共享人才库接口要求登录态；请在服务端配置 BRAINX_TTC_SHARED_AUTH_TOKEN")
        space_id, source, token_source = settings.ttc_talent_space_id or None, "shared", "shared_service"
    else:
        try:
            token = unseal_user_token(user.ttc_auth_token)
        except VaultError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not token:
            raise HTTPException(status_code=409, detail="请先完成飞书登录并连接自己的 TTC 人才库")
        space_id, source, token_source = user.ttc_space_id or None, "owned", "user_login"
    sync_id = talent_sync_service.sync_for_user_async(owner, space_id=space_id, auth_token=token, source=source)
    return {"ok": True, "sync_id": sync_id, "mode": "api", "token_source": token_source, "source": source, "space_id": space_id, "status": "running"}


@router.get("/ttc/status", summary="查询同步进度")
def sync_status(sync_id: str = Query(..., description="同步 ID"), db: Session = Depends(get_db), owner: str = Depends(owner_user_id)):
    info = get_sync_progress(sync_id)
    return {"status": "not_found"} if info.get("owner") and info["owner"] != owner else info


@router.post("/ttc/ingest", summary="导入 TTC 页面导出/复制的原始 JSON(异步)")
def ingest_ttc(body: SyncIngestBody, db: Session = Depends(get_db), owner: str = Depends(owner_user_id)):
    sync_id = talent_sync_service.sync_for_user_async(owner, raw_payload=body.talents)
    return {"ok": True, "sync_id": sync_id, "mode": "ingest", "status": "running"}
