"""Candidate and job status HTTP bindings."""

from fastapi import APIRouter

from reloop.api import legacy

router = APIRouter()
router.add_api_route("/api/candidates", legacy.candidates, methods=["GET"])
router.add_api_route("/api/candidates/{candidate_id}", legacy.candidate_detail, methods=["GET"])
router.add_api_route("/api/ingest-v2/log", legacy.ingest_v2_log, methods=["GET"])
router.add_api_route("/api/evaluate-jd/{candidate_id}", legacy.evaluate_jd, methods=["POST"])
router.add_api_route("/api/export-jd", legacy.export_jd, methods=["GET"])
