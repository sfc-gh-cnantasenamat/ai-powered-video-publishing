# VidPrep

Upload your own video or audio file to generate chapters, descriptions, titles, keywords, thumbnails, captions, quotes, and an FAQ with Snowflake Cortex.

## Sample video

No video handy? Upload `sample/vidprep_demo.mp4`, a two-minute synthetic narrated demo with no real people or data. See `sample/README.md` for how it was made.

## Run locally

Install the dependencies listed in `pyproject.toml` in your Python environment. Configure a named Snowflake connection outside the repository, then run:

```bash
SNOWFLAKE_DEFAULT_CONNECTION_NAME=devrel python -m streamlit run app.py
```

The connection must be authorized to use the stage configured in `config.py` and the required Cortex functions. For another local profile, replace `devrel` with its name. Hosted Streamlit uses its embedded identity.

Optional environment overrides: `VIDPREP_STAGE_FQN` (three unquoted identifiers), `VIDPREP_CACHE_DIR` (isolated local cache/scratch directory). Defaults remain `VIDPREP_DB.APPS.VIDPREP_STAGE` and `.cache`.

## Deploy and clean up

Follow the [guide](https://github.com/sfc-gh-cnantasenamat/sfguide-ai-powered-video-publishing). Check all names in `snowflake.yml` before deploying. Do not replace a preexisting app unintentionally. The manifest contains only source files and dependency metadata.

Stop local processes you started. Remove only your run-owned staged media, temporary files, and isolated test schema/app after retaining results. Leave shared warehouses, compute pools, integrations, and existing deployments intact.

Local regression tests use mocked cloud calls and do not certify hosted execution:

```bash
python -m unittest discover -s . -p 'test_*.py' -v
```