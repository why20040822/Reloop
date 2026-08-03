"""Health, static and operational HTTP bindings."""

from fastapi import APIRouter

from reloop.api import legacy

router = APIRouter()
router.add_api_route("/", legacy.index, methods=["GET"])
router.add_api_route("/feishu-web-bridge.user.js", legacy.feishu_web_bridge_script, methods=["GET"])
router.add_api_route("/api/health", legacy.health, methods=["GET"])
router.add_api_route("/api/gmail-status", legacy.gmail_status, methods=["GET"])
router.add_api_route("/api/gmail-sync", legacy.gmail_sync_now, methods=["POST"])
router.add_api_route("/api/quality/stats", legacy.quality_stats, methods=["GET"])
router.add_api_route("/api/quality/trend", legacy.quality_trend, methods=["GET"])
