"""worldbible — библия мира перед генерацией кадров: герой (без имени и без сходства с реальным
человеком), локации, эпоха, палитра. Opus пишет описания по brief+script, Gemini рисует лист героя
и по одному пустому плану на локацию; дальше stills подаёт их референсами в каждый кадр."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..sources import genimage
from ..util import claude_cost, parse_json_block

MODEL = "claude-opus-5"


def run_stage(cfg, ctx: Path, cost) -> dict:
    import anthropic
    ch = cfg.channel
    brief = json.loads((ctx / "brief.json").read_text(encoding="utf-8"))
    script = (ctx / "script.md").read_text(encoding="utf-8")
    shots = re.findall(r"^\[SHOT:\s*(.+?)\s*\|", script, flags=re.M | re.I)
    style = ch.get("style_prompt", "")
    prompt = (f"История: {brief.get('topic')}\nУгол: {brief.get('angle','')}\n"
              f"Факты брифа (первые 25):\n" + "\n".join("- " + (f.get("fact") or "")[:160] for f in brief.get("facts", [])[:25]) +
              "\n\nСписок кадров из сценария:\n" + "\n".join("- " + x for x in shots[:120]) +
              "\n\nСоставь БИБЛИЮ МИРА для художника. Правила: герой — стилизованный персонаж, НЕ похожий на реального "
              "человека (не описывать реальные черты), без имени; эпоха и страна — из фактов; локации — все, что нужны кадрам, "
              "с одинаковыми ключами, как в кадрах. Верни ТОЛЬКО JSON:\n"
              "{\"era\":\"годы/страны\",\"palette\":\"3–4 цвета словами\",\n"
              " \"hero\":{\"key\":\"HERO\",\"look\":\"внешность 40–60 слов на английском: возраст, телосложение, волосы, одежда (одна и та же на весь ролик), характерная деталь\",\"prompt\":\"промпт листа персонажа на английском\"},\n"
              " \"others\":[{\"key\":\"clerk|officer|...\",\"look\":\"...\"}],\n"
              " \"locations\":[{\"key\":\"как в кадрах\",\"prompt\":\"пустой план локации на английском, 25–40 слов: пространство, свет, эпоха, предметы\"}],\n"
              " \"props\":[\"ключевые предметы\"]}")
    client = anthropic.Anthropic()
    r = client.messages.create(model=MODEL, max_tokens=6000, messages=[{"role": "user", "content": prompt}])
    cost.add("worldbible", MODEL, claude_cost(MODEL, r.usage), "описания мира")
    W = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
    out = ctx / "world"; out.mkdir(exist_ok=True)
    model = ch.get("image_model", "gemini-3.1-flash-image")
    spent = 0.0
    hp = out / "hero.jpg"
    if not hp.exists():
        res = genimage.generate(cfg, f"Character sheet, front three-quarter view, waist-up, neutral dark studio background: {W['hero']['look']}. {W['hero'].get('prompt','')} {style}", hp, model=model)
        spent += res["usd"]
    W["hero"]["file"] = str(hp)
    for loc in W.get("locations", [])[:10]:
        key = re.sub(r"[^a-z0-9]+", "_", loc["key"].lower()).strip("_")[:40]
        lp = out / f"loc_{key}.jpg"
        if not lp.exists():
            try:
                res = genimage.generate(cfg, f"Establishing shot, no people: {loc['prompt']} Era: {W.get('era','')}. Palette: {W.get('palette','')}. {style}", lp, model=model)
                spent += res["usd"]
            except Exception as e:
                loc["error"] = str(e)[:120]; continue
        loc["file"] = str(lp)
    cost.add("worldbible", model, spent, f"герой + {len(W.get('locations', []))} локаций")
    (ctx / "world.json").write_text(json.dumps(W, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"hero": bool(hp.exists()), "locations": sum(1 for l in W.get("locations", []) if l.get("file")),
            "era": W.get("era"), "usd_images": round(spent, 2)}
