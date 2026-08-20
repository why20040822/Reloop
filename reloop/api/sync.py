"""同步路由: TTC 私域人才库 -> 标准结构化 -> 统一人才画像库。

优先用当前登录用户绑定的 TTC Token/空间(见 POST /auth/ttc/bind);
未绑定时回落 .env 全局 Token(默认空间)。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.db.models import User
from reloop.modules.sync.client import talent_sync_service
from reloop.schemas.talent import SyncIngestBody

router = APIRouter(prefix="/sync", tags=["数据同步"])


@router.post("/ttc", summary="从 TTC 人才库接口拉取并同步(用我绑定的 Token)")
def sync_from_ttc(
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    user = db.query(User).filter(User.user_id == owner).first()
    user_token = user.ttc_auth_token if user else None
    user_space = user.ttc_space_id if user else None
    count = talent_sync_service.sync_for_user(
        owner,
        db=db,
        space_id=user_space,
        auth_token=user_token,
    )
    return {
        "ok": True,
        "synced": count,
        "mode": "api",
        "token_source": "user" if user_token else "global",
        "space_id": user_space,
    }


@router.post("/ttc/ingest", summary="导入 TTC 页面导出/复制的原始 JSON")
def ingest_ttc(
    body: SyncIngestBody,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    count = talent_sync_service.sync_for_user(owner, raw_payload=body.talents, db=db)
    return {"ok": True, "synced": count, "mode": "ingest"}
