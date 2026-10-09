"""Streamlit app: uploaded video -> description + accurate timestamped chapters."""

import traceback

import streamlit as st

import enhance
from acquire import AcquisitionError, acquire_from_upload
from generate import GenerationError, format_timestamp, generate
from transcribe import TranscriptionError, get_transcript

st.set_page_config(
    page_title="VidPrep",
    page_icon=":material/schedule:",
    layout="wide",
)

st.title(":material/schedule: VidPrep")
st.caption(
    "Upload a video or audio file. Timestamps are resolved from "
    "real transcribed word timings — never guessed by the model."
)

st.header("Input")

with st.container(border=True):
    uploaded_file = st.file_uploader(
        "Video or audio file", type=["mp4", "mov", "mkv", "webm", "ogv", "m4a", "mp3", "wav", "flac", "aac", "ogg"]
    )

    generate_clicked = st.button("Generate", type="primary")

if generate_clicked:
    for result_key in ("media", "result", "transcript", "seek_seconds", "extras", "output_tab"):
        st.session_state.pop(result_key, None)
    if uploaded_file is None:
        st.warning("Please upload a file first.")
    else:
        progress = st.empty()
        try:
            progress.progress(0, text="Acquiring media...")
            media = acquire_from_upload(uploaded_file)
            progress.progress(25, text=f"Acquired: {media.title or 'media'}")

            progress.progress(40, text="Transcribing (this is the long step)...")
            transcript = get_transcript(media)
            progress.progress(
                80,
                text=f"Transcribed ({len(transcript.words)} words, {transcript.duration:.0f}s)",
            )

            progress.progress(90, text="Generating description and chapters...")
            result = generate(media, transcript)
            progress.progress(100, text="Done")
            progress.empty()

            st.session_state["media"] = media
            st.session_state["result"] = result
            st.session_state["transcript"] = transcript
            st.session_state["seek_seconds"] = 0.0
            st.session_state["extras"] = {}

        except AcquisitionError as e:
            progress.empty()
            st.error(f"Could not acquire media: {e}")
        except TranscriptionError as e:
            progress.empty()
            st.error(f"Transcription failed: {e}")
        except GenerationError as e:
            progress.empty()
            st.error(f"Generation failed: {e}")
        except Exception as e:
            progress.empty()
            st.error(f"Unexpected error: {e}")
            st.code(traceback.format_exc())

if "result" in st.session_state:
    media = st.session_state["media"]
    result = st.session_state["result"]
    transcript = st.session_state["transcript"]
    st.session_state.setdefault("seek_seconds", 0.0)
    st.session_state.setdefault("extras", {})
    extras = st.session_state["extras"]

    st.header("Output")

    with st.container(border=True):
        # A keyed, stateful tab set keeps the selected tab when an extras button reruns the app.
        tab_overview, tab_titles_seo, tab_thumbs, tab_captions = st.tabs(
            ["Overview", "Titles & SEO", "Thumbnails & Clips", "Captions & FAQ"],
            key="output_tab",
            on_change="rerun",
        )

        with tab_overview:
            left, right = st.columns([3, 2])

            # NOTE: this block must run before the "right" block below so that a
            # button click updates seek_seconds in session_state before the video
            # player (in the right column) reads it in this same script run.
            with left:
                st.subheader("Chapters")
                st.caption("Click a timestamp to jump the preview player to that moment.")

                for i, c in enumerate(result.chapters):
                    ts = format_timestamp(c.start_seconds)
                    row_cols = st.columns([1, 4])
                    with row_cols[0]:
                        if st.button(ts, key=f"seek_btn_{i}"):
                            st.session_state["seek_seconds"] = c.start_seconds
                    with row_cols[1]:
                        st.markdown(f"**{c.title}**")

            with right:
                st.subheader("Preview")
                seek_seconds = int(st.session_state["seek_seconds"])
                if media.media_kind == "video":
                    st.video(media.local_media_path, start_time=seek_seconds)
                else:
                    st.audio(media.local_media_path, start_time=seek_seconds)

            st.subheader("Description")
            lines = [result.description, "", "⏳ Timestamps"]
            for c in result.chapters:
                lines.append(f"{format_timestamp(c.start_seconds)} {c.title}")
            if result.keywords:
                lines += ["", "🔑 Keywords", ", ".join(result.keywords)]
            st.code("\n".join(lines), language=None)

        with tab_titles_seo:
            if st.button("Generate title & SEO suggestions", key="gen_titles_seo"):
                try:
                    with st.spinner("Generating title, category, and end-screen suggestions..."):
                        extras["titles_seo"] = enhance.generate_titles_seo(media, result, transcript.duration)
                except GenerationError as e:
                    st.error(f"Generation failed: {e}")

            titles_seo = extras.get("titles_seo")
            if titles_seo:
                st.subheader("Title suggestions")
                st.code("\n".join(titles_seo.titles), language=None)

                st.subheader("Category")
                st.write(f"**{titles_seo.category or 'Unknown'}** — {titles_seo.category_reason}")

                st.subheader("End screen")
                st.write(
                    f"Around **{format_timestamp(titles_seo.endscreen_seconds)}**: "
                    f"{titles_seo.endscreen_suggestion}"
                )

                st.subheader("SEO checklist")
                for item in enhance.seo_checklist(result, titles_seo.titles):
                    icon = ":material/check_circle:" if item["passed"] else ":material/warning:"
                    st.write(f"{icon} **{item['label']}** — {item['detail']}")
            else:
                st.caption("Click the button above to generate title, category, and SEO suggestions.")

        with tab_thumbs:
            st.subheader("Thumbnail candidates")
            if st.button("Generate thumbnail candidates", key="gen_thumbs"):
                extras["thumbnails"] = enhance.generate_thumbnails(media, result)

            thumbnails = extras.get("thumbnails")
            if thumbnails:
                thumb_cols = st.columns(min(len(thumbnails), 5) or 1)
                for i, t in enumerate(thumbnails):
                    with thumb_cols[i % len(thumb_cols)]:
                        st.image(t.image_path, caption=f"{format_timestamp(t.seconds)} — {t.chapter_title}")
            elif thumbnails == []:
                st.caption("No video available to extract thumbnail frames from (audio-only source).")
            else:
                st.caption("Click the button above to extract candidate thumbnail frames.")

            st.divider()
            st.subheader("Pull quotes / social clips")
            if st.button("Generate pull quotes", key="gen_quotes"):
                try:
                    with st.spinner("Scanning transcript for quotable moments..."):
                        extras["quotes"] = enhance.generate_quotes(media, transcript)
                except GenerationError as e:
                    st.error(f"Generation failed: {e}")

            quotes = extras.get("quotes")
            if quotes:
                for q in quotes:
                    st.markdown(f"> {q.text}")
                    st.caption(f"{format_timestamp(q.start_seconds)} - {format_timestamp(q.end_seconds)}")
            elif quotes == []:
                st.caption("No quotable moments found.")
            else:
                st.caption("Click the button above to find quotable moments for social/teaser clips.")

        with tab_captions:
            st.subheader("Caption file export")
            srt_text = enhance.build_srt(transcript)
            vtt_text = enhance.build_vtt(transcript)
            base_name = (media.title or "captions").replace(" ", "_")
            dl_cols = st.columns(2)
            with dl_cols[0]:
                st.download_button("Download .srt", srt_text, file_name=f"{base_name}.srt", mime="text/plain")
            with dl_cols[1]:
                st.download_button("Download .vtt", vtt_text, file_name=f"{base_name}.vtt", mime="text/vtt")

            st.divider()
            st.subheader("FAQ / Timestamps for X")
            if st.button("Generate FAQ", key="gen_faq"):
                try:
                    with st.spinner("Generating FAQ from chapters..."):
                        extras["faq"] = enhance.generate_faq(media, result)
                except GenerationError as e:
                    st.error(f"Generation failed: {e}")

            faq = extras.get("faq")
            if faq:
                lines = []
                for item in faq:
                    st.markdown(f"**{item.question}**")
                    st.write(item.answer)
                    st.caption(f"See {format_timestamp(item.start_seconds)} — {item.chapter_title}")
                    lines.append(f"{format_timestamp(item.start_seconds)} {item.question}")
                st.subheader("Copy-paste \"Timestamps for X\" block")
                st.code("\n".join(lines), language=None)
            elif faq == []:
                st.caption("No FAQ items generated.")
            else:
                st.caption("Click the button above to generate an FAQ from the chapters.")
