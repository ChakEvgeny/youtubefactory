"""script — сценарий под удержание, claude-fable-5-1, с разметкой сцен."""
from __future__ import annotations

import json
import re

import anthropic

from ..util import claude_cost

MODEL = "claude-fable-5-1"

SYSTEM = """Ты пишешь сценарий закадрового текста для безликого YouTube-канала на английском.
Пишет носитель языка, говорит человек, а не диктор корпоративного ролика.

УДЕРЖАНИЕ — единственная цель. Правила:
- Хук ≤ 15 секунд (примерно 35 слов). Начинай сразу с сути: цифра, парадокс, сцена.
  Никаких приветствий и представлений.
- Pattern interrupt каждые 60-90 секунд: смена ритма, прямой вопрос зрителю,
  неожиданная цифра, контраст. Отмечать не надо, просто делай.
- Open loops: обещание, которое закрывается позже. Минимум три на ролик,
  первое — в первые 30 секунд.
- Конкретика вместо общих слов. Каждый фактический тезис опирается на факт из BRIEF.
  Ничего сверх BRIEF не выдумывай.
- Разговорный английский: сокращения, короткие предложения, обращение на «you».

РАЗМЕТКА СЦЕН. Каждые 8-20 секунд речи вставляй отдельной строкой одно из двух:

[SCENE: что в кадре | stock query на английском 2-5 слов | kling: yes/no]
kling: yes — только если реального кадра заведомо не найти.

[MOTION: тип | данные]  — программная анимация вместо съёмки. Четыре типа:
  brand    | brand=Название; effect=crack|fire|fall; subtitle=2-3 слова приговора
  chart    | title=подпись; points=100,80,45,12; labels=2019,2021,2023,2025; unit=k
  counter  | from=0; to=4300000000; prefix=$; label=что за число
  callout  | text=короткий тезис; note=уточнение
MOTION уместен там, где в тексте звучит число, динамика, сумма или название
компании — рисовать это дешевле и честнее, чем искать похожий сток.

Формат ответа: чистый текст сценария со строками [SCENE: ...] между абзацами.
Никакого markdown, никаких заголовков, никаких пояснений до или после."""


def run(cfg, ctx, cost) -> dict:
    brief = json.loads((ctx / "brief.json").read_text(encoding="utf-8"))
    ch = cfg.channel
    anti = cfg.defaults["anti_slop"]
    words = cfg.target_words()
    kl_lo, kl_hi = cfg.defaults["kling_per_video"]
    m_lo, m_hi = ch.get("motion_share", [0.1, 0.15])
    kling_note = {"none": "kling: yes НЕ используй ни разу — канал строится на картах и стоке.",
                  "low": f"kling: yes максимум {kl_lo} раз, только для недостающих кадров.",
                  "high": f"kling: yes от {kl_lo} до {kl_hi} раз — ниша принимает генеративку."
                  }[ch.get("kling_bias", "low")]

    facts = "\n".join(f"- {f['fact']} ({f.get('number','')}; {f.get('date','')}; {f['source_url']})"
                      for f in brief["facts"])
    prompt = f"""КАНАЛ: {ch['niche']} / {ch['subniche']}
УГОЛ ПОДАЧИ: {brief.get('angle','')}
ЦЕЛЕВАЯ ДЛИНА: {ch['target_minutes'][0]}-{ch['target_minutes'][1]} минут, это примерно {words} слов
при темпе {cfg.defaults['words_per_minute']} слов в минуту.

ТИПЫ ХУКОВ, которые работают в этой нише (выбери один и разверни):
{chr(10).join('- ' + h for h in ch['hook_types'])}

ВИЗУАЛЬНЫЙ СТИЛЬ КАНАЛА (влияет на stock query в разметке сцен):
{ch['visual_style']}

{kling_note}

ДОЛЯ MOTION: от {int(m_lo*100)}% до {int(m_hi*100)}% всех сцен должны быть [MOTION: ...].
Остальные — [SCENE: ...].

ЗАПРЕЩЁННЫЕ ФРАЗЫ (ни одной, ни в каком виде):
{chr(10).join('- ' + p for p in anti['banned_phrases'])}

ПРАВИЛА СТИЛЯ:
{chr(10).join('- ' + r for r in anti['rules'])}

BRIEF — только эти факты, ничего сверх них:
{facts}

Напиши сценарий."""

    resp = client_call(prompt)
    text, usage = resp
    cost.add("script", MODEL, claude_cost(MODEL, usage), f"~{words} слов")

    (ctx / "script.md").write_text(text, encoding="utf-8")
    scenes = parse_scenes(text)
    (ctx / "scenes.json").write_text(json.dumps(scenes, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    spoken = spoken_words(text)
    n_motion = sum(1 for s in scenes if s["type"] == "motion")
    lo, hi = ch.get("motion_share", [0.1, 0.15])
    share = n_motion / max(len(scenes), 1)
    return {"words": spoken, "scenes": len(scenes),
            "kling_scenes": sum(1 for s in scenes if s["kling"]),
            "motion_scenes": n_motion, "motion_share": round(share, 3),
            "motion_in_target": lo <= share <= hi,
            "est_minutes": round(spoken / cfg.defaults["words_per_minute"], 1)}


def client_call(prompt: str):
    client = anthropic.Anthropic()
    with client.messages.stream(
        model=MODEL, max_tokens=32000, system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    text = "".join(b.text for b in msg.content if b.type == "text")
    return text, msg.usage


SCENE_RE = re.compile(r"^\[SCENE:\s*(.+?)\s*\|\s*(.+?)\s*\|\s*kling:\s*(yes|no)\s*\]\s*$",
                      re.IGNORECASE | re.MULTILINE)
MOTION_RE = re.compile(r"^\[MOTION:\s*(brand|chart|counter|callout)\s*\|\s*(.+?)\s*\]\s*$",
                       re.IGNORECASE | re.MULTILINE)
ANY_MARK_RE = re.compile(r"^\[(?:SCENE|MOTION):.+?\]\s*$", re.IGNORECASE | re.MULTILINE)


def parse_scenes(text: str) -> list[dict]:
    """Обе разметки в одном списке, порядок — по позиции в тексте."""
    items = []
    for m in SCENE_RE.finditer(text):
        items.append({"type": "stock", "description": m.group(1), "stock_query": m.group(2),
                      "kling": m.group(3).lower() == "yes", "char_pos": m.start()})
    for m in MOTION_RE.finditer(text):
        items.append({"type": "motion", "motion_kind": m.group(1).lower(),
                      "motion_data": m.group(2), "description": f"{m.group(1)}: {m.group(2)[:60]}",
                      "stock_query": "", "kling": False, "char_pos": m.start()})
    items.sort(key=lambda x: x["char_pos"])
    for i, it in enumerate(items):
        it["idx"] = i
    return items


def spoken_words(text: str) -> int:
    return len(ANY_MARK_RE.sub("", text).split())
