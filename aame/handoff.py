"""Build offline YouTube handoffs from operator-verified receipts.

This module checks scope and chronology. It does not contact a provider or
validate the underlying evidence references. Callers must supply verified facts
and resolve the submission deadline from the applicable campaign terms.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from urllib.parse import parse_qs, urlsplit


_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}


@dataclass(frozen=True)
class HandoffScope:
    campaign_id: str
    campaign_version: str
    channel_id: str
    artifact_sha256: str


@dataclass(frozen=True)
class ReviewReceipt:
    scope: HandoffScope
    approved_at: datetime
    evidence_ref: str


@dataclass(frozen=True)
class PublishHandoff:
    scope: HandoffScope
    prepared_at: datetime


@dataclass(frozen=True)
class PublishReceipt:
    scope: HandoffScope
    video_url: str
    posted_at: datetime
    evidence_ref: str
    visibility: str = "public"


@dataclass(frozen=True)
class SubmissionHandoff:
    scope: HandoffScope
    video_id: str
    video_url: str
    posted_at: datetime
    deadline: datetime


@dataclass(frozen=True)
class SubmissionReceipt:
    scope: HandoffScope
    video_url: str
    submitted_at: datetime
    evidence_ref: str


def _nonblank(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_scope(scope: HandoffScope) -> None:
    if not all(_nonblank(value) for value in (
        scope.campaign_id,
        scope.campaign_version,
        scope.channel_id,
        scope.artifact_sha256,
    )):
        raise ValueError("handoff requires populated campaign, channel and artifact scope")
    if _SHA256.fullmatch(scope.artifact_sha256) is None:
        raise ValueError("artifact must be identified by its lowercase SHA-256 digest")


def _require_utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("handoff timestamps must be UTC")


def _require_manual(permission: str) -> None:
    if permission != "manual":
        raise ValueError("handoff requires explicit manual permission")


def _validate_review(
    scope: HandoffScope,
    *,
    required: bool,
    review: ReviewReceipt | None,
    latest_approval: datetime,
) -> None:
    if type(required) is not bool:
        raise ValueError("campaign pre-review requirement must be explicit")
    if review is None:
        if required:
            raise ValueError("campaign requires pre-publish approval")
        return
    _require_utc(review.approved_at)
    if (
        review.scope != scope
        or not _nonblank(review.evidence_ref)
        or review.approved_at > latest_approval
    ):
        raise ValueError("review must approve the same artifact before publication")


def youtube_video_id(url: str) -> str:
    """Extract a video ID from an official HTTPS video URL."""
    if not isinstance(url, str) or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url
    ):
        raise ValueError("invalid YouTube video URL")
    try:
        parsed = urlsplit(url)
        params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=12)
    except ValueError:
        raise ValueError("invalid YouTube video URL") from None
    if parsed.scheme != "https" or parsed.fragment:
        raise ValueError("invalid YouTube video URL")
    host = parsed.netloc.lower()
    path = parsed.path.split("/")
    video_id = ""
    if host == "youtu.be" and len(path) == 2 and "v" not in params:
        video_id = path[1]
    elif host in _YOUTUBE_HOSTS:
        if len(path) == 3 and path[1] == "shorts" and "v" not in params:
            video_id = path[2]
        if parsed.path == "/watch" and len(params.get("v", [])) == 1:
            video_id = params["v"][0]
    if _VIDEO_ID.fullmatch(video_id) is None:
        raise ValueError("invalid YouTube video URL")
    return video_id


def prepare_publish_handoff(
    scope: HandoffScope,
    *,
    permission: str,
    review_required: bool,
    now: datetime,
    review: ReviewReceipt | None = None,
) -> PublishHandoff:
    _validate_scope(scope)
    _require_manual(permission)
    _require_utc(now)
    _validate_review(scope, required=review_required, review=review, latest_approval=now)
    return PublishHandoff(scope, now)


def build_submission_handoff(
    scope: HandoffScope,
    publish: PublishReceipt,
    *,
    permission: str,
    review_required: bool,
    deadline: datetime,
    now: datetime,
    review: ReviewReceipt | None = None,
) -> SubmissionHandoff:
    _validate_scope(scope)
    _require_manual(permission)
    for instant in (now, deadline, publish.posted_at):
        _require_utc(instant)
    if publish.scope != scope or not _nonblank(publish.evidence_ref):
        raise ValueError("publish receipt must match handoff scope and include evidence")
    if publish.visibility != "public":
        raise ValueError("submission handoff requires confirmed public visibility")
    _validate_review(
        scope, required=review_required, review=review, latest_approval=publish.posted_at,
    )
    if not publish.posted_at <= now <= deadline:
        raise ValueError("publication must occur before handoff and within deadline")
    video_id = youtube_video_id(publish.video_url)
    return SubmissionHandoff(
        scope, video_id, f"https://www.youtube.com/shorts/{video_id}", publish.posted_at,
        deadline,
    )


def validate_submission_receipt(
    handoff: SubmissionHandoff, receipt: SubmissionReceipt, *, now: datetime,
) -> SubmissionReceipt:
    _require_utc(receipt.submitted_at)
    _require_utc(now)
    if receipt.scope != handoff.scope or not _nonblank(receipt.evidence_ref):
        raise ValueError("submission receipt must match handoff scope and include evidence")
    if youtube_video_id(receipt.video_url) != handoff.video_id:
        raise ValueError("submission receipt must reference the published video")
    if not handoff.posted_at <= receipt.submitted_at <= min(handoff.deadline, now):
        raise ValueError("submission receipt is outside the permitted time window")
    return receipt
