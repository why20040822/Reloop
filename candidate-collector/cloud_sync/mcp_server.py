"""MCP server exposing the unified TTC cloud data instance to AI tools.

Runs over stdio and connects **directly** to the cloud RDS MySQL instance, so
it works on any machine that has (a) this repo, (b) the RDS credentials in the
environment / .env, and (c) an outbound route to the RDS endpoint. It does not
depend on the local candidate-collector HTTP service running.

Register with:
    command: <repo>/candidate-collector/.venv/bin/python
    args:    ["-m", "cloud_sync.mcp_server"]
    cwd:     <repo>/candidate-collector

Tools:
    cloud_stats                 Row counts for the shared instance.
    search_candidates           Keyword search over cloud_candidates.
    list_recent_candidates      Most recently collected candidates.
    get_candidate               Full record for one candidate fingerprint.
    search_memories             Keyword search over conversation memories.
    semantic_search_memories    Embedding (cosine) search over memories.

注意：不要加 ``from __future__ import annotations``——FastMCP 1.8 的工具
注册直接 inspect 原始注解，字符串化注解会让 issubclass 抛 TypeError。
"""
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import CloudSyncClient, get_conn
from .config import rds_configured
from . import embeddings

mcp = FastMCP("zhongxiaomi")


def _err(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def _require_rds() -> dict[str, Any] | None:
    if not rds_configured():
        return _err(
            "RDS not configured. Set RDS_HOST, RDS_DB, RDS_USER, RDS_PASSWORD "
            "in the environment or the project .env file."
        )
    return None


@mcp.tool()
def cloud_stats() -> dict[str, Any]:
    """Return row counts for the unified cloud data instance."""
    if (e := _require_rds()):
        return e
    client = CloudSyncClient()
    embedded = 0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL")
                embedded = cur.fetchone()[0]
    except Exception:
        embedded = -1  # embedding column may not exist yet
    return {
        "ok": True,
        "candidates": client.count_candidates(),
        "memories": client.count_memories(),
        "memories_with_embedding": embedded,
    }


@mcp.tool()
def search_candidates(query: str, limit: int = 10) -> dict[str, Any]:
    """Keyword search over cloud candidates (name / company / resume text)."""
    if (e := _require_rds()):
        return e
    limit = max(1, min(int(limit), 100))
    like = f"%{query}%"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fingerprint, name, current_company, current_role,
                       phone, email, platform,
                       LEFT(raw_text, 300) AS raw_text, collected_at
                FROM cloud_candidates
                WHERE raw_text LIKE %s OR name LIKE %s OR current_company LIKE %s
                ORDER BY collected_at DESC
                LIMIT %s
                """,
                (like, like, like, limit),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        if r.get("collected_at") is not None:
            r["collected_at"] = str(r["collected_at"])
    return {"ok": True, "query": query, "count": len(rows), "candidates": rows}


@mcp.tool()
def list_recent_candidates(limit: int = 20) -> dict[str, Any]:
    """Return the most recently collected candidates."""
    if (e := _require_rds()):
        return e
    limit = max(1, min(int(limit), 200))
    rows = CloudSyncClient().list_recent_candidates(limit)
    for r in rows:
        for k in ("collected_at", "created_at", "updated_at"):
            if r.get(k) is not None:
                r[k] = str(r[k])
        # Keep the listing compact.
        if isinstance(r.get("raw_text"), str):
            r["raw_text"] = r["raw_text"][:200]
    return {"ok": True, "count": len(rows), "candidates": rows}


@mcp.tool()
def get_candidate(fingerprint: str) -> dict[str, Any]:
    """Return the full stored record for one candidate by fingerprint."""
    if (e := _require_rds()):
        return e
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM cloud_candidates WHERE fingerprint = %s LIMIT 1",
                (fingerprint,),
            )
            row = cur.fetchone()
            if not row:
                return _err(f"candidate not found: {fingerprint}")
            cols = [d[0] for d in cur.description]
            record = dict(zip(cols, row))
    for k in ("collected_at", "created_at", "updated_at"):
        if record.get(k) is not None:
            record[k] = str(record[k])
    # JSON columns arrive as strings from pymysql; parse for readability.
    for k in ("experiences_json", "education_json", "keywords_json", "parsed_json"):
        if isinstance(record.get(k), str):
            try:
                record[k] = json.loads(record[k])
            except (ValueError, TypeError):
                pass
    return {"ok": True, "candidate": record}


@mcp.tool()
def search_memories(query: str, project_id: str = "ttc", limit: int = 10) -> dict[str, Any]:
    """Keyword search over synced conversation / artifact memories."""
    if (e := _require_rds()):
        return e
    limit = max(1, min(int(limit), 100))
    like = f"%{query}%"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source, content_type, LEFT(content_text, 500) AS content_text,
                       created_at
                FROM memories
                WHERE project_id = %s AND content_text LIKE %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, like, limit),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        if r.get("created_at") is not None:
            r["created_at"] = str(r["created_at"])
    return {"ok": True, "query": query, "count": len(rows), "memories": rows}


@mcp.tool()
def semantic_search_memories(
    query: str, project_id: str = "ttc", limit: int = 10
) -> dict[str, Any]:
    """Semantic (embedding cosine) search over memories.

    Requires embeddings to be configured and backfilled. Falls back to an
    explanatory error when the embedding endpoint is unavailable.
    """
    if (e := _require_rds()):
        return e
    if not embeddings.embeddings_configured():
        return _err(
            "Embeddings not configured. Set EMBEDDING_API_KEY / OPENAI_NEXT_API_KEY, "
            "then run the backfill script."
        )
    limit = max(1, min(int(limit), 50))
    try:
        query_vec = embeddings.embed_text(query)
    except Exception as exc:  # embedding endpoint failure
        return _err(f"embedding request failed: {exc}")

    rows = CloudSyncClient().get_memory_embeddings(project_id=project_id)
    scored = []
    for r in rows:
        vec = embeddings.parse_embedding(r.get("embedding"))
        score = embeddings.cosine_similarity(query_vec, vec)
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[:limit]
    results = [
        {
            "id": r["id"],
            "source": r["source"],
            "content_type": r["content_type"],
            "content_text": r["content_text"],
            "score": round(score, 4),
        }
        for score, r in top
    ]
    return {
        "ok": True,
        "query": query,
        "model": embeddings.EMBEDDING_MODEL,
        "count": len(results),
        "memories": results,
    }


# ── Write tools (any machine with RDS credentials can write) ──────

@mcp.tool()
def add_memory(
    content_text: str,
    source: str = "claude",
    project_id: str = "ttc",
    content_type: str = "note",
    metadata: dict | None = None,
    embed: bool = True,
) -> dict[str, Any]:
    """Write a memory into the shared cloud store (idempotent by content).

    Use this to persist a decision, a summary, or any context you want every
    machine / AI tool to recall later.
    """
    if (e := _require_rds()):
        return e
    if not content_text or not content_text.strip():
        return _err("content_text is empty")
    client = CloudSyncClient()
    client.ensure_embedding_column()
    row = {
        "project_id": project_id,
        "source": source,
        "content_type": content_type,
        "content_text": content_text.strip(),
        "metadata": metadata or {},
    }
    stats = client.upsert_memories([row])
    embedded = False
    # Best-effort embedding so it is immediately semantic-searchable.
    if embed and embeddings.embeddings_configured() and stats.get("errors", 0) == 0:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, content_text FROM memories "
                        "WHERE project_id=%s AND source=%s AND embedding IS NULL "
                        "ORDER BY id DESC LIMIT 1",
                        (project_id, source),
                    )
                    r = cur.fetchone()
            if r:
                vec = embeddings.embed_text(r[1])
                client.update_memory_embeddings(
                    [(r[0], embeddings.serialize_embedding(vec), embeddings.embedding_model_name())]
                )
                embedded = True
        except Exception:
            embedded = False
    return {"ok": stats.get("errors", 0) == 0, "stats": stats, "embedded": embedded}


@mcp.tool()
def add_candidate(
    name: str,
    fingerprint: str = "",
    current_company: str = "",
    current_role: str = "",
    phone: str = "",
    email: str = "",
    raw_text: str = "",
    platform: str = "manual",
    source_url: str = "",
) -> dict[str, Any]:
    """Upsert one candidate into the shared cloud store.

    指纹由唯一算法 sha256(fingerprint_input()) 派生（R5），同人重复添加即更新。
    ``fingerprint`` 参数已废弃自建 md5 用法；传入时作为 source_record_id
    参与规范指纹计算（保持幂等语义）。
    """
    if (e := _require_rds()):
        return e
    if not name.strip():
        return _err("name is empty")

    from ingestion.entry import ingest_record
    from models import CandidateRecord

    record = CandidateRecord(
        name=name.strip(),
        current_company=current_company.strip() or None,
        current_title=current_role.strip() or None,
        phone=phone.strip() or None,
        email=email.strip() or None,
        raw_text=raw_text,
        source_platform=platform,
        source_type=platform,
        source_url=source_url.strip() or None,
        source_record_id=fingerprint.strip() or None,
    )
    try:
        result = ingest_record(record, read_back=False)
    except Exception as exc:
        return _err(f"cloud write failed: {exc}")
    return {
        "ok": True,
        "fingerprint": result.fingerprint,
        "stats": result.stats,
        "quality_score": result.quality_score,
        "missing_fields": result.missing_fields,
    }


def main() -> None:
    # R1：启动闸门——live 结构版本落后 repo 即拒绝启动
    from cloud_sync.migrate import ensure_current

    if rds_configured():
        ensure_current()
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
