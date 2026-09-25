#!/usr/bin/env python3
"""Контактный лист раскадровки: кадр + его описание под ним.

Проверять надо не «красиво ли», а то ли нарисовано, что заказано, — поэтому
подпись под кадром обязательна (правило канала). Собирается одной командой,
чтобы лист не отставал от кадров: дважды выходило так, что правки внесены, а на
проверку уходила вчерашняя сетка.

    python scripts/qc_grid.py <папка ролика>
"""
from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--per", type=int, default=12)
    ap.add_argument("--cols", type=int, default=4)
    a = ap.parse_args()
    D = Path(a.dir)
    # раскадровка называется по-разному: у объяснялок timed.json, у Terms — storyboard.json
    src = next((D / n for n in ("storyboard.json", "timed.json") if (D / n).exists()), None)
    if src is None:
        raise SystemExit("нет ни storyboard.json, ни timed.json")
    # схемы тоже показываем: их фон — обычный кадр, и без них в сетке дыра
    shots = [s for s in json.loads(src.read_text(encoding="utf-8"))
             if s.get("kind") in ("scene", "diagram")]
    # кадры лежат либо в stills/sNNN.jpg, либо в scenes/NNN.jpg
    def frame(s):
        i = s.get("bg_id", s["id"])
        for p in (D / "stills" / f"s{i:03d}.jpg", D / "scenes" / f"{i:03d}.jpg"):
            if p.exists():
                return p
        return None

    for old in D.glob("qc_*.jpg"):
        old.unlink()
    f = ImageFont.truetype(FONT, 14)
    fb = ImageFont.truetype(BOLD, 16)
    tw, th, pad, texth = 380, 214, 10, 56
    miss = []
    for page in range((len(shots) + a.per - 1) // a.per):
        part = shots[page * a.per:(page + 1) * a.per]
        rows = (len(part) + a.cols - 1) // a.cols
        im = Image.new("RGB", (a.cols * (tw + pad) + pad, rows * (th + texth + pad) + pad), (16, 16, 18))
        d = ImageDraw.Draw(im)
        for k, s in enumerate(part):
            x = pad + (k % a.cols) * (tw + pad)
            y = pad + (k // a.cols) * (th + texth + pad)
            p = frame(s)
            if p:
                im.paste(Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
            else:
                d.rectangle([x, y, x + tw, y + th], fill=(40, 40, 44))
                d.text((x + 10, y + 10), "НЕТ КАДРА", font=fb, fill=(200, 120, 120))
                miss.append(s["id"])
            mark = " · СХЕМА" if s.get("kind") == "diagram" else ""
            d.text((x + 4, y + th + 3), f"{s['id']} · shot {s.get('tag', '')}{mark}",
                   font=fb, fill=(235, 235, 235))
            ty = y + th + 21
            cap = s.get("visual") or ("схема поверх кадра: " + str((s.get("diagram") or {}).get("title") or
                                      (s.get("diagram") or {}).get("kind", "")))
            for ln in textwrap.wrap(cap, 56)[:2]:
                d.text((x + 4, ty), ln, font=f, fill=(185, 185, 185))
                ty += 16
        im.save(D / f"qc_{page + 1:02d}.jpg", quality=84)
    n = (len(shots) + a.per - 1) // a.per
    print(f"{D.name}: листов {n}, кадров {len(shots)}" + (f", НЕТ КАДРА: {miss}" if miss else ""))


if __name__ == "__main__":
    main()
