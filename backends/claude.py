import asyncio
import json
import os
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional


class ClaudeCodeSession:
    """Claude Code CLI (`claude -p --output-format stream-json`) バックエンド。"""

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
        self.bin_path = os.environ.get("CLAUDE_BIN", "claude")
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.conversation_id: Optional[str] = None
        self.turn_count: int = 0
        self.model: str = os.environ.get("CLAUDE_MODEL", "")
        self.active_speaker_id: int = default_speaker_id
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        return None

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
            self.model = model
            await self.stop()

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

            prompt = (
                self.build_preamble_fn(sid) + user_text
                if self.turn_count == 0
                else user_text
            )
            cmd = [
                self.bin_path,
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--dangerously-skip-permissions",
            ]
            if self.model:
                cmd.extend(["--model", self.model])
            if self.conversation_id:
                cmd.extend(["--resume", self.conversation_id])

            self.proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.workdir),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,
            )
            assert self.proc.stdout

            emitted_len = 0
            try:
                while True:
                    raw_line = await self.proc.stdout.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("session_id"):
                        self.conversation_id = data["session_id"]

                    msg_type = data.get("type")
                    if msg_type == "assistant":
                        msg = data.get("message", {})
                        for blk in msg.get("content", []):
                            btype = blk.get("type")
                            if btype == "tool_use":
                                yield {"type": "progress", "label": self.describe_step_fn(blk)}
                            elif btype == "text":
                                full_text = blk.get("text", "")
                                if len(full_text) > emitted_len:
                                    delta = full_text[emitted_len:]
                                    emitted_len = len(full_text)
                                    yield {"type": "text", "text": delta}
                    elif msg_type == "result":
                        if data.get("is_error"):
                            raise RuntimeError(str(data.get("result", "claude error")))
                        res_text = data.get("result", "")
                        if isinstance(res_text, str) and len(res_text) > emitted_len:
                            yield {"type": "text", "text": res_text[emitted_len:]}
                        self.turn_count += 1
                rc = await self.proc.wait()
                if rc != 0 and self.proc.stderr:
                    err = (await self.proc.stderr.read()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"claude exited ({rc}): {err[:300]}")
            finally:
                self.proc = None

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
