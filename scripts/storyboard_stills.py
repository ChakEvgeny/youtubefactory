#!/usr/bin/env python3
"""Раскадровка картинками: одна картинка на каждый кадр ДО генерации видео.

Смысл стадии — увидеть весь ролик за центы и поправить фон, персонажа и
композицию до того, как тратиться на Veo. Утверждённые картинки потом идут
в image-to-video как первый кадр.

Правила рендера, зашитые в промпт: нейросеть не рисует текст и цифры;
кадры типа card рисуем сами в PIL; лицо героя показываем редко.
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
from pipeline import costs
from pipeline.sources import genimage

NOTEXT = (" No readable text anywhere in the frame: no numbers, no letters, no labels, no signage, "
          "no screen text. Any paper, screen or sign must be blank, blurred or turned away from camera.")

STYLES = {
 "survival": ("Photoreal cinematic still, 1920s Arctic expedition, overcast polar daylight, "
              "desaturated palette of bone white, wet gravel grey, dark seal-brown and one warm "
              "lamp accent. Shot on 35mm, shallow depth of field, natural light only. "
              "The woman's face is almost never visible: prefer hands, back, silhouette, wide "
              "figure in landscape, or object detail."),
 "work": ("A three-ink risograph print on cream paper, and only three inks. Deep navy #1B2A5E for "
          "outlines, dark masses and the settled lower third; warm ochre #C89A3C for the main colour "
          "and all light; signal red #E4533A as an accent only, never more than a tenth of the frame. "
          "Dense confident outlines of one weight, halftone dot screens for tone, a deliberate one to "
          "two pixel misregistration where inks meet, visible paper grain. Fills are solid ink, never "
          "a pale halftone — a grey or lilac mass is a failure. Everyone except the presenter has a "
          "completely blank head with no facial features."),
 "heists": ("Photoreal cinematic still, 1984 American suburbia and television studio, warm tungsten "
            "and cathode-ray glow, palette of deep navy, warm off-white, worn brown, one red accent. "
            "Shot on 35mm, shallow depth of field. Faces used sparingly, prefer hands, back of head, "
            "objects and wide shots."),
}


def font(sz, mono=True):
    p = ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if mono
         else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    return ImageFont.truetype(p, sz)


def card(text: str, out: Path, w=1376, h=768):
    """Кадр-карточка: текст печатаем сами, нейросеть к нему не подпускаем."""
    im = Image.new("RGB", (w, h), (11, 15, 20))
    d = ImageDraw.Draw(im)
    words, lines, cur = text.split(), [], ""
    f = font(54)
    for wd in words:
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=f) > w - 220 and cur:
            lines.append(cur); cur = wd
        else:
            cur = t
    if cur:
        lines.append(cur)
    y = h // 2 - len(lines) * 40
    for ln in lines:
        d.text(((w - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=(245, 244, 240))
        y += 80
    d.rectangle([w // 2 - 150, y + 20, w // 2 + 150, y + 26], fill=(46, 229, 157))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=92)
    return {"file": str(out), "usd": 0.0, "model": "pil-card"}


def sheet(files: list[Path], out: Path, cols=6, tw=320):
    ok = [f for f in files if f.exists()]
    if not ok:
        return
    rows = (len(ok) + cols - 1) // cols
    th = int(tw * 9 / 16)
    im = Image.new("RGB", (cols * tw, rows * (th + 26)), (18, 18, 20))
    d = ImageDraw.Draw(im)
    for i, f in enumerate(ok):
        x, y = (i % cols) * tw, (i // cols) * (th + 26)
        im.paste(Image.open(f).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        d.text((x + 6, y + th + 4), f.stem, font=font(16), fill=(210, 210, 210))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--lane", choices=list(STYLES), required=True)
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("--limit", type=int, default=0, help="сделать только первые N кадров (проба стиля)")
    ap.add_argument("--only", default="", help="номера через запятую — перегенерировать выборочно")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--hero-anchor", default="hero_back")
    ap.add_argument("--pause", type=float, default=6.0, help="пауза между запросами, сек")
    a = ap.parse_args()

    d = Path(a.dir)
    shots = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    if a.limit:
        shots = shots[:a.limit]
    only = {int(x) for x in a.only.split(",") if x.strip().isdigit()}
    if only:
        shots = [s for s in shots if s["id"] in only]

    out = d / "storyboard"
    out.mkdir(exist_ok=True)
    cfg = Config()
    # стиль проекта важнее стиля дорожки: дорожечные пресеты сняты с прошлых
    # фильмов и тащат чужую эпоху. style.txt кладём в папку проекта.
    sp = d / "style.txt"
    style = sp.read_text(encoding="utf-8").strip() if sp.exists() else STYLES[a.lane]
    print("стиль:", style[:80], "…", "(из style.txt)" if sp.exists() else "(пресет дорожки)")
    anch = d / "anchors"
    hero_ref = anch / (a.hero_anchor + ".jpg")
    if not hero_ref.exists():
        print(f"нет якоря героя: {hero_ref}")
    # карта «номер кадра -> локация» из locations.json
    loc_of, loc_plate, loc_rule = {}, {}, {}
    lp = d / "locations.json"
    if lp.exists():
        for l in json.loads(lp.read_text(encoding="utf-8")):
            plate = anch / f"loc_{l['key']}.jpg"
            loc_plate[l["key"]] = plate if plate.exists() else None
            loc_rule[l["key"]] = l.get("rule", "")
            for n in l.get("shots") or []:
                loc_of[int(n)] = l["key"]
    rules = ""
    rp = d / "style_notes.md"
    extra = (d / "prompt_rules.txt")
    if extra.exists():
        rules = extra.read_text(encoding="utf-8").strip()
    spent = {"usd": 0.0, "fail": 0}

    def one(s):
        dst = out / f"{s['id']:03d}.jpg"
        if dst.exists():
            return dst
        if s.get("kind") == "black":
            # пауза: чистый чёрный кадр, генерировать нечего
            Image.new("RGB", (1376, 768), (0, 0, 0)).save(dst, quality=95)
            return dst
        if s.get("kind") == "card" or (s.get("card_text") or "").strip():
            card(s.get("card_text") or s.get("visual", ""), dst)
            return dst
        key = s.get("loc") or loc_of.get(s["id"])
        parts = [style]
        if rules:
            parts.append(rules)
        if key and loc_rule.get(key):
            parts.append(loc_rule[key])
        if s.get("phase_rule"):
            parts.append(s["phase_rule"])
        parts.append(s["visual"].rstrip(".") + ".")
        # в безлюдный кадр не подаём якорь человека: модель послушно впишет его туда,
        # где его быть не должно. Персонажи берутся из поля chars (scripts/shot_refs.py).
        plate = loc_plate.get(key)
        if s.get("no_camp") and key:
            clean = anch / f"loc_{key}_empty.jpg"
            plate = clean if clean.exists() else None
        char_refs = []
        if not s.get("no_person"):
            for ck in (s.get("chars") or [])[:2]:
                f = anch / f"char_{ck}.jpg"
                if f.exists():
                    char_refs.append(f)
            if not char_refs and hero_ref.exists() and s.get("chars") is None:
                char_refs = [hero_ref]      # старые проекты без разметки chars
        else:
            parts.append("Nobody in frame at all: no person, no figure, no silhouette.")
        if s.get("no_camp"):
            parts.append("Nothing man-made in frame: no tent, no camp, no crates, no ropes.")
        # не больше трёх референсов: модель берёт первые три
        refs = [f for f in (char_refs + [plate]) if f and Path(f).exists()][:3] or None
        prompt = " ".join(parts) + NOTEXT
        delay = a.pause
        for attempt in range(6):
            try:
                r = genimage.generate(cfg, prompt, dst, refs=refs, model=a.model, retries=0)
                spent["usd"] += r.get("usd", 0.0)
                time.sleep(a.pause)
                return dst
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    time.sleep(delay)
                    delay = min(delay * 2, 90)
                    continue
                spent["fail"] += 1
                print(f"  ! кадр {s['id']}: {msg[:90]}", flush=True)
                return dst
        spent["fail"] += 1
        print(f"  ! кадр {s['id']}: лимит запросов не отпустил", flush=True)
        return dst
        return dst

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        files = list(ex.map(one, shots))
    done = [f for f in files if f.exists()]

    for i in range(0, len(done), 36):
        sheet(done[i:i + 36], out / f"sheet_{i//36+1:02d}.jpg")

    md = ["# Раскадровка картинками", "",
          f"Кадров {len(shots)}, готово {len(done)}, ошибок {spent['fail']}, "
          f"потрачено ${spent['usd']:.2f}, время {int(time.time()-t0)} с.", "",
          "Смотреть контактные листы sheet_NN.jpg. Номер файла = номер кадра.",
          "Что не так — назовите номера, перегенерирую точечно:",
          "`scripts/storyboard_stills.py <папка> --lane <lane> --only 12,44,71`", "",
          "| # | время | тип | что видим | что слышно |", "|---:|---|---|---|---|"]
    for s in shots:
        mm = lambda x: f"{int(x)//60:02d}:{int(x)%60:02d}"
        md.append(f"| {s['id']:03d} | {mm(s['t_in'])} | {s.get('kind','')} | "
                  f"{(s.get('visual') or '').replace('|','/')[:110]} | "
                  f"{(s.get('narr') or '').replace('|','/')[:90]} |")
    (out / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"готово: {len(done)}/{len(shots)} кадров, ${spent['usd']:.2f}, ошибок {spent['fail']}")
    costs.log(costs.project_of(d), "stills", "gemini-image", spent["usd"],
              len(done), "кадров")


if __name__ == "__main__":
    main()
