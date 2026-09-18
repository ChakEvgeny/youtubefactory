#!/usr/bin/env python3
"""Полное превью одним проходом: хук (demo18) → титры (стиль Lume) → суд (demo19).
Одна видеодорожка (concat планов + грейд), одна звуковая: два диктора по таймлайну, музыка без обрыва
с даком под голос, ambient/речь планов, SFX (hit на стыках, whoosh на титрах, райзер перед поворотами), loudnorm."""
import json, subprocess, sys, random
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
from PIL import Image, ImageDraw, ImageFont
from pipeline.config import Config
from pipeline.stages.assemble import fx_filter, sfx_file
from pipeline.util import ffprobe_duration
cfg=Config('heists'); W,H,FPS=1920,1080,30
OUT=Path('/mnt/d/youtube/output/heists/preview_full'); OUT.mkdir(exist_ok=True); tmp=OUT/'_work'; tmp.mkdir(exist_ok=True)
def run(cmd):
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=3600)
    if r.returncode: raise SystemExit("ffmpeg: "+r.stderr[-700:])
GREEN=(46,229,157); MONO='/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'; MONOB='/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
def card(lines, secs, mode, name, px):
    d_out=tmp/name; d_out.mkdir(exist_ok=True); n=int(secs*FPS); f=ImageFont.truetype(MONOB if mode=='type' else MONO, px)
    total_chars=sum(len(l) for l in lines); rnd=random.Random(7)
    for i in range(n):
        t=i/FPS; im=Image.new('RGB',(W,H),(6,7,9)); d=ImageDraw.Draw(im)
        for x in range(0,W,64): d.line([(x,0),(x,H)],fill=(12,14,17))          # сетка
        for y in range(0,H,64): d.line([(0,y),(W,y)],fill=(12,14,17))
        if mode=='fade': a=min(t/0.9,1.0,max((secs-t)/0.9,0.0)); shown=lines
        else:
            a=1.0 if t<secs-0.7 else max((secs-t)/0.7,0.0); k=int(min(t/max(secs-1.8,0.1),1.0)*total_chars); shown=[]
            for l in lines: shown.append(l[:max(k,0)]); k-=len(l)
            if int(t*3)%2==0 and t<secs-1.8: shown[-1]+='▌'
        col=tuple(int(c*a) for c in ((225,228,232) if mode=='fade' else GREEN))
        y=H/2-(len(lines)*px*1.5)/2
        for j,l in enumerate(shown):
            w=d.textlength(l,font=f); d.text(((W-w)/2,y),l,font=f,fill=col if not (mode=='fade' and j==0) else tuple(int(c*a) for c in GREEN)); y+=px*1.5
        if mode=='fade': d.line([(W/2-120,H/2+len(lines)*px*0.85),(W/2+120,H/2+len(lines)*px*0.85)],fill=tuple(int(c*a) for c in GREEN),width=2)
        for _ in range(400):                                                     # зерно
            x,y2=rnd.randrange(W),rnd.randrange(H); im.putpixel((x,y2),tuple(min(255,c+18) for c in im.getpixel((x,y2))))
        im.save(d_out/f"f{i:04d}.png")
    out=tmp/f"{name}.mp4"; run(["ffmpeg","-y","-v","error","-framerate",str(FPS),"-i",str(d_out/'f%04d.png'),"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)]); return out
# ── таймлайн ──
H18=Path('/mnt/d/youtube/output/heists/demo18'); H19=Path('/mnt/d/youtube/output/heists/demo19')
R18=json.loads((H18/'result.json').read_text(encoding='utf-8')); R19=json.loads((H19/'result.json').read_text(encoding='utf-8'))
v1=H18/'voice_James_nohow.mp3'; v2=H19/'voice_James.mp3'; d1=ffprobe_duration(v1); d2=ffprobe_duration(v2)
segs=[]
s18=R18['segments']; du=R18['durs']; head=sum(du[:-1]); sc=(d1+0.3)/head
for s,d in zip(s18[:-1],du[:-1]): segs.append({**s,'dur':d*sc,'src':'hook'})
segs.append({**s18[-1],'file':str(H18/'clips'/'c08_speak_0.mp4'),'dur':6.0,'src':'hook','speech':True,'kind':'clip'})
segs.append({'kind':'card','file':str(card(["A TRUE STORY","Every event in this film happened.","The reconstruction is AI-generated."],3.8,'fade','card1',52)),'dur':3.8,'src':'card'})
segs.append({'kind':'card','file':str(card(["MANHATTAN FEDERAL COURT","AUGUST 2017"],3.6,'type','card2',66)),'dur':3.6,'src':'card'})
s19=R19['segments']; du19=R19['durs']; sc2=(d2+0.6)/sum(du19)
for s,d in zip(s19,du19): segs.append({**s,'dur':d*sc2,'src':'court'})
# дальнейшие блоки: папки с result.json + voice_James.mp3 (в порядке сюжета)
EXTRA=[Path(x) for x in sys.argv[1:]]; extra_voices=[]
for bdir in EXTRA:
    Rb=json.loads((bdir/'result.json').read_text(encoding='utf-8')); vb=bdir/'voice_James.mp3'; db=ffprobe_duration(vb)
    scb=(db+0.6)/sum(Rb['durs']); t0=sum(x['dur'] for x in segs)
    starts_b={}
    for s,d in zip(Rb['segments'],Rb['durs']):
        starts_b[s['id']]=sum(x['dur'] for x in segs)
        segs.append({**s,'dur':d*scb,'src':bdir.name})
    extra_voices.append((vb,t0))
    # реплики других голосов (прокурор, судья) — на своих планах, клип при этом глушим
    import json as _j
    vl=bdir/'voice_lines.json'
    if vl.exists():
        sbb=_j.loads((bdir/'storyboard.json').read_text(encoding='utf-8'))
        import re as _re
        for line in _j.loads(vl.read_text(encoding='utf-8')):
            who='prosecutor' if 'prosecutor' in line.lower() else ('judge' if 'judge' in line.lower() else 'other')
            vf2=bdir/f'voice_{who}.mp3'
            if not vf2.exists(): continue
            pid=None
            for sh in sbb['shots']:
                if (sh.get('text') or '').strip().startswith(line[:40]) or line[:40] in (sh.get('text') or ''):
                    pid=int(_re.sub(r'\D','',str(sh['id']))); break
            if pid is None or pid not in starts_b: continue
            extra_voices.append((vf2, starts_b[pid]+0.3))
            for sg in segs:
                if sg.get('src')==bdir.name and sg.get('id')==pid: sg['mute']=True
starts=[]; t=0.0
for s in segs: starts.append(t); t+=s['dur']
total=t; hook_end=sum(s['dur'] for s in segs if s['src']=='hook'); court_start=hook_end+3.8+3.6
# ── видео ──
seq=[]
for i,s in enumerate(segs):
    dur=s['dur']; out=tmp/f"seg{i:02d}.mp4"; prev=segs[i-1] if i else None
    fx="punch" if (prev and prev['kind']=='clip' and s['kind']=='clip') else "kenburns_slow"
    if s['kind']=='card':
        sd=ffprobe_duration(Path(s['file'])) or dur                 # карточка короче слота -> тянем, не обрезаем
        vf=(f"setpts={dur/sd:.4f}*PTS," if sd<dur else "")+f"fps={FPS}"
        if sd<dur and dur/sd>1.6: vf=f"fps={FPS},tpad=stop_mode=clone:stop_duration={dur-sd+0.5:.2f}"
        run(["ffmpeg","-y","-v","error","-i",s['file'],"-vf",vf,"-t",f"{dur:.2f}","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    elif s['kind']=='still':
        run(["ffmpeg","-y","-v","error","-loop","1","-framerate",str(FPS),"-t",f"{dur:.2f}","-i",s['file'],"-vf",fx_filter("pushin",dur,W,H)+f",fps={FPS}","-t",f"{dur:.2f}","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    else:
        sd=ffprobe_duration(Path(s['file'])) or dur; pre=""
        if sd<dur and dur/sd<=1.4:                        # слот длиннее клипа: замедляем, а не морозим кадр
            pre=f"setpts={dur/sd:.4f}*PTS,"
        vf=pre+fx_filter(fx,dur,W,H)+f",fps={FPS}"
        if sd<dur and dur/sd>1.4: vf+=f",tpad=stop_mode=clone:stop_duration={dur-sd+0.5:.2f}"
        if s.get('title'): vf+=f",drawtext=fontfile={MONOB}:text='{s['title']}':fontcolor=0x2EE59D:fontsize=72:x=90:y=90:alpha='if(lt(t,0.5),t/0.5,if(lt(t,{dur-0.6:.2f}),1,({dur:.2f}-t)/0.6))'"
        if s.get('speech') or i==len(segs)-1: vf+=f",fade=t=out:st={max(dur-0.7,0):.2f}:d=0.7"
        run(["ffmpeg","-y","-v","error","-i",s['file'],"-t",f"{dur:.2f}","-an","-vf",vf,"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    seq.append(out)
# контроль: суммарная длина отрендеренных сегментов должна совпасть с таймлайном
import subprocess as _sp
real=sum(ffprobe_duration(c) or 0 for c in seq)
if abs(real-total)>0.5: print(f"! длина сегментов {real:.1f}с против таймлайна {total:.1f}с — правлю последний сегмент")
if real<total-0.5:
    last=seq[-1]; need=total-real+ (ffprobe_duration(last) or 0)
    fixed=last.with_name(last.stem+'_pad.mp4')
    _sp.run(["ffmpeg","-y","-v","error","-i",str(last),"-vf",f"tpad=stop_mode=clone:stop_duration={need:.2f},fps={FPS}","-t",f"{need:.2f}","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(fixed)],check=True)
    seq[-1]=fixed
(tmp/'concat.txt').write_text("\n".join(f"file '{c}'" for c in seq),encoding='utf-8')
run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(tmp/'concat.txt'),"-c","copy",str(tmp/'silent.mp4')])
# ── звук ──
music=Path(cfg.paths.music_dir)/'heist_tense.mp3'; cs=int(court_start*1000)
ins=["-i",str(tmp/'silent.mp4'),"-i",str(v1),"-i",str(v2),"-stream_loop","-1","-i",str(music)]
nlab=["[n1]","[n2]"]
parts=["[1:a]aformat=fltp:48000:stereo[n1]", f"[2:a]aformat=fltp:48000:stereo,adelay={cs}|{cs}[n2]"]
for j,(vb,t0) in enumerate(extra_voices):
    ins+=["-i",str(vb)]; idx=ins.count("-i")-1; ms=int(t0*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,adelay={ms}|{ms}[n{j+3}]"); nlab.append(f"[n{j+3}]")
parts+=["".join(nlab)+f"amix=inputs={len(nlab)}:duration=longest:dropout_transition=0,volume={len(nlab)},asplit=2[vm][vm2]",
       f"[3:a]aformat=fltp:48000:stereo,atrim=0:{total:.2f},volume=0.22[m0]","[m0][vm2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]"]
labels=["[duck]"]; k=0
for i,s in enumerate(segs):
    if s['kind']!='clip': continue
    if s.get('mute'): continue                      # клип без своей дорожки (голос героя не нужен)
    ins+=["-i",s['file']]; idx=ins.count("-i")-1; st=int(starts[i]*1000); vol=1.0 if s.get('speech') else 0.12; dur=s['dur']
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,atrim=0:{dur:.2f},volume={vol},afade=t=in:d=0.3,afade=t=out:st={max(dur-0.5,0):.2f}:d=0.5,adelay={st}|{st}[amb{k}]"); labels.append(f"[amb{k}]"); k+=1
sx=cfg.defaults.get('sfx',{}); hit=sfx_file(cfg,'hit',sx.get('hit','')); whoosh=sfx_file(cfg,'whoosh',sx.get('whoosh','')); riser=sfx_file(cfg,'riser',sx.get('riser',''),seconds=6.0)
points=[]
for i in range(1,len(segs)):
    a,b=segs[i-1],segs[i]
    if b['kind']=='card' or a['kind']=='card': points.append((whoosh,starts[i]-0.15,0.35))
    elif a['kind']=='clip' and b['kind']=='clip': points.append((hit,starts[i]-0.05,0.35))
tyl=next((starts[i] for i,s in enumerate(segs) if s.get('title')),None)
if riser and tyl: points.append((riser,max(tyl-6,0),0.3))
if riser: points.append((riser,max(court_start-6,0),0.25))
for f,tt,vol in points:
    if not f: continue
    ins+=["-i",str(f)]; idx=ins.count("-i")-1; ms=int(max(tt,0)*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,volume={vol},adelay={ms}|{ms}[s{k}]"); labels.append(f"[s{k}]"); k+=1
parts.append("".join(labels)+f"amix=inputs={len(labels)}:duration=first:dropout_transition=0,volume={len(labels)}[bed]")
parts.append("[bed][vm]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
g=cfg.channel.get('grade',{}); vf=f"eq=contrast={g.get('contrast',1.05)}:saturation={g.get('saturation',0.9)}:brightness={g.get('brightness',-0.01)},noise=alls={int(g.get('grain',5))}:allf=t+u,vignette=PI/4.6"
run(["ffmpeg","-y","-v","error",*ins,"-filter_complex",";".join(parts),"-map","0:v","-map","[a]","-vf",vf,"-t",f"{total:.2f}","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",str(OUT/'preview_full.mp4')])
run(["ffmpeg","-y","-v","error","-i",str(OUT/'preview_full.mp4'),"-vf","scale=1280:720","-c:v","libx264","-preset","slow","-crf","24","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart",str(OUT/'preview_full_small.mp4')])
json.dump({"segments":segs,"starts":starts,"total":total,"court_start":court_start},open(OUT/'timeline.json','w'),ensure_ascii=False,indent=1)
print(f"preview_full: {total:.1f}s, хук {hook_end:.1f}s, суд с {court_start:.1f}s")
