#!/usr/bin/env python3
"""Оживление фотографии через DepthFlow с нашими движениями камеры.

Готовые пресеты DepthFlow зациклены: камера ходит туда-сюда по синусу. Для
документального кадра нужен односторонний проезд, поэтому движение считается
от tau (0..1) со сглаживанием на входе и выходе.
"""
from __future__ import annotations
import argparse, math
from pathlib import Path
from attrs import define
from depthflow.scene import DepthScene


def ease(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


@define
class Move(DepthScene):
    """Односторонний проезд. Параметры кладём в атрибуты класса перед запуском."""
    def update(self):
        p = ease(min(max(self.tau, 0.0), 1.0))
        k = (1.0 - p) if END_NEUTRAL else (p - 0.5)
        self.state.steady = 0.30
        self.state.focus = 0.35
        self.state.isometric = 0.60
        self.state.height = HEIGHT
        self.state.zoom = 1.0 - ZOOM * (1.0 - p if END_NEUTRAL else p)
        self.state.offset = (DX * k, DY * k)


MOVES = {                 # (сдвиг по x, по y, наезд)
    "push":  (0.10, 0.0, 0.07),
    "pull":  (-0.10, 0.0, -0.05),
    "left":  (-0.85, 0.0, 0.02),
    "right": (0.85, 0.0, 0.02),
    "down":  (0.0, 0.70, 0.03),
    "fly":   (0.60, -0.25, 0.05),
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image"); ap.add_argument("out")
    ap.add_argument("--dur", type=float, default=5.0)
    ap.add_argument("--mode", default="fly")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--height", type=float, default=0.32, help="глубина рельефа")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--end-neutral", action="store_true",
                    help="закончить ровно в исходной точке — под стык с клипом")
    a = ap.parse_args()
    dx, dy, zm = MOVES.get(a.mode, MOVES["fly"])
    globals()["DX"] = dx * a.strength
    globals()["DY"] = dy * a.strength
    globals()["ZOOM"] = zm * a.strength
    globals()["HEIGHT"] = a.height
    globals()["END_NEUTRAL"] = a.end_neutral
    scene = Move()
    scene.input(image=str(Path(a.image)))
    scene.main(output=str(Path(a.out)), time=a.dur, width=1280, height=720,
               fps=a.fps, ssaa=1.2)
    print("готово:", a.out)
