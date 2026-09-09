"""critic — claude-opus-5, три прохода правок + отдельный проход по хуку."""
from __future__ import annotations

import json

import anthropic

from ..util import claude_cost, parse_json_block

MODEL = "claude-opus-5"

SYSTEM = """Ты редактор закадрового текста. Твоя работа — не хвалить, а резать.

Три прохода, в этом порядке:
1. ГДЕ ЗВУЧИТ КАК AI: шаблонные обороты, симметричные парные конструкции
   («не просто X, а Y»), нанизанные прилагательные, безличные связки,
   одинаковая длина предложений подряд, слова-пустышки (crucial, remarkable,
   fascinating, testament, delve, landscape, realm).
2. ГДЕ ВОДА: предложения, которые можно удалить без потери смысла;
   повторы уже сказанного; разгон перед мыслью.
3. ГДЕ ФАКТ БЕЗ ОПОРЫ НА BRIEF: любое утверждение с цифрой, датой, именем
   или причинностью, которого нет в BRIEF.

Правки применяй прямо в тексте. Строки [SCENE: ...] сохраняй как есть,
их менять нельзя. Длину сохраняй в пределах ±10%.

Отвечай ТОЛЬКО JSON без markdown:
{"script":"полный исправленный текст сценария",
 "changes":[{"pass":"ai|water|unsourced","before":"фрагмент до","after":"фрагмент после",
             "why":"кратко по-русски"}],
 "verdict":"что осталось слабым, 1-3 фразы"}"""

HOOK_SYSTEM = """Ты редактор хуков. Тебе дают первые ~15 секунд закадрового текста.
Хук должен: цеплять с первого предложения, содержать конкретику (цифру, имя, парадокс),
не иметь приветствий и разгона, обещать что-то, что закроется позже.
Отвечай ТОЛЬКО JSON: {"hook":"исправленный текст хука","why":"что изменил, по-русски",
"changed":true|false}"""


def run(cfg, ctx, cost) -> dict:
    client = anthropic.Anthropic()
    script = (ctx / "script.md").read_text(encoding="utf-8")
    brief = json.loads((ctx / "brief.json").read_text(encoding="utf-8"))
    anti = cfg.defaults["anti_slop"]
    facts = "\n".join(f"- {f['fact']} ({f.get('number','')}; {f.get('date','')})"
                      for f in brief["facts"])

    prompt = (f"ЗАПРЕЩЁННЫЕ ФРАЗЫ:\n{chr(10).join('- ' + p for p in anti['banned_phrases'])}\n\n"
              f"BRIEF (единственный допустимый источник фактов):\n{facts}\n\n"
              f"СЦЕНАРИЙ:\n{script}")
    with client.messages.stream(model=MODEL, max_tokens=32000, system=SYSTEM,
                                messages=[{"role": "user", "content": prompt}]) as st:
        msg = st.get_final_message()
    cost.add("critic", MODEL, claude_cost(MODEL, msg.usage), "три прохода")
    data = parse_json_block("".join(b.text for b in msg.content if b.type == "text"))
    fixed = data.get("script") or script

    # второй проход — только хук
    head = "\n".join(fixed.strip().splitlines()[:6])[:900]
    r2 = client.messages.create(model=MODEL, max_tokens=2000, system=HOOK_SYSTEM,
                                messages=[{"role": "user", "content": head}])
    cost.add("critic", MODEL, claude_cost(MODEL, r2.usage), "проход по хуку")
    hook = parse_json_block("".join(b.text for b in r2.content if b.type == "text"))
    if hook.get("changed") and hook.get("hook"):
        fixed = fixed.replace(head.strip(), hook["hook"].strip(), 1)

    (ctx / "script.md").write_text(fixed, encoding="utf-8")
    by_pass: dict = {}
    for c in data.get("changes", []):
        by_pass[c.get("pass", "?")] = by_pass.get(c.get("pass", "?"), 0) + 1
    md = ["# Критик", "", f"**Вердикт:** {data.get('verdict','')}", "",
          "| проход | правок |", "|--------|-------:|"]
    md += [f"| {k} | {v} |" for k, v in by_pass.items()]
    md += ["", f"**Хук:** {'переписан — ' + hook.get('why','') if hook.get('changed') else 'оставлен как был'}",
           "", "## Правки", ""]
    for c in data.get("changes", []):
        md += [f"**[{c.get('pass')}]** {c.get('why','')}", f"- было: {c.get('before','')[:160]}",
               f"- стало: {c.get('after','')[:160]}", ""]
    (ctx / "critic.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    from .script import parse_scenes, spoken_words
    (ctx / "scenes.json").write_text(
        json.dumps(parse_scenes(fixed), ensure_ascii=False, indent=1), encoding="utf-8")
    return {"changes": len(data.get("changes", [])), "by_pass": by_pass,
            "hook_changed": bool(hook.get("changed")), "words": spoken_words(fixed)}
