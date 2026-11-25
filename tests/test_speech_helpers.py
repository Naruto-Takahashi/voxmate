import unittest

from server import _extract_lipsync_timeline, clean_for_speech, extract_expression_tag


class SpeechHelpersTests(unittest.TestCase):
    def test_extract_expression_tag_uses_last_tag(self):
        stripped, expr = extract_expression_tag("[expr:happy] やったね！ [expr:shy] てれるな。")
        self.assertEqual(expr, "shy")
        self.assertEqual(stripped.strip(), "やったね！  てれるな。")

    def test_clean_for_speech_strips_markdown_and_tags(self):
        raw = "[expr:happy] **すごい** [リンク](https://example.com) ```python\nx=1\n``` だよ！"
        cleaned = clean_for_speech(raw)
        self.assertNotIn("[expr:", cleaned)
        self.assertNotIn("x=1", cleaned)
        self.assertIn("すごい リンク だよ！", cleaned)

    def test_extract_lipsync_timeline_generates_vowel_events(self):
        query = {
            "prePhonemeLength": 0.1,
            "accent_phrases": [
                {
                    "moras": [
                        {"consonant_length": 0.05, "vowel": "a", "vowel_length": 0.1},
                        {"consonant_length": 0.01, "vowel": "i", "vowel_length": 0.1},
                    ],
                    "pause_mora": {"consonant_length": 0.0, "vowel_length": 0.2},
                }
            ],
        }
        events = _extract_lipsync_timeline(query, speed_scale=1.0)
        self.assertEqual(events[0], [0, "idle"])
        shapes = [ev[1] for ev in events]
        self.assertIn("a", shapes)
        self.assertIn("i", shapes)
        self.assertEqual(events[-1][1], "idle")


if __name__ == "__main__":
    unittest.main()
