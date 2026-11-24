#!/usr/bin/env python3
"""custom_psd/ 配下の立ち絵 PSD から全表情 PNG を static/portraits/ へ一括抽出する。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from PIL import Image
from psd_tools import PSDImage

ASSET_DIRS = {
    "zundamon": "zundamon",
    "metan": "metan",
    "tsumugi": "tsumugi",
    "hau": "hau",
    "sora": "sora",
    "whitecul": "whitecul",
    "goki": "goki",
    "usagi": "usagi",
    "zunko": "zunko",
    "itako": "itako",
    "ankomon": "ankomon",
    "kobako": "kobako",
}

EXPRESSIONS = (
    "idle",
    "blink",
    "speak",
    "think",
    "happy",
    "troubled",
    "surprised",
    "shy",
    "angry",
    "sad",
    "pale",
    "playful",
)


def _find_group(psd: PSDImage, keywords: Iterable[str]):
    for layer in psd:
        if layer.is_group() and any(k in layer.name for k in keywords):
            return layer
    # 衣装グループの中に腕グループがネストされているキャラ（hau, metan, usagi, kobako）向け
    for layer in psd:
        if layer.is_group() and layer.visible:
            for sub in layer:
                if sub.is_group() and any(k in sub.name for k in keywords):
                    return sub
    return None


def _pick_child(group, candidates: Iterable[str], fallback_last: bool = True):
    if group is None:
        return None
    children = list(group)
    for pat in candidates:
        for c in children:
            if pat in c.name and "非表示" not in c.name:
                return c
    if fallback_last:
        for c in reversed(children):
            if "非表示" not in c.name:
                return c
    return None


def _select_only(group, target) -> None:
    if group is None:
        return
    group.visible = True
    for c in group:
        c.visible = (c is target)


def _set_symbols(
    psd: PSDImage,
    want_sweat: bool = False,
    want_tear: bool = False,
    want_sweat_heavy: bool = False,
) -> None:
    for layer in psd:
        if layer.is_group() and any(k in layer.name for k in ("汗", "涙", "記号", "なみだ")):
            layer.visible = True
            has_regular_sweat = any("汗" in c.name and "多め" not in c.name for c in layer)
            has_regular_tear = any(("涙" in c.name or "なみだ" in c.name) and "滝" not in c.name for c in layer)
            for c in layer:
                nm = c.name
                if want_sweat_heavy and "汗多め" in nm:
                    c.visible = True
                elif (want_sweat or (want_sweat_heavy and not has_regular_sweat)) and "汗" in nm and "多め" not in nm:
                    c.visible = True
                elif want_tear and ("涙" in nm or "なみだ" in nm) and (not has_regular_tear or "滝" not in nm):
                    c.visible = True
                elif any(k in nm for k in ("汗", "涙", "なみだ", "非公式", "!B")):
                    c.visible = False


def _apply_expression(psd: PSDImage, expr: str) -> None:
    eye_g = _find_group(psd, ("!目", "目"))
    brow_g = _find_group(psd, ("!眉", "眉", "!まゆ", "まゆ"))
    mouth_g = _find_group(psd, ("!口", "口"))
    cheek_g = _find_group(psd, ("!頬", "!ほっぺ", "ほっぺ", "!顔色", "顔色"))
    l_arm_g = _find_group(psd, ("!左腕", "!手前の腕"))
    r_arm_g = _find_group(psd, ("!右腕", "!奥の腕"))

    # 腕のデフォルトは基本
    l_arm = _pick_child(l_arm_g, ("*基本", "*普通", "基本"))
    r_arm = _pick_child(r_arm_g, ("*基本", "*普通", "基本"))

    # デフォルトの頬
    cheek = _pick_child(cheek_g, ("*ほっぺ基本", "*ほっぺ", "*頬", "*普通", "ほっぺ"), fallback_last=False)

    want_sweat = False
    want_sweat_heavy = False
    want_tear = False

    if expr == "idle":
        eye = _pick_child(eye_g, ("*基本目セット", "*普通目", "*目セット", "*基本a1", "*基本目1", "*基本目", "*カメラ目線", "*基本"))
        brow = _pick_child(brow_g, ("*基本眉", "*普通眉", "*基本", "*普通", "*ごきげん"))
        mouth = _pick_child(mouth_g, ("*ほほえみ", "*にこ", "*ん"))
    elif expr == "blink":
        eye = _pick_child(eye_g, ("*閉じ目", "*目閉じ", "*閉じ", "*ーー", "*なごみ", "*にっこり"))
        brow = _pick_child(brow_g, ("*基本眉", "*普通眉", "*基本", "*普通", "*ごきげん"))
        mouth = _pick_child(mouth_g, ("*ほほえみ", "*にこ", "*ん"))
    elif expr == "speak":
        eye = _pick_child(eye_g, ("*基本目セット", "*普通目", "*目セット", "*基本a1", "*基本目1", "*基本目", "*カメラ目線", "*基本"))
        brow = _pick_child(brow_g, ("*基本眉", "*普通眉", "*基本", "*普通", "*ごきげん"))
        mouth = _pick_child(mouth_g, ("*わあー", "*あは", "*ほあー", "*ほえあー", "*おわー", "*おおー", "*えあー", "*ほあ", "*おー", "*お"))
    elif expr == "think":
        eye = _pick_child(eye_g, ("*上向き目", "*上向き", "*上むき", "*見上げ", "*基本目2", "*目逸らし", "*基本"))
        brow = _pick_child(brow_g, ("*困り", "*こまり", "*上がり", "*基本"))
        mouth = _pick_child(mouth_g, ("*んー", "*むん", "*んむ", "*ん", "*む", "*三角", "*△"))
        l_arm = _pick_child(l_arm_g, ("*考える", "*あごに指", "*口元に指", "*口元", "*頬に手", "*胸元", "*手のひら", "*基本", "*普通"))
    elif expr == "happy":
        eye = _pick_child(eye_g, ("*にっこり", "*^^", "*><", "*＞＜"))
        brow = _pick_child(brow_g, ("*上がり", "*ごきげん", "*基本", "*普通"))
        mouth = _pick_child(mouth_g, ("*わあー", "*わあ", "*わー", "*あはー", "*あは", "*えへ", "*ほあー", "*ほほえみ"))
        cheek = _pick_child(cheek_g, ("*ほっぺ赤め", "ほっぺ赤め", "*赤面", "*ほっぺ", "*頬", "*普通"), fallback_last=False) or cheek
        r_arm = _pick_child(r_arm_g, ("*手を挙げる", "*ばんざい", "*ぐっ", "*ピース", "*ひろげ", "*腕ひろげる", "*上", "*指立て", "*ゆびたて", "*指さし", "*指差す", "*ゆびさし", "*指差し上", "*基本", "*普通"))
    elif expr == "troubled":
        eye = _pick_child(eye_g, ("*なごみ", "*><", "*＞＜", "*基本"))
        brow = _pick_child(brow_g, ("*困り", "*こまり"))
        mouth = _pick_child(mouth_g, ("*うへー", "*うへえー", "*うへぇ", "*むくー", "*うえー", "*あえ", "*んー", "*んゅ", "*んむ", "*む"))
        r_arm = _pick_child(r_arm_g, ("*頭こつん", "*ほっぺに手", "*頬に手", "*胸元", "*手の甲", "*基本", "*普通"))
        want_sweat = True
    elif expr == "surprised":
        eye = _pick_child(eye_g, ("*〇〇", "*◯◯", "*○○", "*見開き", "*上向き目2", "*カメラ目線", "*基本"))
        brow = _pick_child(brow_g, ("*上がり", "*困り", "*基本"))
        mouth = _pick_child(mouth_g, ("*うわー", "*うっわー", "*おおー", "*おわー", "*おあー", "*おー", "*ほえあー", "*お"))
        r_arm = _pick_child(r_arm_g, ("*手を挙げる", "*ばんざい", "*ひろげ", "*腕ひろげる", "*上", "*手をかざす", "*ほっぺに手", "*頬に手", "*横", "*指さし", "*指差し横", "*ゆびさし", "*基本", "*普通"))
    elif expr == "shy":
        eye = _pick_child(eye_g, ("*><", "*＞＜", "*なごみ", "*にっこり", "*うっとり"))
        brow = _pick_child(brow_g, ("*困り", "*こまり", "*上がり", "*基本"))
        mouth = _pick_child(mouth_g, ("*えへ", "*へへ", "*にへ", "*むふ", "*ぺろ", "*ほほえみ"))
        cheek = _pick_child(cheek_g, ("*赤面", "*ほっぺ赤め", "ほっぺ赤め", "*ほっぺ"), fallback_last=False) or cheek
        l_arm = _pick_child(l_arm_g, ("*頬に手", "*口元", "*胸元", "*ひそひそ", "*ささやき", "*手の甲", "*基本", "*普通"))
        r_arm = _pick_child(r_arm_g, ("*ほっぺに手", "*頬に手", "*胸元", "*基本", "*普通"))
    elif expr == "angry":
        eye = _pick_child(eye_g, ("*ジト目", "*三白眼", "*細め目", "*基本目セット", "*普通目", "*目セット", "*基本"))
        brow = _pick_child(brow_g, ("*怒り", "*おこ"))
        mouth = _pick_child(mouth_g, ("*むん", "*むすー", "*むくー", "*いー", "*もむー", "*んむ", "*んー"))
        l_arm = _pick_child(l_arm_g, ("*腕組み", "*腰", "*胸元", "*基本", "*普通"))
        r_arm = _pick_child(r_arm_g, ("*指差し横", "*指差す", "*横指差し", "*指さし", "*ゆびさし", "*ゆびたて", "*指立て", "*腰", "*チョップ", "*基本", "*普通"))
    elif expr == "sad":
        eye = _pick_child(eye_g, ("*なごみ", "*閉じ目", "*目閉じ", "*閉じ", "*><", "*＞＜", "*基本"))
        brow = _pick_child(brow_g, ("*困り", "*こまり"))
        mouth = _pick_child(mouth_g, ("*んゅ", "*むくー", "*うえー", "*うへー", "*うへえー", "*あえ", "*んー", "*んむ", "*む"))
        r_arm = _pick_child(r_arm_g, ("*胸元", "*ほっぺに手", "*頬に手", "*基本", "*普通"))
        want_tear = True
    elif expr == "pale":
        eye = _pick_child(eye_g, ("*ぐるぐる", "*四白眼", "*三白眼", "*ジト目", "*〇〇", "*◯◯", "*○○", "*なごみ", "*基本"))
        brow = _pick_child(brow_g, ("*困り", "*こまり"))
        mouth = _pick_child(mouth_g, ("*うへー", "*うへえー", "*うへぇ", "*ひゅっ", "*むあー", "*うえー", "*△", "*三角", "*んー", "*む"))
        cheek = _pick_child(cheek_g, ("*青ざめ", "*青め", "縦線", "*クマ", "*くま", "*寝不足", "かげり", "*ほっぺ", "*頬"), fallback_last=False) or cheek
        r_arm = _pick_child(r_arm_g, ("*頭こつん", "*ほっぺに手", "*頬に手", "*口元", "*手の甲", "*基本", "*普通"))
        want_sweat_heavy = True
    elif expr == "playful":
        eye = _pick_child(eye_g, ("*ウインク", "*にっこり", "*><", "*＞＜", "*うっとり", "*基本"))
        brow = _pick_child(brow_g, ("*上がり", "*ごきげん", "*困り", "*基本", "*普通"))
        mouth = _pick_child(mouth_g, ("*ぺろん", "*ぺろり", "*ぺろ", "*にやり", "*にやけ", "*にし", "*ω", "*むふ", "*えへ", "*ちゅわ"))
        cheek = _pick_child(cheek_g, ("*ほっぺ赤め", "ほっぺ赤め", "*赤面", "*ほっぺ", "*頬", "*普通"), fallback_last=False) or cheek
        l_arm = _pick_child(l_arm_g, ("*ピース", "*口元に指", "*口元", "*ひそひそ", "*ささやき", "*基本", "*普通"))
        r_arm = _pick_child(r_arm_g, ("*ピース", "*頭こつん", "*チョップ", "*ぐっ", "*指さし", "*指差す", "*ゆびさし", "*横", "*基本", "*普通"))
    else:
        return

    _select_only(eye_g, eye)
    _select_only(brow_g, brow)
    _select_only(mouth_g, mouth)
    if cheek_g is not None and cheek is not None:
        _select_only(cheek_g, cheek)
    if l_arm_g is not None and l_arm is not None:
        _select_only(l_arm_g, l_arm)
        if "腕組み" in l_arm.name and r_arm_g is not None:
            r_arm_g.visible = False
            r_arm = None
    if r_arm_g is not None and r_arm is not None:
        _select_only(r_arm_g, r_arm)
    _set_symbols(psd, want_sweat=want_sweat, want_tear=want_tear, want_sweat_heavy=want_sweat_heavy)


def extract_character(asset: str, psd_path: Path, out_dir: Path, height: int = 800) -> None:
    psd = PSDImage.open(psd_path)
    if asset == "hau":
        for layer in psd:
            if layer.is_group():
                if "標準防護具" in layer.name:
                    layer.visible = False
                elif "いつもの服" in layer.name:
                    layer.visible = True
    rendered: dict[str, Image.Image] = {}
    union_bbox = None

    for expr in EXPRESSIONS:
        _apply_expression(psd, expr)
        img = psd.composite(force=True).convert("RGBA")
        rendered[expr] = img
        bb = img.getbbox()
        if bb:
            if union_bbox is None:
                union_bbox = bb
            else:
                union_bbox = (
                    min(union_bbox[0], bb[0]),
                    min(union_bbox[1], bb[1]),
                    max(union_bbox[2], bb[2]),
                    max(union_bbox[3], bb[3]),
                )

    if union_bbox is None:
        union_bbox = (0, 0, psd.width, psd.height)

    cw = union_bbox[2] - union_bbox[0]
    ch = union_bbox[3] - union_bbox[1]
    target_w = max(1, int(round(cw * (height / ch))))

    out_dir.mkdir(parents=True, exist_ok=True)
    for expr, img in rendered.items():
        cropped = img.crop(union_bbox).resize((target_w, height), Image.Resampling.LANCZOS)
        cropped.save(out_dir / f"{asset}_{expr}.png")

    icon_path = out_dir / f"{asset}_icon.png"
    if not icon_path.exists():
        idle = rendered["idle"].crop(union_bbox)
        face_sz = min(cw, int(ch * 0.45))
        fx = max(0, (cw - face_sz) // 2)
        fy = max(0, int(ch * 0.04))
        face = idle.crop((fx, fy, fx + face_sz, fy + face_sz)).resize((128, 128), Image.Resampling.LANCZOS)
        face.save(icon_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--psd-dir", default="custom_psd")
    parser.add_argument("--out-dir", default="static/portraits")
    parser.add_argument("--only", default="", help="Comma-separated asset keys")
    args = parser.parse_args()

    psd_root = Path(args.psd_dir)
    out_dir = Path(args.out_dir)
    targets = [s.strip() for s in args.only.split(",") if s.strip()] or list(ASSET_DIRS.keys())

    for asset in targets:
        sub = psd_root / ASSET_DIRS[asset]
        psds = sorted(sub.rglob("*.psd"))
        if not psds:
            print(f"[SKIP] {asset}: no PSD found in {sub}")
            continue
        print(f"[EXTRACT] {asset} <- {psds[0].name}", flush=True)
        extract_character(asset, psds[0], out_dir)
    print("Done.")


if __name__ == "__main__":
    main()
