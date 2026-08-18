"""Reloop MVP activity scoring.

The score is deliberately deterministic and explainable.  It is calculated
from signals captured at ingestion time; no background crawling is required.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


ACTIVE_STATUSES = ("看机会", "离职", "求职", "考虑机会", "open to work")


def parse_datetime(value: Any) -> datetime | None:
    """Parse common ISO/date inputs and normalize them to aware UTC."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def calculate_activity(
    signals: dict[str, Any] | None,
    *,
    starred: bool = False,
    employment_status: str | None = None,
    opportunity_intent: str | None = None,
    now: datetime | None = None,
) -> tuple[int, datetime | None, dict[str, int]]:
    """Return ``(score, last_active_at, breakdown)`` for one candidate.

    Supported signal keys are stable API contracts:
    ``resume_updated_at``, ``email_new_resume``, ``email_received_at``,
    ``recently_active`` and ``recently_active_at``.
    """
    signals = signals or {}
    now = parse_datetime(now) or datetime.now(timezone.utc)
    breakdown: dict[str, int] = {}
    activity_times: list[datetime] = []

    resume_updated_at = parse_datetime(signals.get("resume_updated_at"))
    if resume_updated_at:
        activity_times.append(resume_updated_at)
        age = now - resume_updated_at
        if timedelta(0) <= age <= timedelta(days=30):
            breakdown["resume_updated_within_30d"] = 40

    status_text = " ".join(
        str(value or "").lower()
        for value in (
            signals.get("employment_status"),
            employment_status,
            opportunity_intent,
        )
    )
    if any(status in status_text for status in ACTIVE_STATUSES):
        breakdown["open_to_opportunities"] = 30

    if bool(signals.get("email_new_resume")):
        breakdown["new_resume_from_email"] = 20
        email_time = parse_datetime(signals.get("email_received_at"))
        if email_time:
            activity_times.append(email_time)

    if bool(signals.get("recently_active")):
        breakdown["recently_active_on_source"] = 10
        active_time = parse_datetime(signals.get("recently_active_at"))
        if active_time:
            activity_times.append(active_time)

    if starred:
        breakdown["consultant_starred"] = 30

    return min(100, sum(breakdown.values())), max(activity_times, default=None), breakdown
