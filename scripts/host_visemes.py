#!/usr/bin/env python3
"""Набор артикуляций под конкретный кадр ведущего.

Марионетка (`host_anim.py`) накладывает на лицо шесть вариантов рта. Брать их
из чужого рисунка нельзя: борода получается другого оттенка и вокруг рта лезет
цветной ореол. Поэтому рты генерируются из ТОГО ЖЕ кадра — шесть вариантов
одной картинки, — а потом вырезаются по разнице с исходником.

    python scripts/host_visemes.py <папка> --frame stills/s904.jpg --name 904

Кладёт `anim/visemes<name>/v0..v5.png` и `anim/<name>_patch.json`.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
import anthropic  # noqa: E402

from pipeline.config import Config  # noqa: E402
from pipeline.sources import genimage  # noqa: E402

MODEL = "claude-opus-5"
# m0 «зубы наружу» и m5 «оскал» в речи не нужны, но набор держим полным
MOUTHS = [
    "lips pressed together in a neutral closed mouth",
    "lips pressed together in a closed mouth, as in the sound M",
    "mouth slightly open in a narrow horizontal slit, as in the sound E",
    "mouth open wide and tall, as in the sound A",
    "mouth open in a small round O, as in the sound O",
    "mouth open in a wide flat grin showing the upper teeth, as in the sound EE",
]


def box_from_diff(base: Image.Image, variants: list[Path]) -> tuple[float, float, float, float]:
    """НЕ ИСПОЛЬЗУЕТСЯ. Оставлено с объяснением, чтобы не изобрести заново.

    Замысел был найти рот по разнице базы и вариантов: варианты просили изменить
    только рот. На деле модель перерисовывает лицо целиком, разница покрывает
    весь кадр, и прямоугольник выходит во весь экран. Значит и альфа по разнице,
    которая была здесь раньше, держалась на случайности."""
    raise NotImplementedError


def find_mouth(base: Image.Image) -> tuple[float, float, float, float]:
    """Рот через очки: они дают и центр лица, и его ширину.

    Две прошлые попытки провалились. Спрашивать прямоугольник у модели нельзя —
    она показала на нос. Искать «самую тёмную строку под очками» тоже нельзя —
    в неё попадает фон, и рамка разъезжается во весь кадр, а один раз села на
    грудь. Очки — единственная деталь, которую видно надёжно: сплошная тёмная
    перемычка поперёк лица в верхней половине кадра.
    """
    import numpy as np
    W, H = base.size
    g = np.asarray(base.convert("L"), dtype=float)
    dark = g < 105

    # строка очков: самый длинный НЕПРЕРЫВНЫЙ тёмный отрезок в верхней половине
    best = (0, None, 0, 0)
    for y in range(int(H * 0.12), int(H * 0.62)):
        row = dark[y]
        run = x0 = 0
        for x in range(W):
            if row[x]:
                run += 1
                if run == 1:
                    x0 = x
                if run > best[0]:
                    best = (run, y, x0, x)
            else:
                run = 0
    run, gy, gx0, gx1 = best
    if gy is None or run < W * 0.10:
        raise SystemExit("очки не найдены — рот определить нечем")

    face_w = gx1 - gx0                       # ширина очков ≈ ширина лица
    cx = (gx0 + gx1) / 2
    mouth_y = gy + face_w * 0.62             # рот ниже очков на 0.62 ширины лица
    mw = face_w * 0.46                       # рот уже лица примерно вдвое
    mh = face_w * 0.34
    x0, x1 = cx - mw / 2, cx + mw / 2
    y0, y1 = mouth_y - mh / 2, mouth_y + mh / 2
    return (max(x0, 0) / W, max(y0, 0) / H, min(x1, W) / W, min(y1, H) / H)


def mouth_box(p: Path) -> tuple[float, float, float, float]:
    """Прямоугольник рта долями кадра — спрашиваем у модели, на глаз не угадать."""
    cl = anthropic.Anthropic()
    r = cl.messages.create(
        model=MODEL, max_tokens=800,
        system=("Верни ТОЛЬКО JSON {\"x0\":..,\"y0\":..,\"x1\":..,\"y1\":..} — прямоугольник "
                "вокруг рта человека в кадре, долями ширины и высоты от 0 до 1. Рамка "
                "должна включать губы, усы и подбородочную часть бороды под губой, с "
                "небольшим запасом со всех сторон."),
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(p.read_bytes()).decode()}}]}])
    txt = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
    j = json.loads(re.search(r"\{.*?\}", txt, re.S).group(0))
    return j["x0"], j["y0"], j["x1"], j["y1"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--frame", required=True, help="кадр ведущего относительно папки")
    ap.add_argument("--name", required=True, help="имя набора, например 904")
    ap.add_argument("--box", default="", help="x0,y0,x1,y1 долями, если не спрашивать модель")
    a = ap.parse_args()

    P = Path(a.dir)
    src = P / a.frame
    base = Image.open(src).convert("RGB")
    W, H = base.size
    # прямоугольник берём из разницы с уже сгенерированными вариантами; если их
    # ещё нет — спрашиваем модель, но потом пересчитываем по разнице
    cached = sorted((P / "anim" / f"visemes{a.name}").glob("_m*.jpg"))
    if a.box:
        box = [float(x) for x in a.box.split(",")]
    else:
        box = list(find_mouth(base))
        print("рот найден геометрически")
    x0, y0, x1, y1 = box
    px = (int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
    print(f"рот: {box} -> {px}")

    A = P / "anim"
    vdir = A / f"visemes{a.name}"
    vdir.mkdir(parents=True, exist_ok=True)
    (A / f"{a.name}_patch.json").write_text(json.dumps({"patch": box}), encoding="utf-8")

    cfg = Config()
    ref_crop = np.asarray(base.crop(px), dtype=float)
    w, h = px[2] - px[0], px[3] - px[1]

    # эллипс по губам: разница по всему прямоугольнику тянет за собой бороду и щёки
    ell = Image.new("L", (w, h), 0)
    ImageDraw.Draw(ell).ellipse([w * 0.06, h * 0.10, w * 0.94, h * 0.90], fill=255)
    ell = ell.filter(ImageFilter.GaussianBlur(max(2, w // 28)))
    ell_a = np.asarray(ell, dtype=float) / 255.0

    spent = 0.0
    for i, shape in enumerate(MOUTHS):
        if i == 0:
            var = base
        else:
            tmp = vdir / f"_m{i}.jpg"
            if tmp.exists():                       # вариант уже сгенерирован — не платим снова
                var = Image.open(tmp).convert("RGB").resize((W, H))
                crop = var.crop(px)
                alpha = ell_a.copy()
                if i <= 1:
                    alpha[:] = 0.0
                out = np.dstack([np.asarray(crop, dtype=np.uint8),
                                 (alpha * 255).astype(np.uint8)])
                Image.fromarray(out, "RGBA").save(vdir / f"v{i}.png")
                print(f"  v{i}: из кэша")
                continue
            prompt = (f"The exact same illustration, unchanged in every way — same face, same "
                      f"beard, same glasses, same colours, same lines, same background. The only "
                      f"difference: the man's {shape}. The inside of the mouth is drawn in deep "
                      f"navy #1B2A5E and the teeth in the pale paper tone — never red, never pink, "
                      f"no tongue colour. Do not move the head, do not change the framing, do not "
                      f"redraw anything else.")
            r = genimage.generate(cfg, prompt, tmp, refs=[src])
            spent += r.get("usd", 0.0)
            var = Image.open(tmp).convert("RGB").resize((W, H))
        crop = var.crop(px)
        # накладка СПЛОШНАЯ по эллипсу губ. Альфа по разнице оставляла
        # полупрозрачные пиксели там, где разница слабая, и сквозь них
        # просвечивал сомкнутый рот исходного рисунка.
        alpha = ell_a.copy()
        if i <= 1:
            alpha[:] = 0.0          # сомкнутый рот — это сам кадр, накладка пустая
        out = np.dstack([np.asarray(crop, dtype=np.uint8),
                         (alpha * 255).astype(np.uint8)])
        Image.fromarray(out, "RGBA").save(vdir / f"v{i}.png")
        print(f"  v{i}: непрозрачных {float((alpha > 0.2).mean())*100:.0f}%")
    print(f"{vdir}  ${spent:.2f}")


if __name__ == "__main__":
    main()
