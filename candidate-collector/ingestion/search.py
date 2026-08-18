"""Natural-language-ish search over local candidate records.

Provides keyword/phrase search across names, companies, titles, schools,
skills, locations and raw text, plus simple feedback tracking for business
users to flag correct/incorrect parses or recommendations.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "candidates.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_search_tables() -> None:
    with closing(_conn()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS candidate_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER,
                fingerprint TEXT,
                feedback_type TEXT NOT NULL,
                field TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_candidate ON candidate_feedback(candidate_id)"
        )
        conn.commit()


def search_candidates(
    query: str,
    *,
    min_score: int | None = None,
    platform: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search local candidates by keyword/phrase.

    The query is split into tokens and matched against name, company, title,
    school, skills, location and raw text.
    """
    init_search_tables()
    tokens = [t.strip() for t in query.split() if len(t.strip()) >= 1]
    if not tokens:
        return {"ok": True, "query": query, "count": 0, "candidates": []}

    conditions = []
    args: list[Any] = []
    for token in tokens:
        conditions.append(
            "(name LIKE ? OR phone LIKE ? OR email LIKE ? OR current_company LIKE ? OR current_role LIKE ? "
            "OR undergraduate_school LIKE ? OR keywords_json LIKE ? OR location LIKE ? OR raw_text LIKE ?)"
        )
        args.extend([f"%{token}%"] * 9)

    where = " WHERE " + " AND ".join(conditions)
    if min_score is not None:
        where += " AND score >= ?"
        args.append(min_score)
    if platform:
        where += " AND platform = ?"
        args.append(platform)

    sql = f"SELECT * FROM candidates {where} ORDER BY score DESC, updated_at DESC LIMIT ?"
    args.append(limit)

    with closing(_conn()) as conn:
        rows = conn.execute(sql, args).fetchall()

    candidates = []
    for row in rows:
        item = dict(row)
        for key in ("strengths_json", "risks_json", "experiences_json", "education_json", "keywords_json", "jd_scores_json"):
            try:
                item[key.replace("_json", "")] = json.loads(item.pop(key, "[]") or "[]")
            except (json.JSONDecodeError, TypeError):
                item[key.replace("_json", "")] = []
        # Highlight matching tokens.
        item["highlights"] = _extract_highlights(item, tokens)
        candidates.append(item)

    return {"ok": True, "query": query, "count": len(candidates), "candidates": candidates}


def _extract_highlights(candidate: dict[str, Any], tokens: list[str]) -> list[str]:
    highlights: list[str] = []
    raw = candidate.get("raw_text", "") or ""
    lines = raw.splitlines()
    for line in lines:
        line = line.strip()
        if len(line) < 10 or len(line) > 300:
            continue
        if any(token.lower() in line.lower() for token in tokens):
            highlights.append(line)
        if len(highlights) >= 3:
            break
    return highlights


def add_feedback(
    candidate_id: int | None,
    fingerprint: str | None,
    feedback_type: str,
    field: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Record human feedback on a candidate or parse result."""
    init_search_tables()
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with closing(_conn()) as conn:
        conn.execute(
            """
            INSERT INTO candidate_feedback (candidate_id, fingerprint, feedback_type, field, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (candidate_id, fingerprint, feedback_type, field, note, now),
        )
        conn.commit()
    return {"ok": True, "feedback_type": feedback_type}


def list_feedback(candidate_id: int | None = None, limit: int = 50) -> dict[str, Any]:
    init_search_tables()
    with closing(_conn()) as conn:
        if candidate_id is not None:
            rows = conn.execute(
                "SELECT * FROM candidate_feedback WHERE candidate_id = ? ORDER BY id DESC LIMIT ?",
                (candidate_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM candidate_feedback ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return {"ok": True, "count": len(rows), "items": [dict(r) for r in rows]}
