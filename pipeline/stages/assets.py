"""assets — Pexels video -> Pixabay video -> Pexels photo, плюс Kling для сцен kling:yes."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from ..util import Cache, sha1

SEARCH_TTL_H = 24
KLING_BASE = "https://api-singapore.klingai.com"
KLING_COST_PER_CLIP = 0.28   # 5 сек 1080p, уточняется по ответу API
# Без внятного User-Agent Cloudflare перед Pexels отдаёт 403 error code 1010.
UA = "Mozilla/5.0 (X11; Linux x86_64) yt-pipeline/1.0"


def _get(url: str, headers: dict, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def search_pexels_video(q: str, key: str, cache: Cache) -> list[dict]:
    h = sha1("pexels_v", q)
    hit = cache.get_json("assets", h, SEARCH_TTL_H)
    if hit is not None:
        return hit
    url = ("https://api.pexels.com/videos/search?per_page=8&orientation=landscape&size=medium&query="
           + urllib.parse.quote(q))
    d = _get(url, {"Authorization": key})
    out = []
    for v in d.get("videos", []):
        files = [f for f in v.get("video_files", []) if (f.get("width") or 0) >= 1280]
        if not files:
            continue
        best = sorted(files, key=lambda f: abs((f.get("width") or 0) - 1920))[0]
        out.append({"src": "pexels_video", "url": best["link"], "w": best.get("width"),
                    "duration": v.get("duration"), "id": v.get("id")})
    cache.put_json("assets", h, out)
    return out


def search_pixabay_video(q: str, key: str, cache: Cache) -> list[dict]:
    h = sha1("pixabay_v", q)
    hit = cache.get_json("assets", h, SEARCH_TTL_H)
    if hit is not None:
        return hit
    url = (f"https://pixabay.com/api/videos/?key={key}&per_page=8&video_type=film&q="
           + urllib.parse.quote(q))
    d = _get(url, {})
    out = []
    for v in d.get("hits", []):
        vs = (v.get("videos") or {}).get("large") or (v.get("videos") or {}).get("medium")
        if vs and vs.get("url"):
            out.append({"src": "pixabay_video", "url": vs["url"], "w": vs.get("width"),
                        "duration": v.get("duration"), "id": v.get("id")})
    cache.put_json("assets", h, out)
    return out


def search_pexels_photo(q: str, key: str, cache: Cache) -> list[dict]:
    h = sha1("pexels_p", q)
    hit = cache.get_json("assets", h, SEARCH_TTL_H)
    if hit is not None:
        return hit
    url = ("https://api.pexels.com/v1/search?per_page=8&orientation=landscape&query="
           + urllib.parse.quote(q))
    d = _get(url, {"Authorization": key})
    out = [{"src": "pexels_photo", "url": p["src"]["large2x"], "id": p.get("id")}
           for p in d.get("photos", []) if p.get("src", {}).get("large2x")]
    cache.put_json("assets", h, out)
    return out


def download(url: str, cache: Cache, ext: str) -> Path:
    h = sha1(url)
    p = cache.blob_path("media", h, ext)
    if p.exists() and p.stat().st_size > 0:
        return p
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, p.open("wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    return p


def kling_auth(cfg) -> str | None:
    """Kling: в .env лежит одиночный KLING_API_KEY (не пара access/secret).
    Если появится пара — собираем JWT HS256, как требует их доступ по ключам."""
    api = cfg.key("KLING_API_KEY")
    if api:
        return f"Bearer {api}"
    access, secret = cfg.key("KLING_ACCESS_KEY"), cfg.key("KLING_SECRET_KEY")
    if not (access and secret):
        return None
    import base64 as b64
    import hashlib
    import hmac

    def seg(o):
        return b64.urlsafe_b64encode(json.dumps(o, separators=(",", ":")).encode()).rstrip(b"=")
    now = int(time.time())
    head, body = seg({"alg": "HS256", "typ": "JWT"}), seg(
        {"iss": access, "exp": now + 1800, "nbf": now - 5})
    sig = b64.urlsafe_b64encode(
        hmac.new(secret.encode(), head + b"." + body, hashlib.sha256).digest()).rstrip(b"=")
    return "Bearer " + (head + b"." + body + b"." + sig).decode()


def run_stage(cfg, ctx, cost, kling_limit: int | None = None) -> dict:
    cache = Cache(cfg.paths.cache_dir)
    scenes = json.loads((ctx / "scenes.json").read_text(encoding="utf-8"))
    pex, pix = cfg.key("PEXELS_API_KEY"), cfg.key("PIXABAY_API_KEY")
    lo, hi = cfg.defaults["kling_per_video"]
    limit = kling_limit if kling_limit is not None else hi
    if cfg.channel.get("kling_bias") == "none":
        limit = 0
    max_row = cfg.defaults["max_same_source_in_row"]

    picked, used_kling, last_src, row = [], 0, None, 0
    for sc in scenes:
        if sc.get("type") == "motion":      # рисуется стадией motion, сток не нужен
            picked.append({"idx": sc["idx"], "query": "", "kling": False, "source": "motion",
                           "file": None, "description": sc["description"]})
            continue
        q = sc["stock_query"]
        cands: list[dict] = []
        try:
            cands += search_pexels_video(q, pex, cache)
        except Exception as e:
            print(f"    ! pexels video «{q}»: {str(e)[:70]}")
        try:
            cands += search_pixabay_video(q, pix, cache)
        except Exception as e:
            print(f"    ! pixabay «{q}»: {str(e)[:70]}")
        try:
            cands += search_pexels_photo(q, pex, cache)
        except Exception as e:
            print(f"    ! pexels photo «{q}»: {str(e)[:70]}")

        # разнообразие: не больше max_row подряд из одного источника
        chosen = None
        for c in cands:
            if c["src"] == last_src and row >= max_row:
                continue
            chosen = c
            break
        chosen = chosen or (cands[0] if cands else None)

        entry = {"idx": sc["idx"], "query": q, "kling": sc["kling"], "source": None,
                 "file": None, "description": sc["description"]}
        if sc["kling"] and used_kling < limit:
            entry["source"] = "kling"
            entry["pending_kling"] = True
            used_kling += 1
            cost.add("assets", "kling", KLING_COST_PER_CLIP, f"сцена {sc['idx']}: {q}")
        elif chosen:
            ext = ".mp4" if "video" in chosen["src"] else ".jpg"
            try:
                f = download(chosen["url"], cache, ext)
                entry["source"] = chosen["src"]
                entry["file"] = str(f)
            except Exception as e:
                print(f"    ! скачивание «{q}»: {str(e)[:70]}")
        if entry["source"] and entry["source"] != "kling":
            row = row + 1 if entry["source"] == last_src else 1
            last_src = entry["source"]
        picked.append(entry)

    (ctx / "assets.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    by_src: dict = {}
    for p in picked:
        by_src[p["source"] or "none"] = by_src.get(p["source"] or "none", 0) + 1
    return {"scenes": len(picked), "by_source": by_src, "kling_used": used_kling,
            "kling_limit": limit}
