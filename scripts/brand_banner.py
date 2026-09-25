#!/usr/bin/env python3
"""Текст на баннере канала — кодом, а не моделью.

Модель рисует только плиту (персонаж слева, правая часть пустая); название и
строку позиционирования кладём поверх, внутри безопасной зоны 1546x423. Поэтому
смена названия — одна команда, а не перегенерация.

  python scripts/brand_banner.py <папка> "TERMS OF EMPLOYMENT" "One job. Four countries. The real numbers."
"""
from __future__ import annotations
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 2560, 1440
SAFE_W, SAFE_H = 1546, 423
NAVY, OCHRE, RED, PAPER = (0x1B, 0x2A, 0x5E), (0xC8, 0x9A, 0x3C), (0xE4, 0x53, 0x3A), (0xF2, 0xEC, 0xE0)
FONTS = Path.home() / ".fonts"


def fit(path: Path, text: str, max_w: int, start: int) -> ImageFont.FreeTypeFont:
    size = start
    while size > 12:
        f = ImageFont.truetype(str(path), size)
        if f.getbbox(text)[2] - f.getbbox(text)[0] <= max_w:
            return f
        size -= 2
    return ImageFont.truetype(str(path), 12)


def wrap_two(path: Path, text: str, max_w: int, start: int):
    """Длинное название разбиваем на две строки: так кегль вдвое крупнее."""
    one = fit(path, text, max_w, start)
    words = text.split()
    if len(words) < 2 or one.size >= start * 0.8:
        return [text], one
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        f = min(fit(path, a, max_w, start), fit(path, b, max_w, start), key=lambda x: x.size)
        if best is None or f.size > best[1].size:
            best = ([a, b], f)
    return best if best and best[1].size > one.size else ([text], one)


def main():
    prj = Path(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else "TERMS OF EMPLOYMENT"
    line = sys.argv[3] if len(sys.argv) > 3 else "One job. Four countries. The real numbers."
    b = prj / "brand"
    plate = b / "banner.jpg"
    if not plate.exists():
        sys.exit(f"нет плиты {plate}")
    # Фигуру не вырезаем: её кожа — та же кремовая бумага, что и фон, любая маска
    # по цвету пробивает лицо насквозь. Вместо этого масштабируем всю плиту так,
    # чтобы фигура заняла заданную долю безопасной зоны, и ставим её правым краем
    # внутрь зоны. Фон плиты — ровная бумага, поэтому шва не видно.
    import numpy as np
    src = Image.open(plate).convert("RGB")
    arr = np.asarray(src.convert("RGB"), dtype=float)
    mask = np.linalg.norm(arr - np.array(PAPER), axis=2) > 110
    dens = mask.mean(axis=1)
    bt = next((y for y in range(int(src.height * 0.55), src.height) if dens[y] > 0.6), src.height)
    fig = mask.copy(); fig[bt:, :] = False
    xs = np.where(fig.mean(axis=0) > 0.02)[0]
    ys = np.where(fig.mean(axis=1) > 0.02)[0]
    fl, fr, ft, fb = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())

    sx0, sy0 = (W - SAFE_W) // 2, (H - SAFE_H) // 2
    band_h = int(H * 0.13)
    FIG_SHARE = 0.32                                    # доля безопасной зоны под фигуру
    k = (SAFE_W * FIG_SHARE) / max(fr - fl, 1)
    k = min(k, (H - band_h) * 0.86 / max(fb - ft, 1))
    # Плиту вставляем целиком вместе с её собственной плашкой, а нашу рисуем ровно
    # там, где плашка плиты начинается: тогда они совпадают, шва нет и плечи
    # естественно уходят в тёмное. Срезать плашку нельзя — вместе с ней уходит
    # подбородок, а фон подложки светлее нашего и даёт видимую рамку.
    sw, sh = int(src.width * k), int(src.height * k)
    scaled = src.resize((sw, sh), Image.LANCZOS)
    bg = tuple(int(v) for v in np.median(arr[:int(src.height * 0.25), :int(src.width * 0.25)]
                                         .reshape(-1, 3), axis=0))
    im = Image.new("RGB", (W, H), bg)
    ox = sx0 + SAFE_W - 60 - int(fr * k)                # правый край фигуры — внутри зоны
    band_y = int(H * 0.68)
    oy = band_y - int(bt * k)                           # плашка плиты ложится на нашу
    im.paste(scaled, (ox, oy))
    d = ImageDraw.Draw(im)
    d.rectangle([0, band_y, W, H], fill=NAVY)
    band_h = H - band_y
    fig_left = ox + int(fl * k)

    sx, sy = sx0, sy0
    # персонаж справа: текст ставим в левые две трети безопасной зоны
    tx = sx
    tw = fig_left - sx - 60                             # текст не подходит к фигуре ближе 60 px
    lines, f_name = wrap_two(FONTS / "ArchivoBlack.ttf", name, tw, 170)
    f_line = fit(FONTS / "Poppins.ttf", line, tw, 64)

    nh = f_name.size * 1.04
    lh = f_line.getbbox(line)[3] - f_line.getbbox(line)[1]
    gap, rule = 30, 8
    total = nh * len(lines) + gap + rule + gap + lh
    y = sy + (SAFE_H - total) // 2

    for ln in lines:
        d.text((tx, y), ln, font=f_name, fill=NAVY)
        y += nh
    y += gap
    d.rectangle([tx, y, tx + int(tw * 0.22), y + rule], fill=RED)
    y += rule + gap
    d.text((tx, y), line, font=f_line, fill=NAVY)

    out = b / "banner_2560x1440.png"
    im.save(out)
    chk = im.copy()
    ImageDraw.Draw(chk).rectangle([sx, sy, sx + SAFE_W, sy + SAFE_H], outline=RED, width=6)
    chk.save(b / "banner_safezone_check.png")
    print(f"{out}\nназвание {f_name.size} px, строка {f_line.size} px, текст от x={tx}")


if __name__ == "__main__":
    main()
