"""Human review HTTP bindings."""

from fastapi import APIRouter

from reloop.api import legacy

router = APIRouter()
router.add_api_route("/api/review/queue", legacy.review_queue_endpoint, methods=["GET"])
router.add_api_route("/api/review/{log_id}", legacy.review_detail_endpoint, methods=["GET"])
router.add_api_route("/api/review/{log_id}/approve", legacy.review_approve_endpoint, methods=["POST"])
router.add_api_route("/api/review/{log_id}/reject", legacy.review_reject_endpoint, methods=["POST"])
router.add_api_route("/api/review/{log_id}/attachment", legacy.review_attachment_endpoint, methods=["GET"])
router.add_api_route("/api/review-v1/queue", legacy.review_v1_queue_endpoint, methods=["GET"])
router.add_api_route("/api/review-v1/{candidate_id}", legacy.review_v1_detail_endpoint, methods=["GET"])
router.add_api_route("/api/review-v1/{candidate_id}/approve", legacy.review_v1_approve_endpoint, methods=["POST"])
router.add_api_route("/api/review-v1/{candidate_id}/reject", legacy.review_v1_reject_endpoint, methods=["POST"])
router.add_api_route("/api/review-v1/{candidate_id}/attachment", legacy.review_v1_attachment_endpoint, methods=["GET"])
