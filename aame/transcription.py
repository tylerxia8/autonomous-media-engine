"""Transcribe authorized local MP4 audio with an explicitly pinned Whisper model."""

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unicodedata
import wave

from .video import MAX_SOURCE_BYTES, MAX_TRANSCRIPT_BYTES, VideoError
from .video import _MOV_DEMUXER, _load_cues, _run, _snapshot, _source_duration


MAX_AUDIO_MS = 15 * 60 * 1000
MAX_MODEL_BYTES = 512 * 1024 * 1024
TRANSCRIBE_TIMEOUT_S = 900
CAPTION_MS = 5_000
CAPTION_CHARS = 80


def _timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise VideoError("Whisper returned an invalid word timestamp")
    return round(value * 1000)


def _caption_text(value):
    if not isinstance(value, str):
        raise VideoError("Whisper returned invalid word text")
    plain = "".join(
        char for char in value
        if not unicodedata.category(char).startswith("C") or char.isspace()
    )
    replacements = str.maketrans("<>{}\\", "‹›｛｝⧵")
    return " ".join(plain.translate(replacements).split())


def _cues_from_segments(segments, duration_ms):
    cues = []
    previous_end = 0
    for segment in segments:
        words = segment.get("words", [])
        if not words and str(segment.get("text", "")).strip():
            raise VideoError("Whisper output is missing word timings")
        start = end = 0
        text = ""
        for entry in words:
            word = _caption_text(entry.get("word"))
            if not word:
                continue
            if len(word) > CAPTION_CHARS:
                raise VideoError("Whisper returned an oversized word")
            word_start = max(previous_end, min(duration_ms, _timestamp(entry.get("start"))))
            word_end = min(duration_ms, _timestamp(entry.get("end")))
            if word_end <= word_start:
                continue
            if word_end - word_start > CAPTION_MS:
                raise VideoError("Whisper returned an overlong word timing")
            if text and (
                word_start - end > 1_000
                or word_end - start > CAPTION_MS
                or len(text) + 1 + len(word) > CAPTION_CHARS
            ):
                cues.append({"start_ms": start, "end_ms": end, "text": text})
                text = ""
            if not text:
                start = word_start
                text = word
            else:
                text += " " + word
            end = word_end
            previous_end = end
        if text:
            cues.append({"start_ms": start, "end_ms": end, "text": text})
    if not cues:
        raise VideoError("Whisper did not return any usable speech")
    return cues


def _recognize(audio, weights, duration_ms):
    # Load the checkpoint ourselves to require weights-only deserialization and
    # avoid Whisper's model-name lookup and download path.
    import numpy
    import torch
    from whisper.model import ModelDimensions, Whisper

    torch.set_num_threads(2)
    checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
    model = Whisper(ModelDimensions(**checkpoint["dims"]))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    with wave.open(str(audio), "rb") as source:
        pcm = source.readframes(source.getnframes())
    samples = numpy.frombuffer(pcm, dtype="<i2").astype(numpy.float32) / 32768.0
    result = model.transcribe(samples, fp16=False, word_timestamps=True, verbose=None)
    return _cues_from_segments(result["segments"], duration_ms)


def _worker(directory, duration_ms):
    # The subprocess can import this project from its resolved source root,
    # regardless of the caller's current working directory.
    command = (
        "from pathlib import Path; import json, sys; "
        "from aame.transcription import _recognize; "
        "cues = _recognize(Path('audio.wav'), Path('model.pt'), int(sys.argv[1])); "
        "Path('captions.json').write_text(json.dumps(cues, ensure_ascii=False), encoding='utf-8')"
    )
    environment = {
        "PATH": os.defpath,
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
        "HOME": str(directory.resolve()),
        "TIKTOKEN_CACHE_DIR": str(directory.resolve()),
        "CUDA_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": "2",
    }
    try:
        subprocess.run(
            [sys.executable, "-B", "-c", command, str(duration_ms)],
            cwd=directory,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=TRANSCRIBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VideoError("local Whisper worker failed or exceeded its time limit") from exc


def transcribe(
    source_root: Path,
    asset_relative_path: str,
    output: Path,
    *,
    expected_source_sha256: str,
    model_root: Path,
    model_relative_path: str,
    expected_model_sha256: str,
) -> str:
    """Transcribe bounded local audio and return the output JSON's SHA-256."""
    output = Path(output)
    if output.suffix != ".json" or output.exists() or output.is_symlink():
        raise VideoError("output must be a new .json file")
    try:
        with tempfile.TemporaryDirectory(prefix=".aame-transcription-", dir=output.parent) as tmp:
            directory = Path(tmp)
            source = directory / "source.mp4"
            model = directory / "model.pt"
            _snapshot(source_root, asset_relative_path, source, expected_source_sha256, MAX_SOURCE_BYTES)
            duration_ms = _source_duration(source)
            if duration_ms > MAX_AUDIO_MS:
                raise VideoError("source exceeds the offline transcription duration limit")
            _snapshot(model_root, model_relative_path, model, expected_model_sha256, MAX_MODEL_BYTES)
            # FFmpeg decodes only audio. Whisper receives samples, so it does not
            # invoke its own FFmpeg process or parse the original media.
            _run("ffmpeg", [
                "-v", "error", "-nostdin", "-n", "-protocol_whitelist", "file",
                "-max_alloc", "134217728", "-threads", "2", *_MOV_DEMUXER,
                "-i", "source.mp4", "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", "-t", f"{duration_ms / 1000:.3f}", "audio.wav",
            ], directory, 90)
            _worker(directory, duration_ms)
            captions = directory / "captions.json"
            if not 0 < captions.stat().st_size <= MAX_TRANSCRIPT_BYTES:
                raise VideoError("generated transcript exceeds its byte limit")
            _load_cues(captions, duration_ms)
            digest = hashlib.sha256(captions.read_bytes()).hexdigest()
            os.link(captions, output)
    except OSError as exc:
        raise VideoError("could not complete offline transcription") from exc
    return digest
