import asyncio
import base64
import io
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
import wave
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncGenerator, Optional

import httpx
import numpy as np
import torch

try:
    import mlx_whisper
except ImportError:
    mlx_whisper = None

try:
    from faster_whisper import WhisperModel as FasterWhisperModel
except ImportError:
    FasterWhisperModel = None
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from scipy import signal
from silero_vad import get_speech_timestamps, load_silero_vad

from backends import create_backend_session
from fast_path import try_fast_path

BASE_DIR = Path(__file__).resolve().parent
CHAT_WORKDIR = Path(
    os.environ.get("VOXMATE_WORKDIR", str(BASE_DIR / "chat_workspace"))
).expanduser()
CHAT_WORKDIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
_DEFAULT_WHISPER = (
    "mlx-community/whisper-large-v3-turbo-q4" if mlx_whisper is not None else "large-v3-turbo"
)
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", _DEFAULT_WHISPER)
DEFAULT_SPEAKER_ID = int(os.environ.get("VOICEVOX_SPEAKER", "3"))
AGY_BIN = os.environ.get("AGY_BIN", os.path.expanduser("~/.local/bin/agy"))

CHAR_INFO_DIR = Path(
    os.environ.get(
        "VOICEVOX_CHAR_INFO_DIR",
        str(BASE_DIR / "voicevox" / "macos-arm64" / "resources" / "character_info"),
    )
).expanduser()
CUSTOM_PORTRAIT_DIR = STATIC_DIR / "portraits"

PRESET_SPEAKERS = [
    {"id": 3, "name": "ずんだもん", "style": "ノーマル", "asset": "zundamon", "uuid": "388f246b-8c41-4ac1-8e2d-5d79f3ff56d9", "color": "#74D969", "persona": "ずんだもん（語尾は「〜なのだ」「〜のだ」、一人称は「ボク」）"},
    {"id": 1, "name": "ずんだもん", "style": "あまあま", "asset": "zundamon", "uuid": "388f246b-8c41-4ac1-8e2d-5d79f3ff56d9", "color": "#8EE67E", "persona": "ずんだもん（甘え気味で優しく、語尾は「〜なのだ」「〜のだ」、一人称は「ボク」）"},
    {"id": 7, "name": "ずんだもん", "style": "ツンツン", "asset": "zundamon", "uuid": "388f246b-8c41-4ac1-8e2d-5d79f3ff56d9", "color": "#58C452", "persona": "ずんだもん（少しツンデレ気味に、語尾は「〜なのだ」「〜のだ」、一人称は「ボク」）"},
    {"id": 2, "name": "四国めたん", "style": "ノーマル", "asset": "metan", "uuid": "7ffcb7ce-00ec-4bdc-82cd-45a8889e43ff", "color": "#F472B6", "persona": "四国めたん（上品で少しお嬢様風の丁寧な口調、一人称は「わたくし」または「私」）"},
    {"id": 0, "name": "四国めたん", "style": "あまあま", "asset": "metan", "uuid": "7ffcb7ce-00ec-4bdc-82cd-45a8889e43ff", "color": "#F9A8D4", "persona": "四国めたん（甘え気味で優しいお嬢様風の口調、一人称は「わたくし」または「私」）"},
    {"id": 6, "name": "四国めたん", "style": "ツンツン", "asset": "metan", "uuid": "7ffcb7ce-00ec-4bdc-82cd-45a8889e43ff", "color": "#EC4899", "persona": "四国めたん（少しツンとしたお嬢様風の口調、一人称は「わたくし」）"},
    {"id": 8, "name": "春日部つむぎ", "style": "ノーマル", "asset": "tsumugi", "uuid": "35b2c544-660e-401e-b503-0e14c635303a", "color": "#FBBF24", "persona": "春日部つむぎ（明るくフレンドリーなギャル寄りの親しみやすい口調、一人称は「あーし」または「私」）"},
    {"id": 10, "name": "雨晴はう", "style": "ノーマル", "asset": "hau", "uuid": "3474ee95-c274-47f9-aa1a-8322163d96f1", "color": "#60A5FA", "persona": "雨晴はう（優しく穏やかな看護師風の丁寧語）"},
    {"id": 16, "name": "九州そら", "style": "ノーマル", "asset": "sora", "uuid": "481fb609-6446-4870-9f46-90c4dd623403", "color": "#818CF8", "persona": "九州そら（上品で知的、丁寧で優しい女性の口調）"},
    {"id": 15, "name": "九州そら", "style": "あまあま", "asset": "sora", "uuid": "481fb609-6446-4870-9f46-90c4dd623403", "color": "#A5B4FC", "persona": "九州そら（柔らかく甘え気味で優しい女性の口調）"},
    {"id": 18, "name": "九州そら", "style": "ツンツン", "asset": "sora", "uuid": "481fb609-6446-4870-9f46-90c4dd623403", "color": "#6366F1", "persona": "九州そら（クールで少しツンとした知的な女性の口調）"},
    {"id": 23, "name": "WhiteCUL", "style": "ノーマル", "asset": "whitecul", "uuid": "67d5d8da-acd7-4207-bb10-b5542d3a663b", "color": "#93C5FD", "persona": "WhiteCUL（クールで落ち着いた少しミステリアスな女性の口調、一人称は「私」）"},
    {"id": 24, "name": "WhiteCUL", "style": "たのしい", "asset": "whitecul", "uuid": "67d5d8da-acd7-4207-bb10-b5542d3a663b", "color": "#BAE6FD", "persona": "WhiteCUL（明るく楽しげで親しみやすい女性の口調、一人称は「私」）"},
    {"id": 27, "name": "後鬼", "style": "人間ver.", "asset": "goki", "uuid": "0f56c2f2-644c-49c9-8989-94e11f7129d0", "color": "#F87171", "persona": "後鬼（落ち着いて頼もしく、丁寧で落ち着いたお姉さんの口調）"},
    {"id": 28, "name": "後鬼", "style": "ぬいぐるみver.", "asset": "goki", "uuid": "0f56c2f2-644c-49c9-8989-94e11f7129d0", "color": "#FCA5A5", "persona": "後鬼（少し可愛らしく柔らかいぬいぐるみ風の口調）"},
    {"id": 61, "name": "中国うさぎ", "style": "ノーマル", "asset": "usagi", "uuid": "1f18ffc3-47ea-4ce0-9829-0576d03a7ec8", "color": "#FCA5A5", "persona": "中国うさぎ（少し控えめで素朴、可愛らしい口調）"},
    {"id": 62, "name": "中国うさぎ", "style": "おどろき", "asset": "usagi", "uuid": "1f18ffc3-47ea-4ce0-9829-0576d03a7ec8", "color": "#FDBA74", "persona": "中国うさぎ（元気で少しびっくりしやすい素朴で可愛らしい口調）"},
    {"id": 107, "name": "東北ずん子", "style": "ノーマル", "asset": "zunko", "uuid": "80802b2d-8c75-4429-978b-515105017010", "color": "#86EFAC", "persona": "東北ずん子（明るく元気でずんだ餅が大好きな優しいお姉さんの口調）"},
    {"id": 109, "name": "東北イタコ", "style": "ノーマル", "asset": "itako", "uuid": "ab4c31a3-8769-422a-b412-708f5ae637e8", "color": "#C4B5FD", "persona": "東北イタコ（落ち着いて少しお茶目な丁寧なお姉さんの口調、語尾に「〜ですわ」「〜ですよ」）"},
    {"id": 113, "name": "あんこもん", "style": "ノーマル", "asset": "ankomon", "uuid": "3be49e15-34bb-48a0-9e2f-9b80c96e9905", "color": "#C084FC", "persona": "あんこもん（少し気だるげでマイペース、語尾に「〜なのだ」等を混ぜるあんこの妖精の口調）"},
    {"id": 114, "name": "あんこもん", "style": "つよつよ", "asset": "ankomon", "uuid": "3be49e15-34bb-48a0-9e2f-9b80c96e9905", "color": "#A855F7", "persona": "あんこもん（自信たっぷりで元気なあんこの妖精の口調）"},
    {"id": 116, "name": "あんこもん", "style": "けだるげ", "asset": "ankomon", "uuid": "3be49e15-34bb-48a0-9e2f-9b80c96e9905", "color": "#D8B4FE", "persona": "あんこもん（眠そうでゆるく気だるげなあんこの妖精の口調）"},
    {"id": 127, "name": "ブイブイ・コバコ", "style": "ノーマル", "asset": "kobako", "uuid": "0d1745d9-ba28-4bf1-b792-3e670ee980ee", "color": "#34D399", "persona": "ブイブイ・コバコ（元気で可愛らしくフレンドリーな口調）"},
]

ALLOWED_MODELS = {
    "gemini-3.8-flash-low": "高速 (Flash)",
    "gemini-4-hydrogen-low": "標準 (Hydrogen)",
    "gemini-4-neon-low": "高精度 (Neon)",
}


def build_preamble(speaker_id: int) -> str:
    persona = "ずんだもん（語尾は「〜なのだ」「〜のだ」、一人称は「ボク」）"
    for sp in PRESET_SPEAKERS:
        if sp["id"] == speaker_id:
            persona = sp["persona"]
            break

    workspace_hint = ""
    voxmate_prompt_path = CHAT_WORKDIR / "VOXMATE.md"
    if voxmate_prompt_path.exists():
        try:
            workspace_hint = "\n" + voxmate_prompt_path.read_text(encoding="utf-8")[:2500].strip()
        except Exception:
            pass

    memory_path = CHAT_WORKDIR / "MEMORY.md"
    if memory_path.exists():
        try:
            memory_text = memory_path.read_text(encoding="utf-8")[:1500].strip()
            if memory_text:
                workspace_hint += f"\n\n[記憶メモ (MEMORY.md)]\n{memory_text}"
        except Exception:
            pass

    return (
        f"【音声会話モード】あなたは「{persona}」として振る舞ってください。"
        "ユーザーをシステム上のユーザーIDやアカウント名で呼ばず、キャラクターの性格に合わせて「マスター」や「ご主人様」などと呼んでください。"
        "音声で読み上げるため、キャラクターの口調を保ったまま1〜3文程度の簡潔で自然な日本語で答えてください。"
        "Markdown記号（*や#や`）や箇条書き記号、URLは使わないでください。"
        f"{workspace_hint}\n\nユーザーの発言: "
    )


def _describe_tool_step(su: dict) -> str:
    raw = json.dumps(su, ensure_ascii=False).lower()
    if "calendar" in raw:
        return "予定を登録中..." if ("add" in raw or "create" in raw) else "予定を確認中..."
    if "gmail" in raw or "mail" in raw or "triage" in raw:
        return "メールを確認中..."
    if "memo" in raw or "note" in raw:
        return "メモを確認中..."
    if "notify" in raw or "discord" in raw:
        return "通知を送信中..."
    return "情報を確認中..."


agy_session = create_backend_session(
    workdir=CHAT_WORKDIR,
    default_speaker_id=DEFAULT_SPEAKER_ID,
    build_preamble_fn=build_preamble,
    describe_step_fn=_describe_tool_step,
    clean_for_speech_fn=lambda s: clean_for_speech(s),
)
_vv_client: Optional[httpx.AsyncClient] = None
_vad_model = None

STATE_FILE = Path(
    os.environ.get("VOXMATE_STATE_FILE", os.path.expanduser("~/.config/voxmate/state.json"))
).expanduser()
TIMERS_FILE = STATE_FILE.parent / "timers.json"


def _load_shared_state() -> dict:
    default = {
        "speaker_id": DEFAULT_SPEAKER_ID,
        "speed_scale": 1.12,
        "history": [],
        "alerts": [],
        "alarm_dismissed_at": 0.0,
        "state_version": 1,
    }
    if STATE_FILE.exists():
        try:
            loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            default["speaker_id"] = int(loaded.get("speaker_id", DEFAULT_SPEAKER_ID))
            default["speed_scale"] = float(loaded.get("speed_scale", 1.12))
            default["history"] = list(loaded.get("history", []))[-30:]
            default["alerts"] = list(loaded.get("alerts", []))[-10:]
            default["alarm_dismissed_at"] = float(loaded.get("alarm_dismissed_at", 0.0))
        except Exception:
            pass
    return default


shared_state = _load_shared_state()


def _save_shared_state() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(shared_state, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def _load_timers() -> list[dict]:
    if TIMERS_FILE.exists():
        try:
            data = json.loads(TIMERS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save_timers() -> None:
    try:
        TIMERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TIMERS_FILE.write_text(
            json.dumps(active_timers, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


active_timers: list[dict] = _load_timers()


def _parse_fire_at(seconds: Optional[int], at: Optional[str]) -> float:
    now = time.time()
    if seconds is not None:
        if seconds <= 0:
            raise HTTPException(status_code=400, detail="seconds must be > 0")
        return now + int(seconds)
    if at:
        raw = at.strip()
        local_tz = datetime.now().astimezone().tzinfo
        m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", raw)
        if m:
            h, mn, sec = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
            now_dt = datetime.now(local_tz)
            target = now_dt.replace(hour=h, minute=mn, second=sec, microsecond=0)
            if target <= now_dt:
                target += timedelta(days=1)
            return target.timestamp()
        try:
            dt = datetime.fromisoformat(raw.replace(" ", "T"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=local_tz)
            ts = dt.timestamp()
            if ts <= now:
                raise HTTPException(status_code=400, detail="Target time must be in the future")
            return ts
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid time format: {at}")
    raise HTTPException(status_code=400, detail="Either seconds or at is required")


def _timer_public_view(item: dict, now: Optional[float] = None) -> dict:
    now = now or time.time()
    return {
        "id": item["id"],
        "label": item["label"],
        "kind": item.get("kind", "alarm"),
        "fire_at": item["fire_at"],
        "fire_at_iso": item["fire_at_iso"],
        "remaining_sec": max(0, int(round(item["fire_at"] - now))),
        "notify_discord": bool(item.get("notify_discord", False)),
    }


async def _fire_timer_item(item: dict) -> None:
    label = (item.get("label") or "タイマー").strip()
    kind = item.get("kind", "alarm")
    if label in ("タイマー", ""):
        alert_text = "タイマーの時間です、マスター！"
    else:
        alert_text = f"{label}の時間です、マスター！"

    shared_state["history"].append({"role": "ai", "text": alert_text})
    shared_state["history"] = shared_state["history"][-30:]
    shared_state.setdefault("alerts", []).append({
        "id": item["id"],
        "label": label,
        "kind": kind,
        "text": alert_text,
        "fired_at": time.time(),
    })
    shared_state["alerts"] = shared_state["alerts"][-10:]
    shared_state["state_version"] += 1
    _save_shared_state()

    if item.get("notify_discord"):
        sec_bin = CHAT_WORKDIR / "scripts" / "sec"
        if sec_bin.exists():
            try:
                proc = await asyncio.create_subprocess_exec(
                    str(sec_bin),
                    "notify-discord",
                    "--message",
                    f"⏰ {alert_text}",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                asyncio.create_task(proc.wait())
            except Exception:
                pass


async def _timer_watcher_loop() -> None:
    while True:
        try:
            now = time.time()
            due = [t for t in active_timers if float(t.get("fire_at", 0)) <= now]
            if due:
                due_ids = {t["id"] for t in due}
                active_timers[:] = [t for t in active_timers if t["id"] not in due_ids]
                _save_timers()
                for item in due:
                    await _fire_timer_item(item)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(1.0)


def _append_shared_history(user_text: str, ai_text: str) -> None:
    if user_text:
        shared_state["history"].append({"role": "user", "text": user_text})
    if ai_text:
        shared_state["history"].append({"role": "ai", "text": ai_text})
    shared_state["history"] = shared_state["history"][-30:]
    shared_state["state_version"] += 1
    _save_shared_state()


def get_vad_model():
    global _vad_model
    if _vad_model is None:
        _vad_model = load_silero_vad()
    return _vad_model


async def _warmup_stt() -> None:
    try:
        with tempfile.TemporaryDirectory() as td:
            wav_path = Path(td) / "warmup.wav"
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00\x00" * 4800)
            await asyncio.to_thread(_transcribe_wav_file, wav_path)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _vv_client
    _vv_client = httpx.AsyncClient(timeout=30.0)
    get_vad_model()
    asyncio.create_task(agy_session.start())
    asyncio.create_task(_warmup_stt())
    watcher_task = asyncio.create_task(_timer_watcher_loop())
    yield
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass
    await agy_session.stop()
    if _vv_client:
        await _vv_client.aclose()


app = FastAPI(title="VoxMate", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class TextChatRequest(BaseModel):
    text: str
    speaker_id: int = DEFAULT_SPEAKER_ID
    speed_scale: float = 1.12
    reset: bool = False
    silent: bool = False


class SettingsRequest(BaseModel):
    agy_model: Optional[str] = None
    speaker_id: Optional[int] = None
    speed_scale: Optional[float] = None


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"[`*_#>]+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


_tts_cache: dict[tuple[str, int, float], bytes] = {}
_TTS_CACHE_MAX = 64


async def synthesize_voicevox(
    text: str,
    speaker_id: int = DEFAULT_SPEAKER_ID,
    speed_scale: float = 1.12,
) -> bytes:
    sp_rounded = round(max(0.7, min(1.6, float(speed_scale))), 2)
    cache_key = (text, int(speaker_id), sp_rounded)
    if len(text) <= 60 and cache_key in _tts_cache:
        return _tts_cache[cache_key]

    client = _vv_client or httpx.AsyncClient(timeout=30.0)
    q_resp = await client.post(
        f"{VOICEVOX_URL}/audio_query",
        params={"text": text, "speaker": speaker_id},
    )
    q_resp.raise_for_status()
    query = q_resp.json()
    query["speedScale"] = sp_rounded

    s_resp = await client.post(
        f"{VOICEVOX_URL}/synthesis",
        params={"speaker": speaker_id},
        json=query,
    )
    s_resp.raise_for_status()
    audio = s_resp.content
    if len(text) <= 60:
        if len(_tts_cache) >= _TTS_CACHE_MAX:
            _tts_cache.pop(next(iter(_tts_cache)))
        _tts_cache[cache_key] = audio
    return audio


_faster_whisper_model = None


def _get_faster_whisper_model():
    global _faster_whisper_model
    if _faster_whisper_model is None:
        if FasterWhisperModel is None:
            raise RuntimeError("Neither mlx-whisper nor faster-whisper is installed")
        device = os.environ.get("FASTER_WHISPER_DEVICE", "auto")
        compute_type = os.environ.get("FASTER_WHISPER_COMPUTE_TYPE", "auto")
        _faster_whisper_model = FasterWhisperModel(
            WHISPER_MODEL, device=device, compute_type=compute_type
        )
    return _faster_whisper_model


def _transcribe_wav_file(wav_path: Path) -> str:
    prefer = os.environ.get("VOXMATE_STT", "").strip().lower()
    use_mlx = (mlx_whisper is not None) and (prefer != "faster-whisper")
    if use_mlx:
        result = mlx_whisper.transcribe(
            str(wav_path),
            path_or_hf_repo=WHISPER_MODEL,
            language="ja",
            initial_prompt="自然な日本語の会話です。",
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.2,
        )
        return (result.get("text") or "").strip()

    model = _get_faster_whisper_model()
    segments, _ = model.transcribe(
        str(wav_path),
        language="ja",
        initial_prompt="自然な日本語の会話です。",
        condition_on_previous_text=False,
        vad_filter=True,
    )
    return "".join(seg.text for seg in segments).strip()


def transcribe_audio_bytes(audio_bytes: bytes, suffix: str = ".webm") -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = Path(tmpdir) / f"input{suffix}"
        wav_path = Path(tmpdir) / "audio.wav"
        in_path.write_bytes(audio_bytes)

        res = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(in_path),
                "-af",
                "highpass=f=80",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(wav_path),
            ],
            capture_output=True,
        )
        if res.returncode != 0:
            raise RuntimeError(
                f"ffmpeg error ({suffix}, {len(audio_bytes)}B): {res.stderr.decode('utf-8', errors='replace')[-400:]}"
            )

        text = _transcribe_wav_file(wav_path)
        hallucinations = {
            "ご視聴ありがとうございました",
            "ご視聴ありがとうございました。",
            "ありがとうございました",
            "ありがとうございました。",
            "ん",
        }
        if text in hallucinations:
            return ""
        return text


@app.get("/")
async def index():
    return FileResponse(
        str(STATIC_DIR / "index.html"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/sw.js")
async def service_worker():
    return FileResponse(
        str(STATIC_DIR / "sw.js"),
        media_type="application/javascript",
    )


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(
        str(STATIC_DIR / "manifest.webmanifest"),
        media_type="application/manifest+json",
    )


def _find_speaker(speaker_id: int) -> Optional[dict]:
    for sp in PRESET_SPEAKERS:
        if sp["id"] == speaker_id:
            return sp
    return None


@app.get("/api/character/{speaker_id}/portrait")
async def character_portrait(speaker_id: int, expr: str = "idle"):
    sp = _find_speaker(speaker_id)
    if not sp:
        raise HTTPException(status_code=404, detail="Speaker not found")
    asset = sp.get("asset")
    if asset:
        if expr in ("idle", "blink", "speak", "think", "happy"):
            expr_file = CUSTOM_PORTRAIT_DIR / f"{asset}_{expr}.png"
            if expr_file.exists():
                return FileResponse(
                    str(expr_file),
                    media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"},
                )
        custom = CUSTOM_PORTRAIT_DIR / f"{asset}_portrait.png"
        if custom.exists():
            return FileResponse(
                str(custom),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=3600"},
            )
    uuid = sp["uuid"]
    p_style = CHAR_INFO_DIR / uuid / "portraits" / f"{speaker_id}.png"
    p_main = CHAR_INFO_DIR / uuid / "portrait.png"
    target = p_style if p_style.exists() else p_main
    if not target.exists():
        raise HTTPException(status_code=404, detail="Portrait not found")
    return FileResponse(
        str(target),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/character/{speaker_id}/icon")
async def character_icon(speaker_id: int):
    sp = _find_speaker(speaker_id)
    if not sp:
        raise HTTPException(status_code=404, detail="Speaker not found")
    asset = sp.get("asset")
    if asset:
        custom = CUSTOM_PORTRAIT_DIR / f"{asset}_icon.png"
        if custom.exists():
            return FileResponse(
                str(custom),
                media_type="image/png",
                headers={"Cache-Control": "no-cache"},
            )
    uuid = sp["uuid"]
    target = CHAR_INFO_DIR / uuid / "icons" / f"{speaker_id}.png"
    if not target.exists():
        raise HTTPException(status_code=404, detail="Icon not found")
    return FileResponse(
        str(target),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/state")
async def get_state():
    now = time.time()
    return {
        "agy_model": agy_session.model,
        "speaker_id": shared_state["speaker_id"],
        "speed_scale": shared_state["speed_scale"],
        "history": shared_state["history"],
        "alerts": shared_state.get("alerts", []),
        "alarm_dismissed_at": float(shared_state.get("alarm_dismissed_at", 0.0)),
        "timers": [_timer_public_view(t, now) for t in sorted(active_timers, key=lambda x: x["fire_at"])],
        "state_version": shared_state["state_version"],
    }


@app.get("/api/health")
async def health():
    vv_ok = False
    try:
        client = _vv_client or httpx.AsyncClient(timeout=2.0)
        r = await client.get(f"{VOICEVOX_URL}/version")
        vv_ok = r.status_code == 200
    except Exception:
        vv_ok = False
    now = time.time()
    return {
        "ok": True,
        "voicevox": vv_ok,
        "conversation_id": agy_session.conversation_id,
        "agy_running": bool(agy_session.proc and agy_session.proc.returncode is None),
        "agy_model": agy_session.model,
        "whisper_model": WHISPER_MODEL,
        "speaker_id": shared_state["speaker_id"],
        "speed_scale": shared_state["speed_scale"],
        "history": shared_state["history"],
        "alerts": shared_state.get("alerts", []),
        "alarm_dismissed_at": float(shared_state.get("alarm_dismissed_at", 0.0)),
        "timers": [_timer_public_view(t, now) for t in sorted(active_timers, key=lambda x: x["fire_at"])],
        "state_version": shared_state["state_version"],
        "speakers": PRESET_SPEAKERS,
        "models": [{"id": k, "label": v} for k, v in ALLOWED_MODELS.items()],
    }


@app.post("/api/alerts/dismiss")
async def dismiss_alerts():
    shared_state["alarm_dismissed_at"] = time.time()
    shared_state["state_version"] += 1
    _save_shared_state()
    return {"ok": True, "alarm_dismissed_at": shared_state["alarm_dismissed_at"]}


class TimerCreateRequest(BaseModel):
    seconds: Optional[int] = None
    at: Optional[str] = None
    label: str = "タイマー"
    kind: str = "alarm"
    notify_discord: bool = False


class TimerCancelRequest(BaseModel):
    id: Optional[str] = None
    label: Optional[str] = None
    all: bool = False


@app.get("/api/timers")
async def list_timers():
    now = time.time()
    return {
        "timers": [_timer_public_view(t, now) for t in sorted(active_timers, key=lambda x: x["fire_at"])]
    }


@app.post("/api/timers")
async def create_timer(req: TimerCreateRequest):
    fire_at = _parse_fire_at(req.seconds, req.at)
    local_tz = datetime.now().astimezone().tzinfo
    fire_dt = datetime.fromtimestamp(fire_at, tz=local_tz)
    kind = "reminder" if str(req.kind).strip().lower() == "reminder" else "alarm"
    item = {
        "id": str(uuid.uuid4())[:8],
        "label": (req.label or "タイマー").strip() or "タイマー",
        "kind": kind,
        "fire_at": fire_at,
        "fire_at_iso": fire_dt.isoformat(timespec="seconds"),
        "created_at": time.time(),
        "notify_discord": bool(req.notify_discord),
    }
    active_timers.append(item)
    _save_timers()
    shared_state["state_version"] += 1
    _save_shared_state()
    return {"ok": True, "timer": _timer_public_view(item)}


@app.delete("/api/timers/{timer_id}")
async def delete_timer(timer_id: str):
    before = len(active_timers)
    active_timers[:] = [t for t in active_timers if t["id"] != timer_id]
    if len(active_timers) == before:
        raise HTTPException(status_code=404, detail="Timer not found")
    _save_timers()
    shared_state["state_version"] += 1
    _save_shared_state()
    return {"ok": True, "removed": before - len(active_timers)}


@app.post("/api/timers/cancel")
async def cancel_timers(req: TimerCancelRequest):
    before = len(active_timers)
    if req.all:
        active_timers.clear()
    elif req.id:
        active_timers[:] = [t for t in active_timers if t["id"] != req.id]
    elif req.label:
        q = req.label.strip().lower()
        active_timers[:] = [t for t in active_timers if q not in t["label"].lower()]
    else:
        raise HTTPException(status_code=400, detail="Specify id, label, or all=true")
    removed = before - len(active_timers)
    if removed > 0:
        _save_timers()
        shared_state["state_version"] += 1
        _save_shared_state()
    return {"ok": True, "removed": removed}


@app.post("/api/settings")
async def update_settings(req: SettingsRequest):
    changed = False
    if req.agy_model is not None:
        if req.agy_model not in ALLOWED_MODELS:
            raise HTTPException(status_code=400, detail="Unsupported model")
        await agy_session.set_model(req.agy_model)
        changed = True
    if req.speaker_id is not None:
        if not _find_speaker(req.speaker_id):
            raise HTTPException(status_code=400, detail="Unsupported speaker_id")
        if shared_state["speaker_id"] != req.speaker_id:
            shared_state["speaker_id"] = req.speaker_id
            changed = True
    if req.speed_scale is not None:
        val = max(0.7, min(1.5, float(req.speed_scale)))
        if abs(shared_state["speed_scale"] - val) > 1e-4:
            shared_state["speed_scale"] = val
            changed = True
    if changed:
        shared_state["state_version"] += 1
        _save_shared_state()
    return {
        "ok": True,
        "agy_model": agy_session.model,
        "speaker_id": shared_state["speaker_id"],
        "speed_scale": shared_state["speed_scale"],
        "state_version": shared_state["state_version"],
    }


@app.post("/api/reset")
async def reset_conversation():
    await agy_session.stop()
    asyncio.create_task(agy_session.start())
    shared_state["history"] = []
    shared_state["state_version"] += 1
    _save_shared_state()
    return {"ok": True}


@app.post("/api/tts")
async def synthesize_tts(req: TextChatRequest):
    cleaned = clean_for_speech(req.text.strip())
    if not cleaned:
        raise HTTPException(status_code=400, detail="Empty text")
    wav_bytes = await synthesize_voicevox(
        cleaned, speaker_id=req.speaker_id, speed_scale=req.speed_scale
    )
    return JSONResponse({"audio_base64": base64.b64encode(wav_bytes).decode("ascii")})


@app.post("/api/chat/text")
async def chat_text(req: TextChatRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    t0 = time.perf_counter()
    reply, conv_id = await agy_session.ask(
        req.text.strip(), speaker_id=req.speaker_id, reset=req.reset
    )
    t1 = time.perf_counter()
    wav_bytes = await synthesize_voicevox(
        reply, speaker_id=req.speaker_id, speed_scale=req.speed_scale
    )
    t2 = time.perf_counter()
    return JSONResponse(
        {
            "user_text": req.text.strip(),
            "reply_text": reply,
            "conversation_id": conv_id,
            "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
            "timings": {"stt": 0.0, "agy": round(t1 - t0, 2), "tts": round(t2 - t1, 2)},
        }
    )


COMMON_WAKE_WORDS = [
    "ねえ", "ねぇ", "ねー", "ね〜", "ね、", "ね。", "ねえ、",
    "もしもし", "ヘイ", "へい", "ちょっと", "おい", "おーい", "あの",
]
SPEAKER_WAKE_WORDS = {
    "ずんだもん": ["ずんだ", "すんだ", "すんな", "づんだ"],
    "四国めたん": ["めたん", "四国"],
    "春日部つむぎ": ["つむぎ", "春日部"],
    "雨晴はう": ["はう", "雨晴"],
    "九州そら": ["そら", "九州"],
    "WhiteCUL": ["ホワイト", "雪", "カル", "white"],
    "後鬼": ["ごき", "後鬼"],
    "中国うさぎ": ["うさぎ", "中国"],
    "東北ずん子": ["ずん子", "ずんこ", "ずん"],
    "東北イタコ": ["イタコ", "いたこ"],
    "あんこもん": ["あんこ", "アンコ"],
    "ブイブイ・コバコ": ["コバコ", "こばこ", "ブイブイ"],
}


def matches_wake_word(text: str, speaker_id: int) -> bool:
    norm = text.lower().replace(" ", "").replace("　", "")
    sp = _find_speaker(speaker_id)
    words = list(COMMON_WAKE_WORDS)
    if sp:
        words.extend(SPEAKER_WAKE_WORDS.get(sp["name"], []))
    return any(w.lower() in norm for w in words)


async def _stream_reply_events(
    user_text: str,
    speaker_id: int,
    speed_scale: float,
    t0: float,
    t_stt: float,
    reset: bool = False,
    silent: bool = False,
) -> AsyncGenerator[bytes, None]:
    tts_tasks: list[tuple[str, asyncio.Task[bytes]]] = []
    buf = ""
    split_re = re.compile(r"([。！？\n])")
    t_ai_start = time.perf_counter()
    first_audio_sent = False
    first_audio_sec = 0.0
    full_reply_parts: list[str] = []

    async def flush_sentence(s: str) -> None:
        cleaned = clean_for_speech(s)
        if not cleaned:
            return
        if silent:
            full_reply_parts.append(cleaned)
            return
        task = asyncio.create_task(
            synthesize_voicevox(cleaned, speaker_id, speed_scale)
        )
        tts_tasks.append((cleaned, task))

    async def _fast_add_timer(
        seconds: Optional[int] = None,
        at: Optional[str] = None,
        label: str = "タイマー",
        kind: str = "alarm",
    ) -> dict:
        res = await create_timer(
            TimerCreateRequest(seconds=seconds, at=at, label=label, kind=kind)
        )
        return res["timer"]

    def _fast_list_timers() -> list[dict]:
        now = time.time()
        return [_timer_public_view(t, now) for t in sorted(active_timers, key=lambda x: x["fire_at"])]

    def _fast_cancel_timers(all_timers: bool = True) -> int:
        before = len(active_timers)
        if all_timers:
            active_timers.clear()
        removed = before - len(active_timers)
        if removed > 0:
            _save_timers()
            shared_state["state_version"] += 1
            _save_shared_state()
        return removed

    fast_reply = await try_fast_path(
        user_text=user_text,
        speaker_id=speaker_id,
        workdir=CHAT_WORKDIR,
        base_dir=BASE_DIR,
        timer_ops={
            "add": _fast_add_timer,
            "list": _fast_list_timers,
            "cancel": _fast_cancel_timers,
        },
    )

    if fast_reply:
        prev_len = len(full_reply_parts)
        await flush_sentence(fast_reply)
        if silent and len(full_reply_parts) > prev_len:
            first_audio_sent = True
            first_audio_sec = time.perf_counter() - t0
            yield (
                json.dumps(
                    {"type": "text", "text": full_reply_parts[-1]},
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8")
    else:
        async for ev in agy_session.ask_events(
            user_text, speaker_id=speaker_id, reset=reset
        ):
            if ev["type"] == "progress":
                yield (
                    json.dumps(
                        {"type": "progress", "label": ev["label"]}, ensure_ascii=False
                    )
                    + "\n"
                ).encode("utf-8")
                continue

            buf += ev["text"]
            while True:
                m = split_re.search(buf)
                if not m:
                    break
                end_idx = m.end()
                sentence = buf[:end_idx]
                buf = buf[end_idx:]
                prev_len = len(full_reply_parts)
                await flush_sentence(sentence)
                if silent and len(full_reply_parts) > prev_len:
                    if not first_audio_sent:
                        first_audio_sent = True
                        first_audio_sec = time.perf_counter() - t0
                    yield (
                        json.dumps(
                            {"type": "text", "text": full_reply_parts[-1]},
                            ensure_ascii=False,
                        )
                        + "\n"
                    ).encode("utf-8")

                while tts_tasks and tts_tasks[0][1].done():
                    s_txt, task = tts_tasks.pop(0)
                    wav = await task
                    full_reply_parts.append(s_txt)
                    if not first_audio_sent:
                        first_audio_sent = True
                        first_audio_sec = time.perf_counter() - t0
                    yield (
                        json.dumps(
                            {
                                "type": "audio",
                                "text": s_txt,
                                "audio_base64": base64.b64encode(wav).decode("ascii"),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    ).encode("utf-8")

        if buf.strip():
            prev_len = len(full_reply_parts)
            await flush_sentence(buf)
            if silent and len(full_reply_parts) > prev_len:
                if not first_audio_sent:
                    first_audio_sent = True
                    first_audio_sec = time.perf_counter() - t0
                yield (
                    json.dumps(
                        {"type": "text", "text": full_reply_parts[-1]},
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8")

    t_ai = time.perf_counter() - t_ai_start

    for s_txt, task in tts_tasks:
        wav = await task
        full_reply_parts.append(s_txt)
        if not first_audio_sent:
            first_audio_sent = True
            first_audio_sec = time.perf_counter() - t0
        yield (
            json.dumps(
                {
                    "type": "audio",
                    "text": s_txt,
                    "audio_base64": base64.b64encode(wav).decode("ascii"),
                },
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")

    _append_shared_history(user_text, " ".join(full_reply_parts))

    yield (
        json.dumps(
            {
                "type": "done",
                "timings": {
                    "stt": round(t_stt, 2),
                    "agy": round(t_ai, 2),
                    "first_audio": round(first_audio_sec, 2),
                },
            }
        )
        + "\n"
    ).encode("utf-8")


@app.post("/api/chat/text/stream")
async def chat_text_stream(req: TextChatRequest):
    user_text = req.text.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Empty text")

    async def event_stream() -> AsyncGenerator[bytes, None]:
        t0 = time.perf_counter()
        yield (
            json.dumps(
                {"type": "stt", "user_text": user_text, "stt_sec": 0.0},
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        try:
            async for chunk in _stream_reply_events(
                user_text,
                req.speaker_id,
                req.speed_scale,
                t0,
                0.0,
                reset=req.reset,
                silent=req.silent,
            ):
                yield chunk
        except Exception as exc:
            yield (
                json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
                + "\n"
            ).encode("utf-8")

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/chat/audio/stream")
async def chat_audio_stream(
    file: UploadFile = File(...),
    speaker_id: int = Form(DEFAULT_SPEAKER_ID),
    speed_scale: float = Form(1.12),
    require_wake: bool = Form(False),
    silent: bool = Form(False),
):
    audio_bytes = await file.read()
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"

    async def event_stream() -> AsyncGenerator[bytes, None]:
        if len(audio_bytes) < 500:
            yield (json.dumps({"type": "empty"}) + "\n").encode("utf-8")
            return

        t0 = time.perf_counter()
        try:
            user_text = await asyncio.to_thread(transcribe_audio_bytes, audio_bytes, suffix)
        except Exception as exc:
            print(f"[STT ERROR] {exc}", flush=True)
            yield (json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n").encode("utf-8")
            return
        t_stt = time.perf_counter() - t0
        if not user_text:
            yield (json.dumps({"type": "empty"}) + "\n").encode("utf-8")
            return

        print(f"[STT] ({t_stt:.2f}s) require_wake={require_wake} text={user_text!r}", flush=True)
        if require_wake and not matches_wake_word(user_text, speaker_id):
            yield (
                json.dumps(
                    {"type": "ignored", "heard": user_text, "stt_sec": round(t_stt, 2)},
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8")
            return

        yield (
            json.dumps(
                {
                    "type": "stt",
                    "user_text": user_text,
                    "stt_sec": round(t_stt, 2),
                },
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")

        async for chunk in _stream_reply_events(
            user_text, speaker_id, speed_scale, t0, t_stt, silent=silent
        ):
            yield chunk

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def pcm16_to_wav_bytes(pcm_chunks: list[bytes], sample_rate: int = 16000) -> bytes:
    raw = np.frombuffer(b"".join(pcm_chunks), dtype=np.int16).astype(np.float32)
    if raw.size > 0:
        peak = float(np.max(np.abs(raw)))
        if peak > 10.0:
            # 歪みの出ない線形ピーク正規化 (最大振幅の 75% に揃える)
            gain = min(12.0, (32767.0 * 0.75) / peak)
            raw = np.clip(raw * gain, -32767.0, 32767.0)
    norm_bytes = raw.astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(norm_bytes)
    return buf.getvalue()


@app.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket):
    """ChatGPT Voice Mode 方式: Silero VAD で人間の声だけを検知し、STT -> agy -> VOICEVOX を返す。"""
    await websocket.accept()
    vad = get_vad_model()
    vad.reset_states()

    speaker_id = DEFAULT_SPEAKER_ID
    speed_scale = 1.12
    in_sample_rate = 48000
    listening = True

    # Silero VAD パラメータ (16kHz, 512 samples = 32ms/chunk)
    CHUNK_SAMPLES = 512
    CHUNK_BYTES = CHUNK_SAMPLES * 2
    START_PROB = 0.35
    END_PROB = 0.20
    START_FRAMES = 2      # 約 64ms 連続で人間の声なら発話開始
    SILENCE_FRAMES = 26   # 約 830ms 無音で発話終了
    MAX_SPEECH_FRAMES = 460  # 最大約 15 秒
    PRE_ROLL_FRAMES = 18  # 約 0.58 秒のプリロール
    VAD_GAIN = 3.0        # Echo Show 5 の小さめなマイク入力を補うゲイン

    pcm16k_buf = bytearray()
    pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_FRAMES)
    speech_chunks: list[bytes] = []
    in_speech = False
    voiced_streak = 0
    silence_streak = 0
    processing_task: Optional[asyncio.Task] = None
    diag_frames = 0
    diag_max_prob = 0.0
    diag_max_rms = 0.0

    async def process_turn(chunks_copy: list[bytes]):
        nonlocal listening
        try:
            t0 = time.perf_counter()
            wav_bytes = pcm16_to_wav_bytes(chunks_copy, 16000)
            user_text = await asyncio.to_thread(transcribe_audio_bytes, wav_bytes, ".wav")
            t_stt = time.perf_counter() - t0
            print(f"[WS-STT] ({t_stt:.2f}s) sr={in_sample_rate} text={user_text!r}", flush=True)

            if not user_text:
                await websocket.send_json({"type": "empty"})
                vad.reset_states()
                listening = True
                await websocket.send_json({"type": "state", "state": "listening"})
                return

            await websocket.send_json({
                "type": "stt",
                "user_text": user_text,
                "stt_sec": round(t_stt, 2),
            })

            tts_tasks: list[tuple[str, asyncio.Task[bytes]]] = []
            buf = ""
            split_re = re.compile(r"([。！？\n])")
            t_ai_start = time.perf_counter()
            first_audio_sent = False
            first_audio_sec = 0.0

            async def flush_sentence(s: str) -> None:
                cleaned = clean_for_speech(s)
                if cleaned:
                    task = asyncio.create_task(
                        synthesize_voicevox(cleaned, speaker_id, speed_scale)
                    )
                    tts_tasks.append((cleaned, task))

            async for delta in agy_session.ask_deltas(user_text, speaker_id=speaker_id):
                buf += delta
                while True:
                    m = split_re.search(buf)
                    if not m:
                        break
                    end_idx = m.end()
                    sentence = buf[:end_idx]
                    buf = buf[end_idx:]
                    await flush_sentence(sentence)

                    while tts_tasks and tts_tasks[0][1].done():
                        s_txt, task = tts_tasks.pop(0)
                        wav = await task
                        if not first_audio_sent:
                            first_audio_sent = True
                            first_audio_sec = time.perf_counter() - t0
                        await websocket.send_json({
                            "type": "audio",
                            "text": s_txt,
                            "audio_base64": base64.b64encode(wav).decode("ascii"),
                        })

            if buf.strip():
                await flush_sentence(buf)

            t_ai = time.perf_counter() - t_ai_start

            for s_txt, task in tts_tasks:
                wav = await task
                if not first_audio_sent:
                    first_audio_sent = True
                    first_audio_sec = time.perf_counter() - t0
                await websocket.send_json({
                    "type": "audio",
                    "text": s_txt,
                    "audio_base64": base64.b64encode(wav).decode("ascii"),
                })

            await websocket.send_json({
                "type": "turn_done",
                "timings": {
                    "stt": round(t_stt, 2),
                    "agy": round(t_ai, 2),
                    "first_audio": round(first_audio_sec, 2),
                },
            })
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[WS-ERR] {e}", flush=True)
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
                vad.reset_states()
                listening = True
                await websocket.send_json({"type": "state", "state": "listening"})
            except Exception:
                pass

    await websocket.send_json({"type": "state", "state": "listening"})

    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break

            if msg.get("text") is not None:
                data = json.loads(msg["text"])
                mtype = data.get("type")
                if mtype == "config":
                    speaker_id = int(data.get("speaker_id", speaker_id))
                    speed_scale = float(data.get("speed_scale", speed_scale))
                    if data.get("sample_rate"):
                        in_sample_rate = int(data["sample_rate"])
                elif mtype == "resume":
                    vad.reset_states()
                    pcm16k_buf.clear()
                    pre_roll.clear()
                    speech_chunks.clear()
                    in_speech = False
                    voiced_streak = 0
                    silence_streak = 0
                    listening = True
                    await websocket.send_json({"type": "state", "state": "listening"})
                elif mtype == "interrupt":
                    if processing_task and not processing_task.done():
                        processing_task.cancel()
                    vad.reset_states()
                    pcm16k_buf.clear()
                    pre_roll.clear()
                    speech_chunks.clear()
                    in_speech = False
                    voiced_streak = 0
                    silence_streak = 0
                    listening = True
                    await websocket.send_json({"type": "state", "state": "listening"})
                elif mtype == "commit":
                    if in_speech and speech_chunks:
                        listening = False
                        captured = list(speech_chunks)
                        speech_chunks.clear()
                        in_speech = False
                        voiced_streak = 0
                        silence_streak = 0
                        await websocket.send_json({"type": "state", "state": "thinking"})
                        processing_task = asyncio.create_task(process_turn(captured))
                continue

            raw_bytes = msg.get("bytes")
            if not raw_bytes or not listening:
                continue

            # ネイティブ sample_rate -> 16kHz へ高品質リサンプリング
            if in_sample_rate != 16000:
                in_arr = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
                target_len = max(1, int(round(len(in_arr) * 16000 / in_sample_rate)))
                resamp = signal.resample(in_arr, target_len)
                pcm16k_bytes = np.clip(resamp, -32768.0, 32767.0).astype(np.int16).tobytes()
            else:
                pcm16k_bytes = raw_bytes

            pcm16k_buf.extend(pcm16k_bytes)
            while len(pcm16k_buf) >= CHUNK_BYTES and listening:
                chunk = bytes(pcm16k_buf[:CHUNK_BYTES])
                del pcm16k_buf[:CHUNK_BYTES]

                arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(arr * arr)))
                boosted = np.clip(arr * VAD_GAIN, -1.0, 1.0)
                with torch.no_grad():
                    prob = float(vad(torch.from_numpy(boosted), 16000).item())

                diag_frames += 1
                diag_max_prob = max(diag_max_prob, prob)
                diag_max_rms = max(diag_max_rms, rms)
                if diag_frames >= 62:  # 約2秒ごと
                    print(f"[WS-VAD] max_prob={diag_max_prob:.2f} max_rms={diag_max_rms:.4f} in_speech={in_speech}", flush=True)
                    diag_frames = 0
                    diag_max_prob = 0.0
                    diag_max_rms = 0.0

                if not in_speech:
                    pre_roll.append(chunk)
                    if prob >= START_PROB:
                        voiced_streak += 1
                        if voiced_streak >= START_FRAMES:
                            in_speech = True
                            silence_streak = 0
                            speech_chunks = list(pre_roll)
                            pre_roll.clear()
                            await websocket.send_json({"type": "speech_start"})
                    else:
                        voiced_streak = 0
                else:
                    speech_chunks.append(chunk)
                    if prob < END_PROB:
                        silence_streak += 1
                    else:
                        silence_streak = 0

                    if silence_streak >= SILENCE_FRAMES or len(speech_chunks) >= MAX_SPEECH_FRAMES:
                        listening = False
                        captured = list(speech_chunks)
                        speech_chunks.clear()
                        in_speech = False
                        voiced_streak = 0
                        silence_streak = 0
                        await websocket.send_json({"type": "state", "state": "thinking"})
                        processing_task = asyncio.create_task(process_turn(captured))
    except WebSocketDisconnect:
        pass
    finally:
        if processing_task and not processing_task.done():
            processing_task.cancel()
