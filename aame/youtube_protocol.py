"""Build and parse YouTube resumable-upload requests without network I/O."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from aame.video import MAX_OUTPUT_BYTES


_ORIGIN = "https://www.googleapis.com"
_UPLOAD = "/upload/youtube/v3/videos"
_ID = re.compile(r"[A-Za-z0-9_-]{11}")


@dataclass(frozen=True)
class Request:
    method: str
    url: str = field(repr=False)
    headers: dict = field(repr=False)
    body: bytes = field(default=b"", repr=False)


@dataclass(frozen=True)
class Session:
    url: str = field(repr=False)
    size: int
    digest: str

    def __post_init__(self):
        if type(self.size) is not int or not 0 < self.size <= MAX_OUTPUT_BYTES:
            raise ValueError("invalid upload size")
        if not isinstance(self.digest, str) or not re.fullmatch("[0-9a-f]{64}", self.digest):
            raise ValueError("invalid artifact digest")
        if not isinstance(self.url, str) or any(
            ord(char) < 33 or ord(char) >= 127 for char in self.url
        ):
            raise ValueError("invalid resumable upload location")
        url = urlsplit(self.url)
        params = parse_qs(url.query, max_num_fields=8, keep_blank_values=True)
        if (
            url.scheme != "https" or url.netloc != "www.googleapis.com"
            or url.path != _UPLOAD or url.fragment
            or len(params.get("upload_id", [])) != 1 or not params["upload_id"][0]
        ):
            raise ValueError("invalid resumable upload location")

    def probe(self):
        return Request("PUT", self.url, {
            "Content-Length": "0",
            "Content-Range": f"bytes */{self.size}",
        })

    def transfer(self, approved_bytes, *, next_offset=0):
        if (
            type(approved_bytes) is not bytes or len(approved_bytes) != self.size
            or sha256(approved_bytes).hexdigest() != self.digest
        ):
            raise ValueError("upload payload differs from approved artifact")
        if type(next_offset) is not int or not 0 <= next_offset < self.size:
            raise ValueError("invalid confirmed upload offset")
        remaining = approved_bytes[next_offset:]
        return Request("PUT", self.url, {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(remaining)),
            "Content-Range": f"bytes {next_offset}-{self.size - 1}/{self.size}",
        }, remaining)

    def progress(self, status, headers, payload):
        if status == 308:
            value = _header(headers, "Range")
            if value is None:
                return Progress("incomplete", next_offset=0)
            match = re.fullmatch(r"bytes=0-([0-9]{1,10})", value)
            if match is None or not 0 < (offset := int(match[1]) + 1) < self.size:
                return Progress("reconciliation_required")
            return Progress("incomplete", next_offset=offset)
        if status in (200, 201) and isinstance(payload, dict):
            video_id = payload.get("id")
            if isinstance(video_id, str) and _ID.fullmatch(video_id):
                return Progress("uploaded", video_id=video_id)
        return Progress("reconciliation_required")


@dataclass(frozen=True)
class Progress:
    state: str
    next_offset: int | None = None
    video_id: str | None = None


def _header(headers, name):
    matches = [value for key, value in headers.items() if key.lower() == name.lower()]
    if len(matches) == 1 and isinstance(matches[0], str):
        return matches[0]
    if matches:
        raise ValueError("ambiguous response header")
    return None


def begin(upload, *, category_id, contains_synthetic_media, size):
    if type(size) is not int or not 0 < size <= MAX_OUTPUT_BYTES:
        raise ValueError("invalid upload size")
    if not isinstance(category_id, str) or not re.fullmatch(r"[1-9][0-9]{0,3}", category_id):
        raise ValueError("explicit YouTube category required")
    if (
        type(contains_synthetic_media) is not bool or type(upload.made_for_kids) is not bool
        or type(upload.paid_product_placement) is not bool
        or upload.visibility not in ("private", "unlisted", "public")
        or not isinstance(upload.title, str) or not upload.title.strip()
    ):
        raise ValueError("explicit title, visibility and disclosures required")
    snippet = {"title": upload.title, "categoryId": category_id}
    if not isinstance(upload.description, str) or len(upload.description.encode()) > 5000:
        raise ValueError("invalid YouTube description")
    if upload.description:
        snippet["description"] = upload.description
    body = json.dumps({
        "snippet": snippet,
        "status": {
            "privacyStatus": upload.visibility,
            "selfDeclaredMadeForKids": upload.made_for_kids,
            "containsSyntheticMedia": contains_synthetic_media,
        },
        "paidProductPlacementDetails": {
            "hasPaidProductPlacement": upload.paid_product_placement,
        },
    }).encode()
    query = urlencode({
        "uploadType": "resumable",
        "part": "snippet,status,paidProductPlacementDetails",
    })
    return Request("POST", f"{_ORIGIN}{_UPLOAD}?{query}", {
        "Content-Length": str(len(body)),
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": "video/mp4",
    }, body)


def session_from_response(status, headers, *, size, approved_digest):
    if status != 200:
        raise ValueError("upload session initiation requires reconciliation")
    return Session(_header(headers, "Location"), size, approved_digest)


def processing_request(video_id):
    if not isinstance(video_id, str) or _ID.fullmatch(video_id) is None:
        raise ValueError("invalid video ID")
    query = urlencode({"part": "snippet,status,processingDetails", "id": video_id})
    return Request("GET", f"{_ORIGIN}/youtube/v3/videos?{query}", {})


def confirm_processing(payload, *, video_id, channel_id, visibility):
    """Only a matching owner-visible processed video can be handed off."""
    if not isinstance(payload, dict):
        return False
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return False
    item = items[0]
    snippet, status, processing = (
        item.get("snippet"), item.get("status"), item.get("processingDetails")
    )
    return (
        all(isinstance(part, dict) for part in (snippet, status, processing))
        and item.get("id") == video_id
        and snippet.get("channelId") == channel_id
        and status.get("privacyStatus") == visibility
        and status.get("uploadStatus") == "processed"
        and processing.get("processingStatus") == "succeeded"
    )
