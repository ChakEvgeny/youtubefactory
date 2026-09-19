#!/usr/bin/env python3
"""Рисунки страниц дневника для Survivor's Notebook по раскадровке.

Отличия от explain_scenes.py: бумага в кадре — это и есть стиль (там её
запрещают), каждому кадру подаётся эталон стиля (styletest/ref.jpg), а
ключевой предмет из раскадровки получает ржавый акцент — один на кадр.
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

NEG = (" No text, no letters, no numbers, no handwriting, no labels, no logos, no watermark."
       " Faces small, in shadow or turned away. No blood, no wounds, no dead bodies.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--only", default="", help="id через запятую — перерисовать выборочно")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    d = Path(a.dir)
    style = (d / "style.txt").read_text(encoding="utf-8").strip()
    ref = [d / "styletest" / "ref.jpg"]
    fmt = json.loads((d / "format.json").read_text(encoding="utf-8")) if (d / "format.json").exists() else {}
    accent = fmt.get("accent", "red")       # у нуара — жёлтый
    src = d / "timed.json" if (d / "timed.json").exists() else d / "board.json"
    shots = json.loads(src.read_text(encoding="utf-8"))
    only = {int(x) for x in a.only.split(",") if x.strip().isdigit()}
    todo = [s for s in shots if s["kind"] == "scene" and (not only or s["id"] in only)]
    out = d / "scenes"; out.mkdir(exist_ok=True)
    cfg = Config()
    spent = {"usd": 0.0, "n": 0, "fail": []}

    def one(s):
        dst = out / f"{s['id']:03d}.jpg"
        if dst.exists() and not only:
            return
        # Акцент — только на отдельной вещи. На торосе, следе или поручне красный
        # мазок читается как кровь (брак в 7 кадрах из 129 на «Карлуке»).
        key = (f" The {s['key']} is the key object and the only {accent} thing in the drawing;"
               f" no {accent} smears on ground, walls, water or tracks." if s.get("key")
               else f" No {accent} colour anywhere in this drawing.")
        try:
            r = genimage.generate(cfg, f"{style} {s['visual']}.{key}{NEG}", dst, refs=ref)
            spent["usd"] += r.get("usd", 0.0); spent["n"] += 1
        except Exception as e:
            spent["fail"].append(f"{s['id']}: {str(e)[:80]}")
        time.sleep(1.5)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, todo))
    costs.log(costs.project_of(d), "scenes", "gemini-3.1-flash-image", spent["usd"], spent["n"], "сцен")
    print(f"сцен {spent['n']}/{len(todo)}, ${spent['usd']:.2f}, {int(time.time() - t0)} c")
    for f in spent["fail"]:
        print("  !", f)


if __name__ == "__main__":
    main()
