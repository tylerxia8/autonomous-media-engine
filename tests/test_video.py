from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from aame.video import Cue, VideoError, produce, rank_candidates, verify_render


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MomentSelectionTest(unittest.TestCase):
    def test_windows_prefer_more_speech_without_spanning_a_long_gap(self):
        cues = [
            Cue(0, 2_000, "intro"),
            Cue(8_000, 10_000, "clear useful first"),
            Cue(10_500, 12_500, "second thought"),
        ]
        ranked = rank_candidates(cues, limit=2)
        self.assertEqual((ranked[0].first_cue, ranked[0].last_cue), (1, 2))
        self.assertIn("silence_penalty", ranked[0].reasons)
        self.assertGreaterEqual(ranked[0].score, ranked[1].score)
        self.assertEqual(ranked, rank_candidates(cues, limit=2))
        with self.assertRaisesRegex(VideoError, "duration profile"):
            rank_candidates(cues, minimum_ms=15_000)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class LocalVideoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.root = Path(temp.name)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24",
             "-f", "lavfi", "-i", "sine=frequency=440", "-t", "4", "-threads", "1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.root / "valid.mp4")],
            check=True,
            timeout=30,
        )
        (cls.root / "captions.json").write_text(json.dumps([
            {"start_ms": 500, "end_ms": 1600, "text": "A useful story."},
            {"start_ms": 1700, "end_ms": 3000, "text": "A surprising conclusion."},
        ]), encoding="utf8")

    def produce(self, name, *, source="valid.mp4", transcript="captions.json", source_hash=None):
        return produce(
            self.root, source, transcript, self.root / name,
            expected_source_sha256=source_hash or digest(self.root / "valid.mp4"),
            expected_transcript_sha256=digest(self.root / transcript),
        )

    def test_captioned_mp4_passes_qa_and_tampering_fails(self):
        receipt = self.produce("clip.mp4")
        self.assertEqual((receipt.start_ms, receipt.end_ms), (500, 3000))
        clip = self.root / "clip.mp4"
        self.assertEqual(receipt.output_sha256, digest(clip))
        self.assertTrue(verify_render(clip, receipt))
        self.assertFalse(verify_render(clip, replace(receipt, end_ms=1_800)))
        with self.assertRaisesRegex(VideoError, "new"):
            self.produce("clip.mp4")
        with clip.open("ab") as out:
            out.write(b"tamper")
        self.assertFalse(verify_render(clip, receipt))

    def test_traversal_symlink_and_unverified_provenance_fail_before_output(self):
        (self.root / "linked.mp4").symlink_to(self.root / "valid.mp4")
        for source in ("../valid.mp4", "linked.mp4", str(self.root / "valid.mp4")):
            with self.subTest(source=source), self.assertRaises(VideoError):
                self.produce("unauthorized.mp4", source=source)
        with self.assertRaisesRegex(VideoError, "digest"):
            self.produce("unauthorized.mp4", source_hash="f" * 64)
        self.assertFalse((self.root / "unauthorized.mp4").exists())

    def test_checked_bytes_must_also_be_valid_media_and_captions(self):
        corrupt = self.root / "corrupt.mp4"
        corrupt.write_bytes(b"not a movie")
        with self.assertRaises(VideoError):
            self.produce("invalid.mp4", source=corrupt.name, source_hash=digest(corrupt))
        (self.root / "bad.json").write_text(
            '[{"start_ms": 0, "end_ms": 1500, "text": "<b>injection</b>"}]',
            encoding="utf8",
        )
        with self.assertRaisesRegex(VideoError, "markup"):
            self.produce("invalid.mp4", transcript="bad.json")
        self.assertFalse((self.root / "invalid.mp4").exists())
