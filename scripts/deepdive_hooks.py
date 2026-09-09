#!/usr/bin/env python3
"""Типы хуков из первых 60 сек + проверка ниши на ad-unfriendly контент."""
import json, os, re, sys
from pathlib import Path
import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-haiku-4-5"
SC = Path(sys.argv[1])
load_dotenv(ROOT / ".env")
client = anthropic.Anthropic()
PRE = sys.argv[2] if len(sys.argv) > 2 else "dd"
SAFETY_NICHE = sys.argv[3] if len(sys.argv) > 3 else None
data = json.loads((SC / f"{PRE}_data.json").read_text(encoding="utf-8"))
subs = json.loads((SC / f"{PRE}_subs.json").read_text(encoding="utf-8"))
pl = json.loads((SC / f"{PRE}_playlists.json").read_text(encoding="utf-8"))

def jparse(t):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.MULTILINE).strip()
    a, b = t.find("{"), t.rfind("}")
    return json.loads(t[a:b+1])

def ask(system, content, mt=3000):
    r = client.messages.create(model=MODEL, max_tokens=mt, system=system,
                               messages=[{"role": "user", "content": content}])
    return jparse("".join(b.text for b in r.content if b.type == "text")), r.usage

SYS_HOOK = ("Ты разбираешь ХУКИ — первые 60 секунд роликов YouTube. Выдели типы хуков "
            "(например: шокирующая цифра; прямой вопрос зрителю; обещание раскрыть секрет; "
            "сцена-загадка; личная история; отрицание общего мнения). Для каждого типа дай "
            "имя по-русски, короткое описание и ДОСЛОВНУЮ цитату из текста как пример. "
            "Отвечай ТОЛЬКО JSON: {\"hooks\":[{\"name\":\"...\",\"what\":\"...\",\"quote\":\"...\","
            "\"video_id\":\"...\"}]} без markdown.")

SYS_SAFE = ("Ты оцениваешь пригодность канала для рекламодателей YouTube. Ищи признаки "
            "ad-unfriendly контента: забой скота, разделка животных, кровь, жестокость, "
            "травмы, смерть. Отвечай ТОЛЬКО JSON: {\"verdict\":\"safe|risky|unsafe\","
            "\"reason\":\"кратко по-русски\",\"evidence\":[\"заголовок или что видно на обложке\"]} "
            "без markdown.")

out, tin, tout = {}, 0, 0
for niche, d in data.items():
    texts = {k: v for k, v in subs.get(niche, {}).items() if len(v) > 80}
    if not texts:
        out[niche] = {"hooks": [], "n_subs": 0}
        continue
    idx = {v["id"]: v for v in d["top_vs"] + d["top_views"]}
    body = "\n\n".join(f"video_id: {k}\nЗАГОЛОВОК: {idx.get(k,{}).get('title','')}\n"
                       f"ПЕРВЫЕ 60 СЕК: {t}" for k, t in texts.items())
    try:
        h, u = ask(SYS_HOOK, f"НИША: {niche}\n\n{body}")
        tin += u.input_tokens; tout += u.output_tokens
    except Exception as e:
        print(f"! хуки {niche}: {str(e)[:90]}"); h = {"hooks": []}
    out[niche] = {"hooks": h.get("hooks", []), "n_subs": len(texts)}
    print(f"{niche:<22} хуков: {len(h.get('hooks', []))} (по {len(texts)} роликам)")

# ── проверка Animal To Industry и Beyond Factory ────────────────────────────
safety = {}
_sn = SAFETY_NICHE or next(iter(data))
tgt = {t["channel"]: t["channel_id"] for t in data[_sn]["targets"]}
CHECK = list(tgt)[:4]
for name in CHECK:
    cid = tgt.get(name)
    if not cid:
        safety[name] = {"verdict": "нет данных", "reason": "канал не попал в список целей"}
        continue
    items = pl.get(_sn, {}).get(cid, {}).get("items", [])
    titles = "\n".join(f"- {i['title']}" for i in items[:20])
    content = [{"type": "text", "text": f"КАНАЛ: {name}\nПОСЛЕДНИЕ РОЛИКИ:\n{titles}\n\n"
                                        "Ниже обложки нескольких из них."}]
    for i in items[:4]:
        content.append({"type": "image", "source": {
            "type": "url", "url": f"https://i.ytimg.com/vi/{i['id']}/hqdefault.jpg"}})
    try:
        s, u = ask(SYS_SAFE, content, mt=1200)
        tin += u.input_tokens; tout += u.output_tokens
        safety[name] = s
        print(f"{name:<24} -> {s.get('verdict')}: {s.get('reason','')[:80]}")
    except Exception as e:
        safety[name] = {"verdict": "ошибка", "reason": str(e)[:100]}

(SC / f"{PRE}_hooks.json").write_text(json.dumps({"hooks": out, "safety": safety},
                                             ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\nтокены: вход {tin:,}, выход {tout:,} (~${tin/1e6 + tout/1e6*5:.3f})")
