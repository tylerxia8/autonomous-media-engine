import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from aame.transcription import _cues_from_segments, transcribe
from aame.video import VideoError


class WhisperTimingTest(unittest.TestCase):
    def test_padded_word_timings_are_clamped_and_markup_is_inert(self):
        words = [
            {"start": 0.1, "end": 0.3, "word": " <intro> "},
            {"start": 0.25, "end": 0.4, "word": " here\n"},
            {"start": 1.8, "end": 3, "word": " end"},
        ]
        self.assertEqual(_cues_from_segments([{"words": words}], 2_000), [
            {"start_ms": 100, "end_ms": 400, "text": "‹intro› here"},
            {"start_ms": 1800, "end_ms": 2000, "text": "end"},
        ])

    def test_unaligned_speech_fails_closed(self):
        with self.assertRaisesRegex(VideoError, "missing word timings"):
            _cues_from_segments([{"text": "unverified timing"}], 2_000)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class LocalTranscriptionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "speech.mp4"
        self.model = self.root / "checkpoint.pt"
        self.captions = self.root / "captions.json"
        self.model.write_bytes(b"synthetic checkpoint")
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-threads", "1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(self.source),
        ], check=True, timeout=20)

    def transcribe(self, **overrides):
        args = {
            "expected_source_sha256": sha256(self.source),
            "expected_model_sha256": sha256(self.model),
        }
        args.update(overrides)
        return transcribe(self.root, self.source.name, self.captions,
                          model_root=self.root, model_relative_path=self.model.name, **args)

    @patch("aame.transcription._worker")
    def test_authorized_audio_reaches_fake_whisper_and_output_is_valid(self, worker):
        def recognize(directory, duration_ms):
            self.assertGreaterEqual(duration_ms, 1_900)
            self.assertEqual((directory / "model.pt").read_bytes(), b"synthetic checkpoint")
            with wave.open(str(directory / "audio.wav"), "rb") as samples:
                self.assertEqual((samples.getnchannels(), samples.getframerate()), (1, 16_000))
                self.assertGreater(samples.getnframes(), 30_000)
            (directory / "captions.json").write_text(
                json.dumps([{"start_ms": 0, "end_ms": 1_500, "text": "Test speech."}]),
                encoding="utf-8",
            )

        worker.side_effect = recognize
        self.assertEqual(self.transcribe(), sha256(self.captions))
        worker.assert_called_once()
        with self.assertRaisesRegex(VideoError, "new"):
            self.transcribe()

    @patch("aame.transcription._worker")
    def test_bad_evidence_never_calls_whisper(self, worker):
        for field in ("expected_model_sha256", "expected_source_sha256"):
            with self.subTest(field=field), self.assertRaisesRegex(VideoError, "digest"):
                self.transcribe(**{field: "f" * 64})
        worker.assert_not_called()
        self.assertFalse(self.captions.exists())
