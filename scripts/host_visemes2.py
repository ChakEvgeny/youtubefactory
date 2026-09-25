#!/usr/bin/env python3
"""Набор артикуляций: варианты того же рисунка плюс накладка по фактической разнице.

Пять прошлых попыток провалились, потому что модель перерисовывала лицо целиком
и накладка тащила чужой тон кожи. Формулировка «то же самое изображение, изменён
только рот» это снимает: замерено — отличается 1,5% кадра, из них 79% в области
рта.

Накладка вырезается НЕ по эллипсу, а по тому, что реально изменилось, с жёстким
краем: подмешиваться нечему, значит и ореолу взяться неоткуда.

    python scripts/host_visemes2.py <папка> --frame anim/desk_refs/desk3.jpg \
        --name D2 --box 0.44,0.28,0.55,0.44
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from pipeline.config import Config  # noqa: E402
from pipeline.sources import genimage  # noqa: E402

SHAPES = {
    2: "his mouth is slightly open in a narrow horizontal slit, as if saying the sound E",
    3: "his mouth is open a moderate amount as if saying the sound A in ordinary speech, not shouting, showing a dark mouth opening with the upper teeth above it",
    4: "his mouth is open in a small round O, as if saying the sound O",
    5: "his mouth is open in a wide flat grin showing the upper teeth, as if saying the sound EE",
}
KEEP = ("The exact same illustration, unchanged in every way — same face, same beard, same hair, "
        "same glasses, same clothes, same background, same colours, same lines, same halftone "
        "texture, same framing. The only difference: {}. Do not move the head, do not redraw "
        "anything else at all.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--frame", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--box", default="", help="x0,y0,x1,y1; пусто — найти по разнице")
    a = ap.parse_args()

    P = Path(a.dir)
    src = P / a.frame
    base = Image.open(src).convert("RGB")
    W, H = base.size
    if not a.box:
        # разница теперь локальная, поэтому тёмное пятно отличий и есть рот:
        # руками задавать прямоугольник больше не нужно
        probe = P / "anim" / f"visemes{a.name}" / "_m3.jpg"
        probe.parent.mkdir(parents=True, exist_ok=True)
        if not probe.exists():
            genimage.generate(Config(), KEEP.format(SHAPES[3]), probe, refs=[src])
        v = np.asarray(Image.open(probe).convert("RGB").resize((W, H)), dtype=float)
        bb = np.asarray(base, dtype=float)
        dd = np.abs(v - bb).mean(axis=2)
        mm = (dd > 26) & ((v.mean(axis=2) < 150) | (bb.mean(axis=2) < 150))
        mm = ndimage.binary_closing(mm, np.ones((7, 7)))
        lab0, n0 = ndimage.label(mm)
        if not n0:
            raise SystemExit("рот не найден по разнице")
        sz0 = ndimage.sum(mm, lab0, range(1, n0 + 1))
        ys, xs = np.nonzero(lab0 == int(np.argmax(sz0)) + 1)
        pw, ph = (xs.max() - xs.min()) * 0.45, (ys.max() - ys.min()) * 0.45
        x0 = max(0, xs.min() - pw) / W; x1 = min(W, xs.max() + pw) / W
        y0 = max(0, ys.min() - ph) / H; y1 = min(H, ys.max() + ph) / H
        print(f"рот найден по разнице: {x0:.3f},{y0:.3f},{x1:.3f},{y1:.3f}")
    else:
        x0, y0, x1, y1 = [float(v) for v in a.box.split(",")]
    px = (int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
    vdir = P / "anim" / f"visemes{a.name}"
    vdir.mkdir(parents=True, exist_ok=True)
    (P / "anim" / f"{a.name}_patch.json").write_text(
        json.dumps({"patch": [x0, y0, x1, y1]}), encoding="utf-8")

    ref = np.asarray(base.crop(px), dtype=float)
    cfg = Config()
    spent = 0.0
    # сомкнутый рот — это сам кадр, накладка пустая
    for i in (0, 1):
        w, h = px[2] - px[0], px[3] - px[1]
        Image.fromarray(np.zeros((h, w, 4), dtype=np.uint8), "RGBA").save(vdir / f"v{i}.png")
    for i, shape in SHAPES.items():
        tmp = vdir / f"_m{i}.jpg"
        if not tmp.exists():
            r = genimage.generate(cfg, KEEP.format(shape), tmp, refs=[src])
            spent += r.get("usd", 0.0)
        var = Image.open(tmp).convert("RGB").resize((W, H))
        crop = np.asarray(var.crop(px), dtype=float)
        d = np.abs(crop - ref).mean(axis=2)
        # берём только САМ РОТ: тёмные губы и отверстие. Если брать всю разницу,
        # в накладку попадает борода, которую модель слегка перерисовала, и её
        # другой тон виден прямоугольником по краю
        dark_new = crop.mean(axis=2) < 150
        dark_old = ref.mean(axis=2) < 150
        m = (d > 26) & (dark_new | dark_old)
        m = ndimage.binary_closing(m, np.ones((5, 5)))
        m = ndimage.binary_fill_holes(m)
        m = ndimage.binary_dilation(m, np.ones((3, 3)))
        lab, n = ndimage.label(m)
        if n:
            sizes = ndimage.sum(m, lab, range(1, n + 1))
            m = lab == (int(np.argmax(sizes)) + 1)      # один кусок: сам рот
        alpha = (m * 255).astype(np.uint8)
        out = np.dstack([np.asarray(var.crop(px), dtype=np.uint8), alpha])
        Image.fromarray(out, "RGBA").save(vdir / f"v{i}.png")
        print(f"  v{i}: накладка {float(m.mean())*100:4.0f}% прямоугольника")
    print(f"{vdir}  ${spent:.2f}")


if __name__ == "__main__":
    main()
