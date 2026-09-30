#!/usr/bin/env python3
"""Заставка блока для Terms of Employment: название блока с «кипящей» линией.

Переход между блоками — не пролистывание кадров, а затемнение, надпись и снова
затемнение (решение Евгения 2026-09-28). Надпись живая: тот же приём, что у
марионетки ведущего, — микродеформация сетки на каждый кадр (`boil.warp`), а не
статичный титр.

Клип отдаётся сегментом с ЧЁРНЫМИ первым и последним кадрами: цепочка xfade в
сборке сама превращает это в уход в затемнение и выход из него, отдельная логика
переходов не нужна.

  python scripts/work_title.py "WHAT RESIDENCE ACTUALLY MEANS" out.mp4 --seconds 2.4
"""
from __future__ import annotations
import argparse, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from PIL import Image, ImageDraw, ImageFont
from boil import warp

W, H, FPS = 1920, 1080, 25
PAPER = (240, 233, 218)     # бумага канала
NAVY = (27, 42, 94)         # краска один — #1B2A5E
OCHRE = (200, 154, 60)      # краска два — #C89A3C
# Шрифт заставки канала — тот же, которым набрано «Terms of Employment»
# в интро (intro_build.py). Решение Евгения 2026-09-30: названия глав
# должны читаться как часть бренда, а не как карточка с цифрами.
FONT = Path.home() / ".fonts" / "SpecialElite-Regular.ttf"


def lay(text: str) -> Image.Image:
    """Надпись на бумаге: две-три строки, поля как у карточек."""
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    words, lines, cur = text.upper().split(), [], ""
    size = 96
    while True:
        f = ImageFont.truetype(str(FONT), size)
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= W * 0.74:
                cur = t
            else:
                lines.append(cur); cur = w
        lines.append(cur)
        if len(lines) <= 3 and max(d.textlength(l, font=f) for l in lines) <= W * 0.74:
            break
        size -= 6
        if size < 40:
            break
    lh = size * 1.35
    y = H / 2 - lh * len(lines) / 2
    for ln in lines:
        d.text((W / 2, y), ln, font=f, fill=NAVY, anchor="ma")
        y += lh
    # тонкая охряная черта под блоком — единственное украшение
    wln = max(d.textlength(l, font=ImageFont.truetype(str(FONT), size)) for l in lines)
    d.rectangle([W / 2 - wln / 2, y + size * 0.25, W / 2 + wln / 2, y + size * 0.25 + 6], fill=OCHRE)
    return im


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text"); ap.add_argument("out")
    ap.add_argument("--seconds", type=float, default=2.4)
    ap.add_argument("--amp", type=float, default=1.6, help="амплитуда дрожания, px")
    ap.add_argument("--hold", type=int, default=3, help="кадров на один рисунок, «на тройках»")
    a = ap.parse_args()
    base = lay(a.text)
    n = max(int(a.seconds * FPS), FPS)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for i in range(n):
            # новый рисунок раз в hold кадров — как в рисованной анимации
            warp(base, seed=i // a.hold, amp=a.amp).save(td / f"f{i:04d}.png")
        black = a.seconds * 0.18      # чёрные края: из них сборка делает затемнение
        subprocess.run(
            ["ffmpeg", "-v", "error", "-framerate", str(FPS), "-i", str(td / "f%04d.png"),
             "-vf", f"fade=t=in:st=0:d={black:.2f},fade=t=out:st={a.seconds-black:.2f}:d={black:.2f},"
                    f"format=yuv420p", "-c:v", "libx264", "-crf", "17", "-r", str(FPS),
             "-t", f"{a.seconds:.3f}", a.out, "-y"], check=True)
    print(a.out, f"{a.seconds:.1f} c, {n} кадров")


if __name__ == "__main__":
    main()
