#!/usr/bin/env python3
"""Переводит замеры референса (bible_data.json) в config/channels.yaml для канала business.

Ничего не придумывает: бюджет типов кадров, ритм по секциям, текст на экране,
переходы и звук берутся из медиан группы «mondo startups»; контрольная группа
(Logically Answered, JunkBondInvestor) — только для сверки в отчёте.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
R = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/d/youtube/cache/refs")
CHANNEL = "business"

# классы vision-классификатора -> типы источников нашего конвейера
MAP = {
    "cutout-collage": "collage", "logo-brand-card": "card", "text-kinetic": "card",
    "chart-graph": "motion", "article-screenshot": "screens", "map": "motion",
    "stock-video": "stock", "real-footage": "footage", "ai-image": "kling", "black-or-empty": None,
}


def main():
    data = json.loads((R / "bible_data.json").read_text(encoding="utf-8"))
    ref = data["mondo startups"]["agg"]
    types = ref.get("types", {})
    budget: dict = {}
    for cls, pct in types.items():
        k = MAP.get(cls)
        if k and pct:
            budget[k] = round(budget.get(k, 0) + pct / 100, 3)
    total = sum(budget.values()) or 1
    budget = {k: round(v / total, 3) for k, v in budget.items()}

    cfg_p = ROOT / "config" / "channels.yaml"
    cfg = yaml.safe_load(cfg_p.read_text(encoding="utf-8"))
    ch = cfg["channels"][CHANNEL]
    d = cfg["defaults"]

    fmt = {
        "source": "docs/format_bible_business.md",
        "measured_on": f"Mondo Startups, {data['mondo startups']['n']} видео (топ по просмотрам за 12 мес)",
        "shot_budget": budget,
        "pacing": {
            "hook": [max(round(ref["hook_median"] * 0.7, 1), 1.0), round(ref["hook_median"] * 1.3, 1)],
            "middle": [max(round(ref["middle_median"] * 0.7, 1), 1.0), round(ref["middle_median"] * 1.3, 1)],
            "tail": [max(round(ref["tail_median"] * 0.7, 1), 1.0), round(ref["tail_median"] * 1.3, 1)],
            "shots_per_min": ref["shots_per_min"],
            "p10": ref["shot_p10"], "p90": ref["shot_p90"],
        },
        "on_screen_text": {
            "share": ref["text_share"], "size_pct": ref.get("text_size"), "pos_pct": ref.get("text_pos"),
            "bg_pct": ref.get("bg"), "face_share": ref["face_share"],
        },
        "transitions_pct": ref.get("transitions"),
        "micro_motion_share": ref["micro_motion_share"],
        "audio": {
            "wpm": ref["wpm"], "wpm_speaking": ref["wpm_speaking"], "pauses_per_min": ref["pauses_per_min"],
            "music_constant": ref["music_constant_share"] >= 0.5,
            "music_in_pauses_db": ref["music_in_pauses_db"], "sfx_at_cuts": ref["sfx_at_cuts"],
        },
        "structure": {
            "duration_min": ref["duration_min"], "numbers_per_min": ref["numbers_per_min"],
            "chapters": ref["chapters"], "first_turn_sec": ref["first_turn_sec"],
        },
    }
    fmt["footage_rule"] = ("real-footage (новостная съёмка, интервью) у нас нет: 60% его доли идёт "
                           "в screens (карточки прессы, fair use ≤4 с), остаток — в collage")
    ch["format"] = fmt
    # рабочие ручки конвейера — из замера (deepcopy, чтобы yaml не ставил якоря)
    d["shot_budget"] = copy.deepcopy(budget)
    d["shot_seconds"] = list(fmt["pacing"]["middle"])
    d["narration_tempo"] = round(min(max((ref["wpm"] or 154) / 154, 0.95), 1.15), 3)
    ch["target_minutes"] = [int(ref["duration_min"] * 0.85), int(ref["duration_min"] * 1.15) + 1]
    cfg_p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    print("бюджет типов:", budget)
    print("ритм (сек/кадр):", fmt["pacing"])
    print("текст на экране:", fmt["on_screen_text"]["share"], "% кадров; переходы:", fmt["transitions_pct"])
    print("звук:", fmt["audio"])
    print("длина цель:", ch["target_minutes"], "мин; tempo", d["narration_tempo"])


if __name__ == "__main__":
    main()
