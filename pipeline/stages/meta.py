"""meta — 3 заголовка по шаблонам ниши, описание с главами и источниками, 15 тегов."""
from __future__ import annotations

import json
from pathlib import Path

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

    # скелеты заголовков из замера референса (config/title_skeletons_<channel>.yaml)
    import yaml
    skp = Path(cfg.root) / "config" / f"title_skeletons_{cfg.channel_name}.yaml" if hasattr(cfg, "root") \
        else Path(__file__).resolve().parents[2] / "config" / f"title_skeletons_{cfg.channel_name}.yaml"
    skel = yaml.safe_load(skp.read_text(encoding="utf-8")) if skp.exists() else None
    if skel:
        masks = "\n".join(f"- {s['mask']}   [{s['family']}, ×{s['count']}, avg {s['avg_views']:,} views; e.g. «{s['examples'][0]}»]"
                          for s in skel["skeletons"])
        templates_block = ("МАСКИ ЗАГОЛОВКОВ (замер референса; каждый заголовок — ровно одна маска, плейсхолдеры "
                           "{BRAND}/{PERSON}/{MONEY}/{NUMBER}/{THING}/{VERB} заполняются фактами из брифа; верни поле mask у каждого):\n"
                           + masks + "\nПРАВИЛА:\n" + "\n".join("- " + r for r in skel.get("rules", [])))
    else:
        templates_block = "ШАБЛОНЫ ЗАГОЛОВКОВ:\n" + "\n".join("- " + t for t in ch["title_templates"])
    sysmsg = (
        "Ты пишешь упаковку для ролика YouTube на английском. Заголовки строго по маскам/шаблонам "
        "ниши, каждый ≤ 70 символов, без кликбейта, которого нет в ролике. Описание — "
        "3-5 предложений живым языком, без «in this video». Теги — 15 штук, нижний регистр, "
        "без решёток.\nОтвечай ТОЛЬКО JSON без markdown: "
        "{\"titles\":[\"...\",\"...\",\"...\"],\"title_masks\":[\"маска каждого\"],\"description\":\"...\",\"tags\":[\"...\"]}")
    prompt = (f"НИША: {ch['niche']} / {ch['subniche']}\n"
              + templates_block +
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
    lp = ctx / "sources_log.json"
    if lp.exists():
        log = json.loads(lp.read_text(encoding="utf-8"))
        imgs = [x for x in log if x.get("stage") == "collage" and x.get("license")]
        press = [x for x in log if x.get("stage") == "screens" and x.get("url")]
        if imgs:
            lines += ["", "Images (Wikimedia Commons):"]
            seen = set()
            for x in imgs:
                k = x["page"]
                if k in seen:
                    continue
                seen.add(k)
                lines.append(f"- {x['title'][5:80]} — {x['author'][:40]}, {x['license']}: {x['page']}")
        if press:
            lines += ["", "Press excerpts shown under fair use for commentary:"]
            seen = set()
            for x in press:
                if x["url"] in seen:
                    continue
                seen.add(x["url"])
                lines.append(f"- {x['outlet']}, {x.get('date','')}: {x['url']}")
    lines += ["", "Tags: " + ", ".join(data.get("tags", []))]
    (ctx / "meta.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    data["chapters"] = chs
    data["sources"] = uniq
    (ctx / "meta.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"titles": data["titles"], "tags": len(data.get("tags", [])),
            "chapters": len(chs), "sources": len(uniq)}
