"""Media acquisition: either a local file upload or a YouTube URL via yt-dlp.

Produces a normalized `AcquiredMedia` object that downstream transcription
and generation modules consume, regardless of source.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, urlparse

import yt_dlp
import imageio_ffmpeg

from config import TMP_DIR, YOUTUBE_COOKIES_FILE

os.makedirs(TMP_DIR, exist_ok=True)

# Make sure pip-installed console-script binaries (e.g. the `deno` JS runtime
# yt-dlp needs to solve YouTube's signature challenges) are on PATH — the
# container runtime doesn't always put the interpreter's own bin/ dir there.
_bin_dir = os.path.dirname(sys.executable)
if _bin_dir and _bin_dir not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _bin_dir + os.pathsep + os.environ.get("PATH", "")

# AI_TRANSCRIBE-supported containers (video ones can be sent to AI_TRANSCRIBE
# directly with no local audio extraction needed).
_SUPPORTED_VIDEO_EXTS = {"mp4", "mov", "mkv", "webm", "ogv"}
_SUPPORTED_AUDIO_EXTS = {"aac", "flac", "m4a", "mp3", "mp4", "ogg", "wav", "webm"}


@dataclass
class ExistingChapter:
    start_seconds: float
    title: str


@dataclass
class AcquiredMedia:
    source_type: str  # "upload" | "youtube"
    local_media_path: str  # path to the file that will be sent to AI_TRANSCRIBE
    media_kind: str  # "video" | "audio"
    cache_key: str  # stable key for caching transcript/generation results
    title: Optional[str] = None
    existing_description: Optional[str] = None
    existing_chapters: list[ExistingChapter] = field(default_factory=list)
    captions_vtt_path: Optional[str] = None  # set if usable YouTube captions were found
    captions_source: Optional[str] = None  # "manual" | "automatic"
    video_id: Optional[str] = None
    local_preview_path: Optional[str] = None  # small local video file for the UI preview player
    error: Optional[str] = None


class AcquisitionError(Exception):
    """Raised when acquisition fails in a way the UI should surface directly."""


def _base_ydl_opts() -> dict:
    """Optional local cookies do not guarantee that YouTube permits access.

    Hosted deployment does not include cookies. Use the original-file fallback
    when YouTube refuses a request rather than attempting to bypass a challenge.
    """
    opts: dict = {}
    if YOUTUBE_COOKIES_FILE and os.path.exists(YOUTUBE_COOKIES_FILE):
        opts["cookiefile"] = YOUTUBE_COOKIES_FILE
    return opts


def _file_hash(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()[:16]


def acquire_from_upload(uploaded_file) -> AcquiredMedia:
    """Save a Streamlit UploadedFile to disk and wrap it as AcquiredMedia."""
    ext = os.path.splitext(uploaded_file.name)[1].lstrip(".").lower()
    if ext not in _SUPPORTED_VIDEO_EXTS and ext not in _SUPPORTED_AUDIO_EXTS:
        raise AcquisitionError(
            f"Unsupported file type '.{ext}'. AI_TRANSCRIBE supports: "
            f"{sorted(_SUPPORTED_VIDEO_EXTS | _SUPPORTED_AUDIO_EXTS)}"
        )

    with tempfile.NamedTemporaryFile(dir=TMP_DIR, suffix=f".{ext}", delete=False) as destination:
        dest_path = destination.name
        destination.write(uploaded_file.getbuffer())

    file_hash = _file_hash(dest_path)
    media_kind = "video" if ext in _SUPPORTED_VIDEO_EXTS else "audio"

    return AcquiredMedia(
        source_type="upload",
        local_media_path=dest_path,
        media_kind=media_kind,
        cache_key=f"upload_{file_hash}",
        title=os.path.splitext(uploaded_file.name)[0],
    )


def _extract_youtube_id(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
            return None
        if parsed.port not in {None, 80, 443}:
            return None
        segments = parsed.path.strip("/").split("/")
        if parsed.hostname in {"youtu.be", "www.youtu.be"} and len(segments) == 1:
            candidate = segments[0]
        elif parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if parsed.path == "/watch":
                candidate = parse_qs(parsed.query).get("v", [""])[0]
            elif len(segments) == 2 and segments[0] in {"shorts", "embed", "live"}:
                candidate = segments[1]
            else:
                return None
        else:
            return None
    except ValueError:
        return None
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None


def acquire_from_youtube_upload(url: str, uploaded_file) -> AcquiredMedia:
    """Use an original media file with a YouTube link, without network access."""
    video_id = _extract_youtube_id(url)
    if not video_id:
        raise AcquisitionError("Enter a valid YouTube video URL.")
    media = acquire_from_upload(uploaded_file)
    media.video_id = video_id
    media.cache_key = f"{media.cache_key}_yt_{video_id}"
    return media


def _youtube_failure(error: Exception, operation: str) -> str:
    detail = str(error).lower().replace("\u2019", "'")
    fallback = (
        "Attach the original video/audio file under this URL and generate again. "
        "The app will use that file and keep the YouTube chapter links without contacting YouTube."
    )
    if "confirm you're not a bot" in detail or "confirm you are not a bot" in detail:
        return f"YouTube requires interactive bot verification for this server's request. {fallback}"
    if "403" in detail or "forbidden" in detail:
        return f"YouTube refused the {operation} request (HTTP 403). {fallback}"
    if "429" in detail or "too many requests" in detail:
        return f"YouTube rate-limited this server. Wait before retrying. {fallback}"
    return f"Could not complete the YouTube {operation} request. {fallback}"


def _pick_caption_track(info: dict) -> tuple[Optional[dict], Optional[str], Optional[str]]:
    """Prefer manual subtitles over auto-generated captions, English first."""
    for source, label in (("subtitles", "manual"), ("automatic_captions", "automatic")):
        tracks = info.get(source) or {}
        if not tracks:
            continue
        for lang in ("en", "en-US", "en-GB"):
            if lang in tracks:
                return tracks[lang], label, lang
        # fall back to first available language track
        first_lang = next(iter(tracks), None)
        if first_lang:
            return tracks[first_lang], label, first_lang
    return None, None, None


def acquire_from_youtube(url: str, prefer_captions: bool = True) -> AcquiredMedia:
    """Fetch metadata (and captions, if usable) then download audio-only media."""
    video_id = _extract_youtube_id(url)
    if not video_id:
        raise AcquisitionError("Enter a valid YouTube video URL.")
    url = f"https://www.youtube.com/watch?v={video_id}"

    metadata_opts = {**_base_ydl_opts(), "quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(metadata_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise AcquisitionError(_youtube_failure(e, "metadata")) from e

    title = info.get("title")
    existing_description = info.get("description") or None
    existing_chapters = [
        ExistingChapter(start_seconds=c["start_time"], title=c.get("title", ""))
        for c in (info.get("chapters") or [])
        if c.get("start_time") is not None
    ]

    captions_vtt_path = None
    captions_source = None
    if prefer_captions:
        track, captions_source, lang = _pick_caption_track(info)
        if track:
            caption_opts = {
                **_base_ydl_opts(),
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "writesubtitles": captions_source == "manual",
                "writeautomaticsub": captions_source == "automatic",
                "subtitleslangs": [lang],
                "subtitlesformat": "vtt",
                "outtmpl": os.path.join(TMP_DIR, f"{video_id}.%(ext)s"),
            }
            try:
                with yt_dlp.YoutubeDL(caption_opts) as ydl:
                    ydl.download([url])
                candidate = os.path.join(TMP_DIR, f"{video_id}.{lang}.vtt")
                if os.path.exists(candidate):
                    captions_vtt_path = candidate
            except yt_dlp.utils.DownloadError:
                captions_vtt_path = None  # fall back to audio transcription

    # Always download audio (used either for AI_TRANSCRIBE fallback, or if
    # the caller opts out of caption-based timing entirely).
    audio_template = os.path.join(TMP_DIR, f"{video_id}.%(ext)s")
    audio_opts = {
        **_base_ydl_opts(),
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": audio_template,
    }
    try:
        with yt_dlp.YoutubeDL(audio_opts) as ydl:
            result = ydl.extract_info(url, download=True)
            local_media_path = ydl.prepare_filename(result)
    except yt_dlp.utils.DownloadError as e:
        raise AcquisitionError(_youtube_failure(e, "audio download")) from e

    ext = os.path.splitext(local_media_path)[1].lstrip(".").lower()
    if ext not in _SUPPORTED_AUDIO_EXTS:
        raise AcquisitionError(
            f"Downloaded audio format '.{ext}' isn't supported by AI_TRANSCRIBE."
        )

    # Also download a small, low-resolution video+audio stream purely for the
    # UI preview player. Streamlit's CSP blocks embedding third-party iframes
    # (e.g. a YouTube embed), but a local media file served from the app's own
    # origin plays fine, so this is the only way to show a real video preview
    # instead of audio-only. Most videos only have a single-file (progressive)
    # option at 360p+, so to actually get down to a small size we pick a
    # low-res video-only DASH stream and mux it with a small audio-only stream
    # via ffmpeg, falling back to whatever's smallest if that's unavailable.
    local_preview_path = None
    preview_template = os.path.join(TMP_DIR, f"{video_id}_preview.%(ext)s")
    preview_opts = {
        **_base_ydl_opts(),
        "quiet": True,
        "no_warnings": True,
        "format": (
            "bestvideo[height<=240][ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo[height<=240]+bestaudio/"
            "best[height<=240]/worst[ext=mp4]/worst"
        ),
        "merge_output_format": "mp4",
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
        "outtmpl": preview_template,
    }
    try:
        with yt_dlp.YoutubeDL(preview_opts) as ydl:
            preview_result = ydl.extract_info(url, download=True)
            local_preview_path = ydl.prepare_filename(preview_result)
    except yt_dlp.utils.DownloadError:
        local_preview_path = None  # preview is best-effort; app still works without it

    return AcquiredMedia(
        source_type="youtube",
        local_media_path=local_media_path,
        media_kind="audio",
        cache_key=f"yt_{video_id}",
        title=title,
        existing_description=existing_description,
        existing_chapters=existing_chapters,
        captions_vtt_path=captions_vtt_path,
        captions_source=captions_source,
        video_id=video_id,
        local_preview_path=local_preview_path,
    )
