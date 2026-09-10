"""Wikimedia Commons: поиск изображений с лицензией и автором, скачивание, лог атрибуции.

API без ключа. Берём только свободные лицензии; для CC-BY / CC-BY-SA атрибуция
обязательна — строка для угла кадра и запись в паспорт.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from ..util import Cache, sha1

API = "https://commons.wikimedia.org/w/api.php"
UA = "yt-pipeline/1.0 (faceless documentary; contact: local)"
# лицензии, которые берём; порядок = предпочтение (меньше обязательств — выше)
OK_LICENSES = ["CC0", "Public domain", "PD", "OGL", "GODL", "CC BY 4.0", "CC BY 3.0",
               "CC BY 2.0", "CC BY 2.5", "CC BY 1.0", "CC BY-SA 4.0", "CC BY-SA 3.0",
               "CC BY-SA 2.0", "CC BY-SA 2.5", "CC BY-SA 1.0"]
BAD = ("NC", "ND", "Fair use", "Non-free", "unknown", "?")


def _get(params: dict, timeout=40) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def license_rank(short: str) -> int:
    s = (short or "").strip()
    for i, ok in enumerate(OK_LICENSES):
        if s.upper().startswith(ok.upper()):
            return i
    return 999


def search(query: str, cache: Cache, limit: int = 8, min_width: int = 1200) -> list[dict]:
    """Кандидаты с лицензией/автором. Кэш 7 дней."""
    key = sha1("commons", query, limit, min_width)
    hit = cache.get_json("commons", key, ttl_hours=24 * 7)
    if hit is not None:
        return hit
    try:
        r = _get({"action": "query", "generator": "search", "gsrsearch": query,
                  "gsrnamespace": "6", "gsrlimit": str(limit * 2),
                  "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
                  "iiurlwidth": "1600"})
    except Exception:
        return []
    out = []
    for p in (r.get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata", {}) or {}
        lic = em.get("LicenseShortName", {}).get("value", "")
        if not lic or any(b.lower() in lic.lower() for b in BAD):
            continue
        if license_rank(lic) == 999:
            continue
        mime = ii.get("mime", "")
        if not mime.startswith("image/") or "svg" in mime or "gif" in mime:
            continue
        if (ii.get("width") or 0) < min_width:
            continue
        out.append({
            "src": "commons", "title": p.get("title", ""),
            "page": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(p.get('title', ''))}",
            "url": ii.get("thumburl") or ii.get("url"), "orig": ii.get("url"),
            "w": ii.get("thumbwidth") or ii.get("width"), "h": ii.get("thumbheight") or ii.get("height"),
            "license": lic, "license_url": em.get("LicenseUrl", {}).get("value", ""),
            "author": _strip(em.get("Artist", {}).get("value", "")) or "unknown",
            "credit": _strip(em.get("Credit", {}).get("value", ""))[:80],
            "date": (em.get("DateTimeOriginal", {}).get("value", "") or "")[:10],
            "desc": _strip(em.get("ImageDescription", {}).get("value", ""))[:160],
            "needs_attribution": not lic.upper().startswith(("CC0", "PUBLIC", "PD")),
        })
    out.sort(key=lambda c: (license_rank(c["license"]), -(c["w"] or 0)))
    out = out[:limit]
    cache.put_json("commons", key, out)
    return out


def download(cand: dict, cache: Cache) -> Path:
    """Скачивание с паузой и повтором на 429: Commons режет частые запросы."""
    import time
    h = sha1(cand["url"])
    p = cache.blob_path("commons_img", h, ".jpg")
    if p.exists() and p.stat().st_size > 0:
        return p
    last = None
    for attempt in range(3):
        time.sleep(1.5 + attempt * 4.0)
        try:
            req = urllib.request.Request(cand["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r, p.open("wb") as f:
                while chunk := r.read(1 << 16):
                    f.write(chunk)
            return p
        except Exception as e:                   # 429 / обрыв — ждём и повторяем
            last = e
            p.unlink(missing_ok=True)
    raise RuntimeError(f"download failed: {str(last)[:80]}")


def attribution(cand: dict) -> str:
    """Строка для угла кадра: автор · лицензия · Wikimedia Commons."""
    if not cand.get("needs_attribution"):
        return f"{cand.get('author','')[:28]} · {cand.get('license','')} · Wikimedia Commons".strip(" ·")
    return f"© {cand.get('author','')[:28]} · {cand.get('license','')} · Wikimedia Commons"
