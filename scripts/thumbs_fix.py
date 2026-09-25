#!/usr/bin/env python3
"""Правки обложек без новой генерации (2026-09-19): перекладка текста и кадрирование
уже сгенерированных фонов из /mnt/d/youtube/thumbs/<канал>/<слаг>/bg_vN_*.jpg.

- why-and-how: без кремовой плашки; текст прямо на кадре на тёмной полупрозрачной
  подложке; объект укрупнён кадрированием к правой половине; фон затемнён.
- wide: текст во всю ширину кадра (для Salad Oil v2 «вдвое крупнее»).
"""
from __future__ import annotations
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from thumbs_v2 import fit_text, W, H, F, BASE

CREAM, INK, CORAL = (246, 238, 222), (12, 12, 16), (236, 86, 64)


def latest_bg(d: Path, k: int) -> Path:
    c = sorted(d.glob(f"bg_v{k}_*.jpg"), key=lambda p: p.stat().st_mtime)
    return c[-1]


def cover(im: Image.Image, zoom: float = 1.0, fx: float = 0.5, fy: float = 0.5) -> Image.Image:
    """Заполнить 1280×720 с увеличением zoom, центр кадрирования (fx, fy) в долях исходника."""
    m = int(im.width * 0.04), int(im.height * 0.04)
    im = im.crop((m[0], m[1], im.width - m[0], im.height - m[1]))
    r = max(W / im.width, H / im.height) * zoom
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    cx, cy = int(im.width * fx), int(im.height * fy)
    x0 = min(max(cx - W // 2, 0), im.width - W); y0 = min(max(cy - H // 2, 0), im.height - H)
    return im.crop((x0, y0, x0 + W, y0 + H))


def why_and_how(bg: Path, text: str, out: Path, zoom=1.35, fx=0.68):
    """Эталон канала — submarines v1 / breathe v1: тёмный кадр, объект крупно, текст на тёмной подложке."""
    im = cover(Image.open(bg).convert("RGB"), zoom, fx)
    im = ImageEnhance.Brightness(im).enhance(0.72)              # затемнить фон целиком
    g = Image.new("L", (W, H), 0); dg = ImageDraw.Draw(g)
    for x in range(int(W * 0.6)):                              # и сильнее — слева, под текстом
        dg.line([(x, 0), (x, H)], fill=int(170 * min(1, (W * 0.6 - x) / (W * 0.3))))
    im.paste((6, 8, 14), (0, 0), g)
    fit = fit_text(text, "Sriracha.ttf", int(W * 0.56) - 40, int(H * 0.62))
    lines, f, cap, lh = fit
    x0, y0 = 56, (H - lh * len(lines)) // 2
    tw = max(f.getlength(l) for l in lines)
    pad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(pad).rounded_rectangle((x0 - 28, y0 - 22, x0 + tw + 28, y0 + lh * len(lines) + 10), 22,
                                          fill=(0, 0, 0, 150))
    im.paste(pad.filter(ImageFilter.GaussianBlur(10)), (0, 0), pad.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(im)
    for i, line in enumerate(lines):
        words = line.split(); cx = x0; y = y0 + i * lh - f.getbbox("H")[1]
        for wi, wd in enumerate(words):
            col = CORAL if (i == len(lines) - 1 and wi == len(words) - 1) else CREAM
            d.text((cx, y), wd, font=f, fill=col, stroke_width=max(4, cap // 16), stroke_fill=INK)
            cx += f.getlength(wd + " ")
    im.save(out, "JPEG", quality=90, optimize=True)
    return cap


def wide(bg: Path, lines: list[str], out: Path, font="Anton.ttf", fill=(242, 192, 48), where="middle", maxcap=999):
    im = cover(Image.open(bg).convert("RGB"))
    im = ImageEnhance.Brightness(im).enhance(0.8)
    for s in range(400, 60, -2):
        f = ImageFont.truetype(str(F / font), s); cap = f.getbbox("H")[3] - f.getbbox("H")[1]
        if max(f.getlength(l) for l in lines) <= W - 90 and cap * 1.22 * len(lines) <= H - 60 and cap <= maxcap:
            break
    lh = int(cap * 1.22)
    y0 = {"middle": (H - lh * len(lines)) // 2, "bottom": H - lh * len(lines) - 20, "top": 36}[where]
    if where == "bottom":   # тёмная полоса снизу под текст
        g = Image.new("L", (W, H), 0); dg = ImageDraw.Draw(g)
        for y in range(H):
            dg.line([(0, y), (W, y)], fill=int(220 * min(1, max(0, (y - (y0 - 80)) / 160))))
        im.paste((6, 6, 8), (0, 0), g)
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        d.text((45, y0 + i * lh - f.getbbox("H")[1]), l, font=f, fill=fill, stroke_width=cap // 12, stroke_fill=(6, 6, 6))
    im.save(out, "JPEG", quality=90, optimize=True)
    return cap


STY = {  # оформление текста по каналам — как в thumbs_v2 / why_and_how
    "heists": dict(font="Anton.ttf", fill=(242, 192, 48), accent=None, stroke=(8, 8, 8), backing=False, zoom=1.0, dim=1.0),
    "survival": dict(font="RobotoSerifCondBlack.ttf", fill=(241, 230, 207), accent=(214, 58, 44), stroke=(6, 8, 16), backing=False, zoom=1.0, dim=1.0),
    "explain": dict(font="Sriracha.ttf", fill=CREAM, accent=CORAL, stroke=INK, backing=True, zoom=1.2, dim=0.72),
}


def hero(ch: str, bg: Path, num: str, rest: str, out: Path, zoom=None, fx=0.66):
    """Число крупным элементом: первая строка — число (заглавная ~2× текста), вторая — 2–3 слова."""
    st = STY[ch]
    im = cover(Image.open(bg).convert("RGB"), zoom or st["zoom"], fx if (zoom or st["zoom"]) > 1 else 0.5)
    im = ImageEnhance.Brightness(im).enhance(st["dim"])
    g = Image.new("L", (W, H), 0); dg = ImageDraw.Draw(g)
    for x in range(int(W * 0.62)):
        dg.line([(x, 0), (x, H)], fill=int(235 * min(1, max(0, (W * 0.62 - x) / (W * 0.26)))))
    im.paste((6, 7, 10), (0, 0), g)
    fp = str(F / st["font"]); maxw = int(W * 0.62)
    capof = lambda f: f.getbbox("H")[3] - f.getbbox("H")[1]
    for s2 in range(200, 60, -2):                       # вторая строка: крупнее, но в колонку
        f2 = ImageFont.truetype(fp, s2)
        if f2.getlength(rest) <= maxw: break
    for s1 in range(520, 60, -4):                       # число: ≤ 2.2× и в колонку по ширине/высоте
        f1 = ImageFont.truetype(fp, s1)
        if f1.getlength(num) <= maxw and capof(f1) <= 2.2 * capof(f2) and capof(f1) * 1.18 + capof(f2) * 1.3 <= H * 0.8:
            break
    c1, c2 = capof(f1), capof(f2)
    if c2 < 90:
        raise ValueError(f"«{rest}»: заглавная {c2}px < 90 — сократить текст")
    y1 = (H - int(c1 * 1.18 + c2)) // 2; y2 = y1 + int(c1 * 1.18)
    x0 = 56
    if st["backing"]:
        tw = max(f1.getlength(num), f2.getlength(rest))
        pad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(pad).rounded_rectangle((x0 - 28, y1 - 24, x0 + tw + 28, y2 + c2 + 26), 22, fill=(0, 0, 0, 150))
        pad = pad.filter(ImageFilter.GaussianBlur(10)); im.paste(pad, (0, 0), pad)
    d = ImageDraw.Draw(im)
    d.text((x0, y1 - f1.getbbox("H")[1]), num, font=f1, fill=st["accent"] or st["fill"],
           stroke_width=max(5, c1 // 16), stroke_fill=st["stroke"])
    d.text((x0, y2 - f2.getbbox("H")[1]), rest, font=f2, fill=st["fill"],
           stroke_width=max(4, c2 // 14), stroke_fill=st["stroke"])
    im.save(out, "JPEG", quality=90, optimize=True)
    return c1, c2
