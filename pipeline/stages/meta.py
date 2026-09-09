"""meta — 3 заголовка по шаблонам ниши, описание с главами и источниками, 15 тегов."""
from __future__ import annotations

import json

import anthropic

from ..util import claude_cost, parse_json_block

MODEL = "claude-opus-5"


def chapters(ctx, n: int = 7) -> list[dict]:
    """Главы по равным долям длительности, привязанные к началам сцен."""
    ts = json.loads((ctx / "timestamps.json").read_text(encoding="utf-8"))
    scenes = json.loads((ctx / "scenes.json").read_text(encoding="utf-8"))
    total = ts.get("duration") or 0
    if not scenes or not total:
        return []
    step = max(len(scenes) // n, 1)
    words = ts["words"]
    out = []
    for i in range(0, len(scenes), step):
        frac = i / max(len(scenes), 1)
        t = total * frac
        out.append({"t": int(t), "scene": scenes[i]["description"][:60]})
    return out[:n]


def run_stage(cfg, ctx, cost) -> dict:
    client = anthropic.Anthropic()
    ch = cfg.channel
    brief = json.loads((ctx / "brief.json").read_text(encoding="utf-8"))
    script = (ctx / "script.md").read_text(encoding="utf-8")[:6000]
    chs = chapters(ctx)
    srcs = [{"title": f.get("source_title"), "url": f["source_url"]} for f in brief["facts"]]
    uniq, seen = [], set()
    for s in srcs:
        if s["url"] not in seen:
            seen.add(s["url"])
            uniq.append(s)

    sysmsg = (
        "Ты пишешь упаковку для ролика YouTube на английском. Заголовки строго по шаблонам "
        "ниши, каждый ≤ 70 символов, без кликбейта, которого нет в ролике. Описание — "
        "3-5 предложений живым языком, без «in this video». Теги — 15 штук, нижний регистр, "
        "без решёток.\nОтвечай ТОЛЬКО JSON без markdown: "
        "{\"titles\":[\"...\",\"...\",\"...\"],\"description\":\"...\",\"tags\":[\"...\"]}")
    prompt = (f"НИША: {ch['niche']} / {ch['subniche']}\n"
              f"ШАБЛОНЫ ЗАГОЛОВКОВ:\n" + "\n".join("- " + t for t in ch["title_templates"]) +
              f"\n\nУГОЛ: {brief.get('angle','')}\n\nНАЧАЛО СЦЕНАРИЯ:\n{script}")
    r = client.messages.create(model=MODEL, max_tokens=2000, system=sysmsg,
                               messages=[{"role": "user", "content": prompt}])
    cost.add("meta", MODEL, claude_cost(MODEL, r.usage), "заголовки, описание, теги")
    data = parse_json_block("".join(b.text for b in r.content if b.type == "text"))

    lines = [data["titles"][0], "", data.get("description", ""), "", "Chapters:"]
    for c in chs:
        lines.append(f"{c['t']//60}:{c['t']%60:02d} {c['scene']}")
    lines += ["", "Sources:"]
    lines += [f"- {s['title'] or s['url']}: {s['url']}" for s in uniq[:20]]
    lines += ["", "Tags: " + ", ".join(data.get("tags", []))]
    (ctx / "meta.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    data["chapters"] = chs
    data["sources"] = uniq
    (ctx / "meta.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"titles": data["titles"], "tags": len(data.get("tags", [])),
            "chapters": len(chs), "sources": len(uniq)}
