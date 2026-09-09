#!/usr/bin/env python3
"""Ужесточение языкового фильтра: ролик остаётся в lang=X, только если
(а) langdetect по title даёт X, (б) доля латиницы среди букв title >= 90%,
(в) default_audio_language пуст или начинается с X.
Не прошедшие -> relevant=0, reason='lang_leak'. YouTube API не используется."""
import argparse, json, os, sys, unicodedata
from pathlib import Path
from dotenv import load_dotenv
from langdetect import DetectorFactory, LangDetectException
from langdetect import detect as ld
from supabase import create_client

DetectorFactory.seed = 0
ROOT = Path(__file__).resolve().parent.parent
LATIN_MIN = 0.90

def latin_ratio(s: str) -> float:
    letters = [c for c in (s or "") if c.isalpha()]
    if not letters: return 0.0
    lat = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
    return lat / len(letters)

def title_lang(title: str, desc: str = ""):
    """langdetect по title + описанию: на одном коротком заголовке он ошибается —
    замерено, 22 из 23 отбракованных по title оказались настоящим английским."""
    text = f"{title or ''} {(desc or '')[:300]}".strip()
    try: return ld(text) if text else None
    except LangDetectException: return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="en")
    ap.add_argument("--apply", action="store_true", help="без него — только показать")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
    has_reason = True
    try: sb.table("videos").select("relevance_reason").limit(1).execute()
    except Exception: has_reason = False

    rows, off = [], 0
    while True:
        b = (sb.table("videos").select("id,title,description,lang,niche,default_audio_language,relevant,view_count")
             .eq("lang", args.lang).range(off, off + 999).execute().data)
        if not b: break
        rows += b; off += 1000
        if len(b) < 1000: break

    leaks, kept = [], 0
    for v in rows:
        t = v.get("title") or ""
        dal = (v.get("default_audio_language") or "").lower()
        ok = (title_lang(t, v.get("description")) == args.lang
              and latin_ratio(t) >= LATIN_MIN
              and (not dal or dal.startswith(args.lang)))
        if ok: kept += 1
        else: leaks.append(v)

    was_rel = [v for v in leaks if v.get("relevant") == 1]
    print(f"lang={args.lang}: всего {len(rows)}, проходят ужесточённый фильтр {kept}, "
          f"утечек {len(leaks)} (из них были relevant=1: {len(was_rel)})")
    print("\nпримеры утечек, которые были relevant=1 (по просмотрам):")
    for v in sorted(was_rel, key=lambda x: -(x.get("view_count") or 0))[:12]:
        t = v["title"] or ""
        print(f"  {v['view_count']:>9,} lat={latin_ratio(t):.2f} det={title_lang(t, v.get('description'))} "
              f"dal={v.get('default_audio_language') or '-':<6} | {t[:58]}")

    dump = ROOT / "reports" / f"lang_leaks_{args.lang}.json"
    dump.parent.mkdir(exist_ok=True)
    dump.write_text(json.dumps([v["id"] for v in leaks], indent=0), encoding="utf-8")
    print(f"\nсписок id сохранён: {dump.relative_to(ROOT)} "
          f"({'reason будет записан' if has_reason else 'колонки relevance_reason нет — reason не пишется'})")

    if not args.apply:
        print("это предпросмотр; для записи добавь --apply")
        return
    ids = [v["id"] for v in leaks]
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        payload = {"relevant": 0}
        if has_reason: payload["relevance_reason"] = "lang_leak"
        sb.table("videos").update(payload).in_("id", chunk).execute()
    print(f"проставлено relevant=0 у {len(ids)} роликов")

if __name__ == "__main__":
    main()
