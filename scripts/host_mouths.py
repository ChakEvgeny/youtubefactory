#!/usr/bin/env python3
"""Артикуляции рисуются, а не генерируются.

Четыре попытки делать рты генерацией вариантов того же кадра провалились
одинаково: модель перерисовывает лицо целиком, тон кожи и бороды в накладке
отличается от базы, и на стыке появляется грязное кольцо. Разница, эллипс с
растушёвкой, сплошная накладка — всё упирается в это.

Здесь шесть форм рта рисуются плоской заливкой в красках канала. Прозрачна
ровно форма рта, поэтому ореолу взяться неоткуда, а цвет совпадает по
определению.

    python scripts/host_mouths.py <папка> --name desk2 --box 0.42,0.47,0.54,0.59
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

NAVY = (0x1B, 0x2A, 0x5E)
PAPER = (0xF2, 0xEC, 0xE0)


def draw(i: int, w: int, h: int) -> Image.Image:
    """v0,v1 сомкнут · v2 узкая щель · v3 широко открыт · v4 круглое О · v5 оскал"""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = w / 2, h / 2
    lw = max(2, int(h * 0.055))
    if i <= 1:
        return im                                # сомкнутый рот уже нарисован на базе
    geom = {2: (0.26, 0.09), 3: (0.24, 0.26), 4: (0.13, 0.17), 5: (0.30, 0.13)}[i]
    rx, ry = w * geom[0], h * geom[1]
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=NAVY + (255,))
    if i in (2, 3, 5):                            # полоска зубов по верхней кромке
        th = ry * 0.42
        d.ellipse([cx - rx * 0.86, cy - ry * 0.98, cx + rx * 0.86, cy - ry + th * 2],
                  fill=PAPER + (255,))
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=NAVY + (255,), width=lw)
    return im


def snap(base: Image.Image, box: list[float]) -> list[float]:
    """Подтянуть прямоугольник к настоящей линии рта внутри него.

    Рука ставит рамку примерно, и нарисованный рот садится выше родного —
    получаются два рта. Здесь внутри уже верной области ищется самая тёмная
    короткая горизонталь: это и есть линия губ базы."""
    W, H = base.size
    x0, y0, x1, y1 = [int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)]
    pad = int((y1 - y0) * 0.6)
    y0s, y1s = max(0, y0 - pad), min(H, y1 + pad)
    g = np.asarray(base.convert("L").crop((x0, y0s, x1, y1s)), dtype=float)
    dark = (g < 110).mean(axis=1)
    if dark.max() < 0.08:
        return box
    my = int(np.argmax(dark)) + y0s
    h = y1 - y0
    return [box[0], max(0, my - h * 0.5) / H, box[2], min(H, my + h * 0.5) / H]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--name", required=True)
    ap.add_argument("--box", required=True, help="x0,y0,x1,y1 долями кадра")
    ap.add_argument("--frame", default="", help="кадр базы, чтобы подтянуть рамку")
    ap.add_argument("--size", type=int, default=420, help="ширина накладки в пикселях")
    a = ap.parse_args()
    P = Path(a.dir)
    box = [float(x) for x in a.box.split(",")]
    if a.frame:
        box = snap(Image.open(P / a.frame).convert("RGB"), box)
        print(f"рамка подтянута к линии губ: {[round(v, 3) for v in box]}")
    A = P / "anim"
    vdir = A / f"visemes{a.name}"
    vdir.mkdir(parents=True, exist_ok=True)
    w = a.size
    h = int(w * (box[3] - box[1]) / (box[2] - box[0]))
    for i in range(6):
        m = draw(i, w, h)
        m = m.filter(ImageFilter.GaussianBlur(0.6))   # мягкий край, как у печати
        m.save(vdir / f"v{i}.png")
    (A / f"{a.name}_patch.json").write_text(json.dumps({"patch": box}), encoding="utf-8")
    print(f"{vdir}  накладка {w}x{h}, шесть форм нарисованы")


if __name__ == "__main__":
    main()
