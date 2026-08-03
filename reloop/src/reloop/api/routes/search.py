"""Search and feedback HTTP bindings."""

from fastapi import APIRouter

from reloop.api import legacy

router = APIRouter()
router.add_api_route("/api/search", legacy.search, methods=["POST"])
router.add_api_route("/api/feedback", legacy.feedback, methods=["POST"])
router.add_api_route("/api/feedback", legacy.list_candidate_feedback, methods=["GET"])
