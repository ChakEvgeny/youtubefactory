#!/usr/bin/env python3
"""Проба стилей: одни и те же кадры в нескольких стилях + подписанный лист.

Стиль выбирается сравнением одинаковых сюжетов, иначе сравниваешь сюжеты,
а не стили. Описание пробы — <dir>/styletest/probe.json:

  {"neg": "...", "styles": {"notebook": "...", ...}, "shots": {"k1": "...", ...}}

  python scripts/style_probe.py /mnt/d/youtube/output/survival/2026-09-18_karluk
"""
from __future__ import annotations
import argparse, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from PIL import Image, ImageDraw, ImageFont
from pipeline.config import Config
from pipeline.sources import genimage
from pipeline import costs

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def sheet(out: Path, styles: list[str], shots: list[str], cell_w: int = 640, tag: str = ""):
    cell_h = cell_w * 9 // 16
    pad, lab = 12, 40
    W = pad + len(shots) * (cell_w + pad)
    H = pad + len(styles) * (cell_h + lab + pad)
    img = Image.new("RGB", (W, H), (24, 24, 24))
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype(FONT, 22)
    except OSError:
        f = ImageFont.load_default()
    for r, st in enumerate(styles):
        y = pad + r * (cell_h + lab + pad)
        for c, sh in enumerate(shots):
            x = pad + c * (cell_w + pad)
            p = out / f"{st}_{sh}.jpg"
            d.text((x, y + 8), f"{st} · {sh}", fill=(235, 235, 235), font=f)
            if p.exists():
                img.paste(Image.open(p).convert("RGB").resize((cell_w, cell_h)), (x, y + lab))
    dst = out / f"sheet_{tag}.jpg" if tag else out / "sheet.jpg"
    img.save(dst, quality=88)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--model", default="gemini-3.1-flash-image")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--probe", default="probe.json", help="файл пробы в styletest/")
    a = ap.parse_args()
    out = Path(a.dir) / "styletest"
    probe = json.loads((out / a.probe).read_text(encoding="utf-8"))
    styles, shots, neg = probe["styles"], probe["shots"], probe.get("neg", "")
    # эталон стиля: картинки, на которые модель равняется во всех кадрах
    refs = [out / r for r in probe.get("refs", [])] or None
    jobs = [(st, sh) for st in styles for sh in shots]
    cfg = Config()
    spent = {"usd": 0.0, "n": 0, "fail": []}

    def one(job):
        st, sh = job
        dst = out / f"{st}_{sh}.jpg"
        if dst.exists():
            return
        try:
            r = genimage.generate(cfg, f"{styles[st]} {shots[sh]} {neg}", dst, refs=refs, model=a.model)
            spent["usd"] += r.get("usd", 0.0); spent["n"] += 1
        except Exception as e:
            spent["fail"].append(f"{st}_{sh}: {str(e)[:80]}")
        time.sleep(2)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, jobs))
    if spent["n"]:
        costs.log(costs.project_of(Path(a.dir)), "styletest", a.model, spent["usd"], spent["n"], "проб")
    print(f"новых {spent['n']}/{len(jobs)}, ${spent['usd']:.2f}, {int(time.time() - t0)} c")
    for f in spent["fail"]:
        print("  !", f)
    print(sheet(out, list(styles), list(shots), tag=Path(a.probe).stem.removeprefix("probe").strip("_")))


if __name__ == "__main__":
    main()
