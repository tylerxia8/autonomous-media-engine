"""Offline YouTube Shorts publishing contract. No network transport is provided."""

from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Literal, Protocol


Visibility = Literal["private", "unlisted", "public"]


@dataclass(frozen=True)
class Upload:
    channel_id: str
    campaign_version: str
    artifact_hash: str
    title: str
    visibility: Visibility
    made_for_kids: bool
    paid_product_placement: bool


@dataclass(frozen=True)
class Authorization:
    # A future caller must construct this from verified policy evidence.
    approved_upload: Upload
    expires_at: datetime
    owner_enabled: bool
    channel_oauth_verified: bool
    rights_verified: bool
    qa_verified: bool
    campaign_allows_upload: bool
    quota_available: bool


@dataclass(frozen=True)
class RemoteVideo:
    video_id: str
    visibility: Visibility
    processed: bool


@dataclass(frozen=True)
class Result:
    state: str
    video_id: str | None = None


class UploadSimulator(Protocol):
    def insert(self, *, artifact_hash: str, body: dict) -> RemoteVideo: ...


class YouTubeShortsAdapter:
    """Exercise request and receipt handling against a test double.

    Attempts are process-local. Production requires a durable attempt store,
    verified authorization resolution and a separately reviewed OAuth transport.
    """

    def __init__(self, simulator: UploadSimulator):
        self._simulator = simulator
        self._lock = Lock()
        self._attempts: dict[str, tuple[Upload, Result]] = {}

    def publish(
        self,
        upload: Upload,
        *,
        key: str,
        now: datetime,
        authorization: Authorization | None = None,
        dry_run: bool = True,
        stopped: bool = False,
    ) -> Result:
        if stopped:
            return Result("stopped")
        if dry_run:
            return Result("dry_run")
        if not self._permitted(upload, authorization, now):
            return Result("denied")
        if not key:
            raise ValueError("upload requires an idempotency key")

        pending = Result("reconciliation_required")
        with self._lock:
            existing = self._attempts.get(key)
            if existing is not None:
                original, previous = existing
                if original != upload:
                    raise ValueError("idempotency key already bound to a different upload")
                return previous
            self._attempts[key] = (upload, pending)

        body = {
            "snippet": {"title": upload.title},
            "status": {
                "privacyStatus": upload.visibility,
                "selfDeclaredMadeForKids": upload.made_for_kids,
            },
            "paidProductPlacementDetails": {
                "hasPaidProductPlacement": upload.paid_product_placement,
            },
        }
        try:
            remote = self._simulator.insert(artifact_hash=upload.artifact_hash, body=body)
        except TimeoutError:
            return pending
        if not remote.video_id:
            return pending
        state = "reconciliation_required"
        if remote.processed and remote.visibility == upload.visibility:
            state = "confirmed"
        result = Result(state, remote.video_id)
        with self._lock:
            self._attempts[key] = (upload, result)
        return result

    @staticmethod
    def _permitted(upload: Upload, grant: Authorization | None, now: datetime) -> bool:
        return (
            grant is not None
            and grant.approved_upload == upload
            and now.utcoffset() is not None
            and grant.expires_at.utcoffset() is not None
            and now < grant.expires_at
            and all((
                grant.owner_enabled,
                grant.channel_oauth_verified,
                grant.rights_verified,
                grant.qa_verified,
                grant.campaign_allows_upload,
                grant.quota_available,
            ))
            and bool(upload.channel_id and upload.campaign_version and upload.artifact_hash)
            and bool(upload.title.strip())
            and upload.visibility in ("private", "unlisted", "public")
            and type(upload.made_for_kids) is bool
            and type(upload.paid_product_placement) is bool
        )
