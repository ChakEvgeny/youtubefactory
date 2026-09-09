#!/usr/bin/env python3
"""Сравнительная таблица четырёх ниш; дописывается в конец отчёта deepdive."""
import collections, json, os, re, statistics, sys
from datetime import datetime, timezone
from pathlib import Path
import anthropic
from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
SC = Path(sys.argv[1])
NICHES = ["space_science", "business_breakdowns", "geography_maps", "disasters_survival"]
load_dotenv(ROOT / ".env")
client = anthropic.Anthropic()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
now = datetime.now(timezone.utc)

D, H = {}, {}
for pre in ("dd", "dd2"):
    D.update(json.loads((SC / f"{pre}_data.json").read_text(encoding="utf-8")))
    H.update(json.loads((SC / f"{pre}_hooks.json").read_text(encoding="utf-8")).get("safety", {}))

SYS = ("Ты оцениваешь нишу YouTube для рекламодателей. Ищи gore, жестокость, смерть, "
       "шок-контент, дезинформацию. Отвечай ТОЛЬКО JSON: "
       "{\"verdict\":\"safe|risky|unsafe\",\"reason\":\"кратко по-русски\"} без markdown.")
def check(niche):
    titles = "\n".join(f"- {v['title']}" for v in D[niche]["top_views"][:20])
    content = [{"type": "text", "text": f"НИША: {niche}\nЗАГОЛОВКИ ТОП-20:\n{titles}\n\nНиже обложки."}]
    for v in D[niche]["top_views"][:4]:
        content.append({"type": "image", "source": {
            "type": "url", "url": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg"}})
    r = client.messages.create(model="claude-haiku-4-5", max_tokens=800, system=SYS,
                               messages=[{"role": "user", "content": content}])
    t = "".join(b.text for b in r.content if b.type == "text")
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.MULTILINE).strip()
    return json.loads(t[t.find("{"):t.rfind("}") + 1])

# вердикт по нише: худший из вердиктов её каналов-целей, иначе — прямая проверка
RANK = {"safe": 0, "risky": 1, "unsafe": 2}
verdicts = {}
for n in NICHES:
    ch_names = {t["channel"] for t in D[n]["targets"]}
    got = [v for k, v in H.items() if k in ch_names and v.get("verdict") in RANK]
    if got:
        worst = max(got, key=lambda v: RANK[v["verdict"]])
        verdicts[n] = (worst["verdict"], f"по каналам-целям: {worst['reason'][:70]}")
    else:
        r = check(n)
        verdicts[n] = (r.get("verdict", "?"), r.get("reason", "")[:70])
    print(f"{n:<22} {verdicts[n][0]}")

scores = {r["niche"]: r for r in sb.table("niche_scores").select("*").eq("lang", "en").execute().data}
rows = []
for n in NICHES:
    r = scores.get(n, {})
    d = r.get("details") or {}
    top = D[n]["top_views"]
    ai = sum(1 for v in top if v.get("format") == "ai_generated_visuals")
    fm = collections.Counter(v["format"] for v in top if v.get("format"))
    med = statistics.median([v["duration"] for v in top if v["duration"]])
    nv, nr = r.get("n_videos", 0), r.get("n_relevant") or 0
    rows.append({
        "niche": n, "score": r.get("score", 0), "prec": nr * 100 // max(nv, 1),
        "nrel": nr, "comp": r.get("competition", 0), "newc": r.get("newcomer_share", 0),
        "ay": d.get("anomalies_young", 0), "anom": r.get("anomalies", 0),
        "fmt": f"{fm.most_common(1)[0][0]} {fm.most_common(1)[0][1]*100//len(top)}%" if fm else "—",
        "med": f"{int(med)//60}:{int(med)%60:02d}", "safe": verdicts[n][0],
        "ai": f"{ai}/{len(top)}",
    })

L = ["", "---", "", "# Сравнение четырёх ниш (EN, после чистки языка)", "",
     "| ниша | score | точность | n_rel | comp | newc | аном. у молодых | доминирующий формат | медиана | ad-safety | AI-визуал в топ-30 |",
     "|------|------:|---------:|------:|-----:|-----:|----------------:|---------------------|--------:|-----------|-------------------:|"]
for r in sorted(rows, key=lambda x: -x["score"]):
    L.append(f"| **{r['niche']}** | {r['score']:,.0f} | {r['prec']}% | {r['nrel']} | {r['comp']} | "
             f"{r['newc']:.2f} | {r['ay']} из {r['anom']} | {r['fmt']} | {r['med']} | "
             f"`{r['safe']}` | {r['ai']} |")
L += ["", "Пояснения к колонкам:", "",
      "- **точность** — доля relevant=1 среди прошедших фильтры: насколько запросы попадают в нишу.",
      "- **аном. у молодых** — сколько роликов с view/sub ≥ 3 сделано каналами моложе 12 месяцев; "
      "прямой показатель того, пускает ли ниша новичков.",
      "- **ad-safety** — вердикт по обложкам и заголовкам каналов-целей (safe / risky / unsafe).",
      "- **AI-визуал в топ-30** — сколько роликов топа собрано на сгенерированной картинке: "
      "чем больше, тем ближе ниша к нашему конвейеру.", ""]
for n in NICHES:
    v = verdicts[n]
    L.append(f"- `{n}` — ad-safety **{v[0]}**: {v[1]}")
L.append("")

dest = ROOT / "reports" / f"deepdive_{now.date().isoformat()}.md"
with dest.open("a", encoding="utf-8") as f:
    f.write("\n".join(L) + "\n")
print(f"дописано в {dest.relative_to(ROOT)}")
