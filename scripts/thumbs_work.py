#!/usr/bin/env python3
"""Обложки канала Terms of Employment: раскладки из docs/thumbnail_standard.md,
текст рисуется кодом, поля и пересечения проверяются числом.

Жёсткие правила канала:
  - поле не меньше MARGIN px от края кадра и от фигуры персонажа;
  - высота заглавной не ниже 90 px (иначе сокращать текст, а не кегль);
  - подложка под текстом — сплошной navy, не полупрозрачный серый;
  - текст никогда не пересекается с фигурой и не выходит за поля.

  python scripts/thumbs_work.py <папка проекта>
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
MARGIN = 60
CAP_MIN = 90
NAVY, OCHRE, RED, PAPER = (0x1B, 0x2A, 0x5E), (0xC8, 0x9A, 0x3C), (0xE4, 0x53, 0x3A), (0xF2, 0xEC, 0xE0)
FONTS = Path.home() / ".fonts"
AB = lambda s: ImageFont.truetype(str(FONTS / "ArchivoBlack.ttf"), s)


def fit(words, max_w, max_h=None, start=340, shrink=1.0):
    s = int(start)
    while s > 16:
        f = AB(s)
        wide = max(f.getbbox(w)[2] - f.getbbox(w)[0] for w in words)
        tall = max(f.getbbox(w)[3] - f.getbbox(w)[1] for w in words)
        if wide <= max_w and (max_h is None or tall * len(words) * 1.22 <= max_h):
            break
        s -= 2
    f = AB(max(16, int(s * shrink)))
    return f, f.getbbox("H")[3] - f.getbbox("H")[1]


def put(d, xy, text, f, fill):
    """От верхней кромки глифов: у базовой линии запас непредсказуем и текст уезжает."""
    bb = f.getbbox(text)
    d.text((xy[0] - bb[0], xy[1] - bb[1]), text, font=f, fill=fill)
    return (xy[0], xy[1], xy[0] + bb[2] - bb[0], xy[1] + bb[3] - bb[1])


def figure_left(img: Image.Image, x_from: int) -> int:
    """Левая граница фигуры персонажа в кадре — по не-бумажным пикселям."""
    a = np.asarray(img.convert("RGB"), dtype=float)[:, x_from:]
    m = np.linalg.norm(a - np.array(PAPER), axis=2) > 110
    cols = np.where(m.mean(axis=0) > 0.04)[0]
    return x_from + int(cols.min()) if len(cols) else W


def check(name, boxes, fig_x=None):
    """Числовая проверка: поля от краёв и зазор до фигуры."""
    bad = []
    for b in boxes:
        if b[0] < MARGIN or b[1] < MARGIN or b[2] > W - MARGIN or b[3] > H - MARGIN:
            bad.append(f"выходит за поле {MARGIN} px: {tuple(int(v) for v in b)}")
        if fig_x is not None and b[2] > fig_x - MARGIN:
            bad.append(f"ближе {MARGIN} px к фигуре: правый край {int(b[2])}, фигура с {fig_x}")
    print(f"  {name}: " + ("OK" if not bad else "; ".join(bad)))
    return not bad



def crop_to(im, box):
    """Кадрирование к объекту: по эталону он занимает не меньше трети кадра,
    а исходный кадр ролика почти всегда общий план. box — доли ширины и высоты."""
    if not box:
        return im
    W0, H0 = im.size
    x0, y0, x1, y1 = box
    return im.crop((int(x0 * W0), int(y0 * H0), int(x1 * W0), int(y1 * H0)))


def host(frac):
    im = Image.open(HOST).convert("RGB")
    r = H / im.height
    im = im.resize((int(im.width * r), H), Image.LANCZOS)
    return im.crop((im.width - int(W * frac), 0, im.width, H))


DEFAULT = {"a": {"big": "0", "label": "DAYS"},
           "b": {"words": ["FIRED", "WITHOUT", "WARNING"]},
           "c": {"lines": ["GONE BY", "LUNCH"], "bg": "styletest/riso_lock2_k1_empty_desk.jpg"},
           "d": {"lines": ["NOT A", "LOOPHOLE"], "bg": "stills/s926.jpg"}}


def main():
    global HOST
    prj = Path(sys.argv[1]); B, T = prj / "brand", prj / "thumbs"
    T.mkdir(exist_ok=True); HOST = B / "thumb_template.jpg"
    # Тексты и фоны — из thumbs.json ролика: раскладки у канала постоянные,
    # меняется только содержимое, и вшивать его в код нельзя.
    spec = DEFAULT
    if (prj / "thumbs.json").exists():
        import json
        spec = {**DEFAULT, **json.loads((prj / "thumbs.json").read_text(encoding="utf-8"))}
    ok_all = True

    # A — число-герой: воздух вокруг блока, текст не подходит к фигуре
    a = Image.new("RGB", (W, H), PAPER); hx = int(W * 0.62)
    a.paste(host(0.38), (hx, 0)); d = ImageDraw.Draw(a)
    figx = figure_left(a, hx)
    tw = figx - MARGIN - MARGIN
    big, lab = spec["a"]["big"], spec["a"]["label"]
    f0, _ = fit([big], tw, int(H * 0.46), start=430)
    fD, capA = fit([lab], tw, int(H * 0.22))
    h0 = f0.getbbox(big)[3] - f0.getbbox(big)[1]
    hD = fD.getbbox(lab)[3] - fD.getbbox(lab)[1]
    gap = 34
    top = (H - (h0 + gap + hD)) // 2
    boxes = [put(d, (MARGIN, top), big, f0, RED),
             put(d, (MARGIN, top + h0 + gap), lab, fD, NAVY)]
    a.save(T / "thumb_a_number.jpg", quality=92)
    ok_all &= check(f"A (заглавная {capA} px)", boxes, figx)

    # B — колонка: блок левее, кегль на 10% меньше
    # Персонажу отдано меньше ширины, чем в A: иначе колонка из трёх слов не
    # набирает заглавную 90 px. Просьбу «уменьшить кегль на 10%» не исполняем —
    # наложение на лицо снято геометрией (текст обрезан по фигуре минус поле),
    # а кегль ниже 90 px нарушил бы docs/thumbnail_standard.md.
    b = Image.new("RGB", (W, H), PAPER); hx = int(W * 0.70)
    b.paste(host(0.30), (hx, 0)); d = ImageDraw.Draw(b)
    figx = figure_left(b, hx)
    tw = figx - MARGIN - MARGIN
    words = spec["b"]["words"]
    fB, capB = fit(words, tw, H - 2 * MARGIN)
    hw = max(fB.getbbox(w)[3] - fB.getbbox(w)[1] for w in words)
    step = hw * 1.24
    top = (H - (step * 3 - (step - hw))) // 2
    cols = [NAVY] * (len(words) - 1) + [RED]
    boxes = [put(d, (MARGIN, top + i * step), w, fB, c)
             for i, (w, c) in enumerate(zip(words, cols))]
    b.save(T / "thumb_b_column.jpg", quality=92)
    ok_all &= check(f"B (заглавная {capB} px)", boxes, figx)

    # C — объект: сплошная navy-плашка вместо грязной полупрозрачной серой
    c = crop_to(Image.open(prj / spec["c"]["bg"]).convert("RGB"), spec["c"].get("crop"))
    r = max(W / c.width, H / c.height)
    c = c.resize((int(c.width * r), int(c.height * r)), Image.LANCZOS)
    c = c.crop(((c.width - W) // 2, 0, (c.width - W) // 2 + W, H))
    lines = spec["c"]["lines"]
    fC, capC = fit(lines, W - 2 * MARGIN, int(H * 0.38))
    hl = max(fC.getbbox(l)[3] - fC.getbbox(l)[1] for l in lines)
    step = hl * 1.2
    block = step * 2 - (step - hl)
    # +4 px, как в раскладке D: без запаса нижняя строка садится ровно на
    # границу поля и проверка валится на округлении
    band = int(block + 2 * MARGIN) + 4
    d = ImageDraw.Draw(c)
    d.rectangle([0, H - band, W, H], fill=NAVY)
    top = H - band + MARGIN
    boxes = [put(d, (MARGIN, top + i * step), l, fC, col)
             for i, (l, col) in enumerate(zip(lines, [PAPER, RED]))]
    c.save(T / "thumb_c_object.jpg", quality=92)
    ok_all &= check(f"C (заглавная {capC} px)", boxes)

    # D — отрицание очевидной причины: зритель уверен, что увольнение без
    # предупреждения это лазейка, а в ролике это норма по умолчанию. Приём
    # обязателен по docs/thumbnails.md: минимум два варианта из четырёх должны
    # спорить со зрителем, а не описывать ролик
    # Раскладка «текст во всю ширину снизу», как у C: в колонке рядом с фигурой
    # слово LOOPHOLE даёт заглавную 84 px при минимуме 90, а по правилу канала
    # сокращают текст или дают ему ширину, но не кегль
    e = crop_to(Image.open(prj / spec["d"]["bg"]).convert("RGB"), spec["d"].get("crop"))
    r = max(W / e.width, H / e.height)
    e = e.resize((int(e.width * r), int(e.height * r)), Image.LANCZOS)
    e = e.crop(((e.width - W) // 2, 0, (e.width - W) // 2 + W, H))
    lines = spec["d"]["lines"]
    fE, capE = fit(lines, W - 2 * MARGIN, int(H * 0.42))
    hl = max(fE.getbbox(l)[3] - fE.getbbox(l)[1] for l in lines)
    step = hl * 1.2
    # +4 px: без запаса нижняя строка садится ровно на границу поля и проверка
    # валится на округлении
    band = int(step * 2 - (step - hl) + 2 * MARGIN) + 4
    d = ImageDraw.Draw(e)
    d.rectangle([0, H - band, W, H], fill=NAVY)
    top = H - band + MARGIN
    boxes = [put(d, (MARGIN, int(top + i * step)), l, fE, col)
             for i, (l, col) in enumerate(zip(lines, [PAPER, RED]))]
    e.save(T / "thumb_d_denial.jpg", quality=92)
    ok_all &= check(f"D (заглавная {capE} px)", boxes)

    for f in ("thumb_a_number", "thumb_b_column", "thumb_c_object", "thumb_d_denial"):
        Image.open(T / f"{f}.jpg").resize((210, 118), Image.LANCZOS).save(T / f"{f}_210.jpg", quality=90)
    print("все поля в норме" if ok_all else "есть нарушения полей")


if __name__ == "__main__":
    main()
