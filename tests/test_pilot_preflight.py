"""Offline preflight tests with actual local media, no network/payment."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from aame.pilot_preflight import preflight, load_plan
from aame.video import VideoError


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class PilotPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.source_root = Path(cls.scratch.name)
        cls.source = cls.source_root / "source.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin",
             "-f", "lavfi", "-i", "color=size=160x90:rate=5",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000",
             "-t", "61", "-threads", "1", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.source)],
            check=True, timeout=30)
        cls.source_hash = digest(cls.source)

    def setUp(self):
        self.scratch_order = tempfile.TemporaryDirectory(dir=self.source_root)
        self.addCleanup(self.scratch_order.cleanup)
        root = Path(self.scratch_order.name)
        self.database = root / "private.sqlite"
        self.transcript = root / "transcript.json"
        self.rows = [{"start_ms": i * 10000, "end_ms": (i + 1) * 10000,
                      "text": "one two three four five six seven eight nine ten"}
                     for i in range(6)]
        self.transcript.write_text(json.dumps(self.rows), encoding="utf-8")
        self.args = dict(order_ref="fixture-order", agreement_version="v1",
                         destination_ref="private-fixture",
                         expected_source_sha256=self.source_hash,
                         expected_transcript_sha256=digest(self.transcript))

    def plan(self, **updates):
        return preflight(self.database, self.source_root, self.source.name,
                         str(self.transcript.relative_to(self.source_root)),
                         **dict(self.args, **updates))

    def test_exact_plan_restart_and_replay(self):
        result = self.plan()
        self.assertEqual(result["plan"]["windows"],
                         [[0, 20000], [20000, 40000], [40000, 60000]])
        self.assertEqual(result["plan"]["amount_cents"], 7500)
        self.assertFalse(result["checkout_authorized"])
        self.assertFalse(result["cash_verified"])
        self.assertEqual(load_plan(self.database, "fixture-order"), result)
        self.assertEqual(self.plan(), result)
        with self.assertRaises(ValueError):
            self.plan(agreement_version="v2")
        with self.assertRaises(ValueError):
            self.plan(count=1, amount_cents=2500)

    def test_transcript_tampering_and_out_of_source(self):
        self.rows[-1]["end_ms"] = 62000
        self.transcript.write_text(json.dumps(self.rows), encoding="utf-8")
        with self.assertRaises(VideoError):
            self.plan()
        with self.assertRaises(VideoError):
            self.plan(expected_transcript_sha256=digest(self.transcript))
        with self.assertRaises(ValueError):
            load_plan(self.database, "fixture-order")

    def test_infeasible_and_wrong_price(self):
        self.transcript.write_text(json.dumps(self.rows[:5]), encoding="utf-8")
        with self.assertRaises(VideoError):
            self.plan(expected_transcript_sha256=digest(self.transcript))
        with self.assertRaises(ValueError):
            self.plan(amount_cents=2500)
        with self.assertRaises(ValueError):
            load_plan(self.database, "fixture-order")

    def test_corruption_detected(self):
        self.plan()
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE pilot_preflight SET digest='bad'")
        with self.assertRaises(ValueError):
            load_plan(self.database, "fixture-order")

    def test_concurrent_replay(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.plan(), range(2)))
        self.assertEqual(results[0], results[1])
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM pilot_preflight").fetchone()[0], 1)
