import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

_ZUNDA_IDS = {3, 1, 7, 113, 114, 116}
_METAN_IDS = {2, 0, 6}
_TSUMUGI_IDS = {8}


def _noun_end(speaker_id: int) -> str:
    if speaker_id in _ZUNDA_IDS:
        return "なのだ！"
    if speaker_id in _METAN_IDS:
        return "ですわ！"
    if speaker_id in _TSUMUGI_IDS:
        return "だよ！"
    return "ですよ！"


def _past_end(speaker_id: int, stem_plain: str, stem_polite: str) -> str:
    if speaker_id in _ZUNDA_IDS:
        return f"{stem_plain}のだ！"
    if speaker_id in _METAN_IDS:
        return f"{stem_polite}わ！"
    if speaker_id in _TSUMUGI_IDS:
        return f"{stem_plain}よ！"
    return f"{stem_polite}！"


def _normalize(text: str) -> str:
    trans = str.maketrans("０１２３４５６７８９：", "0123456789:")
    return re.sub(r"\s+", " ", text.translate(trans)).strip()


def _try_clock(text: str, speaker_id: int) -> Optional[str]:
    if len(text) > 22:
        return None
    if any(w in text for w in ("予定", "会議", "ミーティング", "タイマー", "アラーム", "起き", "リマインド")):
        return None
    now = datetime.now().astimezone()
    end = _noun_end(speaker_id)
    if re.search(r"(今|いま|現在).{0,3}(何時|なんじ|時刻)", text) or text in ("何時", "なんじ", "現在時刻"):
        return f"今は{now.hour}時{now.minute}分{end}"
    if re.search(r"(今日|きょう).{0,3}(何日|なんにち|日付|何曜日|なんようび)", text) or text in ("今日の日付", "何曜日"):
        wday = "月火水木金土日"[now.weekday()]
        return f"今日は{now.month}月{now.day}日、{wday}曜日{end}"
    return None


async def _try_timer(text: str, speaker_id: int, timer_ops: dict[str, Any]) -> Optional[str]:
    n_end = _noun_end(speaker_id)
    is_timer_word = any(w in text for w in ("タイマー", "アラーム", "リマインド", "リマインダー", "目覚まし"))

    # 一覧確認
    if is_timer_word and any(w in text for w in ("確認", "一覧", "教えて", "見せて", "いくつ", "残")):
        if not any(w in text for w in ("かけて", "セット", "設定", "登録", "起こして")):
            timers = timer_ops["list"]()
            if not timers:
                return f"今動いているタイマーはない{n_end}"
            parts = []
            for t in timers[:3]:
                rem = int(t.get("remaining_sec", 0))
                m, s = divmod(rem, 60)
                rem_str = f"{m}分{s}秒" if m > 0 and s > 0 else (f"{m}分" if m > 0 else f"{s}秒")
                parts.append(f"{t['label']}があと{rem_str}")
            return "、".join(parts) + n_end

    # キャンセル / 停止
    if is_timer_word and any(w in text for w in ("止め", "とめ", "消し", "けし", "解除", "キャンセル", "削除")):
        if not re.search(r"\d+\s*(秒|分|時間|時)", text):
            removed = timer_ops["cancel"](all_timers=True)
            if removed > 0:
                return f"タイマーを{removed}件" + _past_end(speaker_id, "キャンセルした", "キャンセルしました")
            return f"キャンセルできるタイマーはなかった{n_end}"

    # 相対時間タイマー（例: 3分後にタイマー、1分30秒後にラーメン教えて）
    rel_m = re.search(
        r"(?:(?P<h>\d+)\s*時間)?\s*(?:(?P<m>\d+)\s*分)?\s*(?:(?P<s>\d+)\s*秒)?\s*後(?:に)?(?P<rest>.*)",
        text,
    )
    if rel_m and (rel_m.group("h") or rel_m.group("m") or rel_m.group("s")):
        rest = rel_m.group("rest") or ""
        if any(w in text for w in ("タイマー", "アラーム", "リマインド", "リマインダー", "教えて", "鳴らして")):
            sec = (
                int(rel_m.group("h") or 0) * 3600
                + int(rel_m.group("m") or 0) * 60
                + int(rel_m.group("s") or 0)
            )
            if sec > 0:
                kind = "reminder" if "リマインド" in text else "alarm"
                label_clean = re.sub(
                    r"(を|の)?(タイマー|アラーム|リマインド|リマインダー)(を)?(かけて|セットして|設定して|登録して|して|お願い|鳴らして)?|(を)?(教えて|鳴らして).*",
                    "",
                    rest,
                ).strip(" 、。")
                label = label_clean or ("リマインド" if kind == "reminder" else "タイマー")
                await timer_ops["add"](seconds=sec, at=None, label=label, kind=kind)
                h_val, rem_s = divmod(sec, 3600)
                m_val, s_val = divmod(rem_s, 60)
                dur_parts = []
                if h_val:
                    dur_parts.append(f"{h_val}時間")
                if m_val:
                    dur_parts.append(f"{m_val}分")
                if s_val:
                    dur_parts.append(f"{s_val}秒")
                dur_str = "".join(dur_parts)
                return f"{dur_str}後に{label}を" + _past_end(speaker_id, "セットした", "セットしました")

    # 時刻指定アラーム / リマインダー（例: 7時半に起こして、19時にゴミ出しリマインド）
    at_m = re.search(
        r"(?P<ampm>午前|午後)?\s*(?P<h>\d{1,2})\s*時\s*(?:(?P<half>半)|(?P<m>\d{1,2})\s*分?)?\s*(?:に)?(?P<rest>.*)",
        text,
    )
    if at_m and any(w in text for w in ("起こして", "アラーム", "タイマー", "リマインド", "リマインダー")):
        hour = int(at_m.group("h"))
        if at_m.group("ampm") == "午後" and hour < 12:
            hour += 12
        elif at_m.group("ampm") == "午前" and hour == 12:
            hour = 0
        minute = 30 if at_m.group("half") else int(at_m.group("m") or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            at_str = f"{hour:02d}:{minute:02d}"
            rest = at_m.group("rest") or ""
            kind = "reminder" if "リマインド" in text else "alarm"
            label_clean = re.sub(
                r"(で|に|を|の)?(起こして|アラーム|タイマー|リマインド|リマインダー)(を)?(かけて|セットして|設定して|登録して|して|お願い)?.*",
                "",
                rest,
            ).strip(" 、。")
            label = label_clean or ("目覚まし" if "起こして" in text else ("リマインド" if kind == "reminder" else "アラーム"))
            await timer_ops["add"](seconds=None, at=at_str, label=label, kind=kind)
            return f"{hour}時{minute:02d}分に{label}を" + _past_end(speaker_id, "セットした", "セットしました")

    return None


def _load_switchbot_devices(workdir: Path, base_dir: Path) -> list[dict]:
    candidates = [
        workdir / "memory" / "switchbot-devices.json",
        workdir / ".cache" / "switchbot-devices.json",
        base_dir / ".cache" / "switchbot-devices.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return list(data.get("devices", [])) + list(data.get("remotes", []))
            except Exception:
                pass
    return []


async def _try_switchbot(text: str, speaker_id: int, workdir: Path, base_dir: Path) -> Optional[str]:
    if len(text) > 35:
        return None
    # 複雑な操作（温度指定・状態確認・一括操作等）は LLM へ渡す
    if any(w in text for w in ("度", "温度", "湿度", "電力", "状態", "確認", "全部", "すべて", "チャンネル", "冷房", "暖房")):
        return None

    turn_on = any(w in text for w in ("つけて", "点けて", "オン", "on", "ON", "起動"))
    turn_off = any(w in text for w in ("消して", "オフ", "off", "OFF", "止めて", "切って"))
    if turn_on == turn_off:
        return None

    devices = _load_switchbot_devices(workdir, base_dir)
    if not devices:
        return None

    low_text = text.lower().replace(" ", "")
    matched = [
        d for d in devices
        if d.get("name") and d["name"].lower().replace(" ", "") in low_text
    ]
    if len(matched) != 1:
        return None

    dev = matched[0]
    sb_bin = workdir / "scripts" / "sb"
    if not sb_bin.exists():
        sb_bin = base_dir / "tools" / "sb"
    if not sb_bin.exists():
        return None

    cmd_name = "turnOn" if turn_on else "turnOff"
    try:
        proc = await asyncio.create_subprocess_exec(
            str(sb_bin),
            "cmd",
            dev["id"],
            cmd_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
        if proc.returncode != 0:
            return None
        res = json.loads(out.decode("utf-8", errors="replace"))
        if res.get("statusCode") not in (100, None):
            return None
    except Exception:
        return None

    plain_verb = "つけた" if turn_on else "消した"
    polite_verb = "つけました" if turn_on else "消しました"
    return f"{dev['name']}を" + _past_end(speaker_id, plain_verb, polite_verb)


async def try_fast_path(
    user_text: str,
    speaker_id: int,
    workdir: Path,
    base_dir: Path,
    timer_ops: dict[str, Any],
) -> Optional[str]:
    norm = _normalize(user_text)
    if not norm:
        return None

    reply = _try_clock(norm, speaker_id)
    if reply:
        return reply

    reply = await _try_timer(norm, speaker_id, timer_ops)
    if reply:
        return reply

    reply = await _try_switchbot(norm, speaker_id, workdir, base_dir)
    if reply:
        return reply

    return None
