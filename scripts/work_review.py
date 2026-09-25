#!/usr/bin/env python3
"""Раскадровка на просмотр: контактные листы по блокам с разметкой.

Под каждым кадром — номер, тайм-код, длительность, реплика и пометки: что
анимируется, где фишка, чего ещё нет. Один файл на блок, смотреть с диска.

    python scripts/work_review.py <папка>
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# лист просмотра внутренний, подписи русские — Courier Prime кириллицы не знает
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def font(sz: int):
    for f in FONTS:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def wrap(d, txt, fnt, w):
    out, line = [], ""
    for word in txt.split():
        t = (line + " " + word).strip()
        if d.textlength(t, font=fnt) > w and line:
            out.append(line)
            line = word
        else:
            line = t
    if line:
        out.append(line)
    return out[:3]


def frame_of(P: Path, sh) -> Image.Image | None:
    """для клипа берём кадр из середины — видно, что именно анимируется"""
    if sh.get("clip"):
        p = P / sh["clip"]
        if p.exists():
            out = P / "_review" / "_frames" / f"c{sh['id']:03d}.jpg"
            out.parent.mkdir(exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.6", "-i", str(p),
                            "-frames:v", "1", str(out)], check=False)
            if out.exists():
                return Image.open(out).convert("RGB")
    f = P / (sh.get("file") or f"stills/s{sh['id']:03d}.jpg")
    return Image.open(f).convert("RGB") if f.exists() else None


def sheet(P: Path, block: str, shots: list, out: Path, cols=3, tw=600):
    th = int(tw * 9 / 16)
    cap = 116
    rows = (len(shots) + cols - 1) // cols
    im = Image.new("RGB", (cols * tw, rows * (th + cap) + 46), (16, 16, 18))
    d = ImageDraw.Draw(im)
    d.text((14, 12), f"{block} — {len(shots)} кадров", font=font(26), fill=(242, 236, 224))
    for i, sh in enumerate(shots):
        x, y = (i % cols) * tw, 46 + (i // cols) * (th + cap)
        pic = frame_of(P, sh)
        if pic:
            im.paste(pic.resize((tw - 8, th), Image.LANCZOS), (x + 4, y))
        else:
            d.rectangle([x + 4, y, x + tw - 4, y + th], fill=(52, 30, 30))
            d.text((x + 18, y + th // 2), "КАДРА НЕТ", font=font(30), fill=(228, 83, 58))
        t0 = sh.get("t_in", 0)
        head = f"{sh['id']:>3}  {int(t0)//60}:{t0%60:05.2f}  {sh.get('dur',0):.1f}с"
        tags = []
        if sh.get("clip"):
            tags.append("АНИМАЦИЯ")
        if sh.get("bridge"):
            tags.append("МОСТ В СЛЕДУЮЩИЙ БЛОК")
        if sh.get("chip"):
            tags.append(f"фишка {sh['chip']}")
        if sh.get("kind") == "hero" and not sh.get("clip"):
            tags.append("ВЕДУЩИЙ БЕЗ АНИМАЦИИ")
        d.text((x + 10, y + th + 6), head, font=font(20), fill=(200, 154, 60))
        if tags:
            d.text((x + 10, y + th + 30), " · ".join(tags), font=font(18), fill=(228, 83, 58))
        fnt = font(17)
        for k, ln in enumerate(wrap(d, sh.get("narr") or "—", fnt, tw - 24)):
            d.text((x + 10, y + th + 54 + k * 20), ln, font=fnt, fill=(232, 232, 228))
    im.save(out, quality=86)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    a = ap.parse_args()
    P = Path(a.dir)
    sb = json.loads((P / "storyboard.json").read_text(encoding="utf-8"))
    out = P / "_review"
    out.mkdir(exist_ok=True)
    # листы от прошлых прогонов остаются лежать и путают: у блоков меняются
    # номера и названия, и рядом с новым листом оказывается старый
    for f in out.glob("*.jpg"):
        f.unlink()
    blocks, rows = {}, []
    for s in sb:
        blocks.setdefault(s.get("block", "?"), []).append(s)
    for i, (b, ss) in enumerate(blocks.items()):
        ss.sort(key=lambda s: s.get("t_in", 0))
        name = f"{i:02d}_" + "".join(c if c.isalnum() else "_" for c in b)[:28] + ".jpg"
        sheet(P, b, ss, out / name)
        drawn = sum(1 for s in ss if (P / (s.get("clip") or s.get("file")
                                            or f"stills/s{s['id']:03d}.jpg")).exists())
        anim = sum(1 for s in ss if s.get("clip"))
        hero_static = sum(1 for s in ss if s.get("kind") == "hero" and not s.get("clip"))
        rows.append((b, len(ss), drawn, anim, hero_static, name))
    w = max(len(r[0]) for r in rows)
    print(f"{'блок':<{w}}  кадров  нарисовано  анимация  ведущий без анимации  файл")
    for b, n, drawn, anim, hs, name in rows:
        print(f"{b:<{w}}  {n:>6}  {drawn:>10}  {anim:>8}  {hs:>20}  _review/{name}")


if __name__ == "__main__":
    main()
