#!/usr/bin/env python3
"""VOICEVOX Engine を使って KWS 学習用のポジティブ／ネガティブ音声（16kHz モノラル WAV）を生成する。"""

from __future__ import annotations

import argparse
import asyncio
import io
import random
import wave
from pathlib import Path

import httpx
import numpy as np
from scipy import signal

VOICEVOX_URL = "http://127.0.0.1:50021"

# 多様な男女・声質をカバーする話者ID群
SPEAKER_IDS = [3, 1, 7, 2, 0, 8, 10, 16, 23, 24, 27, 61, 107, 109, 113, 127]

POS_TEXTS = [
    "ちょっと聞いて",
    "ちょっときいて",
    "ちょっと聞いて。",
    "ちょっと聞いて！",
    "ちょ、ちょっと聞いて",
]

HARD_NEG_TEXTS = [
    "ちょっと待って",
    "ちょっとまって",
    "ちょっと見て",
    "ちょっとだけ",
    "ちょっと行ってくる",
    "ちょっと来て",
    "ちょっと教えて",
    "ちょっとお願い",
    "ちょっとこれ見て",
    "ちょっと暑いね",
    "ちょっと寒いね",
    "ちょっと休もう",
    "ちょっと違うかな",
    "ちょっと遠いかも",
    "聞いてみて",
    "これ聞いて",
    "ねえ聞いて",
    "聞いてないよ",
    "ちゃんと聞いてる？",
    "話を聞いて",
    "音楽を聞いて",
    "ちょっと確認して",
]

GENERAL_NEG_TEXTS = [
    "今日の予定を教えて",
    "今何時ですか",
    "おはようございます",
    "おやすみなさい",
    "いつもありがとう",
    "電気をつけて",
    "テレビを消して",
    "タイマーを3分かけて",
    "明日の天気はどうかな",
    "メールを確認して",
    "了解しました",
    "それはすごいですね",
    "なるほど分かりました",
    "お腹すいたなあ",
    "コーヒー飲みたい",
    "窓を開けておこう",
    "そろそろ寝る時間かな",
    "お疲れ様でした",
]


def _wav_bytes_to_16k_mono(wav_bytes: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        pcm = signal.resample_poly(pcm, 16000, sr).astype(np.float32)
    return np.clip(pcm, -1.0, 1.0)


def _save_16k_wav(path: Path, pcm: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    i16 = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(i16.tobytes())


async def _synth_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    text: str,
    speaker_id: int,
    speed: float,
    pitch: float,
    intonation: float,
    out_path: Path,
) -> bool:
    async with sem:
        try:
            q_resp = await client.post(
                f"{VOICEVOX_URL}/audio_query",
                params={"text": text, "speaker": speaker_id},
                timeout=15.0,
            )
            q_resp.raise_for_status()
            q = q_resp.json()
            q["speedScale"] = round(speed, 2)
            q["pitchScale"] = round(pitch, 3)
            q["intonationScale"] = round(intonation, 2)
            s_resp = await client.post(
                f"{VOICEVOX_URL}/synthesis",
                params={"speaker": speaker_id},
                json=q,
                timeout=20.0,
            )
            s_resp.raise_for_status()
            pcm = _wav_bytes_to_16k_mono(s_resp.content)
            _save_16k_wav(out_path, pcm)
            return True
        except Exception as e:
            print(f"[WARN] synth failed ({text}, sp={speaker_id}): {e}")
            return False


async def generate_dataset(pos_count: int, neg_count: int, out_dir: Path, concurrency: int = 4) -> None:
    rng = random.Random(42)
    pos_dir = out_dir / "pos_tts"
    neg_dir = out_dir / "neg_tts"
    pos_dir.mkdir(parents=True, exist_ok=True)
    neg_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient() as client:
        # 起動確認
        v = await client.get(f"{VOICEVOX_URL}/version", timeout=5.0)
        v.raise_for_status()
        print(f"VOICEVOX version: {v.text.strip()}")

        tasks = []
        for i in range(pos_count):
            p = pos_dir / f"pos_{i:04d}.wav"
            if p.exists():
                continue
            tasks.append(
                _synth_one(
                    client,
                    sem,
                    rng.choice(POS_TEXTS),
                    rng.choice(SPEAKER_IDS),
                    rng.uniform(0.84, 1.26),
                    rng.uniform(-0.07, 0.07),
                    rng.uniform(0.85, 1.20),
                    p,
                )
            )

        neg_pool = HARD_NEG_TEXTS * 2 + GENERAL_NEG_TEXTS
        for i in range(neg_count):
            p = neg_dir / f"neg_{i:04d}.wav"
            if p.exists():
                continue
            tasks.append(
                _synth_one(
                    client,
                    sem,
                    rng.choice(neg_pool),
                    rng.choice(SPEAKER_IDS),
                    rng.uniform(0.84, 1.26),
                    rng.uniform(-0.07, 0.07),
                    rng.uniform(0.85, 1.20),
                    p,
                )
            )

        print(f"Generating {len(tasks)} audio files...")
        done = 0
        for fut in asyncio.as_completed(tasks):
            await fut
            done += 1
            if done % 100 == 0 or done == len(tasks):
                print(f"  progress: {done}/{len(tasks)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pos", type=int, default=800)
    parser.add_argument("--neg", type=int, default=1200)
    parser.add_argument("--out-dir", default="data/kws")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(generate_dataset(args.pos, args.neg, Path(args.out_dir), args.concurrency))
    print("Done.")


if __name__ == "__main__":
    main()
