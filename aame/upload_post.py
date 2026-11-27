"""Plan Upload-Post video requests and exercise them with a fixture transport."""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlencode, urlsplit
from urllib.request import Request
from uuid import NAMESPACE_URL, uuid4, uuid5

from aame.handoff import youtube_video_id


_API = "https://api.upload-post.com"
_MAX_MEDIA_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class UploadPostPlan:
    operation_id: str
    profile: str
    platform: str
    artifact_sha256: str
    title: str
    description: str
    visibility: str
    made_for_kids: bool
    paid_partnership: bool
    synthetic_media: bool

    @property
    def fingerprint(self):
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode()).hexdigest()

    @property
    def request_id(self):
        # A changed payload keeps the same ID for a given immutable operation.
        return str(uuid5(NAMESPACE_URL, f"{_API}/aame/{self.operation_id}"))

    def validate(self):
        if not isinstance(self.operation_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_.:-]{1,128}", self.operation_id,
        ):
            raise ValueError("operation_id must be a stable ID of 1–128 ASCII characters")
        if not isinstance(self.profile, str) or not self.profile.strip() or len(self.profile) > 128:
            raise ValueError("an exact Upload-Post profile is required")
        if self.platform not in ("youtube", "instagram"):
            raise ValueError("only YouTube and Instagram are supported")
        if not isinstance(self.artifact_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.artifact_sha256,
        ):
            raise ValueError("artifact_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(self.title, str) or not self.title.strip() or len(self.title) > 100:
            raise ValueError("title must be nonblank and at most 100 characters")
        if not isinstance(self.description, str) or len(self.description.encode()) > 5000:
            raise ValueError("description must be at most 5,000 UTF-8 bytes")
        if any(type(value) is not bool for value in (
            self.made_for_kids, self.paid_partnership, self.synthetic_media,
        )):
            raise ValueError("content declarations must be explicit booleans")
        if self.visibility not in ("private", "unlisted", "public"):
            raise ValueError("an explicit supported visibility is required")
        if self.platform == "instagram":
            if self.visibility != "public" or self.made_for_kids or self.paid_partnership:
                raise ValueError("Instagram requires public visibility and supported disclosures")
            if len(self.description or self.title) > 2200:
                raise ValueError("Instagram caption must be at most 2,200 characters")


@dataclass(frozen=True)
class UploadPostApproval:
    fingerprint: str
    expires_at: datetime
    owner_approved: bool
    rights_approved: bool
    qa_approved: bool

    def allows(self, plan, now):
        return (
            self.fingerprint == plan.fingerprint
            and isinstance(self.expires_at, datetime)
            and self.expires_at.utcoffset() is not None
            and now < self.expires_at
            and self.owner_approved is True
            and self.rights_approved is True
            and self.qa_approved is True
        )


@dataclass(frozen=True)
class UploadPostResult:
    state: str
    request_id: str
    fingerprint: str
    post_url: str | None = None


def _read_approved_media(path, expected_sha256):
    if path.suffix.lower() != ".mp4":
        raise ValueError("approved artifact must be an MP4")
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags), "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or not 12 <= info.st_size <= _MAX_MEDIA_BYTES:
            raise ValueError("MP4 must be a regular file within the 64 MiB limit")
        video = handle.read(_MAX_MEDIA_BYTES + 1)
    if len(video) > _MAX_MEDIA_BYTES or video[4:8] != b"ftyp":
        raise ValueError("approved artifact must have an MP4 type header")
    if sha256(video).hexdigest() != expected_sha256:
        raise ValueError("approved artifact SHA-256 does not match local bytes")
    return video


def _multipart(plan, video):
    fields = {
        "user": plan.profile,
        "platform[]": plan.platform,
        "title": plan.title,
        "request_id": plan.request_id,
        "external_id": plan.fingerprint,
        "async_upload": "true",
    }
    if plan.platform == "youtube":
        fields.update({
            "description": plan.description,
            "privacyStatus": plan.visibility,
            "selfDeclaredMadeForKids": str(plan.made_for_kids).lower(),
            "hasPaidProductPlacement": str(plan.paid_partnership).lower(),
            "containsSyntheticMedia": str(plan.synthetic_media).lower(),
        })
    else:
        fields.update({
            "instagram_title": plan.description or plan.title,
            "media_type": "REELS",
            "is_ai_generated": str(plan.synthetic_media).lower(),
        })

    boundary = f"AAME-{uuid4().hex}"
    parts = [
        (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
         f"{value}\r\n").encode()
        for name, value in fields.items()
    ]
    parts.extend((
        (f'--{boundary}\r\nContent-Disposition: form-data; name="video"; filename="clip.mp4"\r\n'
         "Content-Type: video/mp4\r\n\r\n").encode(),
        video,
        f"\r\n--{boundary}--\r\n".encode(),
    ))
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


def _matched_post_url(platform, url):
    if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        return False
    if platform == "youtube":
        try:
            youtube_video_id(url)
            return True
        except ValueError:
            return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc in ("www.instagram.com", "instagram.com")
        and re.fullmatch(r"/reels?/[A-Za-z0-9_-]+/?", parsed.path) is not None
    )


class UploadPostAdapter:
    """Construct request envelopes for a fixture. No live transport is provided."""

    def __init__(self, *, fixture_transport=None):
        self._fixture_transport = fixture_transport

    def _fixture_headers(self):
        if self._fixture_transport is None:
            raise ValueError("Upload-Post execution is disabled without a fixture transport")
        return {"Authorization": "Apikey fixture-key", "Accept": "application/json"}

    @staticmethod
    def _result(plan, state, url=None):
        return UploadPostResult(state, plan.request_id, plan.fingerprint, url)

    def _request(self, request):
        try:
            return self._fixture_transport(request)
        except (OSError, HTTPException):
            return None, None

    def submit(self, plan, video_path, *, dry_run=True, approval=None, now=None):
        plan.validate()
        video = _read_approved_media(Path(video_path), plan.artifact_sha256)
        if dry_run:
            return self._result(plan, "dry_run")

        now = now if now is not None else datetime.now(timezone.utc)
        if now.utcoffset() is None or approval is None or not approval.allows(plan, now):
            raise ValueError("current owner, rights and QA approval for the exact plan is required")
        headers = self._fixture_headers()
        content_type, body = _multipart(plan, video)
        headers.update({
            "Content-Type": content_type,
            "Idempotency-Key": plan.request_id,
            "X-Request-Id": plan.request_id,
        })
        code, payload = self._request(Request(f"{_API}/api/upload", body, headers, method="POST"))
        if code in (400, 401, 403, 404, 413, 415, 422, 429):
            return self._result(plan, "rejected")
        if (
            code in (200, 202)
            and isinstance(payload, dict)
            and payload.get("success") is True
            and payload.get("request_id") == plan.request_id
            and payload.get("external_id", plan.fingerprint) == plan.fingerprint
        ):
            return self._result(plan, "accepted")
        return self._result(plan, "reconciliation_required")

    def poll(self, plan, *, dry_run=True):
        plan.validate()
        if dry_run:
            return self._result(plan, "dry_run")
        query = urlencode({"request_id": plan.request_id})
        request = Request(f"{_API}/api/uploadposts/status?{query}", headers=self._fixture_headers())
        code, payload = self._request(request)
        if code == 404:
            # The original POST could still be in transit. Never resubmit automatically.
            return self._result(plan, "status_not_found")
        if (
            code != 200
            or not isinstance(payload, dict)
            or payload.get("request_id") != plan.request_id
            or payload.get("external_id") != plan.fingerprint
        ):
            return self._result(plan, "reconciliation_required")
        status = payload.get("status")
        if status in ("pending", "queued", "processing", "in_progress"):
            return self._result(plan, "processing")
        if status == "failed":
            return self._result(plan, "failed")
        results = payload.get("results")
        if status != "completed" or not isinstance(results, list):
            return self._result(plan, "reconciliation_required")
        platform_results = [
            row for row in results if isinstance(row, dict) and row.get("platform") == plan.platform
        ]
        if len(platform_results) != 1:
            return self._result(plan, "reconciliation_required")
        result = platform_results[0]
        if (result.get("skipped") is True or result.get("success") is False
                or result.get("status") in ("skipped", "failed")):
            return self._result(plan, "failed")
        url = result.get("post_url") or result.get("url")
        if result.get("success") is True and _matched_post_url(plan.platform, url):
            return self._result(plan, "provider_reported_published", url)
        return self._result(plan, "reconciliation_required")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("submit", "poll"):
        command = commands.add_parser(name)
        command.add_argument("plan", type=Path)
        if name == "submit":
            command.add_argument("video", type=Path)
    args = parser.parse_args()
    try:
        plan = UploadPostPlan(**json.loads(args.plan.read_text(encoding="utf-8")))
        adapter = UploadPostAdapter()
        if args.command == "submit":
            result = adapter.submit(plan, args.video)
        else:
            result = adapter.poll(plan)
    except (OSError, TypeError, ValueError, KeyError) as error:
        parser.exit(2, f"Invalid Upload-Post input: {error}\n")
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
