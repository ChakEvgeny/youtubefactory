#!/usr/bin/env python3
"""Тайминг появления строк карточки — из посимвольного выравнивания озвучки.

Карточка обязана двигаться по голосу: строка, ступень или столбик появляются
тогда, когда их произносят. Без этого зритель двадцать секунд смотрит на
статичную таблицу. Здесь для каждой карточки ищутся её опорные фразы в реплике
и переводятся в секунды от начала карточки.

    python scripts/work_beats.py <папка>
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# опорные фразы по карточкам: по одной на строку, ступень или столбик
CUES = {
 910:  ["no notice", "no written explanation", "no process"],
 924:  ["six months", "to twelve", "eighteen"],
 935:  ["1999", "April 2012", "January 2027"],
 944:  ["Federally regulated", "Ontario"],
 947:  ["rough ceiling", "twenty-four months"],
 959:  ["Up to a year", "One to three years", "Three to five", "More than five", "forty-five"],
 981:  ["before you sign", "not after"],
 1012: ["One.", "notice does the contract", "statutory floor"],
 1013: ["One.", "notice does the contract", "Two."],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    a = ap.parse_args()
    P = Path(a.dir)
    tm = json.loads((P / "timed.json").read_text(encoding="utf-8"))
    by = {s["id"]: s for s in tm}

    cache: dict[str, dict] = {}
    done = 0
    for sid, cues in CUES.items():
        s = by.get(sid)
        if not s or not s.get("audio"):
            print(f"  ! карточка {sid}: нет звука")
            continue
        blk = Path(s["audio"]).stem                      # blockNN
        if blk not in cache:
            cache[blk] = json.loads((P / "voice" / f"{blk}.json").read_text(encoding="utf-8"))
        al = cache[blk]
        ch, st = al["characters"], al["character_start_times_seconds"]
        text = "".join(ch)
        narr = (s.get("narr") or "").strip()
        base = text.find(narr[:40])
        if base < 0:
            print(f"  ! карточка {sid}: реплика не найдена в блоке")
            continue
        # ищем только внутри собственной реплики шота и без учёта регистра:
        # по всему блоку фраза находится в другом месте и метка уезжает за карточку
        span_lo, span_hi = base, base + len(narr)
        low = text.lower()
        beats, pos = [], span_lo
        for cue in cues:
            k = low.find(cue.lower(), pos, span_hi)
            if k < 0:
                k = low.find(cue.lower(), span_lo, span_hi)
            if k < 0:
                beats.append(round(beats[-1] + 0.8, 2) if beats else 0.0)
            else:
                beats.append(round(min(max(st[k] - st[base], 0.0), s["dur"] - 0.2), 2))
                pos = k + len(cue)
        s.setdefault("card", {})["beats"] = beats
        # длина карточки = длина её реплики, а не выдуманное число
        s["card"]["seconds"] = round(s["dur"], 2)
        done += 1
        print(f"  {sid}: {beats}  длина {s['dur']:.1f} с")
    (P / "timed.json").write_text(json.dumps(tm, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"карточек с таймингом: {done}")


if __name__ == "__main__":
    main()
