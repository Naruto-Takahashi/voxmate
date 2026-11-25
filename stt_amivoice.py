import os
from pathlib import Path
from typing import Optional

import httpx

DEFAULT_AMIVOICE_URL = "https://acp-api.amivoice.com/v1/nolog/recognize"
DEFAULT_AMIVOICE_ENGINE = "-a-general"


def build_amivoice_d_param(
    engine: str = DEFAULT_AMIVOICE_ENGINE,
    profile_words: str = "",
) -> str:
    """AmiVoice 同期 HTTP API 用の d パラメータを組み立てる。"""
    parts = [f"grammarFileNames={engine.strip() or DEFAULT_AMIVOICE_ENGINE}"]
    words = profile_words.strip()
    if words:
        parts.append(f"profileWords={words}")
    return " ".join(parts)


def parse_amivoice_response(payload: dict) -> str:
    """AmiVoice 同期 HTTP API の JSON レスポンスから認識テキストを抽出する。"""
    code = str(payload.get("code") or "").strip()
    if code:
        msg = str(payload.get("message") or "AmiVoice API error").strip()
        raise RuntimeError(f"AmiVoice error ({code}): {msg}")
    return str(payload.get("text") or "").strip()


def transcribe_wav_amivoice(
    wav_path: Path,
    app_key: Optional[str] = None,
    engine: Optional[str] = None,
    profile_words: Optional[str] = None,
    endpoint_url: Optional[str] = None,
    timeout_sec: float = 30.0,
) -> str:
    """16kHz モノラル WAV ファイルを AmiVoice 同期 HTTP API で文字起こしする。"""
    key = (app_key if app_key is not None else os.environ.get("AMIVOICE_APP_KEY", "")).strip()
    if not key:
        raise RuntimeError(
            "AMIVOICE_APP_KEY が設定されていません。.env または環境変数に設定してください。"
        )

    eng = (
        engine
        if engine is not None
        else os.environ.get("AMIVOICE_ENGINE", DEFAULT_AMIVOICE_ENGINE)
    ).strip() or DEFAULT_AMIVOICE_ENGINE
    words = (
        profile_words
        if profile_words is not None
        else os.environ.get("AMIVOICE_PROFILE_WORDS", "")
    ).strip()
    url = (
        endpoint_url
        if endpoint_url is not None
        else os.environ.get("AMIVOICE_URL", DEFAULT_AMIVOICE_URL)
    ).strip() or DEFAULT_AMIVOICE_URL

    d_param = build_amivoice_d_param(engine=eng, profile_words=words)
    audio_bytes = wav_path.read_bytes()

    with httpx.Client(timeout=timeout_sec) as client:
        resp = client.post(
            url,
            files={
                "u": (None, key),
                "d": (None, d_param),
                "a": (wav_path.name, audio_bytes, "audio/wav"),
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"AmiVoice HTTP error ({resp.status_code}): {resp.text[:300]}"
            )
        return parse_amivoice_response(resp.json())
