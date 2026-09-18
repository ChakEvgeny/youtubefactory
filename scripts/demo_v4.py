#!/usr/bin/env python3
"""Демо v4: стиллы «первый/последний кадр» (gemini-3-pro-image, референсы героя и локации) ->
Veo 3.1 standard first&last frame -> QC (порог 5) -> сборка с удержанием конечного кадра штампа."""
import base64, json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
import anthropic
from PIL import Image, ImageDraw, ImageFont
from pipeline.config import Config
from pipeline.sources import genimage, genvideo as gv
from pipeline.stages.assemble import fx_filter, sfx_file
from pipeline.util import claude_cost, parse_json_block, ffprobe_duration
cfg=Config('heists'); D=Path('/mnt/d/youtube/output/heists/demo16'); (D/'clips').mkdir(exist_ok=True)
sb=json.loads((D/'storyboard.json').read_text(encoding='utf-8')); hero=Path(sb['hero']); STYLE=sb['style']
IMG='gemini-3-pro-image'; VEO='veo-3.1-generate-preview'; client=anthropic.Anthropic(); spent={'img':0.0,'veo':0.0,'qc':0.0}
def run(cmd):
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=1800)
    if r.returncode: raise SystemExit("ffmpeg: "+r.stderr[-600:])
def img(prompt, out, refs):
    if out.exists(): return out
    r=genimage.generate(cfg, prompt, out, refs=refs, model=IMG); spent['img']+=r['usd']; return out
locs={}
for k,p in sb['locations'].items(): locs[k]=img(p+' '+STYLE, D/f'loc_{k}.jpg', [])
print('локации ok')
def stamp_overlay(src, dst, text, sub):
    im=Image.open(src).convert('RGBA'); W,H=im.size
    st=Image.new('RGBA',(int(W*0.30),int(H*0.19)),(0,0,0,0)); d=ImageDraw.Draw(st)
    f1=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', int(H*0.065)); f2=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', int(H*0.03))
    red=(190,26,34,225); d.rounded_rectangle([4,4,st.width-4,st.height-4],radius=16,outline=red,width=7)
    d.text((st.width/2,st.height*0.42),text,font=f1,fill=red,anchor='mm'); d.text((st.width/2,st.height*0.78),sub,font=f2,fill=red,anchor='mm')
    st=st.rotate(-6,expand=True,resample=Image.BICUBIC); im.alpha_composite(st,(int(W*0.55),int(H*0.56))); im.convert('RGB').save(dst,quality=92); return dst
def qc(mp, sh):
    imgs=[]
    for t in (0.3,1.2,2.4,3.6,4.8,5.6):
        r=subprocess.run(["ffmpeg","-v","error","-ss",f"{t}","-i",str(mp),"-frames:v","1","-vf","scale=640:-2","-f","image2pipe","-vcodec","mjpeg","-"],capture_output=True,timeout=60)
        if r.stdout: imgs.append({"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":base64.b64encode(r.stdout).decode()}})
    imgs.append({"type":"text","text":f"Кадры клипа по заданию: «{sh['motion']}». Начальное состояние: «{sh['first'][:200]}». Конечное: «{sh['last'][:200]}». "
                 "Проверь правдоподобие: руки/ноги/пальцы, объекты не морфят и не телепортируются, действие соответствует заданию и доходит до конечного состояния, нет лишних людей и текста. "
                 "Верни ТОЛЬКО JSON {\"ok\":true/false,\"score\":0-10,\"defects\":[\"...\"]}"})
    for attempt in range(2):
        r=client.messages.create(model="claude-opus-5",max_tokens=4000,messages=[{"role":"user","content":imgs}]); spent['qc']+=claude_cost("claude-opus-5",r.usage)
        try: return parse_json_block("".join(b.text for b in r.content if b.type=="text"))
        except Exception: continue
    return {"ok":True,"score":None,"defects":["QC не ответил"]}
segments=[]   # (file, dur, kind)
for sh in sb['shots']:
    if sh.get('reuse'):
        segments.append((sh['reuse'], sh['seconds'], 'clip')); print(f"план {sh['id']}: reuse"); continue
    loc=locs[sh['loc']]; refs=([hero] if sh['hero'] else [])+[loc]
    note=(" The main character is the SAME person as in reference image 1 (identical face, hair, grey cardigan, checked shirt)." if sh['hero'] else "")+f" The setting matches reference image {len(refs)} exactly (same counter, glass partition and slot, same light)."
    first=img(f"{sh['first']}{note} {STYLE}", D/f"s{sh['id']:02d}_first.jpg", refs)
    last=img(f"{sh['last']} This is the END state of the same shot as reference image 1: identical camera position, framing, lighting, character and set; only the described change. {STYLE}", D/f"s{sh['id']:02d}_last_raw.jpg", [first]+([hero] if sh['hero'] else []))
    if sh.get('stamp_overlay'):
        last=stamp_overlay(last, D/f"s{sh['id']:02d}_last.jpg", sh['stamp_overlay']['text'], sh['stamp_overlay']['sub'])
    print(f"план {sh['id']}: стиллы ok")
    best=None
    for attempt in range(2):
        mp=D/'clips'/f"c{sh['id']:02d}_{attempt}.mp4"
        if not mp.exists():
            r=gv.veo(cfg, sh['motion']+" "+STYLE, mp, seconds=sh['seconds'], image=first, last_frame=last, model=VEO, resolution="720p", timeout=900); spent['veo']+=r['usd']
        q=qc(mp, sh); print(f"план {sh['id']}: дубль {attempt} QC {q.get('score')} {q.get('defects')}"[:220])
        if (q.get('score') or 5)>=5 or q.get('ok'): best=mp; break
        best=best or mp
    segments.append((str(best), sh['seconds'], 'clip'))
    if sh.get('stamp_overlay'): segments.append((str(last), sh['stamp_overlay']['hold'], 'still'))
print('расходы', {k:round(v,2) for k,v in spent.items()})
# ── сборка ────────────────────────────────────────────────────────────────
voice=Path(sb['voice']); total=ffprobe_duration(voice)+0.6; W,H,FPS=1920,1080,30; tmp=D/'_clips'; tmp.mkdir(exist_ok=True)
durs=[d for _,d,_ in segments]; durs[-1]=max(durs[-1], total-sum(durs[:-1]))   # хвост голоса — на последнем плане
seq=[]; starts=[]; t=0.0
for i,((f,_,kind),dur) in enumerate(zip(segments,durs)):
    starts.append(t); t+=dur; out=tmp/f"seg{i:02d}.mp4"
    fx="kenburns_slow" if kind=='still' else ("punch" if i>0 and segments[i-1][2]!='still' else "kenburns_slow")
    vf=fx_filter(fx,dur,W,H)+f",fps={FPS}"
    if kind=='still':
        run(["ffmpeg","-y","-v","error","-loop","1","-framerate",str(FPS),"-t",f"{dur:.2f}","-i",f,"-vf",vf,"-t",f"{dur:.2f}","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    else:
        sd=ffprobe_duration(Path(f)) or dur
        if sd<dur: vf+=f",tpad=stop_mode=clone:stop_duration={dur-sd+0.5:.2f}"
        if i==len(segments)-1: vf+=f",fade=t=out:st={max(dur-0.8,0):.2f}:d=0.8"
        run(["ffmpeg","-y","-v","error","-i",f,"-t",f"{dur:.2f}","-an","-vf",vf,"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    seq.append(out)
(D/'_concat.txt').write_text("\n".join(f"file '{c}'" for c in seq),encoding='utf-8'); silent=D/'_silent.mp4'
run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(D/'_concat.txt'),"-c","copy",str(silent)])
music=Path(cfg.paths.music_dir)/'heist_tense.mp3'
ins=["-i",str(silent),"-i",str(voice),"-stream_loop","-1","-i",str(music)]
parts=["[1:a]aformat=fltp:48000:stereo,asplit=2[vm][vm2]", f"[2:a]aformat=fltp:48000:stereo,atrim=0:{total:.2f},volume=0.22[m0]","[m0][vm2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]"]
labels=["[duck]"]; k=0
for i,((f,_,kind),dur) in enumerate(zip(segments,durs)):
    if kind!='clip': continue
    ins+=["-i",f]; idx=ins.count("-i")-1; st=int(starts[i]*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,atrim=0:{dur:.2f},volume=0.12,afade=t=in:d=0.3,afade=t=out:st={max(dur-0.5,0):.2f}:d=0.5,adelay={st}|{st}[amb{k}]"); labels.append(f"[amb{k}]"); k+=1
sx=cfg.defaults.get('sfx',{}); hit=sfx_file(cfg,'hit',sx.get('hit','')); riser=sfx_file(cfg,'riser',sx.get('riser',''),seconds=6.0)
for i in range(1,len(segments)):
    if segments[i][2]=='still' or not hit: continue
    ins+=["-i",str(hit)]; idx=ins.count("-i")-1; ms=int(max(starts[i]-0.05,0)*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,volume=0.35,adelay={ms}|{ms}[s{k}]"); labels.append(f"[s{k}]"); k+=1
if riser and len(starts)>1:
    ins+=["-i",str(riser)]; idx=ins.count("-i")-1; ms=int(max(starts[1]-6,0)*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,volume=0.3,adelay={ms}|{ms}[s{k}]"); labels.append(f"[s{k}]"); k+=1
parts.append("".join(labels)+f"amix=inputs={len(labels)}:duration=first:dropout_transition=0,volume={len(labels)}[bed]")
parts.append("[bed][vm]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
g=cfg.channel.get('grade',{}); vf=f"eq=contrast={g.get('contrast',1.05)}:saturation={g.get('saturation',0.9)}:brightness={g.get('brightness',-0.01)},noise=alls={int(g.get('grain',5))}:allf=t+u,vignette=PI/4.6"
run(["ffmpeg","-y","-v","error",*ins,"-filter_complex",";".join(parts),"-map","0:v","-map","[a]","-vf",vf,"-t",f"{total:.2f}","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(D/'demo.mp4')])
run(["ffmpeg","-y","-v","error","-i",str(D/'demo.mp4'),"-vf","scale=1280:720","-c:v","libx264","-preset","slow","-crf","24","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart",str(D/'demo_small.mp4')])
json.dump({"segments":segments,"durs":durs,"spent":spent},open(D/'result.json','w'),ensure_ascii=False,indent=1)
print("demo:", D/'demo.mp4', f"{total:.1f}s")
