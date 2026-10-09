"""Media acquisition: save an uploaded video or audio file for processing.

Produces a normalized `AcquiredMedia` object that downstream transcription
and generation modules consume.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

from config import TMP_DIR

os.makedirs(TMP_DIR, exist_ok=True)

# AI_TRANSCRIBE-supported containers (video ones can be sent to AI_TRANSCRIBE
# directly with no local audio extraction needed).
_SUPPORTED_VIDEO_EXTS = {"mp4", "mov", "mkv", "webm", "ogv"}
_SUPPORTED_AUDIO_EXTS = {"aac", "flac", "m4a", "mp3", "mp4", "ogg", "wav", "webm"}


@dataclass
class AcquiredMedia:
    source_type: str  # "upload"
    local_media_path: str  # path to the file that will be sent to AI_TRANSCRIBE
    media_kind: str  # "video" | "audio"
    cache_key: str  # stable key for caching transcript/generation results
    title: Optional[str] = None


class AcquisitionError(Exception):
    """Raised when acquisition fails in a way the UI should surface directly."""


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
