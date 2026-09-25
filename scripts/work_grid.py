#!/usr/bin/env python3
"""Сетки раскадровки для смыслового ревью: кадр плюс реплика целиком.

Отличие от `work_review.py`: там лист для производства (тайм-коды, пометки
анимации), здесь — лист для чтения смысла. Под кадром стоит вся реплика, потому
что оценивается не картинка сама по себе, а попадает ли она в то, что звучит.

Лист жёстко укладывается в 1600 px по длинной стороне и меньше мегабайта:
такие картинки смотрят с телефона и пересылают.

    python scripts/work_grid.py <папка>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLS, PER = 4, 12
MAXSIDE, QUALITY, MAXBYTES = 1600, 75, 1_000_000
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def font(sz: int):
    for f in FONTS:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def wrap(d, txt, fnt, w, maxlines):
    out, line = [], ""
    for word in txt.split():
        t = (line + " " + word).strip()
        if d.textlength(t, font=fnt) > w and line:
            out.append(line)
            line = word
            if len(out) == maxlines:
                return out
        else:
            line = t
    if line and len(out) < maxlines:
        out.append(line)
    return out


def stale(sh) -> bool:
    """картинка отстала от описания: у карточек Remotion и у хука отпечатка нет"""
    if sh.get("kind") == "card" or sh.get("clip") or not sh.get("visual"):
        return False          # карточка и готовый клип отпечатка не имеют
    key = f"{sh.get('kind')}|{sh.get('visual') or ''}|{sh.get('file') or ''}"
    return sh.get("drawn") != hashlib.sha1(key.encode()).hexdigest()[:10]


def picture(P: Path, sh, cache: Path):
    """у кадра с анимацией картинки нет — берём кадр из клипа"""
    if sh.get("clip"):
        p = P / sh["clip"]
        if p.exists():
            cache.mkdir(parents=True, exist_ok=True)
            out = cache / f"c{sh['id']}.jpg"
            if not out.exists():
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.6", "-i", str(p),
                                "-frames:v", "1", str(out)], check=False)
            if out.exists():
                return Image.open(out).convert("RGB")
    f = P / (sh.get("file") or f"stills/s{sh['id']:03d}.jpg")
    return Image.open(f).convert("RGB") if f.exists() else None


def grid(P: Path, title: str, shots: list, out: Path) -> None:
    tw = MAXSIDE // COLS
    th = int(tw * 9 / 16)
    fh, fs = font(15), font(12)
    cap = 4 + 17 + 4 * 15 + 6          # номер плюс до четырёх строк реплики
    rows = (len(shots) + COLS - 1) // COLS
    W, H = MAXSIDE, 30 + rows * (th + cap)
    im = Image.new("RGB", (W, H), (16, 16, 18))
    d = ImageDraw.Draw(im)
    d.text((8, 7), title, font=fh, fill=(242, 236, 224))
    for i, sh in enumerate(shots):
        x, y = (i % COLS) * tw, 30 + (i // COLS) * (th + cap)
        pic = picture(P, sh, P / "_grid" / "_frames")
        if pic:
            im.paste(pic.resize((tw - 6, th), Image.LANCZOS), (x + 3, y))
        else:
            d.rectangle([x + 3, y, x + tw - 3, y + th], fill=(56, 28, 28))
            d.text((x + 12, y + th // 2), "нет кадра", font=fh, fill=(228, 83, 58))
        mark = []
        if sh.get("kind") == "hero":
            mark.append("ведущий")
        if sh.get("chip"):
            c = sh["chip"]
            mark.append("фишка " + str(c.get("big") if isinstance(c, dict) else c))
        if stale(sh):
            mark.append("УСТАРЕЛ")
        if sh.get("bridge"):
            mark.append("мост")
        head = f"{sh['id']}" + ("  ·  " + " · ".join(mark) if mark else "")
        d.text((x + 8, y + th + 4), head, font=fs, fill=(200, 154, 60))
        narr = re.sub(r"[✅⚠️]", "", sh.get("narr") or "—").replace("  ", " ").strip()
        for k, ln in enumerate(wrap(d, narr or "—", fs, tw - 16, 4)):
            d.text((x + 8, y + th + 23 + k * 15), ln, font=fs, fill=(226, 226, 222))
    out.parent.mkdir(parents=True, exist_ok=True)
    q = QUALITY
    while True:
        im.save(out, quality=q, optimize=True)
        if out.stat().st_size <= MAXBYTES or q <= 40:
            break
        q -= 10                         # требование «до мегабайта» важнее качества


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    a = ap.parse_args()
    P = Path(a.dir)
    sb = json.loads((P / "storyboard.json").read_text(encoding="utf-8"))
    out = P / "_grid"
    out.mkdir(exist_ok=True)
    for f in out.glob("*.jpg"):
        f.unlink()

    blocks: dict[str, list] = {}
    for s in sb:
        blocks.setdefault(s.get("block", "?"), []).append(s)
    # отдельный лист: все появления ведущего подряд плюс кадр из хука как эталон
    heroes = sorted([s for s in sb if s.get("kind") == "hero" and s["id"] < 8000],
                    key=lambda s: s["t_in"])
    if heroes:
        blocks["ведущий подряд"] = heroes
    for b, ss in blocks.items():
        ss.sort(key=lambda s: s.get("t_in", 0))
        slug = re.sub(r"[^\wА-Яа-яёЁ]+", "_", b).strip("_")
        parts = [ss[i:i + PER] for i in range(0, len(ss), PER)] or [[]]
        for n, part in enumerate(parts):
            suf = "" if len(parts) == 1 else "_" + "abcdefgh"[n]
            f = out / f"{slug}{suf}.jpg"
            grid(P, f"{b}{suf}  —  {len(part)} кадров", part, f)
            print(f"  {f.name:<34} {len(part):>2} кадров  {f.stat().st_size // 1024:>4} КБ")


if __name__ == "__main__":
    main()
