from datetime import timedelta
from pathlib import Path
import shutil
import tempfile
import unittest

from aame.demo import DEMO_LAUNCH, fixture_inputs, run_demo
from aame.workflow import Workflow, WorkflowError


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
class WorkflowTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.now = DEMO_LAUNCH + timedelta(hours=1)

    def prepare(self):
        source_root = self.root / "source"
        packet, source, transcript, digest = fixture_inputs(source_root)
        workflow = Workflow(self.root / "output", launch_at=DEMO_LAUNCH)
        receipt = workflow.prepare(
            "test", packet=packet, source_root=source_root, source=source,
            transcript=transcript, transcript_hash=digest, now=self.now,
        )
        return workflow, receipt

    def test_demo_renders_and_reconciles_once_across_restart(self):
        directory = self.root / "demo"
        report = run_demo(directory)
        self.assertEqual(report["jobs"][0]["state"], "reconciled")
        self.assertTrue((directory / "output" / "fixture.mp4").is_file())
        self.assertFalse(report["verified_cash_break_even"])
        workflow = Workflow(directory / "output", launch_at=DEMO_LAUNCH)
        workflow.reconcile_fixture("fixture", now=self.now + timedelta(days=2))
        finance = workflow.report(now=self.now + timedelta(days=2))["simulated_finance"]
        self.assertEqual(finance["estimated_cents"], 1500)
        self.assertEqual(finance["approved_cents"], 1500)
        self.assertEqual(finance["received_cash_cents"], 1400)
        report = workflow.report(now=self.now + timedelta(days=2))
        self.assertEqual(report["simulated_week"]["net_cash_per_day_cents_floor"], 200)
        self.assertFalse(report["simulated_week"]["meets_daily_cash_target"])
        self.assertIsNone(report["recorded_owner_seconds_this_week"])
        for _ in range(2):
            workflow.record_owner_time("check", seconds=45, now=self.now)
        report = workflow.report(now=self.now + timedelta(days=2))
        self.assertEqual(report["recorded_owner_seconds_this_week"], 45)

    def test_publish_before_review_time_and_after_artifact_tampering_is_denied(self):
        workflow, receipt = self.prepare()
        review_time = self.now + timedelta(minutes=1)
        workflow.review("test", artifact_hash=receipt["output_sha256"], now=review_time)
        with self.assertRaisesRegex(WorkflowError, "previous stage"):
            workflow.publish_fixture("test", now=self.now)
        (self.root / "output" / "test.mp4").write_bytes(b"tampered")
        with self.assertRaisesRegex(WorkflowError, "technical QA"):
            workflow.publish_fixture("test", now=review_time)

    def test_submission_deadline_and_post_stop_reconciliation(self):
        workflow, receipt = self.prepare()
        workflow.review("test", artifact_hash=receipt["output_sha256"], now=self.now)
        workflow.publish_fixture("test", now=self.now)
        deadline = self.now + timedelta(minutes=30)
        with self.assertRaisesRegex(ValueError, "deadline"):
            workflow.submit_fixture("test", deadline=deadline, now=deadline + timedelta(seconds=1))
        workflow.submit_fixture("test", deadline=deadline, now=deadline)
        workflow.revoke("test", now=deadline)
        workflow.stop(now=deadline)
        with self.assertRaisesRegex(WorkflowError, "stopped"):
            workflow.publish_fixture("test", now=deadline)
        with self.assertRaisesRegex(WorkflowError, "no approved"):
            workflow.reconcile_fixture("test", now=deadline)
        workflow.record_review_fixture("test", approved=True, now=deadline)
        pending = workflow.report(now=deadline)
        self.assertEqual(pending["waiting_payouts"][0]["state"], "payout_approved")
        finance = pending["simulated_finance"]
        self.assertEqual(finance["approved_cents"], 1500)
        self.assertEqual(finance["received_cash_cents"], 0)
        workflow.reconcile_fixture("test", now=deadline)
        report = workflow.report(now=deadline)
        self.assertEqual(report["jobs"][0]["state"], "reconciled")
        self.assertTrue(report["jobs"][0]["revoked"])
        self.assertTrue(report["stopped"])

    def test_revocation_blocks_previously_reviewed_render(self):
        workflow, receipt = self.prepare()
        workflow.review("test", artifact_hash=receipt["output_sha256"], now=self.now)
        workflow.revoke("test", now=self.now)
        with self.assertRaisesRegex(WorkflowError, "revoked"):
            workflow.publish_fixture("test", now=self.now)


if __name__ == "__main__":
    unittest.main()
