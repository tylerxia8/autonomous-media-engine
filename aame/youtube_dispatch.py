"""Durable YouTube upload session handling for an explicitly enabled caller."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import stat

from aame.youtube_protocol import (
    Session,
    begin,
    confirm_processing,
    processing_request,
    session_from_response,
)
from aame.youtube_transport import DispatchDenied, TransportError
from aame.video import MAX_OUTPUT_BYTES


class DispatchError(ValueError):
    pass


@dataclass(frozen=True)
class DispatchResult:
    state: str
    video_id: str | None = None


class UploadDispatcher:
    """One worker per upload store. The caller verifies live authorization.

    Sessions carry sensitive upload capability and are persisted separately
    from workflow/audit data. OAuth tokens are never placed in this store.
    """

    def __init__(self, directory, transport):
        root = Path(directory)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or stat.S_IMODE(root.stat().st_mode) & 0o077:
            raise DispatchError("upload journal requires a private directory")
        path = root / "uploads.sqlite"
        try:
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                    raise DispatchError("upload journal requires a private regular file")
            finally:
                os.close(fd)
        except OSError:
            raise DispatchError("could not open private upload journal") from None
        self._path = path
        self._transport = transport
        with self._transaction() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS uploads (
                    key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL, session_uri TEXT, video_id TEXT
                )
            """)

    @contextmanager
    def _transaction(self):
        with closing(sqlite3.connect(self._path, timeout=1)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def initialize(self, key, upload, artifact, *, category_id, contains_synthetic_media):
        request, fingerprint = self._inputs(
            key, upload, artifact, category_id, contains_synthetic_media,
        )
        with self._transaction() as connection:
            row = self._lookup(connection, key, fingerprint)
            if row is not None:
                return self._result(row)
            connection.execute("INSERT INTO uploads VALUES (?, ?, 'initiating', NULL, NULL)",
                               (key, fingerprint))

        # A timeout here may have created a resumable session. Never send a
        # second insert for the same attempt if its session URI was lost.
        try:
            response = self._transport.send(request)
            session = session_from_response(
                response.status, response.headers, size=len(artifact),
                approved_digest=upload.artifact_hash,
            )
        except DispatchDenied:
            with self._transaction() as connection:
                connection.execute("DELETE FROM uploads WHERE key = ?", (key,))
            return DispatchResult("authorization_required")
        except (TransportError, ValueError):
            with self._transaction() as connection:
                connection.execute(
                    "UPDATE uploads SET state = 'reconciliation_required' WHERE key = ?", (key,)
                )
            return DispatchResult("reconciliation_required")
        with self._transaction() as connection:
            connection.execute(
                "UPDATE uploads SET state = 'session_saved', session_uri = ? WHERE key = ?",
                (session.url, key),
            )
        return DispatchResult("session_saved")

    def advance(self, key, upload, artifact, *, category_id, contains_synthetic_media):
        _, fingerprint = self._inputs(
            key, upload, artifact, category_id, contains_synthetic_media,
        )
        with self._transaction() as connection:
            row = self._lookup(connection, key, fingerprint)
            if row is None:
                raise DispatchError("initialize the upload before transfer")
            if row["state"] == "session_saved":
                return self._transfer(connection, row, upload, artifact)
            if row["state"] == "uploaded":
                return self._confirm(connection, row, upload)
            return self._result(row)

    def _transfer(self, connection, row, upload, artifact):
        session = Session(row["session_uri"], len(artifact), upload.artifact_hash)
        try:
            response = self._transport.send(session.probe())
            if response.status in (429, 500, 502, 503, 504):
                return DispatchResult("session_saved")
            progress = session.progress(response.status, response.headers, response.payload)
            if progress.state == "incomplete":
                response = self._transport.send(
                    session.transfer(artifact, next_offset=progress.next_offset)
                )
                if response.status in (429, 500, 502, 503, 504):
                    return DispatchResult("session_saved")
                progress = session.progress(response.status, response.headers, response.payload)
        except TransportError:
            # The same server-side session will be probed on the next call.
            return DispatchResult("session_saved")
        if progress.state == "incomplete":
            return DispatchResult("session_saved")
        connection.execute(
            "UPDATE uploads SET state = ?, video_id = ? WHERE key = ?",
            (progress.state, progress.video_id, row["key"]),
        )
        return DispatchResult(progress.state, progress.video_id)

    def _confirm(self, connection, row, upload):
        try:
            response = self._transport.send(processing_request(row["video_id"]))
        except TransportError:
            return self._result(row)
        if response.status == 200 and confirm_processing(
            response.payload, video_id=row["video_id"], channel_id=upload.channel_id,
            visibility=upload.visibility,
        ):
            connection.execute(
                "UPDATE uploads SET state = 'confirmed', session_uri = NULL WHERE key = ?",
                (row["key"],),
            )
            return DispatchResult("confirmed", row["video_id"])
        return self._result(row)

    @staticmethod
    def _inputs(key, upload, artifact, category_id, contains_synthetic_media):
        if not isinstance(key, str) or not key.strip() or len(key) > 128:
            raise DispatchError("upload requires a valid idempotency key")
        if (
            type(artifact) is not bytes or not 0 < len(artifact) <= MAX_OUTPUT_BYTES
            or sha256(artifact).hexdigest() != upload.artifact_hash
        ):
            raise DispatchError("upload requires the exact approved artifact bytes")
        if not upload.channel_id or not upload.campaign_version:
            raise DispatchError("upload must bind its channel and campaign version")
        request = begin(
            upload, category_id=category_id, contains_synthetic_media=contains_synthetic_media,
            size=len(artifact),
        )
        binding = repr((upload.channel_id, upload.campaign_version, upload.artifact_hash)).encode()
        return request, sha256(binding + b"\n" + request.body).hexdigest()

    @staticmethod
    def _lookup(connection, key, fingerprint):
        row = connection.execute("SELECT * FROM uploads WHERE key = ?", (key,)).fetchone()
        if row is not None and row["fingerprint"] != fingerprint:
            raise DispatchError("upload key already bound to different approved inputs")
        return row

    @staticmethod
    def _result(row):
        state = row["state"]
        if state == "initiating":
            state = "reconciliation_required"
        return DispatchResult(state, row["video_id"])
