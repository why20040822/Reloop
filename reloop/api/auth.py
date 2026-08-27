"""Feishu application login, TTC official callback binding, and current user APIs."""

from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from reloop.api.deps import get_current_user, get_db, require_authenticated_non_guest_user
from reloop.config import settings
from reloop.db.models import TalentProfile, User
from reloop.modules.auth.feishu import create_session_token, feishu_auth
from reloop.modules.auth.flows import (
    FLOW_COOKIE_NAME,
    browser_binding,
    consume_flow_token,
    issue_flow_token,
)
from reloop.modules.auth.ttc import TTCAuthError, build_login_url, validate_token
from reloop.modules.auth.vault import VaultError, seal_user_token, unseal_user_token

router = APIRouter(prefix="/auth", tags=["认证"])


class FeishuLoginBody(BaseModel):
    handle: str = ""


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


def _redirect_to_spa(route: str, **params: str) -> RedirectResponse:
    query = urlencode(params)
    target = f"{_public_auth_base_url()}/#/{route}"
    return RedirectResponse(f"{target}?{query}" if query else target, status_code=302)


def _set_flow_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        FLOW_COOKIE_NAME,
        value,
        max_age=settings.auth_flow_ttl_seconds,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/auth",
    )


def _issue_oauth_state(
    request: Request,
    response: Response,
    db: Session,
    *,
    provider: str,
    user_id: str | None = None,
) -> str:
    browser_secret, _ = browser_binding(request.cookies.get(FLOW_COOKIE_NAME))
    state = issue_flow_token(
        db,
        provider=provider,
        purpose="oauth_state",
        browser_secret=browser_secret,
        ttl_seconds=settings.auth_flow_ttl_seconds,
        user_id=user_id,
    )
    _set_flow_cookie(response, browser_secret)
    return state


def _callback_secret(request: Request, *names: str) -> str:
    values = request.scope.get("state", {}).get("auth_callback_secrets", {})
    for name in names:
        value = values.get(name)
        if value:
            return value
    return ""


@router.get("/feishu/url", summary="获取飞书扫码授权页 URL")
def feishu_login_url(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    if not feishu_auth.enabled:
        raise HTTPException(status_code=400, detail="飞书登录未配置(BRAINX_FEISHU_APP_ID/SECRET)")
    state = _issue_oauth_state(request, response, db, provider="feishu")
    return {"url": feishu_auth.login_url(_callback_url("feishu"), state=state)}


@router.get("/feishu/qrcode", summary="登录二维码(SVG 图片, 内容为飞书授权页 URL)")
def feishu_qrcode(request: Request, db: Session = Depends(get_db)):
    if not feishu_auth.enabled:
        raise HTTPException(status_code=400, detail="飞书登录未配置(BRAINX_FEISHU_APP_ID/SECRET)")
    import io
    import segno

    browser_secret, _ = browser_binding(request.cookies.get(FLOW_COOKIE_NAME))
    state = issue_flow_token(
        db,
        provider="feishu",
        purpose="oauth_state",
        browser_secret=browser_secret,
        ttl_seconds=settings.auth_flow_ttl_seconds,
    )
    buf = io.BytesIO()
    segno.make(feishu_auth.login_url(_callback_url("feishu"), state=state), error="m").save(
        buf, kind="svg", scale=6, border=2, dark="#1a1a1a"
    )
    response = Response(content=buf.getvalue(), media_type="image/svg+xml")
    _set_flow_cookie(response, browser_secret)
    return response


@router.get("/feishu/callback", include_in_schema=False)
def feishu_callback(request: Request, db: Session = Depends(get_db)):
    state = request.query_params.get("state")
    flow = consume_flow_token(
        db,
        raw_token=state,
        provider="feishu",
        purpose="oauth_state",
        browser_secret=request.cookies.get(FLOW_COOKIE_NAME),
    )
    if flow is None:
        return _redirect_to_spa("auth/callback", status="error", error="invalid_state")
    code = _callback_secret(request, "code")
    if not code:
        db.commit()
        return _redirect_to_spa("auth/callback", status="error", error="missing_code")
    info = feishu_auth.login_by_code(code)
    open_id = info.get("open_id") if info else None
    if not isinstance(open_id, str) or not open_id:
        db.commit()
        return _redirect_to_spa("auth/callback", status="error", error="login_failed")
    user_id = f"fs_{open_id}"
    user = db.query(User).filter(User.user_id == user_id).first()
    display_name = info.get("name") or "飞书用户"
    if user is None:
        user = User(user_id=user_id, display_name=display_name)
        db.add(user)
    else:
        user.display_name = display_name or user.display_name
    handle = issue_flow_token(
        db,
        provider="feishu",
        purpose="session_handle",
        browser_secret=request.cookies.get(FLOW_COOKIE_NAME) or "",
        ttl_seconds=settings.auth_handle_ttl_seconds,
        user_id=user_id,
        payload={"display_name": user.display_name},
    )
    db.commit()
    return _redirect_to_spa("auth/callback", status="success", handle=handle)


@router.post("/feishu/login", summary="一次性句柄换登录态")
def feishu_login(body: FeishuLoginBody, request: Request, db: Session = Depends(get_db)):
    if not feishu_auth.enabled:
        raise HTTPException(status_code=400, detail="飞书登录未配置(BRAINX_FEISHU_APP_ID/SECRET)")
    flow = consume_flow_token(
        db,
        raw_token=body.handle,
        provider="feishu",
        purpose="session_handle",
        browser_secret=request.cookies.get(FLOW_COOKIE_NAME),
    )
    user_id = flow.get("user_id") if flow else None
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="登录句柄无效或已过期")
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="登录用户不存在")
    db.commit()
    return {"token": create_session_token(user_id), "user": {"user_id": user_id, "display_name": user.display_name}}


@router.get("/ttc/login-url", summary="获取 TTC 官方飞书登录地址")
def ttc_login_url(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_authenticated_non_guest_user),
):
    try:
        state = _issue_oauth_state(
            request,
            response,
            db,
            provider="ttc",
            user_id=user.user_id,
        )
        return {"url": build_login_url(_callback_url("ttc"), state=state)}
    except TTCAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ttc/callback", include_in_schema=False)
def ttc_callback(request: Request, db: Session = Depends(get_db)):
    flow = consume_flow_token(
        db,
        raw_token=request.query_params.get("state"),
        provider="ttc",
        purpose="oauth_state",
        browser_secret=request.cookies.get(FLOW_COOKIE_NAME),
    )
    if flow is None:
        return _redirect_to_spa("ttc/callback", status="error", error="invalid_state")
    token = _callback_secret(request, "token", "access_token").strip()
    if not token:
        db.commit()
        return _redirect_to_spa("ttc/callback", status="error", error="missing_token")
    user_id = flow.get("user_id")
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None or user.user_id == settings.guest_owner_id:
        db.commit()
        return _redirect_to_spa("ttc/callback", status="error", error="invalid_user")
    try:
        sealed_token = seal_user_token(token)
    except VaultError:
        db.commit()
        return _redirect_to_spa("ttc/callback", status="error", error="credential_unavailable")
    try:
        profile = validate_token(token)
    except TTCAuthError:
        db.commit()
        return _redirect_to_spa("ttc/callback", status="error", error="invalid_token")
    user.ttc_auth_token = sealed_token
    if profile.get("space_id"):
        user.ttc_space_id = profile["space_id"]
    if profile.get("display_name"):
        user.ttc_bound_name = profile["display_name"]
    db.commit()
    from reloop.modules.sync.client import talent_sync_service

    talent_sync_service.sync_for_user_async(user.user_id, auth_token=token, source="owned")
    return _redirect_to_spa("ttc/callback", status="success")


@router.post("/ttc/bind", summary="校验并自动绑定 TTC 登录态，随后同步个人库")
def bind_ttc_account(body: TTCBindBody, db: Session = Depends(get_db), user: User = Depends(require_authenticated_non_guest_user)):
    token = body.token.strip()
    try:
        sealed_token = seal_user_token(token)
    except VaultError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        profile = validate_token(token)
    except TTCAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user.ttc_auth_token = sealed_token
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
