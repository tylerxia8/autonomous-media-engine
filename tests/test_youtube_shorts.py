from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock

from aame.youtube_shorts import Authorization, RemoteVideo, Upload, YouTubeShortsAdapter


class YouTubeShortsTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 26, tzinfo=timezone.utc)
        self.upload = Upload("channel", "campaign-v1", "fixture-hash", "AAME fixture",
                             "public", False, False)
        self.grant = Authorization(
            approved_upload=self.upload,
            expires_at=self.now + timedelta(minutes=5),
            owner_enabled=True,
            channel_oauth_verified=True,
            rights_verified=True,
            qa_verified=True,
            campaign_allows_upload=True,
            quota_available=True,
        )
        self.api = Mock(spec=["insert"])
        self.api.insert.return_value = RemoteVideo("fake-id", "public", True)
        self.adapter = YouTubeShortsAdapter(self.api)

    def publish(self, **overrides):
        arguments = dict(key="job", now=self.now, authorization=self.grant, dry_run=False)
        arguments.update(overrides)
        return self.adapter.publish(self.upload, **arguments)

    def test_default_dry_run_and_stop(self):
        result = self.adapter.publish(self.upload, key="job", now=self.now,
                                      authorization=self.grant)
        self.assertEqual(result.state, "dry_run")
        self.assertEqual(self.publish(stopped=True).state, "stopped")
        self.api.insert.assert_not_called()

    def test_denies_missing_stale_and_incomplete_authorization(self):
        variants = [
            None,
            replace(self.grant, expires_at=self.now),
            replace(self.grant, approved_upload=replace(self.upload, channel_id="other")),
            replace(self.grant, approved_upload=replace(self.upload, artifact_hash="other")),
        ]
        for field in ("owner_enabled", "channel_oauth_verified", "rights_verified",
                      "qa_verified", "campaign_allows_upload", "quota_available"):
            variants.append(replace(self.grant, **{field: False}))
        for grant in variants:
            with self.subTest(grant=grant):
                self.assertEqual(self.publish(authorization=grant).state, "denied")
        self.api.insert.assert_not_called()

    def test_explicit_metadata_and_confirmed_receipt_are_replay_safe(self):
        result = self.publish()
        self.assertEqual((result.state, result.video_id), ("confirmed", "fake-id"))
        self.assertEqual(self.publish(), result)
        self.api.insert.assert_called_once_with(
            artifact_hash="fixture-hash",
            body={
                "snippet": {"title": "AAME fixture"},
                "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
                "paidProductPlacementDetails": {"hasPaidProductPlacement": False},
            },
        )

    def test_changed_payload_cannot_reuse_key(self):
        self.publish()
        self.upload = replace(self.upload, visibility="unlisted")
        self.grant = replace(self.grant, approved_upload=self.upload)
        with self.assertRaisesRegex(ValueError, "different upload"):
            self.publish()
        self.api.insert.assert_called_once()

    def test_unknown_upload_outcome_never_retries(self):
        self.api.insert.side_effect = TimeoutError
        first = self.publish()
        self.assertEqual((first.state, first.video_id), ("reconciliation_required", None))
        self.assertEqual(self.publish(), first)
        self.api.insert.assert_called_once()

    def test_processing_and_visibility_must_match(self):
        for key, remote in (
            ("processing", RemoteVideo("fake-id", "public", False)),
            ("private", RemoteVideo("fake-id", "private", True)),
            ("missing-id", RemoteVideo("", "public", True)),
        ):
            with self.subTest(key=key):
                self.api.insert.return_value = remote
                result = self.publish(key=key)
                self.assertEqual(result.state, "reconciliation_required")
                self.assertEqual(self.publish(key=key), result)
        self.assertEqual(self.api.insert.call_count, 3)


if __name__ == "__main__":
    unittest.main()
