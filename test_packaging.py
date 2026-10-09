import ast
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import acquire
import generate
import transcribe
from transcribe import Transcript, Word

ROOT = Path(__file__).parent

class PackagingTests(unittest.TestCase):
    def test_manifest_contains_only_required_source(self):
        text = (ROOT / 'snowflake.yml').read_text()
        artifacts = [line.strip()[2:] for line in text.split('    artifacts:\n')[1].splitlines() if line.strip().startswith('- ')]
        self.assertEqual(set(artifacts), {'app.py', 'acquire.py', 'generate.py', 'transcribe.py', 'enhance.py', 'cache.py', 'config.py', 'snowflake_conn.py', 'pyproject.toml'})
        for artifact in artifacts:
            self.assertTrue((ROOT / artifact).is_file())

    def test_no_cookies_by_default(self):
        with patch.object(acquire, 'YOUTUBE_COOKIES_FILE', ''):
            self.assertEqual(acquire._base_ydl_opts(), {})

    def test_stage_identifier_validation(self):
        with patch.dict(os.environ, {'VIDPREP_STAGE_FQN': "db.schema.stage';DROP DATABASE x;--"}):
            spec = importlib.util.spec_from_file_location('config_test', ROOT / 'config.py')
            with self.assertRaises(ValueError):
                spec.loader.exec_module(importlib.util.module_from_spec(spec))

    def test_stage_cleanup_after_transcription_error(self):
        with patch.object(transcribe, 'put_file', return_value='unique.wav'), patch.object(transcribe, 'run_query', side_effect=[RuntimeError('transcription failed'), []]) as query:
            with self.assertRaisesRegex(RuntimeError, 'transcription failed'):
                transcribe._transcribe_chunk_with_ai_transcribe('fixture.wav')
            self.assertTrue(query.call_args_list[-1].args[0].startswith('REMOVE '))

    def test_stage_cleanup_after_invalid_json(self):
        with patch.object(transcribe, 'put_file', return_value='unique.wav'), patch.object(transcribe, 'run_query', side_effect=[[['invalid']], []]) as query:
            with self.assertRaises(ValueError):
                transcribe._transcribe_chunk_with_ai_transcribe('fixture.wav')
            self.assertEqual(query.call_count, 2)

    def test_caption_cache_does_not_override_forced_transcription(self):
        media = acquire.AcquiredMedia('upload', 'fixture.wav', 'audio', 'new')
        transcript = Transcript([Word(0, 1, 'hello')], 1)
        with patch.object(transcribe.cache, 'get', return_value=None) as get, patch.object(transcribe.cache, 'set'), patch.object(transcribe, '_transcribe_via_ai_transcribe', return_value=transcript):
            transcribe.get_transcript(media, False)
            get.assert_called_once_with('transcripts', 'new_ai')

    def test_python_sources_parse(self):
        for path in ROOT.glob('*.py'):
            ast.parse(path.read_text(), filename=path.name)

    def test_generation_cache_tracks_transcript_content(self):
        media = acquire.AcquiredMedia('upload', 'fixture.wav', 'audio', 'new')
        cached = {'description': 'cached', 'chapters': [], 'keywords': []}
        with patch.object(generate.cache, 'get', return_value=cached) as get:
            generate.generate(media, Transcript([Word(0, 1, 'one')], 1))
            generate.generate(media, Transcript([Word(0, 1, 'two')], 1))
            self.assertNotEqual(get.call_args_list[0].args[1], get.call_args_list[1].args[1])

if __name__ == '__main__':
    unittest.main()