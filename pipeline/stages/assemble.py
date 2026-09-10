"""assemble — ffmpeg: сцены по таймкодам голоса, xfade, Ken Burns, субтитры,
музыка с sidechain-ducking, loudnorm -14 LUFS, 1080p30 h264."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from ..util import sha1, ffprobe_duration, run

XFADE = 0.4          # длительность перехода, сек
CLOSING_HOLD = 2.5   # закрывающий план после последнего слова, сек
SUB_WORDS = 4        # слов в строке субтитра


def scene_times(ctx: Path, scenes: list[dict], words: list[dict], total: float) -> list[tuple]:
    """Старт каждой сцены = время слова, стоящего на её позиции в тексте."""
    script = (ctx / "script.md").read_text(encoding="utf-8")
    scene_re = re.compile(r"^\[(?:SCENE|MOTION|BEAT):.+?\]\s*$", re.IGNORECASE | re.MULTILINE)
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
    # финальный [SCENE] после последнего слова — закрывающий план поверх уходящей музыки
    if out and out[-1][0] >= total - 1.5:
        st = out[-1][0]
        out[-1] = (st, st + CLOSING_HOLD)
    return out


def sentences(words: list[dict]) -> list[dict]:
    """Группировка слов в предложения — субтитры строим по ним, а не по 3-5 слов."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.!?]$", w["word"]) or len(cur) >= 18:
            out.append({"text": " ".join(x["word"] for x in cur),
                        "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur = []
    if cur:
        out.append({"text": " ".join(x["word"] for x in cur),
                    "start": cur[0]["start"], "end": cur[-1]["end"]})
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
Style: Main,DejaVu Sans,{int(h*0.046)},&H00FFFFFF,&H00000000,&H88000000,-1,1,{max(3,int(h*0.004))},2,2,{int(w*0.20)},{int(w*0.20)},{int(h*0.08)},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = []
    for sn in sentences(words):
        txt = sn["text"].replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,{ts(sn['start'])},{ts(sn['end'])},Main,,0,0,0,,{txt}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def fx_filter(fx: str, dur: float, w: int, h: int) -> str:
    """Движение внутри кадра через crop с временны́м выражением — дёшево и без loop.
    Кривые — ease-out cubic (пружина без осцилляции), не линейные."""
    D = max(dur, 0.5)
    ease = f"(1-pow(1-min(t/{D:.3f},1),3))"
    if fx == "pushin":                       # push-in 4.5%
        z = f"(1+0.045*{ease})"
    elif fx == "zoomout":                    # медленный отъезд 6%
        z = f"(1.06-0.06*{ease})"
    elif fx == "kenburns_slow":              # едва заметный наезд 3%
        z = f"(1+0.03*min(t/{D:.3f},1))"
    elif fx == "punch":                      # punch-in: 1.10 -> 1.0 за 0.35 с, дальше лёгкий push
        z = f"(1+0.10*pow(1-min(t/0.35,1),3)+0.03*min(t/{D:.3f},1))"
    else:
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    return (f"scale={w*1.12:.0f}:{h*1.12:.0f}:force_original_aspect_ratio=increase,"
            f"crop=w='iw/{z}':h='ih/{z}',scale={w}:{h},setsar=1")


def build_clip(entry: dict, dur: float, w: int, h: int, fps: int, out: Path,
               fx: str = "cut", fade_in: float = 0.0, fade_out: float = 0.0):
    """Нормализует один ассет в клип нужной длительности с эффектом по типу кадра."""
    src = entry.get("file")
    fades = ""
    if fade_in > 0:
        fades += f",fade=t=in:st=0:d={fade_in:.2f}"
    if fade_out > 0:
        fades += f",fade=t=out:st={max(dur-fade_out,0):.2f}:d={fade_out:.2f}"
    if not src:
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", f"color=c=black:s={w}x{h}:d={dur:.2f}:r={fps}",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])
        return
    if src.endswith(".jpg"):
        frames = max(int(dur * fps), 2)
        slow = fx in ("kenburns_slow", "zoomout")
        zmax = 1.06 if slow else 1.14
        step = (zmax - 1.0) / frames
        z = (f"min(zoom+{step:.5f},{zmax})" if fx != "zoomout"
             else f"if(lte(zoom,1.0),{zmax},max(1.001,zoom-{step:.5f}))")
        if fx == "punch":
            z = f"1+0.10*pow(1-min(on/{fps*0.35:.1f},1),3)+0.03*on/{frames}"
        vf = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2},"
              f"zoompan=z='{z}':d={frames}:s={w}x{h}:fps={fps},setsar=1{fades}")
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", f"{dur:.2f}", "-i", src,
             "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])
        return
    sd = ffprobe_duration(Path(src)) or dur
    speed = 1.25 if fx == "speedramp" else 1.0
    need = dur * speed
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if sd < need:
        cmd += ["-stream_loop", str(int(need // max(sd, 0.5)) + 1)]
    elif sd > need + 1.0:                    # разные куски одного файла, не всегда начало
        cmd += ["-ss", f"{min((sd - need) * 0.35, sd - need):.2f}"]
    vf = fx_filter(fx, dur, w, h)
    if speed != 1.0:
        vf = f"setpts=PTS/{speed}," + vf
    vf += f",fps={fps}" + fades
    # -t здесь — выходная опция: длина слота, а не длина прочитанного источника
    # (при speedramp source читается на need=dur*1.25, но выход обязан быть dur)
    cmd += ["-i", src, "-t", f"{dur:.2f}", "-an", "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)]
    run(cmd)


def black_clip(dur: float, w: int, h: int, fps: int, out: Path):
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c=black:s={w}x{h}:d={dur:.2f}:r={fps}",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])


def sfx_file(cfg, kind: str, text: str, seconds: float = 1.2) -> Path | None:
    """SFX через ElevenLabs sound-generation, один раз на вид, в кэш music_dir/sfx_<kind>.mp3."""
    import urllib.request
    p = Path(cfg.paths.music_dir) / f"sfx_{kind}.mp3"
    if p.exists() and p.stat().st_size > 0:
        return p
    key = cfg.key("ELEVENLABS_API_KEY")
    if not key:
        return None
    body = json.dumps({"text": text, "duration_seconds": seconds, "prompt_influence": 0.5}).encode()
    req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation", data=body,
                                 headers={"xi-api-key": key, "Content-Type": "application/json"}, method="POST")
    try:
        data = urllib.request.urlopen(req, timeout=120).read()
        if not data or data[:1] == b"{" or len(data) < 2000:
            return None
        p.write_bytes(data)
        return p
    except Exception:
        return None


def duck_envelope(words: list[dict], total: float, out: Path, depth_db: float = -12.0,
                  attack: float = 0.06, release: float = 0.35, gap: float = 0.30,
                  sr: int = 48000) -> Path:
    """Огибающая громкости музыки из пословных таймкодов: под речью −depth_db.
    Детерминировано, в отличие от sidechaincompress, который на этом голосе
    давал −4…−6 dB при любых настройках."""
    import array, math, wave
    # слова -> речевые отрезки (паузы короче gap не размыкают)
    segs = []
    for w in words:
        if segs and w["start"] - segs[-1][1] < gap:
            segs[-1][1] = max(segs[-1][1], w["end"])
        else:
            segs.append([w["start"], w["end"]])
    n = int(total * sr) + sr
    low = 10 ** (depth_db / 20)
    env = array.array("f", [1.0]) * n
    for a, b in segs:
        i0, i1 = int(max(a - attack, 0) * sr), int(min(b + release, total) * sr)
        for i in range(i0, min(i1, n)):
            t = i / sr
            if t < a:                      # атака: 1 -> low
                g = 1 - (1 - low) * (t - (a - attack)) / attack
            elif t <= b:
                g = low
            else:                          # отпускание: low -> 1
                g = low + (1 - low) * (t - b) / release
            env[i] = min(env[i], g)
    pcm = array.array("h", (int(max(-1.0, min(1.0, v)) * 32767) for v in env))
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return out


def pick_music(music_dir: Path) -> Path | None:
    if not music_dir.exists():
        return None
    tracks = [p for p in music_dir.iterdir()
              if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".flac", ".ogg")]
    return random.choice(tracks) if tracks else None


def run_stage(cfg, ctx: Path, cost, preview_sec: float | None = None) -> dict:
    """Сборка по кадрам. Hard cut по умолчанию, dip-to-black на поворотах,
    движение внутри кадра по типу фрагмента, грейд и зерно, музыка с ducking."""
    w, h = cfg.defaults["resolution"]
    fps = cfg.defaults["fps"]
    lufs = cfg.defaults["loudness_lufs"]
    subs_on = bool(cfg.channel.get("subtitles", cfg.defaults.get("subtitles", False)))
    shots = json.loads((ctx / "assets.json").read_text(encoding="utf-8"))
    ts = json.loads((ctx / "timestamps.json").read_text(encoding="utf-8"))
    voice = ctx / "voice.mp3"
    total = ffprobe_duration(voice)
    if preview_sec:
        shots = [s for s in shots if s["start"] < preview_sec]
        total = min(total, preview_sec)
    mfiles = {}
    gen_audio = []                                   # (start, file) — ambient из t2v-клипов
    gp = ctx / "generate.json"
    if gp.exists():
        for m in json.loads(gp.read_text(encoding="utf-8")):
            mfiles[m["idx"]] = m["file"]
            if m.get("audio"):
                gen_audio.append((m["idx"], m["file"]))
    for name in ("motion.json", "collage.json", "screens.json"):
        mp = ctx / name
        if mp.exists():
            mfiles.update({m["idx"]: m["file"] for m in json.loads(mp.read_text(encoding="utf-8")) if m["idx"] not in mfiles})

    shots_dur = {sh["idx"]: max(min(sh["end"], total) - sh["start"], 0.8) for sh in shots}
    DIP = 0.4
    tmp = ctx / "_clips"
    tmp.mkdir(exist_ok=True)
    seq, dips = [], 0
    for i, sh in enumerate(shots):
        end = min(sh["end"], total) if preview_sec else sh["end"]
        dur = max(end - sh["start"], 0.8)
        src = mfiles.get(sh["idx"]) if sh.get("source") in ("motion", "card", "collage", "screens", "gen") \
            else sh.get("file")
        dip = bool(sh.get("dip_before")) and i > 0
        if dip:                                  # 0.4с чёрного: 0.15 fade-out + 0.1 чёрный + 0.15 fade-in
            dur -= DIP
            b = tmp / f"b{sh['idx']:04d}.mp4"
            if not b.exists():
                black_clip(0.10, w, h, fps, b)
            seq.append(b)
            dips += 1
        fx = sh.get("fx", "cut") if sh.get("source") not in ("motion", "card", "collage", "screens", "gen") else "cut"
        if sh.get("beat") == "hook" and i > 0 and cfg.defaults.get("hook_fx") and sh.get("source") not in ("motion", "card"):
            fx = cfg.defaults["hook_fx"]
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        # ключ клипа — содержимое, а не номер кадра: при пересборке с другим источником
        # старый клип по тому же idx не должен подхватываться
        key = sha1("clip", f"{src}|{dur:.2f}|{fx}|{int(dip)}|{int(bool(nxt and nxt.get('dip_before')))}")[:16]
        c = tmp / f"s{sh['idx']:04d}_{key}.mp4"
        if not c.exists():
            build_clip({"file": src}, max(dur, 0.5), w, h, fps, c, fx=fx,
                       fade_in=0.15 if dip else 0.0,
                       fade_out=0.15 if (nxt and nxt.get("dip_before")) else 0.0)
        seq.append(c)
    if not seq:
        raise SystemExit("нет кадров для сборки")

    # hard cut: concat demuxer без перекодирования между кадрами
    lst = ctx / "_concat.txt"
    lst.write_text("\n".join(f"file '{c}'" for c in seq), encoding="utf-8")
    silent = ctx / "_video_silent.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(silent)], timeout=3600)

    # музыка: тревожный трек с первой фразы после хука, финальный — на последней четверти
    hook_end = 0.0
    for sh in shots:
        if sh.get("beat") == "hook":
            hook_end = max(hook_end, sh["end"])
    riser_at = hook_end                            # райзер подводит к концу хука
    if cfg.defaults.get("music_from") == "start":
        hook_end = 0.0
    total = max(total, max((sh["end"] for sh in shots), default=total))   # закрывающий план
    mdir = cfg.paths.music_dir
    tense, resolve = mdir / "jlr_tense.mp3", mdir / "jlr_resolve.mp3"
    if not tense.exists():
        tense = pick_music(mdir)
    music_ok = bool(tense and tense.exists())
    switch = total * 0.78

    out = ctx / ("preview.mp4" if preview_sec else "video.mp4")
    grade = cfg.channel.get("grade", cfg.defaults.get("grade", {}))
    vf = [f"eq=contrast={grade.get('contrast',1.05)}:saturation={grade.get('saturation',0.9)}"
          f":brightness={grade.get('brightness',-0.01)}",
          f"noise=alls={int(grade.get('grain',6))}:allf=t+u",
          "vignette=PI/4.6"]
    if subs_on:
        ass = ctx / "subs.ass"
        make_ass(ts["words"], ass, w, h)
        vf.append("subtitles='" + str(ass).replace("\\", "/").replace(":", r"\:") + "'")

    if music_ok:
        ins = ["-i", str(silent), "-i", str(voice), "-stream_loop", "-1", "-i", str(tense)]
        # голос нужен дважды (сайдчейн + микс) — метку нельзя потребить дважды, отсюда asplit
        parts = ["[1:a]aformat=fltp:48000:stereo[vm]",
                 f"[2:a]aformat=fltp:48000:stereo,atrim=0:{max(total-hook_end,1):.2f},"
                 f"adelay={int(hook_end*1000)}|{int(hook_end*1000)},afade=t=in:st={hook_end:.2f}:d=0.35[m0]"]
        mlab = "[m0]"
        if resolve.exists() and total - switch > 20 and not preview_sec:
            ins += ["-stream_loop", "-1", "-i", str(resolve)]
            parts += [f"[3:a]aformat=fltp:48000:stereo,atrim=0:{total-switch+3:.2f},"
                      f"adelay={int((switch-3)*1000)}|{int((switch-3)*1000)},afade=t=in:st={switch-3:.2f}:d=3[m1]",
                      f"[m0]afade=t=out:st={switch-3:.2f}:d=3[m0f]",
                      "[m0f][m1]amix=inputs=2:duration=longest:dropout_transition=0[mm]"]
            mlab = "[mm]"
        # −12 dB под голосом: огибающая из таймкодов слов, умножаем музыку на неё
        env = duck_envelope(ts["words"], total + 1.0, ctx / "_duck_env.wav",
                            depth_db=float(cfg.defaults.get("duck_db", -12.0)))
        env_idx = ins.count("-i")            # индекс входа = число -i до него, не len//2
        ins += ["-i", str(env)]
        parts += [f"{mlab}volume=0.28[mv]",
                  f"[{env_idx}:a]aformat=fltp:48000:stereo[env]",
                  "[mv][env]amultiply[duck]"]
        # ambient из t2v-клипов (Veo пишет звук): на 10–15% громкости, на месте своего кадра
        amb_labels = []
        starts = {sh["idx"]: sh["start"] for sh in shots}
        gain = 10 ** (float(cfg.defaults.get("gen", {}).get("ambient_gain_db", -18)) / 20)
        for k, (gidx, gfile) in enumerate(a for a in gen_audio if a[0] in starts):
            i_in = ins.count("-i")
            ins += ["-i", str(gfile)]
            st = int(starts[gidx] * 1000)
            parts.append(f"[{i_in}:a]aformat=fltp:48000:stereo,volume={gain:.3f},afade=t=in:d=0.3,"
                         f"afade=t=out:st={max(shots_dur.get(gidx, 4.0) - 0.4, 0.1):.2f}:d=0.4,adelay={st}|{st}[amb{k}]")
            amb_labels.append(f"[amb{k}]")
        # SFX на стыках: whoosh на dip-переходах, hit на смене кадра внутри хука (у референса ~12% стыков)
        sx = cfg.defaults.get("sfx") or {}
        if sx.get("enabled"):
            sgain = 10 ** (float(sx.get("gain_db", -16)) / 20)
            points = []
            for i, sh in enumerate(shots):
                if i == 0:
                    continue
                if sh.get("dip_before") and "dip" in sx.get("at", []):
                    points.append(("whoosh", sh["start"] - 0.25))
                elif sh.get("beat") == "hook" and "hook_cuts" in sx.get("at", []):
                    points.append(("hit", sh["start"] - 0.05))
                elif "turn" in sx.get("at", []) and sh.get("beat") == "turn" and shots[i - 1].get("beat") != "turn":
                    points.append(("hit", sh["start"] - 0.05))       # вход в поворот сюжета
            files = {k: sfx_file(cfg, k, sx.get(k, "")) for k in ("whoosh", "hit")}
            if "riser" in sx.get("at", []) and sx.get("riser") and riser_at > 3:
                rs = float(sx.get("riser_sec", 6))
                files["riser"] = sfx_file(cfg, "riser", sx["riser"], seconds=rs)
                points.append(("riser", max(riser_at - rs, 0.0)))
            for k, (kind, t) in enumerate(p for p in points if files.get(p[0])):
                i_in = ins.count("-i")
                ins += ["-i", str(files[kind])]
                ms = int(max(t, 0) * 1000)
                parts.append(f"[{i_in}:a]aformat=fltp:48000:stereo,volume={sgain:.3f},adelay={ms}|{ms}[sfx{k}]")
                amb_labels.append(f"[sfx{k}]")
        if amb_labels:
            # [duck] первым: duration=first берёт длину музыкальной дорожки, а не короткого SFX
            parts.append("[duck]" + "".join(amb_labels) + f"amix=inputs={len(amb_labels) + 1}:duration=first:"
                         f"dropout_transition=0,volume={len(amb_labels) + 1}[duck2]")
            duck_lab = "[duck2]"
        else:
            duck_lab = "[duck]"
        parts += [f"{duck_lab}[vm]amix=inputs=2:duration=first:dropout_transition=0,"
                  f"afade=t=out:st={max(total-1.8,0):.2f}:d=1.8,"
                  f"loudnorm=I={lufs}:TP=-1.5:LRA=11[a]"]
        cmd = ["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", ";".join(parts),
               "-map", "0:v", "-map", "[a]"]
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(voice),
               "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11", "-map", "0:v", "-map", "1:a"]
    cmd += ["-vf", ",".join(vf)]
    if preview_sec:
        cmd += ["-t", f"{preview_sec:.2f}"]
    cmd += ["-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(out)]
    run(cmd, timeout=14400)

    silent.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
    (ctx / "_duck_env.wav").unlink(missing_ok=True)
    if not preview_sec:
        for f in tmp.glob("*.mp4"):
            f.unlink(missing_ok=True)
        if not any(tmp.iterdir()):
            tmp.rmdir()

    import collections
    durs = sorted(round(s["end"] - s["start"], 1) for s in shots)
    cost.add("assemble", "ffmpeg", 0.0, f"{len(shots)} кадров, dip {dips}")
    return {"shots": len(shots), "median_shot_sec": durs[len(durs) // 2] if durs else 0,
            "fx": dict(collections.Counter(s.get("fx", "cut") for s in shots)),
            "dips": dips, "music": music_ok, "music_from_sec": round(hook_end, 1),
            "sfx": len(amb_labels) if music_ok else 0,
            "duration_sec": round(ffprobe_duration(out), 1), "subtitles": subs_on,
            "size_mb": round(out.stat().st_size / 1e6, 1), "file": str(out)}
