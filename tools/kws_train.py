#!/usr/bin/env python3
"""openWakeWord 特徴抽出器 (16x96) を使ってカスタム KWS モデル (.onnx) を学習・評価する。"""

from __future__ import annotations

import argparse
import random
import wave
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from openwakeword.model import Model as OWWModel
import openwakeword.utils as oww_utils
from openwakeword.utils import AudioFeatures


def _ensure_oww_base_models() -> None:
    import openwakeword
    res_dir = Path(openwakeword.__file__).resolve().parent / "resources" / "models"
    if not (res_dir / "melspectrogram.onnx").exists() or not (res_dir / "embedding_model.onnx").exists():
        dl = getattr(oww_utils, "download_models", None)
        if dl is not None:
            print("Downloading openWakeWord base feature models...")
            dl([])


TARGET_SAMPLES = 32000  # 2.0 sec @ 16kHz -> embed_clips output shape (16, 96)


def load_wav_16k_float(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def trim_silence(pcm: np.ndarray, thresh: float = 0.02, pad_samples: int = 1600) -> np.ndarray:
    if len(pcm) == 0:
        return pcm
    peak = float(np.max(np.abs(pcm)))
    if peak < 1e-4:
        return pcm
    abs_pcm = np.abs(pcm)
    idx = np.where(abs_pcm >= max(thresh, peak * 0.08))[0]
    if len(idx) == 0:
        return pcm
    s = max(0, int(idx[0]) - pad_samples)
    e = min(len(pcm), int(idx[-1]) + 1 + pad_samples)
    return pcm[s:e]


def place_in_2s_window(pcm: np.ndarray, rng: random.Random, align: str = "random") -> np.ndarray:
    pcm = trim_silence(pcm)
    out = np.zeros(TARGET_SAMPLES, dtype=np.float32)
    if len(pcm) >= TARGET_SAMPLES:
        start = (len(pcm) - TARGET_SAMPLES) if align == "end" else rng.randint(0, len(pcm) - TARGET_SAMPLES)
        out[:] = pcm[start : start + TARGET_SAMPLES]
        return out
    slack = TARGET_SAMPLES - len(pcm)
    if align == "end":
        # 発話が終わった直後〜0.45秒以内をターゲットにする
        min_off = max(0, slack - int(0.45 * 16000))
        offset = rng.randint(min_off, slack)
    elif align == "partial_neg":
        # 言葉の後半が切れたスライディングウィンドウをネガティブとして学習させる
        keep = max(4000, min(len(pcm) // 2, 12000))
        offset = TARGET_SAMPLES - keep
        out[offset : offset + keep] = pcm[:keep]
        return out
    else:
        offset = rng.randint(0, slack)
    out[offset : offset + len(pcm)] = pcm
    return out


def augment_clip(pcm: np.ndarray, rng: random.Random, is_pos: bool) -> np.ndarray:
    gain = rng.uniform(0.32, 1.15) if is_pos else rng.uniform(0.25, 1.15)
    x = pcm * gain
    # 環境ノイズを軽く混合
    noise_level = rng.uniform(0.0, 0.015)
    if noise_level > 0:
        x = x + np.random.normal(0.0, noise_level, size=x.shape).astype(np.float32)
    x = np.clip(x, -1.0, 1.0)
    return (x * 32767.0).astype(np.int16)


class KwsNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.LayerNorm(96),
        )
        self.temporal = nn.Conv1d(96, 64, kernel_size=3, padding=1)
        self.act = nn.ReLU()
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.30),
            nn.Linear(16 * 64, 96),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(96, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, 16, 96)
        h = self.conv(x).transpose(1, 2)  # (B, 96, 16)
        h = self.act(self.temporal(h)).transpose(1, 2)  # (B, 16, 64)
        return self.head(h)


class KwsExportWrapper(nn.Module):
    def __init__(self, core: KwsNet) -> None:
        super().__init__()
        self.core = core

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.core(x))


def build_dataset(data_dir: Path, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    np.random.seed(seed)

    pos_tts = sorted((data_dir / "pos_tts").glob("*.wav"))
    pos_user = sorted((data_dir / "pos_user").glob("*.wav"))
    neg_tts = sorted((data_dir / "neg_tts").glob("*.wav"))
    neg_user = sorted((data_dir / "neg_user").glob("*.wav"))

    print(
        f"Dataset files: pos_tts={len(pos_tts)}, pos_user={len(pos_user)}, "
        f"neg_tts={len(neg_tts)}, neg_user={len(neg_user)}"
    )
    if not pos_tts and not pos_user:
        raise RuntimeError("No positive samples found!")

    clips: list[np.ndarray] = []
    labels: list[int] = []

    # ポジティブ TTS: 各サンプルを1〜2パターンの配置・音量で拡張
    for p in pos_tts:
        pcm = load_wav_16k_float(p)
        for _ in range(2):
            w = place_in_2s_window(pcm, rng, align="end")
            clips.append(augment_clip(w, rng, is_pos=True))
            labels.append(1)

    # ユーザー生声ポジティブ＆ネガティブ:
    # 話者声質だけでポジティブと誤学習しないよう、pos_user と neg_user の総クリップ数をバランスさせ全スライド位置をカバー
    if pos_user:
        repeat_user = max(6, min(14, 300 // max(1, len(pos_user))))
        for p in pos_user:
            pcm = load_wav_16k_float(p)
            for _ in range(repeat_user):
                w = place_in_2s_window(pcm, rng, align="end")
                clips.append(augment_clip(w, rng, is_pos=True))
                labels.append(1)

    # ネガティブ TTS: random + end配置でハードネガティブの誤爆を抑える
    for p in neg_tts:
        pcm = load_wav_16k_float(p)
        for al in ("random", "end"):
            w = place_in_2s_window(pcm, rng, align=al)
            clips.append(augment_clip(w, rng, is_pos=False))
            labels.append(0)

    # ポジティブの途中切れ（「ちょっと」だけ等）もネガティブとして少量混ぜる
    for p in rng.sample(pos_tts, min(200, len(pos_tts))):
        pcm = load_wav_16k_float(p)
        w = place_in_2s_window(pcm, rng, align="partial_neg")
        clips.append(augment_clip(w, rng, is_pos=False))
        labels.append(0)

    # ユーザーネガティブ (あらゆるスライド位置で確実に 0 を出すよう多めに拡張)
    if neg_user:
        repeat_neg_user = max(10, min(35, 350 // max(1, len(neg_user))))
        for p in neg_user:
            pcm = load_wav_16k_float(p)
            for _ in range(repeat_neg_user):
                al = rng.choice(("random", "end"))
                w = place_in_2s_window(pcm, rng, align=al)
                clips.append(augment_clip(w, rng, is_pos=False))
                labels.append(0)

    # 純粋な無音・環境ノイズ系ネガティブを追加
    for _ in range(300):
        lvl = rng.uniform(0.0, 0.025)
        noise = np.random.normal(0.0, lvl, size=TARGET_SAMPLES).astype(np.float32)
        clips.append((np.clip(noise, -1.0, 1.0) * 32767.0).astype(np.int16))
        labels.append(0)

    X_audio = np.stack(clips, axis=0)
    y = np.array(labels, dtype=np.float32)

    print(f"Extracting openWakeWord embeddings for {len(X_audio)} clips...")
    _ensure_oww_base_models()
    import inspect
    af_params = inspect.signature(AudioFeatures.__init__).parameters
    af = AudioFeatures(inference_framework="onnx") if "inference_framework" in af_params else AudioFeatures()
    feats = af.embed_clips(X_audio, batch_size=64)
    print(f"Embeddings shape: {feats.shape}")
    return feats, y


def train_and_export(
    data_dir: Path,
    out_onnx: Path,
    epochs: int = 35,
    lr: float = 1e-3,
) -> None:
    feats, y = build_dataset(data_dir)
    n = len(feats)
    idx = np.random.permutation(n)
    split = int(n * 0.85)
    tr_idx, va_idx = idx[:split], idx[split:]

    X_tr = torch.from_numpy(feats[tr_idx])
    y_tr = torch.from_numpy(y[tr_idx]).unsqueeze(1)
    X_va = torch.from_numpy(feats[va_idx])
    y_va = torch.from_numpy(y[va_idx]).unsqueeze(1)

    # 誤検知を厳しく抑えるため pos_weight は抑えめにする
    pos_weight = torch.tensor([0.8])

    model = KwsNet()
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)

    best_loss = float("inf")
    best_state = None
    batch_size = 128

    for ep in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(len(X_tr))
        for i in range(0, len(X_tr), batch_size):
            b = perm[i : i + batch_size]
            opt.zero_grad()
            logits = model(X_tr[b])
            loss = criterion(logits, y_tr[b])
            loss.backward()
            opt.step()

        model.eval()
        with torch.no_grad():
            va_logits = model(X_va)
            va_loss = float(criterion(va_logits, y_va))
            probs = torch.sigmoid(va_logits)
            preds = (probs >= 0.5).float()
            tp = float(((preds == 1) & (y_va == 1)).sum())
            fp = float(((preds == 1) & (y_va == 0)).sum())
            fn = float(((preds == 0) & (y_va == 1)).sum())
            tn = float(((preds == 0) & (y_va == 0)).sum())
            recall = tp / max(1.0, tp + fn)
            fpr = fp / max(1.0, fp + tn)

        if va_loss < best_loss:
            best_loss = va_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}

        if ep % 5 == 0 or ep == epochs:
            print(
                f"Epoch {ep:02d}/{epochs} | val_loss={va_loss:.4f} | "
                f"recall={recall*100:.1f}% | false_pos={fpr*100:.2f}%"
            )

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()

    out_onnx.parent.mkdir(parents=True, exist_ok=True)
    wrapper = KwsExportWrapper(model).eval()
    dummy_in = torch.zeros(1, 16, 96, dtype=torch.float32)
    torch.onnx.export(
        wrapper,
        dummy_in,
        str(out_onnx),
        input_names=["input"],
        output_names=["output"],
        opset_version=14,
        dynamo=False,
    )
    print(f"Exported ONNX model to {out_onnx} ({out_onnx.stat().st_size / 1024:.1f} KB)")

    # openWakeWord でロードして推論テスト
    import inspect
    oww_params = inspect.signature(OWWModel.__init__).parameters
    kw_arg = "wakeword_models" if "wakeword_models" in oww_params else "wakeword_model_paths"
    oww_kwargs = {kw_arg: [str(out_onnx)]}
    if "inference_framework" in oww_params:
        oww_kwargs["inference_framework"] = "onnx"
    oww = OWWModel(**oww_kwargs)
    test_silence = np.zeros(1280, dtype=np.int16)
    res = oww.predict(test_silence)
    print("openWakeWord smoke test:", res)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/kws")
    parser.add_argument("--out", default="models/chotto_kiite.onnx")
    parser.add_argument("--epochs", type=int, default=35)
    args = parser.parse_args()
    train_and_export(Path(args.data_dir), Path(args.out), epochs=args.epochs)


if __name__ == "__main__":
    main()
