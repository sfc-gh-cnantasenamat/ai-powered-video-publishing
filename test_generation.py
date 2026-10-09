import tempfile
import unittest
from unittest.mock import patch

import cache
import enhance
import generate
from acquire import AcquiredMedia
from generate import Chapter, GeneratedResult, GenerationError
from transcribe import Transcript, Word


def _media():
    return AcquiredMedia(source_type="upload", local_media_path="x.mp4", media_kind="video", cache_key="m1")


def _transcript(text="hello world"):
    words = [Word(start=i * 1.0, end=i * 1.0 + 0.5, text=t) for i, t in enumerate(text.split())]
    return Transcript(words=words, duration=float(len(words)))


def _result(title="Intro"):
    return GeneratedResult(description="d", chapters=[Chapter(0.0, title)], keywords=["k"])


class AiCompleteRetryTests(unittest.TestCase):
    def setUp(self):
        sleep = patch("generate.time.sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def test_retries_null_then_succeeds(self):
        with patch("generate.run_query", side_effect=[[(None,)], [('{"quotes": []}',)]]) as rq:
            self.assertEqual(generate._ai_complete_json("p", {}), {"quotes": []})
        self.assertEqual(rq.call_count, 2)

    def test_raises_after_bounded_attempts(self):
        with patch("generate.run_query", return_value=[(None,)]) as rq:
            with self.assertRaises(GenerationError) as ctx:
                generate._ai_complete_json("p", {})
        self.assertEqual(rq.call_count, generate.AI_COMPLETE_ATTEMPTS)
        self.assertIn("try again", str(ctx.exception))

    def test_empty_rows_also_retried(self):
        with patch("generate.run_query", side_effect=[[], [({"items": []},)]]):
            self.assertEqual(generate._ai_complete_json("p", {}), {"items": []})


class ExtrasCacheKeyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch.object(cache, "CACHE_DIR", tmp.name) if hasattr(cache, "CACHE_DIR") else None
        if patcher:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _faq_calls(self, result):
        payload = {"items": [{"question": "Q?", "answer": "A", "chapter_index": 0}]}
        with patch("enhance._ai_complete_json", return_value=payload) as ai:
            enhance.generate_faq(_media(), result)
        return ai.call_count

    def test_faq_cache_invalidates_when_result_changes(self):
        with patch("enhance.cache.get", return_value=None) as get, patch("enhance.cache.set"):
            self._faq_calls(_result("Intro"))
            self._faq_calls(_result("Different"))
        keys = [c.args[1] for c in get.call_args_list]
        self.assertEqual(len(set(keys)), 2)

    def test_quote_cache_key_tracks_transcript(self):
        with patch("enhance.cache.get", return_value=None) as get, patch("enhance.cache.set"), \
                patch("enhance._ai_complete_json", return_value={"quotes": []}):
            enhance.generate_quotes(_media(), _transcript("hello world"))
            enhance.generate_quotes(_media(), _transcript("goodbye world"))
            enhance.generate_quotes(_media(), _transcript("hello world"))
        keys = [c.args[1] for c in get.call_args_list]
        self.assertNotEqual(keys[0], keys[1])
        self.assertEqual(keys[0], keys[2])

    def test_titles_cache_key_tracks_result(self):
        with patch("enhance.cache.get", return_value=None) as get, patch("enhance.cache.set"), \
                patch("enhance._ai_complete_json", side_effect=GenerationError("stop")):
            for title in ("Intro", "Other"):
                with self.assertRaises(GenerationError):
                    enhance.generate_titles_seo(_media(), _result(title), 10.0)
        keys = [c.args[1] for c in get.call_args_list]
        self.assertNotEqual(keys[0], keys[1])


if __name__ == "__main__":
    unittest.main()
