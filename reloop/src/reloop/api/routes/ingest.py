"""Candidate capture and ingestion HTTP bindings."""

from fastapi import APIRouter

from reloop.api import legacy

router = APIRouter()
router.add_api_route("/api/capture", legacy.capture, methods=["POST"])
router.add_api_route("/api/feishu-web/message", legacy.feishu_web_message, methods=["POST"])
router.add_api_route("/api/feishu-web/messages", legacy.feishu_web_messages, methods=["GET"])
router.add_api_route("/api/feishu-web/pending-replies", legacy.feishu_web_pending_replies, methods=["GET"])
router.add_api_route("/api/feishu-web/reply-ack", legacy.feishu_web_reply_ack, methods=["POST"])
router.add_api_route("/api/import-text", legacy.import_text, methods=["POST"])
router.add_api_route("/api/import-url", legacy.import_url, methods=["POST"])
router.add_api_route("/api/import-file", legacy.import_file, methods=["POST"])
router.add_api_route("/api/import-local-download", legacy.import_local_download, methods=["POST"])
router.add_api_route("/api/ingest-v2/file", legacy.ingest_v2_file, methods=["POST"])
router.add_api_route("/api/ingest-v2/text", legacy.ingest_v2_text, methods=["POST"])
