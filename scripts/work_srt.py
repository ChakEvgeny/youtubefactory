#!/usr/bin/env python3
"""SRT под СОБРАННЫЙ ролик Terms of Employment.

`make_srt.py` берёт времена прямо из раскадровки, и для этого канала это неверно:
утверждённое начало собрано отдельно и на неускоренной дорожке, поэтому хук в
фильме длиннее, чем в раскадровке, а всё остальное сдвинуто на длину начала.
Здесь оба преобразования считаются из фактических длин файлов, а не задаются
руками.

    python scripts/work_srt.py <папка> --prefix cuts/first30.mp4 --out subs_en.srt
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import textwrap
from pathlib import Path

MAXC = 84


def dur(p) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def clean(t: str) -> str:
    t = re.sub(r"\[[^\]]*\]", " ", t or "")
    return re.sub(r"\s+", " ", t).strip()


def ts(x: float) -> str:
    h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--prefix", default="",
                    help="готовое начало отдельным файлом (первый ролик канала)")
    ap.add_argument("--intro", default="",
                    help="заставка, вставленная ПОСЛЕ хука: файл или секунды")
    ap.add_argument("--hook-audio", default="voice/hook_a.mp3")
    ap.add_argument("--out", default="subs_en.srt")
    a = ap.parse_args()
    P = Path(a.dir)
    tm = json.loads((P / "timed.json").read_text(encoding="utf-8"))

    def is_hook(b: str) -> bool:
        b = str(b).strip().lower()
        return b.startswith("0 ") or "хук" in b or "hook" in b

    hook = sorted([s for s in tm if is_hook(s["block"])], key=lambda x: x["t_in"])
    rest = sorted([s for s in tm if not is_hook(s["block"])], key=lambda x: x["t_in"])
    if not hook:
        raise SystemExit("блок хука не найден")

    if a.prefix:
        # первый ролик канала: утверждённое начало собрано отдельным файлом и на
        # неускоренной дорожке, поэтому хук растягиваем в отношении длин
        board = max(s["t_in"] + s["dur"] for s in hook)
        k = dur(P / a.hook_audio) / board
        off = dur(P / a.prefix) - rest[0]["t_in"]
        print(f"хук: раскадровка {board:.2f}с → фильм {board*k:.2f}с (×{k:.4f}); "
              f"остальное сдвиг {off:+.2f}с")
    else:
        # обычный случай: времена раскадровки и есть времена фильма, а всё после
        # хука сдвинуто ровно на длину вставленной заставки
        k = 1.0
        try:
            off = float(a.intro)
        except ValueError:
            off = dur(P / a.intro) if a.intro else 0.0
        print(f"хук без изменений; заставка {off:.2f}с, сдвиг всего после неё {off:+.2f}с")

    cues = []
    for s in hook + rest:
        t = clean(s.get("narr_plain") or s.get("narr") or "")
        if not t:
            continue
        if is_hook(s["block"]):
            a0, b0 = s["t_in"] * k, (s["t_in"] + s["dur"]) * k
        else:
            a0, b0 = s["t_in"] + off, s["t_in"] + s["dur"] + off
        parts = textwrap.wrap(t, MAXC, break_long_words=False) or [t]
        tot = sum(len(p) for p in parts) or 1
        cur = a0
        for p in parts:
            d = (b0 - a0) * len(p) / tot
            cues.append((cur, cur + d, p))
            cur += d
    # реплики идут встык, поэтому соседние строки не наезжают; но если кадр
    # немой, между ними образуется дыра — её оставляем, так читается легче
    out = P / a.out
    out.write_text("".join(
        f"{i}\n{ts(x)} --> {ts(y)}\n{txt}\n\n" for i, (x, y, txt) in enumerate(cues, 1)
    ), encoding="utf-8")
    print(f"{out}  {len(cues)} реплик, последняя кончается на {cues[-1][1]:.2f}с")


if __name__ == "__main__":
    main()
