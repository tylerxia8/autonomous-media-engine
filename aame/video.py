"""Local clip production from a hash-authorized MP4 and timestamped transcript."""

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import heapq
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata


MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_SOURCE_MS = 60 * 60 * 1000
MAX_CLIP_MS = 35_000
WIDTH = 720
HEIGHT = 1280
RECIPE_VERSION = "vertical-captioned-v1"
SCORING_VERSION = "transcript-window-v2"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MOV_DEMUXER = ["-f", "mov", "-enable_drefs", "0", "-max_streams", "16"]


class VideoError(ValueError):
    """An input, dependency, render or technical QA failure."""


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class RenderReceipt:
    source_sha256: str
    transcript_sha256: str
    output_sha256: str
    start_ms: int
    end_ms: int
    recipe_version: str = RECIPE_VERSION
    scoring_version: str = SCORING_VERSION
    selection_score: int = 0
    selection_reasons: tuple[str, ...] = ()


def _snapshot(root, relative_path, destination, expected_hash, limit):
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or any(p == ".." for p in path.parts):
        raise VideoError("asset must be a relative path inside the authorized source root")
    if not isinstance(expected_hash, str) or _SHA256.fullmatch(expected_hash) is None:
        raise VideoError("authorization must specify a lowercase SHA-256 digest")

    # Open each component relative to the previous directory descriptor so no
    # symlink or concurrent directory replacement can redirect an open.
    directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    handles = []
    digest = hashlib.sha256()
    total = 0
    try:
        handles.append(os.open(root, directory))
        for part in path.parts[:-1]:
            handles.append(os.open(part, directory, dir_fd=handles[-1]))
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=handles[-1])
        with os.fdopen(fd, "rb") as source, destination.open("xb") as copy:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise VideoError("asset is empty, oversized or not a regular file")
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise VideoError("asset exceeds its byte limit")
                digest.update(chunk)
                copy.write(chunk)
    except OSError as exc:
        raise VideoError("could not open an authorized local asset") from exc
    finally:
        for fd in reversed(handles):
            os.close(fd)
    if not hmac.compare_digest(digest.hexdigest(), expected_hash):
        raise VideoError("asset digest does not match authorization")


def _run(program, arguments, directory, timeout):
    executable = shutil.which(program)
    if not executable:
        raise VideoError(f"{program} is required for local production")
    try:
        result = subprocess.run(
            [executable, *arguments],
            cwd=directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if program == "ffprobe" else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VideoError(f"{program} failed or exceeded its time limit") from exc
    return result.stdout


def _probe(path):
    try:
        payload = _run(
            "ffprobe",
            ["-v", "error", "-protocol_whitelist", "file", "-max_alloc", "134217728",
             *_MOV_DEMUXER,
             "-show_entries",
             "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,duration",
             "-of", "json", "./" + path.name],
            path.parent,
            15,
        )
        probe = json.loads(payload)
        duration_ms = int(Fraction(probe["format"]["duration"]) * 1000)
        return duration_ms, probe["streams"]
    except (TypeError, KeyError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise VideoError("invalid or unsupported media metadata") from exc


def _source_duration(path):
    duration, streams = _probe(path)
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if not 1000 <= duration <= MAX_SOURCE_MS or len(videos) != 1 or len(audios) != 1:
        raise VideoError("source must have one video and one audio stream and last 1s–1h")
    video = videos[0]
    try:
        fps = Fraction(video["avg_frame_rate"])
        width, height = video["width"], video["height"]
        if not (2 <= width <= 3840 and 2 <= height <= 3840 and 0 < fps <= 120):
            raise VideoError("source video exceeds supported resolution or frame rate")
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise VideoError("invalid or unsupported source video stream") from exc
    return duration


def _cue_text(value):
    if not isinstance(value, str) or any(unicodedata.category(c)[0] == "C" for c in value):
        raise VideoError("caption contains control characters or is not text")
    text = " ".join(value.split())
    if not 1 <= len(text) <= 100 or any(c in text for c in "<>{}\\"):
        raise VideoError("caption exceeds the text limit or contains subtitle markup")
    return text


def _load_cues(path, duration):
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise VideoError("malformed timestamped transcript") from exc
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise VideoError("transcript must contain 1–10000 caption cues")
    cues = []
    previous_end = 0
    for row in rows:
        if not isinstance(row, dict):
            raise VideoError("transcript cue must be a JSON object")
        start, end = row.get("start_ms"), row.get("end_ms")
        if (
            type(start) is not int
            or type(end) is not int
            or not previous_end <= start < end <= duration
            or end - start > MAX_CLIP_MS
        ):
            raise VideoError("transcript cues must be ordered, nonoverlapping and inside the source")
        cues.append(Cue(start, end, _cue_text(row.get("text"))))
        previous_end = end
    return cues


@dataclass(frozen=True)
class ClipCandidate:
    first_cue: int
    last_cue: int
    start_ms: int
    end_ms: int
    score: int
    reasons: tuple[str, ...]
    version: str = SCORING_VERSION


def rank_candidates(cues, *, limit=1, minimum_ms=1_000, maximum_ms=MAX_CLIP_MS):
    """Rank bounded contiguous cue windows with reproducible explanations."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise VideoError("candidate limit must be between 1 and 20")
    if (
        type(minimum_ms) is not int or type(maximum_ms) is not int
        or not 1_000 <= minimum_ms <= maximum_ms <= MAX_CLIP_MS
    ):
        raise VideoError("invalid clip duration profile")

    def windows():
        for first, beginning in enumerate(cues):
            words = speech = 0
            for last in range(first, min(first + 80, len(cues))):
                cue = cues[last]
                if last > first and cue.start_ms - cues[last - 1].end_ms > 2_500:
                    break
                duration = cue.end_ms - beginning.start_ms
                if duration > maximum_ms:
                    break
                words += len(cue.text.split())
                speech += cue.end_ms - cue.start_ms
                if duration < minimum_ms:
                    continue
                band_distance = max(12_000 - duration, duration - 25_000, 0)
                dead_air = duration - speech
                reasons = ["caption_speech"]
                if band_distance:
                    reasons.append("outside_preferred_length")
                else:
                    reasons.append("preferred_length")
                if dead_air >= 500:
                    reasons.append("silence_penalty")
                score = min(words, 55) * 100 - band_distance // 10 - dead_air // 20
                yield ClipCandidate(
                    first, last, beginning.start_ms, cue.end_ms, score, tuple(reasons),
                )

    candidates = heapq.nlargest(
        limit, windows(),
        key=lambda candidate: (
            candidate.score, -candidate.start_ms, -(candidate.end_ms - candidate.start_ms),
        ),
    )
    if not candidates:
        raise VideoError("no usable clip candidate fits the duration profile")
    return candidates


def _srt_time(milliseconds):
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _render(directory, cues):
    start, end = cues[0].start_ms, cues[-1].end_ms
    events = [
        f"{i}\n{_srt_time(cue.start_ms - start)} --> {_srt_time(cue.end_ms - start)}\n{cue.text}\n"
        for i, cue in enumerate(cues, 1)
    ]
    (directory / "captions.srt").write_text("\n".join(events), encoding="utf-8")
    # Bold readable captions and a neutral vertical canvas preserve the source frame.
    filters = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,"
        "subtitles=captions.srt:force_style='Fontsize=21,Bold=1,MarginV=48,Outline=2'"
    )
    _run("ffmpeg", [
        "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
        "-max_alloc", "134217728", "-filter_threads", "1",
        "-ss", f"{start / 1000:.3f}", "-protocol_whitelist", "file",
        "-threads", "2", "-max_pixels", str(3840 * 3840), *_MOV_DEMUXER, "-i", "source.mp4",
        "-protocol_whitelist", "file", "-f", "srt", "-i", "captions.srt",
        "-map", "0:v:0", "-map", "0:a:0", "-map", "1:s:0", "-map_metadata", "-1",
        "-map_chapters", "-1", "-vf", filters, "-threads", "2",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ac", "2", "-c:s", "mov_text",
        "-t", f"{(end - start) / 1000:.3f}", "-fs", str(MAX_OUTPUT_BYTES),
        "-movflags", "+faststart", "clip.mp4",
    ], directory, 180)


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_render(output: Path, receipt: RenderReceipt) -> bool:
    """Verify hash, stream layout and decode viability in a caller-owned output directory."""
    output = Path(output)
    try:
        if (
            receipt.recipe_version != RECIPE_VERSION
            or not 1_000 <= receipt.end_ms - receipt.start_ms <= MAX_CLIP_MS
            or not stat.S_ISREG(output.lstat().st_mode)
            or not 0 < output.stat().st_size <= MAX_OUTPUT_BYTES
            or not hmac.compare_digest(_sha256(output), receipt.output_sha256)
        ):
            return False
        duration, streams = _probe(output)
        if abs(duration - (receipt.end_ms - receipt.start_ms)) > 175:
            return False
        if [stream.get("codec_type") for stream in streams] != ["video", "audio", "subtitle"]:
            return False
        video, audio, captions = streams
        if (
            (video.get("width"), video.get("height"), video.get("codec_name"))
            != (WIDTH, HEIGHT, "h264")
            or audio.get("codec_name") != "aac"
            or captions.get("codec_name") != "mov_text"
            or abs(int(Fraction(video["duration"]) * 1000) - duration) > 175
            or abs(int(Fraction(audio["duration"]) * 1000) - duration) > 250
        ):
            return False
        _run("ffmpeg", [
            "-v", "error", "-xerror", "-nostdin", "-protocol_whitelist", "file",
            "-max_alloc", "134217728", "-threads", "2", "-max_pixels", str((WIDTH + 64) * (HEIGHT + 64)),
            *_MOV_DEMUXER,
            "-i", "./" + output.name, "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
        ], output.parent, 35)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError):
        return False
    return True


def produce(
    source_root: Path,
    asset_relative_path: str,
    transcript_relative_path: str,
    output: Path,
    *,
    expected_source_sha256: str,
    expected_transcript_sha256: str,
    minimum_ms: int = 1_000,
    maximum_ms: int = MAX_CLIP_MS,
) -> RenderReceipt:
    """Render a clip atomically. Both authorized digests are mandatory."""
    output = Path(output)
    if output.suffix != ".mp4" or output.exists() or output.is_symlink():
        raise VideoError("output must be a new .mp4 file")
    try:
        with tempfile.TemporaryDirectory(prefix=".aame-video-", dir=output.parent) as scratch:
            directory = Path(scratch)
            source = directory / "source.mp4"
            transcript = directory / "transcript.json"
            _snapshot(source_root, asset_relative_path, source, expected_source_sha256, MAX_SOURCE_BYTES)
            _snapshot(source_root, transcript_relative_path, transcript, expected_transcript_sha256,
                      MAX_TRANSCRIPT_BYTES)
            all_cues = _load_cues(transcript, _source_duration(source))
            winner = rank_candidates(all_cues, minimum_ms=minimum_ms, maximum_ms=maximum_ms)[0]
            cues = all_cues[winner.first_cue:winner.last_cue + 1]
            _render(directory, cues)
            clip = directory / "clip.mp4"
            receipt = RenderReceipt(
                expected_source_sha256, expected_transcript_sha256, _sha256(clip),
                winner.start_ms, winner.end_ms, selection_score=winner.score,
                selection_reasons=winner.reasons,
            )
            if not verify_render(clip, receipt):
                raise VideoError("render did not pass local technical checks")
            os.link(clip, output)
    except OSError as exc:
        raise VideoError("could not publish the local render atomically") from exc
    return receipt
