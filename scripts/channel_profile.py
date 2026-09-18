#!/usr/bin/env python3
"""Профиль каналов-кандидатов: последние 25 роликов через yt-dlp (темп, длина, медиана
просмотров, v/s), возраст из Supabase, обложки 3 шт. -> контакт-лист + Opus: стиль графики
(simple_2d / stickman / whiteboard / 3d_or_ai / real_or_stock / other) и сложность
воспроизведения нашим конвейером (1–5)."""
from __future__ import annotations
import base64, json, os, statistics, subprocess, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
from supabase import create_client
import anthropic
from pipeline.util import claude_cost, parse_json_block

OUT = Path("/mnt/d/youtube/cache/channel_profiles"); OUT.mkdir(parents=True, exist_ok=True)
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
client = anthropic.Anthropic(); cost = 0.0
ids = [x for x in sys.argv[1:]]
prof = {}
for cid in ids:
    j = OUT / f"{cid}.json"
    if j.exists():
        prof[cid] = json.loads(j.read_text(encoding="utf-8")); continue
    url = f"https://www.youtube.com/channel/{cid}/videos" if cid.startswith("UC") else f"https://www.youtube.com/@{cid}/videos"
    r = subprocess.run(["yt-dlp", "--flat-playlist", "--playlist-end", "25", "-J", url], capture_output=True, text=True, timeout=300)
    try: d = json.loads(r.stdout)
    except Exception: print("  ! yt-dlp:", cid, r.stderr[-120:]); continue
    e = [x for x in d.get("entries", []) if x and x.get("duration")]
    ch = (sb.table("channels").select("*").eq("id", d.get("channel_id") or cid).limit(1).execute().data or [{}])[0]
    now = datetime.now(timezone.utc)
    created = ch.get("created_at")
    age_m = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).days / 30.4 if created else None
    views = [x.get("view_count") or 0 for x in e]; durs = [x["duration"] / 60 for x in e]
    subs = d.get("channel_follower_count") or ch.get("subscriber_count") or 0
    # темп: сколько роликов за последние 60 дней (по датам нет — оценка через число в списке за период невозможна в flat; берём video_count/возраст)
    vc = ch.get("video_count") or len(e)
    per_week = (vc / (age_m * 4.35)) if age_m else None
    thumbs = []
    for x in e[:3]:
        p = OUT / f"{x['id']}.jpg"
        if not p.exists():
            for q in ("maxresdefault", "hqdefault"):
                try: urllib.request.urlretrieve(f"https://i.ytimg.com/vi/{x['id']}/{q}.jpg", p); break
                except Exception: pass
        if p.exists(): thumbs.append(p)
    style = {}
    if thumbs:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(t.read_bytes()).decode()}} for t in thumbs]
        content.append({"type": "text", "text": "Обложки трёх роликов одного канала. Определи стиль графики канала: simple_2d (плоские рисованные персонажи/иллюстрации, как OverSimplified/Dinzo), stickman, whiteboard, stylized_3d (явно анимационные 3D-персонажи: Pixar-подобные, безликие манекены, мультяшные пропорции — сразу видно, что это анимация), ai_realistic (нейросетевые «фотореалистичные» картины, имитация фото/кино), real_or_stock (фото/съёмка), other. Отдельно: язык текста на обложках — если не английский, укажи в why. Оцени, насколько такой стиль воспроизводим конвейером с Remotion-анимацией простых 2D-иллюстраций (1 — почти невозможно, 5 — легко). Верни ТОЛЬКО JSON {\"style\":\"...\",\"reproducible\":1-5,\"lang\":\"en|hi|...\",\"why\":\"кратко по-русски\"}"})
        rr = client.messages.create(model="claude-opus-5", max_tokens=500, messages=[{"role": "user", "content": content}])
        cost += claude_cost("claude-opus-5", rr.usage)
        try: style = parse_json_block("".join(b.text for b in rr.content if b.type == "text"))
        except Exception: style = {}
    prof[cid] = {"id": d.get("channel_id") or cid, "name": d.get("channel") or ch.get("title"), "handle": d.get("uploader_id"), "subs": subs,
                 "age_months": round(age_m, 1) if age_m else None, "video_count": vc, "per_week": round(per_week, 1) if per_week else None,
                 "median_views": int(statistics.median(views)) if views else 0, "vs": round(statistics.median(views) / subs, 2) if subs and views else None,
                 "median_min": round(statistics.median(durs), 1) if durs else None, "style": style, "titles": [x.get("title") for x in e[:6]],
                 "url": f"https://www.youtube.com/{d.get('uploader_id') or 'channel/' + cid}"}
    j.write_text(json.dumps(prof[cid], ensure_ascii=False, indent=1), encoding="utf-8")
    p = prof[cid]
    print(f"{(p['name'] or '')[:26]:<26} {p['subs']:>9,} {str(p['age_months']):>5}мес {str(p['per_week']):>4}/нед  {p['median_views']:>9,} v/s {p['vs']!s:>5}  {p['median_min']!s:>4}м  {p['style'].get('style','?'):<13} repr {p['style'].get('reproducible','?')}  {p['url']}")
print(f"cost ${cost:.2f}")
