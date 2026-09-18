#!/usr/bin/env python3
"""Раскладывает блок в папку просмотра: КАЖДЫЙ план — mp4 в порядке монтажа,
стиллы рендерятся с медленным наездом, карточки как есть, у видео варианты .1/.2/.3."""
import json, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
from pipeline.config import Config
from pipeline.stages.assemble import fx_filter
from pipeline.util import ffprobe_duration
cfg=Config('heists'); B=Path(sys.argv[1]); RV=Path(sys.argv[2]); RV.mkdir(exist_ok=True); W,H,FPS=1920,1080,30
for f in RV.glob('*'):
    if f.is_file(): f.unlink()
R=json.loads((B/'result.json').read_text(encoding='utf-8')); sb=json.loads((B/'storyboard.json').read_text(encoding='utf-8'))
meta={int(re.sub(r'\D','',str(s['id']))): s for s in sb['shots']}
def run(cmd): subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=900)
rows=["# Порядок монтажа — все планы как видео","","Имя: `NN_typ_idII.M.mp4` (NN — порядок, typ — vid/card/still, II — id плана, M — вариант).","",
      "| # | файлы | тип | QC | длит | текст диктора |","|---:|---|---|---:|---:|---|"]
for n,s in enumerate(R['segments'],1):
    i=s['id']; kind=s['kind']; typ={'clip':'vid','card':'card','still':'still'}[kind]; dur=s['dur']
    if kind=='clip': cands=sorted(B.glob(f'clips/c{i:02d}_*.mp4'))
    elif kind=='card': cands=[B/'clips'/f'card{i:02d}.mp4']
    else: cands=sorted(B.glob(f's{i:02d}_*.jpg'))
    cands=[c for c in cands if c.exists()]; chosen=str(s['file'])
    cands=sorted(cands,key=lambda c:(0 if str(c)==chosen else 1,c.name)); names=[]
    for m,c in enumerate(cands,1):
        out=RV/f"{n:02d}_{typ}_id{i:02d}.{m}.mp4"
        if c.suffix=='.jpg':
            run(["ffmpeg","-y","-v","error","-loop","1","-framerate",str(FPS),"-t",f"{dur:.2f}","-i",str(c),
                 "-vf",fx_filter("pushin",dur,W,H)+f",fps={FPS}","-t",f"{dur:.2f}","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(out)])
        else:
            run(["ffmpeg","-y","-v","error","-i",str(c),"-c","copy",str(out)])
        names.append(out.name)
    rows.append(f"| {n:02d} | {' , '.join(names)} | {typ} | {s.get('qc','')} | {dur:.0f}с | {(meta.get(i,{}).get('text') or '').replace('|','/')[:76]} |")
(RV/'README.md').write_text("\n".join(rows),encoding='utf-8')
print('файлов:',len(list(RV.glob('*.mp4'))),'| README.md')
