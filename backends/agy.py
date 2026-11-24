import asyncio
import json
import os
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional


class PersistentAgySession:
    """agy --input-format stream-json を常駐させ、起動オーバーヘッドを無くす。"""

    def __init__(
        self,
        workdir: Path,
        default_speaker_id: int,
        build_preamble_fn: Callable[[int], str],
        describe_step_fn: Callable[[dict], str],
        clean_for_speech_fn: Callable[[str], str],
    ) -> None:
        self.workdir = workdir
        self.default_speaker_id = default_speaker_id
        self.build_preamble_fn = build_preamble_fn
        self.describe_step_fn = describe_step_fn
        self.clean_for_speech_fn = clean_for_speech_fn
        self.bin_path = os.environ.get("AGY_BIN", os.path.expanduser("~/.local/bin/agy"))
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.conversation_id: Optional[str] = None
        self.turn_count: int = 0
        self.model: str = os.environ.get("AGY_MODEL", "gemini-3.8-flash-low")
        self.active_speaker_id: int = default_speaker_id
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self.proc and self.proc.returncode is None:
            return
        cmd = [
            self.bin_path,
            "--print=",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--disable-slash-commands",
            "--dangerously-skip-permissions",
            "--effort",
            "low",
        ]
        if self.model:
            cmd.extend(["--model", self.model])

        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.workdir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=10 * 1024 * 1024,
        )
        self.conversation_id = None
        self.turn_count = 0

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.proc = None
        self.conversation_id = None
        self.turn_count = 0

    async def set_model(self, model: str) -> None:
        async with self._lock:
            if model == self.model and self.proc and self.proc.returncode is None:
                return
            self.model = model
            await self.stop()
            asyncio.create_task(self.start())

    async def ask_events(
        self,
        user_text: str,
        speaker_id: Optional[int] = None,
        reset: bool = False,
    ) -> AsyncGenerator[dict, None]:
        sid = self.default_speaker_id if speaker_id is None else speaker_id
        async with self._lock:
            speaker_changed = self.turn_count > 0 and sid != self.active_speaker_id
            if reset or speaker_changed:
                await self.stop()
            self.active_speaker_id = sid
            await self.start()
            assert self.proc and self.proc.stdin and self.proc.stdout

            prompt = (
                self.build_preamble_fn(sid) + user_text
                if self.turn_count == 0
                else user_text
            )
            payload = {
                "event": "user",
                "message": {"content": [{"type": "text", "text": prompt}]},
            }
            self.proc.stdin.write(
                (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            )
            await self.proc.stdin.drain()

            completed = False
            try:
                while True:
                    raw_line = await self.proc.stdout.readline()
                    if not raw_line:
                        err = ""
                        if self.proc.stderr:
                            err = (await self.proc.stderr.read()).decode(
                                "utf-8", errors="replace"
                            )
                        await self.stop()
                        raise RuntimeError(f"agy exited unexpectedly: {err[:300]}")

                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ev = data.get("event")
                    if ev == "init":
                        self.conversation_id = data.get("conversation_id")
                    elif ev == "step_update":
                        su = data.get("step_update", {})
                        st = su.get("step_type")
                        if st == "tool" and su.get("state") == "ACTIVE":
                            yield {"type": "progress", "label": self.describe_step_fn(su)}
                        elif st == "agent_response":
                            delta = su.get("text_delta", "")
                            if delta:
                                yield {"type": "text", "text": delta}
                    elif ev == "result":
                        res = data.get("result", {})
                        if res.get("status") != "SUCCESS":
                            raise RuntimeError(
                                f"agy error: {res.get('error', 'unknown error')}"
                            )
                        self.conversation_id = (
                            res.get("conversation_id") or self.conversation_id
                        )
                        self.turn_count += 1
                        completed = True
                        return
            finally:
                if not completed:
                    await self.stop()
                    asyncio.create_task(self.start())

    async def ask_deltas(
        self,
        user_text: str,
        speaker_id: Optional[int] = None,
        reset: bool = False,
    ) -> AsyncGenerator[str, None]:
        async for ev in self.ask_events(user_text, speaker_id=speaker_id, reset=reset):
            if ev["type"] == "text":
                yield ev["text"]

    async def ask(
        self,
        user_text: str,
        speaker_id: Optional[int] = None,
        reset: bool = False,
    ) -> tuple[str, str]:
        chunks: list[str] = []
        async for d in self.ask_deltas(user_text, speaker_id=speaker_id, reset=reset):
            chunks.append(d)
        reply = self.clean_for_speech_fn("".join(chunks))
        if not reply:
            reply = "うまく聞き取れなかったのだ。もう一回言ってほしいのだ。"
        return reply, self.conversation_id or ""
