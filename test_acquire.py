import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yt_dlp

import acquire
from generate import Chapter, GeneratedResult
from streamlit.testing.v1 import AppTest
from transcribe import Transcript, Word


class UploadedFile(io.BytesIO):
    def __init__(self, name, content=b"original media test fixture"):
        super().__init__(content)
        self.name = name


class AcquisitionTests(unittest.TestCase):
    def test_supported_youtube_urls(self):
        for url in (
            "https://youtu.be/HXWatyIxE1s?t=30",
            "https://www.youtube.com/watch?v=HXWatyIxE1s&list=playlist",
            "https://youtube.com/shorts/HXWatyIxE1s",
            "https://m.youtube.com/live/HXWatyIxE1s",
        ):
            with self.subTest(url=url):
                self.assertEqual(acquire._extract_youtube_id(url), "HXWatyIxE1s")

    def test_invalid_urls_never_reach_downloader(self):
        for url in (
            "https://example.com/?v=HXWatyIxE1s",
            "https://youtube.com.example.com/watch?v=HXWatyIxE1s",
            "https://youtube.com/watch?v=HXWatyIxE1sEXTRA",
            "file:///watch?v=HXWatyIxE1s",
            "https://youtube.com:invalid/watch?v=HXWatyIxE1s",
            "https://user:secret@youtube.com/watch?v=HXWatyIxE1s",
        ):
            with self.subTest(url=url), patch.object(acquire.yt_dlp, "YoutubeDL") as downloader:
                with self.assertRaises(acquire.AcquisitionError):
                    acquire.acquire_from_youtube(url)
                downloader.assert_not_called()

    def test_original_file_fallback_never_contacts_youtube(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(acquire, "TMP_DIR", directory):
            with patch.object(acquire.yt_dlp, "YoutubeDL") as downloader:
                media = acquire.acquire_from_youtube_upload(
                    "https://youtu.be/HXWatyIxE1s", UploadedFile("original.mp4")
                )
            downloader.assert_not_called()
            self.assertEqual(media.video_id, "HXWatyIxE1s")
            self.assertEqual(media.source_type, "upload")
            self.assertEqual(media.media_kind, "video")
            self.assertEqual(Path(media.local_media_path).read_bytes(), b"original media test fixture")
            self.assertTrue(media.cache_key.endswith("_yt_HXWatyIxE1s"))

    def test_upload_names_cannot_escape_scratch_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(acquire, "TMP_DIR", directory):
            first = acquire.acquire_from_upload(UploadedFile("../../original.mp4", b"first"))
            second = acquire.acquire_from_upload(UploadedFile("../../original.mp4", b"second"))
            self.assertEqual(Path(first.local_media_path).parent, Path(directory))
            self.assertNotEqual(first.local_media_path, second.local_media_path)
            self.assertEqual(Path(first.local_media_path).read_bytes(), b"first")

    def test_fallback_cache_distinguishes_file_contents(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(acquire, "TMP_DIR", directory):
            first = acquire.acquire_from_youtube_upload(
                "https://youtu.be/HXWatyIxE1s", UploadedFile("original.wav", b"first")
            )
            second = acquire.acquire_from_youtube_upload(
                "https://youtu.be/HXWatyIxE1s", UploadedFile("original.wav", b"second")
            )
            self.assertNotEqual(first.cache_key, second.cache_key)
            self.assertEqual(first.media_kind, "audio")

    def test_bot_verification_is_reported_without_raw_error(self):
        with patch.object(acquire.yt_dlp, "YoutubeDL") as downloader:
            downloader.return_value.__enter__.return_value.extract_info.side_effect = (
                yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot. sensitive-detail")
            )
            with self.assertRaises(acquire.AcquisitionError) as caught:
                acquire.acquire_from_youtube("https://youtu.be/HXWatyIxE1s")
            self.assertIn("interactive bot verification", str(caught.exception))
            self.assertNotIn("sensitive-detail", str(caught.exception))

    def test_http_error_classification(self):
        self.assertIn("HTTP 403", acquire._youtube_failure(Exception("HTTP Error 403"), "audio"))
        self.assertIn("rate-limited", acquire._youtube_failure(Exception("HTTP Error 429"), "metadata"))


class AppRecoveryTests(unittest.TestCase):
    def test_missing_input_clears_old_output(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
        app.session_state["result"] = GeneratedResult(description="Old result")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertNotIn("result", app.session_state)
        self.assertFalse(app.tabs)
        self.assertTrue(app.warning)

    def test_failed_request_clears_old_output(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
        app.radio[0].set_value("YouTube link").run()
        app.text_input[0].set_value("https://youtu.be/HXWatyIxE1s").run()
        app.session_state["result"] = GeneratedResult(description="Previous video's result")
        with patch.object(acquire, "acquire_from_youtube", side_effect=acquire.AcquisitionError("Bot verification")):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertIn("Bot verification", app.error[0].value)
        self.assertNotIn("result", app.session_state)
        self.assertFalse(app.tabs)

    def test_original_file_flows_through_ui_with_youtube_links(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
        app.radio[0].set_value("YouTube link").run()
        app.text_input[0].set_value("https://youtu.be/HXWatyIxE1s").run()
        transcript = Transcript(words=[Word(0, 1, "Welcome")], duration=1)
        result = GeneratedResult(description="Description", chapters=[Chapter(0, "Welcome")])
        with tempfile.TemporaryDirectory() as directory, patch.object(acquire, "TMP_DIR", directory):
            with (
                patch("streamlit.file_uploader", return_value=UploadedFile("original.mp4")),
                patch.object(acquire.yt_dlp, "YoutubeDL") as downloader,
                patch("transcribe.get_transcript", return_value=transcript) as transcribe,
                patch("generate.generate", return_value=result) as generate,
            ):
                app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            downloader.assert_not_called()
            transcribe.assert_called_once()
            generate.assert_called_once()
            self.assertTrue(any("https://youtu.be/HXWatyIxE1s?t=0" in entry.value for entry in app.markdown))
            self.assertEqual(app.session_state["media"].media_kind, "video")


if __name__ == "__main__":
    unittest.main()