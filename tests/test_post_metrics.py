import unittest
from datetime import datetime, timezone, timedelta
from aame.post_metrics import normalize


class PostMetricsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.kw = dict(request_id="fixture-request", platform="instagram",
                       post_id="fixture-post", published_at=self.now - timedelta(hours=1),
                       now=self.now)
        self.row = dict(success=True, platform_post_id="fixture-post",
                        as_of=self.now.isoformat(), post_metrics_source="platform_api",
                        post_metrics={"views": 0, "avg_watch_seconds": 12.5})
        self.payload = dict(success=True, post={"request_id": "fixture-request"},
                            platforms={"instagram": self.row})

    def read(self):
        return normalize(self.payload, **self.kw)

    def test_true_zero_and_seconds(self):
        self.assertEqual(self.read().views, 0)
        self.assertEqual(self.read().average_watch_seconds, 12.5)

    def test_provider_failure_is_missing_not_zero(self):
        self.row["post_metrics_error"] = "fixture failure"
        self.assertIsNone(self.read().views)
        self.assertEqual(self.read().missing_reason, "provider_unavailable")

    def test_wrong_post_and_request_rejected(self):
        self.row["platform_post_id"] = "other"
        self.assertEqual(self.read().missing_reason, "identity_mismatch")
        self.row["platform_post_id"] = "fixture-post"
        self.payload["post"]["request_id"] = "other"
        self.assertEqual(self.read().missing_reason, "identity_mismatch")

    def test_invalid_time_rejected(self):
        for value in ("invalid", "2026-01-02T00:00:00", "2026-01-03T00:00:00Z"):
            self.row["as_of"] = value
            self.assertEqual(self.read().missing_reason, "invalid_capture_time")

    def test_missing_or_malformed_counters(self):
        for value in (None, -1, True, "12", 1.5):
            self.row["post_metrics"] = {"views": value, "ig_reels_avg_watch_time": 15000}
            result = self.read()
            self.assertIsNone(result.views)
            self.assertIsNone(result.average_watch_seconds)

    def test_stale_and_unverified(self):
        self.kw["published_at"] = self.now - timedelta(days=3)
        self.row["as_of"] = (self.now - timedelta(days=2)).isoformat()
        self.assertEqual(self.read().missing_reason, "stale_capture")
        self.row["as_of"] = self.now.isoformat()
        self.row["post_metrics_source"] = "unknown"
        self.assertEqual(self.read().missing_reason, "unverified_metrics")
