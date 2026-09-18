#!/usr/bin/env python3
"""Format autopsy, часть 2: тип кадра и текст на экране через Haiku vision.

Кадр каждые 2 с -> сетки 3x3 (480x270 на плитку) -> одна классификация на сетку.
Классы: cutout-collage, article-screenshot, logo-brand-card, stock-video, ai-image,
chart-graph, text-kinetic, map, real-footage, black-or-empty.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))
from pipeline.util import claude_cost, parse_json_block  # noqa: E402

MODEL = "claude-opus-5"
STEP = 2.0
GRID = 3
CLASSES = ["cutout-collage", "article-screenshot", "logo-brand-card", "stock-video", "ai-image",
           "chart-graph", "text-kinetic", "map", "real-footage", "black-or-empty"]
SYSTEM = (
    "Ты классифицируешь кадры документального YouTube-ролика. Дана сетка кадров, "
    "пронумерованных слева направо, сверху вниз. Для КАЖДОГО кадра верни:\n"
    "type — один из: " + ", ".join(CLASSES) + ".\n"
    "  cutout-collage: вырезанный объект/человек/логотип на однотонном или градиентном фоне;\n"
    "  article-screenshot: скриншот статьи, сайта, твита, документа;\n"
    "  logo-brand-card: логотип или название бренда крупно как главный объект;\n"
    "  stock-video: постановочная стоковая съёмка (офисы, люди в костюмах, конвейеры без привязки);\n"
    "  ai-image: сгенерированная картинка (гладкая, характерные артефакты);\n"
    "  chart-graph: график, диаграмма, таблица, счётчик;\n"
    "  text-kinetic: только текст/цифры на фоне, без предметного изображения;\n"
    "  map: карта; real-footage: реальная новостная/архивная съёмка, репортаж, интервью.\n"
    "text — есть ли на кадре текст (кроме мелких подписей): none | small | medium | large;\n"
    "text_pos — top | center | bottom | none;\n"
    "bg — dark | light | color (фон в основном тёмный / светлый / цветной);\n"
    "face — есть ли лицо крупно: true|false.\n"
    "Отвечай ТОЛЬКО JSON: {\"1\": {\"type\":..., \"text\":..., \"text_pos\":..., \"bg\":..., \"face\":...}, \"2\": {...}} "
    "без markdown."
)


def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def duration(p: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)])
    return float(r.stdout.strip() or 0)


def extract_frames(video: Path, out_dir: Path, step: float) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "f_%05d.jpg"
    if not any(out_dir.glob("f_*.jpg")):
        run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", f"fps=1/{step},scale=480:-2",
             "-q:v", "4", str(pattern)], timeout=1800)
    return sorted(out_dir.glob("f_*.jpg"))


def make_grid(frames: list[Path], out: Path) -> int:
    inputs = []
    for f in frames:
        inputs += ["-i", str(f)]
    n = len(frames)
    layout = "|".join(f"{(i % GRID) * 480}_{(i // GRID) * 270}" for i in range(n))
    filt = "".join(f"[{i}:v]scale=480:270,drawtext=text='{i+1}':fontsize=40:fontcolor=white:"
                   f"box=1:boxcolor=black@0.65:x=10:y=10[t{i}];" for i in range(n))
    filt += "".join(f"[t{i}]" for i in range(n)) + (f"xstack=inputs={n}:layout={layout}" if n > 1 else "null")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", filt, "-q:v", "4", str(out)])
    return n


def classify(video: Path, work: Path, client, budget: dict) -> dict:
    frames = extract_frames(video, work / "frames", STEP)
    per = []
    for i in range(0, len(frames), GRID * GRID):
        chunk = frames[i:i + GRID * GRID]
        grid = work / f"grid_{i:05d}.jpg"
        cache = grid.with_suffix(".json")
        if cache.exists():
            d = json.loads(cache.read_text(encoding="utf-8"))
        else:
            n = make_grid(chunk, grid)
            content = [{"type": "text", "text": f"Кадров в сетке: {n}."},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(grid.read_bytes()).decode()}}]
            try:
                r = client.messages.create(model=MODEL, max_tokens=1500, system=SYSTEM,
                                           messages=[{"role": "user", "content": content}])
                budget["usd"] += claude_cost(MODEL, r.usage)
                budget["calls"] += 1
                d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
            except Exception as e:
                print(f"    ! сетка {i}: {str(e)[:70]}")
                d = {}
            cache.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        for k, f in enumerate(chunk):
            v = d.get(str(k + 1), {}) if isinstance(d, dict) else {}
            per.append({"t": round((i + k) * STEP, 1), "type": v.get("type", "unknown"),
                        "text": v.get("text", "none"), "text_pos": v.get("text_pos", "none"),
                        "bg": v.get("bg", "?"), "face": bool(v.get("face"))})
    n = max(len(per), 1)
    types = Counter(x["type"] for x in per)
    txt = Counter(x["text"] for x in per)
    pos = Counter(x["text_pos"] for x in per if x["text"] != "none")
    bg = Counter(x["bg"] for x in per)
    return {
        "frames": len(per), "step": STEP,
        "type_pct": {k: round(v * 100 / n, 1) for k, v in types.most_common()},
        "text_share": round(sum(1 for x in per if x["text"] != "none") * 100 / n, 1),
        "text_size_pct": {k: round(v * 100 / n, 1) for k, v in txt.most_common()},
        "text_pos_pct": {k: round(v * 100 / max(sum(pos.values()), 1), 1) for k, v in pos.most_common()},
        "bg_pct": {k: round(v * 100 / n, 1) for k, v in bg.most_common()},
        "face_share": round(sum(1 for x in per if x["face"]) * 100 / n, 1),
        "per_frame": per,
    }


if __name__ == "__main__":
    video = Path(sys.argv[1])
    work = Path(sys.argv[2]) if len(sys.argv) > 2 else video.with_suffix("")
    out = video.with_suffix(".frames.json")
    budget = {"usd": 0.0, "calls": 0}
    res = classify(video, work, anthropic.Anthropic(), budget)
    res["cost_usd"] = round(budget["usd"], 4)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{video.name}: {res['frames']} кадров, {budget['calls']} вызовов, ${budget['usd']:.3f} | "
          f"типы {res['type_pct']} | текст на {res['text_share']}% кадров")
