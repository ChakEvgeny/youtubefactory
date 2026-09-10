#!/usr/bin/env python3
"""Сверка нашего превью с референсом тем же инструментом: ритм (scene-detect)
и доли типов кадров (тот же vision-классификатор). Печатает таблицу и пишет
compare.json рядом с превью."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

video = Path(sys.argv[1])
refs = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/mnt/d/youtube/cache/refs")
work = video.parent / "_compare"
work.mkdir(exist_ok=True)

import autopsy_rhythm as ar  # noqa: E402
import autopsy_frames as af  # noqa: E402
import anthropic  # noqa: E402

rhythm = ar.analyse(video, sample_transitions=25, sample_motion=20)
budget = {"usd": 0.0, "calls": 0}
frames = af.classify(video, work, anthropic.Anthropic(), budget)
ours = {"rhythm": rhythm, "frames": frames, "cost_usd": round(budget["usd"], 4)}
(video.parent / "compare.json").write_text(json.dumps(ours, ensure_ascii=False, indent=1), encoding="utf-8")

ref = json.loads((refs / "bible_data.json").read_text(encoding="utf-8"))["mondo startups"]["agg"]


def row(name, a, b):
    print(f"  {name:<26} {str(a):>14} {str(b):>14}")


print(f"\n{'':<26} {'референс':>14} {'наше превью':>14}")
row("кадров/мин", ref["shots_per_min"], rhythm["per_min"])
row("медиана кадра, с", ref["shot_median"], rhythm["median"])
row("p10 / p90", f"{ref['shot_p10']} / {ref['shot_p90']}", f"{rhythm['p10']} / {rhythm['p90']}")
row("хук медиана, с", ref["hook_median"], rhythm["hook"].get("median"))
row("середина медиана, с", ref["middle_median"], rhythm["middle"].get("median"))
row("микродвижение, доля", ref["micro_motion_share"], rhythm["micro_motion_share"])
row("переходы", ref.get("transitions"), rhythm["transitions_pct"])
row("текст на экране, %", ref["text_share"], frames["text_share"])
row("лицо крупно, %", ref["face_share"], frames["face_share"])
print("\n  типы кадров, %:")
keys = sorted(set(ref["types"]) | set(frames["type_pct"]), key=lambda k: -(ref["types"].get(k) or 0))
for k in keys:
    row("  " + k, ref["types"].get(k, 0), frames["type_pct"].get(k, 0))
print(f"\n  vision на превью: {budget['calls']} вызовов, ${budget['usd']:.3f}")
