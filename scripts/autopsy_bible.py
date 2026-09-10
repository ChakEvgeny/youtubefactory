#!/usr/bin/env python3
"""Сводит все замеры референсов в docs/format_bible_business.md и печатает
агрегаты по каналам (Mondo отдельно, остальные — контрольная группа)."""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/d/youtube/cache/refs")


def load(d: Path, name: str):
    p = d / f"video.{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 2) if xs else None


def agg(rows: list[dict]) -> dict:
    """Медианы по группе роликов."""
    out = {}
    out["duration_min"] = med([r["rhythm"].get("duration", 0) / 60 for r in rows])
    out["shots_per_min"] = med([r["rhythm"].get("per_min") for r in rows])
    out["shot_median"] = med([r["rhythm"].get("median") for r in rows])
    out["shot_p10"] = med([r["rhythm"].get("p10") for r in rows])
    out["shot_p90"] = med([r["rhythm"].get("p90") for r in rows])
    for sec in ("hook", "middle", "tail"):
        out[f"{sec}_median"] = med([r["rhythm"].get(sec, {}).get("median") for r in rows])
        out[f"{sec}_per_min"] = med([r["rhythm"].get(sec, {}).get("per_min") for r in rows])
    tr = defaultdict(list)
    for r in rows:
        for k, v in r["rhythm"].get("transitions_pct", {}).items():
            tr[k].append(v)
    out["transitions"] = {k: med(v) for k, v in tr.items()}
    out["micro_motion_share"] = med([r["rhythm"].get("micro_motion_share") for r in rows])
    ty = defaultdict(list)
    for r in rows:
        for k, v in r["frames"].get("type_pct", {}).items():
            ty[k].append(v)
    out["types"] = dict(sorted({k: med(v + [0] * (len(rows) - len(v))) for k, v in ty.items()}.items(),
                               key=lambda kv: -(kv[1] or 0)))
    out["text_share"] = med([r["frames"].get("text_share") for r in rows])
    ts = defaultdict(list)
    for r in rows:
        for k, v in r["frames"].get("text_size_pct", {}).items():
            ts[k].append(v)
    out["text_size"] = {k: med(v) for k, v in ts.items()}
    tp = defaultdict(list)
    for r in rows:
        for k, v in r["frames"].get("text_pos_pct", {}).items():
            tp[k].append(v)
    out["text_pos"] = {k: med(v) for k, v in tp.items()}
    bg = defaultdict(list)
    for r in rows:
        for k, v in r["frames"].get("bg_pct", {}).items():
            bg[k].append(v)
    out["bg"] = {k: med(v) for k, v in bg.items()}
    out["face_share"] = med([r["frames"].get("face_share") for r in rows])
    sp = [r["audio"].get("speech", {}) for r in rows]
    out["wpm"] = med([s.get("wpm") for s in sp])
    out["wpm_speaking"] = med([s.get("wpm_speaking") for s in sp])
    out["pauses_per_min"] = med([s.get("pauses_gt07_per_min") for s in sp])
    au = [r["audio"].get("audio", {}) for r in rows]
    out["music_in_pauses_db"] = med([a.get("music_in_pauses_db") for a in au])
    out["music_constant_share"] = round(sum(1 for a in au if a.get("music_constant")) / max(len(au), 1), 2)
    out["sfx_at_cuts"] = med([a.get("sfx_at_cuts_share") for a in au])
    st = [r["audio"].get("structure", {}) for r in rows]
    out["numbers_per_min"] = med([s.get("numbers_per_min") for s in st])
    out["chapters"] = med([s.get("chapters") for s in st])
    out["first_turn_sec"] = med([(s.get("first_turn") or {}).get("t") for s in st])
    return out


def main():
    sel = json.loads((R / "selection.json").read_text(encoding="utf-8"))
    thumbs = json.loads((R / "thumbs.json").read_text(encoding="utf-8")) if (R / "thumbs.json").exists() else {}
    groups = {}
    for key, vids in sel.items():
        rows = []
        for v in vids:
            d = R / v["id"]
            if not (d / "video.mp4").exists():
                continue
            rows.append({"id": v["id"], "title": v["title"], "views": v["views"], "date": v["date"],
                         "rhythm": load(d, "rhythm"), "frames": load(d, "frames"), "audio": load(d, "audio"),
                         "thumb": thumbs.get(v["id"], {})})
        groups[key] = rows
    result = {k: {"n": len(v), "agg": agg(v) if v else {}, "videos": v} for k, v in groups.items()}
    (R / "bible_data.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, g in result.items():
        a = g["agg"]
        print(f"\n=== {k} (n={g['n']}) ===")
        for kk in ("duration_min", "shots_per_min", "shot_median", "shot_p10", "shot_p90", "hook_median",
                   "middle_median", "tail_median", "transitions", "micro_motion_share", "types", "text_share",
                   "text_size", "text_pos", "bg", "face_share", "wpm", "wpm_speaking", "pauses_per_min",
                   "music_in_pauses_db", "music_constant_share", "sfx_at_cuts", "numbers_per_min", "chapters",
                   "first_turn_sec"):
            print(f"  {kk:<22} {a.get(kk)}")


if __name__ == "__main__":
    main()
