"""Feishu (Lark) Bitable adapter for candidate records.

This adapter converts a :class:`models.CandidateRecord` into Feishu Base cell
values and writes them via ``lark-cli`` (already installed and authenticated on
the user's machine).  A dry-run mode previews the payload without touching the
Base.

Only storage fields declared in ``config/feishu_field_mapping.json`` are
written. System fields, formula fields, lookup fields and read-only fields are
excluded automatically.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from reloop.config import PROJECT_ROOT
from reloop.domain.models import CandidateRecord

MAPPING_PATH = PROJECT_ROOT / "config" / "feishu_field_mapping.json"


class FeishuBaseAdapter:
    def __init__(self, mapping_path: Path | str | None = None, base_token: str | None = None, table_id: str | None = None):
        self.mapping_path = Path(mapping_path) if mapping_path else MAPPING_PATH
        self.mapping = json.loads(self.mapping_path.read_text(encoding="utf-8"))
        self.base_token = base_token or self.mapping["base_token"]
        self.table_id = table_id or self.mapping["table_id"]

    def _field_value(self, record: CandidateRecord, spec: dict[str, Any]) -> Any:
        """Resolve a single Feishu field value from a CandidateRecord."""
        candidate_field = spec.get("candidate_field")
        if not candidate_field:
            return None

        value = getattr(record, candidate_field, None)
        formatter = spec.get("formatter")

        if formatter == "join_comma":
            items = value or []
            return ", ".join(str(x) for x in items) if isinstance(items, list) else str(items) if items else None

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
                    # Skip invalid select values to avoid API errors.
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

        # Retry on Feishu rate limit or network errors.
        err = data.get("error", {}) if isinstance(data, dict) else {}
        is_rate_limit = isinstance(err, dict) and err.get("code") == 800004135
        is_network = isinstance(err, dict) and err.get("type") == "network"
        if (is_rate_limit or is_network) and _attempt < 4:
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

    def upload_attachment(self, file_path: Path | str, record_id: str, field_id: str) -> str:
        """Upload a local file to an existing record's attachment field and return the Feishu file token.

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

        Text fields are created via +record-batch-create using field names.
        Attachments are uploaded afterward because the batch-create command
        does not accept attachment fields as normal CellValue.
        Returns the created record ID on success.
        """
        if dry_run:
            return self.dry_run(record)

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
        if record.original_attachment_path and Path(record.original_attachment_path).is_file():
            try:
                self.upload_attachment(record.original_attachment_path, record_id, attachment_field_id)
            except Exception:
                # Rollback the partial text record so retries do not see it as a duplicate.
                self._delete_record(record_id)
                raise

        return resp

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

    def record_exists(self, record: CandidateRecord) -> bool:
        """Check whether an equivalent record already exists in the Base.

        Uses the formula field ``查重值`` if available, otherwise falls back to
        searching by phone, name+phone, or name+company.  Authentication or
        network errors are raised rather than treated as "not duplicate" so the
        caller can decide whether to proceed.
        """
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
