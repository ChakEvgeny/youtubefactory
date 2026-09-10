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

РАЗМЕТКА РИТМА. Перед каждым смысловым фрагментом ставь отдельной строкой:
[BEAT: hook|story|quote|turn|fact]
  hook  — первые ~15 секунд, максимальный темп;
  story — человеческая история, живая сцена с людьми;
  quote — прямая речь, цитата с именем;
  turn  — поворот сюжета, смена главы;
  fact  — ключевая цифра или вывод.
Фрагментов на ролик 12-20. Действует до следующего [BEAT: ...].

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


def run(cfg, ctx, cost, notes: str | None = None) -> dict:
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
{("" if not notes else chr(10) + "ОТДЕЛЬНЫЕ ТРЕБОВАНИЯ К ЭТОЙ ВЕРСИИ (важнее общих правил):" + chr(10) + notes + chr(10))}
Напиши сценарий."""

    resp = client_call(prompt)
    text, usage = resp
    cost.add("script", MODEL, claude_cost(MODEL, usage), f"~{words} слов")

    dst = ctx / "script.md"
    if dst.exists():                       # предыдущая версия не теряется
        n = len(list(ctx.glob("script.v*.md"))) + 1
        (ctx / f"script.v{n}.md").write_text(dst.read_text(encoding="utf-8"), encoding="utf-8")
    dst.write_text(text, encoding="utf-8")
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
BEAT_RE = re.compile(r"^\[BEAT:\s*(hook|story|quote|turn|fact)\s*\]\s*$",
                     re.IGNORECASE | re.MULTILINE)
ANY_MARK_RE = re.compile(r"^\[(?:SCENE|MOTION|BEAT):.+?\]\s*$", re.IGNORECASE | re.MULTILINE)


REMARK_SYSTEM = """Ты расставляешь разметку ритма в готовом сценарии.

ЖЁСТКОЕ ПРАВИЛО: текст сценария не меняется НИ ОДНИМ СЛОВОМ. Ты только вставляешь
новые строки [BEAT: ...] между абзацами. Существующие строки [SCENE: ...] и
[MOTION: ...] оставляешь на своих местах без изменений.

Перед каждым смысловым фрагментом вставь отдельной строкой:
[BEAT: hook|story|quote|turn|fact]
  hook  — открытие ролика, первые ~15 секунд;
  story — человеческая история, живая сцена с конкретными людьми;
  quote — прямая речь, цитата с именем и должностью;
  turn  — поворот сюжета, переход к новой главе;
  fact  — ключевая цифра, сравнение, вывод.

Фрагментов должно получиться 12-20. Первый обязательно hook.
Верни ПОЛНЫЙ текст сценария с добавленными строками, без markdown-ограждения,
без пояснений до и после."""


TAG_RE = re.compile(r"\[(?:pause|thoughtful|firmly|quietly|sighs)\]", re.IGNORECASE)

TAGS_SYSTEM = """Ты расставляешь аудио-теги ElevenLabs v3 в готовом сценарии закадрового текста.

ЖЁСТКОЕ ПРАВИЛО: слова сценария не меняются. Строки [SCENE: ...], [MOTION: ...],
[BEAT: ...] не трогаются. Ты только:
1) вставляешь теги ВНУТРИ абзацев речи: [pause] [thoughtful] [firmly] [quietly] [sighs];
2) переводишь в ЗАГЛАВНЫЕ одно слово в предложении там, где нужна эмфаза.

Лимиты:
- не чаще одного тега на 2-3 предложения; ставить только в эмоциональных точках
  (перед поворотом, перед цитатой, после сильной цифры) — не ради украшения;
- [pause] — только перед поворотом или ключевой цифрой, максимум 6 на весь текст;
- капс — не больше ОДНОГО слова в предложении, и не в каждом предложении:
  по одному-два на абзац максимум, только на слове, которое несёт удар.
Верни ПОЛНЫЙ текст без markdown-ограждения и без пояснений."""


def remark_tags(cfg, ctx, cost) -> dict:
    """Аудио-теги поверх готового текста: слова не трогаем, только теги и капс."""
    client = anthropic.Anthropic()
    script = (ctx / "script.md").read_text(encoding="utf-8")
    with client.messages.stream(model=MODEL, max_tokens=32000, system=TAGS_SYSTEM,
                                messages=[{"role": "user", "content": script}]) as st:
        msg = st.get_final_message()
    cost.add("script", MODEL, claude_cost(MODEL, msg.usage), "аудио-теги")
    out = "".join(b.text for b in msg.content if b.type == "text").strip()

    def bare(t):   # без разметки и без тегов, в нижнем регистре — сравниваем сами слова
        return TAG_RE.sub("", ANY_MARK_RE.sub("", t)).lower().split()
    a, b = bare(script), bare(out)
    if a != b:
        diff = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
        if diff > 3:
            return {"applied": False, "reason": f"слова изменились ({diff} расхождений)"}
    tags = TAG_RE.findall(out)
    sents = re.split(r"(?<=[.!?])\s+", ANY_MARK_RE.sub("", out))
    caps = sum(1 for sn in sents if len(re.findall(r"\b[A-Z]{3,}\b", sn)) > 1)
    k = len(list(ctx.glob("script.v*.md"))) + 1
    (ctx / f"script.v{k}.md").write_text(script, encoding="utf-8")
    (ctx / "script.md").write_text(out, encoding="utf-8")
    (ctx / "scenes.json").write_text(json.dumps(parse_scenes(out), ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    import collections
    return {"applied": True, "tags": len(tags), "by_tag": dict(collections.Counter(t.lower() for t in tags)),
            "sentences": len(sents), "sentences_with_2plus_caps": caps}


def remark_beats(cfg, ctx, cost) -> dict:
    """Разметка BEAT поверх готового текста: слова не трогаем."""
    client = anthropic.Anthropic()
    script = (ctx / "script.md").read_text(encoding="utf-8")
    with client.messages.stream(model=MODEL, max_tokens=32000, system=REMARK_SYSTEM,
                                messages=[{"role": "user", "content": script}]) as st:
        msg = st.get_final_message()
    cost.add("script", MODEL, claude_cost(MODEL, msg.usage), "разметка BEAT")
    out = "".join(b.text for b in msg.content if b.type == "text").strip()

    before = spoken_words(script)
    after = spoken_words(out)
    if abs(after - before) > max(8, before * 0.01):
        return {"applied": False, "reason": f"текст изменился: было {before} слов, стало {after}"}

    k = len(list(ctx.glob("script.v*.md"))) + 1
    (ctx / f"script.v{k}.md").write_text(script, encoding="utf-8")
    (ctx / "script.md").write_text(out, encoding="utf-8")
    (ctx / "scenes.json").write_text(json.dumps(parse_scenes(out), ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    beats = [m.group(1).lower() for m in BEAT_RE.finditer(out)]
    import collections
    return {"applied": True, "beats": len(beats), "by_type": dict(collections.Counter(beats)),
            "words_before": before, "words_after": after}


def beat_at(text: str, pos: int) -> str:
    """Тип фрагмента, действующий в этой позиции текста."""
    cur = "exposition"
    for m in BEAT_RE.finditer(text):
        if m.start() <= pos:
            cur = m.group(1).lower()
        else:
            break
    return cur


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
        it["beat"] = beat_at(text, it["char_pos"])
    return items


def spoken_words(text: str) -> int:
    return len(ANY_MARK_RE.sub("", text).split())
