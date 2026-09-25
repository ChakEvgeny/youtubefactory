#!/usr/bin/env python3
"""Заставка канала: наезд через плечо на папку, руки печатают, на наклейке набивается название.

Всё из одного утверждённого мастер-кадра:
  - камера — непрерывный зум по мастеру, поэтому движение идеально гладкое;
  - руки — три фазы того же кадра, накладываются по маске различий (сцена не
    разъезжается, потому что меняются только пальцы);
  - название — Remotion-подобная посимвольная печать, но рисуется здесь же,
    шрифтом бренда, прямо в белую наклейку на обложке.

  python scripts/intro_build.py <папка> --name "TERMS OF EMPLOYMENT"
"""
from __future__ import annotations
import argparse, json, math, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FPS = 25
BRAND = Path.home() / ".fonts" / "SpecialElite-Regular.ttf"
NAVY = (0x1B, 0x2A, 0x5E)


def ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--name", default="TERMS OF EMPLOYMENT")
    ap.add_argument("--sec", type=float, default=7.0)
    ap.add_argument("--out", default="intro.mp4")
    a = ap.parse_args()
    P = Path(a.dir); O = P / "intro"
    base = Image.open(O / "master.jpg").convert("RGB")
    W, H = base.size
    anch = json.loads((O / "anchors.json").read_text())
    lab = anch["label"]

    # фазы рук: маска различий, чтобы менялись только пальцы
    hands = []
    ba = np.asarray(base, dtype=float)
    for i in (1, 2, 3):
        f = O / f"hands{i}.jpg"
        if not f.exists():
            continue
        ia = np.asarray(Image.open(f).convert("RGB").resize((W, H)), dtype=float)
        diff = np.linalg.norm(ia - ba, axis=2)
        m = np.clip((diff - 30) / 60, 0, 1)
        m = np.asarray(Image.fromarray((m * 255).astype("uint8")).filter(
            ImageFilter.GaussianBlur(2.5)), dtype=float) / 255
        hands.append((Image.fromarray(ia.astype("uint8")), m))

    n = int(a.sec * FPS)
    zoom_end = int(n * 0.62)          # к этому кадру камера доехала до наклейки
    type_from = int(n * 0.58)
    tmp = O / "_frames"; tmp.mkdir(exist_ok=True)
    for f in tmp.glob("*.jpg"):
        f.unlink()

    # конечная рамка кадра — наклейка с воздухом вокруг
    lw, lh = lab[2] - lab[0], lab[3] - lab[1]
    cx, cy = (lab[0] + lab[2]) / 2, (lab[1] + lab[3]) / 2
    end_w = min(lw * 3.4, 1.0)
    end_h = end_w * 9 / 16
    letters = len(a.name)

    for i in range(n):
        t = min(i / max(zoom_end, 1), 1.0)
        k = ease(t)
        # прямоугольник кадра интерполируем от полного к наклейке
        w = 1.0 + (end_w - 1.0) * k
        h = 1.0 + (end_h - 1.0) * k
        x0 = (0.5 + (cx - 0.5) * k) - w / 2
        y0 = (0.5 + (cy - 0.5) * k) - h / 2
        x0 = min(max(x0, 0), 1 - w); y0 = min(max(y0, 0), 1 - h)

        frame = base.copy()
        if hands and i < zoom_end:                 # руки видны только пока не доехали
            img, m = hands[(i // 5) % len(hands)]  # смена фазы каждые 5 кадров — ритм печати
            frame = Image.composite(img, frame, Image.fromarray((m * 255).astype("uint8")))

        if i >= type_from:                          # печать в наклейку
            shown = min(letters, int((i - type_from) / max(n - type_from - 8, 1) * letters) + 1)
            d = ImageDraw.Draw(frame)
            box_w = (lab[2] - lab[0]) * W * 0.86
            size = 12
            while size < 200:
                f2 = ImageFont.truetype(str(BRAND), size + 2)
                if f2.getbbox(a.name)[2] - f2.getbbox(a.name)[0] > box_w:
                    break
                size += 2
            font = ImageFont.truetype(str(BRAND), size)
            txt = a.name[:shown]
            bb = font.getbbox(a.name)
            tx = lab[0] * W + ((lab[2] - lab[0]) * W - (bb[2] - bb[0])) / 2 - bb[0]
            ty = lab[1] * H + ((lab[3] - lab[1]) * H - (bb[3] - bb[1])) / 2 - bb[1]
            d.text((tx, ty), txt, font=font, fill=NAVY)

        crop = frame.crop((int(x0 * W), int(y0 * H), int((x0 + w) * W), int((y0 + h) * H)))
        crop.resize((1920, 1080), Image.LANCZOS).save(tmp / f"f{i:04d}.jpg", quality=93)

    out = O / a.out
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS),
                    "-i", str(tmp / "f%04d.jpg"), "-c:v", "libx264", "-crf", "18",
                    "-pix_fmt", "yuv420p", str(out)], check=True)
    print(f"{out}  {n} кадров, наезд до {zoom_end}, печать с {type_from}")


if __name__ == "__main__":
    main()
