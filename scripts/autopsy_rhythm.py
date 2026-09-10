#!/usr/bin/env python3
"""Format autopsy, часть 1: ритм монтажа и переходы по scene-detect.

Вход: mp4. Выход: json с границами кадров, распределением длин по секциям
(хук 0-15с / середина / финал 30с), типом перехода на каждом стыке и
долей кадров с постоянным микродвижением.
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

SCENE_THR = 0.28          # порог ffmpeg scene: ниже — ловим и мягкие смены
HOOK_SEC = 15.0
TAIL_SEC = 30.0


def run(cmd, timeout=1800):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def duration(p: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(p)])
    return float(r.stdout.strip() or 0)


def scene_cuts(p: Path) -> list[float]:
    """Времена смен кадра по ffmpeg scene-детектору."""
    r = run(["ffmpeg", "-v", "info", "-i", str(p), "-vf",
             f"select='gt(scene,{SCENE_THR})',showinfo", "-an", "-f", "null", "-"])
    cuts = [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    # схлопываем стыки ближе 0.25с (dip/dissolve дают два срабатывания)
    out = []
    for t in sorted(cuts):
        if not out or t - out[-1] > 0.25:
            out.append(t)
    return out


def frame_stats(p: Path, t: float) -> tuple[float, float]:
    """Средняя яркость (YAVG) и разница с предыдущим кадром (YDIF) в момент t."""
    # signalstats пишет метрики только через metadata=print (в stdout)
    r = run(["ffmpeg", "-v", "error", "-ss", f"{max(t-0.05,0):.2f}", "-i", str(p), "-t", "0.12",
             "-vf", "scale=320:-2,signalstats,metadata=print:file=-", "-f", "null", "-"])
    y = re.findall(r"signalstats\.YAVG=([\d.]+)", r.stdout)
    d = re.findall(r"signalstats\.YDIF=([\d.]+)", r.stdout)
    return (float(y[-1]) if y else 128.0, float(d[-1]) if d else 0.0)


def transition_type(p: Path, t: float) -> str:
    """hard — резкая смена; dip — чёрный кадр у стыка; soft — плавная (dissolve/zoom/slide)."""
    y_before, _ = frame_stats(p, t - 0.30)
    y_at, d_at = frame_stats(p, t)
    y_after, _ = frame_stats(p, t + 0.30)
    if min(y_before, y_at, y_after) < 12:
        return "dip"
    # мягкий переход: разница размазана на соседние кадры
    _, d_prev = frame_stats(p, t - 0.15)
    _, d_next = frame_stats(p, t + 0.15)
    if d_at < 18 and (d_prev > 6 or d_next > 6):
        return "soft"
    return "hard"


def micro_motion(p: Path, a: float, b: float) -> float:
    """Среднее YDIF внутри кадра (между сменами) — есть ли постоянное движение."""
    if b - a < 1.2:
        return 0.0
    r = run(["ffmpeg", "-v", "error", "-ss", f"{a+0.3:.2f}", "-i", str(p), "-t", f"{min(b-a-0.6, 4):.2f}",
             "-vf", "scale=320:-2,fps=4,signalstats,metadata=print:file=-", "-f", "null", "-"])
    d = [float(x) for x in re.findall(r"signalstats\.YDIF=([\d.]+)", r.stdout)]
    return statistics.mean(d[1:]) if len(d) > 1 else 0.0     # первый YDIF всегда 0


def analyse(p: Path, sample_transitions: int = 40, sample_motion: int = 30) -> dict:
    dur = duration(p)
    cuts = scene_cuts(p)
    bounds = [0.0] + cuts + [dur]
    shots = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i + 1] - bounds[i] > 0.15]
    lens = [b - a for a, b in shots]

    def sect(lo, hi):
        ls = [b - a for a, b in shots if a >= lo and a < hi]
        ls_sorted = sorted(ls)
        if not ls:
            return {"n": 0}
        return {"n": len(ls), "median": round(statistics.median(ls), 2),
                "p10": round(ls_sorted[int(len(ls) * 0.1)], 2), "p90": round(ls_sorted[int(len(ls) * 0.9)], 2),
                "per_min": round(len(ls) / max((hi - lo) / 60, 0.01), 1)}

    ls_sorted = sorted(lens)
    step = max(len(cuts) // sample_transitions, 1)
    trans = {}
    for t in cuts[::step][:sample_transitions]:
        k = transition_type(p, t)
        trans[k] = trans.get(k, 0) + 1
    tot_t = sum(trans.values()) or 1

    stepm = max(len(shots) // sample_motion, 1)
    motion = [micro_motion(p, a, b) for a, b in shots[::stepm][:sample_motion]]
    moving = sum(1 for m in motion if m > 1.2) / max(len(motion), 1)

    return {
        "duration": round(dur, 1), "shots": len(shots), "per_min": round(len(shots) / (dur / 60), 1),
        "median": round(statistics.median(lens), 2) if lens else 0,
        "p10": round(ls_sorted[int(len(lens) * 0.1)], 2) if lens else 0,
        "p90": round(ls_sorted[int(len(lens) * 0.9)], 2) if lens else 0,
        "hook": sect(0, HOOK_SEC), "middle": sect(HOOK_SEC, dur - TAIL_SEC), "tail": sect(dur - TAIL_SEC, dur),
        "transitions_pct": {k: round(v * 100 / tot_t) for k, v in trans.items()},
        "micro_motion_share": round(moving, 2),
        "micro_motion_mean_ydif": round(statistics.mean(motion), 2) if motion else 0,
        "cuts": [round(c, 2) for c in cuts],
    }


if __name__ == "__main__":
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".rhythm.json")
    res = analyse(src)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    r = res
    print(f"{src.name}: {r['duration']}с, кадров {r['shots']} ({r['per_min']}/мин), медиана {r['median']}с "
          f"p10 {r['p10']} p90 {r['p90']} | хук {r['hook'].get('median')} / середина {r['middle'].get('median')} / "
          f"финал {r['tail'].get('median')} | переходы {r['transitions_pct']} | микродвижение {r['micro_motion_share']}")
