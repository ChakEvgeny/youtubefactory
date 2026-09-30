#!/usr/bin/env python3
"""Реплики ведущего — отдельными вставками, а не вырезкой из общей дорожки.

Раньше реплика жила внутри блока, ускоренного до 1.2: рот частил, а на стыке
перетекание открывало уже говорящее лицо за 0.3 с до первого слова. Здесь
вставка — самостоятельный кусок: своя озвучка на нормальной скорости, своя
тишина по краям (перетекание уходит в неё), своё выравнивание. Липсинк внутри
вставки разъехаться не может, потому что звук и картинка сделаны из одного файла.

Основную дорожку переозвучивать не нужно: реплики просто перестают из неё браться.

    python scripts/work_inserts.py <папка>            # все вставки
    python scripts/work_inserts.py <папка> --only 904
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from pipeline import costs
from scripts.voice_blocks import say  # noqa: E402

HEAD, TAIL = 0.35, 0.45   # HEAD ≥ половины перетекания (0.3), иначе рот стартует раньше слова


def dur_of(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--only", default="")
    ap.add_argument("--model", default="eleven_v4")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="темп вставки; звук растягивается atempo после синтеза")
    # voice_blocks.py озвучивает ВСЕ реплики с текстом, включая реплики ведущего,
    # и перебивает им audio/a_off. Если основную дорожку переозвучили после
    # вставок, привязку надо вернуть — но без нового синтеза, иначе собранные
    # марионетки перестают совпадать со звуком, из которого сделаны.
    ap.add_argument("--rebind", action="store_true",
                    help="вернуть привязку к готовым voice/ins_*.mp3 без обращения к API")
    a = ap.parse_args()
    P = Path(a.dir)
    key = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY")
    vid = json.loads((P / "cast.json").read_text(encoding="utf-8"))["narrator"]["id"]
    tm = json.loads((P / "timed.json").read_text(encoding="utf-8"))
    only = {int(x) for x in a.only.split(",") if x.strip().isdigit()}
    her = [s for s in tm if s.get("kind") == "hero" and s["id"] != 91
           and (not only or s["id"] in only)]
    (P / "voice").mkdir(exist_ok=True)
    chars = 0
    for s in sorted(her, key=lambda x: x["t_in"]):
        text = (s.get("narr") or "").strip()
        out = P / "voice" / f"ins_{s['id']}.mp3"
        if a.rebind:
            if not out.exists():
                print(f"  {s['id']}: нет {out.name}, нужна озвучка"); continue
            d = dur_of(out)
            # звук уже ускорен при синтезе — перезаписывать speed единицей нельзя,
            # иначе метаданные врут о темпе вставки
            s.update(audio=f"voice/ins_{s['id']}.mp3", align=f"voice/ins_{s['id']}.json",
                     a_off=0.0, a_end=round(d, 3), dur=round(d, 3),
                     speed=s.get("speed", 1.0))
            print(f"  {s['id']:>4} {d:5.2f}с привязан заново")
            continue
        raw = P / "voice" / f"ins_{s['id']}_raw.mp3"
        al = say(key, vid, text, raw, model=a.model)
        if al is None:
            print(f"  {s['id']}: озвучка не вышла"); continue
        chars += len(text)
        # Скорость даём растяжкой: у eleven_v4 родной speed не работает.
        # Тишина по краям добавляется ПОСЛЕ ускорения, иначе ускорится и она.
        tempo = "" if abs(a.speed - 1.0) < 1e-6 else f"atempo={a.speed},"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw),
                        "-af", f"{tempo}adelay={int(HEAD*1000)}:all=1,apad=pad_dur={TAIL}",
                        "-c:a", "libmp3lame", "-b:a", "192k", str(out)], check=True)
        raw.unlink()
        # выравнивание тоже сжимается во столько же раз, иначе липсинк разъедется
        al["character_start_times_seconds"] = [x / a.speed + HEAD for x in al["character_start_times_seconds"]]
        al["character_end_times_seconds"] = [x / a.speed + HEAD for x in al["character_end_times_seconds"]]
        (P / "voice" / f"ins_{s['id']}.json").write_text(json.dumps(al), encoding="utf-8")
        d = dur_of(out)
        s.update(audio=f"voice/ins_{s['id']}.mp3", align=f"voice/ins_{s['id']}.json",
                 a_off=0.0, dur=round(d, 3), speed=a.speed)
        print(f"  {s['id']:>4} {d:5.2f}с (было {s.get('dur_old', 0) or 0:.2f}) {text[:46]}")
    # шоты идут встык, поэтому после смены длин пересчитываем начала подряд
    rest = sorted([x for x in tm if not str(x["block"]).startswith("0 ")], key=lambda x: x["t_in"])
    t = rest[0]["t_in"]
    for s in rest:
        s["t_in"] = round(t, 3); t += s["dur"]
    (P / "timed.json").write_text(json.dumps(tm, ensure_ascii=False, indent=1), encoding="utf-8")
    if chars:
        costs.log("work", "voice", "eleven_v3", chars / 1000 * 0.30, len(her), "вставки ведущего")
    print(f"готово, {len(her)} вставок, конец фильма {t:.2f} с")


if __name__ == "__main__":
    main()
