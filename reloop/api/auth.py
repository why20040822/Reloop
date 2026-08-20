"""认证路由: 飞书扫码登录 + 当前用户信息 + TTC 私域人才库绑定。

扫码流程(前端配合):
  GET  /auth/feishu/url?redirect_uri=<前端回调地址>  -> 授权页 URL
  GET  /auth/feishu/qrcode?redirect_uri=...          -> 登录二维码(SVG)
  用户扫码确认 -> 飞书重定向 redirect_uri?code=...
  POST /auth/feishu/login {code}                     -> {token, user}
  此后请求带 X-Auth-Token: <token>

TTC 绑定(每个用户拉自己的私域人才库):
  TTC 网关 Token 是 TTC 自签 JWT(其站点飞书登录后签发, ~90 天有效),
  Reloop 的飞书应用无法代签 —— 因此扫码登录后, 用户粘贴一次自己
  app.ttcadvisory.com 上的 Authorization Token 做绑定:
  POST /auth/ttc/bind {token, space_id?}   (自动认领该 TTC 身份下的存量数据)
  POST /sync/ttc                           (用绑定身份拉取自己的私域库)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, get_current_user
from reloop.db.models import (
    FeedbackLog,
    InteractionRecord,
    Position,
    Recommendation,
    TalentProfile,
    User,
)
from reloop.modules.auth.feishu import (
    create_session_token,
    decode_ttc_jwt_unverified,
    feishu_auth,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


class FeishuLoginBody(BaseModel):
    code: str = ""


class TtcBindBody(BaseModel):
    # app.ttcadvisory.com F12 -> Network -> Authorization: Bearer xxx 里的 xxx
    token: str
    space_id: Optional[str] = None


@router.get("/feishu/url", summary="获取飞书扫码授权页 URL")
def feishu_login_url(redirect_uri: str = Query(..., description="扫码成功后的前端回调地址")):
    if not feishu_auth.enabled:
        raise HTTPException(status_code=400, detail="飞书登录未配置(BRAINX_FEISHU_APP_ID/SECRET)")
    return {"url": feishu_auth.login_url(redirect_uri)}


@router.get("/feishu/qrcode", summary="登录二维码(SVG 图片, 内容为飞书授权页 URL)")
def feishu_qrcode(redirect_uri: str = Query(...)):
    if not feishu_auth.enabled:
        raise HTTPException(status_code=400, detail="飞书登录未配置(BRAINX_FEISHU_APP_ID/SECRET)")
    import io

    import segno

    url = feishu_auth.login_url(redirect_uri)
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#1a1a1a")
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


@router.post("/feishu/login", summary="授权码换登录态(扫码回调后调用)")
def feishu_login(
    body: FeishuLoginBody,
    db: Session = Depends(get_db),
):
    if not feishu_auth.enabled:
        raise HTTPException(status_code=400, detail="飞书登录未配置(BRAINX_FEISHU_APP_ID/SECRET)")
    if not body.code:
        raise HTTPException(status_code=400, detail="缺少授权码 code")
    info = feishu_auth.login_by_code(body.code)
    if not info:
        raise HTTPException(status_code=401, detail="飞书登录失败(code 无效或已过期)")
    open_id = info.get("open_id")
    name = info.get("name") or "飞书用户"
    user_id = f"fs_{open_id}"
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        user = User(user_id=user_id, display_name=name)
        db.add(user)
    else:
        user.display_name = name or user.display_name
    db.commit()
    token = create_session_token(user_id)
    return {"token": token, "user": {"user_id": user_id, "display_name": user.display_name}}


@router.get("/me", summary="当前登录用户信息(含 TTC 绑定状态)")
def me(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pool_count = (
        db.query(TalentProfile)
        .filter(TalentProfile.owner_user_id == user.user_id)
        .count()
    )
    return {
        "user_id": user.user_id,
        "display_name": user.display_name,
        "pool_count": pool_count,
        "ttc_bound": bool(user.ttc_auth_token),
        "ttc_bound_name": user.ttc_bound_name,
        "ttc_space_id": user.ttc_space_id,
    }


@router.post("/ttc/bind", summary="绑定 TTC 私域人才库 Token(一次性, ~90 天有效)")
def ttc_bind(
    body: TtcBindBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """绑定后自动认领该 TTC 身份下已同步的存量数据(按 open_id 迁移 owner)。"""
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="缺少 TTC Token")
    claims = decode_ttc_jwt_unverified(token)
    custom = (claims.get("CustomData") or {}) if claims else {}
    bound_name = custom.get("nick_name") or ""
    ttc_open_id = custom.get("open_id") or ""
    if not ttc_open_id:
        raise HTTPException(status_code=400, detail="Token 解析失败: 未包含身份信息(请复制完整 Bearer Token)")

    # 认领存量数据: TTC open_id 名下的数据迁移到当前登录用户
    migrated = 0
    if ttc_open_id and ttc_open_id != user.user_id:
        for model in (TalentProfile, Position, InteractionRecord, Recommendation, FeedbackLog):
            migrated += (
                db.query(model)
                .filter(model.owner_user_id == ttc_open_id)
                .update({model.owner_user_id: user.user_id}, synchronize_session=False)
            )

    user.ttc_auth_token = token
    user.ttc_bound_name = bound_name
    if body.space_id:
        user.ttc_space_id = body.space_id.strip()
    db.commit()
    logger.info("[auth] ttc bind user=%s bound=%s migrated=%d", user.user_id, bound_name, migrated)
    return {
        "ok": True,
        "bound_name": bound_name,
        "migrated_rows": migrated,
        "space_id": user.ttc_space_id,
    }
