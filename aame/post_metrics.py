"""Normalize authorized Upload-Post analytics; no network or publishing calls."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite


@dataclass(frozen=True)
class PostMetrics:
    request_id: str
    platform: str
    post_id: str
    captured_at: datetime | None
    views: int | None
    average_watch_seconds: float | None
    missing_reason: str | None


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def normalize(payload: dict, *, request_id: str, platform: str,
              post_id: str, published_at: datetime, now: datetime) -> PostMetrics:
    """Accept only a bound platform response; missing or stale data is not zero."""
    if platform not in ("youtube", "instagram") or not request_id or not post_id:
        raise ValueError("expected publication identity required")
    if published_at.utcoffset() is None or now.utcoffset() is None or published_at > now:
        raise ValueError("invalid publication time")
    def missing(reason):
        return PostMetrics(request_id, platform, post_id, None, None, None, reason)
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return missing("provider_unavailable")
    post = payload.get("post")
    if not isinstance(post, dict) or post.get("request_id") != request_id:
        return missing("identity_mismatch")
    platforms = payload.get("platforms")
    row = platforms.get(platform) if isinstance(platforms, dict) else None
    if not isinstance(row, dict) or row.get("platform_post_id") != post_id:
        return missing("identity_mismatch")
    if row.get("success") is not True or row.get("post_metrics_error"):
        return missing("provider_unavailable")
    captured = _time(row.get("as_of"))
    if captured is None or not published_at <= captured <= now:
        return missing("invalid_capture_time")
    if now - captured > timedelta(hours=24):
        return missing("stale_capture")
    metrics = row.get("post_metrics")
    if not isinstance(metrics, dict) or row.get("post_metrics_source") != "platform_api":
        return missing("unverified_metrics")
    views = metrics.get("views")
    if type(views) is not int or not 0 <= views <= 2**63 - 1:
        views = None
    # Only consume explicitly seconds-denominated fields, never guess units.
    watch = metrics.get("avg_watch_seconds")
    if type(watch) not in (int, float) or not 0 <= watch <= 86400 or not isfinite(watch):
        watch = None
    return PostMetrics(request_id, platform, post_id, captured, views, watch,
                       None if views is not None else "views_unavailable")
