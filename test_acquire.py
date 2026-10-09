import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acquire
from generate import Chapter, GeneratedResult
from streamlit.testing.v1 import AppTest
from transcribe import Transcript, Word


class UploadedFile(io.BytesIO):
    def __init__(self, name, content=b"original media test fixture"):
        super().__init__(content)
        self.name = name


class AcquisitionTests(unittest.TestCase):
    def test_upload_names_cannot_escape_scratch_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(acquire, "TMP_DIR", directory):
            first = acquire.acquire_from_upload(UploadedFile("../../original.mp4", b"first"))
            second = acquire.acquire_from_upload(UploadedFile("../../original.mp4", b"second"))
            self.assertEqual(Path(first.local_media_path).parent, Path(directory))
            self.assertNotEqual(first.local_media_path, second.local_media_path)
            self.assertEqual(Path(first.local_media_path).read_bytes(), b"first")

    def test_cache_key_distinguishes_file_contents(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(acquire, "TMP_DIR", directory):
            first = acquire.acquire_from_upload(UploadedFile("original.wav", b"first"))
            second = acquire.acquire_from_upload(UploadedFile("original.wav", b"second"))
            self.assertNotEqual(first.cache_key, second.cache_key)
            self.assertEqual(first.media_kind, "audio")

    def test_video_upload_is_video_kind(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(acquire, "TMP_DIR", directory):
            media = acquire.acquire_from_upload(UploadedFile("original.mp4"))
            self.assertEqual(media.source_type, "upload")
            self.assertEqual(media.media_kind, "video")
            self.assertEqual(media.title, "original")

    def test_unsupported_extension_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(acquire, "TMP_DIR", directory):
            with self.assertRaises(acquire.AcquisitionError):
                acquire.acquire_from_upload(UploadedFile("notes.txt"))


class AppRecoveryTests(unittest.TestCase):
    def test_input_is_upload_only(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.radio)
        self.assertFalse(app.text_input)
        self.assertFalse(app.toggle)

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
        app.session_state["result"] = GeneratedResult(description="Previous video's result")
        with (
            patch("streamlit.file_uploader", return_value=UploadedFile("original.mp4")),
            patch.object(acquire, "acquire_from_upload", side_effect=acquire.AcquisitionError("Unsupported file")),
        ):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertIn("Unsupported file", app.error[0].value)
        self.assertNotIn("result", app.session_state)
        self.assertFalse(app.tabs)

    def test_upload_flows_through_ui_with_seek_buttons(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
        transcript = Transcript(words=[Word(0, 1, "Welcome")], duration=1)
        result = GeneratedResult(description="Description", chapters=[Chapter(0, "Welcome")])
        with tempfile.TemporaryDirectory() as directory, patch.object(acquire, "TMP_DIR", directory):
            with (
                patch("streamlit.file_uploader", return_value=UploadedFile("original.mp4")),
                patch("transcribe.get_transcript", return_value=transcript) as transcribe,
                patch("generate.generate", return_value=result) as generate,
            ):
                app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            transcribe.assert_called_once()
            generate.assert_called_once()
            self.assertIn("0:00", [b.label for b in app.button])
            self.assertEqual(app.session_state["media"].media_kind, "video")


if __name__ == "__main__":
    unittest.main()
