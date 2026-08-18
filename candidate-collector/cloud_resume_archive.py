"""Private OSS resume-file archive for authorized browser captures.

The extension receives a short-lived PUT URL only. Long-lived OSS credentials
and upload-session signing secrets remain on the ECS host.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field, field_validator

from cloud_sync.client import CloudSyncClient
from plugin_auth import AuthenticatedActor


MAX_RESUME_BYTES = int(os.getenv("OSS_RESUME_MAX_BYTES", str(20 * 1024 * 1024)))
UPLOAD_TTL_SECONDS = int(os.getenv("OSS_RESUME_UPLOAD_TTL_SECONDS", "300"))
ALLOWED_EXTENSIONS = {".pdf": "application/pdf", ".doc": "application/msword", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


class ResumeUploadRequest(BaseModel):
    platform: str = Field(default="maimai", max_length=64)
    source_candidate_id: str = Field(min_length=1, max_length=255)
    source_url: str = Field(default="", max_length=4000)
    file_name: str = Field(min_length=1, max_length=512)
    page_session_id: str = Field(default="", max_length=255)
    plugin_version: str = Field(default="", max_length=32)

    @field_validator("platform")
    @classmethod
    def only_maimai(cls, value: str) -> str:
        if value.strip().lower() != "maimai":
            raise ValueError("当前仅支持脉脉简历文件")
        return "maimai"

    @field_validator("source_candidate_id")
    @classmethod
    def clean_candidate_id(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9._~=-]+", value):
            raise ValueError("候选人标识格式无效")
        return value

    @field_validator("file_name")
    @classmethod
    def allowed_file_name(cls, value: str) -> str:
        value = PurePosixPath(value.replace("\\", "/")).name.strip()
        if not value or len(value) > 255:
            raise ValueError("文件名无效")
        if PurePosixPath(value).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("仅支持 PDF、DOC、DOCX 简历文件")
        return value


class ResumeUploadComplete(BaseModel):
    session_token: str = Field(min_length=20, max_length=4096)
    file_size: int = Field(gt=0, le=MAX_RESUME_BYTES)
    sha256: str = Field(min_length=64, max_length=64)

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        value = value.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("SHA-256 格式无效")
        return value


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少 OSS 配置：{name}")
    return value


def _session_secret() -> bytes:
    return _required("OT_PLUGIN_SESSION_SECRET").encode("utf-8")


def _encode_session(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=")
    signature = hmac.new(_session_secret(), body, hashlib.sha256).digest()
    return body.decode("ascii") + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def _decode_session(token: str) -> dict[str, Any]:
    try:
        body_text, signature_text = token.split(".", 1)
        body = body_text.encode("ascii")
        padding = b"=" * (-len(body) % 4)
        expected = hmac.new(_session_secret(), body, hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature_text.encode("ascii") + b"=" * (-len(signature_text) % 4))
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("invalid signature")
        data = json.loads(base64.urlsafe_b64decode(body + padding))
        if int(data["expires_at"]) < int(datetime.now(UTC).timestamp()):
            raise ValueError("expired")
        return data
    except Exception as exc:
        raise RuntimeError("上传会话无效或已过期") from exc


class OSSResumeArchive:
    """Issues short upload URLs and indexes completed private OSS objects."""

    def __init__(self, client: CloudSyncClient | None = None) -> None:
        self.client = client or CloudSyncClient()

    @staticmethod
    def _bucket():
        try:
            import oss2
        except ImportError as exc:  # pragma: no cover - exercised in deployment
            raise RuntimeError("服务器尚未安装 oss2 依赖") from exc
        endpoint = _required("OSS_ENDPOINT")
        bucket_name = _required("OSS_BUCKET")
        access_key_id = _required("OSS_ACCESS_KEY_ID")
        access_key_secret = _required("OSS_ACCESS_KEY_SECRET")
        return oss2.Bucket(oss2.Auth(access_key_id, access_key_secret), endpoint, bucket_name), bucket_name

    def create_upload(self, request: ResumeUploadRequest, actor: AuthenticatedActor) -> dict[str, Any]:
        bucket, bucket_name = self._bucket()
        now = datetime.now(UTC)
        extension = PurePosixPath(request.file_name).suffix.lower()
        object_key = "resumes/maimai/{:%Y/%m}/{}{}".format(now, secrets.token_hex(20), extension)
        expires_at = int((now + timedelta(seconds=UPLOAD_TTL_SECONDS)).timestamp())
        request_id = secrets.token_urlsafe(18)
        session = _encode_session({
            "request_id": request_id,
            "object_key": object_key,
            "bucket": bucket_name,
            "platform": request.platform,
            "source_candidate_id": request.source_candidate_id,
            "source_url": request.source_url,
            "file_name": request.file_name,
            "page_session_id": request.page_session_id or request_id,
            "plugin_version": request.plugin_version,
            "user_id": actor.user_id,
            "plugin_session_id": actor.session_id,
            "device_id": actor.device_id,
            "expires_at": expires_at,
        })
        return {
            "ok": True,
            "request_id": request_id,
            # The signed URL is valid briefly, but OSS rejects a second PUT
            # once the random object key has been written successfully.
            "upload_url": bucket.sign_url(
                "PUT", object_key, UPLOAD_TTL_SECONDS,
                headers={"x-oss-forbid-overwrite": "true"}, slash_safe=True,
            ),
            "session_token": session,
            "expires_at": expires_at,
            "max_bytes": MAX_RESUME_BYTES,
        }

    @staticmethod
    def _sha256_object(bucket: Any, object_key: str) -> str:
        """Hash a private OSS object in bounded memory before indexing it."""
        response = bucket.get_object(object_key)
        digest = hashlib.sha256()
        try:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        return digest.hexdigest()

    def complete_upload(self, request: ResumeUploadComplete, actor: AuthenticatedActor) -> dict[str, Any]:
        session = _decode_session(request.session_token)
        if (
            int(session.get("user_id") or 0) != actor.user_id
            or str(session.get("plugin_session_id") or "") != actor.session_id
            or str(session.get("device_id") or "") != actor.device_id
        ):
            raise RuntimeError("上传会话与当前登录设备不匹配")
        bucket, bucket_name = self._bucket()
        if session.get("bucket") != bucket_name:
            raise RuntimeError("上传目标不匹配")
        try:
            meta = bucket.get_object_meta(session["object_key"])
            actual_size = int(meta.headers.get("Content-Length", "0"))
        except Exception as exc:
            raise RuntimeError("OSS 中未找到已上传的简历文件") from exc
        if actual_size != request.file_size or actual_size > MAX_RESUME_BYTES:
            raise RuntimeError("简历文件大小校验失败")
        actual_sha256 = self._sha256_object(bucket, session["object_key"])
        if not hmac.compare_digest(actual_sha256, request.sha256):
            raise RuntimeError("简历文件 SHA-256 校验失败")

        # Reuse a previously archived identical file, even for another
        # candidate, then remove the fresh temporary duplicate. Different
        # hashes remain separate historical versions for the same candidate.
        existing = self.client.find_resume_file_by_sha256(actual_sha256)
        archive_bucket = bucket_name
        archive_object_key = session["object_key"]
        if existing and (existing["oss_bucket"], existing["oss_object_key"]) != (bucket_name, archive_object_key):
            try:
                bucket.delete_object(archive_object_key)
            except Exception as exc:
                raise RuntimeError("重复简历清理失败，未写入索引") from exc
            archive_bucket = existing["oss_bucket"]
            archive_object_key = existing["oss_object_key"]
        content_type = ALLOWED_EXTENSIONS[PurePosixPath(session["file_name"]).suffix.lower()]
        row = {
            "platform": session["platform"],
            "source_candidate_id": session["source_candidate_id"],
            "source_url": session.get("source_url", ""),
            "file_name": session["file_name"],
            "content_type": content_type,
            "file_size": actual_size,
            "sha256": actual_sha256,
            "oss_bucket": archive_bucket,
            "oss_object_key": archive_object_key,
            "first_archived_by_user_id": (
                existing.get("first_archived_by_user_id") if existing else actor.user_id
            ),
        }
        result = self.client.upsert_resume_file(row)
        is_duplicate = bool(existing) or result["action"] != "created"
        self.client.record_activity_event({
            "user_id": actor.user_id,
            "candidate_id": result.get("candidate_id"),
            "resume_file_id": result.get("id"),
            "platform": row["platform"],
            "source_candidate_id": row["source_candidate_id"],
            "action": "resume_seen_duplicate" if is_duplicate else "resume_archived",
            "page_session_id": session["page_session_id"],
            "plugin_version": session.get("plugin_version", ""),
            "metadata": {"file_size": actual_size},
        })
        return {
            "ok": True,
            "action": "duplicate" if is_duplicate else "created",
            "first_archived_by": result.get("first_archived_by_name") or "历史数据／上传人未知",
            "handled_by": actor.name,
            "file": {
                "id": result.get("id"),
                "name": row["file_name"],
                "size": actual_size,
                "sha256": actual_sha256,
                "platform": row["platform"],
            },
        }
