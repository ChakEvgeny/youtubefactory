"""critic — claude-opus-5, три прохода правок + отдельный проход по хуку."""
from __future__ import annotations

import json

import anthropic

from ..util import claude_cost, parse_json_block

MODEL = "claude-opus-5"

SYSTEM = """Ты редактор закадрового текста. Твоя работа — не хвалить, а резать.

Четыре прохода, в этом порядке:
1. ГДЕ ЗВУЧИТ КАК AI: шаблонные обороты, симметричные парные конструкции
   («не просто X, а Y»), нанизанные прилагательные, безличные связки,
   одинаковая длина предложений подряд, слова-пустышки (crucial, remarkable,
   fascinating, testament, delve, landscape, realm).
2. ГДЕ ВОДА: предложения, которые можно удалить без потери смысла;
   повторы уже сказанного; разгон перед мыслью.
3. ГДЕ ФАКТ БЕЗ ОПОРЫ НА BRIEF: любое утверждение с цифрой, датой, именем
   или причинностью, которого нет в BRIEF.
4. ГДЕ ЭТО ЗВУЧИТ КАК ОТЧЁТ, А НЕ КАК ИСТОРИЯ: абзацы, где подряд идут цифры
   и проценты без человека в кадре; статистика вместо последствия; перечисление
   показателей там, где можно показать, что это значило для конкретного дилера,
   поставщика или рабочего. Для каждого такого места предложи КОНКРЕТНУЮ замену
   на сцену с человеком, опираясь на факты BRIEF. Если в BRIEF нет подходящей
   человеческой сцены — так и скажи в why, но замену не выдумывай.

Правки применяй прямо в тексте. Строки [SCENE: ...] / [SHOT: ...] / [BEAT: ...] сохраняй как есть,
их менять нельзя. Длину сохраняй в пределах ±10%.

Отвечай ТОЛЬКО JSON без markdown:
{"script":"полный исправленный текст сценария",
 "changes":[{"pass":"ai|water|unsourced|report","before":"фрагмент до","after":"фрагмент после",
             "why":"кратко по-русски"}],
 "verdict":"что осталось слабым, 1-3 фразы"}"""

HOOK_SYSTEM = """Ты редактор хуков. Тебе дают первые ~15 секунд закадрового текста.
Хук должен: цеплять с первого предложения, содержать конкретику (цифру, имя, парадокс),
не иметь приветствий и разгона, обещать что-то, что закроется позже.
Отвечай ТОЛЬКО JSON: {"hook":"исправленный текст хука","why":"что изменил, по-русски",
"changed":true|false}"""


NUMBERS_SYSTEM = """Ты редактор. В тексте слишком много числовых показателей — он читается
как отчёт. Задача: оставить НЕ БОЛЬШЕ {limit} самых сильных чисел на весь сценарий.

Что считается числом: сумма, процент, количество людей/фирм/машин, доля рынка,
срок в годах. Даты событий и годы числами НЕ считаются — их не трогай.

Правила:
- Прямые цитаты людей не трогай вообще, даже если внутри цитаты есть число.
- Строки [SCENE: ...], [SHOT: ...], [BEAT: ...] и [MOTION: ...] не трогай.
- Лишнее число либо превращай в последствие («выручка упала на 24%» -> что это
  значило для конкретной фирмы или человека), либо убирай вместе с предложением,
  если без числа оно пустое.
- Оставляй те числа, которые бьют сильнее всего и держат сюжет.
- ДЛИНА: итог строго от {min_words} до {max_words} слов речи (без строк разметки).
  Это жёсткая рамка. Если после чистки текст просел — разверни оставшиеся
  человеческие сцены. Если вылез за верхнюю границу — режь описания и повторы,
  но не цитаты и не оставшиеся числа. Посчитай слова перед ответом.

Отвечай ТОЛЬКО JSON без markdown:
{{"script":"полный текст","kept":["число 1","число 2"],"removed":["что убрал"],
  "why":"1-2 фразы по-русски"}}"""


def numbers_pass(cfg, ctx, cost, limit: int = 12, min_words: int = 1600,
                 max_words: int = 1800) -> dict:
    """Пятый проход: чистка числовой плотности, цитаты не трогаются."""
    client = anthropic.Anthropic()
    script = (ctx / "script.md").read_text(encoding="utf-8")
    with client.messages.stream(
        model=MODEL, max_tokens=32000,
        system=NUMBERS_SYSTEM.format(limit=limit, min_words=min_words, max_words=max_words),
        messages=[{"role": "user", "content": script}]) as st:
        msg = st.get_final_message()
    cost.add("critic", MODEL, claude_cost(MODEL, msg.usage), f"проход по числам (лимит {limit})")
    data = parse_json_block("".join(b.text for b in msg.content if b.type == "text"))
    fixed = data.get("script") or script
    import re as _re
    n = len(_re.sub(r"^\[(?:SCENE|MOTION|SHOT|BEAT):.+?\]\s*$", "", fixed, flags=_re.M | _re.I).split())
    if not (min_words * 0.95 <= n <= max_words * 1.05):
        return {"applied": False, "words": n,
                "reason": f"после чистки {n} слов — вне рамки {min_words}-{max_words}, откат"}
    dst = ctx / "script.md"
    k = len(list(ctx.glob("script.v*.md"))) + 1
    (ctx / f"script.v{k}.md").write_text(script, encoding="utf-8")
    dst.write_text(fixed, encoding="utf-8")
    from .script import parse_scenes
    (ctx / "scenes.json").write_text(
        json.dumps(parse_scenes(fixed), ensure_ascii=False, indent=1), encoding="utf-8")
    return {"applied": True, "kept": data.get("kept", []), "removed": data.get("removed", []),
            "why": data.get("why", "")}


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
    cdst = ctx / "critic.md"
    if cdst.exists():
        n = len(list(ctx.glob("critic.v*.md"))) + 1
        (ctx / f"critic.v{n}.md").write_text(cdst.read_text(encoding="utf-8"), encoding="utf-8")
    cdst.write_text("\n".join(md) + "\n", encoding="utf-8")

    from .script import parse_scenes, spoken_words
    (ctx / "scenes.json").write_text(
        json.dumps(parse_scenes(fixed), ensure_ascii=False, indent=1), encoding="utf-8")
    return {"changes": len(data.get("changes", [])), "by_pass": by_pass,
            "hook_changed": bool(hook.get("changed")), "words": spoken_words(fixed)}
