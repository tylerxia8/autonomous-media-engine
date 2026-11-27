"""Offline durable at-most-once dispatch claim for Upload-Post.

A committed claim is never released, even if the process crashes before POST.
Recovery is status-only; missing/failed status does not authorize a new POST.
This module does not verify rights, STOP, reservations, or provider identity.
It is not a live dispatcher. Use a private local SQLite database, never Git.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from pathlib import Path

from aame.upload_post import UploadPostPlan, UploadPostResult

_STATES = frozenset({
    "reconciliation_required", "accepted", "processing", "status_not_found",
    "rejected", "failed", "provider_reported_published",
})


@dataclass(frozen=True)
class DispatchClaim:
    may_submit: bool
    state: str
    request_id: str


class DispatchJournal:
    def __init__(self, database: Path):
        self.database = Path(database)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS upload_post_dispatch (
                    operation_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL,
                    destination_id TEXT NOT NULL,
                    claimed_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    post_url TEXT
                )
            """)

    def _connect(self):
        return sqlite3.connect(self.database, timeout=10)

    @staticmethod
    def _check(plan, destination_id):
        if not isinstance(plan, UploadPostPlan):
            raise ValueError("invalid upload plan")
        plan.validate()
        if (not isinstance(destination_id, str) or not destination_id.strip()
                or len(destination_id) > 256
                or any(ord(c) < 32 or ord(c) == 127 for c in destination_id)):
            raise ValueError("immutable verified destination ID required")

    @staticmethod
    def _bound(row, plan, destination_id):
        if row[:3] != (plan.request_id, plan.fingerprint, destination_id):
            raise ValueError("dispatch operation conflicts with its original binding")

    @staticmethod
    def _lookup(db, plan):
        return db.execute("""
            SELECT request_id, fingerprint, destination_id, state, post_url
            FROM upload_post_dispatch WHERE operation_id = ?
        """, (plan.operation_id,)).fetchone()

    def claim(self, plan, destination_id):
        """One process obtains a claim; all later calls must reconcile only.

        Caller must resolve a trusted immutable destination and current policy,
        quota, budget and STOP before dispatch. A claim is not authorization.
        """
        self._check(plan, destination_id)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._lookup(db, plan)
            if row is not None:
                self._bound(row, plan, destination_id)
                return DispatchClaim(False, row[3], row[0])
            db.execute("""
                INSERT INTO upload_post_dispatch
                (operation_id, request_id, fingerprint, destination_id, claimed_at, state)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (plan.operation_id, plan.request_id, plan.fingerprint,
                  destination_id, datetime.now(timezone.utc).isoformat(),
                  "reconciliation_required"))
            return DispatchClaim(True, "reconciliation_required", plan.request_id)

    def record(self, plan, destination_id, result):
        """Store a provider report without granting retries or proving revenue."""
        self._check(plan, destination_id)
        if (not isinstance(result, UploadPostResult)
                or result.request_id != plan.request_id
                or result.fingerprint != plan.fingerprint
                or result.state not in _STATES):
            raise ValueError("result is not bound to dispatch")
        if result.state == "provider_reported_published":
            from aame.upload_post import _matched_post_url
            if not _matched_post_url(plan.platform, result.post_url):
                raise ValueError("invalid reported post URL")
        elif result.post_url is not None:
            raise ValueError("unexpected post URL")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._lookup(db, plan)
            if row is None:
                raise ValueError("no durable dispatch claim")
            self._bound(row, plan, destination_id)
            if row[3] == "provider_reported_published":
                if result.state == row[3] and row[4] != result.post_url:
                    raise ValueError("conflicting publication receipt")
                # Stale polls cannot erase a reported publication.
                return row[3]
            db.execute("""
                UPDATE upload_post_dispatch SET state = ?, post_url = ?
                WHERE operation_id = ?
            """, (result.state, result.post_url, plan.operation_id))
            return result.state
