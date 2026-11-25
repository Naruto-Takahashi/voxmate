#!/usr/bin/env python3
"""マイクからオーナーの生声サンプル（16kHz モノラル WAV）を連続録音するツール。"""

from __future__ import annotations

import argparse
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd


def save_wav(path: Path, pcm: np.ndarray, sr: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    i16 = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(i16.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["pos", "neg"], default="pos", help="pos=ちょっと聞いて / neg=誤爆しやすい言葉や環境音")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--sec", type=float, default=1.8)
    parser.add_argument("--out-dir", default="data/kws")
    args = parser.parse_args()

    sub = "pos_user" if args.kind == "pos" else "neg_user"
    out_dir = Path(args.out_dir) / sub
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("*.wav"))
    start_idx = len(existing)

    label = "「ちょっと聞いて」" if args.kind == "pos" else "「ちょっと待って / 無音 / 雑談」"
    print(f"=== 生声録音ツール ({label}) ===")
    print(f"保存先: {out_dir} / 回数: {args.count}回 / 1回 {args.sec}秒")
    print("普通・早口・小声・少し離れて などバリエーションを混ぜて発声してください。")
    input("準備ができたら Enter を押してください...")

    sr = 16000
    n_samples = int(sr * args.sec)
    for i in range(args.count):
        idx = start_idx + i
        print(f"\n[{i + 1}/{args.count}] 3... ", end="", flush=True)
        time.sleep(0.35)
        print("2... ", end="", flush=True)
        time.sleep(0.35)
        print("1... 発声！", flush=True)
        rec = sd.rec(n_samples, samplerate=sr, channels=1, dtype="float32")
        sd.wait()
        pcm = rec.reshape(-1)
        peak = float(np.max(np.abs(pcm)))
        out_path = out_dir / f"{args.kind}_{idx:04d}.wav"
        save_wav(out_path, pcm, sr)
        print(f"  保存完了: {out_path.name} (peak={peak:.3f})")
        time.sleep(0.25)

    print("\nすべての録音が完了しました！")


if __name__ == "__main__":
    main()
