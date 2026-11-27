"""Advance one explicitly approved YouTube upload through the official API."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlencode
from urllib.request import Request as HTTPRequest, ProxyHandler, build_opener

from aame.qualification import current_evidence
from aame.video import MAX_OUTPUT_BYTES
from aame.youtube_dispatch import UploadDispatcher
from aame.youtube_protocol import Request, begin
from aame.youtube_shorts import Upload
from aame.youtube_transport import TransportError, YouTubeTransport, _NoRedirect


SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)
TOKEN_URI = "https://oauth2.googleapis.com/token"
CHANNEL_CHECK = Request("GET", "https://www.googleapis.com/youtube/v3/channels?part=id&mine=true", {})


def read_file(path, *, limit, private=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("expected a bounded regular file")
        if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError("approval and credentials must be owner-only files")
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file exceeds byte limit")
    return data


def refresh_access_token(credentials, *, opener=None):
    fields = ("client_id", "client_secret", "refresh_token")
    if not isinstance(credentials, dict) or any(
        not isinstance(credentials.get(key), str) or not credentials[key] for key in fields
    ):
        raise ValueError("OAuth credentials are incomplete")
    form = {key: credentials[key] for key in fields}
    form["grant_type"] = "refresh_token"
    request = HTTPRequest(TOKEN_URI, data=urlencode(form).encode(), method="POST")
    open_request = opener or build_opener(ProxyHandler({}), _NoRedirect()).open
    try:
        with open_request(request, timeout=20) as response:
            raw = response.read(65537)
        result = json.loads(raw) if len(raw) <= 65536 else None
    except (OSError, ValueError):
        raise ValueError("Google OAuth refresh failed; check the grant") from None
    token = result.get("access_token") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("Google OAuth refresh returned no access token")
    return token


def authorize(client_file, output):
    """Run on the channel owner's workstation. Google handles credentials."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    config = json.loads(read_file(client_file, limit=65536, private=True))
    if not isinstance(config, dict) or not isinstance(config.get("installed"), dict):
        raise ValueError("expected a Desktop app OAuth configuration")
    installed = config["installed"]
    if (
        installed.get("auth_uri") not in (
            "https://accounts.google.com/o/oauth2/auth",
            "https://accounts.google.com/o/oauth2/v2/auth",
        )
        or installed.get("token_uri") != TOKEN_URI
    ):
        raise ValueError("OAuth configuration must point to Google")
    if os.path.lexists(output):
        raise ValueError("choose a new credentials path")
    flow = InstalledAppFlow.from_client_config(config, SCOPES, autogenerate_code_verifier=True)
    credentials = flow.run_local_server(host="127.0.0.1", port=0, prompt="consent", timeout_seconds=300)
    if not credentials.refresh_token:
        raise ValueError("Google did not issue offline access")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump({
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "refresh_token": credentials.refresh_token,
        }, file)
    return {"state": "credentials_saved"}


def advance(args, *, clock=None, token_factory=refresh_access_token,
            transport_factory=YouTubeTransport, dispatcher_factory=UploadDispatcher):
    clock = clock or (lambda: datetime.now(timezone.utc))
    approval_bytes = read_file(args.approval, limit=65536, private=True)
    approval = json.loads(approval_bytes)
    if not current_evidence(approval, clock()) or approval.get("owner_enabled") is not True:
        raise ValueError("current owner publication approval required")
    if not isinstance(approval.get("rights_reference"), str) or not approval["rights_reference"].strip():
        raise ValueError("source reuse rights reference required")
    try:
        upload = Upload(**approval["upload"])
        metadata = {
            "category_id": approval["category_id"],
            "contains_synthetic_media": approval["contains_synthetic_media"],
        }
    except (KeyError, TypeError):
        raise ValueError("invalid approved upload metadata") from None
    if not isinstance(upload.channel_id, str) or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", upload.channel_id):
        raise ValueError("approve an exact YouTube channel ID")
    if not isinstance(upload.campaign_version, str) or not upload.campaign_version.strip():
        raise ValueError("approval requires a content or campaign revision")
    artifact = read_file(args.video, limit=MAX_OUTPUT_BYTES)
    if sha256(artifact).hexdigest() != upload.artifact_hash:
        raise ValueError("video digest does not match owner approval")
    begin(upload, size=len(artifact), **metadata)
    if not args.execute:
        return {"state": "dry_run", "channel_id": upload.channel_id, "visibility": upload.visibility}
    stop_path = args.journal / "STOP"

    def still_authorized(_request):
        if os.path.lexists(stop_path) or not current_evidence(approval, clock()):
            return False
        try:
            return read_file(args.approval, limit=65536, private=True) == approval_bytes
        except (OSError, ValueError):
            return False

    if not still_authorized(None):
        raise ValueError("publication stopped or approval changed")
    credentials = json.loads(read_file(args.credentials, limit=65536, private=True))
    token = token_factory(credentials)
    transport = transport_factory(access_token=lambda: token, authorize=still_authorized)
    response = transport.send(CHANNEL_CHECK)
    items = response.payload.get("items") if isinstance(response.payload, dict) else None
    if (
        response.status != 200 or not isinstance(items, list) or len(items) != 1
        or not isinstance(items[0], dict) or items[0].get("id") != upload.channel_id
        or response.payload.get("nextPageToken")
    ):
        raise ValueError("OAuth channel does not match the approved destination")

    dispatcher = dispatcher_factory(args.journal, transport)
    key = f"{upload.channel_id}:{upload.artifact_hash}"
    result = dispatcher.initialize(key, upload, artifact, **metadata)
    if result.state in ("session_saved", "uploaded"):
        result = dispatcher.advance(key, upload, artifact, **metadata)
    output = asdict(result)
    if result.state == "confirmed":
        output["url"] = f"https://www.youtube.com/watch?v={result.video_id}"
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("authorize")
    setup.add_argument("client_file", type=Path)
    setup.add_argument("output", type=Path)
    push = commands.add_parser("advance")
    for name in ("approval", "video", "credentials", "journal"):
        push.add_argument(f"--{name}", type=Path, required=True)
    push.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = authorize(args.client_file, args.output) if args.command == "authorize" else advance(args)
    except ImportError:
        parser.exit(1, "Install google-auth-oauthlib for the one-time authorization command.\n")
    except TransportError:
        parser.exit(1, "YouTube API connection failed before channel verification.\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"AAME: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
