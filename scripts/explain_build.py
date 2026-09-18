#!/usr/bin/env python3
"""Сборка объясняющего ролика: сцены — картинки, схемы — Remotion, паузы — чёрное.

Темп бодрый: базовая скорость 1.15, между блоками короткие паузы.
Переходы жёсткой склейкой — это не документалка, здесь смены должны читаться.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from voice_speed import speed, dur, breathe

FPS, W, H = 24, 1920, 1080
MOTION = ROOT / "motion"
WPM_CAP = 165.0
FONT_DEFAULT = "Sriracha"

# Концовка — одинаковая во ВСЕХ роликах канала, отдельно включать не надо.
# Последний рисунок уходит в чёрное, выезжает плашка THE END, под ней две строки.
OUTRO_SEC = 6.0
OUTRO_END = "THE END"
OUTRO_THANKS = "Thanks for watching"
OUTRO_CTA = "Subscribe for more"

# Заставка канала — во всех роликах, в первой паузе (сразу после вступления).
# Имя выводится «невидимым карандашом», звук карандаша звучит только пока идёт
# письмо. Музыка перед заставкой уходит в ноль и после неё стартует заново.
BUMPER_SEC = 4.0
BUMPER_WORDS = ["Why", "&", "How"]
PENCIL = Path("/mnt/d/youtube/music/pencil_write.mp3")
# окна письма внутри заставки, секунды (считаны из Bumper.tsx)
PENCIL_WINDOWS = [(0.33, 2.58), (2.75, 3.20)]


def needs_plate(img: Path, thresh: float = 30.0) -> bool:
    """Нужна ли плашка под текстом.

    Разброс яркости тут не работает: рисунок везде контрастный, и по нему все
    кадры выходят «пёстрыми». Мерить надо ПЛОТНОСТЬ ДЕТАЛЕЙ — сколько линий
    штриховки попадает в зону текста. Замер по 38 кадрам: медиана 30,
    ровные фоны 18-24, забитые штриховкой 42-49.
    """
    try:
        from PIL import Image, ImageStat, ImageFilter
        im = Image.open(img).convert("L")
        w, h = im.size
        box = im.crop((int(w * 0.12), int(h * 0.22), int(w * 0.88), int(h * 0.80)))
        return ImageStat.Stat(box.filter(ImageFilter.FIND_EDGES)).mean[0] > thresh
    except Exception:
        return True


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(" ".join(map(str, cmd))[:180] + "\n" + r.stderr[-600:])
    return r


def ken(img: Path, out: Path, L: float):
    """Медленный наезд без дрожания.

    zoompan держит положение окна в целых пикселях и округляет его каждый кадр —
    на исходнике в размер кадра это заметное подрагивание. Увеличиваем втрое:
    ошибка округления становится треть пикселя и глазом не читается.
    """
    nf = max(int(L * FPS), 1)
    run(["ffmpeg", "-v", "error", "-framerate", str(FPS), "-loop", "1", "-i", str(img),
         "-frames:v", str(nf),
         "-vf", f"scale={W*3}:{H*3}:flags=lanczos,"
                f"zoompan=z='1+0.05*on/{nf}':d=1:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},setsar=1",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         str(out), "-y"])


def main():
    d = Path(sys.argv[1])
    sp = float(sys.argv[2]) if len(sys.argv) > 2 else 1.15
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    T = d / "_film"; T.mkdir(exist_ok=True)

    # Концовка. Правило Евгения 2026-09-17: ролик не обрывается на последнем слове.
    # Держим последний рисунок, уводим в бумагу, показываем благодарность и призыв.
    # Кадр синтетический: без речи, поэтому ниже сам получает тишину, а музыка
    # продолжает играть (она зациклена) и ролик заканчивается на ней.
    if not any(s.get("kind") == "outro" for s in r):
        last_scene = next((s["id"] for s in reversed(r) if s["kind"] == "scene"), None)
        if last_scene is not None:
            r.append({"id": max(s["id"] for s in r) + 1, "kind": "outro",
                      "bg_id": last_scene, "dur": OUTRO_SEC, "narr": "",
                      "block": "OUTRO", "visual": None, "diagram": None})

    # Заставка занимает место первой паузы: там уже есть дыхание после вступления.
    first_pause = next((x for x in r if x["kind"] == "pause"), None)
    if first_pause is not None and not any(x.get("kind") == "bumper" for x in r):
        first_pause["kind"] = "bumper"; first_pause["dur"] = BUMPER_SEC

    print("речь…", flush=True)
    # Звук блочный: один файл на смысловой блок, у кадра есть смещение внутри него.
    # Длительность кадра берётся ТОЛЬКО из окна ElevenLabs (a_end - a_off) и никогда
    # из dur. Раньше стояло dur + 0.05 «на хвостик», а dur тут же перезаписывался и
    # сохранялся в timed.json — каждая пересборка добавляла ещё 50 мс, и окно
    # залезало в следующий кадр. На четвёртой сборке нахлёст был 0.20 с: столько
    # звучит короткое слово, поэтому оно повторялось на склейке. Окна у voice_blocks
    # и так стыкуются встык, добавлять к ним нечего.
    for s in r:
        if s["kind"] in ("pause", "bumper", "outro") or not s.get("audio"):
            s["adur"] = float(s.get("dur", 0.7))
        else:
            s["adur"] = round(float(s["a_end"]) - float(s["a_off"]), 3)

    t = 0.0
    for s in r:
        s["t_in"] = round(t, 2); s["dur"] = s["adur"]; s["t_out"] = round(t + s["dur"], 2)
        t += s["dur"]
    (d / "timed.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  хронометраж {int(t)//60}:{int(t)%60:02d}", flush=True)

    print("кадры…", flush=True)
    t0 = time.time()
    for n, s in enumerate(r, 1):
        seg = T / f"s{s['id']:04d}.mp4"
        L = s["dur"]
        if seg.exists() and abs(dur(seg) - L) < 0.06:
            continue
        if s["kind"] == "bumper":
            raw = T / f"bump_raw{s['id']:04d}.mp4"
            if not raw.exists() or abs(dur(raw) - L) > 0.08:
                run(["npx", "--no-install", "remotion", "render", "src/index.ts", "Bumper",
                     str(raw), "--props", json.dumps({"seconds": round(L, 2),
                                                      "font": s.get("font") or FONT_DEFAULT,
                                                      "words": BUMPER_WORDS})],
                    cwd=str(MOTION))
            # перекодируем теми же ключами, что и остальные куски: склейка идёт
            # через TS с -c copy, разнобой в профиле h264 её ломает
            run(["ffmpeg", "-v", "error", "-i", str(raw), "-an", "-t", f"{L:.3f}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-r", str(FPS), str(seg), "-y"])
        elif s["kind"] == "pause":
            run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                 f"color=c=0xF2E9D8:s={W}x{H}:r={FPS}", "-t", f"{L:.3f}", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(seg), "-y"])
        elif s["kind"] == "diagram":
            # Схема — НЕ отдельный экран с текстом: она ложится поверх рисунка,
            # иначе рисованный ролик прерывается текстовой заставкой каждые 3 секунды.
            dg = dict(s.get("diagram") or {})
            dg["seconds"] = round(L, 2); dg["transparent"] = True
            dg["font"] = s.get("font") or FONT_DEFAULT
            # Подложка ВСЕГДА. Замер по кадру (needs_plate) отменён 2026-09-17:
            # обводку получал только counter, а у gauge/split/equation/cell текст
            # шёл чистым C.ink и на штриховке пропадал полностью. Рисунок под схемой
            # всегда плотный, ровного фона в этой стилистике не бывает.
            dg["plate"] = True
            dg["outline"] = False
            ov = T / f"o{s['id']:04d}.mov"
            if not ov.exists() or abs(dur(ov) - L) > 0.08:
                run(["npx", "--no-install", "remotion", "render", "src/index.ts", "Diagram",
                     str(ov), "--codec", "prores", "--prores-profile", "4444",
                     "--pixel-format", "yuva444p10le", "--image-format", "png",
                     "--props", json.dumps(dg)], cwd=str(MOTION))
            bgimg = d / "scenes" / f"{s.get('bg_id', s['id']):03d}.jpg"
            bg = T / f"b{s['id']:04d}.mp4"
            if not bg.exists() or abs(dur(bg) - L) > 0.06:
                ken(bgimg, bg, L)
            run(["ffmpeg", "-v", "error", "-i", str(bg), "-i", str(ov), "-filter_complex",
                 f"[1:v]scale={W}:{H}[fg];[0:v][fg]overlay=0:0:format=auto[v]",
                 "-map", "[v]", "-t", f"{L:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "18", "-pix_fmt", "yuv420p", str(seg), "-y"])
        elif s["kind"] == "outro":
            bgimg = d / "scenes" / f"{s['bg_id']:03d}.jpg"
            ov = T / f"o{s['id']:04d}.mov"
            if not ov.exists() or abs(dur(ov) - L) > 0.08:
                run(["npx", "--no-install", "remotion", "render", "src/index.ts", "Outro",
                     str(ov), "--codec", "prores", "--prores-profile", "4444",
                     "--pixel-format", "yuva444p10le", "--image-format", "png",
                     "--props", json.dumps({"seconds": round(L, 2),
                                            "font": s.get("font") or FONT_DEFAULT,
                                            "end": OUTRO_END,
                                            "thanks": OUTRO_THANKS, "cta": OUTRO_CTA})],
                    cwd=str(MOTION))
            bg = T / f"b{s['id']:04d}.mp4"
            if not bg.exists() or abs(dur(bg) - L) > 0.06:
                ken(bgimg, bg, L)
            run(["ffmpeg", "-v", "error", "-i", str(bg), "-i", str(ov), "-filter_complex",
                 f"[1:v]scale={W}:{H}[fg];[0:v][fg]overlay=0:0:format=auto[v]",
                 "-map", "[v]", "-t", f"{L:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "18", "-pix_fmt", "yuv420p", str(seg), "-y"])
        else:
            img = d / "scenes" / f"{s['id']:03d}.jpg"
            if not img.exists():
                print(f"  ! кадр {s['id']}: нет картинки", flush=True)
                run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                     f"color=c=0xF2E9D8:s={W}x{H}:r={FPS}", "-t", f"{L:.3f}", "-c:v", "libx264",
                     "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(seg), "-y"])
                continue
            # лёгкий наезд: рисунок не плывёт, но кадр не мёртвый
            ken(img, seg, L)
        if n % 20 == 0:
            print(f"  {n}/{len(r)}  {int(time.time()-t0)} c", flush=True)

    print("склейка…", flush=True)
    # Через MPEG-TS, а не напрямую по mp4. У сегментов завышена метаданная
    # длительность в контейнере; склейка расставляет их по этим меткам с разрывами,
    # и fps-фильтр забивает разрывы дублями — видео раздувается в 7 раз.
    # В TS длительность считается честно, и перекодировать ничего не нужно.
    tsl = []
    for s in r:
        mp4 = T / f"s{s['id']:04d}.mp4"
        ts = T / f"s{s['id']:04d}.ts"
        if not ts.exists() or ts.stat().st_mtime < mp4.stat().st_mtime:
            run(["ffmpeg", "-v", "error", "-i", str(mp4), "-c", "copy",
                 "-bsf:v", "h264_mp4toannexb", "-f", "mpegts", str(ts), "-y"])
        tsl.append(ts)
    lst = T / "v.txt"
    lst.write_text("\n".join(f"file '{p.resolve()}'" for p in tsl), encoding="utf-8")
    silent = T / "video.mp4"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(silent), "-y"])

    print("звук…", flush=True)
    ap = []
    for s in r:
        w = T / f"w{s['id']:04d}.wav"
        if w.exists() and abs(dur(w) - s["dur"]) > 0.05:
            w.unlink()
        if not w.exists():
            if s.get("audio"):
                # вырезаем окно из блочного файла по таймкодам ElevenLabs
                run(["ffmpeg", "-v", "error", "-ss", f"{s['a_off']:.3f}",
                     "-i", str(d / s["audio"]), "-t", f"{s['dur']:.3f}",
                     "-af", f"apad=whole_dur={s['dur']:.3f}",
                     "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(w), "-y"])
            elif s["kind"] == "bumper" and PENCIL.exists():
                # Карандаш звучит ТОЛЬКО пока идёт письмо: между словами и после
                # подчёркивания — тишина. Иначе шорох тянется по пустому кадру.
                gate = "+".join(f"between(t,{a},{b})" for a, b in PENCIL_WINDOWS)
                run(["ffmpeg", "-v", "error", "-i", str(PENCIL), "-af",
                     f"volume=0.55,volume='{gate}':eval=frame,"
                     f"afade=t=out:st={s['dur']-0.85:.2f}:d=0.12,"
                     f"apad=whole_dur={s['dur']:.3f}",
                     "-t", f"{s['dur']:.3f}", "-ar", "48000", "-ac", "1",
                     "-c:a", "pcm_s16le", str(w), "-y"])
            else:
                run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                     "-t", f"{s['dur']:.3f}", "-ar", "48000", "-ac", "1", str(w), "-y"])
        ap.append(w)
    alist = T / "a.txt"
    alist.write_text("\n".join(f"file '{p.resolve()}'" for p in ap), encoding="utf-8")
    voice = T / "voice.wav"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(alist),
         "-c:a", "pcm_s16le", str(voice), "-y"])

    out = d / f"FILM_{d.name.split('_',1)[-1].replace('-','_')}.mp4"
    music = Path("/mnt/d/youtube/music/explain_upbeat_2.mp3")

    # Музыкальная дорожка строится руками, а не зацикливанием на весь ролик:
    # на заставке музыка должна замолчать полностью, а ПОСЛЕ неё начаться заново
    # с начала трека, а не продолжиться с середины (решение Евгения 2026-09-17).
    bump = next((x for x in r if x.get("kind") == "bumper"), None)
    track = T / "music.wav"
    if music.exists() and bump is not None:
        parts = []
        for i, seclen in enumerate((bump["t_in"], t - bump["t_out"])):
            if seclen <= 0.05:
                continue
            q = T / f"mus{i}.wav"
            run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(music),
                 "-t", f"{seclen:.3f}", "-af",
                 f"afade=t=in:st=0:d=0.8,afade=t=out:st={max(seclen-1.0,0):.2f}:d=1.0",
                 "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(q), "-y"])
            parts.append((i, q))
        gap = T / "mus_gap.wav"
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
             "-t", f"{bump['dur']:.3f}", "-ar", "48000", "-ac", "2",
             "-c:a", "pcm_s16le", str(gap), "-y"])
        order = [q for i, q in parts if i == 0] + [gap] + [q for i, q in parts if i == 1]
        ml = T / "m.txt"
        ml.write_text("\n".join(f"file '{q.resolve()}'" for q in order), encoding="utf-8")
        run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(ml),
             "-c:a", "pcm_s16le", str(track), "-y"])
        music = track
        print(f"  музыка: тишина {bump['t_in']:.1f}-{bump['t_out']:.1f} c, после заставки трек с начала",
              flush=True)

    if music.exists():
        # Музыка — лёгкий фон: тихо и с приглушением под голосом.
        # volume=0.10 это примерно -20 дБ; sidechain убирает её из-под речи.
        # Голос нужен дважды: как сигнал для приглушения музыки и как основная
        # дорожка. Выход фильтра потребляется только один раз, поэтому asplit.
        fc = ("[2:a]volume=0.10,aformat=sample_fmts=fltp:sample_rates=48000:"
              "channel_layouts=stereo[mu];"
              "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
              "asplit=2[vo1][vo2];"
              "[mu][vo1]sidechaincompress=threshold=0.03:ratio=12:attack=15:release=350[md];"
              "[vo2][md]amix=inputs=2:duration=first:weights=1 0.85,"
              "loudnorm=I=-14:TP=-1.5:LRA=11[a]")
        run(["ffmpeg", "-v", "error", "-i", str(silent), "-i", str(voice),
             "-i", str(music),
             "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-ar", "48000", "-ac", "2", "-shortest", str(out), "-y"])
    else:
        run(["ffmpeg", "-v", "error", "-i", str(silent), "-i", str(voice),
             "-filter_complex", "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-ar", "48000", "-ac", "2", "-shortest", str(out), "-y"])
    print(f"готово: {out}  {dur(out)/60:.1f} мин, видео {dur(silent):.1f} c, звук {dur(voice):.1f} c")


if __name__ == "__main__":
    main()
