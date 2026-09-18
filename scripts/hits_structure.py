#!/usr/bin/env python3
"""Приёмы взлетевших роликов ниши: по json3-транскриптам — хук (первые 45 с), первый поворот,
цифры/мин, главы; затем Opus сводит общую формулу (сюжетные ходы, структура, язык)."""
import json, re, sys, statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'scripts'))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
import anthropic
from pipeline.util import claude_cost, parse_json_block
import autopsy_audio as aa
R=Path('/mnt/d/youtube/cache/refs3'); client=anthropic.Anthropic(); cost=0.0
per=[]
def loose_json(text):
    try: return parse_json_block(text)
    except Exception:
        i,j=text.find('{'),text.rfind('}')
        return json.loads(text[i:j+1])
for vid in (R/'hits.txt').read_text().split():
    cp=R/vid/'structure.json'
    if cp.exists():
        per.append(json.loads(cp.read_text(encoding='utf-8'))); continue
    info=json.loads((R/vid/'video.info.json').read_text(encoding='utf-8'))
    words=aa.parse_json3(R/vid/'video.en.json3')
    dur=float(info.get('duration') or 0)
    text=" ".join(w['w'] for w in words)
    first45=" ".join(w['w'] for w in words if w['t']<=45); first180=" ".join(w['w'] for w in words if w['t']<=180)
    nums=re.findall(r"\b\d[\d,\.]*\b|\b(?:million|billion|thousand|percent)\b",text,re.I)
    prompt=(f"Ролик «{info['title']}» ({info.get('view_count',0):,} просмотров, {dur/60:.0f} мин). Транскрипт первых 3 минут:\n{first180}\n\n"
            "Последние 90 секунд:\n"+" ".join(w['w'] for w in words if w['t']>=dur-90)+"\n\n"
            "Разбери приёмы. Верни ТОЛЬКО JSON: {\"hook_type\":\"как именно цепляют в первые 30 с\",\"hook_quote\":\"первые 2 фразы дословно\","
            "\"promise\":\"что обещают зрителю\",\"first_turn_sec\":число,\"first_turn\":\"в чём первый поворот\",\"protagonist\":\"кто герой и почему за него болеешь\","
            "\"antagonist\":\"кто/что противник\",\"structure\":[\"акты/блоки кратко\"],\"devices\":[\"5–7 конкретных приёмов: ретардация, «а вот что они не знали», цифры, ирония...\"],"
            "\"ending\":\"как заканчивают\",\"tone\":\"тон и язык\"}")
    r=client.messages.create(model="claude-opus-5",max_tokens=4000,messages=[{"role":"user","content":prompt}])
    cost+=claude_cost("claude-opus-5",r.usage)
    a=loose_json("".join(b.text for b in r.content if b.type=="text"))
    a.update({"id":vid,"title":info['title'],"views":info.get('view_count'),"dur_min":round(dur/60,1),"wpm":round(len(words)/(dur/60)) if dur else None,
              "numbers_per_min":round(len(nums)/(dur/60),1) if dur else None,"chapters":[c.get('title') for c in (info.get('chapters') or [])][:12],"first45":first45[:600]})
    cp.write_text(json.dumps(a,ensure_ascii=False,indent=1),encoding='utf-8')
    per.append(a); print(f"  {info['title'][:60]:<60} {a['wpm']} сл/мин, цифр/мин {a['numbers_per_min']}, глав {len(a['chapters'])}, поворот {a.get('first_turn_sec')}с")
digest=json.dumps([{k:v for k,v in a.items() if k!='first45'} for a in per],ensure_ascii=False)
prompt=("Восемь самых успешных роликов ниши «афёры и ограбления с безликими 3D-манекенами» (Lume, Blackfiles, Outplayed) разобраны по приёмам:\n"+digest+
        "\n\nВыведи ОБЩУЮ ФОРМУЛУ ниши для нашего сценариста. Верни ТОЛЬКО JSON: {\"title_formula\":[\"маски заголовков с плейсхолдерами\"],"
        "\"hook_formula\":\"первые 30 с: что обязательно\",\"story_arc\":[\"обязательные акты с таймингом в % длины\"],\"devices\":[\"приёмы, встречающиеся ≥3 раза, с примерами\"],"
        "\"hero_rules\":[\"каким должен быть герой\"],\"money_rule\":\"как подаются суммы\",\"ending_rule\":\"как заканчивать\",\"tone\":\"язык\","
        "\"what_wins\":\"чем Pepsi/Coca-Cola/McDonald's-сюжеты отличаются от остальных (они в 2–11 раз выше медианы)\",\"avoid\":[\"чего не делать\"]}")
r=client.messages.create(model="claude-opus-5",max_tokens=9000,messages=[{"role":"user","content":prompt}]); cost+=claude_cost("claude-opus-5",r.usage)
ftxt="".join(b.text for b in r.content if b.type=="text"); (R/'formula_raw.txt').write_text(ftxt,encoding='utf-8')
F=loose_json(ftxt)
json.dump({"per_video":per,"formula":F},open(R/'hits_structure.json','w'),ensure_ascii=False,indent=1)
print(json.dumps(F,ensure_ascii=False,indent=1)); print(f"cost ${cost:.2f}")
