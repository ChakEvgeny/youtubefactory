#!/usr/bin/env python3
"""SRT из timed.json: тайминги берутся из смонтированного фильма.

Интонационные теги и пометки голоса в субтитры не попадают. Длинные реплики
режутся на куски по 84 знака, время делится пропорционально длине куска.
"""
from __future__ import annotations
import json, re, sys, textwrap
from pathlib import Path

MAXC = 84


def clean(t: str) -> str:
    t = re.sub(r"\[[^\]]*\]", " ", t or "")          # [pause], [slowly] и прочее
    return re.sub(r"\s+", " ", t).strip()


def ts(x: float) -> str:
    h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def main():
    d = Path(sys.argv[1])
    out = d / (sys.argv[2] if len(sys.argv) > 2 else "subs_en.srt")
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    cues = []
    for s in r:
        t = clean(s.get("narr_plain") or s.get("narr") or "")
        if not t or s.get("tier") == "black":
            continue
        a, b = float(s["t_in"]), float(s["t_out"])
        parts = textwrap.wrap(t, MAXC, break_long_words=False) or [t]
        tot = sum(len(p) for p in parts) or 1
        cur = a
        for p in parts:
            dur = (b - a) * len(p) / tot
            cues.append((cur, cur + dur, p))
            cur += dur
    lines = []
    for i, (a, b, t) in enumerate(cues, 1):
        b = max(b, a + 0.9)
        if i < len(cues):
            b = min(b, cues[i][0] - 0.03)
        body = "\n".join(textwrap.wrap(t, 42, break_long_words=False))
        lines.append(f"{i}\n{ts(a)} --> {ts(b)}\n{body}\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{out.name}: реплик {len(cues)}, до {ts(cues[-1][1])}")


if __name__ == "__main__":
    main()
