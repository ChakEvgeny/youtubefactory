#!/usr/bin/env python3
"""Вариант кадра: то же изображение, изменена одна вещь.

Пары «та же комната, меняется только стул» и «те же часы, добавился сектор»
двумя независимыми генерациями не получаются: модель каждый раз рисует новую
комнату. Здесь исходный кадр подаётся референсом, и просят изменить ровно одно —
та же техника, что на артикуляциях рта.

    python scripts/work_variant.py <папка> --from 969 --to 970 \
        --change "the chair is now tilted with its back pushed against the table edge"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from pipeline.config import Config  # noqa: E402
from pipeline.sources import genimage  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--from", dest="src", type=int, required=True)
    ap.add_argument("--to", dest="dst", type=int, required=True)
    ap.add_argument("--change", required=True, help="что именно меняется, английским")
    a = ap.parse_args()

    P = Path(a.dir)
    src = P / "stills" / f"s{a.src}.jpg"
    if not src.exists():
        sys.exit(f"нет исходного кадра {src}")
    out = P / "stills" / f"s{a.dst}.jpg"
    prompt = (f"The exact same illustration, unchanged in every way — same room, same camera "
              f"position, same furniture, same light, same colours, same lines, same texture. "
              f"The only difference: {a.change}. Do not move the camera, do not redraw anything "
              f"else, do not add or remove any other object.")
    r = genimage.generate(Config(), prompt, out, refs=[src])
    print(f"{out}  ${r.get('usd', 0.0):.2f}")

    sb = json.loads((P / "storyboard.json").read_text(encoding="utf-8"))
    for s in sb:
        if s["id"] == a.dst:
            s["variant_of"] = a.src
            s["visual"] = f"вариант кадра {a.src}: {a.change}"
            key = f"{s.get('kind')}|{s['visual']}|{s.get('file') or ''}"
            s["drawn"] = hashlib.sha1(key.encode()).hexdigest()[:10]
    (P / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
