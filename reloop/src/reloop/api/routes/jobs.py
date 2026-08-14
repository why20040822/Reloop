"""Candidate and job status HTTP bindings."""

from fastapi import APIRouter

from reloop.api import legacy

router = APIRouter()
# /api/candidates 与 /api/candidates/{id} 已由 routes/cloud.py 接管（云端优先，本地回退）
router.add_api_route("/api/ingest-v2/log", legacy.ingest_v2_log, methods=["GET"])
router.add_api_route("/api/evaluate-jd/{candidate_id}", legacy.evaluate_jd, methods=["POST"])
router.add_api_route("/api/export-jd", legacy.export_jd, methods=["GET"])
