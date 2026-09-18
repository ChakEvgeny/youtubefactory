"""passport — паспорт ролика в passport.json, запись в Supabase, копия на NAS."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..util import ffprobe_duration, run, utcnow


def run_stage(cfg, ctx: Path, cost, results: dict, topic: str) -> dict:
    def load(name, default=None):
        p = ctx / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else (default or {})

    brief, meta = load("brief.json"), load("meta.json")
    assets, ts = load("assets.json", []), load("timestamps.json")
    video = ctx / "video.mp4"
    by_src: dict = {}
    for a in assets:
        by_src[a.get("source") or "none"] = by_src.get(a.get("source") or "none", 0) + 1

    slug = ctx.name.split("_", 1)[-1]
    pid = f"{cfg.channel_id}/{ctx.name}"
    passport = {
        "id": pid, "channel": cfg.channel_id, "niche": cfg.channel["niche"], "slug": slug,
        "topic": topic, "title": (meta.get("titles") or [None])[0],
        "titles_alt": meta.get("titles", []), "lang": cfg.defaults["lang"],
        "duration_sec": int(ffprobe_duration(video)) if video.exists() else None,
        "n_scenes": len(assets), "scene_sources": by_src,
        "sources": meta.get("sources", []),
        "models": {"research": "claude-opus-5", "script": "claude-fable-5-1",
                   "critic": "claude-opus-5", "meta": "claude-opus-5",
                   "thumbs_vision": "claude-opus-5"},
        "voice_id": ts.get("voice_id"), "voice_model": ts.get("model"),
        "critic_notes": results.get("critic", {}),
        "cost": cost.to_json(), "cost_total": cost.total,
        "out_dir": str(ctx), "stages": results,
        "created_at": utcnow().isoformat(),
    }
    (ctx / "passport.json").write_text(json.dumps(passport, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    written = False
    try:
        from supabase import create_client
        sb = create_client(cfg.key("SUPABASE_URL"), cfg.key("SUPABASE_SERVICE_KEY"))
        row = {k: v for k, v in passport.items() if k not in ("stages",)}
        row["cost_total"] = float(cost.total)
        sb.table("productions").upsert(row, on_conflict="id").execute()
        written = True
    except Exception as e:
        print(f"    ! Supabase: {str(e)[:120]}")

    synced = False
    nas = cfg.paths.nas_dir / cfg.channel_id / ctx.name
    try:
        if cfg.paths.nas_dir.exists():
            nas.parent.mkdir(parents=True, exist_ok=True)
            # .env на NAS не попадает никогда: копируем только папку ролика
            run(["rsync", "-a", "--exclude", "_clips", "--exclude", ".env",
                 f"{ctx}/", f"{nas}/"], timeout=3600)
            synced = True
        else:
            print(f"    ! NAS недоступен ({cfg.paths.nas_dir}) — копия не сделана")
    except Exception as e:
        print(f"    ! rsync: {str(e)[:120]}")

    if written:
        try:
            from supabase import create_client
            sb = create_client(cfg.key("SUPABASE_URL"), cfg.key("SUPABASE_SERVICE_KEY"))
            sb.table("productions").update({"nas_synced": synced}).eq("id", pid).execute()
        except Exception:
            pass
    return {"supabase": written, "nas_synced": synced, "cost_total": cost.total,
            "passport": str(ctx / "passport.json")}
