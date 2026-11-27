from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from aame.handoff import (
    HandoffScope,
    PublishReceipt,
    ReviewReceipt,
    SubmissionReceipt,
    build_submission_handoff,
    prepare_publish_handoff,
    validate_submission_receipt,
    youtube_video_id,
)


POSTED = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
NOW = POSTED + timedelta(minutes=5)
DEADLINE = POSTED + timedelta(minutes=30)
VIDEO_ID = "Abc_123-xyz"
SHORTS_URL = f"https://www.youtube.com/shorts/{VIDEO_ID}"
WATCH_URL = f"https://youtube.com/watch?v={VIDEO_ID}"
SCOPE = HandoffScope("pilot", "1", "channel", "f" * 64)
PUBLISHED = PublishReceipt(SCOPE, WATCH_URL, POSTED, "operator-publish-proof")
APPROVED = ReviewReceipt(SCOPE, POSTED - timedelta(seconds=1), "review-proof")


class HandoffTest(unittest.TestCase):
    def build(self, **overrides):
        arguments = dict(
            scope=SCOPE, publish=PUBLISHED, permission="manual", review_required=True,
            review=APPROVED, deadline=DEADLINE, now=NOW,
        )
        arguments.update(overrides)
        return build_submission_handoff(**arguments)

    def test_handoff_and_receipt_accept_equivalent_url_forms(self):
        handoff = self.build()
        self.assertEqual(handoff.video_url, SHORTS_URL)
        self.assertEqual(handoff.video_id, VIDEO_ID)
        receipt = SubmissionReceipt(
            SCOPE, f"https://youtu.be/{VIDEO_ID}?si=shared", NOW, "operator-submit-proof",
        )
        self.assertEqual(validate_submission_receipt(handoff, receipt, now=NOW), receipt)

    def test_explicit_manual_permission_and_preapproval_before_publish(self):
        handoff = prepare_publish_handoff(
            SCOPE, permission="manual", review_required=True, review=APPROVED, now=POSTED,
        )
        self.assertEqual(handoff.scope, SCOPE)
        with self.assertRaisesRegex(ValueError, "manual permission"):
            prepare_publish_handoff(
                SCOPE, permission="automated", review_required=False, now=POSTED,
            )
        with self.assertRaisesRegex(ValueError, "pre-publish approval"):
            prepare_publish_handoff(SCOPE, permission="manual", review_required=True, now=POSTED)

    def test_scope_visibility_and_evidence_are_required(self):
        for receipt in (
            replace(PUBLISHED, scope=replace(SCOPE, campaign_version="2")),
            replace(PUBLISHED, visibility="private"),
            replace(PUBLISHED, evidence_ref=" "),
        ):
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                self.build(publish=receipt)

    def test_submission_handoff_rejects_late_review_and_deadline(self):
        for overrides in (
            {"review": replace(APPROVED, approved_at=NOW)},
            {"review": None},
            {"review_required": "false"},
            {"deadline": POSTED},
            {"permission": "automated"},
            {"now": NOW.replace(tzinfo=None)},
            {"scope": replace(SCOPE, artifact_sha256="not-a-digest")},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.build(**overrides)
        self.assertEqual(self.build(now=DEADLINE).deadline, DEADLINE)

    def test_receipt_is_scoped_to_video_and_time(self):
        handoff = self.build()
        receipt = SubmissionReceipt(SCOPE, SHORTS_URL, NOW, "receipt-proof")
        for overrides in (
            {"scope": replace(SCOPE, channel_id="other")},
            {"video_url": "https://youtu.be/zyx_123-cbA"},
            {"submitted_at": POSTED - timedelta(seconds=1)},
            {"submitted_at": NOW + timedelta(seconds=1)},
            {"submitted_at": DEADLINE + timedelta(seconds=1)},
            {"evidence_ref": ""},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate_submission_receipt(handoff, replace(receipt, **overrides), now=NOW)

    def test_youtube_allowlist_rejects_ambiguous_and_noncanonical_inputs(self):
        for url in (
            f"https://youtube.com.evil.test/shorts/{VIDEO_ID}",
            f"https://youtube.com@evil.test/shorts/{VIDEO_ID}",
            f"https://evil.test@youtube.com/shorts/{VIDEO_ID}",
            f"https://youtube.com:443/shorts/{VIDEO_ID}",
            f"http://youtu.be/{VIDEO_ID}",
            f"https://youtu.be/{VIDEO_ID}/extra",
            f"https://youtube.com/watch?v={VIDEO_ID}&v={VIDEO_ID}",
            f"https://youtu.be/{VIDEO_ID}?v={VIDEO_ID}",
            f"https://you\ttube.com/shorts/{VIDEO_ID}",
            "https://www.youtube.com/shorts/TOO_SHORT",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                youtube_video_id(url)
