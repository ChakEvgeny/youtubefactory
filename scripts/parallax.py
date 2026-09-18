#!/usr/bin/env python3
"""2.5D-облёт фотографии послойно.

Кадр режется на несколько планов по глубине. Каждый план сдвигается со своей
скоростью и накладывается от дальнего к ближнему. Дыры, которые открываются
за ближними объектами, дорисовываются растяжкой фона — иначе на их месте
получается размазня, как при попиксельном сдвиге.
"""
from __future__ import annotations
import argparse, subprocess, tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

W, H, FPS = 1280, 720, 24
_PIPE, _CACHE = {}, {}


def depth(img: Image.Image, key: str = "") -> np.ndarray:
    if key and key in _CACHE:
        return _CACHE[key]
    if "d" not in _PIPE:
        from transformers import pipeline
        _PIPE["d"] = pipeline("depth-estimation",
                              model="depth-anything/Depth-Anything-V2-Small-hf")
    out = _PIPE["d"](img)["depth"].resize((W, H))
    a = np.asarray(out.filter(ImageFilter.GaussianBlur(3)), dtype=np.float32)
    a = (a - a.min()) / max(a.max() - a.min(), 1e-6)
    if key:
        _CACHE[key] = a
    return a


def _blur(a: np.ndarray, r: float) -> np.ndarray:
    if a.ndim == 2:
        return np.asarray(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
                          .filter(ImageFilter.GaussianBlur(r)), dtype=np.float32)
    return np.asarray(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
                      .filter(ImageFilter.GaussianBlur(r)), dtype=np.float32)


def _shrink(mask: np.ndarray, px: int) -> np.ndarray:
    """Убрать краевые пиксели маски: на границе объекта цвет уже загрязнён им."""
    m = _blur(mask.astype(np.float32) * 255, px) / 255.0
    return m > 0.92


def _grow(mask: np.ndarray, px: int) -> np.ndarray:
    """Расширить маску наружу."""
    m = _blur(mask.astype(np.float32) * 255, px) / 255.0
    return m > 0.02


def inpaint(rgb: np.ndarray, known: np.ndarray, iters: int = 40, rad: float = 10.0) -> np.ndarray:
    """Заливка дыры разрастанием от достоверных краёв.

    На каждом шаге берём размытие уже известного и принимаем только те пиксели,
    где известного набралось достаточно. Так фон вползает в дыру слоями и
    нигде не делится на почти ноль, из-за чего раньше вылетали белые пятна.
    """
    m = known.astype(np.float32)
    img = rgb * m[..., None]
    for _ in range(iters):
        if m.min() > 0.5:
            break
        bi = _blur(img, rad)
        bm = _blur(m * 255.0, rad) / 255.0
        ok = bm > 0.06
        fill = bi / np.maximum(bm, 0.06)[..., None]
        take = (~(m > 0.5)) & ok
        img = np.where(take[..., None], np.clip(fill, 0, 255), img)
        m = np.maximum(m, take.astype(np.float32))
    if m.min() <= 0.5:                       # остатки закрываем средним по кадру
        img = np.where((m > 0.5)[..., None], img, rgb.mean(axis=(0, 1)))
    return img


def build_layers(src: np.ndarray, d: np.ndarray, n: int = 2, fg_share: float = 0.22):
    """Два плана вместо нарезки по квантилям.

    Фон — вся картинка, из которой вырезана только ближняя фигура: дыра
    небольшая и со всех сторон окружена настоящим фоном, поэтому заливка
    получается правдоподобной. Раньше дальним планом было небо, и заливка
    растягивала его белым на весь кадр.
    """
    def pick(share: float):
        """Компактный ближний объект при данном пороге глубины, иначе None."""
        nr = d >= float(np.quantile(d, 1.0 - share))
        try:
            from scipy import ndimage
        except Exception:
            return None
        thin = _shrink(nr, 3)                       # рвём перемычки вроде сапог на земле
        lab, k = ndimage.label(thin)
        ids = []
        for i in range(1, k + 1):
            ys, xs = np.where(lab == i)
            if xs.size < 400:
                continue
            if (xs.max() - xs.min()) > 0.62 * nr.shape[1]:
                continue                            # пласт земли или неба
            if (ys.max() - ys.min()) < 40:
                continue
            ids.append(i)
        if not ids:
            return None
        return _grow(np.isin(lab, ids), 4) & nr

    near = None
    for share in (fg_share, 0.35, 0.5, 0.65):
        near = pick(share)
        if near is not None and near.sum() > 2000:
            break
        near = None
    if near is None:                                # выраженного ближнего плана нет
        a1 = np.ones_like(d, dtype=np.float32)
        return [(src * a1[..., None], a1[..., None], 0.15),
                (src * 0, np.zeros_like(d)[..., None], 1.0)]

    keep = ~_grow(near, 14)
    bg = inpaint(src, keep)
    bg_a = np.ones_like(d, dtype=np.float32)

    core = _shrink(near, 2)
    fa = _blur(core.astype(np.float32) * 255, 2) / 255.0
    fg = src * fa[..., None]

    layers = [(bg * bg_a[..., None], bg_a[..., None], 0.15),
              (fg, fa[..., None], 1.0)]
    if n >= 3:                                   # необязательный средний план
        mid = (d >= float(np.quantile(d, 0.45))) & (~near)
        mc = _shrink(mid, 2)
        ma = _blur(mc.astype(np.float32) * 255, 2) / 255.0
        layers.insert(1, (src * ma[..., None], ma[..., None], 0.5))
    return layers


def shift(img: np.ndarray, dx: float, dy: float, zoom: float) -> np.ndarray:
    h, w = img.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2.0, h / 2.0
    sx = cx + (xs - cx) / zoom - dx
    sy = cy + (ys - cy) / zoom - dy
    sx = np.clip(sx, 0, w - 1); sy = np.clip(sy, 0, h - 1)
    x0 = np.floor(sx).astype(np.int32); y0 = np.floor(sy).astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1); y1 = np.minimum(y0 + 1, h - 1)
    fx = (sx - x0)[..., None]; fy = (sy - y0)[..., None]
    if img.ndim == 2:
        img = img[..., None]
    a = img[y0, x0] * (1 - fx) + img[y0, x1] * fx
    b = img[y1, x0] * (1 - fx) + img[y1, x1] * fx
    return a * (1 - fy) + b * fy


def snow(t, seed=7, n=170):
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0, W, n); ys = rng.uniform(0, H, n)
    sp = rng.uniform(20, 60, n); dr = rng.uniform(-10, 10, n); sz = rng.uniform(0.8, 2.0, n)
    lay = np.zeros((H, W), dtype=np.float32)
    for i in range(n):
        y = int((ys[i] + sp[i] * t) % H); x = int((xs[i] + dr[i] * t) % W); r = int(sz[i])
        lay[max(y-r,0):y+r+1, max(x-r,0):x+r+1] = 0.5
    return lay[..., None]


MOVES = {"push": (0.0, 0.0, 1.10), "pull": (0.0, 0.0, 0.92),
         "left": (-0.05, 0.0, 1.03), "right": (0.05, 0.0, 1.03),
         "down": (0.0, 0.03, 1.04), "fly": (0.04, -0.015, 1.07)}


def render(img_path: Path, out: Path, dur: float, mode: str = "push",
           strength: float = 1.0, with_snow: bool = False, ease: bool = True,
           pop: float = 1.0, end_neutral: bool = False, layers: int = 2):
    im = Image.open(img_path).convert("RGB").resize((W, H), Image.LANCZOS)
    d = depth(im, key=str(img_path))
    src = np.asarray(im, dtype=np.float32)
    L = build_layers(src, d, layers)
    fx, fy, z1 = MOVES.get(mode, MOVES["push"])
    TX, TY = fx * W * strength, fy * H * strength
    ZT = 1.0 + (z1 - 1.0) * strength
    n = max(int(dur * FPS), 2)
    tmp = Path(tempfile.mkdtemp())
    for i in range(n):
        p = i / (n - 1)
        e = (3 * p * p - 2 * p * p * p) if ease else p
        k = (1.0 - e) if end_neutral else (e - 0.5)
        zk = (1.0 - e) if end_neutral else e
        acc = None
        for rgb, alpha, dep in L:
            w = dep ** pop
            zz = 1.0 + (ZT - 1.0) * zk * (0.4 + 0.6 * w)
            lp = shift(rgb, TX * k * w, TY * k * w, zz)
            la = np.clip(shift(alpha, TX * k * w, TY * k * w, zz), 0, 1)
            acc = lp if acc is None else acc * (1 - la) + lp
        if with_snow:
            s = snow(i / FPS)
            acc = acc * (1 - s) + 255 * s
        Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8)).save(tmp / f"{i:05d}.png")
    subprocess.run(["ffmpeg", "-v", "error", "-framerate", str(FPS), "-i", str(tmp / "%05d.png"),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", str(out), "-y"], check=True)
    for q in tmp.glob("*.png"):
        q.unlink()
    tmp.rmdir()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image"); ap.add_argument("out")
    ap.add_argument("--dur", type=float, default=5.0)
    ap.add_argument("--mode", default="push")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--pop", type=float, default=1.0)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--snow", action="store_true")
    ap.add_argument("--end-neutral", action="store_true")
    a = ap.parse_args()
    render(Path(a.image), Path(a.out), a.dur, a.mode, a.strength, a.snow,
           pop=a.pop, end_neutral=a.end_neutral, layers=a.layers)
    print("готово:", a.out)
