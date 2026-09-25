#!/usr/bin/env python3
"""«Кипящая» линия из одного рисунка: микродеформация сетки на каждый кадр.

Почему не генерацией: попытка попросить модель «перерисовать тот же кадр заново»
даёт восемь разных картинок — меняются цвет одежды, высота плашки, положение руки.
Идентичность не держится. Деформация одного утверждённого рисунка держит её
стопроцентно, потому что рисунок один.

  python scripts/boil.py <кадр.jpg> <папка> --frames 8 --amp 2.5
"""
from __future__ import annotations
import argparse, random
from pathlib import Path
from PIL import Image


def warp(im: Image.Image, seed: int, amp: float, cells: int = 10) -> Image.Image:
    """Сетка cells×cells, каждый узел дрожит на несколько пикселей."""
    rnd = random.Random(seed)
    W, H = im.size
    cw, ch = W / cells, H / cells
    mesh = []
    off = {}
    for gy in range(cells + 1):
        for gx in range(cells + 1):
            # края не дёргаем, иначе вылезает кромка
            k = 0.0 if (gx in (0, cells) or gy in (0, cells)) else 1.0
            off[(gx, gy)] = (rnd.uniform(-amp, amp) * k, rnd.uniform(-amp, amp) * k)
    for gy in range(cells):
        for gx in range(cells):
            x0, y0, x1, y1 = gx * cw, gy * ch, (gx + 1) * cw, (gy + 1) * ch
            p = [off[(gx, gy)], off[(gx + 1, gy)], off[(gx + 1, gy + 1)], off[(gx, gy + 1)]]
            quad = (x0 + p[0][0], y0 + p[0][1], x0 + p[3][0], y1 + p[3][1],
                    x1 + p[2][0], y1 + p[2][1], x1 + p[1][0], y0 + p[1][1])
            mesh.append(((int(x0), int(y0), int(x1), int(y1)), quad))
    return im.transform(im.size, Image.MESH, mesh, Image.BILINEAR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--amp", type=float, default=2.5, help="амплитуда дрожания, px")
    a = ap.parse_args()
    im = Image.open(a.src).convert("RGB")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for i in range(a.frames):
        warp(im, 1000 + i, a.amp).save(out / f"b{i:02d}.jpg", quality=94)
    print(f"{a.frames} кадров кипения → {out}")


if __name__ == "__main__":
    main()
