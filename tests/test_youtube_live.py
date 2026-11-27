from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from aame.youtube_dispatch import DispatchResult
from aame.youtube_live import CHANNEL_CHECK, advance
from aame.youtube_transport import Response


NOW = datetime(2026, 11, 27, tzinfo=timezone.utc)
CHANNEL = "UC" + "a" * 22


class LiveUploadTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.args = SimpleNamespace(
            approval=root / "approval.json", credentials=root / "credentials.json",
            video=root / "video.mp4", journal=root, execute=True,
        )
        self.args.video.write_bytes(b"offline video fixture")
        self.args.credentials.write_text("{}")
        self.args.credentials.chmod(0o600)
        self.approval = {
            "verified": True, "owner_enabled": True, "reviewer": "fixture-owner",
            "reference": "fixture-approval", "rights_reference": "fixture-rights",
            "observed_at": "2026-11-26T00:00:00Z", "expires_at": "2026-11-28T00:00:00Z",
            "category_id": "22", "contains_synthetic_media": False,
            "upload": {
                "channel_id": CHANNEL, "campaign_version": "fixture-v1",
                "artifact_hash": sha256(self.args.video.read_bytes()).hexdigest(),
                "title": "Fixture", "description": "Footage credit", "visibility": "public",
                "made_for_kids": False, "paid_product_placement": False,
            },
        }
        self.write_approval()
        self.token_factory = Mock(return_value="fixture-token")
        self.transport = Mock()
        self.transport.send.return_value = Response(200, {}, {"items": [{"id": CHANNEL}]})
        self.transport_factory = Mock(return_value=self.transport)
        self.dispatcher_factory = Mock()
        self.dispatcher_factory.return_value.initialize.return_value = DispatchResult("session_saved")
        self.dispatcher_factory.return_value.advance.return_value = DispatchResult("confirmed", "abcdefghijk")

    def write_approval(self):
        self.args.approval.write_text(json.dumps(self.approval))
        self.args.approval.chmod(0o600)

    def execute(self):
        return advance(
            self.args, clock=lambda: NOW, token_factory=self.token_factory,
            transport_factory=self.transport_factory, dispatcher_factory=self.dispatcher_factory,
        )

    def test_dry_run_does_not_read_credentials_or_contact_provider(self):
        self.args.credentials.unlink()
        self.args.execute = False
        self.assertEqual(self.execute()["state"], "dry_run")
        self.token_factory.assert_not_called()
        self.transport_factory.assert_not_called()

    def test_wrong_oauth_channel_blocks_upload(self):
        self.transport.send.return_value = Response(200, {}, {"items": [{"id": "other"}]})
        with self.assertRaisesRegex(ValueError, "approved destination"):
            self.execute()
        self.dispatcher_factory.assert_not_called()

    def test_checks_channel_and_resumes_with_stable_artifact_key(self):
        result = self.execute()
        self.transport.send.assert_called_once_with(CHANNEL_CHECK)
        self.assertEqual(result["url"], "https://www.youtube.com/watch?v=abcdefghijk")
        key, job, artifact = self.dispatcher_factory.return_value.initialize.call_args.args
        self.assertEqual(key, f"{CHANNEL}:{job.artifact_hash}")
        self.assertEqual(job.description, "Footage credit")
        self.assertEqual(sha256(artifact).hexdigest(), job.artifact_hash)

    def test_stop_tamper_and_expiry_prevent_network(self):
        stop = self.args.journal / "STOP"
        stop.touch()
        with self.assertRaisesRegex(ValueError, "stopped"):
            self.execute()
        stop.unlink()
        self.args.video.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "digest"):
            self.execute()
        self.approval["expires_at"] = NOW.isoformat()
        self.write_approval()
        with self.assertRaisesRegex(ValueError, "approval"):
            self.execute()
        self.token_factory.assert_not_called()

    def test_removed_approval_stops_later_requests(self):
        self.execute()
        guard = self.transport_factory.call_args.kwargs["authorize"]
        self.args.approval.unlink()
        self.assertFalse(guard(CHANNEL_CHECK))
