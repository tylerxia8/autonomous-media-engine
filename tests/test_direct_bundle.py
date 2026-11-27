from datetime import datetime, timedelta, timezone
import unittest

from aame.direct_bundle import bundle_manifest, manifest_digest, validate_receipt


NOW = datetime(2026, 11, 26, 18, tzinfo=timezone.utc)
CLIPS = [("job-a", "a" * 64), ("job-b", "b" * 64), ("job-c", "c" * 64)]


def manifest(clips=CLIPS, **changes):
    params = dict(agreement_id="fixture-agreement", version="v1",
                  destination_ref="fixture-destination", expected_count=3, clips=clips)
    params.update(changes)
    return bundle_manifest(**params)


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.manifest = manifest()
        self.receipt = dict(manifest_sha256=manifest_digest(self.manifest),
                            destination_ref="fixture-destination",
                            provider_receipt_id="fixture-receipt",
                            accepted_at=NOW + timedelta(minutes=1),
                            accepted_artifact_sha256s=[h for _, h in CLIPS],
                            status="accepted")

    def validate(self, receipt=None):
        return validate_receipt(self.manifest, self.receipt if receipt is None else receipt,
                                dispatched_at=NOW, deadline=NOW + timedelta(minutes=5),
                                now=NOW + timedelta(minutes=2))

    def test_canonical_replay_is_order_independent(self):
        self.assertEqual(manifest_digest(self.manifest),
                         manifest_digest(manifest(list(reversed(CLIPS)))))
        self.assertEqual(self.validate(), self.validate())
        self.assertFalse(self.validate()["cash_verified"])
        self.assertFalse(self.validate()["live_enabled"])

    def test_wrong_count_and_duplicates(self):
        for clips in (CLIPS[:2], [CLIPS[0], CLIPS[0], CLIPS[2]],
                      [CLIPS[0], ("other", CLIPS[0][1]), CLIPS[2]]):
            with self.subTest(clips=clips), self.assertRaises(ValueError):
                manifest(clips)

    def test_receipt_cannot_cross_contract_version_or_destination(self):
        for changed in (manifest(version="v2"), manifest(destination_ref="other"),
                        manifest(agreement_id="other")):
            self.assertNotEqual(manifest_digest(self.manifest), manifest_digest(changed))
            with self.assertRaises(ValueError):
                self.validate({**self.receipt, "manifest_sha256": manifest_digest(changed)})

    def test_partial_duplicate_or_altered_receipt_fails(self):
        for hashes in (["a" * 64], ["a" * 64, "a" * 64, "b" * 64, "c" * 64],
                       ["a" * 64, "b" * 64, "d" * 64]):
            with self.subTest(hashes=hashes), self.assertRaises(ValueError):
                self.validate({**self.receipt, "accepted_artifact_sha256s": hashes})

    def test_unknown_status_and_invalid_chronology_fail(self):
        with self.assertRaises(ValueError):
            self.validate({**self.receipt, "status": "pending"})
        for instant in (NOW - timedelta(seconds=1), NOW + timedelta(minutes=3),
                        NOW + timedelta(minutes=6), NOW.replace(tzinfo=None)):
            with self.subTest(instant=instant), self.assertRaises(ValueError):
                self.validate({**self.receipt, "accepted_at": instant})
