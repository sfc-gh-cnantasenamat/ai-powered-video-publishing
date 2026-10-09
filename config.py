"""Central configuration constants for the video-automation app."""

import os
import re

# Fully-qualified internal stage used to stage audio/video files for AI_TRANSCRIBE.
STAGE_FQN = os.getenv("VIDPREP_STAGE_FQN", "VIDPREP_DB.APPS.VIDPREP_STAGE")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", STAGE_FQN):
    raise ValueError("VIDPREP_STAGE_FQN must contain three unquoted Snowflake identifiers")

# Model used for AI_COMPLETE description/chapter generation.
COMPLETE_MODEL = "claude-sonnet-5"

# Max output tokens for AI_COMPLETE calls (generous to avoid truncation).
COMPLETE_MAX_TOKENS = 8192

# AI_TRANSCRIBE limits (seconds) — chunk longer media to stay safely under the
# documented 60-minute cap when using word-level timestamp granularity.
MAX_CHUNK_SECONDS = 55 * 60

# Target number of chapters to aim for in generated output.
MIN_CHAPTERS = 6
MAX_CHAPTERS = 12

# Minimum gap (seconds) enforced between two consecutive chapter start times.
MIN_CHAPTER_GAP_SECONDS = 10

# Local cache directory for transcripts and generated results.
CACHE_DIR = os.getenv("VIDPREP_CACHE_DIR", ".cache")

# Local scratch directory for uploaded media before staging.
TMP_DIR = os.path.join(CACHE_DIR, "tmp")
