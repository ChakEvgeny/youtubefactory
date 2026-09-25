#!/usr/bin/env python3
"""Сборка ролика Terms of Employment целиком из timed.json.

Каждый шот собирается отдельным сегментом, потом сегменты сшиваются
перетеканием. Звук режется по шотам и склеивается встык, поэтому видео и звук
совпадают по построению, а не по совпадению.

Виды шотов: рисунок с наездом камеры · клип марионетки · карточка Remotion.
Поверх рисунка может лежать фишка с числом.

    python scripts/work_assemble.py <папка> --out cuts/draft.mp4
    python scripts/work_assemble.py <папка> --only "3 · США" --out cuts/usa.mp4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOTION = ROOT / "motion"
W, H, FPS, XF = 1920, 1080, 25, 0.6
CHIP_FPS = 24


def stamp(sh, slot: float, P: Path | None = None) -> str:
    """Отпечаток того, ИЗ ЧЕГО собран сегмент. Кэш по одному имени файла уже
    подсунул в сборку устаревшие куски: марионетки перерисовали, а сегменты
    остались от прошлого прогона, и в черновик уехал старый рисунок с наездом.
    Номер сегмента вдобавок съезжает, когда из раскадровки убирают шот."""
    parts = [sh.get("kind"), sh.get("file"), sh.get("clip"), sh.get("over"),
             sh.get("card"), sh.get("chip"), sh.get("audio"),
             round(sh.get("a_off", 0), 3), round(slot, 3)]
    # путь у перерисованного кадра тот же, поэтому в отпечаток идёт ещё и время
    # изменения файла: иначе новый рисунок молча не попадает в сборку
    if P is not None:
        for k in ("file", "clip", "over", "audio"):
            f = sh.get(k)
            if f and (P / f).exists():
                parts.append(int((P / f).stat().st_mtime))
    # карточку и фишку рисует Remotion: данные те же, а вёрстка могла измениться.
    # Без этого правка компонента молча не доезжает до сборки — так таймлайн
    # продолжал вылезать за лист после починки
    for k, comp in (("card", "WorkCard.tsx"), ("chip", "WorkChip.tsx")):
        src = MOTION / "src" / "scenes" / comp
        if sh.get(k) and src.exists():
            parts.append(int(src.stat().st_mtime))
    return hashlib.sha1(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit(f"сбой: {' '.join(str(c) for c in cmd)[:180]}\n{r.stderr[-1200:]}")
    return r


def chip_seq(sh, seconds, work: Path) -> Path | None:
    """фишка — PNG с альфой: ProRes 4444 отдавал yuv422p12le без альфы"""
    if not sh.get("chip"):
        return None
    d = work / f"chip{sh['id']}"
    if d.exists() and list(d.glob("*.png")):
        return d
    d.mkdir(parents=True, exist_ok=True)
    c = sh["chip"]
    props = json.dumps({"big": c.get("big", ""), "small": c.get("small", ""),
                        "kicker": c.get("kicker", ""), "transparent": True,
                        "side": c.get("side", "left"), "seconds": round(seconds, 2)})
    run(["npx", "remotion", "render", "src/index.ts", "WorkChip", str(d),
         "--sequence", "--image-format=png", f"--props={props}", "--log=error"], cwd=MOTION)
    return d


def card_seq(sh, seconds: float, work: Path) -> Path:
    """Карточка — накладка с альфой: инфографика это предмет ПОВЕРХ кадра, а не
    отдельный экран. Поэтому PNG-последовательность, как у фишки."""
    d = work / f"card{sh['id']}"
    if d.exists() and list(d.glob("*.png")):
        return d
    d.mkdir(parents=True, exist_ok=True)
    props = dict(sh["card"])
    props["seconds"] = round(seconds, 2)
    props["overlay"] = True
    run(["npx", "remotion", "render", "src/index.ts", "WorkCard", str(d),
         "--sequence", "--image-format=png",
         f"--props={json.dumps(props, ensure_ascii=False)}", "--log=error"], cwd=MOTION)
    return d


def segment(P: Path, sh, slot: float, out: Path, work: Path, i: int) -> None:
    n = max(int(slot * FPS), 2)
    ins, vf = [], []
    # клип и карточка короче слота на длину перетекания: последний кадр
    # держим через tpad, иначе цепочка xfade обрывается раньше времени
    if sh.get("kind") == "card":
        # под карточкой живёт предыдущий кадр с тем же наездом камеры
        under = P / (sh.get("over") or f"stills/s{sh['id']:03d}.jpg")
        z = (f"min(1.0+0.085*on/{n},1.085)" if i % 2 == 0 else f"max(1.085-0.085*on/{n},1.0)")
        ins += ["-loop", "1", "-t", f"{slot:.3f}", "-i", str(under)]
        vf.append(f"[0:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
                  f"crop={W*2}:{H*2},setsar=1,fps={FPS},"
                  f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"d=1:s={W}x{H}:fps={FPS}[bg];")
        seq = card_seq(sh, slot, work)
        ins += ["-framerate", "24", "-pattern_type", "glob", "-i", str(seq / "element-*.png")]
        vf.append(f"[1:v]scale={W}:{H},fps={FPS}[cd];"
                  f"[bg][cd]overlay=0:0:shortest=0[base];")
    elif sh.get("clip"):
        ins += ["-i", str(P / sh["clip"])]
        vf.append(f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},setsar=1,fps={FPS},"
                  f"tpad=stop_mode=clone:stop_duration={slot:.3f}[base];")
    else:
        f = P / (sh.get("file") or f"stills/s{sh['id']:03d}.jpg")
        z = (f"min(1.0+0.085*on/{n},1.085)" if i % 2 == 0 else f"max(1.085-0.085*on/{n},1.0)")
        ins += ["-loop", "1", "-t", f"{slot:.3f}", "-i", str(f)]
        vf.append(f"[0:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
                  f"crop={W*2}:{H*2},setsar=1,fps={FPS},"
                  f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"d=1:s={W}x{H}:fps={FPS}[base];")
    chip = chip_seq(sh, slot, work)
    if chip:
        k = len([x for x in ins if x == "-i"])
        ins += ["-framerate", str(CHIP_FPS), "-pattern_type", "glob",
                "-i", str(chip / "element-*.png")]
        vf.append(f"[{k}:v]scale={W}:{H},fps={FPS}[ov];[base][ov]overlay=0:0:shortest=0[vout];")
    else:
        vf.append("[base]null[vout];")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *ins,
         "-filter_complex", "".join(vf).rstrip(";"), "-map", "[vout]", "-an",
         "-t", f"{slot:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
         "-pix_fmt", "yuv420p", "-r", str(FPS), str(out)])


def audio_piece(P: Path, sh, slot: float, out: Path) -> None:
    """кусок дорожки ровно под шот; у немых шотов — тишина той же длины"""
    if sh.get("audio"):
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{sh['a_off']:.3f}",
             "-t", f"{slot:.3f}", "-i", str(P / sh["audio"]),
             "-af", f"aformat=channel_layouts=stereo,aresample=48000,"
                    f"asetpts=N/SR/TB,apad,atrim=0:{slot:.3f}",
             "-c:a", "pcm_s16le", str(out)])
    else:
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", f"anullsrc=r=48000:cl=stereo", "-t", f"{slot:.3f}",
             "-c:a", "pcm_s16le", str(out)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="", help="собрать один блок")
    ap.add_argument("--intro", default="")
    # готовый принятый кусок подклеивается ФАЙЛОМ. Пересобирать его из кадров
    # нельзя: перетекание уезжает на стык с продолжением, и вставленное потом
    # интро разрезает уже смешанные кадры.
    ap.add_argument("--prefix", default="", help="готовый mp4 в начало")
    ap.add_argument("--skip-block", action="append", default=[])
    ap.add_argument("--lufs", type=float, default=-14.0)
    # финальный кадр уходит в затемнение, дальше чёрный хвост: зритель понимает,
    # что ролик кончился, до того как YouTube подставит свою заставку
    ap.add_argument("--fade", type=float, default=1.2, help="затемнение в конце, с")
    ap.add_argument("--black", type=float, default=3.0, help="чёрный хвост, с")
    a = ap.parse_args()

    P = Path(a.dir)
    work = P / "_asm"
    work.mkdir(exist_ok=True)
    shots = json.loads((P / "timed.json").read_text(encoding="utf-8"))
    if a.only:
        shots = [s for s in shots if s["block"] == a.only]
    for b in a.skip_block:
        shots = [s for s in shots if not str(s["block"]).startswith(b)]
    shots.sort(key=lambda s: s["t_in"])

    segs, auds, slots = [], [], []
    for i, sh in enumerate(shots):
        slot = float(sh["dur"])
        pad = XF / 2 if i in (0, len(shots) - 1) else XF
        seg = work / f"v{i:03d}.mp4"
        aud = work / f"a{i:03d}.wav"
        st = work / f"v{i:03d}.stamp"
        want = stamp(sh, slot + pad, P)
        if st.exists() and st.read_text().strip() != want:
            # исходник шота изменился: сегмент, карточку и фишку под ним
            # выбрасываем, иначе кэш вернёт вчерашнюю картинку
            for x in (seg, aud):
                x.unlink(missing_ok=True)
            for d in (work / f"card{sh['id']}", work / f"chip{sh['id']}"):
                shutil.rmtree(d, ignore_errors=True)
        if not seg.exists():
            segment(P, sh, slot + pad, seg, work, i)
        if not aud.exists():
            audio_piece(P, sh, slot, aud)
        st.write_text(want)
        segs.append(seg); auds.append(aud); slots.append(slot)
        print(f"  [{sh['id']:>4}] {sh['t_in']:7.2f} {slot:5.2f}с "
              f"{sh.get('kind'):<6} {(sh.get('narr') or '')[:44]}", flush=True)

    # Интро идёт сразу после хука. Имя блока в разных роликах писалось
    # по-разному («0 · хук», «БЛОК 0 · ХУК»), поэтому ищем по смыслу.
    def is_hook(b: str) -> bool:
        b = str(b).strip().lower()
        return b.startswith("0 ") or "хук" in b or "hook" in b

    # Фильм режется на куски ПО ГРАНИЦАМ ШОТОВ, а не по времени. Резать готовую
    # склейку нельзя: перетекание центрировано на стыке, и разрез по времени
    # попадал в его середину — следующий кадр начинал проступать ещё до интро.
    cuts = [0, len(shots)]
    if a.intro:
        n_hook = sum(1 for s in shots if is_hook(s["block"]))
        if not n_hook or n_hook >= len(shots):
            raise SystemExit("блок хука не найден — интро вставлять некуда")
        cuts = [0, n_hook, len(shots)]

    def render_chain(lo: int, hi: int, out: Path) -> None:
        """Отдельный кусок фильма: xfade внутри, по краям — чистая склейка."""
        ins, chain, prev = [], "", "0:v"
        base = shots[lo]["t_in"]
        for j in range(lo, hi):
            ins += ["-i", str(segs[j])]
            k = j - lo
            if k:
                off = shots[j]["t_in"] - base - XF / 2
                chain += (f"[{prev}][{k}:v]xfade=transition=fade:duration={XF}:"
                          f"offset={off:.3f}[x{k}];")
                prev = f"x{k}"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *ins,
             "-filter_complex", chain + f"[{prev}]format=yuv420p[v]", "-map", "[v]", "-an",
             "-t", f"{sum(slots[lo:hi]):.3f}", "-c:v", "libx264", "-preset", "medium",
             "-crf", "17", "-r", str(FPS), str(out)])

    def mux_chain(lo: int, hi: int, out: Path) -> None:
        vid = work / f"body{lo}_{hi}.mp4"
        render_chain(lo, hi, vid)
        lst = work / f"a{lo}_{hi}.txt"
        lst.write_text("".join(f"file '{q}'\n" for q in auds[lo:hi]), encoding="utf-8")
        track = work / f"track{lo}_{hi}.wav"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", str(track)])
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(vid),
             "-i", str(track), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", "-shortest", str(out)])

    parts = []
    for lo, hi in zip(cuts, cuts[1:]):
        q = work / f"part{lo}_{hi}.mp4"
        mux_chain(lo, hi, q)
        parts.append(q)
    joined = parts[0] if len(parts) == 1 else None

    if a.intro:
        fit = work / "intro.mp4"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", a.intro,
             "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                    f"setsar=1,fps={FPS}",
             "-af", "aformat=channel_layouts=stereo,aresample=48000",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(fit)])
        parts.insert(1, fit)
    if len(parts) > 1:
        pl = work / "j.txt"
        pl.write_text("".join(f"file '{q}'\n" for q in parts), encoding="utf-8")
        joined = work / "joined.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(pl),
             "-c", "copy", str(joined)])
    src = joined
    if a.prefix:
        pl = work / "p.txt"
        fit = work / "prefix.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", a.prefix,
             "-vf", f"scale={W}:{H},setsar=1,fps={FPS}",
             "-af", "aformat=channel_layouts=stereo,aresample=48000",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(fit)])
        pl.write_text(f"file '{fit}'\nfile '{joined}'\n", encoding="utf-8")
        src = work / "withprefix.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(pl),
             "-c", "copy", str(src)])

    m = run(["ffmpeg", "-i", str(src), "-af",
             f"loudnorm=I={a.lufs}:TP=-2.5:LRA=11:print_format=json", "-f", "null", "/dev/null"])
    j = json.loads(m.stderr[m.stderr.rindex("{"):m.stderr.rindex("}") + 1])
    vlen = float(run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                      "stream=duration", "-of", "default=nw=1:nk=1", str(src)]).stdout.strip())
    out = P / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    # затемнение делаем в ТОМ ЖЕ проходе, что и нормализацию: иначе видео
    # перекодируется дважды
    af = (f"loudnorm=I={a.lufs}:TP=-2.5:LRA=11:measured_I={j['input_i']}:"
          f"measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
          f"measured_thresh={j['input_thresh']}:offset={j['target_offset']},"
          f"asetpts=N/SR/TB,apad,atrim=0:{vlen:.3f},"
          "aformat=sample_fmts=fltp:channel_layouts=stereo,aresample=48000")
    vopt = ["-c:v", "copy"]
    if a.fade > 0:
        st = max(0.0, vlen - a.fade)
        af += f",afade=t=out:st={st:.3f}:d={a.fade:.3f}"
        vopt = ["-vf", f"fade=t=out:st={st:.3f}:d={a.fade:.3f}",
                "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                "-pix_fmt", "yuv420p", "-r", str(FPS)]
    body_out = (work / "faded.mp4") if a.black > 0 else out
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", af,
         *vopt, "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(body_out)])
    if a.black > 0:
        blk = work / "black.mp4"
        run(["ffmpeg", "-y", "-v", "error",
             "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{a.black:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(blk)])
        tl = work / "t.txt"
        tl.write_text(f"file '{body_out}'\nfile '{blk}'\n", encoding="utf-8")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(tl),
             "-c", "copy", "-fflags", "+genpts", str(out)])

    v = run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=duration",
             "-of", "default=nw=1:nk=1", str(out)]).stdout.strip()
    au = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=duration",
              "-of", "default=nw=1:nk=1", str(out)]).stdout.strip()
    print(f"\n{out}\n  видео {float(v):.3f} с, звук {float(au):.3f} с, "
          f"расхождение {abs(float(v)-float(au)):.3f} с")


if __name__ == "__main__":
    main()
