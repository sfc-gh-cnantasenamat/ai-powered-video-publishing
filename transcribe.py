"""Transcription: turns acquired media into a single, global word-level
timeline of {start, end, text} — the ground truth for all chapter timestamps.

Uses Snowflake AI_TRANSCRIBE with word-level granularity. Handles >55 min
media by chunking with ffmpeg and re-basing each chunk's word timestamps onto
a single global timeline using the chunk's *actual measured* duration (not an
assumed split point), so offsets stay exact even if ffmpeg's split point
lands a little off from the requested segment_time.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field

import imageio_ffmpeg

import cache
from acquire import AcquiredMedia
from config import MAX_CHUNK_SECONDS, STAGE_FQN, TMP_DIR
from snowflake_conn import put_file, run_query


class TranscriptionError(Exception):
    pass


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    words: list[Word] = field(default_factory=list)
    duration: float = 0.0
    granularity: str = "word"
    source: str = "ai_transcribe"

    def to_dict(self):
        return {
            "words": [w.__dict__ for w in self.words],
            "duration": self.duration,
            "granularity": self.granularity,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            words=[Word(**w) for w in d["words"]],
            duration=d["duration"],
            granularity=d["granularity"],
            source=d["source"],
        )


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")


def _probe_duration(path: str) -> float:
    """Parse duration from ffmpeg's own stderr (no bundled ffprobe in
    imageio-ffmpeg, so we avoid depending on a separate ffprobe binary)."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    out = subprocess.run(
        [ffmpeg_exe, "-i", path],
        capture_output=True,
        text=True,
    )
    match = _DURATION_RE.search(out.stderr)
    if not match:
        raise TranscriptionError(f"Could not determine duration of {path}.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _chunk_media(path: str, max_chunk_seconds: int) -> list[str]:
    """Split media into <= max_chunk_seconds chunks. Returns ordered chunk paths.
    Actual chunk boundaries are measured afterward via ffprobe, not assumed."""
    duration = _probe_duration(path)
    if duration <= max_chunk_seconds:
        return [path]

    base, ext = os.path.splitext(path)
    pattern = f"{base}_chunk_%03d{ext}"
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-i",
            path,
            "-f",
            "segment",
            "-segment_time",
            str(max_chunk_seconds),
            "-reset_timestamps",
            "1",
            "-c",
            "copy",
            pattern,
        ],
        capture_output=True,
        check=True,
    )
    chunk_paths = sorted(
        os.path.join(os.path.dirname(path), f)
        for f in os.listdir(os.path.dirname(path) or ".")
        if f.startswith(os.path.basename(base) + "_chunk_") and f.endswith(ext)
    )
    if not chunk_paths:
        raise TranscriptionError("ffmpeg chunking produced no output files.")
    return chunk_paths


def _transcribe_chunk_with_ai_transcribe(chunk_path: str) -> dict:
    """Stage the chunk and call AI_TRANSCRIBE with word-level timestamps."""
    staged_name = put_file(chunk_path, STAGE_FQN)
    sql = (
        f"SELECT AI_TRANSCRIBE(TO_FILE('@{STAGE_FQN}', ?), "
        "OBJECT_CONSTRUCT('timestamp_granularity', 'word'))"
    )
    try:
        rows = run_query(sql, params=(staged_name,))
        if not rows or rows[0][0] is None:
            raise TranscriptionError("AI_TRANSCRIBE returned no result.")
        return json.loads(rows[0][0])
    finally:
        try:
            run_query(f"REMOVE '@{STAGE_FQN}/{staged_name}'")
        except Exception:
            logging.getLogger(__name__).warning("Staged media cleanup failed; check the configured stage.")


def _transcribe_via_ai_transcribe(local_media_path: str) -> Transcript:
    chunk_paths = _chunk_media(local_media_path, MAX_CHUNK_SECONDS)

    all_words: list[Word] = []
    cumulative_offset = 0.0
    for chunk_path in chunk_paths:
        result = _transcribe_chunk_with_ai_transcribe(chunk_path)
        segments = result.get("segments") or []
        for seg in segments:
            all_words.append(
                Word(
                    start=seg["start"] + cumulative_offset,
                    end=seg["end"] + cumulative_offset,
                    text=seg["text"],
                )
            )
        # Use the *actual* measured duration of this chunk (not the requested
        # segment_time) so the next chunk's offset is exact.
        cumulative_offset += _probe_duration(chunk_path)

    return Transcript(
        words=all_words,
        duration=cumulative_offset,
        granularity="word",
        source="ai_transcribe",
    )


def get_transcript(media: AcquiredMedia) -> Transcript:
    """Return a global word-level Transcript for the given media, using the cache
    when available."""
    cache_key = f"{media.cache_key}_ai"
    cached = cache.get("transcripts", cache_key)
    if cached:
        return Transcript.from_dict(cached)

    transcript = _transcribe_via_ai_transcribe(media.local_media_path)

    if not transcript.words:
        raise TranscriptionError("Transcription produced no words/segments.")

    cache.set("transcripts", cache_key, transcript.to_dict())
    return transcript
