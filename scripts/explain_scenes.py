#!/usr/bin/env python3
"""Генерация рисованных сцен объясняющего ролика по board.json.

Схемы здесь не трогаем — их рисует Remotion. Стиль берётся из style.txt
папки проекта, он же служит гарантией единообразия всех кадров.
"""
from __future__ import annotations
import argparse, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from pipeline.config import Config
from pipeline.sources import genimage
from pipeline import costs

NEG = (" No text, no letters, no numbers, no labels, no logos, no watermark, "
       "no photo of paper, no desk or table visible.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--model", default="gemini-3.1-flash-image")
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--pause", type=float, default=4.0)
    a = ap.parse_args()
    d = Path(a.dir)
    style = (d / "style.txt").read_text(encoding="utf-8").strip()
    # timed.json — живой файл: в нём уже прорежены схемы (diagram_trim.py) и
    # проставлены bg_id. board.json — исходная раскадровка, она устаревает.
    src = d / "timed.json" if (d / "timed.json").exists() else d / "board.json"
    shots = json.loads(src.read_text(encoding="utf-8"))
    only = {int(x) for x in a.only.split(",") if x.strip().isdigit()}
    todo = [s for s in shots if s["kind"] == "scene" and (not only or s["id"] in only)]
    out = d / "scenes"; out.mkdir(exist_ok=True)
    cfg = Config()
    spent = {"usd": 0.0, "fail": []}
    t0 = time.time()

    def one(s):
        dst = out / f"{s['id']:03d}.jpg"
        if dst.exists():
            return dst
        try:
            r = genimage.generate(cfg, style + " " + (s.get("visual") or "") + NEG,
                                  dst, model=a.model, aspect="16:9")
            spent["usd"] += r.get("usd", 0.0)
        except Exception as e:
            spent["fail"].append(f"{s['id']}: {str(e)[:70]}")
        time.sleep(a.pause)
        return dst

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        done = [f for f in ex.map(one, todo) if f.exists()]
    costs.log(costs.project_of(d), "scenes", a.model, spent["usd"], len(done), "сцен")
    print(f"сцен {len(done)}/{len(todo)}, ${spent['usd']:.2f}, {int(time.time()-t0)} c")
    for f in spent["fail"][:8]:
        print("  !", f)


if __name__ == "__main__":
    main()
