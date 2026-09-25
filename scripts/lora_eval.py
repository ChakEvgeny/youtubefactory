#!/usr/bin/env python3
"""Слепой лист для сравнения локальной генерации с платным API.

Колонки перемешаны и НЕ подписаны, ключ пишется отдельным файлом: подписанные
колонки заставляют смотреть на ярлык, а не на кадр.

Два листа, потому что критерия два и меряются они по-разному:

  smysl.jpg — тройками: одно описание, три кадра. Здесь считается, нарисовано ли
              то, что написано: предметы, их число, расположение.
  stil.jpg  — полосами по десять кадров от каждого источника подряд. Стиль
              меряется РАЗБРОСОМ по группе, а не отдельным кадром: у платного API
              он плывёт от промпта к промпту, у LoRA держится жёстче.

    python scripts/lora_eval.py --holdout <п> --local <п> --api <п> --out <папка>
"""
from __future__ import annotations

import argparse
import json
import random
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def visual_of(t: Path, styles_root: str) -> str:
    """Описание кадра без преамбулы стиля.

    Подпись собрана как «<триггер> style. <весь style.txt>. <visual>», а style.txt
    сам состоит из нескольких предложений. Резать по точке нельзя — так в лист
    уезжает кусок преамбулы вместо описания; убираем преамбулу целиком.
    """
    txt = t.read_text(encoding="utf-8").strip()
    txt = txt.split(" style. ", 1)[-1]
    proj = t.stem.rsplit("_", 1)[0]
    sf = Path(styles_root) / proj / "style.txt"
    if sf.exists():
        pre = sf.read_text(encoding="utf-8").strip().rstrip(".")
        if txt.startswith(pre):
            txt = txt[len(pre):].lstrip(". ")
    return txt


def load(p: Path, size):
    if p.exists():
        return Image.open(p).convert("RGB").resize(size, Image.LANCZOS)
    im = Image.new("RGB", size, (40, 40, 44))
    ImageDraw.Draw(im).text((10, 10), "нет файла", font=ImageFont.truetype(FONT, 15),
                            fill=(150, 150, 150))
    return im


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", required=True)
    ap.add_argument("--local", required=True)
    ap.add_argument("--api", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20260923)
    ap.add_argument("--styles", default="/mnt/nas/output/explain",
                    help="где лежат проекты со style.txt")
    a = ap.parse_args()
    ho, loc, api = Path(a.holdout), Path(a.local), Path(a.api)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(a.seed)
    items = sorted(ho.glob("*.txt"))
    src = {"в ролике": ho, "локально": loc, "API": api}

    # ЛИСТ 1: смысл, тройками
    tw, th, pad, texth = 430, 242, 14, 86
    row = th + texth + pad
    im = Image.new("RGB", (tw * 3 + pad * 4, row * len(items) + pad), (16, 16, 18))
    d = ImageDraw.Draw(im)
    f, fb = ImageFont.truetype(FONT, 15), ImageFont.truetype(BOLD, 17)
    key = []
    for i, t in enumerate(items):
        y = pad + i * row
        order = list(src); rnd.shuffle(order)
        key.append({"строка": i + 1, "кадр": t.stem,
                    "колонки": {chr(65 + k): name for k, name in enumerate(order)}})
        for k, name in enumerate(order):
            x = pad + k * (tw + pad)
            im.paste(load(src[name] / f"{t.stem}.jpg", (tw, th)), (x, y))
            d.text((x + 6, y + th + 4), f"{i+1}{chr(65 + k)}", font=fb, fill=(235, 235, 235))
        cap = visual_of(t, a.styles)
        ty = y + th + 26
        for line in textwrap.wrap(cap, 128)[:3]:
            d.text((pad, ty), line, font=f, fill=(195, 195, 195)); ty += 18
    im.save(out / "smysl.jpg", quality=88)

    # ЛИСТ 2: стиль, полосами по источникам, порядок источников тоже скрыт
    names = list(src); rnd.shuffle(names)
    sw, sh = 214, 120
    im2 = Image.new("RGB", (sw * len(items) + pad * 2, (sh + 34) * len(names) + pad), (16, 16, 18))
    d2 = ImageDraw.Draw(im2)
    band = []
    for r, name in enumerate(names):
        y = pad + r * (sh + 34)
        d2.text((pad, y - 2), f"полоса {chr(88 + r) if r < 3 else r}", font=fb, fill=(200, 200, 200))
        band.append({"полоса": chr(88 + r), "источник": name})
        for c, t in enumerate(items):
            im2.paste(load(src[name] / f"{t.stem}.jpg", (sw - 4, sh)), (pad + c * sw, y + 20))
    im2.save(out / "stil.jpg", quality=88)

    (out / "klyuch.json").write_text(json.dumps(
        {"смысл": key, "стиль": band}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out}/smysl.jpg — {len(items)} описаний, колонки перемешаны")
    print(f"{out}/stil.jpg — {len(names)} полосы по {len(items)} кадров")
    print(f"{out}/klyuch.json — ключ, открывать ПОСЛЕ оценки")


if __name__ == "__main__":
    main()
