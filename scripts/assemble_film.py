#!/usr/bin/env python3
"""Сборка фильма по timed.json: кадры, движения камеры, переходы, звук.

Кадр может быть клипом Veo, картинкой с движением камеры, замороженной
картинкой или карточкой. Переходы берутся из поля transition: перетекание,
жёсткая склейка, затемнение. Звук собирается встык из пореплично озвученных
файлов, поэтому картинка и голос не разъезжаются.
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

FPS = 24
W, H = 1280, 720


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(" ".join(map(str, cmd))[:200] + "\n" + r.stderr[-800:])
    return r


def probe(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def move_filter(fx: str, dur: float) -> str:
    """Движение камеры по картинке. Наезд и отъезд — zoompan, панорамы — crop."""
    n = max(int(dur * FPS), 2)
    if fx == "push":
        return (f"scale={W*2}:-2,zoompan=z='min(1.0009+0.0009*on,1.10)':d={n}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}")
    if fx == "pull":
        return (f"scale={W*2}:-2,zoompan=z='max(1.10-0.0009*on,1.001)':d={n}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}")
    if fx in ("left", "right", "down"):
        s = 1.14
        ow, oh = int(W * s), int(H * s)
        if fx == "left":
            x, y = f"(iw-ow)*(1-t/{dur:.3f})", "(ih-oh)/2"
        elif fx == "right":
            x, y = f"(iw-ow)*(t/{dur:.3f})", "(ih-oh)/2"
        else:
            x, y = "(iw-ow)/2", f"(ih-oh)*(t/{dur:.3f})"
        return f"scale={ow}:{oh},crop={W}:{H}:{x}:{y},fps={FPS}"
    return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}"


def make_segment(s: dict, d: Path, tmp: Path, length: float) -> Path:
    out = tmp / f"seg_{s['id']:04d}.mp4"
    if out.exists() and abs(probe(out) - length) < 0.08:
        return out
    clip = d / "clips" / f"{s['id']:03d}.mp4"
    img = d / "storyboard" / f"{s['id']:03d}.jpg"
    if s.get("tier") == "anim" and clip.exists():
        cd = probe(clip)
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}"
        if cd and abs(cd - length) > 0.05:
            vf = f"setpts={length/cd:.5f}*PTS," + vf     # растягиваем, а не морозим хвост
        run(["ffmpeg", "-v", "error", "-i", str(clip), "-an", "-vf", vf,
             "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-r", str(FPS), str(out), "-y"])
        return out
    fx = "none" if s.get("tier") in ("freeze", "card") else s.get("fx", "push")
    run(["ffmpeg", "-v", "error", "-loop", "1", "-i", str(img), "-t", f"{length:.3f}",
         "-vf", move_filter(fx, length), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS), str(out), "-y"])
    return out


def main():
    d = Path(sys.argv[1])
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    tmp = d / "_build"; tmp.mkdir(exist_ok=True)

    # 1) звук: реплика + тишина до конца кадра, встык
    aparts = []
    for s in r:
        a = tmp / f"a_{s['id']:04d}.wav"
        if not a.exists() or abs(probe(a) - s["dur"]) > 0.05:
            src = d / (s.get("audio") or "")
            if s.get("audio") and src.exists():
                run(["ffmpeg", "-v", "error", "-i", str(src), "-af",
                     f"apad=whole_dur={s['dur']:.3f}", "-t", f"{s['dur']:.3f}",
                     "-ar", "48000", "-ac", "1", str(a), "-y"])
            else:
                run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                     "-t", f"{s['dur']:.3f}", str(a), "-y"])
        aparts.append(a)
    alist = tmp / "a.txt"
    alist.write_text("\n".join(f"file '{p.resolve()}'" for p in aparts), encoding="utf-8")
    voice = tmp / "voice_full.wav"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(alist),
         "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(voice), "-y"])
    total = probe(voice)
    print(f"голос собран: {int(total)//60}:{int(total)%60:02d}")

    # 2) видео: группы кадров между жёсткими переходами
    runs, cur = [], []
    for s in r:
        if s.get("transition") in ("cut", "dip") and cur:
            runs.append(cur); cur = [s]
        else:
            cur.append(s)
    if cur:
        runs.append(cur)
    print(f"групп перетекания: {len(runs)}")

    OV = 0.6
    run_files = []
    for gi, grp in enumerate(runs, 1):
        segs = []
        for i, s in enumerate(grp):
            extra = OV if i < len(grp) - 1 else 0.0
            segs.append(make_segment(s, d, tmp, s["dur"] + extra))
        outg = tmp / f"run_{gi:03d}.mp4"
        if not outg.exists():
            if len(segs) == 1:
                outg.write_bytes(segs[0].read_bytes())
            else:
                inputs = []
                for p in segs:
                    inputs += ["-i", str(p)]
                fc, prev, acc = [], "0:v", 0.0
                for i in range(1, len(segs)):
                    acc += grp[i - 1]["dur"]
                    lab = f"x{i}"
                    fc.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={OV}:"
                              f"offset={acc - 0:.3f}[{lab}]")
                    prev = lab
                run(["ffmpeg", "-v", "error", *inputs, "-filter_complex", ";".join(fc),
                     "-map", f"[{prev}]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                     "-pix_fmt", "yuv420p", "-r", str(FPS), str(outg), "-y"])
        run_files.append(outg)
        if gi % 5 == 0:
            print(f"  … группа {gi}/{len(runs)}", flush=True)

    vlist = tmp / "v.txt"
    vlist.write_text("\n".join(f"file '{p.resolve()}'" for p in run_files), encoding="utf-8")
    silent = tmp / "video_silent.mp4"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(vlist),
         "-c", "copy", str(silent), "-y"])
    print(f"видео собрано: {probe(silent):.1f} c против звука {total:.1f} c")

    # 3) музыка под голосом с приглушением и финальный микс
    music = Path("/mnt/d/youtube/music/jlr_neutral.mp3")
    if music.exists():
        run(["ffmpeg", "-v", "error", "-i", str(silent), "-i", str(voice),
             "-stream_loop", "-1", "-i", str(music),
             "-filter_complex",
             "[2:a]volume=0.16,atrim=0:%.3f,afade=t=in:st=0:d=3,afade=t=out:st=%.3f:d=4[m];"
             "[1:a][m]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400[mx];"
             "[1:a][mx]amix=inputs=2:duration=first:weights=1 0.9,"
             "loudnorm=I=-14:TP=-1.5:LRA=11[a]" % (total, max(total - 4, 0)),
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", str(d / "FILM_ada.mp4"), "-y"])
    else:
        run(["ffmpeg", "-v", "error", "-i", str(silent), "-i", str(voice),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", str(d / "FILM_ada.mp4"), "-y"])
    f = d / "FILM_ada.mp4"
    print(f"готово: {f}  {probe(f)/60:.1f} мин, {f.stat().st_size/1e6:.0f} МБ")


if __name__ == "__main__":
    main()
