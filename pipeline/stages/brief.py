"""brief — исследование темы через web_search, факты только с источниками."""
from __future__ import annotations

import json
from pathlib import Path

import anthropic

from ..util import claude_cost, parse_json_block

MODEL = "claude-opus-5"
SYSTEM = (
    "Ты собираешь фактуру для сценария документального ролика YouTube. "
    "Используй веб-поиск. Каждый факт обязан иметь источник (URL) и дату публикации "
    "или дату события. Факт без источника не включай вообще — это жёсткое правило. "
    "Нужно 15-25 фактов: цифры, даты, имена, суммы, причинно-следственные связи. "
    "Общие рассуждения не нужны, нужна конкретика, из которой можно собрать сюжет.\n"
    "Отвечай ТОЛЬКО JSON без markdown: {\"angle\":\"под каким углом подавать тему, 1-2 фразы\","
    "\"facts\":[{\"fact\":\"...\",\"number\":\"ключевая цифра или пусто\",\"source_url\":\"...\","
    "\"source_title\":\"...\",\"date\":\"YYYY-MM-DD или период\"}],"
    "\"open_questions\":[\"что осталось непроверенным\"]}"
)


def run(cfg, ctx, topic: str, cost, angle: str | None = None,
        research: str | None = None, augment: bool = False) -> dict:
    client = anthropic.Anthropic()
    ch = cfg.channel
    prev = {}
    if augment and (ctx / "brief.json").exists():
        prev = json.loads((ctx / "brief.json").read_text(encoding="utf-8"))
    prompt = (
        f"ТЕМА: {topic}\n"
        f"КАНАЛ: {ch['niche']} / {ch['subniche']}\n"
        f"ЦЕЛЕВАЯ ДЛИНА РОЛИКА: {ch['target_minutes'][0]}-{ch['target_minutes'][1]} минут "
        f"(значит фактуры нужно на связный сюжет такой длины).\n"
        + (f"ЗАДАННЫЙ УГОЛ ПОДАЧИ (следуй ему, фактуру ищи под него):\n{angle}\n\n"
           if angle else "")
        + (f"ЦЕЛЕВОЙ ЗАПРОС НА ДОБОР ФАКТУРЫ (ищи именно это):\n{research}\n\n"
           if research else "")
        + ("УЖЕ СОБРАНО, НЕ ПОВТОРЯЙ:\n"
           + "\n".join("- " + f["fact"][:110] for f in prev.get("facts", [])) + "\n\n"
           if prev.get("facts") else "")
        + "Собери фактуру по правилам из системного промпта."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 12}],
        messages=[{"role": "user", "content": prompt}],
    )
    cost.add("brief", MODEL, claude_cost(MODEL, resp.usage), "research + web_search")
    text = "".join(b.text for b in resp.content if b.type == "text")
    data = parse_json_block(text)

    facts = [f for f in data.get("facts", []) if (f.get("source_url") or "").startswith("http")]
    dropped = len(data.get("facts", [])) - len(facts)
    added = len(facts)
    if prev.get("facts"):
        seen = {(f.get("source_url"), (f.get("fact") or "")[:60]) for f in prev["facts"]}
        fresh = [f for f in facts if (f.get("source_url"), (f.get("fact") or "")[:60]) not in seen]
        added = len(fresh)
        facts = prev["facts"] + fresh
        data["open_questions"] = (data.get("open_questions") or [])
    data["facts"] = facts
    data["dropped_without_source"] = dropped
    if angle or prev.get("angle"):
        data["angle"] = angle or prev.get("angle")          # заданный угол приоритетнее выбранного моделью

    md = [f"# Brief — {topic}", "", f"**Угол подачи:** {data.get('angle','')}", "",
          f"Фактов с источником: **{len(facts)}**"
          + (f" (отброшено без источника: {dropped})" if dropped else ""), "",
          "| # | факт | цифра | дата | источник |",
          "|--:|------|-------|------|----------|"]
    for i, f in enumerate(facts, 1):
        md.append(f"| {i} | {f.get('fact','')} | {f.get('number','')} | {f.get('date','')} | "
                  f"[{(f.get('source_title') or 'link')[:40]}]({f['source_url']}) |")
    if data.get("open_questions"):
        md += ["", "## Осталось непроверенным", ""]
        md += [f"- {q}" for q in data["open_questions"]]

    (ctx / "brief.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    data["topic"] = topic                       # сценарию и библии мира нужна тема
    (ctx / "brief.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"facts": len(facts), "added": added, "dropped": dropped,
            "angle": data.get("angle", "")[:80]}
