#!/usr/bin/env python3
"""Перерезка блока по словам из выравнивания ElevenLabs.

Хук режется не по репликам, а по словам: реплика длиннее максимума делится по
границе слова, ближайшей к середине; реплика короче минимума склеивается с более
коротким соседом. Границы берутся из посимвольного выравнивания, а не из оценки
по словам в минуту — на оценке кадры разъезжаются с голосом.

    python scripts/work_recut.py <папка> --block "0 · хук" --align voice/hook_a_align.json
    python scripts/work_recut.py <папка> --block "0 · хук" --apply
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MIN_D, MAX_D = 1.2, 3.5


def words(al: dict) -> list[tuple[float, float, str]]:
    ch = al["characters"]
    st = al["character_start_times_seconds"]
    en = al["character_end_times_seconds"]
    out, buf, s0, e1 = [], "", None, None
    for c, a, b in zip(ch, st, en):
        if c.isspace():
            if buf:
                out.append((s0, e1, buf))
                buf, s0 = "", None
            continue
        if not buf:
            s0 = a
        buf += c
        e1 = b
    if buf:
        out.append((s0, e1, buf))
    return out


def sentences(ws) -> list[tuple[float, float, list]]:
    out, cur = [], []
    for w in ws:
        cur.append(w)
        if w[2].rstrip('"”').endswith((".", "!", "?")):
            out.append((cur[0][0], cur[-1][1], cur))
            cur = []
    if cur:
        out.append((cur[0][0], cur[-1][1], cur))
    return out


def split(seg):
    """делим по границе слова, ближайшей к середине, пока обе части влезают"""
    s0, s1, ws = seg
    if s1 - s0 <= MAX_D or len(ws) < 2:
        return [seg]
    mid = (s0 + s1) / 2
    k = min(range(1, len(ws)), key=lambda i: abs(ws[i][0] - mid))
    a = (s0, ws[k - 1][1], ws[:k])
    b = (ws[k][0], s1, ws[k:])
    return split(a) + split(b)


def merge(segs):
    """короткий кусок прилипает к более короткому соседу"""
    segs = list(segs)
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for i, s in enumerate(segs):
            if s[1] - s[0] >= MIN_D:
                continue
            left = segs[i - 1] if i else None
            right = segs[i + 1] if i + 1 < len(segs) else None
            pick = left if right is None else right if left is None else (
                left if (left[1] - left[0]) <= (right[1] - right[0]) else right)
            j = i - 1 if pick is left else i + 1
            lo, hi = min(i, j), max(i, j)
            a, b = segs[lo], segs[hi]
            segs[lo:hi + 1] = [(a[0], b[1], a[2] + b[2])]
            changed = True
            break
    return segs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--block", required=True)
    ap.add_argument("--align", default="voice/hook_a_align.json")
    ap.add_argument("--apply", action="store_true", help="записать слоты в storyboard.json")
    a = ap.parse_args()

    P = Path(a.dir)
    al = json.loads((P / a.align).read_text(encoding="utf-8"))
    segs = merge([x for s in sentences(words(al)) for x in split(s)])

    sb = json.loads((P / "storyboard.json").read_text(encoding="utf-8"))
    old = sorted([s for s in sb if s.get("block") == a.block], key=lambda s: s["t_in"])

    print(f"было {len(old)} кадров, стало {len(segs)}")
    plan = []
    for i, (s0, s1, ws) in enumerate(segs):
        txt = " ".join(w[2] for w in ws)
        # слот наследует кадр, чей старый интервал перекрывается с новым сильнее всех
        best, bo = None, 0.0
        for o in old:
            ov = min(s1, o["t_in"] + o["dur"]) - max(s0, o["t_in"])
            if ov > bo:
                best, bo = o, ov
        plan.append({"seg": (round(s0, 2), round(s1, 2)), "text": txt, "from": best})
        mark = "" if best else "  ← НОВЫЙ КАДР"
        print(f"  {s0:5.2f}–{s1:5.2f} {s1-s0:4.2f}с  "
              f"{('кадр ' + str(best['id'])) if best else 'нет':<9} {txt[:52]}{mark}")

    # кадр можно наследовать только один раз: второй слот той же реплики — новый
    used = set()
    for p in plan:
        b = p["from"]
        if b and b["id"] in used:
            p["from"] = None
        elif b:
            used.add(b["id"])
    need = [p for p in plan if not p["from"]]
    print(f"\nнужно дорисовать кадров: {len(need)}")
    for p in need:
        print(f"  {p['seg'][0]:5.2f}–{p['seg'][1]:5.2f}  {p['text'][:60]}")

    if not a.apply:
        print("\n(пробный прогон; --apply запишет слоты)")
        return

    rest = [s for s in sb if s.get("block") != a.block]
    nid = max(s["id"] for s in sb) + 1
    out = []
    for p in plan:
        s0, s1 = p["seg"]
        if p["from"]:
            s = dict(p["from"])
        else:
            s = {"id": nid, "kind": "insert", "visual": "", "chip": None}
            nid += 1
        s.update(t_in=s0, dur=round(s1 - s0, 2), narr=p["text"], block=a.block)
        out.append(s)
    for s in old:
        if s["id"] not in {x["id"] for x in out}:
            s = dict(s)
            s.update(block="запас", t_in=0.0, dur=0.0, narr="")
            rest.append(s)
    allsh = out + rest
    allsh.sort(key=lambda s: (s["block"] != a.block, s["block"] == "запас", s["t_in"]))
    (P / "storyboard.json").write_text(json.dumps(allsh, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print("\nслоты записаны; кадрам без картинки проставь visual и запусти work_shots.py")


if __name__ == "__main__":
    main()
