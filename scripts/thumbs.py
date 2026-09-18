#!/usr/bin/env python3
"""Обложки: четыре варианта под A/B-тест.

Правила ad-safety (CLAUDE.md): никаких чужих лиц, никаких логотипов СМИ,
никаких плашек BREAKING и имитаций эфирной графики. Текст рисуем сами:
нейросеть буквы коверкает.
"""
from __future__ import annotations
import argparse, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pipeline.config import Config
from pipeline.sources import genimage
from pipeline import costs

W, H = 1280, 720
NEG = (" No text, no letters, no numbers, no logos, no watermarks, no signage. "
       "No recognizable real person's face. No news-broadcast graphics.")


# Как ложится текст на обложку.
#
# bare (по умолчанию) — надпись ПРЯМО на рисунке, без плашки. Решение Евгения
# 2026-09-17: «иначе он собой фон закрывает весь нахер». Плашка съедала половину
# кадра вместе с рисунком, ради которого обложка и делалась. Читаемость держит не
# подложка, а толстая обводка тушью: цвет даёт контраст, обводка — границу на
# любом фоне, светлом и тёмном сразу.
#
# dark/light — старые режимы с плашкой, оставлены для каналов с фильмами.
THEMES = {
    "bare":  {"panel": None,                 "text": None,
              "shadow": None,                "rule": None,
              "sub": (242, 233, 216),        "hand": True},
    "dark":  {"panel": (6, 8, 11, 205),      "text": (245, 244, 240),
              "shadow": (0, 0, 0),           "rule": (198, 40, 40),
              "sub": (198, 198, 198),        "hand": False},
    "light": {"panel": (242, 233, 216, 236), "text": (20, 18, 16),
              "shadow": None,                "rule": (226, 80, 60),
              "sub": (110, 101, 92),         "hand": True},
}
# Яркие цвета для bare. Жёлтого в палитре канала нет — поэтому он бьёт сильнее
# всего и при этом не выглядит чужим. Коралловый спорит с акцентами на рисунке.
COLOURS = {"yellow": (255, 205, 40), "coral": (232, 74, 52),
           "green": (78, 200, 110), "cream": (242, 233, 216)}
INK = (18, 16, 14)

HAND = "/home/chak/.fonts/Sriracha.ttf"


def font(sz, bold=True, hand=False):
    if hand and Path(HAND).exists():
        return ImageFont.truetype(HAND, sz)
    p = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
         else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return ImageFont.truetype(p, sz)


def draw_two(img: Path, l1: str, l2: str, out: Path,
             c1="coral", c2="green", s1=158, s2=80, shift=0.10):
    """Двухстрочная обложка: приказ крупно, ситуация ниже со сдвигом.

    Макет утверждён Евгением 2026-09-17 («DO NOTHING / if you're lost in the
    woods»). Первая строка — провокация, вторая — поисковая привязка: тот же
    запрос, что в заголовке ролика, так обложка работает и на клик, и на поиск.
    Без плашки: читаемость держит обводка тушью.
    """
    im = Image.open(img).convert("RGB").resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    while s1 > 80:
        f1 = ImageFont.truetype(HAND, s1)
        if d.textlength(l1, font=f1) <= W * 0.88:
            break
        s1 -= 4
    f1 = ImageFont.truetype(HAND, s1)
    while s2 > 46:
        f2 = ImageFont.truetype(HAND, s2)
        if d.textlength(l2, font=f2) <= W * 0.82:
            break
        s2 -= 2
    f2 = ImageFont.truetype(HAND, s2)
    x1, y1 = (W - d.textlength(l1, font=f1)) / 2, H * 0.06
    y2 = y1 + s1 * 1.02
    x2 = min(x1 + W * shift, W * 0.97 - d.textlength(l2, font=f2))
    for txt, f, x, y, col, r in (
            (l1, f1, x1, y1, COLOURS.get(c1, COLOURS["coral"]), max(int(s1 * 0.085), 6)),
            (l2, f2, x2, y2, COLOURS.get(c2, COLOURS["green"]), max(int(s2 * 0.10), 5))):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    d.text((x + dx, y + dy), txt, font=f, fill=INK)
        d.text((x, y), txt, font=f, fill=col)
    im.save(out, quality=93)


def draw_bare(img: Path, big, small: str, out: Path, colour="yellow"):
    """Надпись на рисунке без плашки: обводка тушью вместо подложки.

    big — строка, либо список кусков [["LOST? ","green"],["DO NOTHING.","coral"]]
    для двухцветной надписи: ключевое слово выделяется цветом, а не кеглем.
    """
    parts = ([(t, COLOURS.get(c, COLOURS["yellow"])) for t, c in big]
             if isinstance(big, list) else [(big, COLOURS.get(colour, COLOURS["yellow"]))])
    line = "".join(t for t, _ in parts)
    im = Image.open(img).convert("RGB").resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    sz = 132
    while sz > 56:
        f = ImageFont.truetype(HAND, sz)
        if d.textlength(line, font=f) <= W * 0.90:
            break
        sz -= 4
    f = ImageFont.truetype(HAND, sz)
    x, y = (W - d.textlength(line, font=f)) / 2, H * 0.07
    r = max(int(sz * 0.085), 5)
    # обводка кладётся под ВСЮ строку целиком, иначе она перекроет соседний кусок
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                d.text((x + dx, y + dy), line, font=f, fill=INK)
    cx = x
    for t, col in parts:
        d.text((cx, y), t, font=f, fill=col)
        cx += d.textlength(t, font=f)
    if small:
        fm = ImageFont.truetype(HAND, 46)
        sx, sy = (W - d.textlength(small, font=fm)) / 2, y + sz * 1.34
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                d.text((sx + dx, sy + dy), small, font=fm, fill=INK)
        d.text((sx, sy), small, font=fm, fill=THEMES["bare"]["sub"])
    im.save(out, quality=93)


def draw_text(img: Path, big: str, small: str, out: Path, side="left", theme="dark"):
    T = THEMES.get(theme, THEMES["dark"])
    hand = T["hand"]
    im = Image.open(img).convert("RGB").resize((W, H), Image.LANCZOS)
    # половина кадра под текст: иначе крупные буквы теряются на рисунке
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    x0 = 0 if side == "left" else W // 2
    dr.rectangle([x0, 0, x0 + W // 2, H], fill=T["panel"])
    im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
    d = ImageDraw.Draw(im)
    pad = 54
    x = pad if side == "left" else W // 2 + pad
    maxw = W // 2 - pad * 2
    sz = 96
    while sz > 40:
        f = font(sz, hand=hand)
        lines, cur = [], ""
        for word in big.split():
            t = (cur + " " + word).strip()
            if d.textlength(t, font=f) <= maxw:
                cur = t
            else:
                lines.append(cur); cur = word
        lines.append(cur)
        # длинное неразрывное слово ("$7,750,000") перенести нельзя — уменьшаем кегль
        widest = max(d.textlength(x, font=f) for x in lines) if lines else 0
        if len(lines) <= 3 and widest <= maxw:
            break
        sz -= 6
    y = H // 2 - (len(lines) * (sz + 10)) // 2 - 30
    for ln in lines:
        if T["shadow"]:
            d.text((x + 3, y + 3), ln, font=font(sz, hand=hand), fill=T["shadow"])
        d.text((x, y), ln, font=font(sz, hand=hand), fill=T["text"])
        y += sz + 10
    d.rectangle([x, y + 12, x + 150, y + 20], fill=T["rule"])
    if small:
        fs = 34
        while fs > 18 and d.textlength(small, font=font(fs, False, hand)) > maxw:
            fs -= 2
        d.text((x, y + 40), small, font=font(fs, False, hand), fill=T["sub"])
    im.save(out, quality=92)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--style", required=True)
    ap.add_argument("--theme", default="bare", choices=["bare", "dark", "light"],
                    help="bare — текст на рисунке без плашки (по умолчанию)")
    ap.add_argument("--colour", default="yellow", choices=list(COLOURS))
    ap.add_argument("--model", default="gemini-3-pro-image")
    a = ap.parse_args()
    d = Path(a.dir)
    spec = json.loads((d / "thumbs.json").read_text(encoding="utf-8"))
    out = d / "thumbs"; out.mkdir(exist_ok=True)
    cfg = Config()
    spent = {"usd": 0.0}

    def one(item):
        tag = item["tag"]
        bg = out / f"bg_{tag}.jpg"
        if not bg.exists():
            try:
                r = genimage.generate(cfg, a.style + " " + item["image"] + NEG, bg,
                                      model=a.model, aspect="16:9")
                spent["usd"] += r.get("usd", 0.0)
            except Exception as e:
                print(f"  ! {tag}: {str(e)[:80]}"); return None
        dst = out / f"thumb_{tag}.jpg"
        if item.get("l1"):
            draw_two(bg, item["l1"], item.get("l2", ""), dst,
                     item.get("c1", "coral"), item.get("c2", "green"))
        elif a.theme == "bare":
            draw_bare(bg, item["big"], item.get("small", ""), dst, a.colour)
        else:
            draw_text(bg, item["big"], item.get("small", ""), dst,
                      item.get("side", "left"), a.theme)
        return dst

    with ThreadPoolExecutor(max_workers=2) as ex:
        files = [f for f in ex.map(one, spec) if f]
    # контактный лист
    if files:
        sheet = Image.new("RGB", (W, H // 2 * len(files)), (12, 12, 14))
        for i, f in enumerate(files):
            sheet.paste(Image.open(f).resize((W, H // 2), Image.LANCZOS), (0, i * (H // 2)))
        sheet.save(out / "sheet_thumbs.jpg", quality=88)
    costs.log(costs.project_of(d), "thumbs", a.model, spent["usd"], len(spec), "обложек")
    print(f"обложек {len(files)}/{len(spec)}, ${spent['usd']:.2f}")


if __name__ == "__main__":
    main()
