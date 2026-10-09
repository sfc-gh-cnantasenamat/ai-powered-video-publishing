# VidPrep

Upload your own video or audio to generate chapters, descriptions, titles, keywords, thumbnails, captions, quotes, and an FAQ with Snowflake Cortex.

## Run locally

Install the dependencies listed in `pyproject.toml` in your Python environment. Configure a named Snowflake connection outside the repository, then run:

```bash
SNOWFLAKE_DEFAULT_CONNECTION_NAME=devrel python -m streamlit run app.py
```

The connection must be authorized to use the stage configured in `config.py` and the required Cortex functions. For another local profile, replace `devrel` with its name. Hosted Streamlit uses its embedded identity.

Optional environment overrides: `VIDPREP_STAGE_FQN` (three unquoted identifiers), `VIDPREP_CACHE_DIR` (isolated local cache/scratch directory). Defaults remain `VIDPREP_DB.APPS.VIDPREP_STAGE` and `.cache`.

## YouTube input

URL-only downloading is best-effort and can fail with bot verification, HTTP 403, or rate limits. Attach the original file under the YouTube URL to process that file without contacting YouTube, retaining chapter links. Use media you own or are authorized to process.

Cookies are not required, auto-discovered, or included in deployment artifacts. `VIDPREP_YOUTUBE_COOKIES_FILE` is an explicit optional local-only credential path; do not commit or deploy that file, and do not treat cookies as a guarantee of access.

## Deploy and clean up

Follow the [guide](https://github.com/sfc-gh-cnantasenamat/sfguide-ai-powered-video-publishing). Check all names in `snowflake.yml` before deploying. Do not replace a preexisting app unintentionally. The manifest contains only source files and dependency metadata.

Stop local processes you started. Remove only your run-owned staged media, temporary files, and isolated test schema/app after retaining results. Leave shared warehouses, compute pools, integrations, and existing deployments intact.

Local regression tests use mocked cloud calls and do not certify hosted execution:

```bash
python -m unittest discover -s . -p 'test_*.py' -v
```