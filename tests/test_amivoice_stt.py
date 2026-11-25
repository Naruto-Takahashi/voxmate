import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stt_amivoice import (
    DEFAULT_AMIVOICE_ENGINE,
    build_amivoice_d_param,
    parse_amivoice_response,
    transcribe_wav_amivoice,
)


class AmiVoiceSttTests(unittest.TestCase):
    def test_build_d_param_with_and_without_profile_words(self):
        self.assertEqual(
            build_amivoice_d_param(),
            f"grammarFileNames={DEFAULT_AMIVOICE_ENGINE}",
        )
        self.assertEqual(
            build_amivoice_d_param("-a-general", "ずんだもん|ズンダモン SwitchBot|スイッチボット"),
            "grammarFileNames=-a-general profileWords=ずんだもん|ズンダモン SwitchBot|スイッチボット",
        )

    def test_parse_amivoice_response_success_and_error(self):
        self.assertEqual(
            parse_amivoice_response({"code": "", "text": " ずんだもんおはよう "}),
            "ずんだもんおはよう",
        )
        with self.assertRaises(RuntimeError) as ctx:
            parse_amivoice_response({"code": "E001", "message": "Invalid appkey"})
        self.assertIn("E001", str(ctx.exception))

    def test_missing_app_key_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "test.wav"
            wav.write_bytes(b"RIFF....WAVE")
            with patch.dict(os.environ, {"AMIVOICE_APP_KEY": ""}, clear=False):
                with self.assertRaises(RuntimeError) as ctx:
                    transcribe_wav_amivoice(wav)
                self.assertIn("AMIVOICE_APP_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
