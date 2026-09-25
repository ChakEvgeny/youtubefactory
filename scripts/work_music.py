#!/usr/bin/env python3
"""Фоновая музыка под готовый ролик: подложка собирается из частей, поджимается
под голос сайдчейном и подмешивается, после чего громкость нормализуется заново.

Музыка НЕ идёт под утверждённым началом: там своя звуковая драматургия — щелчки
клавиатуры и джингл, и подложка с ними спорит. Поэтому старт по умолчанию — с
конца принятого куска.

    python scripts/work_music.py <папка> --in cuts/draft.mp4 --out cuts/draft_music.mp4 \
        --bed /mnt/d/youtube/music/terms_vinyl_a_1.mp3 /mnt/d/youtube/music/terms_vinyl_b_1.mp3 \
        --start 39.3
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"сбой: {' '.join(str(c) for c in cmd)[:200]}\n{r.stderr[-1000:]}")
    return r


def dur(p) -> float:
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(p)]).stdout.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--in", dest="src", default="cuts/draft.mp4")
    ap.add_argument("--out", default="cuts/draft_music.mp4")
    ap.add_argument("--bed", nargs="+", required=True, help="части подложки по порядку")
    ap.add_argument("--start", type=float, default=39.3, help="с какой секунды играет музыка")
    ap.add_argument("--lufs", type=float, default=-32.0, help="громкость подложки до поджатия")
    ap.add_argument("--xf", type=float, default=6.0, help="перетекание между частями")
    ap.add_argument("--fade-in", type=float, default=3.0)
    ap.add_argument("--fade-out", type=float, default=3.5)
    ap.add_argument("--target", type=float, default=-14.0)
    a = ap.parse_args()
    P = Path(a.dir)
    src = P / a.src
    total = dur(src)
    need = total - a.start
    work = P / "_music"; work.mkdir(exist_ok=True)

    # частей берём столько, чтобы хватило длины; последняя часть может повториться
    parts, acc = [], 0.0
    i = 0
    while acc < need:
        p = a.bed[i % len(a.bed)]
        parts.append(p)
        acc += dur(p) - (a.xf if parts[:-1] else 0)
        i += 1
    ins, fc, prev = [], "", "0:a"
    for k, p in enumerate(parts):
        ins += ["-i", str(p)]
        if k:
            fc += f"[{prev}][{k}:a]acrossfade=d={a.xf}:c1=tri:c2=tri[x{k}];"
            prev = f"x{k}"
    fc += (f"[{prev}]atrim=0:{need:.3f},asetpts=N/SR/TB,"
           f"loudnorm=I={a.lufs}:TP=-8:LRA=7,"
           f"afade=t=in:d={a.fade_in},afade=t=out:st={need - a.fade_out:.3f}:d={a.fade_out},"
           f"aformat=channel_layouts=stereo,aresample=48000[bed]")
    bed = work / "bed.wav"
    run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", fc,
         "-map", "[bed]", "-c:a", "pcm_s16le", str(bed)])
    print(f"подложка {dur(bed):.1f}с из {len(parts)} частей")

    # подложка поджимается ГОЛОСОМ: без этого она лезет в речь на тихих словах
    mixed = work / "mixed.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(bed),
         "-filter_complex",
         f"[1:a]adelay={int(a.start*1000)}|{int(a.start*1000)}[b];"
         f"[b][0:a]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=500[duck];"
         f"[0:a][duck]amix=inputs=2:normalize=0,"
         f"aformat=channel_layouts=stereo,aresample=48000,atrim=0:{total:.3f}[m]",
         "-map", "0:v", "-map", "[m]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(mixed)])

    m = run(["ffmpeg", "-i", str(mixed), "-af",
             f"loudnorm=I={a.target}:TP=-2.5:LRA=11:print_format=json", "-f", "null", "/dev/null"])
    j = json.loads(m.stderr[m.stderr.rindex("{"):m.stderr.rindex("}") + 1])
    out = P / a.out
    run(["ffmpeg", "-y", "-v", "error", "-i", str(mixed), "-af",
         f"loudnorm=I={a.target}:TP=-2.5:LRA=11:measured_I={j['input_i']}:"
         f"measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
         f"measured_thresh={j['input_thresh']}:offset={j['target_offset']},"
         f"asetpts=N/SR/TB,apad,atrim=0:{total:.3f},"
         "aformat=sample_fmts=fltp:channel_layouts=stereo,aresample=48000",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(out)])
    print(f"{out}  {dur(out):.2f}с")


if __name__ == "__main__":
    main()
