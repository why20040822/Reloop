#!/usr/bin/env python3
"""
本地 Mock TTC TalentStore API Server。

启动后模拟 TTC API 的两个核心端点：
- POST /api/talent_store/v1/search
- GET  /api/talent_store/v1/time_based/profile_summary

数据来自 scripts/fetch_ttc_resumes.py 生成的 _all_resumes_api_response.json，
对外表现如同真实 API 调用，便于本地演示、调试和二次开发。

启动：
    python scripts/mock_ttc_api_server.py

测试：
    curl -X POST http://127.0.0.1:8000/api/talent_store/v1/search \
      -H "Content-Type: application/json" \
      -d '{"keyword":"AI产品经理","page_size":10}'

    curl "http://127.0.0.1:8000/api/talent_store/v1/time_based/profile_summary?person_leads_id=001"
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_FILE = REPO_ROOT / "data" / "ttc_resumes_api" / "_all_resumes_api_response.json"

app = FastAPI(title="Mock TTC TalentStore API", version="1.0.0")

_resumes: List[Dict[str, Any]] = []


def _load_data() -> None:
    global _resumes
    if DEFAULT_DATA_FILE.exists():
        data = json.loads(DEFAULT_DATA_FILE.read_text(encoding="utf-8"))
        _resumes = data.get("data", [])
    else:
        _resumes = []


@app.on_event("startup")
def startup():
    _load_data()
    print(f"[Mock API] 已加载 {len(_resumes)} 份简历，数据来源：{DEFAULT_DATA_FILE}")


class SearchPayload(BaseModel):
    keyword: str = "AI产品经理"
    page_size: int = 20
    current_page: int = 1


@app.post("/api/talent_store/v1/search")
def search_talent(payload: SearchPayload):
    keyword = payload.keyword.strip()
    page_size = max(1, min(payload.page_size, 100))
    page = max(1, payload.current_page)

    # 简单关键词过滤（匹配姓名、公司、职位、技能、简历原文）
    keyword_lower = keyword.lower()
    filtered = []
    for r in _resumes:
        text = " ".join([
            r.get("cn_name", ""),
            r.get("current_company", ""),
            r.get("job_title", ""),
            " ".join(r.get("skills", [])),
            r.get("profile_summary", {}).get("raw_resume_text", ""),
        ]).lower()
        if keyword_lower in text or not keyword:
            filtered.append(r)

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]

    return {
        "code": 200,
        "message": "success",
        "data": {
            "person_leads_items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@app.get("/api/talent_store/v1/time_based/profile_summary")
def profile_summary(person_leads_id: Optional[str] = Query(default=None)):
    if person_leads_id is None:
        return {"code": 400, "message": "missing person_leads_id", "data": {}}

    # 本地 mock 用 001/002/... 或 api_mock_from_local_db_001 作为 person_leads_id
    for idx, r in enumerate(_resumes, 1):
        mock_ids = [f"{idx:03d}", f"{r.get('source_type')}_{idx:03d}"]
        if person_leads_id in mock_ids:
            return {
                "code": 200,
                "message": "success",
                "data": r.get("profile_summary", {}),
            }

    return {"code": 404, "message": "profile not found", "data": {}}


@app.get("/health")
def health():
    return {"status": "ok", "loaded_resumes": len(_resumes)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=18000)
