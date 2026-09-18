#!/usr/bin/env python3
"""Кандидаты на первый ролик ниши «манекены»: Opus + web_search ищет реальные, задокументированные
истории «один обычный человек против большого бренда/системы» с точной суммой, приоритет Европа/UK."""
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
import anthropic
from pipeline.util import claude_cost, parse_json_block
client=anthropic.Anthropic()
prompt=("Мы запускаем YouTube-канал в жанре Lume/Blackfiles: 20-минутные истории афер и схем, где обычный человек обыгрывает "
        "большую компанию, банк или систему (примеры хитов: «Pepsi Spent $2 Million to Stop One Kid», «Coca-Cola Lost $40 Million to One "
        "Housewife With a Photocopier», «The McDonald's Monopoly Scam», «The Truck Driver Who Made $6 Million Vanish From the World's Safest Airport»). "
        "Найди 10 РЕАЛЬНЫХ, документально подтверждённых историй (суд, пресса, отчёты) с приоритетом Европы и Великобритании, "
        "которые ещё не заезжены на YouTube (проверь: нет роликов с миллионными просмотрами по этой истории у крупных каналов). "
        "Критерии: один человек или маленькая группа; известный бренд/банк/госсистема как противник; точная сумма; хотя бы один "
        "неожиданный поворот; без убийств и насилия; финал известен (суд/побег/сделка). Для каждой: title_en (в стиле хитов выше), "
        "brand, country, year, sum, plot (5–7 предложений с поворотами), twist, ending, sources (3+ URL с датами), youtube_saturation "
        "(что уже есть на YouTube по этой истории и сколько просмотров), ad_safety_risk, score 1–10. Верни ТОЛЬКО JSON {\"candidates\":[...]}")
msgs=[{"role":"user","content":prompt}]; usage_in=usage_out=0; text=""
for _ in range(12):                       # серверный web_search может вернуть pause_turn — продолжаем ход
    r=client.messages.create(model="claude-opus-5",max_tokens=16000,tools=[{"type":"web_search_20260209","name":"web_search"}],messages=msgs)
    usage_in+=r.usage.input_tokens; usage_out+=r.usage.output_tokens
    text="".join(b.text for b in r.content if b.type=="text")
    print("stop:", r.stop_reason, "| text chars:", len(text))
    if r.stop_reason=="pause_turn":
        msgs=msgs+[{"role":"assistant","content":r.content}]; continue
    if r.stop_reason=="max_tokens" or "candidates" not in text:
        msgs=msgs+[{"role":"assistant","content":r.content},{"role":"user","content":"Продолжай и заверши: выдай итоговый JSON {\"candidates\":[...]} целиком."}]
        continue
    break
class U: input_tokens=usage_in; output_tokens=usage_out
r.usage=U()
try: d=parse_json_block(text)
except Exception:
    i,j=text.find('{"candidates"'),text.rfind('}')
    try: d=json.loads(text[i:j+1])
    except Exception: d={"raw":text}
Path('/mnt/d/youtube/cache/refs3/first_topic_candidates.json').write_text(json.dumps(d,ensure_ascii=False,indent=1),encoding='utf-8')
for c in d.get("candidates",[]): print(f"  [{c.get('score')}] {c.get('title_en')} — {c.get('brand')}, {c.get('country')} {c.get('year')}, {c.get('sum')} | YT: {str(c.get('youtube_saturation'))[:60]}")
print(f"cost ${claude_cost('claude-opus-5', r.usage):.2f}")
