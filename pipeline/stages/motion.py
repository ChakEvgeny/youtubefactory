"""motion — программная анимация сцен через Remotion.

Четыре типа: brand (стилизованный вордмарк из названия — чужие файлы логотипов
не используются), chart (график и падающая стрелка из чисел сценария),
counter (числовой счётчик), callout (текстовая плашка).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..util import ROOT, run, sha1

MOTION_DIR = ROOT / "pipeline" / "motion"
COMP = {"brand": "BrandCard", "chart": "Chart", "counter": "Counter", "callout": "Callout"}
FPS = 30


def parse_data(raw: str) -> dict:
    """`k=v; k=v` -> dict, числа и списки чисел приводятся к типам."""
    out: dict = {}
    for part in (raw or "").split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        if "," in v and all(_isnum(x) for x in v.split(",") if x.strip()):
            out[k] = [float(x) for x in v.split(",") if x.strip()]
        elif _isnum(v):
            out[k] = float(v)
        elif "," in v:
            out[k] = [x.strip() for x in v.split(",") if x.strip()]
        else:
            out[k] = v
    return out


def _isnum(s: str) -> bool:
    try:
        float(str(s).strip())
        return True
    except ValueError:
        return False


def build_props(kind: str, data: dict, palette: list[str], frames: int) -> dict:
    p = {"palette": palette, "durationInFrames": frames}
    if kind == "brand":
        p |= {"brand": str(data.get("brand", "BRAND"))[:22],
              "effect": data.get("effect", "crack"),
              "subtitle": str(data.get("subtitle", ""))[:34]}
    elif kind == "chart":
        pts = data.get("points") or [100, 70, 40, 15]
        p |= {"title": str(data.get("title", ""))[:44], "points": [float(x) for x in pts],
              "labels": data.get("labels") or [], "unit": str(data.get("unit", ""))}
    elif kind == "counter":
        p |= {"from": float(data.get("from", 0)), "to": float(data.get("to", 0)),
              "prefix": str(data.get("prefix", "")), "suffix": str(data.get("suffix", "")),
              "label": str(data.get("label", ""))[:40]}
    elif kind == "callout":
        p |= {"text": str(data.get("text", ""))[:90], "note": str(data.get("note", ""))[:50]}
    return p


def render_one(kind: str, props: dict, out: Path) -> None:
    npx = shutil.which("npx") or "npx"
    run([npx, "--yes", "remotion", "render", "src/index.ts", COMP[kind], str(out),
         "--props", json.dumps(props), "--log", "error"], timeout=1800)


def run_stage(cfg, ctx: Path, cost) -> dict:
    scenes = json.loads((ctx / "scenes.json").read_text(encoding="utf-8"))
    motion = [s for s in scenes if s.get("type") == "motion"]
    palette = cfg.channel["thumb_palette"]
    cache_dir = cfg.paths.cache_dir / "motion"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if not (MOTION_DIR / "node_modules").exists():
        raise SystemExit("Remotion не установлен: cd pipeline/motion && npm install")

    rendered, by_kind, cached = [], {}, 0
    cwd = Path.cwd()
    try:
        import os
        os.chdir(MOTION_DIR)
        for sc in motion:
            kind = sc.get("motion_kind", "callout")
            if kind not in COMP:
                kind = "callout"
            frames = int(max(sc.get("seconds", 4), 2) * FPS)
            props = build_props(kind, parse_data(sc.get("motion_data", "")), palette, frames)
            h = sha1(kind, json.dumps(props, sort_keys=True))
            dest = cache_dir / f"{h}.mp4"
            if dest.exists() and dest.stat().st_size > 0:
                cached += 1
            else:
                render_one(kind, props, dest)
            rendered.append({"idx": sc["idx"], "kind": kind, "file": str(dest)})
            by_kind[kind] = by_kind.get(kind, 0) + 1
    finally:
        import os
        os.chdir(cwd)

    (ctx / "motion.json").write_text(json.dumps(rendered, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    share = len(motion) / max(len(scenes), 1)
    lo, hi = cfg.channel.get("motion_share", [0.1, 0.15])
    cost.add("motion", "remotion", 0.0, f"{len(rendered)} сцен, из кэша {cached}")
    return {"motion_scenes": len(rendered), "total_scenes": len(scenes),
            "share": round(share, 3), "target_share": [lo, hi],
            "in_target": lo <= share <= hi, "by_kind": by_kind, "cached": cached}
