"""thumbs — 3 варианта обложки, проверка читаемости на даунскейле 160x90."""
from __future__ import annotations

import base64
import json
import random
from pathlib import Path

import anthropic

from ..util import claude_cost, ffprobe_duration, parse_json_block, run

VISION = "claude-haiku-4-5"


def best_frames(video: Path, out_dir: Path, n: int = 3) -> list[Path]:
    dur = ffprobe_duration(video)
    frames = []
    for i in range(n):
        t = dur * (0.15 + 0.3 * i)
        p = out_dir / f"_frame_{i}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.1f}", "-i", str(video),
             "-frames:v", "1", "-q:v", "2", str(p)])
        frames.append(p)
    return frames


def luma(img: Path) -> float:
    """Средняя яркость кадра 0..255 через signalstats (YAVG)."""
    p = run(["ffmpeg", "-v", "info", "-i", str(img), "-vf", "signalstats,metadata=print:file=-",
             "-f", "null", "-"], check=False)
    import re as _re
    m = _re.findall(r"YAVG=([\d.]+)", p.stdout or "")
    return float(m[-1]) if m else 128.0


def draw_text(bg: Path, text: str, palette: list[str], out: Path, w=1280, h=720):
    """Текст ≤4 слов крупно. Плашка подбирается по яркости фона:
    тёмный кадр -> светлая плашка с тёмным текстом, светлый -> наоборот.
    Раньше плашка всегда была palette[0] (красная) с белым текстом, и на
    тёмных кадрах проверка читаемости браковала 2 из 3 вариантов."""
    accent = palette[0] if palette else "#D0021B"
    dark_bg = luma(bg) < 110
    if dark_bg:
        box, fg = "#F4F4F2", "#111111"
    else:
        box, fg = "#111111", "#FFFFFF"
    safe = text.upper().replace("'", "").replace(":", "")
    fs = int(h * (0.20 if len(safe) <= 14 else 0.14 if len(safe) <= 24 else 0.10))
    # акцентная полоса канала под плашкой — узнаваемость без чужих логотипов
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"drawbox=x=0:y={int(h*0.86)}:w={w}:h={int(h*0.02)}:color={accent}@0.95:t=fill,"
          f"drawtext=text='{safe}':fontcolor={fg}:fontsize={fs}:"
          f"box=1:boxcolor={box}@0.90:boxborderw=30:"
          f"x=(w-text_w)/2:y=h-text_h-{int(h*0.14)}")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(bg), "-vf", vf, "-frames:v", "1",
         "-q:v", "2", str(out)])


def check_readable(paths: list[Path], client, cost) -> dict:
    """Даунскейл до 160x90 и вопрос модели: читается ли текст."""
    content = [{"type": "text", "text": "Каждая картинка — обложка ролика, ужатая до 160x90 "
                                        "(так её видит зритель в ленте на телефоне). "
                                        "Для каждой ответь, читается ли текст и различим ли объект."}]
    small = []
    for i, p in enumerate(paths):
        sp = p.with_name(p.stem + "_160.jpg")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf", "scale=160:90",
             "-q:v", "4", str(sp)])
        small.append(sp)
        content.append({"type": "text", "text": f"вариант {chr(97+i)}"})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.b64encode(sp.read_bytes()).decode()}})
    r = client.messages.create(
        model=VISION, max_tokens=1200,
        system=("Оцени читаемость обложек в миниатюре. Отвечай ТОЛЬКО JSON без markdown: "
                "{\"a\":{\"readable\":true|false,\"note\":\"кратко по-русски\"},\"b\":{...},\"c\":{...},"
                "\"best\":\"a|b|c\"}"),
        messages=[{"role": "user", "content": content}])
    cost.add("thumbs", VISION, claude_cost(VISION, r.usage), "проверка читаемости 160x90")
    return parse_json_block("".join(b.text for b in r.content if b.type == "text"))


def run_stage(cfg, ctx: Path, cost) -> dict:
    client = anthropic.Anthropic()
    ch = cfg.channel
    palette = ch["thumb_palette"]
    meta_p = ctx / "meta.json"
    if meta_p.exists():
        titles = json.loads(meta_p.read_text(encoding="utf-8")).get("titles", [])
    else:
        titles = []
    brief = json.loads((ctx / "brief.json").read_text(encoding="utf-8"))
    phrases = titles[:3] or [brief.get("angle", "")[:28]] * 3

    video = ctx / "video.mp4"
    bgs = best_frames(video, ctx) if video.exists() else []
    if not bgs:
        raise SystemExit("нет video.mp4 — стадия thumbs идёт после assemble")

    outs = []
    for i, name in enumerate("abc"):
        words = [w for w in (phrases[i % len(phrases)] or "").split() if w][:4]
        outs.append(ctx / f"thumb_{name}.jpg")
        draw_text(bgs[i % len(bgs)], " ".join(words) or "WATCH", palette, outs[-1])

    verdict = check_readable(outs, client, cost)
    for p in ctx.glob("_frame_*.jpg"):
        p.unlink(missing_ok=True)
    (ctx / "thumbs.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    return {"variants": [p.name for p in outs], "best": verdict.get("best"),
            "readable": {k: v.get("readable") for k, v in verdict.items() if isinstance(v, dict)}}
