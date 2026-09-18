"""assets — Pexels video -> Pixabay video -> Pexels photo, плюс Kling для сцен kling:yes."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from ..util import SeenFrames, Cache, claude_cost, parse_json_block, run, sha1

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


VISION = "claude-opus-5"      # Haiku резала JSON и отбраковывала лишнее; +$0.3/ролик
VISION_SYS = (
    "Ты выбираешь стоковый кадр под конкретный момент ролика. Тебе дают текст, "
    "который в этот момент звучит, и несколько превью-кадров.\n"
    "Выбирай тот, что показывает ИМЕННО то, о чём речь. Общая тематическая связь "
    "не годится: если речь про пустой автосалон, кадр стройки — это мимо.\n"
    "Оцени лучший вариант по шкале 0-10, где 10 — точное попадание, 5 — приемлемо, "
    "ниже 5 — не подходит ни один. Если сказано, что показывал ПРЕДЫДУЩИЙ кадр, "
    "не выбирай вариант той же композиции (та же аэросъёмка, тот же тип плана) — "
    "соседние кадры должны отличаться, даже ценой одного балла релевантности. "
    "Тёмные, засвеченные или нечитаемые кадры (силуэты в темноте, пустой коридор без света) "
    "не выбирай — ставь им не выше 4.\n"
    "Отвечай ТОЛЬКО JSON: {\"best\": <индекс с нуля>, \"score\": <0-10>, "
    "\"why\": \"кратко по-русски\"}"
)


def preview_frame(path: str, cache: Cache) -> str | None:
    """Кадр из видео (или само фото) в base64 для vision."""
    import base64
    h = sha1("prev", path)
    p = cache.blob_path("previews", h, ".jpg")
    if not p.exists():
        try:
            if path.endswith(".jpg"):
                run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vf", "scale=320:-2",
                     "-frames:v", "1", str(p)])
            else:
                run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", path, "-vf",
                     "scale=320:-2", "-frames:v", "1", str(p)])
        except Exception:
            return None
    if not p.exists():
        return None
    return base64.b64encode(p.read_bytes()).decode()


def pick_by_vision(client, shot_text: str, scene_desc: str, cands: list[dict],
                   cache: Cache, cost, prev_desc: str = "") -> tuple[int, float, str]:
    content = [{"type": "text",
                "text": f"ЗВУЧИТ В КАДРЕ: {shot_text[:220] or scene_desc[:120]}\n"
                        f"ОПИСАНИЕ СЦЕНЫ: {scene_desc[:120]}"
                        + (f"\nПРЕДЫДУЩИЙ КАДР ПОКАЗЫВАЛ: {prev_desc[:120]}" if prev_desc else "")}]
    shown = []
    for i, c in enumerate(cands):
        b64 = preview_frame(c["file"], cache)
        if not b64:
            continue
        shown.append(i)
        content.append({"type": "text", "text": f"вариант {len(shown)-1}"})
        content.append({"type": "image", "source": {"type": "base64",
                                                    "media_type": "image/jpeg", "data": b64}})
    if not shown:
        return 0, 0.0, "превью не собрались"
    r = client.messages.create(model=VISION, max_tokens=400, system=VISION_SYS,
                               messages=[{"role": "user", "content": content}])
    cost.add("assets", VISION, claude_cost(VISION, r.usage), "vision-отбор")
    try:
        d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
        bi = int(d.get("best", 0))
        return shown[bi] if 0 <= bi < len(shown) else shown[0], float(d.get("score", 0)), \
            str(d.get("why", ""))[:70]
    except Exception as e:
        return shown[0], 0.0, f"разбор ответа: {str(e)[:40]}"


def gather(q: str, pex: str, pix: str, cache: Cache, want: int) -> list[dict]:
    out = []
    for fn, key in ((search_pexels_video, pex), (search_pixabay_video, pix),
                    (search_pexels_photo, pex)):
        if len(out) >= want:
            break
        try:
            out += fn(q, key, cache)
        except Exception as e:
            print(f"    ! поиск «{q}»: {str(e)[:60]}")
    return out[:want * 2]


def run_stage(cfg, ctx, cost, kling_limit: int | None = None, preview_sec: float | None = None):
    """Подбор стока покадрово: кандидаты -> vision -> выбор без повторов."""
    import anthropic
    cache = Cache(cfg.paths.cache_dir)
    client = anthropic.Anthropic()
    shots = json.loads((ctx / "shotlist.json").read_text(encoding="utf-8"))
    if preview_sec:
        shots = [sh for sh in shots if sh["start"] < preview_sec]
    pex, pix = cfg.key("PEXELS_API_KEY"), cfg.key("PIXABAY_API_KEY")
    want = int(cfg.defaults.get("vision_candidates", 5))
    lo, hi = cfg.defaults["kling_per_video"]
    limit = kling_limit if kling_limit is not None else hi
    if cfg.channel.get("kling_bias") == "none":
        limit = 0

    used_files: set[str] = set()
    seen = SeenFrames(ctx)                # похожие кадры (pHash) — из коллажей/скринов тоже
    prev_desc = ""
    picked, stats = [], {"vision_calls": 0, "requeried": 0, "photo_fallback": 0,
                         "no_source": 0, "kling": 0}
    for sh in shots:
        sk = sh.get("src_kind") or ("motion" if sh["kind"] == "motion" else "stock")
        if sk != "stock":                    # collage / screens / motion / card / kling — не сток
            picked.append({**sh, "source": sk, "file": None})
            prev_desc = f"{sk}: {sh.get('subject') or sh.get('fact') or sh.get('motion_kind') or ''}"
            continue
        chosen, score, why, q = None, 0.0, "", sh.get("query") or sh["scene_desc"]
        for attempt in range(2):
            cands = gather(q, pex, pix, cache, want)
            downloaded = []
            for c in cands:
                if len(downloaded) >= want:
                    break
                ext = ".mp4" if "video" in c["src"] else ".jpg"
                try:
                    f = str(download(c["url"], cache, ext))
                except Exception:
                    continue
                if f in used_files or seen.similar(f):   # один сюжет — один раз на ролик
                    continue
                downloaded.append({**c, "file": f})
            if not downloaded:
                if attempt == 0:
                    q = " ".join(q.split()[:2]) + " close up"
                    stats["requeried"] += 1
                    continue
                break
            bi, score, why = pick_by_vision(client, sh["text"], sh["scene_desc"],
                                            downloaded, cache, cost, prev_desc)
            stats["vision_calls"] += 1
            chosen = downloaded[bi]
            if score >= 5:
                break
            if attempt == 0:                 # порог не взят — переформулируем один раз
                q = f"{sh['scene_desc'][:40]} {q.split()[0] if q.split() else ''}".strip()
                stats["requeried"] += 1
        entry = {**sh, "source": None, "file": None, "vision_score": score,
                 "vision_why": why, "final_query": q}
        if chosen:
            if score < 5:
                photos = [c for c in gather(q, pex, pix, cache, want) if "photo" in c["src"]]
                for c in photos:
                    try:
                        f = str(download(c["url"], cache, ".jpg"))
                    except Exception:
                        continue
                    if f not in used_files and not seen.similar(f):
                        chosen = {**c, "file": f}
                        stats["photo_fallback"] += 1
                        break
            entry["source"] = chosen["src"]
            entry["file"] = chosen["file"]
            used_files.add(chosen["file"])
            seen.add(chosen["file"], sh["idx"])
            prev_desc = why or q
        else:
            stats["no_source"] += 1
        picked.append(entry)

    (ctx / "assets.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    by = {}
    for p in picked:
        by[p["source"] or "none"] = by.get(p["source"] or "none", 0) + 1
    scores = [p["vision_score"] for p in picked if p.get("vision_score")]
    return {"shots": len(picked), "by_source": by, **stats,
            "unique_files": len(used_files),
            "avg_vision_score": round(sum(scores) / len(scores), 1) if scores else 0}
