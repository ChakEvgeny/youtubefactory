#!/usr/bin/env python3
"""Типографический кадр канала: текст как самостоятельный кадр, а не подпись.

Рисуется кодом, а не моделью: нейросеть не умеет буквы, а палитра канала
жёсткая. Фон — navy, текст — бумага, выделенное слово — red.

  python scripts/type_card.py <файл.jpg> "NO WARNING." "NO REASON." --accent 1
"""
from __future__ import annotations
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

NAVY, OCHRE, RED, PAPER = (0x1B, 0x2A, 0x5E), (0xC8, 0x9A, 0x3C), (0xE4, 0x53, 0x3A), (0xF2, 0xEC, 0xE0)
FONTS = Path.home() / ".fonts"
W, H = 1920, 1080


def fit(path, text, max_w, start):
    size = start
    while size > 16:
        f = ImageFont.truetype(str(path), size)
        if f.getbbox(text)[2] - f.getbbox(text)[0] <= max_w:
            return f
        size -= 4
    return ImageFont.truetype(str(path), 16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("lines", nargs="+")
    ap.add_argument("--accent", type=int, default=-1, help="номер строки красным, с нуля")
    ap.add_argument("--bg", default="navy", choices=["navy", "paper"])
    a = ap.parse_args()

    bg = NAVY if a.bg == "navy" else PAPER
    fg = PAPER if a.bg == "navy" else NAVY
    im = Image.new("RGB", (W, H), bg)
    # зерно бумаги, чтобы кадр не выпадал из ризографа
    import random
    random.seed(7); px = im.load()
    for _ in range(W * H // 60):
        x, y = random.randrange(W), random.randrange(H)
        r, g, b = px[x, y]
        d = random.randint(-9, 9)
        px[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))
    d = ImageDraw.Draw(im)
    maxw = int(W * 0.80)
    f = min((fit(FONTS / "ArchivoBlack.ttf", t, maxw, 260) for t in a.lines), key=lambda x: x.size)
    lh = f.size * 1.16
    total = lh * len(a.lines)
    y = (H - total) / 2
    for i, t in enumerate(a.lines):
        col = RED if i == a.accent else fg
        w = f.getbbox(t)[2] - f.getbbox(t)[0]
        d.text(((W - w) / 2, y), t, font=f, fill=col)
        y += lh
    d.rectangle([0, H - 96, W, H], fill=OCHRE if a.bg == "navy" else NAVY)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    im.save(a.out, quality=94)
    print(f"{a.out}  кегль {f.size} px")


if __name__ == "__main__":
    main()
