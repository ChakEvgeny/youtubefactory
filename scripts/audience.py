#!/usr/bin/env python3
"""Стадия audience: комментарии под топ-10 роликов референсов (yt-dlp --write-comments)
-> Haiku по каждому ролику -> сводка docs/audience_<channel>.md + 10 тем-кандидатов
data/topics_comments.json (source=comments)."""
from __future__ import annotations
import glob, json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block

R = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/mnt/d/youtube/cache/refs/comments")
CHANNEL, NICHE = "business", "business_breakdowns"
client = anthropic.Anthropic(); cost = 0.0
targets = {t[1]: t for t in json.loads((R / "targets.json").read_text(encoding="utf-8"))}
cache_p = R / "audience_per_video.json"
per_video = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else []
done_ids = {a["id"] for a in per_video}
for f in sorted(glob.glob(str(R / "*.info.json"))):
    if Path(f).stem in done_ids:
        continue
    d = json.loads(Path(f).read_text(encoding="utf-8"))
    vid = d.get("id"); ch, _, title, views = targets.get(vid, ("?", vid, d.get("title", ""), d.get("view_count", 0)))
    cs = sorted(d.get("comments") or [], key=lambda c: -(c.get("like_count") or 0))
    # топ-уровень важнее ответов; обрезаем каждый до 280 символов, всего ≤ 300 комментариев
    text = "\n".join(f"[{c.get('like_count') or 0}👍] {(c.get('text') or '')[:280]}"
                     for c in cs if c.get("parent") in (None, "root"))[:300]
    prompt = (f"Ролик «{title}» (канал {ch}). Комментарии зрителей с числом лайков:\n{text}\n\n"
              "Разбери, что говорит аудитория. Верни ТОЛЬКО JSON:\n"
              "{\"praise\":[\"за что хвалят, коротко, ≤6 пунктов\"],"
              "\"requests\":[\"о чём просят рассказать / какие ролики хотят\"],"
              "\"complaints\":[\"на что жалуются: факты, монтаж, озвучка, длина, реклама — с пометкой темы\"],"
              "\"ai_voice_or_editing\":\"есть ли жалобы/подозрения на AI-озвучку или монтаж — цитата или 'нет'\","
              "\"topic_suggestions\":[{\"topic\":\"компания/бренд/событие\",\"why\":\"почему зрители просят\",\"likes\":число}],"
              "\"notable_quotes\":[\"2–3 самых залайканных характерных комментария\"]}")
    r = client.messages.create(model="claude-haiku-4-5", max_tokens=1800, messages=[{"role": "user", "content": prompt}])
    cost += claude_cost("claude-haiku-4-5", r.usage)
    a = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
    a.update({"id": vid, "channel": ch, "title": title, "views": views, "n_comments": len(cs)})
    per_video.append(a)
    print(f"  {ch[:6]} {title[:45]:<45} {len(cs):>4} комм., тем {len(a.get('topic_suggestions') or [])}")

def j(xs, n=400):
    """список из строк или словарей -> одна строка"""
    out = []
    for x in xs or []:
        out.append(x if isinstance(x, str) else "; ".join(f"{k}: {v}" for k, v in x.items()) if isinstance(x, dict) else str(x))
    return "; ".join(out)[:n]
(R / "audience_per_video.json").write_text(json.dumps(per_video, ensure_ascii=False, indent=1), encoding="utf-8")

# что зрители просят снять — regex по сырым комментариям («do a video on X», «what about X», «next: X»)
import collections
ask = collections.Counter()
ASK = re.compile(r"(?:video|episode|one|story|breakdown|deep ?dive)s? (?:on|about|covering) (?:the )?([A-Z][\w&'.\- ]{2,40}?)(?=[\s,.!?;:)]|$)"
                 r"|(?:what about|please cover|do|cover|next(?::| up)?) (?:the )?([A-Z][\w&'.\- ]{2,40}?)(?=[\s,.!?;:)]|$)")
for f in glob.glob(str(R / "*.info.json")):
    for c in json.loads(Path(f).read_text(encoding="utf-8")).get("comments") or []:
        for m in ASK.finditer(c.get("text") or ""):
            name = (m.group(1) or m.group(2) or "").strip(" .,'-")
            if 2 < len(name) < 40 and name.lower() not in ("this", "that", "it", "you", "the", "i", "how", "why", "what"):
                ask[name] += 1 + int((c.get("like_count") or 0) ** 0.5)
asked = [f"{k} ({v})" for k, v in ask.most_common(60)]
ref_subjects = [t[2] for t in targets.values()]

# сводка по всем 20
digest = json.dumps([{k: v for k, v in a.items() if k not in ("notable_quotes",)} for a in per_video], ensure_ascii=False)
prompt = ("Ниже разборы комментариев под 20 самыми популярными роликами двух каналов жанра business breakdown "
          "(Mondo Startups, Logically Answered). Мы запускаем свой канал в этом жанре: крах европейских и британских брендов, "
          "10–13 мин, закадровый голос ElevenLabs. Сведи в один отчёт. Верни ТОЛЬКО JSON:\n"
          "{\"praise\":[\"строка: что ценят (в N роликах)\"],"
          "\"requests\":[\"строка\"],"
          "\"complaints\":[\"строка: жалоба (в N роликах из 20); отдельно строки про AI-озвучку и про монтаж\"],"
          "\"ai_voice_verdict\":\"вывод: замечают ли AI-озвучку, как реагируют, что из этого следует для нас\","
          "\"editing_verdict\":\"вывод по монтажу/визуалу\","
          "\"topics\":[{\"title\":\"рабочее название темы (EN)\",\"angle\":\"угол\",\"why_story\":\"почему это история взлёта и падения\",\"evidence\":\"кто и как часто просит\",\"europe_uk\":true/false}]"
          "— ровно 10 тем, ТОЛЬКО из того, что зрители ПРОСЯТ снять (topic_suggestions и список ниже), "
          "НЕ сюжеты самих 20 роликов (их темы: " + "; ".join(ref_subjects)[:600] + "); приоритет европейским/британским брендам; "
          "\nЗАПРОСЫ ЗРИТЕЛЕЙ ПО REGEX (имя (вес по лайкам)): " + ", ".join(asked) + "\n"
          "\"rules_for_us\":[\"строка\"]} — все элементы массивов СТРОКИ, без вложенных объектов, кратко.\n\n" + digest)
r = client.messages.create(model="claude-haiku-4-5", max_tokens=8000, messages=[{"role": "user", "content": prompt}])
cost += claude_cost("claude-haiku-4-5", r.usage)
S = parse_json_block("".join(b.text for b in r.content if b.type == "text"))

L = [f"# Аудитория: {NICHE}", "",
     f"Источник: комментарии (топ по лайкам, до 400 на ролик) под 10 самыми просмотренными роликами Mondo Startups и "
     f"10 — Logically Answered; всего {sum(a['n_comments'] for a in per_video)} комментариев, 20 роликов. "
     f"Разбор — claude-haiku-4-5, ${cost:.2f}. Дата: 2026-09-10.", "",
     "## Что хвалят", ""] + [f"- {j([x])}" for x in S.get("praise", [])] + ["", "## О чём просят рассказать", ""] + \
    [f"- {j([x])}" for x in S.get("requests", [])] + ["", "## На что жалуются", ""] + [f"- {j([x])}" for x in S.get("complaints", [])] + \
    ["", f"**AI-озвучка.** {S.get('ai_voice_verdict','')}", "", f"**Монтаж.** {S.get('editing_verdict','')}", "",
     "## Правила для нас", ""] + [f"- {j([x])}" for x in S.get("rules_for_us", [])] + \
    ["", "## Темы-кандидаты (source=comments)", "", "| # | тема | угол | кто просит | EU/UK |", "|---|---|---|---|---|"]
for i, t in enumerate(S.get("topics", [])[:10], 1):
    L.append(f"| {i} | {t.get('title')} | {t.get('angle')} | {t.get('evidence')} | {'да' if t.get('europe_uk') else 'нет'} |")
L += ["", "## По роликам", ""]
for a in per_video:
    L += [f"### {a['channel']}: {a['title']} — {a['views']:,} просм., {a['n_comments']} комм.", "",
          f"- хвалят: {j(a.get('praise'))}",
          f"- просят: {j(a.get('requests'), 300)}",
          f"- жалобы: {j(a.get('complaints'))}",
          f"- AI/монтаж: {str(a.get('ai_voice_or_editing',''))[:200]}",
          f"- темы: {', '.join(t.get('topic','') for t in (a.get('topic_suggestions') or [])[:6])}", ""]
doc = ROOT / "docs" / f"audience_{CHANNEL}.md"
doc.write_text("\n".join(L) + "\n", encoding="utf-8")
rows = [{"channel": CHANNEL, "niche": NICHE, "title": t.get("title"), "angle": t.get("angle"),
         "summary": t.get("evidence"), "why_story": t.get("why_story"), "source": "comments",
         "priority": 150 + i} for i, t in enumerate(S.get("topics", [])[:10])]
(ROOT / "data" / "topics_comments.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
(R / "audience_raw.json").write_text(json.dumps({"per_video": per_video, "summary": S, "asked_regex": asked}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{doc.relative_to(ROOT)}: {len(L)} строк; тем {len(rows)}; ${cost:.3f}")
