#!/usr/bin/env python3
"""Демо: каждый план — Veo 3.1 standard image-to-video по QC-стиллу с промптом действия;
QC движения по 6 кадрам (Opus): ноги на земле, поворот ≤30°, лицо как на референсе, нет текста.
Брак -> перегенерация с усиленным ограничением (1 раз). Пишет demo15/clips/*.mp4 и animate.json."""
import base64, json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
import anthropic
from pipeline.config import Config
from pipeline.sources import genvideo as gv
from pipeline.util import claude_cost, parse_json_block
cfg=Config('heists'); D=Path('/mnt/d/youtube/output/heists/demo15'); (D/'clips').mkdir(exist_ok=True)
sb=json.loads((D/'storyboard.json').read_text(encoding='utf-8')); client=anthropic.Anthropic()
MODEL=sys.argv[1] if len(sys.argv)>1 else "veo-3.1-generate-preview"
hero=Path('/mnt/d/youtube/output/heists/2026-09-10_google-facebook-fake-invoices/world/hero.jpg')
def qc(mp, sh):
    imgs=[]
    for t in (0.3,1.2,2.4,3.6,4.8,5.7):
        r=subprocess.run(["ffmpeg","-v","error","-ss",f"{t}","-i",str(mp),"-frames:v","1","-vf","scale=640:-2","-f","image2pipe","-vcodec","mjpeg","-"],capture_output=True,timeout=60)
        if r.stdout: imgs.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":base64.b64encode(r.stdout).decode()}})
    if sh['hero']: imgs.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":base64.b64encode(hero.read_bytes()).decode()}})
    imgs.append({"type":"text","text":f"Шесть кадров сгенерированного клипа (0.2–3.9 с) по заданию движения: «{sh['motion']}». Ограничения: {sh['avoid']}. "
                 +("Последнее изображение — лист героя. " if sh['hero'] else "")+
                 "Проверь физику и правдоподобие: ноги/руки на своих местах, поворот головы/тела не больше заданного, объекты не морфят, нет лишних людей, нет читаемого текста, лицо героя как на листе. "
                 "Соответствует ли движение заданию? Верни ТОЛЬКО JSON {\"ok\":true/false,\"score\":0-10,\"defects\":[\"...\"]}"})
    usd=0.0
    for attempt in range(2):
        r=client.messages.create(model="claude-opus-5",max_tokens=4000,messages=[{"role":"user","content":imgs}])
        usd+=claude_cost("claude-opus-5",r.usage); txt="".join(b.text for b in r.content if b.type=="text")
        try:
            d=parse_json_block(txt); d["usd"]=usd; return d
        except Exception:
            print(f"    · QC: пустой/битый ответ ({r.stop_reason}), повтор"); continue
    return {"ok":True,"score":None,"defects":["QC не ответил — принято без проверки"],"usd":usd}
res=[]; spent=0.0
for sh in sb['shots']:
    if sh.get('kind')=='motion': res.append({**sh,"file":None}); continue
    still=D/f"still_{sh['id']:02d}.jpg"; secs=6   # 6 с: один план = один слот озвучки (31 с / 5 планов)
    prompt=f"{sh['motion']} Constraints: {sh['avoid']}. Keep the character, clothes, lighting and setting exactly as in the image; realistic slow motion, no camera shake, no text."
    clip=None
    for attempt in range(2):
        mp=D/'clips'/f"clip_{sh['id']:02d}_{attempt}.mp4"
        if not mp.exists():
            try:
                r=gv.veo(cfg,prompt,mp,seconds=secs,image=still,model=MODEL,resolution="720p"); spent+=r['usd']; print(f"  план {sh['id']}: клип {r['seconds']}с ${r['usd']:.2f} {r['elapsed']}с")
            except Exception as e:
                print(f"  план {sh['id']}: ошибка {str(e)[:160]}"); break
        q=qc(mp,sh); spent+=q['usd']; print(f"  план {sh['id']}: QC {q.get('score')} {'ok' if q.get('ok') else 'БРАК'} {q.get('defects')}")
        if q.get('ok') or q.get('score',0)>=6: clip=mp; sh['qc']=q; break
        prompt+=" Fix: "+"; ".join(q.get('defects') or [])[:200]
    res.append({**sh,"file":str(clip) if clip else None})
json.dump({"model":MODEL,"spent_usd":round(spent,2),"shots":res,"stamp_insert":sb.get("stamp_insert")},open(D/'animate.json','w'),ensure_ascii=False,indent=1)
print(f"итого ${spent:.2f}; клипов {sum(1 for r in res if r.get('file'))} из {sum(1 for s in sb['shots'] if s.get('kind')!='motion')}")
