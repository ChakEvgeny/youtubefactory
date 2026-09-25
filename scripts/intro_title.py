#!/usr/bin/env python3
"""Название канала в наклейку на папке: отслеживание четырёхугольника по кадрам.

Kling двигает камеру, поэтому наклейка едет и меняет перспективу. Рисовать текст
по координатам исходного кадра нельзя — он ляжет по диагонали (проверено). Здесь
наклейка ищется на каждом кадре как светлое пятно внутри папки, из него берутся
четыре угла, и отрисованный текст вписывается в них преобразованием QUAD.

  python scripts/intro_title.py <клип.mp4> <выход.mp4> --name "TERMS OF EMPLOYMENT"
"""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BRAND = Path.home() / ".fonts" / "SpecialElite-Regular.ttf"
NAVY = (0x1B, 0x2A, 0x5E)


def perspective_coeffs(dst, src):
    """Коэффициенты для Image.PERSPECTIVE: PIL идёт от точки НАЗНАЧЕНИЯ к источнику,
    поэтому матрица строится на парах (точка в кадре -> точка в картинке текста).
    Ошибка первой версии была в QUAD: он отображает четырёхугольник источника на
    весь холст, а нужно вписать маленькую картинку в четырёхугольник кадра."""
    m = []
    for (x, y), (u, v) in zip(dst, src):
        m.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        m.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    A = np.array(m, dtype=float)
    B = np.array([c for p in src for c in p], dtype=float)
    return np.linalg.solve(A, B).tolist()


def label_quad(im: Image.Image):
    """Четыре угла белой наклейки.

    Путь к решению был длинным, поэтому правило записано явно. Нельзя искать
    «самое светлое справа» (кремовый стол ярче), нельзя ограничиваться габаритом
    охряной папки (в конце наезда она занимает весь кадр). Работает признак
    связности: наклейка — светлая область, которая НЕ КАСАЕТСЯ края кадра, а стол
    касается. Заполнение габарита у неё около 0.5, потому что в перспективе она
    параллелограмм — порог 0.6 её отбрасывал."""
    from scipy import ndimage
    a = np.asarray(im.convert("RGB"), dtype=float)
    H, W, _ = a.shape
    bright = a.min(axis=2) > 215
    lab, n = ndimage.label(bright)
    if n == 0:
        return None
    best = None
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if len(xs) < 2000:
            continue
        if xs.min() <= 1 or ys.min() <= 1 or xs.max() >= W - 2 or ys.max() >= H - 2:
            continue
        box = (xs.min(), ys.min(), xs.max(), ys.max())
        fill = len(xs) / max((box[2] - box[0]) * (box[3] - box[1]), 1)
        if fill < 0.38:
            continue
        if best is None or len(xs) > best[0]:
            best = (len(xs), xs.astype(float), ys.astype(float))
    if best is None:
        return None
    xs, ys = best[1], best[2]
    pts = np.stack([xs, ys], axis=1)
    ssum, diff = pts[:, 0] + pts[:, 1], pts[:, 0] - pts[:, 1]
    tl, br = pts[np.argmin(ssum)], pts[np.argmax(ssum)]
    tr, bl = pts[np.argmax(diff)], pts[np.argmin(diff)]
    q = np.array([tl, tr, br, bl], dtype=float)
    c = q.mean(axis=0)
    q = c + (q - c) * 0.86            # отступ внутрь, чтобы буквы не лезли на рамку
    return [tuple(p) for p in q]


def render_text(name: str, w: int, h: int, shown: int) -> Image.Image:
    """Текст в две строки на прозрачном холсте размером с наклейку."""
    words = name.split()
    mid = len(words) // 2 or 1
    lines = [" ".join(words[:mid]), " ".join(words[mid:])] if len(words) > 2 else [name]
    size = 8
    while size < 400:
        f = ImageFont.truetype(str(BRAND), size + 2)
        wid = max(f.getbbox(l)[2] - f.getbbox(l)[0] for l in lines)
        hei = (f.getbbox("H")[3] - f.getbbox("H")[1]) * len(lines) * 1.5
        if wid > w * 0.84 or hei > h * 0.7:
            break
        size += 2
    font = ImageFont.truetype(str(BRAND), size)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    lh = (font.getbbox("H")[3] - font.getbbox("H")[1]) * 1.5
    total = lh * len(lines)
    y = (h - total) / 2
    typed = 0
    for l in lines:
        take = max(0, min(len(l), shown - typed))
        if take:
            part = l[:take]
            bb = font.getbbox(l)
            x = (w - (bb[2] - bb[0])) / 2 - bb[0]
            d.text((x, y), part, font=font, fill=NAVY)
        typed += len(l) + 1
        y += lh
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--name", default="TERMS OF EMPLOYMENT")
    ap.add_argument("--start", type=float, default=6.6, help="секунда начала печати")
    ap.add_argument("--speed", type=float, default=13.0, help="знаков в секунду")
    a = ap.parse_args()
    src = Path(a.src); out = Path(a.out)
    tmp = out.parent / "_title_frames"; tmp.mkdir(exist_ok=True)
    for f in tmp.glob("*.png"):
        f.unlink()
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vsync", "0",
                    str(tmp / "f%04d.png")], check=True)
    frames = sorted(tmp.glob("f*.png"))
    fps = 25.0
    letters = len(a.name)
    found = 0
    for i, fp in enumerate(frames):
        t = i / fps
        shown = int(max(0.0, t - a.start) * a.speed)
        if shown <= 0:
            continue
        im = Image.open(fp).convert("RGB")
        q = label_quad(im)
        if not q:
            continue
        found += 1
        xs = [p[0] for p in q]; ys = [p[1] for p in q]
        w = int(max(xs) - min(xs)); h = int(max(ys) - min(ys))
        if w < 40 or h < 20:
            continue
        txt = render_text(a.name, w, h, min(shown, letters))
        src = [(0, 0), (w, 0), (w, h), (0, h)]
        coeffs = perspective_coeffs(q, src)
        warped = txt.transform(im.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
        im = Image.alpha_composite(im.convert("RGBA"), warped).convert("RGB")
        im.save(fp)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", "25",
                    "-i", str(tmp / "f%04d.png"), "-c:v", "libx264", "-crf", "17",
                    "-pix_fmt", "yuv420p", str(out)], check=True)
    print(f"{out}  наклейка найдена на {found} кадрах из {len(frames)}")


if __name__ == "__main__":
    main()
