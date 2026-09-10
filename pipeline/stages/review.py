"""review — свой цикл обратной связи вместо TwelveLabs.

Кадры каждые N секунд -> сетки 3x3 -> Haiku vision вместе с текстом сценария
на этом участке -> замечания по ритму, соответствию и пустым кадрам -> review.md.
"""
from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import anthropic

from ..util import claude_cost, ffprobe_duration, parse_json_block, run

VISION = "claude-haiku-4-5"
STEP = 5.0
GRID = 3            # 3x3 = 45 секунд на одну картинку
SYSTEM = (
    "Ты монтажёр-рецензент. Тебе дают сетку кадров из готового ролика (по одному кадру "
    "каждые 5 секунд, слева направо, сверху вниз) и текст закадрового голоса на этом же "
    "отрезке. Оцени три вещи:\n"
    "1) РИТМ — есть ли залипание (соседние кадры почти одинаковые), рваность, "
    "монотонность; 2) СООТВЕТСТВИЕ — показывает ли кадр то, о чём в этот момент речь; "
    "3) ПУСТЫЕ КАДРЫ — чёрные, серые, нечитаемый текст, обрезанные объекты, "
    "явный сток «не про то».\n"
    "Пиши по-русски, коротко, с номерами кадров в сетке (1-9). Не хвали.\n"
    "Отвечай ТОЛЬКО JSON: {\"rhythm\":{\"score\":0-10,\"notes\":[...]},"
    "\"match\":{\"score\":0-10,\"notes\":[...]},\"empty\":[{\"frame\":n,\"what\":\"...\"}],"
    "\"fix\":[\"конкретное действие\"]}"
)


def extract_grid(video: Path, t0: float, out: Path, step: float, n: int, w=1920, h=1080) -> int:
    """Сетка n x n из кадров начиная с t0 с шагом step."""
    tiles = []
    for i in range(n * n):
        t = t0 + i * step
        p = out.parent / f"_rv_{int(t0)}_{i}.jpg"
        try:
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                 "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(p)])
            if p.exists():
                tiles.append(p)
        except Exception:
            break
    if not tiles:
        return 0
    inputs = []
    for p in tiles:
        inputs += ["-i", str(p)]
    cols = n
    rows = (len(tiles) + cols - 1) // cols
    layout = "|".join(f"{(i % cols) * 480}_{(i // cols) * 270}" for i in range(len(tiles)))
    # подпись номера на каждом кадре
    filt = "".join(f"[{i}:v]drawtext=text='{i+1}':fontsize=42:fontcolor=white:box=1:boxcolor=black@0.6:"
                   f"x=12:y=12[t{i}];" for i in range(len(tiles)))
    filt += "".join(f"[t{i}]" for i in range(len(tiles))) + f"xstack=inputs={len(tiles)}:layout={layout}"
    if len(tiles) == 1:
        filt = "[0:v]drawtext=text='1':fontsize=42:fontcolor=white:x=12:y=12"
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", filt, "-q:v", "4", str(out)])
    for p in tiles:
        p.unlink(missing_ok=True)
    return len(tiles)


def change_gaps(video: Path, max_gap: float = 3.0, fps: int = 4, thr: float = 1.0) -> dict:
    """Правило референса: на экране что-то меняется каждые ≤3 с (смена кадра, движение
    камеры, motion). Считаем YDIF между соседними кадрами при 4 fps: кадр «изменился»,
    если YDIF > thr. Возвращаем долю времени в окнах длиннее max_gap без изменений."""
    import re as _re
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf",
                        f"scale=320:-2,fps={fps},signalstats,metadata=print:file=-", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=1800)
    d = [float(x) for x in _re.findall(r"signalstats\.YDIF=([\d.]+)", r.stdout)]
    if len(d) < fps * 2:
        return {"static_share": None, "violations": 0}
    total = len(d) / fps
    gaps, run = [], 0
    for i, v in enumerate(d):
        if v > thr:
            if run / fps > max_gap:
                gaps.append(((i - run) / fps, i / fps))
            run = 0
        else:
            run += 1
    if run / fps > max_gap:
        gaps.append(((len(d) - run) / fps, len(d) / fps))
    static = sum(b - a for a, b in gaps)
    return {"static_share": round(static / total, 3), "violations": len(gaps),
            "longest_static_sec": round(max((b - a for a, b in gaps), default=0.0), 1),
            "gaps": [(round(a, 1), round(b, 1)) for a, b in gaps[:20]]}


def run_stage(cfg, ctx: Path, cost, preview_sec: float | None = None) -> dict:
    video = ctx / ("preview.mp4" if preview_sec else "video.mp4")
    if not video.exists():
        raise SystemExit(f"нет {video.name} — review идёт после assemble")
    ts = json.loads((ctx / "timestamps.json").read_text(encoding="utf-8"))
    words = ts["words"]
    dur = ffprobe_duration(video)
    client = anthropic.Anthropic()
    span = STEP * GRID * GRID
    blocks, t0 = [], 0.0
    while t0 < dur:
        grid = ctx / f"_review_{int(t0):04d}.jpg"
        n = extract_grid(video, t0, grid, STEP, GRID)
        if n == 0:
            break
        text = " ".join(w["word"] for w in words if t0 <= w["start"] < t0 + span)
        content = [{"type": "text", "text": f"ОТРЕЗОК {t0:.0f}–{min(t0+span,dur):.0f}с, кадров в сетке: {n}\n"
                                            f"ТЕКСТ ГОЛОСА НА ОТРЕЗКЕ:\n{text[:1500]}"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(grid.read_bytes()).decode()}}]
        try:
            r = client.messages.create(model=VISION, max_tokens=1500, system=SYSTEM,
                                       messages=[{"role": "user", "content": content}])
            cost.add("review", VISION, claude_cost(VISION, r.usage), f"отрезок {t0:.0f}с")
            d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
        except Exception as e:
            d = {"error": str(e)[:120]}
        blocks.append({"t0": t0, "t1": min(t0 + span, dur), "frames": n, "grid": grid.name, **d})
        t0 += span

    cg = change_gaps(video)
    lines = [f"# Review — {video.name}", "", f"Длительность {dur:.0f}с, кадр каждые {STEP:.0f}с, "
             f"сеток {len(blocks)}.", ""]
    if cg.get("static_share") is not None:
        lines += [f"**Правило ≤3 с:** без изменений на экране {cg['static_share']*100:.0f}% времени, "
                  f"окон дольше 3 с — {cg['violations']}, самое длинное {cg['longest_static_sec']} с"
                  + (f" ({', '.join(f'{a}–{b}' for a, b in cg['gaps'][:8])})" if cg["gaps"] else ""), ""]
    rs = [b["rhythm"]["score"] for b in blocks if "rhythm" in b]
    ms = [b["match"]["score"] for b in blocks if "match" in b]
    empties = sum(len(b.get("empty", [])) for b in blocks)
    if rs:
        lines += [f"**Ритм:** {sum(rs)/len(rs):.1f}/10  **Соответствие:** {sum(ms)/len(ms):.1f}/10  "
                  f"**Пустых/сломанных кадров:** {empties}", ""]
    for b in blocks:
        lines += [f"## {b['t0']:.0f}–{b['t1']:.0f}с  (`{b['grid']}`)", ""]
        if "error" in b:
            lines += [f"ошибка: {b['error']}", ""]
            continue
        lines += [f"Ритм {b['rhythm']['score']}/10:"] + [f"- {n}" for n in b["rhythm"].get("notes", [])]
        lines += [f"Соответствие {b['match']['score']}/10:"] + [f"- {n}" for n in b["match"].get("notes", [])]
        if b.get("empty"):
            lines += ["Пустые/сломанные:"] + [f"- кадр {e.get('frame')}: {e.get('what')}" for e in b["empty"]]
        if b.get("fix"):
            lines += ["Что сделать:"] + [f"- {f}" for f in b["fix"]]
        lines.append("")
    (ctx / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"grids": len(blocks), "rhythm": round(sum(rs)/len(rs), 1) if rs else None,
            "match": round(sum(ms)/len(ms), 1) if ms else None, "empty_frames": empties,
            "static_share": cg.get("static_share"), "static_violations": cg.get("violations"),
            "file": str(ctx / "review.md")}
