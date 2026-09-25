#!/usr/bin/env python3
"""Плита и движущийся слой для кадров, где часть картинки обязана стоять.

Зачем: если плитой взять сам кадр целиком, а сверху положить вырезанную
фигуру, то при дыхании фигура уезжает от СВОЕЙ ЖЕ копии на плите и из-за
головы вылезает вторая голова. Поэтому плита обязана быть без того, что
движется: дыра затягивается ближайшим фоном, а слой кладётся с запасом и
накрывает затяжку.

Разрез вертикальный, по пустой стене между мебелью и оконной рамой. Резать
по контуру не выходит: человек, диван, клин пола и вид за стеклом связаны в
одну заливку широкими областями, эрозия их не разнимает.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage


def inked(im: Image.Image, thr: int = 120) -> np.ndarray:
    """Всё, что не залилось с краёв: человек, мебель, вид за стеклом."""
    g = np.asarray(im.convert("L"), np.uint8)
    lab, _ = ndimage.label(~(g < thr))
    H, W = g.shape
    side = int(H * 0.55)            # фигура законно уходит за нижний край
    edge = set(lab[0, :]) | set(lab[:side, 0]) | set(lab[:side, -1])
    edge.discard(0)
    return ndimage.binary_closing(~np.isin(lab, list(edge)), np.ones((7, 7)))


def split(im: Image.Image, seam: float = 0.52, grow: int = 5):
    m = inked(im)
    H, W = m.shape
    m[:, int(seam * W):] = False     # вид за стеклом остаётся на плите
    a = np.asarray(im.convert("RGB")).copy()
    hole = ndimage.binary_dilation(m, np.ones((2 * grow + 5, 2 * grow + 5)))
    idx = ndimage.distance_transform_edt(hole, return_distances=False, return_indices=True)
    plate = Image.fromarray(a[idx[0], idx[1]])
    fig = im.convert("RGBA")
    al = ndimage.binary_dilation(m, np.ones((2 * grow + 1, 2 * grow + 1)))
    fig.putalpha(Image.fromarray((al * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0)))
    return plate, fig, m.mean()
