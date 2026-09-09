"""assemble — ffmpeg: сцены по таймкодам голоса, xfade, Ken Burns, субтитры,
музыка с sidechain-ducking, loudnorm -14 LUFS, 1080p30 h264."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from ..util import ffprobe_duration, run

XFADE = 0.4          # длительность перехода, сек
SUB_WORDS = 4        # слов в строке субтитра


def scene_times(ctx: Path, scenes: list[dict], words: list[dict], total: float) -> list[tuple]:
    """Старт каждой сцены = время слова, стоящего на её позиции в тексте."""
    script = (ctx / "script.md").read_text(encoding="utf-8")
    scene_re = re.compile(r"^\[SCENE:.+?\]\s*$", re.IGNORECASE | re.MULTILINE)
    starts = []
    for sc in scenes:
        spoken_before = len(scene_re.sub("", script[: sc["char_pos"]]).split())
        idx = min(spoken_before, len(words) - 1) if words else 0
        starts.append(words[idx]["start"] if words else 0.0)
    out = []
    for i, st in enumerate(starts):
        en = starts[i + 1] if i + 1 < len(starts) else total
        if en - st < 1.0:
            en = st + 1.0
        out.append((st, en))
    return out


def make_ass(words: list[dict], path: Path, w: int, h: int):
    def ts(t):
        cs = int(round(t * 100))
        return f"{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,DejaVu Sans,{int(h*0.062)},&H00FFFFFF,&H00000000,&H88000000,-1,1,{max(3,int(h*0.004))},2,2,80,80,{int(h*0.10)},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = []
    for i in range(0, len(words), SUB_WORDS):
        grp = words[i:i + SUB_WORDS]
        txt = " ".join(g["word"] for g in grp).replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,{ts(grp[0]['start'])},{ts(grp[-1]['end'])},Main,,0,0,0,,{txt}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def build_clip(entry: dict, dur: float, w: int, h: int, fps: int, out: Path):
    """Нормализует один ассет в клип нужной длительности 1920x1080."""
    src = entry.get("file")
    scale = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
             f"crop={w}:{h},setsar=1,fps={fps}")
    if not src:                                   # заглушка: чёрный кадр
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", f"color=c=black:s={w}x{h}:d={dur:.2f}:r={fps}",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])
        return
    if src.endswith(".jpg"):                      # фото -> Ken Burns
        frames = max(int(dur * fps), 2)
        z = "min(zoom+0.0009,1.18)" if random.random() < 0.5 else "if(lte(zoom,1.0),1.18,max(1.001,zoom-0.0009))"
        vf = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2},"
              f"zoompan=z='{z}':d={frames}:s={w}x{h}:fps={fps},setsar=1")
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", f"{dur:.2f}", "-i", src,
             "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])
        return
    sd = ffprobe_duration(Path(src)) or dur       # видео короче сцены -> зацикливаем
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if sd < dur:
        cmd += ["-stream_loop", str(int(dur // max(sd, 0.5)) + 1)]
    cmd += ["-i", src, "-t", f"{dur:.2f}", "-an", "-vf", scale,
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)]
    run(cmd)


def pick_music(music_dir: Path) -> Path | None:
    if not music_dir.exists():
        return None
    tracks = [p for p in music_dir.iterdir()
              if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".flac", ".ogg")]
    return random.choice(tracks) if tracks else None


def run_stage(cfg, ctx: Path, cost) -> dict:
    w, h = cfg.defaults["resolution"]
    fps = cfg.defaults["fps"]
    lufs = cfg.defaults["loudness_lufs"]
    assets = json.loads((ctx / "assets.json").read_text(encoding="utf-8"))
    mpath = ctx / "motion.json"
    if mpath.exists():
        mfiles = {m["idx"]: m["file"] for m in json.loads(mpath.read_text(encoding="utf-8"))}
        for a in assets:
            if a.get("source") == "motion" and a["idx"] in mfiles:
                a["file"] = mfiles[a["idx"]]
    scenes = json.loads((ctx / "scenes.json").read_text(encoding="utf-8"))
    ts = json.loads((ctx / "timestamps.json").read_text(encoding="utf-8"))
    voice = ctx / "voice.mp3"
    total = ffprobe_duration(voice)

    tmp = ctx / "_clips"
    tmp.mkdir(exist_ok=True)
    times = scene_times(ctx, scenes, ts["words"], total)
    clips = []
    for entry, (st, en) in zip(assets, times):
        dur = max(en - st + XFADE, 1.2)
        p = tmp / f"c{entry['idx']:03d}.mp4"
        if not p.exists():
            build_clip(entry, dur, w, h, fps, p)
        clips.append(p)

    # склейка с xfade
    silent = ctx / "_video_silent.mp4"
    if len(clips) == 1:
        run(["ffmpeg", "-y", "-v", "error", "-i", str(clips[0]), "-c", "copy", str(silent)])
    else:
        inputs, filt, prev, offset = [], [], "[0:v]", 0.0
        for i, c in enumerate(clips):
            inputs += ["-i", str(c)]
        for i in range(1, len(clips)):
            offset += ffprobe_duration(clips[i - 1]) - XFADE
            lbl = f"[x{i}]"
            filt.append(f"{prev}[{i}:v]xfade=transition=fade:duration={XFADE}:"
                        f"offset={max(offset,0):.2f}{lbl}")
            prev = lbl
        run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filt),
             "-map", prev, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-r", str(fps), str(silent)], timeout=7200)

    ass = ctx / "subs.ass"
    make_ass(ts["words"], ass, w, h)

    music = pick_music(cfg.paths.music_dir)
    out = ctx / "video.mp4"
    ass_esc = str(ass).replace("\\", "/").replace(":", r"\:")
    if music:
        # музыка приглушается голосом: sidechaincompress
        af = ("[1:a]aformat=fltp:44100:stereo,volume=0.22[m];"
              "[2:a]aformat=fltp:44100:stereo[v];"
              "[m][v]sidechaincompress=threshold=0.05:ratio=9:attack=15:release=350[duck];"
              f"[duck][2:a]amix=inputs=2:duration=first:dropout_transition=0,"
              f"loudnorm=I={lufs}:TP=-1.5:LRA=11[a]")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(silent),
               "-stream_loop", "-1", "-i", str(music), "-i", str(voice),
               "-filter_complex", af, "-map", "0:v", "-map", "[a]"]
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(voice),
               "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11", "-map", "0:v", "-map", "1:a"]
    cmd += ["-vf", f"subtitles='{ass_esc}'", "-shortest",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    run(cmd, timeout=10800)

    cost.add("assemble", "ffmpeg", 0.0, f"{len(clips)} сцен, музыка: {music.name if music else 'нет'}")
    return {"clips": len(clips), "duration_sec": round(ffprobe_duration(out), 1),
            "music": music.name if music else None,
            "size_mb": round(out.stat().st_size / 1e6, 1)}
