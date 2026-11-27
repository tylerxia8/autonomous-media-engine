from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from aame.upload_post import UploadPostAdapter, UploadPostApproval, UploadPostPlan


NOW = datetime(2026, 11, 27, tzinfo=timezone.utc)
VIDEO = b"\x00\x00\x00\x0cftypmp42fixture"


class UploadPostTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.video = Path(temporary.name) / "clip.mp4"
        self.video.write_bytes(VIDEO)
        self.plan = UploadPostPlan(
            "production:campaign:job42:youtube", "owner-profile", "youtube",
            sha256(VIDEO).hexdigest(), "Approved title", "Approved description",
            "public", False, True, True,
        )
        self.approval = self.approve(self.plan)
        self.transport = Mock()
        self.adapter = UploadPostAdapter(fixture_transport=self.transport)

    @staticmethod
    def approve(plan):
        return UploadPostApproval(plan.fingerprint, NOW + timedelta(minutes=10), True, True, True)

    @staticmethod
    def fields(request):
        content_type = request.get_header("Content-type").encode()
        raw = b"MIME-Version: 1.0\r\nContent-Type: " + content_type + b"\r\n\r\n" + request.data
        message = BytesParser().parsebytes(raw)
        return {
            part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
            for part in message.get_payload()
        }

    def submit(self, plan=None):
        plan = plan or self.plan
        self.transport.return_value = (200, {"success": True, "request_id": plan.request_id})
        return self.adapter.submit(
            plan, self.video, dry_run=False, approval=self.approve(plan), now=NOW,
        )

    def test_dry_run_and_invalid_approval_never_touch_transport(self):
        self.assertEqual(self.adapter.submit(self.plan, self.video).state, "dry_run")
        self.assertEqual(self.adapter.poll(self.plan).state, "dry_run")
        for approval in (
            None,
            replace(self.approval, fingerprint="another"),
            replace(self.approval, expires_at=NOW),
            replace(self.approval, qa_approved=False),
        ):
            with self.subTest(approval=approval), self.assertRaises(ValueError):
                self.adapter.submit(
                    self.plan, self.video, dry_run=False, approval=approval, now=NOW,
                )
        self.video.write_bytes(VIDEO + b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.adapter.submit(self.plan, self.video)
        self.transport.assert_not_called()

    def test_unwired_adapter_cannot_submit_or_poll(self):
        adapter = UploadPostAdapter()
        with self.assertRaisesRegex(ValueError, "execution is disabled"):
            adapter.submit(
                self.plan, self.video, dry_run=False, approval=self.approval, now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "execution is disabled"):
            adapter.poll(self.plan, dry_run=False)

    def test_multipart_uses_stable_ids_and_explicit_youtube_fields(self):
        self.assertEqual(self.submit().state, "accepted")
        request = self.transport.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.upload-post.com/api/upload")
        self.assertEqual(request.get_header("Authorization"), "Apikey fixture-key")
        self.assertEqual(request.get_header("Idempotency-key"), self.plan.request_id)
        self.assertEqual(request.get_header("X-request-id"), self.plan.request_id)
        self.assertEqual(self.fields(request), {
            "user": b"owner-profile", "platform[]": b"youtube",
            "title": b"Approved title", "description": b"Approved description",
            "request_id": self.plan.request_id.encode(),
            "external_id": self.plan.fingerprint.encode(),
            "async_upload": b"true", "privacyStatus": b"public",
            "selfDeclaredMadeForKids": b"false", "hasPaidProductPlacement": b"true",
            "containsSyntheticMedia": b"true", "video": VIDEO,
        })
        changed = replace(self.plan, title="Changed")
        self.assertEqual(changed.request_id, self.plan.request_id)
        self.assertNotEqual(changed.fingerprint, self.plan.fingerprint)

    def test_instagram_reels_has_explicit_caption_and_ai_disclosure(self):
        plan = replace(
            self.plan, operation_id="production:job42:instagram", platform="instagram",
            paid_partnership=False,
        )
        self.assertEqual(self.submit(plan).state, "accepted")
        fields = self.fields(self.transport.call_args.args[0])
        self.assertEqual(fields["media_type"], b"REELS")
        self.assertEqual(fields["instagram_title"], b"Approved description")
        self.assertEqual(fields["is_ai_generated"], b"true")
        with self.assertRaisesRegex(ValueError, "supported disclosures"):
            self.adapter.submit(replace(plan, paid_partnership=True), self.video)

    def test_timeout_and_not_found_never_repost(self):
        self.transport.side_effect = [TimeoutError(), (404, {})]
        result = self.adapter.submit(
            self.plan, self.video, dry_run=False, approval=self.approval, now=NOW,
        )
        self.assertEqual(result.state, "reconciliation_required")
        self.assertEqual(self.adapter.poll(self.plan, dry_run=False).state, "status_not_found")
        requests = [call.args[0] for call in self.transport.call_args_list]
        self.assertEqual([request.get_method() for request in requests], ["POST", "GET"])
        self.assertTrue(requests[1].full_url.endswith(f"?request_id={result.request_id}"))

    def test_only_bound_platform_success_with_recognized_url_reconciles(self):
        payload = {
            "request_id": self.plan.request_id, "external_id": self.plan.fingerprint,
            "status": "completed",
        }
        url = "https://www.youtube.com/shorts/ABC_def-012"
        for additions, expected in (
            ({"status": "in_progress"}, "processing"),
            ({"status": "failed"}, "failed"),
            ({"external_id": "different"}, "reconciliation_required"),
            ({"results": [{"platform": "youtube", "success": True, "post_url": url}]},
             "provider_reported_published"),
            ({"results": [{"platform": "youtube", "success": True, "post_url": "https://bad.test"}]},
             "reconciliation_required"),
            ({"results": [{"platform": "youtube", "status": "skipped", "skipped": True}]},
             "failed"),
        ):
            with self.subTest(additions=additions):
                self.transport.return_value = (200, {**payload, **additions})
                self.assertEqual(self.adapter.poll(self.plan, dry_run=False).state, expected)
