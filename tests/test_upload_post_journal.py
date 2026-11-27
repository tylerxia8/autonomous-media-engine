from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aame.upload_post import UploadPostPlan, UploadPostResult
from aame.upload_post_journal import DispatchJournal


class JournalTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "journal.sqlite"
        self.journal = DispatchJournal(self.path)
        self.plan = UploadPostPlan(
            "fixture:job:youtube", "fixture-profile", "youtube", "a" * 64,
            "Fixture title", "Fixture description", "public", False, False, False,
        )
        self.destination = "fixture-channel"

    def result(self, state, url=None):
        return UploadPostResult(
            state, self.plan.request_id, self.plan.fingerprint, url,
        )

    def test_parallel_workers_and_restart_only_claim_once(self):
        def claim(_):
            return DispatchJournal(self.path).claim(self.plan, self.destination)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(claim, range(20)))
        self.assertEqual(sum(r.may_submit for r in results), 1)
        self.assertEqual({r.request_id for r in results}, {self.plan.request_id})
        again = DispatchJournal(self.path).claim(self.plan, self.destination)
        self.assertFalse(again.may_submit)
        self.assertEqual(again.state, "reconciliation_required")

    def test_changed_payload_and_destination_cannot_reuse_operation(self):
        self.journal.claim(self.plan, self.destination)
        for plan, destination in (
            (replace(self.plan, title="different"), self.destination),
            (self.plan, "different-channel"),
        ):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                self.journal.claim(plan, destination)

    def test_unknown_and_failed_status_never_release_claim(self):
        self.journal.claim(self.plan, self.destination)
        for state in ("accepted", "processing", "status_not_found", "failed", "rejected"):
            self.journal.record(self.plan, self.destination, self.result(state))
            again = DispatchJournal(self.path).claim(self.plan, self.destination)
            self.assertFalse(again.may_submit)
            self.assertEqual(again.state, state)

    def test_unbound_and_invalid_results_rejected(self):
        with self.assertRaises(ValueError):
            self.journal.record(self.plan, self.destination, self.result("accepted"))
        self.journal.claim(self.plan, self.destination)
        for result in (
            replace(self.result("accepted"), fingerprint="other"),
            replace(self.result("accepted"), request_id="other"),
            self.result("dry_run"),
            self.result("accepted", "https://example.test"),
            self.result("provider_reported_published", "https://example.test"),
        ):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.journal.record(self.plan, self.destination, result)

    def test_stale_poll_cannot_erase_publication(self):
        self.journal.claim(self.plan, self.destination)
        state = "provider_reported_published"
        url = "https://www.youtube.com/watch?v=ABC_def-012"
        self.journal.record(self.plan, self.destination, self.result(state, url))
        self.assertEqual(self.journal.record(
            self.plan, self.destination, self.result("status_not_found")), state)
        with self.assertRaises(ValueError):
            self.journal.record(self.plan, self.destination, self.result(
                state, "https://www.youtube.com/watch?v=XYZ_def-012"))
        claim = DispatchJournal(self.path).claim(self.plan, self.destination)
        self.assertEqual(claim.state, state)
        self.assertFalse(claim.may_submit)


if __name__ == "__main__":
    unittest.main()
