"""Feishu (Lark) Bitable adapter for candidate records.

This adapter converts a :class:`models.CandidateRecord` into Feishu Base cell
values and writes them via ``lark-cli`` (already installed and authenticated on
the user's machine).  A dry-run mode previews the payload without touching the
Base.

Only storage fields declared in the active mapping file
(``config/feishu_field_mapping_candidate.json``，可用 ``FEISHU_MAPPING_FILE``
覆盖；otto2 回退表用 ``config/feishu_field_mapping_otto1.json``) are
written. System fields, formula fields, lookup fields and read-only fields are
excluded automatically.
"""
from __future__ import annotations

import hashlib
import json
import os
import copy
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from models import CandidateRecord


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ttc_sync.lock import ExclusiveSyncLock, LockHeldError  # noqa: E402


DEFAULT_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "feishu_field_mapping_candidate.json"
)
MAPPING_PATH = Path(
    os.getenv("FEISHU_MAPPING_FILE", DEFAULT_MAPPING_PATH)
).expanduser()
TTC_SYNC_LOCK_PATH = REPO_ROOT / "data" / "ttc_sync.lock"
FALLBACK_SYNC_LOCK_PATH = REPO_ROOT / "data" / "candidate_collector_otto2.lock"
READ_ONLY_CLI_COMMANDS = frozenset({"+field-list", "+record-list", "+record-search"})


class AttachmentUploadError(RuntimeError):
    """A text row exists, but its original resume still needs uploading."""

    def __init__(self, record_id: str, table_id: str, cause: Exception) -> None:
        super().__init__(f"record {record_id} created but attachment upload failed: {cause}")
        self.record_id = record_id
        self.table_id = table_id
        self.cause = cause


class FeishuBaseAdapter:
    def __init__(
        self,
        mapping_path: Path | str | None = None,
        base_token: str | None = None,
        table_id: str | None = None,
        validate_schema: bool = True,
    ):
        self.mapping_path = Path(mapping_path) if mapping_path else MAPPING_PATH
        self.mapping = json.loads(self.mapping_path.read_text(encoding="utf-8"))
        # base_token 优先级: 显式传参 > 环境变量 TTC_FEISHU_BASE_TOKEN > 配置文件。
        # 配置文件里只允许放占位符,真实 token 一律走 .env(禁止硬编码进仓库)。
        self.base_token = (
            base_token
            or os.getenv("TTC_FEISHU_BASE_TOKEN")
            or os.getenv("FEISHU_BASE_TOKEN")
            or self.mapping["base_token"]
        )
        self.table_id = table_id or self.mapping["table_id"]
        self.validate_schema = validate_schema
        self._schema_checked = False

    def _field_value(self, record: CandidateRecord, spec: dict[str, Any]) -> Any:
        """Resolve a single Feishu field value from a CandidateRecord."""
        if "constant" in spec:
            return spec["constant"]
        candidate_field = spec.get("candidate_field")
        if not candidate_field:
            return None

        value = getattr(record, candidate_field, None)
        formatter = spec.get("formatter")

        if formatter == "join_comma":
            items = value or []
            return ", ".join(str(x) for x in items) if isinstance(items, list) else str(items) if items else None

        if formatter == "ttc_pid":
            return record.ttc_pid

        if formatter == "education_summary":
            if not record.education:
                return None
            parts = [
                record.education.school,
                record.education.degree,
                str(record.education.graduation_year) if record.education.graduation_year else None,
                record.education.major,
            ]
            return " ".join(p for p in parts if p)

        if formatter == "major":
            return record.education.major if record.education else None

        if formatter == "degree":
            return self._normalize_degree(record.education.degree if record.education else None, spec)

        if formatter == "boolean_to_select":
            text = str(value or "").lower()
            if any(w in text for w in ["是", "yes", "true", "看机会", "考虑", "在职-考虑"]):
                return "是"
            if any(w in text for w in ["否", "no", "false", "不看", "暂不考虑", "不考虑"]):
                return "否"
            return spec.get("fallback", "无信息")

        if formatter == "infer_job_type":
            return self._infer_job_type(record, spec)

        if formatter == "parser_metadata":
            meta = {
                "parser": record.parser_name,
                "version": record.parser_version,
                "confidence": record.parse_confidence,
                "missing_fields": record.missing_fields,
            }
            return json.dumps(meta, ensure_ascii=False, default=str)

        if formatter == "canonical_fingerprint":
            return hashlib.sha256(record.fingerprint_input().encode("utf-8")).hexdigest()

        if formatter == "json":
            return json.dumps(value or {}, ensure_ascii=False, default=str)

        if formatter == "visibility":
            return {"private": "仅自己可见", "team": "组内可见"}.get(str(value), "组内可见")

        if formatter == "ai_profile_summary":
            return self._ai_profile_summary(record)

        if formatter == "work_experience_summary":
            return self._experience_summary(record.work_experiences)

        if formatter == "project_experience_summary":
            return self._experience_summary(record.project_experiences)

        if formatter == "infer_experience_years":
            return self._infer_experience_years(record)

        if formatter == "resume_validity":
            return self._resume_validity(record, spec)

        if formatter == "validity_reason":
            return self._validity_reason(record)

        if isinstance(value, list):
            return ", ".join(str(x) for x in value) if value else None

        if isinstance(value, int):
            return str(value)

        return value

    @staticmethod
    def _normalize_degree(value: str | None, spec: dict[str, Any]) -> str | None:
        if not value:
            return None
        text = value.strip().lower()
        options = spec.get("options", [])
        mapping = {
            "专科": "专科",
            "大专": "专科",
            "本科": "本科",
            "学士": "学士",
            "硕士": "硕士",
            "研究生": "硕士",
            "博士": "博士",
            "其他": "其他",
        }
        for key, mapped in mapping.items():
            if key in text and mapped in options:
                return mapped
        return spec.get("fallback")

    @staticmethod
    def _ai_profile_summary(record: CandidateRecord) -> str:
        parts = [
            f"姓名: {record.name or '未知'}",
            f"当前公司: {record.current_company or '未知'}",
            f"当前岗位: {record.current_title or '未知'}",
            f"工作年限: {record.undergraduate_graduation_year or '未知'}",
            f"技能: {', '.join(record.tech_stack or [])}",
            f"求职意向: {record.expected_title or '未知'}",
            f"是否看机会: {record.opportunity_intent or '未知'}",
        ]
        return "\n".join(parts)

    @staticmethod
    def _experience_summary(experiences: list[Any]) -> str | None:
        if not experiences:
            return None
        summaries = []
        for exp in experiences[:5]:
            if hasattr(exp, "company"):
                parts = [exp.company, exp.role, exp.period]
                summaries.append(" | ".join(p for p in parts if p))
            elif hasattr(exp, "name"):
                parts = [exp.name, exp.role, exp.period]
                summaries.append(" | ".join(p for p in parts if p))
        return "\n".join(summaries) if summaries else None

    @staticmethod
    def _infer_experience_years(record: CandidateRecord) -> float | None:
        if record.undergraduate_graduation_year:
            try:
                return max(0, 2026 - int(record.undergraduate_graduation_year))
            except (TypeError, ValueError):
                pass
        return None

    @staticmethod
    def _resume_validity(record: CandidateRecord, spec: dict[str, Any]) -> str:
        options = spec.get("options", [])
        if not record.name or not record.phone:
            return "不可联系" if "不可联系" in options else spec.get("fallback", "待补全")
        if record.missing_fields:
            return "待补全" if "待补全" in options else spec.get("fallback", "待补全")
        return "可推荐" if "可推荐" in options else spec.get("fallback", "待补全")

    @staticmethod
    def _validity_reason(record: CandidateRecord) -> str | None:
        reasons = []
        if not record.name:
            reasons.append("缺少姓名")
        if not record.phone:
            reasons.append("缺少手机号")
        if not record.current_company:
            reasons.append("缺少当前公司")
        if not record.current_title:
            reasons.append("缺少当前岗位")
        if record.missing_fields:
            reasons.extend(record.missing_fields)
        return "; ".join(reasons) if reasons else None

    @staticmethod
    def _infer_job_type(record: CandidateRecord, spec: dict[str, Any]) -> str:
        """Infer job type from tech stack / current title."""
        text = " ".join(record.tech_stack or []) + " " + (record.current_title or "")
        text = text.lower()
        options = spec.get("options", [])
        # Priority mapping.
        keywords = {
            "算法": ["算法", "machine learning", "ml", "nlp", "cv", "deep learning", "模型", "推荐"],
            "前端": ["前端", "frontend", "react", "vue", "angular"],
            "后端": ["后端", "backend", "java", "go", "python", "服务端"],
            "全栈": ["全栈", "fullstack", "full stack", "全站"],
            "产品": ["产品", "product manager", "产品经理"],
            "infra": ["infra", "sre", "devops", "运维", "基础设施"],
            "爬虫": ["爬虫", "spider", "crawler"],
            "运营": ["运营", "operation"],
        }
        for option, kws in keywords.items():
            if option in options and any(kw in text for kw in kws):
                return option
        return spec.get("fallback", "无匹配标签")

    def build_payload(self, record: CandidateRecord, *, include_attachments: bool = True) -> dict[str, Any]:
        """Return a dict of Feishu field_id -> cell value for this record.

        In dry-run mode this payload is printed/logged but not sent.
        """
        payload: dict[str, Any] = {}
        for key, spec in self.mapping["fields"].items():
            field_id = spec["field_id"]
            value = self._field_value(record, spec)
            if value is None:
                continue
            if spec.get("type") == "attachment":
                if include_attachments and record.original_attachment_path:
                    payload[field_id] = [{"type": "attachment", "file": record.original_attachment_path}]
                continue
            if spec.get("type") in ("select",):
                text = str(value)
                options = spec.get("options", [])
                if options and text not in options:
                    # Use fallback value if available, otherwise skip.
                    fallback = spec.get("fallback")
                    if fallback and fallback in options:
                        text = fallback
                    else:
                        continue
                payload[field_id] = text
                continue
            if spec.get("type") == "multi_select":
                items = value if isinstance(value, list) else [value] if value else []
                options = spec.get("options", [])
                selected = [str(item) for item in items if not options or str(item) in options]
                if selected:
                    payload[field_id] = selected
                continue
            if spec.get("type") == "number":
                try:
                    payload[field_id] = float(value)
                except (TypeError, ValueError):
                    continue
                continue
            if spec.get("type") == "checkbox":
                payload[field_id] = bool(value)
                continue
            if spec.get("type") == "datetime":
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                payload[field_id] = str(value)
                continue
            # Clamp text length to avoid Feishu limits.
            max_len = spec.get("max_length", 100_000)
            text = str(value)
            if len(text) > max_len:
                text = text[:max_len - 3] + "..."
            payload[field_id] = text
        return payload

    def dry_run(self, record: CandidateRecord) -> dict[str, Any]:
        """Return a human-readable description of what would be written."""
        payload = self.build_payload(record)
        # Map field IDs back to names for readability.
        named = {}
        for key, spec in self.mapping["fields"].items():
            if spec["field_id"] in payload:
                val = payload[spec["field_id"]]
                if spec["type"] == "attachment":
                    val = [v.get("file") for v in val] if isinstance(val, list) else val
                named[spec["name"]] = val
        return {
            "base_token": self.base_token,
            "table_id": self.table_id,
            "action": "dry_run",
            "candidate_name": record.name,
            "attachment_sha256": record.attachment_sha256,
            "fields": named,
        }

    def _preflight_schema(self) -> None:
        """Resolve field IDs by name and fail before a write if schema drifted."""
        if self._schema_checked:
            return
        if not self.validate_schema:
            self._schema_checked = True
            return
        response = self._run_cli(
            "+field-list",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--format", "json",
        )
        fields = response.get("data", {}).get("fields", [])
        by_name = {item.get("name"): item for item in fields if isinstance(item, dict)}
        type_aliases = {"multi_select": "select"}
        missing: list[str] = []
        mismatched: list[str] = []
        mapping = copy.deepcopy(self.mapping)
        for key, spec in mapping["fields"].items():
            actual = by_name.get(spec.get("name"))
            if not actual:
                missing.append(spec.get("name") or key)
                continue
            expected_type = type_aliases.get(spec.get("type"), spec.get("type"))
            if actual.get("type") != expected_type:
                mismatched.append(
                    f"{spec.get('name')}: expected {expected_type}, got {actual.get('type')}"
                )
                continue
            spec["field_id"] = actual["id"]
            if actual.get("type") == "select":
                spec["options"] = [
                    option.get("name") for option in actual.get("options", [])
                    if isinstance(option, dict) and option.get("name")
                ]
        if missing or mismatched:
            details = "; ".join(
                (["missing=" + ",".join(missing)] if missing else [])
                + (["type_mismatch=" + ",".join(mismatched)] if mismatched else [])
            )
            raise RuntimeError(f"Feishu table {self.table_id} schema mismatch: {details}")
        self.mapping = mapping
        self._schema_checked = True

    def _run_cli(self, *args: str, cwd: Path | str | None = None, _attempt: int = 1) -> dict[str, Any]:
        cmd = ["lark-cli", "base", *args, "--as", "user"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, cwd=cwd
        )
        if result.returncode != 0:
            raise RuntimeError(f"lark-cli failed: {result.stderr or result.stdout}")
        stdout = result.stdout.strip()
        # Some lark-cli commands default to markdown even when they succeed.
        if stdout.startswith("```"):
            lines = stdout.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stdout = "\n".join(lines)
        if not stdout:
            return {}
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return {"raw_stdout": stdout}

        # Only reads are safe to retry automatically.  A failed write response
        # can mean that Feishu committed the mutation but the acknowledgement
        # was lost, so retrying could create a duplicate row or attachment.
        err = data.get("error", {}) if isinstance(data, dict) else {}
        is_rate_limit = isinstance(err, dict) and err.get("code") == 800004135
        is_network = isinstance(err, dict) and err.get("type") == "network"
        is_ambiguous = is_rate_limit or is_network
        command = args[0] if args else ""
        if is_ambiguous and command not in READ_ONLY_CLI_COMMANDS:
            raise RuntimeError(
                f"Feishu ambiguous write result for {command}; "
                f"refusing automatic retry: {err}"
            )
        if is_ambiguous and _attempt < 4:
            import time
            wait = 2 ** _attempt
            time.sleep(wait)
            return self._run_cli(*args, cwd=cwd, _attempt=_attempt + 1)

        return data

    @staticmethod
    def _extract_attachment_file_token(resp: dict[str, Any]) -> str | None:
        """Best-effort extraction of file_token from +record-upload-attachment response."""
        data = resp.get("data", {})
        # Direct envelope used by some lark-cli versions.
        if isinstance(data, dict):
            token = data.get("file_token") or data.get("token")
            if token:
                return token
            # Nested envelope: data.attachments.{record_id}.{field_id}[*].file_token
            attachments = data.get("attachments", {})
            if isinstance(attachments, dict):
                for rec_id, fields in attachments.items():
                    if isinstance(fields, dict):
                        for fld_id, files in fields.items():
                            if isinstance(files, list) and files:
                                first = files[0]
                                if isinstance(first, dict):
                                    token = first.get("file_token") or first.get("token")
                                    if token:
                                        return token
        return None

    def upload_attachment(
        self,
        file_path: Path | str,
        record_id: str,
        field_id: str,
        *,
        expected_sha256: str | None = None,
    ) -> str:
        """Upload one attachment while holding the shared Feishu write lock."""
        self._preflight_schema()
        is_fallback = self.table_id == self.mapping.get("fallback_table_id")
        with ExclusiveSyncLock(
            FALLBACK_SYNC_LOCK_PATH if is_fallback else TTC_SYNC_LOCK_PATH,
            operation=(
                "candidate-collector-otto2" if is_fallback
                else "candidate-collector"
            ),
        ):
            if expected_sha256 and self._attachment_already_present(
                record_id,
                expected_sha256,
            ):
                return "already-present"
            return self._upload_attachment_unlocked(file_path, record_id, field_id)

    @staticmethod
    def _attachment_cell_has_value(value: Any) -> bool:
        if isinstance(value, list):
            return any(FeishuBaseAdapter._attachment_cell_has_value(item) for item in value)
        if isinstance(value, dict):
            return bool(
                value.get("file_token")
                or value.get("token")
                or value.get("name")
                or value.get("url")
            )
        return bool(value)

    def _attachment_already_present(
        self,
        record_id: str,
        expected_sha256: str,
    ) -> bool:
        """Read back the exact row before appending an attachment on retry."""
        sha_spec = next(
            (
                spec for spec in self.mapping["fields"].values()
                if spec.get("candidate_field") == "attachment_sha256"
                and spec.get("type") == "text"
            ),
            None,
        )
        attachment_spec = next(
            (spec for spec in self.mapping["fields"].values() if spec.get("type") == "attachment"),
            None,
        )
        if not sha_spec or not attachment_spec or not expected_sha256:
            return False
        filter_json = json.dumps(
            {
                "logic": "and",
                "conditions": [[sha_spec["field_id"], "==", expected_sha256]],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        response = self._run_cli(
            "+record-list",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--field-id", sha_spec["field_id"],
            "--field-id", attachment_spec["field_id"],
            "--filter-json", filter_json,
            "--limit", "200",
            "--format", "json",
        )
        envelope = response.get("data", {}) if isinstance(response, dict) else {}
        rows = envelope.get("data", envelope.get("records", [])) if isinstance(envelope, dict) else []
        record_ids = envelope.get("record_id_list", []) if isinstance(envelope, dict) else []
        field_ids = envelope.get("field_id_list", []) if isinstance(envelope, dict) else []
        if not isinstance(rows, list):
            return False
        sha_index = field_ids.index(sha_spec["field_id"]) if sha_spec["field_id"] in field_ids else None
        attachment_index = (
            field_ids.index(attachment_spec["field_id"])
            if attachment_spec["field_id"] in field_ids else None
        )
        for index, row in enumerate(rows):
            row_id = record_ids[index] if index < len(record_ids) else None
            sha_value: Any = None
            attachment_value: Any = None
            if isinstance(row, (list, tuple)):
                if sha_index is not None and sha_index < len(row):
                    sha_value = row[sha_index]
                if attachment_index is not None and attachment_index < len(row):
                    attachment_value = row[attachment_index]
            elif isinstance(row, dict):
                row_id = row.get("record_id") or row.get("id") or row_id
                cells = row.get("fields", row)
                if isinstance(cells, dict):
                    sha_value = cells.get(sha_spec["field_id"], cells.get(sha_spec["name"]))
                    attachment_value = cells.get(
                        attachment_spec["field_id"],
                        cells.get(attachment_spec["name"]),
                    )
            if (
                str(row_id or "") == record_id
                and self._cell_has_exact_text(sha_value, expected_sha256)
                and self._attachment_cell_has_value(attachment_value)
            ):
                return True
        return False

    def _upload_attachment_unlocked(
        self,
        file_path: Path | str,
        record_id: str,
        field_id: str,
    ) -> str:
        """Upload a local file after the caller has acquired the write lock.

        lark-cli's --file argument is documented with relative-path examples and may
        reject absolute paths, so we run the command from the file's parent directory
        and pass only the file name.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Attachment not found: {path}")
        resp = self._run_cli(
            "+record-upload-attachment",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--record-id", record_id,
            "--field-id", field_id,
            "--file", path.name,
            cwd=path.parent,
        )
        file_token = self._extract_attachment_file_token(resp)
        if not file_token:
            raise RuntimeError(f"Attachment upload did not return file_token: {resp}")
        return file_token

    def create_record(self, record: CandidateRecord, *, dry_run: bool = False) -> dict[str, Any]:
        """Create a Feishu Base record for this candidate.

        All writes share the unified engine's process lock.  For TTC records,
        the exact PID lookup and create are therefore one mutually exclusive
        operation too.
        """
        if dry_run:
            return self.dry_run(record)
        self._preflight_schema()
        try:
            with ExclusiveSyncLock(
                TTC_SYNC_LOCK_PATH,
                operation="candidate-collector",
            ):
                return self._create_record_unlocked(record)
        except LockHeldError:
            existing = self._find_existing_source_record(record)
            if existing:
                return {
                    "data": {"record_id_list": [existing]},
                    "idempotent_existing": True,
                    "attachment_uploaded": False,
                    "feishu_table_id": self.table_id,
                    "fallback_reason": "otto1_existing_while_locked",
                }
            return self._create_record_in_fallback(record, reason="otto1_lock_held")
        except RuntimeError as exc:
            if "1254291" not in str(exc):
                raise
            existing = self._find_existing_source_record(record)
            if existing:
                return {
                    "data": {"record_id_list": [existing]},
                    "idempotent_existing": True,
                    "attachment_uploaded": False,
                    "feishu_table_id": self.table_id,
                    "fallback_reason": "otto1_existing_after_conflict",
                }
            return self._create_record_in_fallback(record, reason="otto1_write_conflict")

    def _find_existing_source_record(self, record: CandidateRecord) -> Optional[str]:
        if record.ttc_pid:
            return self.find_existing_ttc_record_id(record)
        return self.find_existing_source_record(record)

    def _create_record_in_fallback(
        self, record: CandidateRecord, *, reason: str
    ) -> dict[str, Any]:
        fallback_table_id = self.mapping.get("fallback_table_id")
        if not fallback_table_id:
            raise LockHeldError("Otto1 is occupied and no fallback table is configured")
        fallback = FeishuBaseAdapter(
            mapping_path=self.mapping_path,
            base_token=self.base_token,
            table_id=fallback_table_id,
            validate_schema=self.validate_schema,
        )
        fallback._preflight_schema()
        with ExclusiveSyncLock(
            FALLBACK_SYNC_LOCK_PATH,
            operation="candidate-collector-otto2",
        ):
            existing_primary = self._find_existing_source_record(record)
            if existing_primary:
                return {
                    "data": {"record_id_list": [existing_primary]},
                    "idempotent_existing": True,
                    "attachment_uploaded": False,
                    "feishu_table_id": self.table_id,
                    "fallback_reason": "otto1_existing_before_fallback",
                }
            response = fallback._create_record_unlocked(record)
        response["feishu_table_id"] = fallback.table_id
        response["fallback_reason"] = reason
        return response

    def _create_record_unlocked(self, record: CandidateRecord) -> dict[str, Any]:
        """Perform one create while the shared TTC/Feishu lock is held."""

        attachment_path = (
            Path(record.original_attachment_path)
            if record.original_attachment_path else None
        )
        if attachment_path and not attachment_path.is_file():
            raise FileNotFoundError(f"Attachment not found: {attachment_path}")

        # Enforce TTC idempotency at the write boundary.  Some ingestion paths
        # make the optional pre-check configurable, so the adapter itself must
        # still prevent a repeated PID from becoming another row.
        if record.source_record_id:
            existing_record_id = (
                self.find_existing_ttc_record_id(record)
                if record.ttc_pid else self.find_existing_source_record(record)
            )
            if existing_record_id:
                attachment_uploaded = False
                if attachment_path:
                    try:
                        if not (
                            record.attachment_sha256
                            and self._attachment_already_present(
                                existing_record_id,
                                record.attachment_sha256,
                            )
                        ):
                            self._upload_attachment_unlocked(
                                attachment_path,
                                existing_record_id,
                                self.attachment_field_id(),
                            )
                        attachment_uploaded = True
                    except Exception as exc:
                        raise AttachmentUploadError(existing_record_id, self.table_id, exc) from exc
                return {
                    "data": {"record_id_list": [existing_record_id]},
                    "idempotent_existing": True,
                    "ttc_pid": record.ttc_pid,
                    "attachment_uploaded": attachment_uploaded,
                    "feishu_table_id": self.table_id,
                }

        payload = self.build_payload(record, include_attachments=False)
        if not payload:
            raise ValueError("No fields to write")

        # Map field_id -> field_name for batch-create (it expects field names).
        id_to_name = {spec["field_id"]: spec["name"] for spec in self.mapping["fields"].values()}
        field_names = [id_to_name[fid] for fid in payload.keys()]
        row_values = list(payload.values())

        batch_json = json.dumps({"fields": field_names, "rows": [row_values]}, ensure_ascii=False)
        resp = self._run_cli(
            "+record-batch-create",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--json", batch_json,
        )

        # Upload attachment if present.
        attachment_field_id = None
        for spec in self.mapping["fields"].values():
            if spec.get("type") == "attachment":
                attachment_field_id = spec["field_id"]
                break
        data = resp.get("data", {})
        record_id = None
        if isinstance(data, dict):
            record_id_list = data.get("record_id_list")
            if isinstance(record_id_list, list) and record_id_list:
                record_id = record_id_list[0]
            records = data.get("records")
            if not record_id and isinstance(records, list) and records:
                record_id = records[0].get("record_id")
        if not record_id:
            raise RuntimeError(f"Batch create did not return a record_id: {resp}")
        if attachment_path:
            if not attachment_field_id:
                raise AttachmentUploadError(
                    record_id,
                    self.table_id,
                    RuntimeError("attachment field is not configured"),
                )
            try:
                self._upload_attachment_unlocked(
                    attachment_path,
                    record_id,
                    attachment_field_id,
                )
            except Exception as exc:
                raise AttachmentUploadError(record_id, self.table_id, exc) from exc

        resp["feishu_table_id"] = self.table_id
        resp["attachment_uploaded"] = bool(attachment_path)
        return resp

    def attachment_field_id(self) -> str:
        self._preflight_schema()
        for spec in self.mapping["fields"].values():
            if spec.get("type") == "attachment":
                return str(spec["field_id"])
        raise RuntimeError("Feishu attachment field is not configured")

    def find_record_id_by_fingerprint(self, record: CandidateRecord) -> str | None:
        """Find the Feishu projection using the canonical ingestion fingerprint."""
        spec = self.mapping["fields"].get("hermes_fingerprint")
        if not spec:
            raise RuntimeError("Feishu mapping is missing hermes_fingerprint")
        fingerprint = hashlib.sha256(record.fingerprint_input().encode("utf-8")).hexdigest()
        response = self._run_cli(
            "+record-search",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--keyword", fingerprint,
            "--search-field", spec["name"],
            "--field-id", spec["name"],
            "--limit", "2",
            "--format", "json",
        )
        ids = (response.get("data") or {}).get("record_id_list") or []
        if len(ids) > 1:
            raise RuntimeError(f"duplicate Feishu projections for fingerprint {fingerprint}")
        return str(ids[0]) if ids else None

    def upsert_record(self, record: CandidateRecord) -> dict[str, Any]:
        """Create or update the unique Feishu projection for a candidate."""
        record_id = self.find_record_id_by_fingerprint(record)
        if not record_id:
            return self.create_record(record)

        payload = self.build_payload(record, include_attachments=False)
        id_to_name = {spec["field_id"]: spec["name"] for spec in self.mapping["fields"].values()}
        named_payload = {id_to_name[field_id]: value for field_id, value in payload.items()}
        response = self._run_cli(
            "+record-upsert",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--record-id", record_id,
            "--json", json.dumps(named_payload, ensure_ascii=False, default=str),
        )
        response.setdefault("data", {})["record_id"] = record_id
        return response

    def _delete_record(self, record_id: str) -> None:
        """Best-effort delete of a record; used for rollback on attachment failure."""
        try:
            self._run_cli(
                "+record-delete",
                "--base-token", self.base_token,
                "--table-id", self.table_id,
                "--record-id", record_id,
                "--yes",
            )
        except Exception:
            pass

    def _has_search_result(self, resp: dict[str, Any]) -> bool:
        """Return True if a record-search response contains at least one record."""
        if not isinstance(resp, dict):
            return False
        data = resp.get("data", {}) or {}
        total = data.get("total")
        if total:
            return True
        records = data.get("data", [])
        return bool(records)

    @staticmethod
    def _search_keyword(*parts: str) -> str:
        """Build a keyword string and clamp it to Feishu's 50-character limit."""
        keyword = " ".join(p for p in parts if p)
        if len(keyword) > 50:
            keyword = keyword[:50]
        return keyword

    def _search_field_name(self, candidate_field: str) -> str | None:
        """Return the Feishu field name used for searching a given candidate field."""
        for spec in self.mapping["fields"].values():
            if spec.get("candidate_field") == candidate_field and spec.get("type") == "text":
                return spec["name"]
        return None

    @staticmethod
    def _cell_has_exact_text(value: Any, expected: str) -> bool:
        """Match a text cell without fuzzy, substring, or case normalization."""
        if isinstance(value, str):
            return value == expected
        if isinstance(value, list):
            return any(
                FeishuBaseAdapter._cell_has_exact_text(item, expected)
                for item in value
            )
        if isinstance(value, dict):
            for key in ("text", "value"):
                if key in value and FeishuBaseAdapter._cell_has_exact_text(
                    value[key], expected
                ):
                    return True
        return False

    @classmethod
    def _exact_match_record_id(
        cls,
        resp: dict[str, Any],
        *,
        field_id: str,
        field_name: str,
        expected: str,
    ) -> Optional[str]:
        """Return the ID of a row whose projected cell exactly equals expected.

        ``lark-cli`` currently returns projected rows as a two-dimensional
        ``data`` array, but older releases returned dictionaries.  Support both
        shapes and fail closed when an exact match has no record identity.
        """
        if not isinstance(resp, dict):
            raise RuntimeError("Unexpected Feishu record-list response")
        if resp.get("error"):
            raise RuntimeError(f"Feishu record-list failed: {resp['error']}")
        envelope = resp.get("data", {}) or {}
        if not isinstance(envelope, dict):
            raise RuntimeError("Unexpected Feishu record-list data envelope")

        rows = envelope.get("data")
        if rows is None:
            rows = envelope.get("records", [])
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected Feishu record-list rows")

        record_ids = envelope.get("record_id_list", [])
        field_ids = envelope.get("field_id_list", [])
        field_names = envelope.get("fields", [])
        column_index: Optional[int] = None
        if isinstance(field_ids, list) and field_id in field_ids:
            column_index = field_ids.index(field_id)
        elif isinstance(field_names, list) and field_name in field_names:
            column_index = field_names.index(field_name)

        exact_record_ids: list[str] = []
        for index, row in enumerate(rows):
            record_id: Optional[str] = None
            value: Any = None
            if isinstance(row, (list, tuple)):
                if column_index is None or column_index >= len(row):
                    raise RuntimeError("Projected Feishu field is missing from row data")
                value = row[column_index]
                if isinstance(record_ids, list) and index < len(record_ids):
                    record_id = record_ids[index]
            elif isinstance(row, dict):
                record_id = row.get("record_id") or row.get("id")
                cells = row.get("fields", row)
                if isinstance(cells, dict):
                    if field_id in cells:
                        value = cells[field_id]
                    elif field_name in cells:
                        value = cells[field_name]
            else:
                raise RuntimeError("Unexpected Feishu record-list row shape")

            if cls._cell_has_exact_text(value, expected):
                if not record_id:
                    raise RuntimeError("Exact TTC match has no Feishu record ID")
                exact_record_ids.append(str(record_id))
        if envelope.get("has_more") or resp.get("has_more"):
            raise RuntimeError(
                "Feishu exact-filter response is incomplete; refusing TTC create"
            )
        if len(exact_record_ids) > 1:
            raise RuntimeError(
                "Multiple exact TTC rows already exist; refusing automatic "
                f"selection: {exact_record_ids}"
            )
        return exact_record_ids[0] if exact_record_ids else None

    def find_existing_ttc_record_id(
        self, record: CandidateRecord
    ) -> Optional[str]:
        """Find an existing TTC row by an exact stable business key.

        Prefer a mapped ``TTC PID`` field when available, then fall back to the
        exact canonical talent URL.  The returned rows are checked locally so a
        server-side filter can never turn a fuzzy match into a duplicate.
        """
        pid = record.ttc_pid
        if not pid:
            return None

        identity_fields: list[tuple[dict[str, Any], str]] = []
        canonical_url = f"https://app.ttcadvisory.com/app/talent/{pid}"
        for key, spec in self.mapping["fields"].items():
            if (
                spec.get("type") == "text"
                and (
                    key == "ttc_pid"
                    or spec.get("name") == "TTC PID"
                    or spec.get("formatter") == "ttc_pid"
                )
            ):
                identity_fields.append((spec, pid))
                break
        if record.source_url:
            for spec in self.mapping["fields"].values():
                if spec.get("type") == "text" and (
                    spec.get("candidate_field") == "source_url"
                    or spec.get("name") == "人才库链接"
                ):
                    identity_fields.append((spec, canonical_url))
                    break

        if not identity_fields:
            raise RuntimeError(
                "TTC dedup requires a mapped TTC PID or 人才库链接 text field"
            )

        for spec, expected in identity_fields:
            filter_json = json.dumps(
                {
                    "logic": "and",
                    "conditions": [[spec["field_id"], "==", expected]],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            resp = self._run_cli(
                "+record-list",
                "--base-token", self.base_token,
                "--table-id", self.table_id,
                "--field-id", spec["field_id"],
                "--filter-json", filter_json,
                "--limit", "200",
                "--format", "json",
            )
            record_id = self._exact_match_record_id(
                resp,
                field_id=spec["field_id"],
                field_name=spec["name"],
                expected=expected,
            )
            if record_id:
                return record_id
        return None

    def find_existing_source_record(self, record: CandidateRecord) -> Optional[str]:
        """Find a non-TTC source by exact normalized talent URL."""
        if not record.source_record_id or not record.source_url:
            return None
        spec = next(
            (
                item for item in self.mapping["fields"].values()
                if item.get("type") == "text" and (
                    item.get("candidate_field") == "source_url"
                    or item.get("name") == "人才库链接"
                )
            ),
            None,
        )
        if not spec:
            raise RuntimeError("Source dedup requires a 人才库链接 text field")
        filter_json = json.dumps(
            {"logic": "and", "conditions": [[spec["field_id"], "==", record.source_url]]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        response = self._run_cli(
            "+record-list",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--field-id", spec["field_id"],
            "--filter-json", filter_json,
            "--limit", "200",
            "--format", "json",
        )
        return self._exact_match_record_id(
            response,
            field_id=spec["field_id"],
            field_name=spec["name"],
            expected=record.source_url,
        )

    def record_exists(self, record: CandidateRecord) -> bool:
        """Check whether an equivalent record already exists in the Base.

        TTC records use exact PID/canonical-link equality exclusively.  Other
        sources retain the legacy phone/name/company search behavior.
        Authentication or network errors are raised rather than treated as
        "not duplicate" so the caller can decide whether to proceed.
        """
        if record.ttc_pid:
            # TTC must never fall back to phone/name matching: those fields are
            # not stable identifiers and legitimately collide across PIDs.
            return self.find_existing_ttc_record_id(record) is not None
        if record.source_record_id and record.source_url:
            return self.find_existing_source_record(record) is not None

        name_field = self._search_field_name("name")
        phone_field = self._search_field_name("phone")
        company_field = self._search_field_name("current_company")

        # Prefer exact phone match.
        if record.phone and phone_field:
            resp = self._run_cli(
                "+record-search",
                "--base-token", self.base_token,
                "--table-id", self.table_id,
                "--keyword", record.phone,
                "--search-field", phone_field,
                "--limit", "1",
                "--format", "json",
            )
            if self._has_search_result(resp):
                return True
        # Strong fallback: name + phone (catches records with empty company).
        if record.name and record.phone and name_field and phone_field:
            resp = self._run_cli(
                "+record-search",
                "--base-token", self.base_token,
                "--table-id", self.table_id,
                "--keyword", self._search_keyword(record.name, record.phone),
                "--search-field", name_field,
                "--search-field", phone_field,
                "--limit", "1",
                "--format", "json",
            )
            if self._has_search_result(resp):
                return True
        # Fallback to name + company.
        if record.name and record.current_company and name_field and company_field:
            resp = self._run_cli(
                "+record-search",
                "--base-token", self.base_token,
                "--table-id", self.table_id,
                "--keyword", self._search_keyword(record.name, record.current_company),
                "--search-field", name_field,
                "--search-field", company_field,
                "--limit", "1",
                "--format", "json",
            )
            if self._has_search_result(resp):
                return True
        # Last resort: name-only match (useful when company/phone are missing).
        if record.name and name_field:
            resp = self._run_cli(
                "+record-search",
                "--base-token", self.base_token,
                "--table-id", self.table_id,
                "--keyword", self._search_keyword(record.name),
                "--search-field", name_field,
                "--limit", "1",
                "--format", "json",
            )
            if self._has_search_result(resp):
                return True
        return False
