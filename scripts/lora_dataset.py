#!/usr/bin/env python3
"""Датасет для обучения LoRA из УЖЕ ПРИНЯТЫХ кадров ролика.

Берутся только кадры, попавшие в смонтированный фильм: в папке лежат и
забракованные, а на них модель учится ровно нашему браку. Подписи не
выдумываются — это поле `visual`, по которому кадр и был нарисован, то есть
пара «картинка — текст» заведомо согласована.

Кадры ведущего исключены: под него отдельная LoRA с триггер-словом, иначе
стилевая модель начнёт подмешивать лицо в предметные кадры.

    python scripts/lora_dataset.py <папка ролика> [...] --out <папка> --trigger trmsemp
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from PIL import Image

STYLE = ("{trigger} style, a three-ink risograph print on cream paper — deep navy outlines, "
         "warm ochre, one signal red accent, halftone dot screens, visible paper grain")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--trigger", default="trmsemp")
    ap.add_argument("--style", default=STYLE)
    ap.add_argument("--style-file", default="", help="взять преамбулу из style.txt проекта")
    ap.add_argument("--max-side", type=int, default=1024)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n, skip = 0, {"нет файла": 0, "ведущий": 0, "карточка": 0, "карта": 0, "нет описания": 0}
    for d in a.dirs:
        D = Path(d)
        style = a.style
        if a.style_file and (D / a.style_file).exists():
            # преамбула — реальный стиль канала из проекта, а не пересказ по памяти
            style = "{trigger} style. " + (D / a.style_file).read_text(encoding="utf-8").strip()
        tm = json.loads((D / "timed.json").read_text(encoding="utf-8"))
        for s in tm:
            if s.get("kind") == "hero":
                skip["ведущий"] += 1; continue
            if s.get("kind") in ("card", "diagram"):
                skip["карточка"] += 1; continue      # схемы рисует Remotion
            # карты рисует notebook_map.py по Natural Earth, модель им не учат:
            # это контуры стран, а не предметный мир канала
            if re.search(r"\bmap\b|\bglobe\b", (s.get("visual") or ""), re.I) \
                    or "map_" in str(s.get("file") or ""):
                skip["карта"] += 1; continue
            f = D / (s.get("file") or f"stills/s{s['id']:03d}.jpg")
            if not f.exists():                      # раскладка объяснялок
                f = D / "scenes" / f"{s['id']:03d}.jpg"
            if not f.exists():
                skip["нет файла"] += 1; continue
            vis = (s.get("visual") or "").strip().rstrip(".")
            if not vis:
                skip["нет описания"] += 1; continue
            im = Image.open(f).convert("RGB")
            r = a.max_side / max(im.size)
            if r < 1:
                im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
            # ПОЛНОЕ имя папки, а не дата: три объяснялки вышли в один день,
            # и по дате кадры затирали друг друга — из 598 на диск легло 429
            stem = f"{D.name}_{s['id']}"
            im.save(out / f"{stem}.jpg", quality=95)
            (out / f"{stem}.txt").write_text(
                style.format(trigger=a.trigger).rstrip(". ") + ". " + vis + ".", encoding="utf-8")
            n += 1
    print(f"{out}: {n} пар «кадр — подпись»")
    for k, v in skip.items():
        if v: print(f"  пропущено, {k}: {v}")


if __name__ == "__main__":
    main()
