"""Feishu application login, TTC official callback binding, and current user APIs."""

from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from reloop.api.deps import get_current_user, get_db
from reloop.config import settings
from reloop.db.models import TalentProfile, User
from reloop.modules.auth.feishu import create_session_token, feishu_auth
from reloop.modules.auth.ttc import TTCAuthError, build_login_url, validate_token
from reloop.modules.auth.vault import seal_user_token, unseal_user_token

router = APIRouter(prefix="/auth", tags=["认证"])


class FeishuLoginBody(BaseModel):
    code: str = ""


class TTCBindBody(BaseModel):
    token: str = ""


def _public_auth_base_url() -> str:
    base_url = settings.auth_public_base_url.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=503, detail="登录回调尚未配置。请在 .env 设置 BRAINX_AUTH_PUBLIC_BASE_URL 为已登记的公网 HTTPS 域名。")
    return base_url


def _callback_url(provider: str) -> str:
    return f"{_public_auth_base_url()}/auth/{provider}/callback"


def _redirect_to_spa(request: Request, route: str) -> RedirectResponse:
    query = urlencode(list(request.query_params.multi_items()))
    target = f"{_public_auth_base_url()}/#/{route}"
    return RedirectResponse(f"{target}?{query}" if query else target, status_code=302)


@router.get("/feishu/url", summary="获取飞书扫码授权页 URL")
def feishu_login_url():
    if not feishu_auth.enabled:
        raise HTTPException(status_code=400, detail="飞书登录未配置(BRAINX_FEISHU_APP_ID/SECRET)")
    return {"url": feishu_auth.login_url(_callback_url("feishu"))}


@router.get("/feishu/qrcode", summary="登录二维码(SVG 图片, 内容为飞书授权页 URL)")
def feishu_qrcode():
    if not feishu_auth.enabled:
        raise HTTPException(status_code=400, detail="飞书登录未配置(BRAINX_FEISHU_APP_ID/SECRET)")
    import io
    import segno

    buf = io.BytesIO()
    segno.make(feishu_auth.login_url(_callback_url("feishu")), error="m").save(buf, kind="svg", scale=6, border=2, dark="#1a1a1a")
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


@router.get("/feishu/callback", include_in_schema=False)
def feishu_callback(request: Request):
    return _redirect_to_spa(request, "auth/callback")


@router.post("/feishu/login", summary="授权码换登录态(扫码回调后调用)")
def feishu_login(body: FeishuLoginBody, db: Session = Depends(get_db)):
    if not feishu_auth.enabled:
        raise HTTPException(status_code=400, detail="飞书登录未配置(BRAINX_FEISHU_APP_ID/SECRET)")
    if not body.code:
        raise HTTPException(status_code=400, detail="缺少授权码 code")
    info = feishu_auth.login_by_code(body.code)
    if not info:
        raise HTTPException(status_code=401, detail="飞书登录失败(code 无效或已过期)")
    user_id = f"fs_{info.get('open_id')}"
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        user = User(user_id=user_id, display_name=info.get("name") or "飞书用户")
        db.add(user)
    else:
        user.display_name = info.get("name") or user.display_name
    db.commit()
    return {"token": create_session_token(user_id), "user": {"user_id": user_id, "display_name": user.display_name}}


@router.get("/ttc/login-url", summary="获取 TTC 官方飞书登录地址")
def ttc_login_url():
    try:
        return {"url": build_login_url(_callback_url("ttc"))}
    except TTCAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ttc/callback", include_in_schema=False)
def ttc_callback(request: Request):
    return _redirect_to_spa(request, "ttc/callback")


@router.post("/ttc/bind", summary="校验并自动绑定 TTC 登录态，随后同步个人库")
def bind_ttc_account(body: TTCBindBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.user_id == settings.guest_owner_id:
        raise HTTPException(status_code=401, detail="请先完成 RE:LOOP 飞书登录，再连接个人人才库")
    try:
        profile = validate_token(body.token)
    except TTCAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    token = body.token.strip()
    user.ttc_auth_token = seal_user_token(token)
    if profile["space_id"]:
        user.ttc_space_id = profile["space_id"]
    if profile["display_name"]:
        user.ttc_bound_name = profile["display_name"]
    db.commit()
    from reloop.modules.sync.client import talent_sync_service
    sync_id = talent_sync_service.sync_for_user_async(user.user_id, auth_token=token, source="owned")
    return {"ok": True, "sync_id": sync_id, "display_name": user.ttc_bound_name or user.display_name, "space_id": user.ttc_space_id}


@router.get("/me", summary="当前登录用户信息(含人才池规模)")
def me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pool_count = db.query(TalentProfile).filter(TalentProfile.owner_user_id == user.user_id).count()
    try:
        ttc_connected = bool(unseal_user_token(user.ttc_auth_token))
    except Exception:  # noqa: BLE001
        ttc_connected = False
    return {"user_id": user.user_id, "display_name": user.display_name, "pool_count": pool_count, "ttc_connected": ttc_connected if user.user_id != settings.guest_owner_id else False, "ttc_space_id": user.ttc_space_id, "ttc_bound_name": user.ttc_bound_name}
