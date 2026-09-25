#!/usr/bin/env python3
"""Вырезать ведущего из проверенной базы и подложить новый фон.

Пять попыток перенести рот в новый рисунок провалились: любой новый рисунок
приносит свой тон кожи и бороды. Здесь наоборот — лицо остаётся ровно то, на
котором липсинк уже работает, меняется только фон за ним.

Маска строится ЗАЛИВКОЙ ОТ КРАЁВ до контура, а не по цвету: кожа ведущего это
тот же кремовый тон, что и бумага фона, и цветовая маска пробивает лицо
насквозь — это уже ловилось на баннере канала.

    python scripts/host_cutout.py <папка> --base anim/desk_refs/desk3.jpg --mask
    python scripts/host_cutout.py <папка> --base ... --bg stills/s8011.jpg --out anim/bases/towers.jpg
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage


def figure_mask(im: Image.Image, thr: int = 120) -> np.ndarray:
    """Фигура = то, что не залилось с краёв, и связано с центром нижней половины."""
    g = np.asarray(im.convert("L"), dtype=np.uint8)
    ink = g < thr                      # контуры
    free = ~ink
    lab, n = ndimage.label(free)
    H, W = g.shape
    # фон засеваем сверху и с боков, но НЕ снизу: фигура законно уходит за
    # нижний край, и если считать его фоном, футболка проваливается в дыру
    side = int(H * 0.55)
    edge = set(lab[0, :]) | set(lab[:side, 0]) | set(lab[:side, -1])
    edge.discard(0)
    bg = np.isin(lab, list(edge))
    fig = ~bg                           # всё, что не дотянулось до края
    fig = ndimage.binary_closing(fig, np.ones((7, 7)))
    lab2, n2 = ndimage.label(fig)
    if not n2:
        raise SystemExit("фигура не найдена")
    # берём компоненту, накрывающую центр нижней половины — там торс
    cy, cx = int(H * 0.72), W // 2
    k = lab2[cy, cx]
    if k == 0:
        sizes = ndimage.sum(fig, lab2, range(1, n2 + 1))
        k = int(np.argmax(sizes)) + 1
    m = (lab2 == k)
    m = ndimage.binary_fill_holes(m)
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--base", required=True)
    ap.add_argument("--bg", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--mask", action="store_true", help="только показать маску")
    ap.add_argument("--cut", default="", help="сохранить одну фигуру с альфой в этот файл")
    a = ap.parse_args()
    P = Path(a.dir)
    base = Image.open(P / a.base).convert("RGB")
    m = figure_mask(base)
    alpha = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))
    if a.mask:
        chk = Image.new("RGB", base.size, (228, 83, 58))
        chk.paste(base, (0, 0), alpha)
        out = P / "_cutout_check.jpg"
        chk.save(out, quality=92)
        print(f"{out}  доля фигуры {m.mean()*100:.0f}%")
        return
    if a.cut:
        fig = base.convert("RGBA")
        fig.putalpha(alpha)
        o = P / a.cut
        o.parent.mkdir(parents=True, exist_ok=True)
        fig.save(o)
        print(f"{o}")
        return
    bg = Image.open(P / a.bg).convert("RGB").resize(base.size)
    bg.paste(base, (0, 0), alpha)
    o = P / a.out
    o.parent.mkdir(parents=True, exist_ok=True)
    bg.save(o, quality=94)
    print(f"{o}")


if __name__ == "__main__":
    main()
