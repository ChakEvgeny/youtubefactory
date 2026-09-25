#!/usr/bin/env python3
"""Сборка блока канала Terms of Employment: кадры по таймкодам озвучки,
инфографика фишкой поверх кадра, перетекания, интро после хука, −14 LUFS.

Каждый кадр сначала собирается отдельным сегментом (наезд камеры плюс фишка),
и только потом сегменты сшиваются перетеканием. Один общий фильтр на всё
читать невозможно, а ошибку в нём видно только по готовому файлу.

    python scripts/work_build.py <папка> --block "0 · хук" --audio voice/hook_a.mp3 \
        --intro /mnt/d/youtube/output/newchannel/brand_terms/intro.mp4 --out cuts/first30.mp4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOTION = ROOT / "motion"
W, H, FPS, XF = 1920, 1080, 25, 0.6
CHIP_FPS = 24  # композиция WorkChip живёт на 24, кадр видео на 25 — подаём с -framerate


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit(f"сбой: {' '.join(str(c) for c in cmd)[:200]}\n{r.stderr[-1500:]}")
    return r


def dur(p) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(p)])
    return float(r.stdout.strip())


def chip_png(sh, seconds: float, work: Path) -> Path | None:
    """Фишка — PNG-последовательность с альфой. ProRes 4444 отдавал yuv422p12le
    без альфы, поэтому только --sequence --image-format=png."""
    if not sh.get("chip"):
        return None
    d = work / f"chip{sh['id']:03d}"
    if d.exists() and list(d.glob("*.png")):
        return d
    d.mkdir(parents=True, exist_ok=True)
    props = json.dumps({"big": sh["chip"], "small": sh.get("chip_small", ""),
                        "kicker": sh.get("chip_kicker", ""), "transparent": True,
                        "side": sh.get("chip_side", "left"), "seconds": round(seconds, 2)})
    run(["npx", "remotion", "render", "src/index.ts", "WorkChip", str(d),
         "--sequence", "--image-format=png", f"--props={props}", "--log=error"], cwd=MOTION)
    return d


def segment(sh, src: Path, slot: float, out: Path, chip: Path | None, i: int) -> None:
    """clip_in — точка входа в клип: Kling почти всегда тратит первую секунду на
    собственный отъезд камеры, и начало клипа в монтаж не годится."""
    """Один кадр: наезд или отъезд, поверх — фишка. zoompan d=1: с d=<кадры> он
    размножает каждый входной кадр и ролик раздувается."""
    n = max(int(slot * FPS), 2)
    z = (f"min(1.0+0.085*on/{n},1.085)" if i % 2 == 0 else f"max(1.085-0.085*on/{n},1.0)")
    ins, vf = [], []
    if src.suffix.lower() in (".mp4", ".mov"):
        if sh.get("clip_in"):
            ins += ["-ss", f"{float(sh['clip_in']):.3f}"]
        ins += ["-t", f"{slot:.3f}", "-i", str(src)]
        vf.append(f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},setsar=1,fps={FPS}[base];")
    else:
        ins += ["-loop", "1", "-t", f"{slot:.3f}", "-i", str(src)]
        vf.append(f"[0:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
                  f"crop={W*2}:{H*2},setsar=1,fps={FPS},"
                  f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"d=1:s={W}x{H}:fps={FPS}[base];")
    if chip:
        ins += ["-framerate", str(CHIP_FPS), "-pattern_type", "glob",
                "-i", str(chip / "element-*.png")]
        vf.append(f"[1:v]scale={W}:{H},fps={FPS}[ov];[base][ov]overlay=0:0:shortest=0[vout];")
    else:
        vf.append("[base]null[vout];")
    fc = "".join(vf).rstrip(";")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *ins,
         "-filter_complex", fc, "-map", "[vout]", "-an",
         "-t", f"{slot:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
         "-pix_fmt", "yuv420p", "-r", str(FPS), str(out)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--block", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--intro", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lufs", type=float, default=-14.0)
    a = ap.parse_args()

    P = Path(a.dir)
    work = P / "_build"
    work.mkdir(exist_ok=True)
    shots = [s for s in json.loads((P / "storyboard.json").read_text(encoding="utf-8"))
             if s["block"] == a.block]
    shots.sort(key=lambda s: s["t_in"])
    if not shots:
        raise SystemExit(f"нет кадров блока {a.block}")

    # исходник кадра: явный clip (анимация), явный file, иначе stills/sNNN.jpg
    segs = []
    for i, sh in enumerate(shots):
        src = P / (sh.get("clip") or sh.get("file") or f"stills/s{sh['id']:03d}.jpg")
        if not src.exists():
            raise SystemExit(f"нет исходника кадра {sh['id']}: {src}")
        slot = sh["dur"]
        # запас под перетекание: половина на краях блока, целое между кадрами
        pad = (XF / 2 if i in (0, len(shots) - 1) else XF)
        seg = work / f"seg{i:02d}.mp4"
        # фишка не должна появляться поверх перетекания: там под ней смесь двух
        # кадров, и плашка читается грязной. Даём ей длину слота без запаса.
        segment(sh, src, slot + pad, seg, chip_png(sh, slot, work), i)
        segs.append((seg, sh, slot))
        print(f"  [{sh['id']:>3}] {sh['t_in']:5.2f}–{sh['t_in']+slot:5.2f}  {src.name}"
              f"{'  +фишка ' + sh['chip'] if sh.get('chip') else ''}")

    # перетекания: смещение центрируем на стыке, поэтому off = t_in − XF/2
    ins, chain, prev = [], "", "0:v"
    for i, (seg, sh, _) in enumerate(segs):
        ins += ["-i", str(seg)]
        if i:
            off = sh["t_in"] - XF / 2
            chain += (f"[{prev}][{i}:v]xfade=transition=fade:duration={XF}:"
                      f"offset={off:.3f}[x{i}];")
            prev = f"x{i}"
    total = shots[-1]["t_in"] + shots[-1]["dur"]
    fc = chain + f"[{prev}]format=yuv420p[vout]"
    body = work / "body.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *ins,
         "-filter_complex", fc, "-map", "[vout]", "-an", "-t", f"{total:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-r", str(FPS), str(body)])

    # звук: моно из ElevenLabs в стерео, иначе часть плееров молчит
    bodya = work / "body_a.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(body),
         "-i", str(P / a.audio), "-map", "0:v", "-map", "1:a",
         # голос короче блока — добиваем тишиной: расхождение видео и звука
         # больше 0.05 с считается браком (CLAUDE.md)
         # голос короче блока — добиваем тишиной и режем ровно по длине блока.
         # asetpts ДО apad: loudnorm и mp3 сдвигают метки, и atrim по чужим
         # меткам отдаёт кусок не той длины. Расхождение больше 0.05 с — брак.
         "-af", "aformat=channel_layouts=stereo,aresample=48000,"
                f"asetpts=N/SR/TB,apad,atrim=0:{total:.3f},asetpts=N/SR/TB",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000",
         "-t", f"{total:.3f}", str(bodya)])

    parts = [bodya]
    if a.intro:
        # интро идёт сразу после хука (правило канала), приводим к общей сетке
        fit = work / "intro_fit.mp4"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", a.intro,
             "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                    f"setsar=1,fps={FPS}",
             "-af", "aformat=channel_layouts=stereo,aresample=48000",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(fit)])
        parts.append(fit)

    lst = work / "parts.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    joined = work / "joined.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(joined)])

    vlen = float(run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                      "stream=duration", "-of", "default=nw=1:nk=1", str(joined)]).stdout.strip())

    # громкость −14 LUFS двумя проходами
    m = run(["ffmpeg", "-i", str(joined), "-af",
             f"loudnorm=I={a.lufs}:TP=-2.5:LRA=11:print_format=json", "-f", "null", "/dev/null"])
    j = json.loads(m.stderr[m.stderr.rindex("{"):m.stderr.rindex("}") + 1])
    out = P / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-af",
         f"loudnorm=I={a.lufs}:TP=-2.5:LRA=11:measured_I={j['input_i']}:"
         f"measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
         f"measured_thresh={j['input_thresh']}:offset={j['target_offset']},"
         # запас под AAC берёт сам loudnorm через TP=-2.5: отдельный volume после
         # нормализации уводил интегральную ниже цели ровно на свою величину
         "asetpts=N/SR/TB,"
         # склейка кусков и loudnorm добавляют по кадру AAC (21 мс) — режем по видео
         f"apad,atrim=0:{vlen:.3f},asetpts=N/SR/TB,"
         "aformat=sample_fmts=fltp:channel_layouts=stereo,aresample=48000",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(out)])

    v = run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
             "stream=duration", "-of", "default=nw=1:nk=1", str(out)]).stdout.strip()
    au = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
              "stream=duration", "-of", "default=nw=1:nk=1", str(out)]).stdout.strip()
    print(f"\n{out}")
    print(f"  видео {float(v):.3f} с, звук {float(au):.3f} с, расхождение {abs(float(v)-float(au)):.3f} с")
    if abs(float(v) - float(au)) > 0.05:
        print("  ВНИМАНИЕ: расхождение больше 0.05 с")


if __name__ == "__main__":
    main()
