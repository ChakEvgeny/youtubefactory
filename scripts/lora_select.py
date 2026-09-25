#!/usr/bin/env python3
"""Отбор кадров для обучения: меньше, но чище.

Все кадры вышли в опубликованных роликах, то есть глазами уже приняты. Остаются
две беды, которые ловятся числом:

  - почти одинаковые кадры. Их в объяснялках много (одна и та же комната с чуть
    другим предметом). Модель на них переучивается и начинает рисовать этот
    кадр на любой запрос;
  - перекос по роликам. Самый длинный ролик даёт вдвое больше кадров, чем
    остальные, и его тема утягивает стиль на себя.

    python scripts/lora_select.py <папка датасета> --keep 250 --out <папка>
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np
from PIL import Image


def phash(p: Path, size: int = 8) -> np.ndarray:
    a = np.asarray(Image.open(p).convert("L").resize((size * 4, size * 4), Image.LANCZOS), float)
    from scipy.fftpack import dct
    d = dct(dct(a, axis=0, norm="ortho"), axis=1, norm="ortho")[:size, :size]
    return (d > np.median(d[1:, 1:])).flatten()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", type=int, default=250)
    ap.add_argument("--thr", type=int, default=6, help="ближе этого по хэшу — дубль")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    imgs = sorted(src.glob("*.jpg"))
    groups: dict[str, list[Path]] = {}
    for p in imgs:
        groups.setdefault(p.stem.rsplit("_", 1)[0], []).append(p)
    hashes = {p: phash(p) for p in imgs}

    kept, dropped = [], 0
    per = max(1, a.keep // max(1, len(groups)))
    for g in sorted(groups):
        # РАВНОМЕРНО по всей длине ролика, а не первые N подряд: иначе в
        # обучение уходит только начало каждого фильма, а концовки не видно
        src_list = groups[g]
        step = max(1, len(src_list) // per)
        order = src_list[::step] + [x for x in src_list if x not in src_list[::step]]
        taken: list[Path] = []
        for p in order:
            if any((hashes[p] != hashes[q]).sum() <= a.thr for q in taken):
                dropped += 1; continue
            taken.append(p)
            if len(taken) >= per:
                break
        kept += taken
        print(f"  {g[:38]:<38} взято {len(taken):>3} из {len(groups[g]):>3}")
    # если из-за дублей не добрали, добираем остатком, снова проверяя похожесть
    if len(kept) < a.keep:
        for p in imgs:
            if p in kept: continue
            if any((hashes[p] != hashes[q]).sum() <= a.thr for q in kept):
                continue
            kept.append(p)
            if len(kept) >= a.keep: break
    for p in kept[:a.keep]:
        shutil.copy(p, out / p.name)
        shutil.copy(p.with_suffix(".txt"), out / p.with_suffix(".txt").name)
    print(f"{out}: {len(kept[:a.keep])} кадров, отсеяно похожих {dropped}")


if __name__ == "__main__":
    main()
