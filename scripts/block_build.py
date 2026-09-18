#!/usr/bin/env python3
"""Генерация блока по storyboard.json: kinds video / video_fl / still / card.
Стиллы gemini-3-pro-image (AI Studio) + QC; видео Veo 3.1 standard (Vertex) + QC (порог 5, 2 дубля);
card — PIL-инфографика в стиле Lume. Пишет result.json (segments, durs) — сборка в preview_full.py."""
import base64, json, random, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
import anthropic
from PIL import Image, ImageDraw, ImageFont
from pipeline.config import Config
from pipeline.sources import genimage, genvideo as gv
from pipeline.util import claude_cost, parse_json_block, ffprobe_duration
cfg=Config('heists'); D=Path(sys.argv[1]); (D/'clips').mkdir(exist_ok=True)
sb=json.loads((D/'storyboard.json').read_text(encoding='utf-8')); hero=Path(sb['hero']); STYLE=sb['style']
IMG='gemini-3-pro-image'; VEO='veo-3.1-generate-preview'; client=anthropic.Anthropic(); spent={'img':0.0,'veo':0.0,'qc':0.0}
W,H,FPS=1920,1080,30; GREEN=(46,229,157); MONO='/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'; MONOB='/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
def b64(p): return {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":base64.b64encode(Path(p).read_bytes()).decode()}}
def ask(content, max_tokens=3000):
    for _ in range(2):
        r=client.messages.create(model="claude-opus-5",max_tokens=max_tokens,messages=[{"role":"user","content":content}]); spent['qc']+=claude_cost("claude-opus-5",r.usage)
        try: return parse_json_block("".join(b.text for b in r.content if b.type=="text"))
        except Exception: continue
    return {}
def gen_img(prompt, out, refs):
    if out.exists(): return out
    r=genimage.generate(cfg, prompt, out, refs=refs, model=IMG); spent['img']+=r['usd']; return out
def card(lines, secs, out):
    """инфографика: тёмная сетка, зелёный моно, строки появляются по одной"""
    d_out=out.with_suffix(''); d_out.mkdir(exist_ok=True); n=int(secs*FPS); rnd=random.Random(3)
    px=int(H*0.06) if max(len(l) for l in lines)<=26 else int(H*0.045); f=ImageFont.truetype(MONOB,px)
    for i in range(n):
        t=i/FPS; im=Image.new('RGB',(W,H),(6,7,9)); d=ImageDraw.Draw(im)
        for x in range(0,W,64): d.line([(x,0),(x,H)],fill=(12,14,17))
        for y in range(0,H,64): d.line([(0,y),(W,y)],fill=(12,14,17))
        fade_out=max(min((secs-t)/0.5,1.0),0.0); y=H/2-len(lines)*px*1.6/2
        for j,l in enumerate(lines):
            a=min(max((t-0.25-j*0.55)/0.35,0.0),1.0)*fade_out; col=tuple(int(c*a) for c in (GREEN if j%2==0 else (225,228,232)))
            w=d.textlength(l,font=f); d.text(((W-w)/2,y),l,font=f,fill=col); y+=px*1.6
        for _ in range(300):
            x,y2=rnd.randrange(W),rnd.randrange(H); im.putpixel((x,y2),tuple(min(255,c+16) for c in im.getpixel((x,y2))))
        im.save(d_out/f"f{i:04d}.png")
    subprocess.run(["ffmpeg","-y","-v","error","-framerate",str(FPS),"-i",str(d_out/'f%04d.png'),"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)],check=True); return out
def caption_still(src: Path, text: str) -> Path:
    """Подпись-плашка нашей графикой: моноширинный шрифт, зелёная линия — как на карточках."""
    import re as _re
    from PIL import Image, ImageDraw, ImageFont
    im=Image.open(src).convert('RGB'); W,H=im.size
    lines=[l.strip() for l in _re.split(r'\s*/\s*', text) if l.strip()][:2]
    px=int(H*0.055); f=ImageFont.truetype(MONOB,px)
    band=int(px*(1.9+0.9*(len(lines)-1))); y0=H-band-int(H*0.06)
    ov=Image.new('RGBA',(W,band),(8,9,11,205)); d=ImageDraw.Draw(ov); d.line([(0,0),(W,0)],fill=GREEN+(255,),width=3)
    y=(band-len(lines)*px*1.25)/2
    for i,l in enumerate(lines):
        d.text((int(W*0.07),y), l, font=f, fill=(GREEN if i==0 else (232,235,238))+(255,)); y+=px*1.25
    im.paste(Image.alpha_composite(im.convert('RGBA').crop((0,y0,W,y0+band)), ov).convert('RGB'), (0,y0))
    out=src.with_name(src.stem+'_cap.jpg'); im.save(out, quality=93); return out


def still_qc(path, sh):
    c=[b64(path)]+([b64(hero)] if sh.get('hero') else [])
    c.append({"type":"text","text":f"Кадр 1 по описанию: «{sh['still']}». "+("Кадр 2 — лист героя: тот же человек? " if sh.get('hero') else "")+
              "Текста и цифр в кадре быть НЕ должно (бумаги/экраны пустые или размытые). Если что-то читается — выпиши это в read_text. "+
              'Проверь соответствие, анатомию, лишних людей. Верни ТОЛЬКО JSON {"ok":true/false,"score":0-10,"read_text":"...","defects":["..."]}'})
    return ask(c,1500)
def clip_qc(mp, sh):
    c=[]
    for t in (0.3,1.2,2.4,3.6,4.8,5.6):
        r=subprocess.run(["ffmpeg","-v","error","-ss",f"{t}","-i",str(mp),"-frames:v","1","-vf","scale=640:-2","-f","image2pipe","-vcodec","mjpeg","-"],capture_output=True,timeout=60)
        if r.stdout: c.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":base64.b64encode(r.stdout).decode()}})
    c.append({"type":"text","text":f"Шесть кадров клипа. Задание: «{sh.get('motion','')}». Сцена: «{sh['still'][:220]}». "+'Проверь: одно действие как задано, анатомия, объекты не морфят/телепортируются, нет лишних людей и текста. Верни ТОЛЬКО JSON {"ok":true/false,"score":0-10,"defects":["..."]}'})
    return ask(c,3000)
locs={k:gen_img(p+' '+STYLE, D/f'loc_{k}.jpg', []) for k,p in sb['locations'].items()}; print('локации ok')
segs=[]
for n_i, sh in enumerate(sb['shots'], 1):
    sh['id']=int(re.sub(r'\D','',str(sh.get('id',''))) or n_i)      # 's01' -> 1
    secs=float(sh.get('seconds',6)); print(f"план {sh['id']} {sh['kind']}", flush=True)
    if sh['kind']=='card':
        out=D/'clips'/f"card{sh['id']:02d}.mp4"
        if not out.exists(): card(sh.get('lines') or ['—'], secs, out)
        segs.append({'id':sh['id'],'file':str(out),'dur':secs,'kind':'card','text':sh.get('text','')}); continue
    refs=([hero] if sh.get('hero') else [])+([locs[sh['loc']]] if sh.get('loc') in locs else [])
    note=(f" The main character is the SAME person as in reference image 1 ({sb['hero_desc']}) — identical face, hair and clothes." if sh.get('hero') else "")+(f" The setting matches reference image {len(refs)} (same room, furniture and light)." if sh.get('loc') in locs else "")
    # никаких надписей от ИИ: цифры/слова накладываем сами (иначе модель выдумывает свои)
    NOTEXT=(" No readable text anywhere in the frame: no numbers, no letters, no labels, no signage, no screen text — "
            "any paper, screen or sign must be blank, blurred or turned away from camera.")
    if sh.get('text_check'):
        sh['still']=sh['still']+NOTEXT
        sh['caption']=sh['text_check']
    still=None
    for attempt in range(3):
        p=D/f"s{sh['id']:02d}_{attempt}.jpg"
        if not p.exists(): gen_img(f"{sh['still']}{note} {STYLE}", p, refs)
        q=still_qc(p, sh); ok=q.get('ok') or (q.get('score') or 0)>=6
        if sh.get('caption') and str(q.get('read_text','')).strip() not in ('', 'нет', 'none', 'NO TEXT'):
            ok=False                                  # модель всё-таки написала текст — перегенерировать
        print(f"   стилл {attempt} QC {q.get('score')} {str(q.get('defects'))[:100]}")
        if ok: still=p; break
        still=still or p
    if sh['kind']=='still':
        if sh.get('caption') and still:
            still=caption_still(Path(still), sh['caption'])        # наша подпись поверх чистого кадра
        segs.append({'id':sh['id'],'file':str(still),'dur':secs,'kind':'still','text':sh.get('text','')}); continue
    last=None
    if sh['kind']=='video_fl' and sh.get('last'):
        last=D/f"s{sh['id']:02d}_last.jpg"
        if not last.exists(): gen_img(f"{sh['last']} This is the END state of the same shot as reference image 1: identical camera, framing, light, character and set. {STYLE}", last, [still]+([hero] if sh.get('hero') else []))
    vsec=int(secs) if int(secs) in (4,6,8) else (6 if secs<7 else 8)
    best=None; best_score=-1
    for attempt in range(2):
        mp=D/'clips'/f"c{sh['id']:02d}_{attempt}.mp4"
        if not mp.exists():
            try:
                r=gv.veo(cfg, sh.get('motion','slow push-in')+" "+STYLE, mp, seconds=vsec, image=still, last_frame=(last if attempt==0 else None), model=VEO, resolution="720p", timeout=900); spent['veo']+=r['usd']
            except Exception as e:
                print(f"   дубль {attempt} ошибка Veo: {str(e)[:100]}"); continue
        q=clip_qc(mp, sh); sc=q.get('score') or 0; print(f"   дубль {attempt} QC {sc} {str(q.get('defects'))[:120]}")
        if sc>best_score: best,best_score=mp,sc
        if q.get('ok') or sc>=5: break
    if best is None: segs.append({'id':sh['id'],'file':str(still),'dur':secs,'kind':'still','text':sh.get('text','')}); continue
    segs.append({'id':sh['id'],'file':str(best),'dur':secs,'kind':'clip','qc':best_score,'text':sh.get('text',''),'title':sh.get('title')})
json.dump({"segments":segs,"durs":[s['dur'] for s in segs],"spent":spent},open(D/'result.json','w'),ensure_ascii=False,indent=1)
print('расходы', {k:round(v,2) for k,v in spent.items()}, '| планов', len(segs))
