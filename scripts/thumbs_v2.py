#!/usr/bin/env python3
"""Обложки по эталону docs/thumbnail_standard.md: 3 варианта на ролик + автопроверка.

Картинка — тем же генератором и стилем канала, что кадры роликов (с ночным /
контрастным светом), текст — кодом. Раскладка постоянная внутри канала: объект
справа крупно, текст — колонка слева (Why&How — на кремовой плашке).

Автопроверка: вариант уменьшается до 210×118, Opus без подсказки читает текст и
называет объект; вторым вызовом сверяем названный объект с задуманным. Текст не
прочитан или объект не тот — перегенерация (до 3 попыток).

  python scripts/thumbs_v2.py [канал ...] [--only слаг,слаг]
Спецификация: /mnt/d/youtube/thumbs/spec.json. Результат: /mnt/d/youtube/thumbs/<канал>/<слаг>/.
"""
from __future__ import annotations
import argparse, base64, difflib, io, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pipeline.config import Config
from pipeline.sources import genimage
from pipeline.util import claude_cost, parse_json_block
from pipeline import costs

BASE = Path("/mnt/d/youtube/thumbs")
W, H = 1280, 720
F = Path.home() / ".fonts"
MODEL = "claude-opus-5"
CAP_MIN = 90           # заглавная ≥ 90 px (эталон — Larson, ~101 px)

COMPOSE = (" Composition for a YouTube thumbnail: ONE main subject, large and close, occupying the right "
           "half of the frame and at least a third of the whole image; the left 45% is empty dark background. "
           "Full-bleed image edge to edge: no border, no panel frame, no paper margins. "
           "No text, no letters, no numbers, no logos, no signs, no watermark. No recognisable real person's face.")
STYLE = {
    "heists": {
        "prompt": ("Hard-boiled noir comic panel, heavy black brush ink, stark chiaroscuro, hard side light "
                   "from one direction, deep black shadows, risograph grain; palette black, cool grey and a "
                   "single warm mustard-yellow accent on the main subject."),
        "ref": "/mnt/nas/output/heists/2026-09-18_salad-oil-swindle/styletest/ref.jpg",
        "font": "Anton.ttf", "fill": (242, 192, 48), "stroke": (8, 8, 8), "plate": None, "dark": True},
    "survival": {
        "prompt": ("Editorial ink illustration: confident pen drawing, dense cross-hatching, bold black contours; "
                   "dramatic NIGHT scene, deep midnight-blue and black background instead of paper, moonlight "
                   "or lantern light on the subject; palette black, deep blue and one small red accent."),
        "ref": None,
        "font": "RobotoSerifCondBlack.ttf", "fill": (241, 230, 207), "stroke": (6, 8, 16),
        "accent": (214, 58, 44), "plate": None, "dark": True},
    "explain": {
        "prompt": ("Hand-drawn ink illustration, confident thick black ink lines, dense cross-hatching, flat bold "
                   "high-chroma colours: vivid cerulean sea-blue, warm cream, strong coral-red on the one object "
                   "that matters, deep ink black. Simple rounded cartoon people. Strong contrast, close-up."),
        "ref": "/mnt/nas/output/explain/2026-09-17_why-not-drink-seawater/scenes/004.jpg",
        "font": "Sriracha.ttf", "fill": (20, 18, 16), "stroke": None,
        "plate": (242, 233, 216), "dark": False},
}


def fit_text(text: str, font: str, max_w: int, max_h: int):
    """Две строки максимум; кегль — самый крупный, влезающий в колонку. Заглавная ≥ CAP_MIN."""
    words = text.split()
    splits = [[text]] + [[" ".join(words[:k]), " ".join(words[k:])] for k in range(1, len(words))]
    best = None
    for lines in splits:
        for size in range(260, 60, -4):
            f = ImageFont.truetype(str(F / font), size)
            cap = f.getbbox("H")[3] - f.getbbox("H")[1]
            ws = [f.getlength(l) for l in lines]
            lh = int(cap * 1.32)
            if max(ws) <= max_w and lh * len(lines) <= max_h:
                if best is None or cap > best[2]:
                    best = (lines, f, cap, lh)
                break
    return best


def render(bg: Path, text: str, ch: str, out: Path):
    st = STYLE[ch]
    im = Image.open(bg).convert("RGB")
    # стиль приносит рамку панели / поля бумаги — срезаем по 4% с каждой стороны
    m = int(im.width * 0.04), int(im.height * 0.04)
    im = im.crop((m[0], m[1], im.width - m[0], im.height - m[1]))
    r = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    col_w = int(W * 0.56)   # 2 строки × 2 слова при заглавной ≥92 px — не уже
    if st["dark"]:
        # тёмная зона под текстом: градиент слева, объект справа не трогаем
        g = Image.new("L", (W, H), 0)
        dg = ImageDraw.Draw(g)
        for x in range(int(W * 0.62)):
            a = int(235 * min(1, max(0, (W * 0.62 - x) / (W * 0.26))))
            dg.line([(x, 0), (x, H)], fill=a)
        im.paste((6, 7, 10), (0, 0), g)
    fit = fit_text(text, st["font"], col_w - 40, int(H * 0.62))
    if not fit or fit[2] < CAP_MIN:
        raise ValueError(f"текст «{text}» не влезает с заглавной ≥{CAP_MIN}px")
    lines, f, cap, lh = fit
    d = ImageDraw.Draw(im)
    x0 = 48
    y0 = (H - lh * len(lines)) // 2
    if st["plate"]:
        pw = max(f.getlength(l) for l in lines) + 70
        ph = lh * len(lines) + 50
        plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(plate).rounded_rectangle((x0 - 30, y0 - 30, x0 - 30 + pw, y0 - 30 + ph), 26,
                                                fill=st["plate"] + (240,), outline=(20, 18, 16, 255), width=5)
        im.paste(plate, (0, 0), plate)
    for i, line in enumerate(lines):
        y = y0 + i * lh - f.getbbox("H")[1]
        words = line.split()
        cx = x0
        for wi, wd in enumerate(words):
            col = st["fill"]
            # у дневника последнее слово — красный акцент
            if st.get("accent") and i == len(lines) - 1 and wi == len(words) - 1:
                col = st["accent"]
            kw = dict(stroke_width=max(4, cap // 14), stroke_fill=st["stroke"]) if st["stroke"] else {}
            d.text((cx, y), wd, font=f, fill=col, **kw)
            cx += f.getlength(wd + " ")
    im.save(out, "JPEG", quality=90, optimize=True)
    return cap


def small_b64(p: Path) -> str:
    b = io.BytesIO()
    Image.open(p).convert("RGB").resize((210, 118), Image.LANCZOS).save(b, "JPEG", quality=90)
    return base64.b64encode(b.getvalue()).decode()


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9$%.,x]", "", s.upper().replace("’", "'").replace("'", ""))


def vision_check(client, p: Path, text: str, obj: str, spent: dict) -> tuple[bool, str]:
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": small_b64(p)}}
    r = client.messages.create(model=MODEL, max_tokens=3000, messages=[{"role": "user", "content": [img, {
        "type": "text", "text": "This is a YouTube thumbnail shown at its real feed size. Return ONLY JSON: "
                                '{"text": "the exact text you can read, or empty", "object": "the main object/scene in under 10 words"}'}]}])
    spent["usd"] += claude_cost(MODEL, r.usage)
    got = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
    read = got.get("text", ""); seen = got.get("object", "")
    ratio = difflib.SequenceMatcher(None, norm(read), norm(text)).ratio()
    # модель думает перед ответом: при 20 токенах всё уходило на мысли, ответ был пуст
    r2 = client.messages.create(model=MODEL, max_tokens=2000, messages=[{"role": "user", "content":
        f'Intended main object: "{obj}". A viewer described the image as: "{seen}". '
        "Would a viewer recognise the intended object in this image? Be lenient about details and wording "
        "(e.g. 'rotary phone with handset off' matches 'telephone receiver off the hook'); answer no only if "
        "it is a different thing entirely or the object is not identifiable. Answer only yes or no."}])
    spent["usd"] += claude_cost(MODEL, r2.usage)
    same = "yes" in "".join(b.text for b in r2.content if b.type == "text").lower()
    ok = ratio >= 0.85 and same
    return ok, f"прочитано «{read}» ({ratio:.2f}), объект «{seen}» → {'да' if same else 'нет'}"


def grid(ch: str, item: dict, d: Path):
    cur = BASE / "_current" / f"{ch}_{item['id']}.jpg"
    tiles = [("сейчас", cur)] + [(f"v{i}", d / f"v{i}.jpg") for i in (1, 2, 3)]
    tw, th, pad, lab = 210, 118, 14, 22
    g = Image.new("RGB", (pad + len(tiles) * (tw + pad), pad * 2 + th + lab), (255, 255, 255))
    dr = ImageDraw.Draw(g)
    fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    for k, (name, p) in enumerate(tiles):
        x = pad + k * (tw + pad)
        if p.exists():
            g.paste(Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS), (x, pad))
        dr.text((x, pad + th + 4), name, fill=(40, 40, 40), font=fnt)
    g.save(d / "grid.jpg", quality=92)
    return d / "grid.jpg"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("channels", nargs="*")
    ap.add_argument("--only", default="")
    ap.add_argument("--redo", default="", help="слаг/vN через запятую — перегенерировать только эти")
    a = ap.parse_args()
    spec = json.loads((BASE / "spec.json").read_text(encoding="utf-8"))
    only = {s for s in a.only.split(",") if s}
    cfg = Config(); client = anthropic.Anthropic()
    spent = {"img": 0.0, "usd": 0.0}
    log = []

    def one(job):
        ch, item, k, (text, scene, obj) = job
        d = BASE / ch / item["slug"]; d.mkdir(parents=True, exist_ok=True)
        st = STYLE[ch]
        for attempt in range(3):
            bg = d / f"bg_v{k}_{attempt}.jpg"
            prompt = f"{st['prompt']} {scene}.{COMPOSE}" + (" Make the left side even darker and emptier." if attempt else "")
            try:
                r = genimage.generate(cfg, prompt, bg, refs=[Path(st["ref"])] if st["ref"] else None, aspect="16:9")
                spent["img"] += r.get("usd", 0)
                cap = render(bg, text, ch, d / f"v{k}.jpg")
                ok, why = vision_check(client, d / f"v{k}.jpg", text, obj, spent)
            except Exception as e:
                ok, why, cap = False, f"ошибка: {str(e)[:100]}", 0
            log.append(f"{ch}/{item['slug']}/v{k} попытка {attempt+1}: {'OK' if ok else 'БРАК'} — {why}")
            if ok:
                return True
        return False

    redo = {x for x in a.redo.split(",") if x}
    jobs = [(ch, it, k + 1, v) for ch in (a.channels or spec) for it in spec[ch]
            if not only or it["slug"] in only for k, v in enumerate(it["v"])
            if not redo or f"{it['slug']}/v{k+1}" in redo]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(one, jobs))
    grids = []
    for ch in (a.channels or spec):
        for it in spec[ch]:
            if (not only or it["slug"] in only) and (not redo or any(r.startswith(it["slug"] + "/") for r in redo)):
                grids.append(grid(ch, it, BASE / ch / it["slug"]))
    (BASE / ("check_log_redo.txt" if redo else "check_log.txt")).write_text("\n".join(sorted(log)), encoding="utf-8")
    costs.log("thumbs_v2", "thumbs", "gemini-3.1-flash-image", spent["img"], len(jobs), "обложек")
    costs.log("thumbs_v2", "thumbs_check", MODEL, spent["usd"], len(jobs), "проверок")
    print(f"вариантов {sum(res)}/{len(jobs)} прошли проверку, картинки ${spent['img']:.2f}, "
          f"проверка ${spent['usd']:.2f}, {int(time.time()-t0)} c")
    for gpath in grids:
        print(gpath)


if __name__ == "__main__":
    main()
