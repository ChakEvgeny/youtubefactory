#!/usr/bin/env python3
"""Один клип Kling из утверждённого кадра, с жёстким промптом и автопроверкой.

Зачем: слепые дубли стоят денег. Правило из docs/generative.md — «промпт только про
камеру и движение, объект уже на кадре, ничего не дорисовываем». В первом тесте я его
нарушил, попросил «естественное движение головы», и модель перерисовала лицо.

После генерации клип сам проверяется на два дефекта:
  - уход стиля: доля пикселей вне палитры канала;
  - уход лица: vision-сверка первого, среднего и последнего кадра с исходником.
Не прошёл — печатается причина, и решение о дубле принимает человек, а не скрипт.

  python scripts/kling_shot.py <кадр.jpg> <выход.mp4> --motion "то, что должно двигаться"
"""
from __future__ import annotations
import argparse, base64, colorsys, json, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path
import numpy as np
from PIL import Image
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
from pipeline.config import Config
from pipeline.stages.assets import KLING_BASE, UA, kling_auth
from pipeline.sources.genvideo import _b64
from pipeline.util import claude_cost, parse_json_block
from pipeline import costs

PAL = [(0x1B, 0x2A, 0x5E), (0xC8, 0x9A, 0x3C), (0xE4, 0x53, 0x3A), (0xF2, 0xEC, 0xE0)]

# Замерено 2026-09-21 на двух дублях: ЖЁСТКАЯ рамка («не перерисовывай, не трогай
# лицо, ничего не меняй») даёт ХУДШИЙ результат — модель получает слишком мало
# свободы и пересобирает лицо целиком. Правило из docs/generative.md про «только
# камера и свет» выведено на фотореалистичном i2v реальных объектов и на рисованном
# персонаже не работает. Рабочая формулировка — мягкая: назвать стиль, который надо
# сохранить, и описать движение своими словами.
SOFT = ("Flat three-ink risograph illustration style is preserved exactly: same colours, same outlines, "
        "same halftone texture, no photorealism, no repainting, no added detail. Static camera. ")
# Жёсткий вариант оставлен для сравнения, по умолчанию не используется.
LOCK = ("This is an existing finished illustration. Do NOT redraw it, do NOT reinterpret it. Keep every "
        "line and colour exactly. The face must stay identical. Static camera. Only this changes: ")


def palette_off(im: Image.Image) -> float:
    a = np.asarray(im.convert("RGB").resize((240, 135)), dtype=float).reshape(-1, 3)
    best = np.full(len(a), 1e9)
    for c in PAL:
        best = np.minimum(best, np.linalg.norm(a - np.array(c), axis=1))
    return float((best > 95).mean())


def frame(v: Path, t: float) -> Image.Image:
    o = Path("/tmp/_kf.png")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(v), "-ss", str(t), "-frames:v", "1",
                    "-y", str(o)], check=True)
    return Image.open(o).convert("RGB")


def drift_check(src: Path, v: Path, dur: float):
    import anthropic
    cl = anthropic.Anthropic()
    shots = [frame(v, 0.2), frame(v, dur / 2), frame(v, max(dur - 0.3, 0.3))]
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(src.read_bytes()).decode()}}]
    for im in shots:
        p = Path("/tmp/_ks.jpg"); im.save(p, quality=90)
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                        "data": base64.b64encode(p.read_bytes()).decode()}})
    content.append({"type": "text", "text":
        "Кадр 1 — исходная иллюстрация. Кадры 2, 3, 4 — начало, середина и конец сгенерированного из неё "
        "клипа. Это один и тот же нарисованный человек во всех четырёх? Сверь форму лица, нос, бороду, "
        "очки, причёску. Отдельно скажи, менялся ли стиль рисунка. "
        'Верни ТОЛЬКО JSON {"same_person":true|false,"style_kept":true|false,"what_changed":"кратко"}'})
    r = cl.messages.create(model="claude-opus-5", max_tokens=900,
                           messages=[{"role": "user", "content": content}])
    try:
        return parse_json_block("".join(b.text for b in r.content if b.type == "text")), \
               claude_cost("claude-opus-5", r.usage)
    except Exception:
        return {"same_person": None}, claude_cost("claude-opus-5", r.usage)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--motion", required=True, help="что именно двигается, одной фразой")
    ap.add_argument("--seconds", type=int, default=5)
    ap.add_argument("--model", default="kling-v3")
    ap.add_argument("--mode", default="std")
    ap.add_argument("--strict", action="store_true",
                    help="жёсткая рамка вместо мягкой; на замере давала худший результат")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    cfg = Config()
    hdr = {"Authorization": kling_auth(cfg), "Content-Type": "application/json", "User-Agent": UA}
    body = {"model_name": a.model, "prompt": ((LOCK + a.motion) if a.strict else (SOFT + a.motion))[:2500], "duration": str(a.seconds),
            "aspect_ratio": "16:9", "mode": a.mode, "image": _b64(src)[0]}
    req = urllib.request.Request(f"{KLING_BASE}/v1/videos/image2video",
                                 data=json.dumps(body).encode(), headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"kling: {e.code} {e.read()[:200].decode('utf-8','ignore')}")
    if d.get("code") != 0:
        sys.exit(f"kling: {d.get('message')}")
    tid = d["data"]["task_id"]; t0 = time.time()
    while True:
        time.sleep(10)
        q = urllib.request.Request(f"{KLING_BASE}/v1/videos/image2video/{tid}", headers=hdr)
        with urllib.request.urlopen(q, timeout=60) as r:
            s = json.loads(r.read().decode())["data"]
        if s.get("task_status") == "succeed":
            urllib.request.urlretrieve(s["task_result"]["videos"][0]["url"], out); break
        if s.get("task_status") == "failed":
            sys.exit(f"kling: {s.get('task_status_msg')}")
        if time.time() - t0 > 900:
            sys.exit("kling: таймаут")
    usd = a.seconds * (0.084 if a.mode == "std" else 0.126)
    costs.log("work", "kling", a.model, usd, 1, a.motion[:40])
    print(f"клип: {out}  {int(time.time()-t0)} с, ${usd:.2f}")

    off_src, off_mid = palette_off(Image.open(src)), palette_off(frame(out, a.seconds / 2))
    v, ai = drift_check(src, out, a.seconds)
    print(f"палитра: было {off_src:.0%} вне, стало {off_mid:.0%}  "
          f"{'OK' if off_mid - off_src <= 0.03 else '← стиль поехал'}")
    print(f"лицо: тот же человек — {v.get('same_person')}, стиль сохранён — {v.get('style_kept')}")
    if v.get("what_changed"):
        print(f"      {v['what_changed'][:150]}")
    print(f"проверка ${ai:.3f}")


if __name__ == "__main__":
    main()
