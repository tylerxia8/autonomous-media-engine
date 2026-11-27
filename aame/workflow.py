"""Durable local AAME workflow. Provider actions are simulated."""

import base64
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from aame.finance import FinanceLedger
from aame.handoff import (
    HandoffScope,
    PublishReceipt,
    ReviewReceipt,
    SubmissionReceipt,
    build_submission_handoff,
    validate_submission_receipt,
)
from aame.qualification import current_evidence, identity_scope, qualify, utc_time
from aame.video import MAX_CLIP_MS, RenderReceipt, produce, verify_render
from aame.youtube_shorts import (
    Authorization,
    RemoteVideo,
    Upload,
    YouTubeShortsAdapter,
)


class WorkflowError(ValueError):
    pass


class FixtureYouTube:
    def __init__(self, job_id):
        digest = sha256(job_id.encode()).digest()
        self.video_id = base64.urlsafe_b64encode(digest).decode()[:11]

    def insert(self, *, artifact_hash, body):
        return RemoteVideo(self.video_id, body["status"]["privacyStatus"], True)


class Workflow:
    def __init__(self, directory, *, launch_at):
        self.root = Path(directory)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database = self.root / "workflow.sqlite"
        self.finance = FinanceLedger(self.root / "fixture-finance.sqlite", launch_at=launch_at)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS control (
                    id INTEGER PRIMARY KEY CHECK (id = 1), stopped INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO control VALUES (1, 0);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, state TEXT NOT NULL, inputs TEXT NOT NULL,
                    render TEXT, published_at TEXT, submitted_at TEXT,
                    pre_review_at TEXT, video_id TEXT,
                    state_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS owner_time (
                    id TEXT PRIMARY KEY, seconds INTEGER NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY, job_id TEXT,
                    transition TEXT NOT NULL, observed_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def _transaction(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    @staticmethod
    def _audit(connection, job_id, transition, now):
        connection.execute(
            "INSERT INTO audit(job_id, transition, observed_at) VALUES (?, ?, ?)",
            (job_id, transition, now.isoformat()),
        )

    @staticmethod
    def _running(connection):
        if connection.execute("SELECT stopped FROM control WHERE id = 1").fetchone()[0]:
            raise WorkflowError("workflow is stopped")

    @staticmethod
    def _job(connection, job_id):
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise WorkflowError("unknown job")
        return row

    @staticmethod
    def _transition_allowed(row, now):
        if row["revoked"]:
            raise WorkflowError("job authorization revoked")
        if now.utcoffset() != timedelta(0) or now < utc_time(row["state_at"]):
            raise WorkflowError("transition time must be UTC and follow the previous stage")

    @staticmethod
    def _qualified(packet, now, *actions):
        decision = qualify(packet, now)
        if decision["status"] != "evidence_complete":
            raise WorkflowError("qualification blocked: " + ", ".join(decision["blockers"]))
        for action in actions:
            if decision["capabilities"][action] == "disabled":
                raise WorkflowError(f"action disabled: {action}")
        if packet.get("marketplace") == "direct":
            raise WorkflowError("direct pilot dispatch is not implemented in this simulator")
        if packet["platform"] != "youtube":
            raise WorkflowError("only the YouTube fixture is supported")
        return decision

    def check_running(self):
        with self._transaction() as connection:
            self._running(connection)

    def stop(self, *, now):
        with self._transaction() as connection:
            connection.execute("UPDATE control SET stopped = 1 WHERE id = 1")
            self._audit(connection, None, "stopped", now)

    def revoke(self, job_id, *, now):
        with self._transaction() as connection:
            self._job(connection, job_id)
            connection.execute("UPDATE jobs SET revoked = 1 WHERE id = ?", (job_id,))
            self._audit(connection, job_id, "revoked", now)

    def prepare(self, job_id, *, packet, source_root, source, transcript, transcript_hash, now):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job_id):
            raise WorkflowError("invalid job ID")
        self._qualified(packet, now, "acquire", "edit")
        if not re.fullmatch(r"[a-f0-9]{64}", packet["asset_id"]):
            raise WorkflowError("asset_id must be its SHA-256")
        if not re.fullmatch(r"[a-f0-9]{64}", transcript_hash):
            raise WorkflowError("invalid transcript SHA-256")

        profile = packet["facts"]["eligibility"].get("clip_duration_ms")
        minimum_ms, maximum_ms = 1_000, MAX_CLIP_MS
        if profile is not None:
            if (
                not isinstance(profile, list) or len(profile) != 2
                or any(type(value) is not int for value in profile)
                or not 1_000 <= profile[0] <= profile[1]
            ):
                raise WorkflowError("invalid campaign clip duration")
            minimum_ms, maximum_ms = profile[0], min(profile[1], MAX_CLIP_MS)
            if minimum_ms > maximum_ms:
                raise WorkflowError("campaign duration exceeds the local recipe")
        inputs = json.dumps(
            [packet, str(Path(source_root).resolve()), source, transcript, transcript_hash],
            sort_keys=True,
        )
        output = self.root / f"{job_id}.mp4"
        with self._transaction() as connection:
            self._running(connection)
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row:
                if row["inputs"] != inputs:
                    raise WorkflowError("job ID already bound to other inputs")
                if row["revoked"]:
                    raise WorkflowError("job authorization revoked")
                if row["render"] is not None:
                    return json.loads(row["render"])
                raise WorkflowError("unfinished or failed render requires operator review")
            connection.execute(
                "INSERT INTO jobs(id, state, inputs, state_at) VALUES (?, 'rendering', ?, ?)",
                (job_id, inputs, now.isoformat()),
            )
            self._audit(connection, job_id, "rendering", now)

        try:
            self.finance.reserve(f"{job_id}:render", 0, now=now)
            with self._transaction() as connection:
                self._running(connection)
                self._transition_allowed(self._job(connection, job_id), now)
            receipt = produce(
                Path(source_root), source, transcript, output,
                expected_source_sha256=packet["asset_id"],
                expected_transcript_sha256=transcript_hash,
                minimum_ms=minimum_ms, maximum_ms=maximum_ms,
            )
            if not verify_render(output, receipt):
                raise WorkflowError("technical QA failed")
            self.finance.resolve(f"{job_id}:render", expense_cents=0, now=now,
                                 evidence="fixture:local-render")
        except Exception:
            with self._transaction() as connection:
                connection.execute(
                    "UPDATE jobs SET state = 'render_failed' WHERE id = ? AND state = 'rendering'",
                    (job_id,),
                )
                self._audit(connection, job_id, "render_failed", now)
            raise
        rendered = asdict(receipt)
        with self._transaction() as connection:
            self._running(connection)
            self._transition_allowed(self._job(connection, job_id), now)
            self.finance.record_event(
                f"{job_id}:estimate", "estimate", packet["fixed_payment"]["fee_usd_cents"],
                now=now, evidence=f"fixture:offer:{job_id}",
            )
            connection.execute(
                "UPDATE jobs SET state = 'review_required', render = ? WHERE id = ?",
                (json.dumps(rendered), job_id),
            )
            self._audit(connection, job_id, "review_required", now)
        return rendered

    def _verify_artifact(self, job_id, row, artifact_hash=None):
        receipt = RenderReceipt(**json.loads(row["render"]))
        if artifact_hash is not None and artifact_hash != receipt.output_sha256:
            raise WorkflowError("approved artifact does not match verified render")
        if not verify_render(self.root / f"{job_id}.mp4", receipt):
            raise WorkflowError("artifact no longer matches technical QA")
        return receipt

    def review(self, job_id, *, artifact_hash, now, pre_review=False):
        with self._transaction() as connection:
            self._running(connection)
            row = self._job(connection, job_id)
            self._transition_allowed(row, now)
            if row["state"] != "review_required":
                raise WorkflowError("job is not awaiting review")
            packet = json.loads(row["inputs"])[0]
            self._qualified(packet, now, "publish")
            if pre_review != (packet["fixed_payment"]["review_order"] == "pre_then_post"):
                raise WorkflowError("pre-review decision must match campaign review order")
        self._verify_artifact(job_id, row, artifact_hash)
        with self._transaction() as connection:
            self._running(connection)
            current = self._job(connection, job_id)
            self._transition_allowed(current, now)
            if current["state"] != "review_required":
                raise WorkflowError("job is no longer awaiting review")
            connection.execute(
                "UPDATE jobs SET state = 'reviewed', state_at = ?, pre_review_at = ? WHERE id = ?",
                (now.isoformat(), now.isoformat() if pre_review else None, job_id),
            )
            self._audit(connection, job_id, "reviewed", now)

    @staticmethod
    def _scope(packet, row):
        return HandoffScope(
            packet["campaign_id"], packet["version"], packet["account_id"],
            json.loads(row["render"])["output_sha256"],
        )

    def publish_fixture(self, job_id, *, now):
        with self._transaction() as connection:
            self._running(connection)
            row = self._job(connection, job_id)
            self._transition_allowed(row, now)
            if row["state"] == "published":
                return
            if row["state"] != "reviewed":
                raise WorkflowError("job must be reviewed before simulated publishing")
            packet = json.loads(row["inputs"])[0]
            decision = self._qualified(packet, now, "publish")
            if decision["capabilities"]["publish"] != "automated":
                raise WorkflowError("simulated adapter requires an automated fixture grant")
        receipt = self._verify_artifact(job_id, row)
        with self._transaction() as connection:
            self._running(connection)
            current = self._job(connection, job_id)
            self._transition_allowed(current, now)
            if current["state"] == "published":
                return
            if current["state"] != "reviewed":
                raise WorkflowError("job is no longer ready to publish")
            upload = Upload(
                packet["account_id"], packet["version"], receipt.output_sha256,
                f"Synthetic fixture {job_id}", "public", False, True,
            )
            grant = Authorization(
                upload, utc_time(packet["permissions"]["publish"]["expires_at"]),
                True, True, True, True, True, True,
            )
            result = YouTubeShortsAdapter(FixtureYouTube(job_id)).publish(
                upload, key=job_id, now=now, dry_run=False, authorization=grant,
            )
            if result.state != "confirmed":
                raise WorkflowError("fixture upload was not confirmed")
            connection.execute(
                """UPDATE jobs SET state = 'published', state_at = ?, published_at = ?,
                   video_id = ? WHERE id = ?""",
                (now.isoformat(), now.isoformat(), result.video_id, job_id),
            )
            self._audit(connection, job_id, "fixture_published", now)

    def submit_fixture(self, job_id, *, deadline, now):
        with self._transaction() as connection:
            self._running(connection)
            row = self._job(connection, job_id)
            self._transition_allowed(row, now)
            if row["state"] == "submitted":
                return
            if row["state"] != "published":
                raise WorkflowError("job must have a confirmed fixture upload")
            packet = json.loads(row["inputs"])[0]
            decision = self._qualified(packet, now, "submit")
            scope = self._scope(packet, row)
            url = f"https://www.youtube.com/shorts/{row['video_id']}"
            posted = utc_time(row["published_at"])
            # This simulator supports the 30-minute deadline profile only.
            if packet["fixed_payment"]["submission_deadline_rule"] != "30 minutes after posting":
                raise WorkflowError("unsupported fixture deadline rule")
            if deadline != posted + timedelta(minutes=30):
                raise WorkflowError("deadline must match published_at plus 30 minutes")
            published = PublishReceipt(scope, url, posted, "fixture:publish")
            reviewed_at = utc_time(row["pre_review_at"])
            review = ReviewReceipt(scope, reviewed_at, "fixture:pre-review") if reviewed_at else None
            handoff = build_submission_handoff(
                scope, published, permission=decision["capabilities"]["submit"],
                review_required=packet["fixed_payment"]["review_order"] == "pre_then_post",
                review=review, deadline=deadline, now=now,
            )
            validate_submission_receipt(
                handoff, SubmissionReceipt(scope, url, now, "fixture:submission"), now=now,
            )
            connection.execute(
                "UPDATE jobs SET state = 'submitted', state_at = ?, submitted_at = ? WHERE id = ?",
                (now.isoformat(), now.isoformat(), job_id),
            )
            self._audit(connection, job_id, "fixture_submitted", now)

    @staticmethod
    def _payment_terms(row, now):
        packet = json.loads(row["inputs"])[0]
        grant = packet["permissions"].get("reconcile")
        if (
            now.utcoffset() != timedelta(0)
            or not current_evidence(grant, now)
            or grant.get("scope") != identity_scope(packet)
            or grant.get("action") != "reconcile"
            or grant.get("mode") != "manual"
        ):
            raise WorkflowError("current manual reconciliation grant required")
        if now < utc_time(row["state_at"]):
            raise WorkflowError("payment event cannot precede the previous stage")
        return packet["fixed_payment"]

    def record_review_fixture(self, job_id, *, approved, now):
        if type(approved) is not bool:
            raise WorkflowError("payout review outcome must be explicit")
        state = "payout_approved" if approved else "payout_rejected"
        with self._transaction() as connection:
            row = self._job(connection, job_id)
            if row["state"] == state:
                return
            if row["state"] != "submitted":
                raise WorkflowError("no fixture submission awaiting payout review")
            payment = self._payment_terms(row, now)
            if approved:
                self.finance.record_event(
                    f"{job_id}:approval", "approval", payment["fee_usd_cents"],
                    now=now, evidence=f"fixture:approval:{job_id}",
                )
            connection.execute(
                "UPDATE jobs SET state = ?, state_at = ? WHERE id = ?",
                (state, now.isoformat(), job_id),
            )
            self._audit(connection, job_id, f"fixture_{state}", now)

    def reconcile_fixture(self, job_id, *, now):
        with self._transaction() as connection:
            row = self._job(connection, job_id)
            if row["state"] == "reconciled":
                return
            if row["state"] != "payout_approved":
                raise WorkflowError("no approved fixture payout to reconcile")
            payment = self._payment_terms(row, now)
            if payment["minimum_views"] != 0:
                raise WorkflowError("view verification is required for this fixture")
            net = payment["fee_usd_cents"] - payment["max_deductions_usd_cents"]
            self.finance.record_event(f"{job_id}:cash", "cash", net,
                                      now=now, evidence=f"fixture:cash:{job_id}")
            connection.execute(
                "UPDATE jobs SET state = 'reconciled', state_at = ? WHERE id = ?",
                (now.isoformat(), job_id),
            )
            self._audit(connection, job_id, "fixture_reconciled", now)

    def record_owner_time(self, key, *, seconds, now):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key):
            raise WorkflowError("invalid owner-time entry ID")
        if type(seconds) is not int or not 0 < seconds <= 86400:
            raise WorkflowError("owner time must be between 1 and 86400 seconds")
        if now.utcoffset() != timedelta(0):
            raise WorkflowError("owner time must be recorded in UTC")
        with self._transaction() as connection:
            previous = connection.execute(
                "SELECT seconds FROM owner_time WHERE id = ?", (key,)
            ).fetchone()
            if previous:
                if previous["seconds"] != seconds:
                    raise WorkflowError("owner-time entry already has a different duration")
                return
            connection.execute(
                "INSERT INTO owner_time VALUES (?, ?, ?)",
                (key, seconds, now.isoformat(timespec="microseconds")),
            )
            self._audit(connection, None, "owner_time_recorded", now)

    def report(self, *, now):
        with self._transaction() as connection:
            jobs = [dict(row) for row in connection.execute(
                "SELECT id, state, revoked, published_at, submitted_at FROM jobs ORDER BY id"
            )]
            stopped = bool(connection.execute(
                "SELECT stopped FROM control WHERE id = 1"
            ).fetchone()[0])
            owner_seconds = connection.execute(
                "SELECT SUM(seconds) FROM owner_time WHERE ? < observed_at AND observed_at <= ?",
                ((now - timedelta(days=7)).isoformat(timespec="microseconds"),
                 now.isoformat(timespec="microseconds")),
            ).fetchone()[0]
        waiting = []
        for job in jobs:
            submitted = utc_time(job["submitted_at"])
            if job["state"] in ("submitted", "payout_approved") and submitted and submitted <= now:
                waiting.append({
                    "id": job["id"],
                    "state": job["state"],
                    "seconds_since_submission": (now - submitted) // timedelta(seconds=1),
                })
        finance = self.finance.report(now=now)
        finance["fixture_break_even"] = finance.pop("verified_cash_break_even")
        return {
            "mode": "simulation",
            "verified_cash_break_even": False,
            "stopped": stopped,
            "jobs": jobs,
            "simulated_finance": finance,
            "simulated_week": self.finance.trailing_week(now=now),
            "recorded_owner_seconds_this_week": owner_seconds,
            "owner_time_target_seconds": 900,
            "waiting_payouts": waiting,
        }
