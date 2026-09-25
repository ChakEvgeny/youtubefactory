#!/usr/bin/env python3
"""Длинные реплики в переведённых субтитрах режутся надвое.

Перевод длиннее английского на треть, и реплика, которая в оригинале читалась
двумя строками, в переводе уезжает в три — они закрывают кадр. Текст при этом
не трогается: реплика делится по границе слов, время делится пропорционально
длине кусков.

    python scripts/subs_split.py <папка>/i18n/subs_ru.srt [...]
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

WIDTH, MAXLINES = 42, 2
LIMIT = WIDTH * MAXLINES


def parse(p: Path):
    out = []
    for blk in p.read_text(encoding="utf-8").strip().split("\n\n"):
        L = [x for x in blk.split("\n") if x.strip()]
        if len(L) >= 3:
            a, b = L[1].split(" --> ")
            out.append((a.strip(), b.strip(), " ".join(L[2:])))
    return out


def sec(t: str) -> float:
    h, m, s = t.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def ts(x: float) -> str:
    h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def split(a: float, b: float, text: str):
    if len(textwrap.wrap(text, WIDTH, break_long_words=False)) <= MAXLINES:
        return [(a, b, text)]
    n = max(2, -(-len(text) // LIMIT))          # на сколько кусков резать
    words, parts, cur = text.split(), [], ""
    target = len(text) / n
    for w in words:
        if cur and len(cur) + 1 + len(w) > target and len(parts) < n - 1:
            parts.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        parts.append(cur)
    tot = sum(len(p) for p in parts) or 1
    out, cur_t = [], a
    for p in parts:
        d = (b - a) * len(p) / tot
        out.append((cur_t, cur_t + d, p))
        cur_t += d
    return out


MIN = 0.8


def merge_short(cues):
    """Реплика короче MIN мелькает. Склеиваем её с соседней, если та идёт
    встык и объединённый текст всё ещё помещается в две строки."""
    out = []
    for a, b, t in cues:
        if out and b - a < MIN:
            pa, pb, pt = out[-1]
            if abs(pb - a) < 0.05 and len(textwrap.wrap(f"{pt} {t}", WIDTH,
                                                        break_long_words=False)) <= MAXLINES:
                out[-1] = (pa, b, f"{pt} {t}")
                continue
        out.append((a, b, t))
    # то, что не склеилось назад, пробуем склеить вперёд
    res = []
    i = 0
    while i < len(out):
        a, b, t = out[i]
        if b - a < MIN and i + 1 < len(out):
            na, nb, nt = out[i + 1]
            if abs(b - na) < 0.05 and len(textwrap.wrap(f"{t} {nt}", WIDTH,
                                                        break_long_words=False)) <= MAXLINES:
                res.append((a, nb, f"{t} {nt}")); i += 2; continue
        res.append((a, b, t)); i += 1
    return res


def main() -> None:
    for arg in sys.argv[1:]:
        p = Path(arg)
        cues = []
        for a, b, t in parse(p):
            cues += split(sec(a), sec(b), t)
        cues = merge_short(cues)
        p.write_text("".join(
            f"{i}\n{ts(a)} --> {ts(b)}\n" + "\n".join(textwrap.wrap(t, WIDTH, break_long_words=False) or [t]) + "\n\n"
            for i, (a, b, t) in enumerate(cues, 1)), encoding="utf-8")
        long = sum(1 for _, _, t in cues
                   if len(textwrap.wrap(t, WIDTH, break_long_words=False)) > MAXLINES)
        print(f"  {p.name}: {len(cues)} реплик, в три строки осталось {long}")


if __name__ == "__main__":
    main()
