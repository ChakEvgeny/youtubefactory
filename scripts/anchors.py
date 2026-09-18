#!/usr/bin/env python3
"""Якоря ролика: персонажи и опорные кадры локаций.

Смысл: зафиксировать внешность людей и геометрию мира ОДИН раз, до раскадровки.
Все последующие кадры генерируются с этими файлами в референсах, иначе персонаж
и геометрия плывут от кадра к кадру.

Читает characters.json и locations.json из папки проекта (списки {key,name,prompt}).
Ведущему персонажу (--lead, по умолчанию первый) делает три ракурса, остальным один.
Локациям — чистые плиты без людей.
"""
from __future__ import annotations
import argparse, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from PIL import Image, ImageDraw, ImageFont
from pipeline.config import Config
from pipeline import costs
from pipeline.sources import genimage

NOTEXT = (" No readable text anywhere in the frame: no numbers, no letters, no labels, no signage. "
          "Any paper or sign must be blank or turned away from camera."
          " One single continuous photograph: one frame only, no diptych, no split panels, "
          "no collage, no borders, no captions, no watermark.")
SHEET = " Plain neutral background, even soft lighting, full figure."


def font(sz):
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", sz)


def sheet(files, out, cols=3, tw=440):
    ok = [f for f in files if Path(f).exists()]
    if not ok:
        return
    rows = (len(ok) + cols - 1) // cols
    th = int(tw * 9 / 16)
    im = Image.new("RGB", (cols * tw, rows * (th + 30)), (18, 18, 20))
    d = ImageDraw.Draw(im)
    for i, f in enumerate(ok):
        x, y = (i % cols) * tw, (i // cols) * (th + 30)
        im.paste(Image.open(f).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        d.text((x + 8, y + th + 6), Path(f).stem, font=font(18), fill=(215, 215, 215))
    im.save(out, quality=92)
    print("  лист:", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--style", required=True, help="общий стилевой префикс")
    ap.add_argument("--lead", default="", help="key ведущего персонажа (по умолчанию первый)")
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("--fallback", default="gemini-3.1-flash-image", help="модель при исчерпании квоты")
    a = ap.parse_args()
    d = Path(a.dir)
    out = d / "anchors"
    out.mkdir(parents=True, exist_ok=True)
    cfg = Config()

    def load(name):
        p = d / name
        if not p.exists():
            return []
        j = json.loads(p.read_text(encoding="utf-8"))
        return [x for x in j if not x.get("dropped")]

    chars, locs = load("characters.json"), load("locations.json")
    if not chars and not locs:
        sys.exit(f"нет characters.json / locations.json в {d}")
    lead = a.lead or (chars[0]["key"] if chars else "")
    spent = {"usd": 0.0, "fail": []}

    def gen(name, prompt, refs=None):
        dst = out / f"{name}.jpg"
        if dst.exists():
            return dst
        for model in (a.model, a.fallback):
            try:
                r = genimage.generate(cfg, a.style + " " + prompt + NOTEXT, dst,
                                      refs=refs, model=model)
                spent["usd"] += r.get("usd", 0.0)
                return dst
            except Exception as e:
                msg = str(e)
                if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                    continue          # квота pro кончилась — тем же промптом на flash
                spent["fail"].append(f"{name}: {msg[:90]}")
                return dst
        spent["fail"].append(f"{name}: квота исчерпана на обеих моделях")
        return dst

    # 1) персонажи: ведущему три ракурса, остальным один
    jobs = []
    for c in chars:
        base = c["prompt"]
        if c["key"] == lead:
            jobs += [
                (f"char_{c['key']}", base + SHEET),
                (f"char_{c['key']}_hands", base + " Extreme close-up of the hands only, "
                                                  "no face in frame, shallow depth of field."),
                (f"char_{c['key']}_wide", base + " A small distant figure in the empty "
                                                 "landscape of the story, seen from far away."),
            ]
        else:
            jobs.append((f"char_{c['key']}", base + SHEET))
    with ThreadPoolExecutor(max_workers=3) as ex:
        char_files = list(ex.map(lambda j: gen(*j), jobs))

    # 2) локации — чистые плиты, без людей и без следов людей
    with ThreadPoolExecutor(max_workers=3) as ex:
        loc_files = list(ex.map(
            lambda l: gen("loc_" + l["key"], l["prompt"] + " No people in frame at all."), locs))

    sheet(char_files, out / "sheet_characters.jpg", cols=3)
    sheet(loc_files, out / "sheet_locations.jpg", cols=3)
    print(f"персонажи {sum(1 for f in char_files if f.exists())}/{len(jobs)}, "
          f"локации {sum(1 for f in loc_files if f.exists())}/{len(locs)}, ${spent['usd']:.2f}")
    costs.log(costs.project_of(d), "anchors", a.model, spent["usd"],
              len(jobs) + len(locs), "картинок")
    for f in spent["fail"]:
        print("  !", f)


if __name__ == "__main__":
    main()
