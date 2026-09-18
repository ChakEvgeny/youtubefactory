#!/usr/bin/env python3
"""Хук v6 финал: планы 1–7 из demo18, план 8 — герой сам говорит «So... how?» (Veo speech, звук клипа на 100%),
диктор без последней строки; затем анимированные титры: «true story» (fade) и «Manhattan Federal Court · August 2017»
(печатается посимвольно). Если готов судебный блок (demo19/demo.mp4) — склеивает в preview_full.mp4."""
import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
from PIL import Image, ImageDraw, ImageFont
from pipeline.config import Config
from pipeline.stages.assemble import fx_filter, sfx_file
from pipeline.util import ffprobe_duration
cfg=Config('heists'); D=Path('/mnt/d/youtube/output/heists/demo18'); W,H,FPS=1920,1080,30; tmp=D/'_final'; tmp.mkdir(exist_ok=True)
def run(cmd):
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=1800)
    if r.returncode: raise SystemExit("ffmpeg: "+r.stderr[-600:])
R=json.loads((D/'result.json').read_text(encoding='utf-8')); segs=R['segments']; durs=R['durs']
segs[-1]['file']=str(D/'clips'/'c08_speak_0.mp4'); segs[-1]['speech']=True
voice=D/'voice_James_nohow.mp3'; vdur=ffprobe_duration(voice)
# план героя с репликой начинается после диктора: слоты 1–7 ужимаем под длину диктора, план 8 = 6 с целиком
head=sum(durs[:-1]); scale=(vdur+0.3)/head; durs=[d*scale for d in durs[:-1]]+[6.0]; total=sum(durs)
# ── титры (PIL -> png-последовательность): fade + печать посимвольно ──
def card_frames(lines, secs, mode, out_dir, font_px=64):
    out_dir.mkdir(exist_ok=True); n=int(secs*FPS)
    f=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf' if mode=='type' else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', font_px)
    total_chars=sum(len(l) for l in lines)
    for i in range(n):
        t=i/FPS; im=Image.new('RGB',(W,H),(5,6,8)); d=ImageDraw.Draw(im)
        if mode=='fade': a=min(t/0.8,1.0,max((secs-t)/0.8,0.0)); shown=lines
        else:
            a=1.0 if t<secs-0.6 else max((secs-t)/0.6,0.0)
            k=int(min(t/(secs-1.6),1.0)*total_chars); shown=[]
            for l in lines:
                shown.append(l[:max(k,0)]); k-=len(l)
            if int(t*2)%2==0 and t<secs-1.6: shown[-1]=shown[-1]+'_'
        col=tuple(int(c*a) for c in ((230,232,235) if mode=='fade' else (46,229,157)))
        y=H/2-(len(lines)*font_px*1.4)/2
        for l in shown:
            w=d.textlength(l,font=f); d.text(((W-w)/2,y),l,font=f,fill=col); y+=font_px*1.4
        im.save(out_dir/f"f{i:04d}.png")
    return n
n1=card_frames(["A TRUE STORY.","Every event in this film happened.","The reconstruction is AI-generated."],3.6,'fade',tmp/'card1',56)
n2=card_frames(["MANHATTAN FEDERAL COURT","AUGUST 2017"],3.4,'type',tmp/'card2',64)
run(["ffmpeg","-y","-v","error","-framerate",str(FPS),"-i",str(tmp/'card1'/'f%04d.png'),"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(tmp/'card1.mp4')])
run(["ffmpeg","-y","-v","error","-framerate",str(FPS),"-i",str(tmp/'card2'/'f%04d.png'),"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(tmp/'card2.mp4')])
# ── видео планов ──
seq=[]; starts=[]; t=0.0
for i,(s,dur) in enumerate(zip(segs,durs)):
    starts.append(t); t+=dur; out=tmp/f"seg{i:02d}.mp4"; fx="punch" if i>0 else "kenburns_slow"
    if s['kind']=='still':
        run(["ffmpeg","-y","-v","error","-loop","1","-framerate",str(FPS),"-t",f"{dur:.2f}","-i",s['file'],"-vf",fx_filter("pushin",dur,W,H)+f",fps={FPS}","-t",f"{dur:.2f}","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    else:
        vf=fx_filter(fx,dur,W,H)+f",fps={FPS}"; sd=ffprobe_duration(Path(s['file'])) or dur
        if sd<dur: vf+=f",tpad=stop_mode=clone:stop_duration={dur-sd+0.5:.2f}"
        if s.get('title'): vf+=f",drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf:text='{s['title']}':fontcolor=0x2EE59D:fontsize=72:x=90:y=90:alpha='if(lt(t,0.5),t/0.5,if(lt(t,{dur-0.6:.2f}),1,({dur:.2f}-t)/0.6))'"
        if i==len(segs)-1: vf+=f",fade=t=out:st={max(dur-0.7,0):.2f}:d=0.7"
        run(["ffmpeg","-y","-v","error","-i",s['file'],"-t",f"{dur:.2f}","-an","-vf",vf,"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    seq.append(out)
(tmp/'concat.txt').write_text("\n".join(f"file '{c}'" for c in seq),encoding='utf-8')
run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(tmp/'concat.txt'),"-c","copy",str(tmp/'silent.mp4')])
# ── звук: диктор, музыка (дак), ambient планов; у плана 8 — речь героя на 100% ──
music=Path(cfg.paths.music_dir)/'heist_tense.mp3'
ins=["-i",str(tmp/'silent.mp4'),"-i",str(voice),"-stream_loop","-1","-i",str(music)]
parts=["[1:a]aformat=fltp:48000:stereo,asplit=2[vm][vm2]", f"[2:a]aformat=fltp:48000:stereo,atrim=0:{total:.2f},volume=0.22[m0]","[m0][vm2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]"]
labels=["[duck]"]; k=0
for i,(s,dur) in enumerate(zip(segs,durs)):
    if s['kind']!='clip': continue
    ins+=["-i",s['file']]; idx=ins.count("-i")-1; st=int(starts[i]*1000); vol=1.0 if s.get('speech') else 0.12
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,atrim=0:{dur:.2f},volume={vol},afade=t=in:d=0.3,afade=t=out:st={max(dur-0.5,0):.2f}:d=0.5,adelay={st}|{st}[amb{k}]"); labels.append(f"[amb{k}]"); k+=1
sx=cfg.defaults.get('sfx',{}); hit=sfx_file(cfg,'hit',sx.get('hit','')); riser=sfx_file(cfg,'riser',sx.get('riser',''),seconds=6.0)
for i in range(1,len(segs)):
    if not hit: continue
    ins+=["-i",str(hit)]; idx=ins.count("-i")-1; ms=int(max(starts[i]-0.05,0)*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,volume=0.35,adelay={ms}|{ms}[s{k}]"); labels.append(f"[s{k}]"); k+=1
if riser:
    ins+=["-i",str(riser)]; idx=ins.count("-i")-1; ms=int(max(starts[5]-6,0)*1000)   # райзер к «three years later»
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,volume=0.3,adelay={ms}|{ms}[s{k}]"); labels.append(f"[s{k}]"); k+=1
parts.append("".join(labels)+f"amix=inputs={len(labels)}:duration=first:dropout_transition=0,volume={len(labels)}[bed]")
parts.append("[bed][vm]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
g=cfg.channel.get('grade',{}); vf=f"eq=contrast={g.get('contrast',1.05)}:saturation={g.get('saturation',0.9)}:brightness={g.get('brightness',-0.01)},noise=alls={int(g.get('grain',5))}:allf=t+u,vignette=PI/4.6"
run(["ffmpeg","-y","-v","error",*ins,"-filter_complex",";".join(parts),"-map","0:v","-map","[a]","-vf",vf,"-t",f"{total:.2f}","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",str(tmp/'hook.mp4')])
# титры с тихой музыкой продолжения
for name in ('card1','card2'):
    run(["ffmpeg","-y","-v","error","-i",str(tmp/f'{name}.mp4'),"-stream_loop","-1","-i",str(music),"-filter_complex","[1:a]aformat=fltp:48000:stereo,volume=0.10[a]","-map","0:v","-map","[a]","-shortest","-c:v","copy","-c:a","aac","-b:a","192k","-ar","48000",str(tmp/f'{name}_a.mp4')])
parts_list=[tmp/'hook.mp4',tmp/'card1_a.mp4',tmp/'card2_a.mp4']
court=Path('/mnt/d/youtube/output/heists/demo19/demo.mp4')
if court.exists(): parts_list.append(court)
(tmp/'final_concat.txt').write_text("\n".join(f"file '{p}'" for p in parts_list),encoding='utf-8')
out=D/('preview_full.mp4' if court.exists() else 'hook_final.mp4')
run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(tmp/'final_concat.txt'),"-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",str(out)])
run(["ffmpeg","-y","-v","error","-i",str(out),"-vf","scale=1280:720","-c:v","libx264","-preset","slow","-crf","24","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart",str(out.with_name(out.stem+'_small.mp4'))])
print("готово:", out, f"хук {total:.1f}s, суд {'есть' if court.exists() else 'нет'}")
