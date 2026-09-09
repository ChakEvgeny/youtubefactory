#!/usr/bin/env python3
"""LLM-разбор: субниши, шаблоны заголовков, обложки. claude-haiku-4-5."""
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
data = json.loads((SC / f"{PRE}_data.json").read_text(encoding="utf-8"))

def jparse(t):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.MULTILINE).strip()
    a, b = t.find("{"), t.rfind("}")
    if a == -1: raise ValueError(t[:200])
    return json.loads(t[a:b+1])

def ask(system, content, max_tokens=4000):
    r = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                               messages=[{"role": "user", "content": content}])
    txt = "".join(b.text for b in r.content if b.type == "text")
    return jparse(txt), r.usage

SYS_CLUSTER = (
    "Ты разбиваешь ролики YouTube одной ниши на 4-6 субниш по смыслу темы. "
    "Субниша — это устойчивый поджанр, а не отдельный ролик. Дай короткое имя "
    "по-русски и отнеси КАЖДЫЙ ролик ровно к одной субнише. "
    "Отвечай ТОЛЬКО JSON: {\"clusters\":[{\"id\":\"c1\",\"name\":\"...\",\"what\":\"...\"}],"
    "\"assign\":{\"<video_id>\":\"c1\"}} без markdown.")

SYS_TEMPLATE = (
    "Ты разбираешь СТРУКТУРУ заголовков роликов YouTube. Определи 5-7 повторяющихся "
    "шаблонов (например: число в начале; 'Inside X'; 'How X is made'; вопрос; "
    "контраст 'X vs Y'; превосходная степень; интрига без раскрытия). "
    "Дай шаблону имя по-русски и схему в виде маски. Отнеси каждый заголовок ровно "
    "к одному шаблону. Отвечай ТОЛЬКО JSON: {\"templates\":[{\"id\":\"t1\",\"name\":\"...\","
    "\"mask\":\"...\"}],\"assign\":{\"<video_id>\":\"t1\"}} без markdown.")

SYS_THUMB = (
    "Ты описываешь обложки роликов YouTube. Для каждой: object — главный объект одним "
    "словосочетанием; text — есть ли крупный текст (да/нет) и какой; colors — 2-3 "
    "доминирующих цвета; face — есть ли человеческое лицо крупным планом (да/нет). "
    "Отвечай ТОЛЬКО JSON: {\"<video_id>\":{\"object\":\"...\",\"text\":\"...\","
    "\"colors\":\"...\",\"face\":\"да/нет\"}} без markdown.")

out, tin, tout = {}, 0, 0
for niche, d in data.items():
    print(f"\n=== {niche} ===")
    pool = {v["id"]: v for v in d["top_views"]}
    for v in d["top_vs"]:
        pool.setdefault(v["id"], v)
    listing = "\n".join(
        f"{v['id']} | views={v['views']} | ch_age={v['ch_age_m']} мес | vs={v['vs']} | {v['title']}"
        for v in pool.values())

    cl, u = ask(SYS_CLUSTER, f"НИША: {niche}\nРОЛИКИ:\n{listing}")
    tin += u.input_tokens; tout += u.output_tokens
    print(f"  субниш: {len(cl.get('clusters', []))}")

    t30 = "\n".join(f"{v['id']} | views={v['views']} | {v['title']}" for v in d["top_views"])
    tp, u = ask(SYS_TEMPLATE, f"ЗАГОЛОВКИ ТОП-30 ниши {niche}:\n{t30}")
    tin += u.input_tokens; tout += u.output_tokens
    print(f"  шаблонов: {len(tp.get('templates', []))}")

    thumbs = {}
    top15 = d["top_views"][:15]
    for i in range(0, len(top15), 5):
        chunk = top15[i:i+5]
        content = [{"type": "text", "text": "Опиши обложки."}]
        for v in chunk:
            content.append({"type": "text", "text": f"video_id: {v['id']} — {v['title'][:110]}"})
            content.append({"type": "image", "source": {
                "type": "url", "url": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg"}})
        try:
            th, u = ask(SYS_THUMB, content, max_tokens=2000)
            tin += u.input_tokens; tout += u.output_tokens
            thumbs.update(th)
        except Exception as e:
            print(f"  ! обложки батч {i}: {str(e)[:80]}")
    print(f"  обложек описано: {len(thumbs)}")
    out[niche] = {"clusters": cl, "templates": tp, "thumbs": thumbs}

(SC / f"{PRE}_llm.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\nтокены: вход {tin:,}, выход {tout:,} (~${tin/1e6*1 + tout/1e6*5:.3f})")
