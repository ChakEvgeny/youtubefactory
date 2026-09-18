#!/usr/bin/env python3
"""Сборка демо: 5 Veo-планов под озвучку (равные слоты по длине голоса), punch-in на стыках,
райзер к первому стыку, hit на каждом стыке, музыка с 0 с (дак под голос), ambient Veo −18 dB,
грейд/зерно/виньетка, затемнение в конце. Пишет demo15/demo.mp4 (1080p) и demo_small.mp4."""
import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
from pipeline.config import Config
from pipeline.stages.assemble import fx_filter, sfx_file, duck_envelope
from pipeline.util import ffprobe_duration
cfg=Config('heists'); D=Path('/mnt/d/youtube/output/heists/demo15')
voice=D/(sys.argv[1] if len(sys.argv)>1 else 'voice_James.mp3')
A=json.loads((D/'animate.json').read_text(encoding='utf-8'))
clips=[s for s in A['shots'] if s.get('file')]
total=ffprobe_duration(voice)+0.6; W,H,FPS=1920,1080,30
tmp=D/'_clips'; tmp.mkdir(exist_ok=True)
lens=[min(ffprobe_duration(Path(s['file'])) or 6.0, 6.0) for s in clips]
ins_cfg=A.get('stamp_insert') or {}
extra=ins_cfg.get('dur',0.0) if ins_cfg.get('file') else 0.0
lens[-1]=max(lens[-1], total-sum(lens[:-1])-extra)     # хвост озвучки — на последнем плане (удержание + fade)
slot=sum(lens)/len(lens)
def run(cmd):
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=1800)
    if r.returncode: raise SystemExit("ffmpeg: "+r.stderr[-800:])
seq=[]; starts=[]; t_acc=0.0
for i,s in enumerate(clips):
    dur=lens[i]; src=s['file']; sd=ffprobe_duration(Path(src)) or 6.0
    starts.append(t_acc); t_acc+=dur
    fx="punch" if i>0 else "kenburns_slow"
    vf=fx_filter(fx,dur,W,H)+f",fps={FPS}"
    if sd<dur: vf+=f",tpad=stop_mode=clone:stop_duration={dur-sd+0.5:.2f}"   # только последний план (хвост голоса)
    if i==len(clips)-1: vf+=f",fade=t=out:st={max(dur-0.8,0):.2f}:d=0.8"
    out=tmp/f"c{i:02d}.mp4"
    run(["ffmpeg","-y","-v","error","-i",src,"-t",f"{dur:.2f}","-an","-vf",vf,"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
    seq.append(out)
    if ins_cfg.get('file') and s.get('id')==ins_cfg.get('after_id'):      # вставка штампа с читаемым текстом
        ins_out=tmp/'stamp_insert.mp4'; d=float(ins_cfg['dur'])
        run(["ffmpeg","-y","-v","error","-loop","1","-framerate",str(FPS),"-t",f"{d:.2f}","-i",ins_cfg['file'],"-vf",fx_filter("punch",d,W,H)+f",fps={FPS}","-t",f"{d:.2f}","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(ins_out)])
        seq.append(ins_out); t_acc+=d
lst=D/'_concat.txt'; lst.write_text("\n".join(f"file '{c}'" for c in seq),encoding='utf-8')
silent=D/'_silent.mp4'; run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(lst),"-c","copy",str(silent)])
# звук: голос + музыка(дак) + ambient планов + SFX
mdir=Path(cfg.paths.music_dir); music=mdir/'heist_tense.mp3'
env=duck_envelope(None,total+1,D/'_env.wav',depth_db=-12.0) if False else None
ins=["-i",str(silent),"-i",str(voice),"-stream_loop","-1","-i",str(music)]
parts=["[1:a]aformat=fltp:48000:stereo,asplit=2[vm][vm2]", f"[2:a]aformat=fltp:48000:stereo,atrim=0:{total:.2f},volume=0.22[m0]"]
# сайдчейн-дак музыки под голос
parts.append("[m0][vm2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]")
labels=["[duck]"]; k=0
for i,s in enumerate(clips):                      # ambient из Veo-клипа на месте своего плана
    ins+=["-i",s['file']]; idx=ins.count("-i")-1; st=int(starts[i]*1000); L=lens[i]
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,atrim=0:{L:.2f},volume=0.12,afade=t=in:d=0.3,afade=t=out:st={max(L-0.5,0):.2f}:d=0.5,adelay={st}|{st}[amb{k}]"); labels.append(f"[amb{k}]"); k+=1
sx=cfg.defaults.get('sfx',{}); files={kind:sfx_file(cfg,kind,sx.get(kind,'')) for kind in ('hit','whoosh')}
riser=sfx_file(cfg,'riser',sx.get('riser',''),seconds=float(sx.get('riser_sec',6)))
points=[('hit',starts[i]-0.05) for i in range(1,len(clips))]
if riser: points.append(('riser',max(starts[1]-6,0) if len(starts)>1 else 0))
for kind,t in points:
    f=riser if kind=='riser' else files.get(kind)
    if not f: continue
    ins+=["-i",str(f)]; idx=ins.count("-i")-1; ms=int(max(t,0)*1000)
    parts.append(f"[{idx}:a]aformat=fltp:48000:stereo,volume={0.35 if kind!='riser' else 0.3},adelay={ms}|{ms}[s{k}]"); labels.append(f"[s{k}]"); k+=1
parts.append("".join(labels)+f"amix=inputs={len(labels)}:duration=first:dropout_transition=0,volume={len(labels)}[bed]")
parts.append("[bed][vm]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
grade=cfg.channel.get('grade',{}); vf=(f"eq=contrast={grade.get('contrast',1.05)}:saturation={grade.get('saturation',0.9)}:brightness={grade.get('brightness',-0.01)},"
     f"noise=alls={int(grade.get('grain',5))}:allf=t+u,vignette=PI/4.6")
out=D/'demo.mp4'
run(["ffmpeg","-y","-v","error",*ins,"-filter_complex",";".join(parts),"-map","0:v","-map","[a]","-vf",vf,"-t",f"{total:.2f}",
     "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(out)])
run(["ffmpeg","-y","-v","error","-i",str(out),"-vf","scale=1280:720","-c:v","libx264","-preset","slow","-crf","24","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart",str(D/'demo_small.mp4')])
print("demo:",out,f"{total:.1f}s, планов {len(clips)}, слот {slot:.1f}s")
