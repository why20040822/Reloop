"""Authenticated RDS gateway for the ot小插件 browser extension.

The service accepts authorized visible-page text and issues short-lived OSS
upload sessions for original resume files. It deliberately excludes local
file/OCR endpoints, and never treats browser file paths as server paths.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from cloud_capture import BrowserCapturePayload
from cloud_ingestion import cloud_target_info, import_capture_to_cloud
from cloud_resume_archive import OSSResumeArchive, ResumeUploadComplete, ResumeUploadRequest
from cloud_sync.client import CloudSyncClient
from plugin_auth import (
    AuthError,
    AuthenticatedActor,
    PluginAuthService,
    verify_admin_credentials,
)


EXTENSION_ORIGIN = os.getenv(
    "OT_PLUGIN_EXTENSION_ORIGIN",
    "chrome-extension://eigjnfagcfofpmenjbddbdgggjmldifn",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ot小插件云端导入",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[EXTENSION_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=86400,
)


auth_service = PluginAuthService()
admin_basic = HTTPBasic(auto_error=False)


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    device_id: str = Field(min_length=8, max_length=255)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=8, max_length=255)


class SessionRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=512)


class ApprovalUpdate(BaseModel):
    status: Literal["pending", "enabled", "disabled"]


def _auth_http_error(exc: AuthError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def require_authenticated_actor(
    authorization: str = Header(default="", alias="Authorization"),
    x_ot_token: str = Header(default="", alias="X-OT-Token"),
) -> AuthenticatedActor:
    # 旧版插件静态 token 兼容：X-OT-Token 与 OT_PLUGIN_API_TOKEN 匹配即放行，
    # 避免强制所有已安装插件立刻升级到登录会话流程。
    expected = os.getenv("OT_PLUGIN_API_TOKEN", "").strip()
    if expected and x_ot_token and hmac.compare_digest(x_ot_token.strip(), expected):
        return AuthenticatedActor(
            user_id=0,
            session_id="legacy-static-token",
            device_id="extension",
            email="legacy@plugin.local",
            name="静态令牌插件",
            avatar_url="",
            approval_status="enabled",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _auth_http_error(AuthError("请先登录插件账号", code="login_required"))
    try:
        return auth_service.authenticate(token.strip())
    except AuthError as exc:
        raise _auth_http_error(exc) from exc


def require_enabled_actor(
    actor: AuthenticatedActor = Depends(require_authenticated_actor),
) -> AuthenticatedActor:
    if actor.approval_status == "pending":
        raise HTTPException(status_code=403, detail={
            "code": "approval_pending", "message": "等待管理员审核启用",
        })
    if actor.approval_status != "enabled":
        raise HTTPException(status_code=403, detail={
            "code": "account_disabled", "message": "该插件账号已停用",
        })
    return actor


def _run_import(payload: BrowserCapturePayload, actor: AuthenticatedActor) -> dict[str, Any]:
    try:
        return import_capture_to_cloud(payload, actor=actor)
    except Exception as exc:
        logger.exception("cloud candidate write failed")
        raise HTTPException(
            status_code=502,
            detail=f"云数据库写入失败：{str(exc)[:180]}",
        ) from exc


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "ot小插件云端导入"}


@app.post("/auth/register")
def auth_register(payload: RegisterRequest) -> dict[str, Any]:
    try:
        return {"ok": True, **auth_service.register(
            name=payload.name,
            email=payload.email,
            password=payload.password,
            device_id=payload.device_id,
        )}
    except AuthError as exc:
        raise _auth_http_error(exc) from exc


@app.post("/auth/login")
def auth_login(payload: LoginRequest) -> dict[str, Any]:
    try:
        return {"ok": True, **auth_service.login(
            email=payload.email,
            password=payload.password,
            device_id=payload.device_id,
        )}
    except AuthError as exc:
        raise _auth_http_error(exc) from exc


@app.post("/auth/session/refresh")
def auth_session_refresh(payload: SessionRefreshRequest) -> dict[str, Any]:
    try:
        return {"ok": True, **auth_service.refresh_session(payload.refresh_token)}
    except AuthError as exc:
        raise _auth_http_error(exc) from exc


@app.get("/auth/me")
def auth_me(actor: AuthenticatedActor = Depends(require_authenticated_actor)) -> dict[str, Any]:
    return {"ok": True, "user": {
        "name": actor.name, "email": actor.email, "avatar_url": actor.avatar_url,
        "approval_status": actor.approval_status,
    }}


@app.post("/auth/logout")
def auth_logout(actor: AuthenticatedActor = Depends(require_authenticated_actor)) -> dict[str, Any]:
    auth_service.logout(actor)
    return {"ok": True}


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(admin_basic),
) -> str:
    if credentials is None or not verify_admin_credentials(
        credentials.username, credentials.password,
    ):
        raise HTTPException(
            status_code=401,
            detail="需要管理员登录",
            headers={"WWW-Authenticate": 'Basic realm="ot plugin admin", charset="UTF-8"'},
        )
    return credentials.username


ADMIN_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ot插件账号审核</title>
  <style>
    :root{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",sans-serif;color:#1d1d1f;background:#f5f5f7}
    *{box-sizing:border-box}body{margin:0}.wrap{max-width:980px;margin:0 auto;padding:48px 24px 80px}
    h1{font-size:34px;margin:0 0 8px}.sub{color:#6e6e73;margin:0 0 30px}.card{background:#fff;border:1px solid #e5e5ea;border-radius:20px;box-shadow:0 12px 36px #0000000d;overflow:hidden}
    .toolbar{padding:18px 22px;border-bottom:1px solid #eee;display:flex;align-items:center;justify-content:space-between}.count{font-weight:650}.refresh{border:0;border-radius:10px;padding:9px 14px;background:#0071e3;color:#fff;cursor:pointer}
    table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:15px 18px;border-bottom:1px solid #eee;font-size:14px}th{color:#6e6e73;font-weight:600;background:#fafafa}.status{font-weight:650}.pending{color:#b25c00}.enabled{color:#12843d}.disabled{color:#c3262e}
    .actions{display:flex;gap:7px}.actions button{border:1px solid #d2d2d7;border-radius:9px;background:#fff;padding:7px 10px;cursor:pointer}.actions button.primary{background:#0071e3;color:#fff;border-color:#0071e3}.empty,.error{padding:38px;text-align:center;color:#6e6e73}.error{color:#c3262e}
    @media(max-width:760px){.wrap{padding:24px 12px}h1{font-size:28px}table,thead,tbody,tr,th,td{display:block}thead{display:none}tr{padding:12px;border-bottom:1px solid #eee}td{border:0;padding:4px 10px}.actions{margin-top:10px}}
  </style>
</head>
<body><main class="wrap">
  <h1>ot插件账号审核</h1>
  <p class="sub">同事注册后会先处于待审批状态。只有你点“启用”，插件才允许导入候选人与归档简历。</p>
  <section class="card">
    <div class="toolbar"><span id="count" class="count">正在读取…</span><button id="refresh" class="refresh">刷新</button></div>
    <div id="content"><div class="empty">正在加载账号</div></div>
  </section>
</main>
<script>
const labels={pending:'待审批',enabled:'已启用',disabled:'已停用'};
const content=document.getElementById('content');const count=document.getElementById('count');
function cell(value){const td=document.createElement('td');td.textContent=value??'—';return td}
async function setStatus(id,status){
  const res=await fetch(`./admin/users/${id}/status`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});
  if(!res.ok){throw new Error('更新失败，请刷新后重试')}await load();
}
function actionButton(text,status,id,primary=false){const b=document.createElement('button');b.textContent=text;if(primary)b.className='primary';b.onclick=()=>setStatus(id,status).catch(showError);return b}
function render(users){content.textContent='';count.textContent=`共 ${users.length} 个账号`;
  if(!users.length){content.innerHTML='<div class="empty">暂时没有人申请账号</div>';return}
  const table=document.createElement('table');const head=document.createElement('thead');head.innerHTML='<tr><th>姓名</th><th>邮箱</th><th>状态</th><th>申请时间</th><th>操作</th></tr>';table.append(head);
  const body=document.createElement('tbody');for(const user of users){const tr=document.createElement('tr');tr.append(cell(user.name),cell(user.email));
    const st=cell(labels[user.approval_status]||user.approval_status);st.className=`status ${user.approval_status}`;tr.append(st,cell(user.created_at));
    const actions=document.createElement('td');actions.className='actions';actions.append(actionButton('启用','enabled',user.id,true),actionButton('待审批','pending',user.id),actionButton('停用','disabled',user.id));tr.append(actions);body.append(tr)}table.append(body);content.append(table)
}
function showError(error){content.innerHTML='';const div=document.createElement('div');div.className='error';div.textContent=error.message||'读取失败';content.append(div)}
async function load(){content.innerHTML='<div class="empty">正在加载账号</div>';try{const res=await fetch('./admin/users',{cache:'no-store'});if(!res.ok)throw new Error('无权访问或服务器未配置管理员账号');const data=await res.json();render(data.users||[])}catch(error){showError(error)}}
document.getElementById('refresh').onclick=load;load();
</script></body></html>"""


@app.get("/admin", response_class=HTMLResponse)
def admin_page(_: str = Depends(require_admin)) -> HTMLResponse:
    return HTMLResponse(
        ADMIN_HTML,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@app.get("/admin/users")
def admin_users(_: str = Depends(require_admin)) -> dict[str, Any]:
    return {"ok": True, "users": auth_service.repository.list_plugin_users()}


@app.post("/admin/users/{user_id}/status")
def admin_user_status(
    user_id: int,
    payload: ApprovalUpdate,
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    if not auth_service.repository.set_plugin_user_status(user_id, payload.status):
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"ok": True, "user_id": user_id, "status": payload.status}


@app.get("/target")
def target(actor: AuthenticatedActor = Depends(require_enabled_actor)) -> dict[str, Any]:
    return {"ok": True, "target": cloud_target_info()}


@app.get("/recent")
def recent(limit: int = Query(default=10, ge=1, le=50),
           actor: AuthenticatedActor = Depends(require_enabled_actor)) -> dict[str, Any]:
    try:
        rows = CloudSyncClient().list_recent_candidates(limit)
    except Exception as exc:
        logger.exception("cloud candidate read failed")
        raise HTTPException(status_code=502, detail="云数据库读取失败") from exc
    for row in rows:
        row.pop("raw_text", None)
        row.pop("parsed_json", None)
    return {"ok": True, "target": cloud_target_info(), "candidates": rows}


@app.post("/import-browser-capture")
def import_browser_capture_endpoint(payload: BrowserCapturePayload,
                                    actor: AuthenticatedActor = Depends(require_enabled_actor)) -> dict[str, Any]:
    return _run_import(payload, actor)


@app.post("/capture")
def capture_endpoint(payload: BrowserCapturePayload,
                     actor: AuthenticatedActor = Depends(require_enabled_actor)) -> dict[str, Any]:
    # Legacy collector actions use the same cloud write path so a freshly
    # imported extension does not depend on a local SQLite service.
    return _run_import(payload, actor)


@app.post("/resume-upload-sessions")
def create_resume_upload_session(payload: ResumeUploadRequest,
                                 actor: AuthenticatedActor = Depends(require_enabled_actor)) -> dict[str, Any]:
    try:
        return OSSResumeArchive().create_upload(payload, actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("resume upload session creation failed")
        raise HTTPException(status_code=502, detail=f"简历归档不可用：{str(exc)[:180]}") from exc


@app.post("/resume-upload-sessions/complete")
def complete_resume_upload(payload: ResumeUploadComplete,
                           actor: AuthenticatedActor = Depends(require_enabled_actor)) -> dict[str, Any]:
    try:
        return OSSResumeArchive().complete_upload(payload, actor)
    except Exception as exc:
        logger.exception("resume upload completion failed")
        raise HTTPException(status_code=502, detail=f"简历归档失败：{str(exc)[:180]}") from exc
