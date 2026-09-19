#!/usr/bin/env python3
"""Аутро Survivor's Notebook под конкретный ролик.

Последний кадр ролика перелистывается, под ним страница «The End» с рамками
под конечную заставку (композиция motion/src/scenes/NotebookOutro.tsx).
Кадр — картинка последней сцены или стоп-кадр из готового видео.

  python scripts/notebook_outro.py <папка ролика> --image scenes/112.jpg
  python scripts/notebook_outro.py <папка ролика> --video FILM.mp4   # берём последний кадр
  --zoom 1.08  если на последнем кадре в ролике уже был наезд камеры
"""
from __future__ import annotations
import argparse, json, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOTION = ROOT / "motion"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--image", default="")
    ap.add_argument("--video", default="")
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--seconds", type=float, default=6)
    a = ap.parse_args()
    d = Path(a.dir)
    pub = MOTION / "public" / "survival" / "_last"
    pub.mkdir(parents=True, exist_ok=True)
    dst = pub / f"{d.name}.jpg"
    if a.image:
        shutil.copy(d / a.image if not Path(a.image).is_absolute() else a.image, dst)
    elif a.video:
        v = d / a.video if not Path(a.video).is_absolute() else Path(a.video)
        subprocess.run(["ffmpeg", "-v", "error", "-sseof", "-0.1", "-i", str(v), "-frames:v", "1",
                        "-q:v", "2", str(dst), "-y"], check=True)
    else:
        raise SystemExit("нужен --image или --video")
    props = {"last": f"survival/_last/{dst.name}", "zoom": a.zoom, "seconds": a.seconds}
    out = d / "OUTRO.mp4"
    subprocess.run(["npx", "remotion", "render", "src/index.ts", "NotebookOutro", str(out),
                    f"--props={json.dumps(props)}", "--log=error"], cwd=MOTION, check=True)
    print(out)


if __name__ == "__main__":
    main()
