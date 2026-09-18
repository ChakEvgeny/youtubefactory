#!/usr/bin/env python3
"""Демо v5 с нуля: одно действие на план, документы — стиллы с наездом, печать рисует image-модель,
QC знает план. Стиллы: gemini-3-pro-image (AI Studio); видео: Veo 3.1 standard (Vertex)."""
import base64, json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
import anthropic
from pipeline.config import Config
from pipeline.sources import genimage, genvideo as gv
from pipeline.stages.assemble import fx_filter, sfx_file
from pipeline.util import claude_cost, parse_json_block, ffprobe_duration
cfg=Config('heists'); D=Path(sys.argv[1] if len(sys.argv)>1 else '/mnt/d/youtube/output/heists/demo17'); (D/'clips').mkdir(exist_ok=True)
sb=json.loads((D/'storyboard.json').read_text(encoding='utf-8')); hero=Path(sb['hero']); STYLE=sb['style']
IMG='gemini-3-pro-image'; VEO='veo-3.1-generate-preview'; client=anthropic.Anthropic(); spent={'img':0.0,'veo':0.0,'qc':0.0}
def run(cmd):
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=1800)
    if r.returncode: raise SystemExit("ffmpeg: "+r.stderr[-600:])
def b64(p): return {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":base64.b64encode(Path(p).read_bytes()).decode()}}
def ask(content, max_tokens=2000):
    r=client.messages.create(model="claude-opus-5",max_tokens=max_tokens,messages=[{"role":"user","content":content}]); spent['qc']+=claude_cost("claude-opus-5",r.usage)
    try: return parse_json_block("".join(b.text for b in r.content if b.type=="text"))
    except Exception: return {}
def gen_img(prompt, out, refs):
    r=genimage.generate(cfg, prompt, out, refs=refs, model=IMG); spent['img']+=r['usd']; return out
locs={k:(D/f'loc_{k}.jpg' if (D/f'loc_{k}.jpg').exists() else gen_img(p+' '+STYLE, D/f'loc_{k}.jpg', [])) for k,p in sb['locations'].items()}
print('локации ok')
def still_qc(path, sh):
    c=[b64(path)]+([b64(hero)] if sh.get('hero') else [])
    c.append({"type":"text","text":f"Кадр 1 сгенерирован по описанию: «{sh['still']}». "+("Кадр 2 — лист героя: тот же человек? " if sh.get('hero') else "")+
              (f"На бумаге должно быть читаемое слово «{sh['text_check']}» — прочитай его. " if sh.get('text_check') else "Никакого читаемого текста и логотипов быть не должно. ")+
              "Проверь соответствие описанию, анатомию (руки, лица), отсутствие лишних людей. Верни ТОЛЬКО JSON {\"ok\":true/false,\"score\":0-10,\"read_text\":\"...\",\"defects\":[\"...\"]}"})
    return ask(c, 1500)
def clip_qc(mp, sh):
    c=[]
    for t in (0.3,1.2,2.4,3.6,4.8,5.6):
        r=subprocess.run(["ffmpeg","-v","error","-ss",f"{t}","-i",str(mp),"-frames:v","1","-vf","scale=640:-2","-f","image2pipe","-vcodec","mjpeg","-"],capture_output=True,timeout=60)
        if r.stdout: c.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":base64.b64encode(r.stdout).decode()}})
    c.append({"type":"text","text":f"Шесть кадров клипа. Задание движения: «{sh['motion']}». Сцена: «{sh['still'][:220]}». "
              "Проверь: одно действие как задано, руки/ноги/пальцы правдоподобны, объекты не морфят и не телепортируются, камера ведёт себя как задано, нет лишних людей и текста. "
              "Верни ТОЛЬКО JSON {\"ok\":true/false,\"score\":0-10,\"defects\":[\"...\"]}"})
    return ask(c, 3000)
segs=[]
for sh in sb['shots']:
    refs=([hero] if sh.get('hero') else [])+[locs[sh['loc']]]
    note=(f" The main character is the SAME person as in reference image 1 ({sb['hero_desc']}) — identical face, hair and clothes." if sh.get('hero') else "")+f" The setting matches reference image {len(refs)} (same room, furniture and light)."
    still=None
    for attempt in range(3):
        p=D/f"s{sh['id']:02d}_{attempt}.jpg"
        if not p.exists(): gen_img(f"{sh['still']}{note} {STYLE}", p, refs)
        q=still_qc(p, sh); print(f"план {sh['id']}: стилл {attempt} QC {q.get('score')} text={q.get('read_text','')!s:.20} {str(q.get('defects'))[:120]}")
        ok=q.get('ok') or (q.get('score') or 0)>=6
        if sh.get('text_check') and sh['text_check'].lower() not in str(q.get('read_text','')).lower(): ok=False
        if ok: still=p; break
        still=still or p
    if sh['kind']=='still':
        segs.append({'id':sh['id'],'file':str(still),'dur':sh['seconds'],'kind':'still'}); continue
    last=None
    if sh['kind']=='video_fl':
        last=D/f"s{sh['id']:02d}_last.jpg"
        if not last.exists(): gen_img(f"{sh['last']} This is the END state of the same shot as reference image 1: identical camera position, framing, lighting, character and set. {STYLE}", last, [still,hero])
    best=None; best_score=-1
    for attempt in range(2):
        mp=D/'clips'/f"c{sh['id']:02d}_{attempt}.mp4"
        if not mp.exists():
            try:
                r=gv.veo(cfg, sh['motion']+" "+STYLE, mp, seconds=sh['seconds'], image=still, last_frame=(last if attempt==0 else None), model=VEO, resolution="720p", timeout=900); spent['veo']+=r['usd']
            except Exception as e:
                print(f"план {sh['id']}: дубль {attempt} ошибка Veo: {str(e)[:120]}"); continue
        q=clip_qc(mp, sh); sc=q.get('score') or 0; print(f"план {sh['id']}: дубль {attempt} QC {sc} {str(q.get('defects'))[:160]}")
        if sc>best_score: best, best_score=mp, sc
        if q.get('ok') or sc>=5: break
    if best is None:                                   # оба дубля упали — план стиллом с наездом
        segs.append({'id':sh['id'],'file':str(still),'dur':sh['seconds'],'kind':'still'}); continue
    segs.append({'id':sh['id'],'file':str(best),'dur':sh['seconds'],'kind':'clip','qc':best_score,'title':sh.get('title')})
print('расходы', {k:round(v,2) for k,v in spent.items()})
# ── сборка ──
voice=Path(sb['voice']); total=ffprobe_duration(voice)+0.6; W,H,FPS=1920,1080,30; tmp=D/'_clips'; tmp.mkdir(exist_ok=True)
durs=[s['dur'] for s in segs]
if sum(durs)>total: durs=[d*total/sum(durs) for d in durs]
else: durs[-1]=max(durs[-1], total-sum(durs[:-1]))
seq=[]; starts=[]; t=0.0
for i,(s,dur) in enumerate(zip(segs,durs)):
    starts.append(t); t+=dur; out=tmp/f"seg{i:02d}.mp4"; fx="punch" if i>0 else "kenburns_slow"
    if s['kind']=='still':
        vf=fx_filter("pushin",dur,W,H)+f",fps={FPS}"
        run(["ffmpeg","-y","-v","error","-loop","1","-framerate",str(FPS),"-t",f"{dur:.2f}","-i",s['file'],"-vf",vf,"-t",f"{dur:.2f}","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    else:
        vf=fx_filter(fx,dur,W,H)+f",fps={FPS}"; sd=ffprobe_duration(Path(s['file'])) or dur
        if sd<dur: vf+=f",tpad=stop_mode=clone:stop_duration={dur-sd+0.5:.2f}"
        if i==len(segs)-1: vf+=f",fade=t=out:st={max(dur-0.8,0):.2f}:d=0.8"
        if s.get('title'): vf+=f",drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf:text='{s['title']}':fontcolor=0x2EE59D:fontsize=54:x=80:y=80:alpha='if(lt(t,0.4),t/0.4,if(lt(t,{dur-0.6:.2f}),1,({dur:.2f}-t)/0.6))'"
        run(["ffmpeg","-y","-v","error","-i",s['file'],"-t",f"{dur:.2f}","-an","-vf",vf,"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    seq.append(out)
(D/'_concat.txt').write_text("\n".join(f"file '{c}'" for c in seq),encoding='utf-8'); silent=D/'_silent.mp4'
run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(D/'_concat.txt'),"-c","copy",str(silent)])
music=Path(cfg.paths.music_dir)/'heist_tense.mp3'
ins=["-i",str(silent),"-i",str(voice),"-stream_loop","-1","-i",str(music)]
parts=["[1:a]aformat=fltp:48000:stereo,asplit=2[vm][vm2]", f"[2:a]aformat=fltp:48000:stereo,atrim=0:{total:.2f},volume=0.22[m0]","[m0][vm2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]"]
labels=["[duck]"]; k=0
for i,(s,dur) in enumerate(zip(segs,durs)):
    if s['kind']!='clip': continue
    ins+=["-i",s['file']]; idx=ins.count("-i")-1; st=int(starts[i]*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,atrim=0:{dur:.2f},volume=0.12,afade=t=in:d=0.3,afade=t=out:st={max(dur-0.5,0):.2f}:d=0.5,adelay={st}|{st}[amb{k}]"); labels.append(f"[amb{k}]"); k+=1
sx=cfg.defaults.get('sfx',{}); hit=sfx_file(cfg,'hit',sx.get('hit','')); riser=sfx_file(cfg,'riser',sx.get('riser',''),seconds=6.0)
for i in range(1,len(segs)):
    if not hit: continue
    ins+=["-i",str(hit)]; idx=ins.count("-i")-1; ms=int(max(starts[i]-0.05,0)*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,volume=0.35,adelay={ms}|{ms}[s{k}]"); labels.append(f"[s{k}]"); k+=1
if riser:
    ins+=["-i",str(riser)]; idx=ins.count("-i")-1; ms=int(max(starts[1]-6,0)*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,volume=0.3,adelay={ms}|{ms}[s{k}]"); labels.append(f"[s{k}]"); k+=1
parts.append("".join(labels)+f"amix=inputs={len(labels)}:duration=first:dropout_transition=0,volume={len(labels)}[bed]")
parts.append("[bed][vm]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
g=cfg.channel.get('grade',{}); vf=f"eq=contrast={g.get('contrast',1.05)}:saturation={g.get('saturation',0.9)}:brightness={g.get('brightness',-0.01)},noise=alls={int(g.get('grain',5))}:allf=t+u,vignette=PI/4.6"
run(["ffmpeg","-y","-v","error",*ins,"-filter_complex",";".join(parts),"-map","0:v","-map","[a]","-vf",vf,"-t",f"{total:.2f}","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(D/'demo.mp4')])
run(["ffmpeg","-y","-v","error","-i",str(D/'demo.mp4'),"-vf","scale=1280:720","-c:v","libx264","-preset","slow","-crf","24","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart",str(D/'demo_small.mp4')])
json.dump({"segments":segs,"durs":durs,"spent":spent},open(D/'result.json','w'),ensure_ascii=False,indent=1)
print("demo:", D/'demo.mp4', f"{total:.1f}s")
