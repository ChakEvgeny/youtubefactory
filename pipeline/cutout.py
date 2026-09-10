"""Вырезка объекта: rembg-матте, эрозия 1px, feather, обрезка по bbox (по cutout.py у hassancs91)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter

_SESSION = None


def _session():
    global _SESSION
    if _SESSION is None:
        from rembg import new_session
        _SESSION = new_session("isnet-general-use")
    return _SESSION


def cutout(src: Path, dst: Path, pad: int = 24, feather: float = 1.0, max_side: int = 1600) -> dict:
    from rembg import remove
    img = Image.open(src).convert("RGBA")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    cut = remove(img, session=_session())
    matte = cut.getchannel("A").filter(ImageFilter.MinFilter(3))
    if feather > 0:
        matte = matte.filter(ImageFilter.GaussianBlur(feather))
    out = img.copy()
    out.putalpha(matte)
    bbox = matte.getbbox()
    if bbox is None:
        raise ValueError("матте пустое — объект не найден")
    l, t, r, b = bbox
    out = out.crop((max(0, l - pad), max(0, t - pad), min(out.width, r + pad), min(out.height, b + pad)))
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    opaque = sum(1 for v in out.getchannel("A").getdata() if v > 8) / (out.width * out.height)
    return {"w": out.width, "h": out.height, "opaque": round(opaque, 2),
            "coverage": round((r - l) * (b - t) / (img.width * img.height), 2)}
