import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from fast_path import try_fast_path


class FastPathTests(unittest.TestCase):
    def _run(self, text: str, speaker_id: int = 3, timers: list | None = None):
        added = []
        active = list(timers or [])

        async def add_timer(seconds=None, at=None, label="タイマー", kind="alarm"):
            item = {"seconds": seconds, "at": at, "label": label, "kind": kind}
            added.append(item)
            return item

        def list_timers():
            return active

        def cancel_timers(all_timers=True):
            n = len(active)
            if all_timers:
                active.clear()
            return n

        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            reply = asyncio.run(
                try_fast_path(
                    text,
                    speaker_id,
                    wd,
                    wd,
                    {"add": add_timer, "list": list_timers, "cancel": cancel_timers},
                )
            )
            return reply, added, active

    def test_clock(self):
        reply, _, _ = self._run("今何時？", speaker_id=3)
        self.assertIsNotNone(reply)
        self.assertIn("時", reply)
        self.assertTrue(reply.endswith("のだ！"))

    def test_clock_ignores_calendar_question(self):
        reply, _, _ = self._run("今日の予定は何時から？")
        self.assertIsNone(reply)

    def test_relative_timer_and_reminder(self):
        reply, added, _ = self._run("3分後にカップ麺のタイマーかけて", speaker_id=8)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["seconds"], 180)
        self.assertEqual(added[0]["label"], "カップ麺")
        self.assertEqual(added[0]["kind"], "alarm")
        self.assertTrue(reply.endswith("だよ！"))

        reply2, added2, _ = self._run("19時にゴミ出しリマインドして", speaker_id=2)
        self.assertEqual(len(added2), 1)
        self.assertEqual(added2[0]["at"], "19:00")
        self.assertEqual(added2[0]["kind"], "reminder")
        self.assertTrue(reply2.endswith("ですわ！"))

    def test_timer_cancel(self):
        reply, _, active = self._run(
            "タイマー全部消して",
            timers=[{"id": "1", "label": "テスト", "remaining_sec": 60}],
        )
        self.assertEqual(len(active), 0)
        self.assertIn("1件キャンセル", reply)

    def test_complex_switchbot_falls_back_to_llm(self):
        reply, _, _ = self._run("エアコンを25度で暖房にして")
        self.assertIsNone(reply)


if __name__ == "__main__":
    unittest.main()
