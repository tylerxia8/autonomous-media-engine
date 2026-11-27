"""Offline benchmark of the three-clip direct pilot; never sends or bills."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from aame.direct_bundle import bundle_manifest, manifest_digest, validate_receipt
from aame.video import Cue, VideoError, produce, rank_candidates, verify_render


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExclusionTests(unittest.TestCase):
    def test_overlap_rejected_touching_boundary_allowed(self):
        cues = [Cue(0, 2000, "first"), Cue(2000, 4000, "second"),
                Cue(4000, 6000, "third")]
        result = rank_candidates(cues, excluded_windows=[(2000, 4000)], limit=2)
        self.assertEqual({(c.start_ms, c.end_ms) for c in result},
                         {(0, 2000), (4000, 6000)})

    def test_bad_or_exhausted_ranges(self):
        cues = [Cue(0, 2000, "first")]
        for windows in (None, [(0, True)], [(2000, 0)], [(-1, 10)],
                        [(0, 3600001)], [(0, 1)] * 101, [(0, 2000)]):
            with self.subTest(windows=windows), self.assertRaises(VideoError):
                rank_candidates(cues, excluded_windows=windows)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class DirectPilotBenchmark(unittest.TestCase):
    def test_three_distinct_real_renders_and_fixture_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            transcript = root / "transcript.json"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-nostdin",
                 "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                 "-t", "24", "-threads", "2", "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
                check=True, timeout=30)
            transcript.write_text(json.dumps([
                {"start_ms": 500, "end_ms": 6000, "text": "First distinct fixture moment."},
                {"start_ms": 8500, "end_ms": 14000, "text": "Second distinct fixture moment."},
                {"start_ms": 16500, "end_ms": 22000, "text": "Third distinct fixture moment."},
            ]), encoding="utf8")
            source_hash, transcript_hash = digest(source), digest(transcript)
            windows, clips, observations = [], [], []
            begin = time.perf_counter()
            for i in range(3):
                output = root / f"clip-{i}.mp4"
                started = time.perf_counter()
                receipt = produce(root, source.name, transcript.name, output,
                                  expected_source_sha256=source_hash,
                                  expected_transcript_sha256=transcript_hash,
                                  minimum_ms=5000, maximum_ms=6000,
                                  excluded_windows=windows)
                self.assertTrue(verify_render(output, receipt))
                self.assertEqual(receipt.output_sha256, digest(output))
                for start, end in windows:
                    self.assertTrue(receipt.end_ms <= start or receipt.start_ms >= end)
                windows.append((receipt.start_ms, receipt.end_ms))
                clips.append((f"fixture-job-{i}", receipt.output_sha256))
                observations.append({"seconds": round(time.perf_counter()-started, 3),
                                     "bytes": output.stat().st_size,
                                     "duration_ms": receipt.end_ms-receipt.start_ms})
            with self.assertRaises(VideoError):
                produce(root, source.name, transcript.name, root / "fourth.mp4",
                        expected_source_sha256=source_hash,
                        expected_transcript_sha256=transcript_hash,
                        minimum_ms=5000, maximum_ms=6000, excluded_windows=windows)
            self.assertFalse((root / "fourth.mp4").exists())
            manifest = bundle_manifest(agreement_id="fixture-agreement", version="v1",
                                       destination_ref="fixture-private", expected_count=3, clips=clips)
            now = datetime(2026, 11, 27, tzinfo=timezone.utc)
            result = validate_receipt(manifest, {
                "manifest_sha256": manifest_digest(manifest),
                "destination_ref": "fixture-private",
                "provider_receipt_id": "fixture-receipt",
                "accepted_at": now,
                "accepted_artifact_sha256s": [h for _, h in clips],
                "status": "accepted",
            }, dispatched_at=now, deadline=now+timedelta(minutes=5), now=now)
            self.assertFalse(result["cash_verified"])
            self.assertFalse(result["live_enabled"])
            print(json.dumps({"benchmark": "synthetic_three_clip_only",
                              "total_seconds": round(time.perf_counter()-begin, 3),
                              "clips": observations, "live_enabled": False,
                              "cash_verified": False, "transcription_measured": False,
                              "editorial_quality_measured": False,
                              "delivery_transport_measured": False}))
