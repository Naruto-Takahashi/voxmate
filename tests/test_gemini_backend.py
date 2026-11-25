import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backends import create_backend_session
from backends.gemini import (
    DEFAULT_GEMINI_MODEL,
    GeminiApiSession,
    extract_gemini_text,
    parse_gemini_sse_line,
)


class GeminiBackendTests(unittest.TestCase):
    def test_parse_gemini_sse_line(self):
        self.assertIsNone(parse_gemini_sse_line(""))
        self.assertIsNone(parse_gemini_sse_line("event: message"))
        self.assertIsNone(parse_gemini_sse_line("data: [DONE]"))
        self.assertIsNone(parse_gemini_sse_line("data: {broken json"))
        parsed = parse_gemini_sse_line('data: {"candidates":[{"content":{"parts":[{"text":"こんにちは"}]}}]}')
        self.assertIsNotNone(parsed)
        self.assertEqual(extract_gemini_text(parsed), "こんにちは")

    def test_extract_gemini_text_multiple_parts(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "やっほー"},
                            {"thought": True},
                            {"text": "なのだ！"},
                        ]
                    }
                }
            ]
        }
        self.assertEqual(extract_gemini_text(payload), "やっほーなのだ！")
        self.assertEqual(extract_gemini_text({}), "")

    def test_factory_creates_gemini_session(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(
                os.environ,
                {
                    "VOXMATE_BACKEND": "gemini",
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_MODEL": "gemini-2.5-flash",
                },
                clear=False,
            ):
                sess = create_backend_session(
                    workdir=Path(td),
                    default_speaker_id=3,
                    build_preamble_fn=lambda sid: f"speaker={sid}\n",
                    describe_step_fn=lambda blk: "",
                    clean_for_speech_fn=lambda s: s.strip(),
                )
        self.assertIsInstance(sess, GeminiApiSession)
        self.assertEqual(sess.model, "gemini-2.5-flash")

    def test_missing_api_key_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
                sess = GeminiApiSession(
                    workdir=Path(td),
                    default_speaker_id=3,
                    build_preamble_fn=lambda sid: "sys",
                    describe_step_fn=lambda blk: "",
                    clean_for_speech_fn=lambda s: s.strip(),
                )
                with self.assertRaises(RuntimeError) as ctx:
                    asyncio.run(sess.ask("おはよう"))
                self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    def test_request_body_includes_history_and_default_model(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"GEMINI_MODEL": ""}, clear=False):
                sess = GeminiApiSession(
                    workdir=Path(td),
                    default_speaker_id=3,
                    build_preamble_fn=lambda sid: f"sys-{sid}",
                    describe_step_fn=lambda blk: "",
                    clean_for_speech_fn=lambda s: s.strip(),
                )
                self.assertEqual(sess.model, DEFAULT_GEMINI_MODEL)
                sess.history.append({"role": "user", "parts": [{"text": "前"}]})
                sess.history.append({"role": "model", "parts": [{"text": "返"}]})
                body = sess._build_request_body(8, "次")
                self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "sys-8")
                self.assertEqual(len(body["contents"]), 3)
                self.assertEqual(body["contents"][-1]["parts"][0]["text"], "次")


if __name__ == "__main__":
    unittest.main()
