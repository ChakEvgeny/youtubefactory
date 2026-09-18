"""storyboard — кадры [SHOT]/[MOTION] сценария по таймкодам голоса: интервал каждого кадра,
крупность, движение (i2v для ключевых, иначе push/zoom), аннотация Opus: локация из библии мира,
присутствие героя, камера. Пишет storyboard.json и shotlist.json (для стадии motion)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..util import claude_cost, parse_json_block
from .script import ANY_MARK_RE

MODEL = "claude-opus-5"
MAX_SHOT = 3.5      # длиннее — режем: тот же кадр другой крупностью (референс: 2–3 с)
MIN_SHOT = 1.6


def scene_times(script: str, scenes: list[dict], words: list[dict]) -> list[float]:
    """Старт каждого кадра = время первого произнесённого слова после его позиции в тексте."""
    # позиция -> порядковый номер произнесённого слова
    starts = []
    for sc in scenes:
        before = ANY_MARK_RE.sub("", script[:sc["char_pos"]])
        n = len(before.split())
        n = min(n, len(words) - 1)
        starts.append(float(words[n]["start"]) if words else 0.0)
    return starts


def run_stage(cfg, ctx: Path, cost, preview_sec: float | None = None) -> dict:
    import anthropic
    script = (ctx / "script.md").read_text(encoding="utf-8")
    scenes = json.loads((ctx / "scenes.json").read_text(encoding="utf-8"))
    ts = json.loads((ctx / "timestamps.json").read_text(encoding="utf-8"))
    words = ts["words"]
    total = float(words[-1]["end"]) if words else 0.0
    world = json.loads((ctx / "world.json").read_text(encoding="utf-8")) if (ctx / "world.json").exists() else {}
    starts = scene_times(script, scenes, words)
    shots = []
    if scenes and starts and starts[0] > 0.5:          # речь началась до первого [SHOT]: первый кадр — с нуля
        starts[0] = 0.0
    CROPS = ["wide", "medium", "close", "insert"]
    for i, sc in enumerate(scenes):
        a = starts[i]
        b = starts[i + 1] if i + 1 < len(scenes) else total
        if b - a < 0.3:
            continue
        text = " ".join(w["word"] for w in words if a <= w["start"] < b)
        base = {"scene": i, "beat": sc.get("beat", "exposition"), "text": text}
        if sc["type"] == "motion":
            shots.append({**base, "kind": "motion", "motion_kind": sc["motion_kind"], "motion_data": sc["motion_data"],
                          "start": a, "end": b, "prompt": sc["description"]})
            continue
        # длинный кадр режем на части: та же сцена, другая крупность
        n_parts = max(1, int((b - a) // MAX_SHOT) + (1 if (b - a) % MAX_SHOT > MIN_SHOT else 0))
        step = (b - a) / n_parts
        for k in range(n_parts):
            base_kind = sc.get("shot_kind", "medium")
            kind_k = base_kind if k == 0 else CROPS[(CROPS.index(base_kind) + k) % 4 if base_kind in CROPS else k % 4]
            shots.append({**base, "kind": "shot", "start": a + k * step, "end": a + (k + 1) * step,
                          "prompt": sc["description"] + ("" if k == 0 else f" — different angle, {kind_k}, same scene a moment later"),
                          "shot_kind": kind_k,
                          "variant": k, "text": " ".join(w["word"] for w in words if a + k * step <= w["start"] < a + (k + 1) * step)})
    for i, sh in enumerate(shots):
        sh["idx"] = i
        sh["dur"] = round(sh["end"] - sh["start"], 2)
        sh["kind_src"] = "still"
        sh["src_kind"] = "motion" if sh["kind"] == "motion" else "still"
        sh["dip_before"] = bool(i and sh["beat"] == "turn" and shots[i - 1]["beat"] != "turn")
        # движение: хук — punch, дальше чередование; i2v — ключевые кадры
        sh["fx"] = "punch" if sh["beat"] == "hook" else ["pushin", "zoomout", "kenburns_slow"][i % 3]
        sh["i2v"] = sh["kind"] == "shot" and (sh["beat"] in ("hook", "turn") or i % 3 == 0) and sh["dur"] >= 2.5
    # аннотация Opus: локация из библии, герой в кадре, камера — батчами
    client = anthropic.Anthropic()
    locs = [l["key"] for l in world.get("locations", [])]
    todo = [sh for sh in shots if sh["kind"] == "shot" and (preview_sec is None or sh["start"] < preview_sec)]
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        listing = "\n".join(f"{sh['idx']} [{sh.get('shot_kind','medium')}] сцена: {sh['prompt']} || в этом кадре звучит: {sh['text'][:160]}" for sh in chunk)
        prompt = (f"Локации библии мира (используй ТОЛЬКО эти ключи): {locs}\nГерой: HERO ({world.get('hero',{}).get('look','')[:120]})\n\n"
                  f"Кадры:\n{listing}\n\nДля каждого кадра верни: location (ключ из списка или \"\"), hero (true/false — герой в кадре), "
                  "camera (одна фраза движения камеры для image-to-video, на английском, например 'slow push-in', 'handheld drift left'), "
                  "image_prompt (готовый промпт кадра на английском 25–45 слов: кто, где, что ИМЕННО делает в тот момент, когда звучит текст этого кадра, свет, крупность; без имён, текста и логотипов). "
                  "ВАЖНО: соседние кадры одной сцены обязаны отличаться действием, объектом или ракурсом — это разные моменты одной сцены, "
                  "как раскадровка кино (например: рука со штампом → лицо клерка → бланк крупно → герой выходит на улицу). Одинаковых промптов подряд быть не должно. "
                  "Верни ТОЛЬКО JSON {\"shots\":{\"<idx>\":{\"location\":\"..\",\"hero\":true,\"camera\":\"..\",\"image_prompt\":\"..\"}}}")
        r = client.messages.create(model=MODEL, max_tokens=8000, messages=[{"role": "user", "content": prompt}])
        cost.add("storyboard", MODEL, claude_cost(MODEL, r.usage), f"аннотация кадров {chunk[0]['idx']}+")
        try:
            d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))["shots"]
        except Exception as e:
            print(f"    ! аннотация {chunk[0]['idx']}+: {str(e)[:80]}"); d = {}
        for sh in chunk:
            v = d.get(str(sh["idx"])) or {}
            sh["location"] = v.get("location") or ""
            sh["hero"] = bool(v.get("hero"))
            sh["camera"] = v.get("camera") or "slow push-in"
            sh["image_prompt"] = v.get("image_prompt") or sh["prompt"]
    (ctx / "storyboard.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    (ctx / "shotlist.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    n_shot = sum(1 for s in shots if s["kind"] == "shot")
    return {"shots": len(shots), "stills": n_shot, "motion": len(shots) - n_shot,
            "i2v": sum(1 for s in todo if s.get("i2v")), "per_min": round(len(shots) / max(total / 60, 0.1), 1),
            "median_sec": round(sorted(s["dur"] for s in shots)[len(shots) // 2], 2) if shots else None}
