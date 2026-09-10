#!/usr/bin/env python3
"""Тест генеративных провайдеров на одном промпте: Veo 3.1 (fast и standard), Runway Gen-4.5
(text-to-video и image-to-video с реального CC-фото), Kling. Пишет клипы и cost.json в
/mnt/d/youtube/output/_gen_tests/. Проверяет доступ/ключи и печатает, чего не хватает."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.config import Config
from pipeline.sources import genvideo as gv

cfg = Config("business")
g = {**cfg.defaults["gen"], **cfg.channel["gen"]}
OUT = Path(cfg.paths.out_dir) / "_gen_tests"
OUT.mkdir(parents=True, exist_ok=True)
PROMPT = ("Wide shot of a car assembly line in a large factory hall at dawn, robotic arms paused, "
          "a few workers in hi-vis vests walking away from the line, cold light through high windows, "
          "slow push-in. " + g["style_prompt"])
photo = next(iter(sorted((Path(cfg.paths.cache_dir) / "collage").glob("*.jpg"))), None)
only = sys.argv[1:]          # veo_fast | veo | runway_t2v | runway_i2v | kling
tests = [("veo_fast", lambda: gv.veo(cfg, PROMPT, OUT / "veo_fast.mp4", seconds=6, model="veo-3.1-fast-generate-preview", negative=g["negative_prompt"])),
         ("veo", lambda: gv.veo(cfg, PROMPT, OUT / "veo_std.mp4", seconds=6, model="veo-3.1-generate-preview", negative=g["negative_prompt"])),
         ("runway_t2v", lambda: gv.runway(cfg, PROMPT, OUT / "runway_t2v.mp4", seconds=5, model=g["runway_model"], ratio=g["runway_ratio"])),
         ("runway_i2v", lambda: gv.runway(cfg, "Slow cinematic push-in, natural light, subtle handheld drift. " + g["style_prompt"],
                                          OUT / "runway_i2v.mp4", seconds=5, image=photo, model=g["runway_model"], ratio=g["runway_ratio"])),
         ("kling", lambda: gv.kling(cfg, PROMPT, OUT / "kling.mp4", seconds=5, model=g["kling_model"]))]
print("ключи:", {k: bool(cfg.key(k)) for k in ("GOOGLE_API_KEY", "RUNWAY_API_KEY", "KLING_API_KEY", "KLING_ACCESS_KEY")})
if cfg.key("RUNWAY_API_KEY"):
    try:
        print("runway:", gv.runway_credits(cfg))
    except Exception as e:
        print("runway: недоступен —", str(e)[:160])
if cfg.key("GOOGLE_API_KEY"):
    try:
        from google import genai
        ids = [m.name for m in genai.Client(api_key=cfg.key("GOOGLE_API_KEY")).models.list() if "veo" in m.name]
        print("veo модели:", ids)
    except Exception as e:
        print("gemini: недоступен —", str(e)[:160])
res = {}
for name, fn in tests:
    if only and name not in only:
        continue
    if name == "runway_i2v" and not photo:
        res[name] = {"error": "нет фото в кэше коллажей"}; continue
    try:
        r = fn(); res[name] = r
        print(f"  {name:<11} ok  {r['seconds']}с  ${r['usd']:.2f}  {r['elapsed']}с  {r['file']}")
    except Exception as e:
        res[name] = {"error": str(e)[:300]}
        print(f"  {name:<11} ошибка: {str(e)[:200]}")
(OUT / "cost.json").write_text(json.dumps({"prompt": PROMPT, "photo": str(photo), "results": res,
                                           "total_usd": round(sum(r.get("usd", 0) for r in res.values()), 3)}, ensure_ascii=False, indent=1), encoding="utf-8")
print("итого $", round(sum(r.get("usd", 0) for r in res.values()), 3))
