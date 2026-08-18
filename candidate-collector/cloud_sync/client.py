"""MySQL client for the cloud sync layer.

Provides connection helpers, idempotent upserts, and simple query helpers
for the unified cloud RDS (MySQL) instance.
"""
from __future__ import annotations

import json
import hashlib
import logging
from contextlib import contextmanager
from typing import Any, Iterator

import pymysql
from pymysql.cursors import DictCursor

from .alerts import alert_sync_error
from .config import RDS_SYNC_BATCH_SIZE, RDS_SYNC_DRY_RUN, build_conn_kwargs

logger = logging.getLogger(__name__)


class UpsertError(RuntimeError):
    """Raised when one or more rows fail during an upsert (R7：禁止静默吞).

    Carries partial stats so callers can see what did land before the failure.
    """

    def __init__(self, message: str, *, stats: dict[str, int], failures: list[str]):
        super().__init__(message)
        self.stats = stats
        self.failures = failures


def _memory_id(row: dict[str, Any]) -> str:
    """Generate a stable idempotency key from project + source + content."""
    import hashlib

    raw = f"{row.get('project_id', '')}:{row.get('source', '')}:{row.get('content_text', '')}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


@contextmanager
def get_conn() -> Iterator[pymysql.Connection]:
    """Yield a MySQL connection and commit/rollback automatically."""
    conn = pymysql.connect(**build_conn_kwargs())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class CloudSyncClient:
    """Thin wrapper around pymysql for candidate and memory upserts."""

    def __init__(self) -> None:
        self.dry_run = RDS_SYNC_DRY_RUN

    def ensure_schema(self, schema_sql_path: str | None = None) -> None:
        """Apply pending migrations (R1：结构变更只走 migrations）。

        ``schema_sql_path`` 参数保留仅为向后兼容，已忽略——
        schema.sql 已作废，唯一真相源是 cloud_sync/migrations/。
        """
        if self.dry_run:
            print("[dry-run] would apply migrations")
            return
        from .migrate import apply_all

        applied = apply_all()
        if applied:
            logger.info("ensure_schema applied migrations: %s", applied)

    # ── Plugin identities and device sessions ─────────────────────

    def create_local_plugin_user(
        self, *, name: str, email: str, password_hash: str,
    ) -> dict[str, Any] | None:
        """Create a pending local account, returning None for duplicate email."""
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                try:
                    cur.execute(
                        "INSERT INTO plugin_users "
                        "(email, password_hash, name, approval_status, last_login_at) "
                        "VALUES (%s, %s, %s, 'pending', UTC_TIMESTAMP())",
                        (email, password_hash, name),
                    )
                except pymysql.err.IntegrityError as exc:
                    if exc.args and exc.args[0] == 1062:
                        return None
                    raise
                cur.execute(
                    "SELECT id, email, name, avatar_url, approval_status "
                    "FROM plugin_users WHERE id = LAST_INSERT_ID() LIMIT 1"
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_plugin_user_by_email(self, email: str) -> dict[str, Any] | None:
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(
                    "SELECT id, email, name, avatar_url, approval_status, password_hash "
                    "FROM plugin_users WHERE email = %s LIMIT 1",
                    (email,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def touch_plugin_user_login(self, user_id: int) -> None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE plugin_users SET last_login_at = UTC_TIMESTAMP(), "
                    "updated_at = UTC_TIMESTAMP() WHERE id = %s",
                    (user_id,),
                )

    def list_plugin_users(self) -> list[dict[str, Any]]:
        """List reviewable accounts without returning password hashes."""
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(
                    "SELECT id, email, name, avatar_url, approval_status, "
                    "created_at, updated_at, last_login_at "
                    "FROM plugin_users WHERE email IS NOT NULL "
                    "ORDER BY FIELD(approval_status, 'pending', 'enabled', 'disabled'), "
                    "created_at DESC"
                )
                return [dict(row) for row in cur.fetchall()]

    def set_plugin_user_status(self, user_id: int, status: str) -> bool:
        with get_conn() as conn:
            with conn.cursor() as cur:
                affected = cur.execute(
                    "UPDATE plugin_users SET approval_status = %s, "
                    "updated_at = UTC_TIMESTAMP() WHERE id = %s AND email IS NOT NULL",
                    (status, user_id),
                )
                return affected == 1

    def upsert_plugin_user(self, identity: dict[str, str]) -> dict[str, Any]:
        sql = """
        INSERT INTO plugin_users (feishu_open_id, name, avatar_url, last_login_at)
        VALUES (%s, %s, %s, UTC_TIMESTAMP())
        ON DUPLICATE KEY UPDATE
            name = VALUES(name), avatar_url = VALUES(avatar_url),
            last_login_at = UTC_TIMESTAMP(), updated_at = UTC_TIMESTAMP()
        """
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(sql, (identity["open_id"], identity["name"], identity.get("avatar_url", "")))
                cur.execute(
                    "SELECT id, feishu_open_id AS open_id, name, avatar_url, approval_status "
                    "FROM plugin_users WHERE feishu_open_id = %s LIMIT 1",
                    (identity["open_id"],),
                )
                return dict(cur.fetchone())

    def update_plugin_user_approval(self, user_id: int, status: str, base_record_id: str = "") -> None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE plugin_users SET approval_status = %s, "
                    "base_record_id = COALESCE(NULLIF(%s, ''), base_record_id), updated_at = UTC_TIMESTAMP() "
                    "WHERE id = %s",
                    (status, base_record_id, user_id),
                )

    def create_login_code(self, code_hash: str, user_id: int, expires_at: Any) -> None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO plugin_login_codes (code_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                    (code_hash, user_id, expires_at),
                )

    def consume_login_code(self, code_hash: str, now: Any) -> dict[str, Any] | None:
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(
                    "SELECT user_id FROM plugin_login_codes WHERE code_hash = %s "
                    "AND used_at IS NULL AND expires_at > %s FOR UPDATE",
                    (code_hash, now),
                )
                code = cur.fetchone()
                if not code:
                    return None
                cur.execute(
                    "UPDATE plugin_login_codes SET used_at = %s WHERE code_hash = %s AND used_at IS NULL",
                    (now, code_hash),
                )
                if cur.rowcount != 1:
                    return None
                cur.execute(
                    "SELECT id, feishu_open_id AS open_id, name, avatar_url, approval_status "
                    "FROM plugin_users WHERE id = %s LIMIT 1",
                    (code["user_id"],),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def create_plugin_session(self, row: dict[str, Any]) -> dict[str, Any]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO plugin_sessions "
                    "(id, user_id, device_id, access_token_hash, refresh_token_hash, "
                    "access_expires_at, refresh_expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (row["id"], row["user_id"], row["device_id"], row["access_token_hash"],
                     row["refresh_token_hash"], row["access_expires_at"], row["refresh_expires_at"]),
                )
        return dict(row)

    @staticmethod
    def _session_select() -> str:
        return (
            "SELECT s.id, s.user_id, s.device_id, s.access_expires_at, s.refresh_expires_at, "
            "u.id AS user_id, u.email AS user_email, u.name AS user_name, "
            "u.avatar_url AS user_avatar_url, u.approval_status AS user_approval_status "
            "FROM plugin_sessions s JOIN plugin_users u ON u.id = s.user_id "
        )

    def get_session_by_access_hash(self, token_hash: str, now: Any) -> dict[str, Any] | None:
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(
                    self._session_select() +
                    "WHERE s.access_token_hash = %s AND s.revoked_at IS NULL "
                    "AND s.access_expires_at > %s LIMIT 1",
                    (token_hash, now),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def rotate_plugin_session(self, refresh_hash: str, updates: dict[str, Any], now: Any) -> dict[str, Any] | None:
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(
                    "SELECT id FROM plugin_sessions WHERE refresh_token_hash = %s "
                    "AND revoked_at IS NULL AND refresh_expires_at > %s FOR UPDATE",
                    (refresh_hash, now),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute(
                    "UPDATE plugin_sessions SET access_token_hash=%s, refresh_token_hash=%s, "
                    "access_expires_at=%s, refresh_expires_at=%s, updated_at=UTC_TIMESTAMP() "
                    "WHERE id=%s AND refresh_token_hash=%s",
                    (updates["access_token_hash"], updates["refresh_token_hash"],
                     updates["access_expires_at"], updates["refresh_expires_at"], row["id"], refresh_hash),
                )
                if cur.rowcount != 1:
                    return None
                cur.execute(self._session_select() + "WHERE s.id = %s LIMIT 1", (row["id"],))
                stored = cur.fetchone()
                return dict(stored) if stored else None

    def revoke_plugin_session(self, session_id: str) -> None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE plugin_sessions SET revoked_at = UTC_TIMESTAMP() "
                    "WHERE id = %s AND revoked_at IS NULL",
                    (session_id,),
                )

    def record_activity_event(self, row: dict[str, Any]) -> bool:
        raw_key = "|".join(str(row.get(key) or "") for key in (
            "user_id", "resume_file_id", "candidate_id", "action", "page_session_id"
        ))
        event_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        with get_conn() as conn:
            with conn.cursor() as cur:
                affected = cur.execute(
                    "INSERT IGNORE INTO plugin_activity_events "
                    "(event_key, user_id, candidate_id, resume_file_id, platform, source_candidate_id, "
                    "action, page_session_id, plugin_version, metadata_json) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (event_key, row["user_id"], row.get("candidate_id"), row.get("resume_file_id"),
                     row.get("platform") or "", row.get("source_candidate_id"), row["action"],
                     row["page_session_id"], row.get("plugin_version") or "",
                     json.dumps(row.get("metadata") or {}, ensure_ascii=False)),
                )
                return affected == 1

    def upsert_candidates(
        self,
        rows: list[dict[str, Any]],
        batch_size: int = RDS_SYNC_BATCH_SIZE,
    ) -> dict[str, int]:
        """Upsert candidate rows into cloud_candidates.

        Args:
            rows: List of dicts with keys matching cloud_candidates columns.
            batch_size: Commit every N rows.

        Returns:
            {"inserted": int, "updated": int, "errors": int}

        Raises:
            UpsertError: 任何一行失败即抛出（R7：错误不得静默吞），
                异常携带 stats 与 failures 明细，并已触发 ERROR 日志 + 飞书告警。
        """
        if not rows:
            return {"inserted": 0, "updated": 0, "errors": 0}

        inserted = updated = errors = 0
        failures: list[str] = []
        upsert_sql = """
        INSERT INTO cloud_candidates (
            fingerprint, name, platform, source_candidate_id, source_url, source_type, title,
            location, current_company, current_role, phone, email,
            undergraduate_school, expected_salary, experiences_json,
            education_json, keywords_json, raw_text, review_status,
            attachment_path, attachment_sha256, collected_at, parsed_json,
            first_collected_by_user_id, activity_score, activity_signals,
            owner, visibility, starred, last_active_at,
            quality_score, missing_fields, expected_title, opportunity_intent
        ) VALUES (
            %(fingerprint)s, %(name)s, %(platform)s, %(source_candidate_id)s, %(source_url)s,
            %(source_type)s, %(title)s, %(location)s, %(current_company)s,
            %(current_role)s, %(phone)s, %(email)s, %(undergraduate_school)s,
            %(expected_salary)s, %(experiences_json)s, %(education_json)s,
            %(keywords_json)s, %(raw_text)s, %(review_status)s,
            %(attachment_path)s, %(attachment_sha256)s, %(collected_at)s,
            %(parsed_json)s, %(first_collected_by_user_id)s, %(activity_score)s,
            %(activity_signals)s, %(owner)s, %(visibility)s, %(starred)s,
            %(last_active_at)s,
            %(quality_score)s, %(missing_fields)s, %(expected_title)s, %(opportunity_intent)s
        )
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            current_company = VALUES(current_company),
            current_role = VALUES(current_role),
            source_candidate_id = VALUES(source_candidate_id),
            phone = VALUES(phone),
            email = VALUES(email),
            raw_text = VALUES(raw_text),
            review_status = VALUES(review_status),
            attachment_sha256 = VALUES(attachment_sha256),
            collected_at = VALUES(collected_at),
            parsed_json = VALUES(parsed_json),
            activity_score = GREATEST(activity_score, VALUES(activity_score)),
            activity_signals = JSON_MERGE_PATCH(
                COALESCE(activity_signals, JSON_OBJECT()),
                COALESCE(VALUES(activity_signals), JSON_OBJECT())
            ),
            owner = COALESCE(VALUES(owner), owner),
            visibility = visibility,
            starred = GREATEST(starred, VALUES(starred)),
            last_active_at = CASE
                WHEN last_active_at IS NULL THEN VALUES(last_active_at)
                WHEN VALUES(last_active_at) IS NULL THEN last_active_at
                ELSE GREATEST(last_active_at, VALUES(last_active_at))
            END,
            quality_score = VALUES(quality_score),
            missing_fields = VALUES(missing_fields),
            expected_title = COALESCE(VALUES(expected_title), expected_title),
            opportunity_intent = COALESCE(VALUES(opportunity_intent), opportunity_intent),
            updated_at = NOW()
        """

        if self.dry_run:
            print(f"[dry-run] would upsert {len(rows)} candidates")
            return {"inserted": len(rows), "updated": 0, "errors": 0}

        with get_conn() as conn:
            with conn.cursor() as cur:
                for i in range(0, len(rows), batch_size):
                    batch = rows[i : i + batch_size]
                    for row in batch:
                        try:
                            prepared = dict(row)
                            prepared.setdefault("first_collected_by_user_id", None)
                            prepared.setdefault("activity_score", 0)
                            prepared.setdefault("activity_signals", "{}")
                            prepared.setdefault("owner", None)
                            prepared.setdefault("visibility", "team")
                            prepared.setdefault("starred", False)
                            prepared.setdefault("last_active_at", None)
                            prepared.setdefault("quality_score", None)
                            prepared.setdefault("missing_fields", None)
                            prepared.setdefault("expected_title", None)
                            prepared.setdefault("opportunity_intent", None)
                            affected = cur.execute(upsert_sql, prepared)
                            # pymysql: 1 = insert, 2 = update (for ON DUPLICATE KEY UPDATE)
                            if affected == 1:
                                inserted += 1
                            else:
                                updated += 1
                        except Exception as exc:
                            errors += 1
                            failures.append(f"fingerprint={row.get('fingerprint')}: {exc}")
                    conn.commit()

        stats = {"inserted": inserted, "updated": updated, "errors": errors}
        if errors:
            alert_sync_error(
                "cloud_candidates 写入失败",
                f"{errors}/{len(rows)} 行失败（inserted={inserted} updated={updated}）。"
                + "；".join(failures[:5]),
            )
            raise UpsertError(
                f"upsert_candidates: {errors}/{len(rows)} rows failed",
                stats=stats,
                failures=failures,
            )
        return stats

    def upsert_resume_file(self, row: dict[str, Any]) -> dict[str, Any]:
        """Index one immutable OSS resume object and link it when possible."""
        if self.dry_run:
            return {"action": "created", "id": None}
        sql = """
        INSERT INTO candidate_resume_files (
            candidate_id, platform, source_candidate_id, source_url, file_name,
            content_type, file_size, sha256, oss_bucket, oss_object_key,
            first_archived_by_user_id
        ) VALUES (
            (SELECT id FROM cloud_candidates
             WHERE platform = %(platform)s AND source_candidate_id = %(source_candidate_id)s
             ORDER BY updated_at DESC LIMIT 1),
            %(platform)s, %(source_candidate_id)s, %(source_url)s, %(file_name)s,
            %(content_type)s, %(file_size)s, %(sha256)s, %(oss_bucket)s, %(oss_object_key)s,
            %(first_archived_by_user_id)s
        )
        ON DUPLICATE KEY UPDATE
            candidate_id = COALESCE(VALUES(candidate_id), candidate_id),
            source_url = VALUES(source_url),
            file_name = VALUES(file_name),
            content_type = VALUES(content_type),
            file_size = VALUES(file_size),
            oss_bucket = VALUES(oss_bucket),
            oss_object_key = VALUES(oss_object_key),
            updated_at = NOW()
        """
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                prepared = dict(row)
                prepared.setdefault("first_archived_by_user_id", None)
                affected = cur.execute(sql, prepared)
                cur.execute(
                    "SELECT f.id, f.candidate_id, f.first_archived_by_user_id, "
                    "COALESCE(u.name, '历史数据／上传人未知') AS first_archived_by_name "
                    "FROM candidate_resume_files f LEFT JOIN plugin_users u "
                    "ON u.id = f.first_archived_by_user_id WHERE f.platform = %s "
                    "AND f.source_candidate_id = %s AND f.sha256 = %s",
                    (row["platform"], row["source_candidate_id"], row["sha256"]),
                )
                stored = cur.fetchone() or {}
        return {
            "action": "created" if affected == 1 else "updated",
            "id": stored.get("id"),
            "candidate_id": stored.get("candidate_id"),
            "first_archived_by_user_id": stored.get("first_archived_by_user_id"),
            "first_archived_by_name": stored.get("first_archived_by_name"),
        }

    def find_resume_file_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        """Return one existing private OSS location for an identical file."""
        if self.dry_run:
            return None
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(
                    "SELECT f.id, f.candidate_id, f.oss_bucket, f.oss_object_key, "
                    "f.first_archived_by_user_id, "
                    "COALESCE(u.name, '历史数据／上传人未知') AS first_archived_by_name "
                    "FROM candidate_resume_files f LEFT JOIN plugin_users u "
                    "ON u.id = f.first_archived_by_user_id "
                    "WHERE f.sha256 = %s ORDER BY f.id ASC LIMIT 1",
                    (sha256,),
                )
                return cur.fetchone()

    def link_resume_files(self, candidate_id: int, platform: str, source_candidate_id: str) -> None:
        if not source_candidate_id or self.dry_run:
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE candidate_resume_files SET candidate_id = %s "
                    "WHERE candidate_id IS NULL AND platform = %s AND source_candidate_id = %s",
                    (candidate_id, platform, source_candidate_id),
                )

    def upsert_memories(
        self,
        rows: list[dict[str, Any]],
        batch_size: int = RDS_SYNC_BATCH_SIZE,
    ) -> dict[str, int]:
        """Upsert memory rows into memories.

        Rows must contain at least: project_id, source, content_type, content_text.
        """
        if not rows:
            return {"inserted": 0, "updated": 0, "errors": 0}

        inserted = updated = errors = 0
        upsert_sql = """
        INSERT INTO memories (
            project_id, source, content_type, content_text, metadata, source_record_id
        ) VALUES (
            %(project_id)s, %(source)s, %(content_type)s, %(content_text)s,
            %(metadata)s, %(source_record_id)s
        )
        ON DUPLICATE KEY UPDATE
            content_text = VALUES(content_text),
            metadata = VALUES(metadata),
            updated_at = NOW()
        """

        if self.dry_run:
            print(f"[dry-run] would upsert {len(rows)} memories")
            return {"inserted": len(rows), "updated": 0, "errors": 0}

        with get_conn() as conn:
            with conn.cursor() as cur:
                for i in range(0, len(rows), batch_size):
                    batch = rows[i : i + batch_size]
                    for row in batch:
                        # Ensure idempotency key exists.
                        if not row.get("source_record_id"):
                            row["source_record_id"] = _memory_id(row)
                        # Serialize metadata dict to JSON string for pymysql.
                        if isinstance(row.get("metadata"), dict):
                            row["metadata"] = json.dumps(row["metadata"], ensure_ascii=False)
                        try:
                            affected = cur.execute(upsert_sql, row)
                            if affected == 1:
                                inserted += 1
                            else:
                                updated += 1
                        except Exception as exc:
                            errors += 1
                            logger.error("memory upsert failed id=%s: %s", row.get("source_record_id"), exc)
                    conn.commit()

        if errors:
            # memories 链路按既定 scope 不抛出（见 DATA_GOVERNANCE 不做清单），
            # 但 R7 要求不得静默：ERROR 日志 + 飞书告警。
            alert_sync_error("memories 同步出现行级失败", f"{errors}/{len(rows)} 行失败")
        return {"inserted": inserted, "updated": updated, "errors": errors}

    def count_candidates(self) -> int:
        """Return total candidate count in cloud_candidates."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM cloud_candidates")
                return cur.fetchone()[0]

    def count_memories(self) -> int:
        """Return total memory count in memories."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM memories")
                return cur.fetchone()[0]

    def list_recent_candidates(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent candidates as a list of dicts."""
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(
                    "SELECT * FROM cloud_candidates ORDER BY collected_at DESC LIMIT %s",
                    (limit,),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_candidate(self, fingerprint: str) -> dict[str, Any] | None:
        """Return one cloud candidate by its stable fingerprint."""
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(
                    "SELECT * FROM cloud_candidates WHERE fingerprint = %s LIMIT 1",
                    (fingerprint,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    # ── Embeddings / semantic search ────────────────────────────────

    def ensure_embedding_column(self) -> None:
        """Add embedding columns to ``memories`` for pre-existing databases.

        CREATE TABLE IF NOT EXISTS does not alter an existing table, so we
        add the columns explicitly and ignore duplicate-column errors.
        """
        if self.dry_run:
            print("[dry-run] would ensure embedding columns")
            return
        alters = [
            "ALTER TABLE memories ADD COLUMN embedding JSON",
            "ALTER TABLE memories ADD COLUMN embedding_model VARCHAR(128)",
            "ALTER TABLE memories ADD COLUMN embedded_at DATETIME",
        ]
        with get_conn() as conn:
            with conn.cursor() as cur:
                for stmt in alters:
                    try:
                        cur.execute(stmt)
                    except (pymysql.err.ProgrammingError, pymysql.err.OperationalError) as exc:
                        if "Duplicate column" in str(exc) or "already exists" in str(exc):
                            continue
                        raise

    def list_memories_without_embedding(
        self, limit: int = 500, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return memories that still need an embedding."""
        sql = (
            "SELECT id, content_text FROM memories WHERE embedding IS NULL"
        )
        params: list[Any] = []
        if project_id:
            sql += " AND project_id = %s"
            params.append(project_id)
        sql += " ORDER BY id LIMIT %s"
        params.append(limit)
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]

    def update_memory_embeddings(self, updates: list[tuple[int, str, str]]) -> int:
        """Persist embeddings. ``updates`` = [(memory_id, embedding_json, model), ...]."""
        if not updates:
            return 0
        if self.dry_run:
            print(f"[dry-run] would update {len(updates)} memory embeddings")
            return len(updates)
        sql = (
            "UPDATE memories SET embedding = %s, embedding_model = %s, "
            "embedded_at = NOW() WHERE id = %s"
        )
        count = 0
        with get_conn() as conn:
            with conn.cursor() as cur:
                for memory_id, embedding_json, model in updates:
                    cur.execute(sql, (embedding_json, model, memory_id))
                    count += cur.rowcount
            conn.commit()
        return count

    def get_memory_embeddings(
        self, project_id: str | None = None, limit: int = 5000
    ) -> list[dict[str, Any]]:
        """Return id/source/content/embedding for memories that have an embedding."""
        sql = (
            "SELECT id, project_id, source, content_type, "
            "LEFT(content_text, 600) AS content_text, embedding "
            "FROM memories WHERE embedding IS NOT NULL"
        )
        params: list[Any] = []
        if project_id:
            sql += " AND project_id = %s"
            params.append(project_id)
        sql += " LIMIT %s"
        params.append(limit)
        with get_conn() as conn:
            with conn.cursor(DictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
