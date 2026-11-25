import asyncio
import json
import os
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional

import httpx

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
MAX_HISTORY_MESSAGES = 40


def extract_gemini_text(payload: dict) -> str:
    """Gemini API レスポンス JSON からテキストチャンクを抽出する。"""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "".join(texts)


def parse_gemini_sse_line(line: str) -> Optional[dict]:
    """SSE の 1 行から JSON ペイロードを取り出す（対象外行は None）。"""
    stripped = line.strip()
    if not stripped or not stripped.startswith("data:"):
        return None
    data_str = stripped[5:].strip()
    if not data_str or data_str == "[DONE]":
        return None
    try:
        parsed = json.loads(data_str)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class GeminiApiSession:
    """公式 Gemini Developer API (`streamGenerateContent?alt=sse`) バックエンド。"""

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
        self.api_key: str = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or ""
        ).strip()
        self.model: str = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
        self.active_speaker_id: int = default_speaker_id
        self.history: list[dict] = []
        self.turn_count: int = 0
        self.conversation_id: str = "gemini-api"
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.history.clear()
        self.turn_count = 0

    async def set_model(self, model: str) -> None:
        async with self._lock:
            self.model = model.strip() or DEFAULT_GEMINI_MODEL
            await self.stop()

    def _build_request_body(self, sid: int, user_text: str) -> dict:
        contents = [*self.history, {"role": "user", "parts": [{"text": user_text}]}]
        return {
            "systemInstruction": {
                "parts": [{"text": self.build_preamble_fn(sid)}]
            },
            "contents": contents,
        }

    async def ask_events(
        self,
        user_text: str,
        speaker_id: Optional[int] = None,
        reset: bool = False,
    ) -> AsyncGenerator[dict, None]:
        sid = self.default_speaker_id if speaker_id is None else speaker_id
        async with self._lock:
            if not self.api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY が設定されていません。.env または環境変数に設定してください。"
                )

            speaker_changed = self.turn_count > 0 and sid != self.active_speaker_id
            if reset or speaker_changed:
                await self.stop()
            self.active_speaker_id = sid

            url = f"{GEMINI_API_BASE}/models/{self.model}:streamGenerateContent"
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            }
            body = self._build_request_body(sid, user_text)

            chunks: list[str] = []
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=10.0)
            ) as client:
                async with client.stream(
                    "POST",
                    url,
                    params={"alt": "sse"},
                    headers=headers,
                    json=body,
                ) as resp:
                    if resp.status_code >= 400:
                        err_body = (await resp.aread()).decode("utf-8", errors="replace")
                        raise RuntimeError(
                            f"Gemini API error ({resp.status_code}): {err_body[:300]}"
                        )
                    async for line in resp.aiter_lines():
                        payload = parse_gemini_sse_line(line)
                        if not payload:
                            continue
                        if "error" in payload:
                            err_msg = payload["error"].get("message", "Gemini API error")
                            raise RuntimeError(str(err_msg))
                        delta = extract_gemini_text(payload)
                        if delta:
                            chunks.append(delta)
                            yield {"type": "text", "text": delta}

            full_reply = "".join(chunks)
            if full_reply:
                self.history.append({"role": "user", "parts": [{"text": user_text}]})
                self.history.append({"role": "model", "parts": [{"text": full_reply}]})
                if len(self.history) > MAX_HISTORY_MESSAGES:
                    self.history = self.history[-MAX_HISTORY_MESSAGES:]
                self.turn_count += 1

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
        return reply, self.conversation_id
