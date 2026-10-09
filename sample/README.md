# Sample video

`vidprep_demo.mp4` is a synthetic test video you can upload to VidPrep instead of your own recording. It is about 1 minute 56 seconds long (1.3 MB, 1280x720) and has eight sections, so Generate should return several chapters.

It contains no real people, data, or account details: each section is a solid color card with a title, narrated by the macOS `say` text-to-speech voice reading a short script about how VidPrep works. `make_demo.py` is the script that built it; you can read the full narration there or rebuild the file on macOS.

The sample is not listed in `snowflake.yml` artifacts, so it is never deployed with the app.
