#!/usr/bin/env python3
"""10 тем-кандидатов на нишу, привязанных к реальным роликам-аналогам."""
import json, os, re, sys
from pathlib import Path
import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
SC = Path(sys.argv[1])
load_dotenv(ROOT / ".env")
client = anthropic.Anthropic()
PRE = sys.argv[2] if len(sys.argv) > 2 else "dd"
data = json.loads((SC / f"{PRE}_data.json").read_text(encoding="utf-8"))
llm = json.loads((SC / f"{PRE}_llm.json").read_text(encoding="utf-8"))
hooks = json.loads((SC / f"{PRE}_hooks.json").read_text(encoding="utf-8"))

SYS = ("Ты предлагаешь темы для нового безликого YouTube-канала на английском. "
       "Каждая тема ДОЛЖНА опираться на конкретный ролик-аналог из списка: указывай его "
       "video_id как доказательство спроса. Тема — это конкретный сюжет, а не рубрика. "
       "Заголовок предлагай на английском, пояснение по-русски. Избегай тем, помеченных "
       "как ad-unfriendly. Не предлагай клонировать один и тот же сюжет несколько раз. "
       "Отвечай ТОЛЬКО JSON: {\"topics\":[{\"title_en\":\"...\",\"why_ru\":\"...\","
       "\"proof_video_id\":\"...\"}]} ровно 10 штук, без markdown.")

out, tin, tout = {}, 0, 0
for niche, d in data.items():
    idx = {v["id"]: v for v in d["top_views"] + d["top_vs"]}
    lines = [f"{v['id']} | views={v['views']:,} | канал {v['channel']} ({v['ch_age_m']} мес) "
             f"| vs={v['vs']} | {v['title']}" for v in idx.values()]
    warn = ""
    if niche == "industries_inside":
        warn = ("\n\nВАЖНО: субниша про рога/кожу быка Брахмана и любая переработка животных "
                "признана ad-unfriendly (забой, разделка). НЕ предлагай такие темы и не "
                "используй их как доказательство спроса.")
    r = client.messages.create(
        model="claude-opus-5", max_tokens=3000, system=SYS,
        messages=[{"role": "user", "content": f"НИША: {niche}\nРОЛИКИ:\n" + "\n".join(lines) + warn}])
    tin += r.usage.input_tokens; tout += r.usage.output_tokens
    t = "".join(b.text for b in r.content if b.type == "text")
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.MULTILINE).strip()
    j = json.loads(t[t.find("{"):t.rfind("}") + 1])
    out[niche] = j.get("topics", [])
    print(f"{niche:<22} тем: {len(out[niche])}")

(SC / f"{PRE}_topics.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"токены: вход {tin:,}, выход {tout:,} (~${tin/1e6 + tout/1e6*5:.3f})")
