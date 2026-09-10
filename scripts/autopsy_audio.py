#!/usr/bin/env python3
"""Format autopsy, часть 3: звук и структура.

Темп речи и паузы — из автосубтитров (vtt); музыка — уровень в паузах речи;
SFX на стыках — всплеск RMS в окне 120 мс у смены кадра; структура —
транскрипт первых 60 с и последних 30 с, цифры в минуту, первый поворот
(Haiku по тексту), главы из описания.
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from pipeline.util import claude_cost, parse_json_block  # noqa: E402


def run(cmd, timeout=900):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ts(s: str) -> float:
    h, m, r = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(r.replace(",", "."))


def parse_vtt(p: Path) -> list[dict]:
    """Слова с таймкодами из авто-VTT (YouTube даёт пословные <c> теги)."""
    words, cur = [], None
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "-->" in line:
            a, b = line.split("-->")[:2]
            cur = (ts(a.strip().split()[0]), ts(b.strip().split()[0]))
            continue
        if cur is None or not line.strip() or line.startswith(("WEBVTT", "Kind", "Language")):
            continue
        # строка вида: prev line words<00:00:01.240><c> new</c><00:00:01.500><c> word</c>
        # YouTube «катит» субтитры: слова до первого inline-таймкода — повтор
        # предыдущей строки, их пропускаем; берём только слова со своим таймкодом.
        parts = re.split(r"<(\d\d:\d\d:\d\d\.\d+)>", line)
        if len(parts) == 1:                      # строка без inline-таймкодов
            for w in re.sub(r"<[^>]+>", "", line).split():
                words.append({"w": w, "t": cur[0]})
            continue
        t = None
        for i, chunk in enumerate(parts):
            if i % 2 == 1:
                t = ts(chunk)
                continue
            if t is None:
                continue                         # хвост предыдущей строки
            for w in re.sub(r"<[^>]+>", "", chunk).split():
                words.append({"w": w, "t": t})
    # монотонность и дедуп
    out, last_t = [], -1.0
    for x in words:
        if x["t"] < last_t - 0.05:
            continue
        if out and out[-1]["w"] == x["w"] and abs(out[-1]["t"] - x["t"]) < 0.05:
            continue
        out.append(x)
        last_t = max(last_t, x["t"])
    return out


def parse_json3(p: Path) -> list[dict]:
    """Пословные таймкоды из json3 (events[].segs[].tOffsetMs) — надёжнее VTT."""
    d = json.loads(p.read_text(encoding="utf-8"))
    words = []
    for e in d.get("events", []) or []:
        t0 = e.get("tStartMs", 0)
        for sg in e.get("segs", []) or []:
            w = (sg.get("utf8") or "").strip()
            if w and w != "\n":
                words.append({"w": w.lstrip(">").strip(), "t": (t0 + sg.get("tOffsetMs", 0)) / 1000})
    return [w for w in words if w["w"]]


def load_words(video: Path) -> list[dict]:
    j = sorted(video.parent.glob("subs*.json3"))
    if j:
        return parse_json3(j[0])
    vtts = sorted(video.parent.glob(video.stem + ".en.vtt")) or sorted(video.parent.glob(video.stem + "*.vtt"))
    return parse_vtt(vtts[0]) if vtts else []


def speech_stats(words: list[dict], dur: float) -> dict:
    if len(words) < 20:
        return {"wpm": None, "pauses_gt07": None, "words": len(words)}
    gaps = [words[i]["t"] - words[i - 1]["t"] for i in range(1, len(words))]
    # у автосубтитров YouTube соседние слова часто делят один таймкод (gap=0),
    # поэтому «время речи» = хронометраж минус длинные паузы, а не сумма зазоров
    long_pause = sum(g - 0.7 for g in gaps if g > 0.7)
    speaking = max(dur - long_pause, 1.0)
    return {"words": len(words), "wpm": round(len(words) / (dur / 60)),
            "wpm_speaking": round(len(words) / (speaking / 60)),
            "pauses_gt07": sum(1 for g in gaps if g > 0.7),
            "pauses_gt07_per_min": round(sum(1 for g in gaps if g > 0.7) / (dur / 60), 1),
            "longest_pause": round(max(gaps), 2)}


def rms_db(p: Path, a: float, d: float, band: str | None = None) -> float:
    af = "volumedetect" if not band else f"{band},volumedetect"
    r = run(["ffmpeg", "-v", "info", "-ss", f"{a:.3f}", "-i", str(p), "-t", f"{d:.3f}", "-af", af, "-f", "null", "-"])
    m = re.findall(r"mean_volume: (-?[\d.]+)", r.stderr)
    return float(m[-1]) if m else -91.0


def music_and_sfx(p: Path, words: list[dict], cuts: list[float], dur: float) -> dict:
    # паузы речи >0.9с — там слышно, есть ли подложка
    gaps = [(words[i - 1]["t"], words[i]["t"]) for i in range(1, len(words)) if words[i]["t"] - words[i - 1]["t"] > 0.9]
    gaps = [g for g in gaps if 5 < g[0] < dur - 5][:12]
    pause_levels = [rms_db(p, a + 0.15, min(b - a - 0.3, 1.5)) for a, b in gaps]
    speech_levels = [rms_db(p, words[i]["t"], 1.0) for i in range(20, len(words), max(len(words) // 10, 1))][:10]
    # SFX на стыках: 120мс у стыка против 400мс до него
    sfx_hits, tested = 0, 0
    for t in cuts[5:][:: max(len(cuts) // 25, 1)][:25]:
        if t < 1 or t > dur - 1:
            continue
        at = rms_db(p, t - 0.03, 0.12)
        before = rms_db(p, t - 0.6, 0.4)
        tested += 1
        if at - before > 4.0:
            sfx_hits += 1
    return {
        "music_in_pauses_db": round(statistics.mean(pause_levels), 1) if pause_levels else None,
        "speech_db": round(statistics.mean(speech_levels), 1) if speech_levels else None,
        "music_constant": bool(pause_levels) and statistics.mean(pause_levels) > -45,
        "sfx_at_cuts_share": round(sfx_hits / tested, 2) if tested else None, "cuts_tested": tested,
    }


def structure(words: list[dict], dur: float, info: dict, client) -> dict:
    text_all = " ".join(w["w"] for w in words)
    first60 = " ".join(w["w"] for w in words if w["t"] <= 60)
    last30 = " ".join(w["w"] for w in words if w["t"] >= dur - 30)
    nums = re.findall(r"\b\d[\d,\.]*\b|\b(?:million|billion|thousand|percent|per cent)\b", text_all, re.I)
    chapters = info.get("chapters") or []
    turn = {}
    if client and len(words) > 50:
        prompt = (f"Транскрипт первых 3 минут ролика:\n{' '.join(w['w'] for w in words if w['t'] <= 180)}\n\n"
                  "Найди ПЕРВЫЙ сюжетный поворот — момент, где история меняет направление "
                  "(«но», неожиданный факт, смена темы с успеха на провал). Верни ТОЛЬКО JSON: "
                  "{\"turn_quote\":\"дословная фраза\",\"why\":\"кратко по-русски\"}")
        try:
            r = client.messages.create(model="claude-haiku-4-5", max_tokens=300,
                                       messages=[{"role": "user", "content": prompt}])
            d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
            q = (d.get("turn_quote") or "").strip()
            # время поворота — первое слово цитаты в транскрипте
            tw = q.split()[:3]
            pos = None
            for i in range(len(words) - 3):
                if [x["w"].strip(".,\"'").lower() for x in words[i:i + 3]] == [t.strip(".,\"'").lower() for t in tw]:
                    pos = words[i]["t"]
                    break
            turn = {"quote": q[:160], "why": d.get("why", ""), "t": round(pos, 1) if pos is not None else None,
                    "cost": claude_cost("claude-haiku-4-5", r.usage)}
        except Exception as e:
            turn = {"error": str(e)[:80]}
    return {"first60": first60[:1200], "last30": last30[:700],
            "numbers_per_min": round(len(nums) / (dur / 60), 1), "numbers_total": len(nums),
            "chapters": len(chapters), "chapter_titles": [c.get("title") for c in chapters][:12],
            "first_turn": turn}


if __name__ == "__main__":
    video = Path(sys.argv[1])
    info = json.loads(video.with_suffix(".info.json").read_text(encoding="utf-8")) if video.with_suffix(".info.json").exists() else {}
    rhythm = json.loads(video.with_suffix(".rhythm.json").read_text(encoding="utf-8")) if video.with_suffix(".rhythm.json").exists() else {}
    words = load_words(video)
    dur = float(info.get("duration") or rhythm.get("duration") or 0)
    import anthropic
    res = {"speech": speech_stats(words, dur),
           "audio": music_and_sfx(video, words, rhythm.get("cuts", []), dur) if words else {},
           "structure": structure(words, dur, info, anthropic.Anthropic())}
    video.with_suffix(".audio.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    s, a, st = res["speech"], res["audio"], res["structure"]
    print(f"{video.name}: речь {s.get('wpm')} сл/мин (в речи {s.get('wpm_speaking')}), пауз>0.7с/мин {s.get('pauses_gt07_per_min')} | "
          f"музыка в паузах {a.get('music_in_pauses_db')} dB ({'постоянно' if a.get('music_constant') else 'нет/тихо'}), "
          f"SFX на стыках {a.get('sfx_at_cuts_share')} | цифр/мин {st['numbers_per_min']}, глав {st['chapters']}, "
          f"поворот на {st['first_turn'].get('t')}с")
