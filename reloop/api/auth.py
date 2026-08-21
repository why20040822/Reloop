"""认证路由: 飞书扫码登录 + 当前用户信息。

扫码流程(前端配合):
  GET  /auth/feishu/url?redirect_uri=<前端回调地址>  -> 授权页 URL
  GET  /auth/feishu/qrcode?redirect_uri=...          -> 登录二维码(SVG)
  用户扫码确认 -> 飞书重定向 redirect_uri?code=...
  POST /auth/feishu/login {code}                     -> {token, user}
  此后请求带 X-Auth-Token: <token>

TTC 私域人才库同步:
  Token 统一由服务端 .env 的 BRAINX_TTC_TALENT_AUTH_TOKEN 提供(不再由用户粘贴绑定),
  所有用户共用同一数据源、各自只看到自己隔离的人才池。详见 POST /sync/ttc。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, get_current_user
from reloop.db.models import (
    TalentProfile,
    User,
)
from reloop.modules.auth.feishu import (
    create_session_token,
    feishu_auth,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


class FeishuLoginBody(BaseModel):
    code: str = ""


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


@router.get("/me", summary="当前登录用户信息(含人才池规模)")
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
    }
