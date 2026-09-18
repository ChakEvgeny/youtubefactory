#!/usr/bin/env python3
"""Полная сборка фильма: параллакс DepthFlow, карточки Remotion, клипы Veo.

Порядок и правила — docs/montage_rules.md. Тайминги берутся из реального
звука. Кадр перед анимацией показывает ту же картинку, что и клип.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from voice_speed import speed, dur, breathe

FPS, W, H, OV = 24, 1280, 720, 0.6
WPM_CAP = float(os.environ.get("WPM_CAP", 148.0))   # потолок темпа речи, слов в минуту.
# На слух режет не абсолютная скорость, а перепад между соседними кадрами:
# 123 -> 162 -> 169 -> 107 звучит как качели. Потолок сжимает верх и тем
# уменьшает перепад. Замерено на Проспери, кадр 3 (нож и флаг).
MOTION = ROOT / "motion"
ENV = dict(os.environ, LD_LIBRARY_PATH="/home/chak/.local/lib")
FXMAP = {"push": "push", "pull": "pull", "left": "left", "right": "right", "down": "down"}


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(" ".join(map(str, cmd))[:200] + "\n" + r.stderr[-700:])
    return r


def main():
    d = Path(sys.argv[1])
    sp = float(sys.argv[2]) if len(sys.argv) > 2 else 1.3
    # третий аргумент — собрать только первые N кадров (превью)
    lim = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    full = r
    if lim:
        r = r[:lim]
    T = d / "_film"; T.mkdir(exist_ok=True)

    # 1) речь: ускоряем с сохранением пауз, длительности берём из файла
    print("речь…", flush=True)
    for s in r:
        if s.get("tier") == "black":
            s["adur"] = float(s.get("dur", 2.0))      # пауза задана вручную, звука нет
            continue
        a = T / f"a{s['id']:04d}.mp3"
        if s.get("audio"):
            f = 1.0 if s.get("no_speedup") else sp
            # Потолок темпа. Реплики без интонационных пометок модель читает вдвое
            # быстрее остальных: замерено на Проспери, 74-250 слов/мин при цели 138.
            # Правится только растяжением: voice_settings.speed на eleven_v3 не работает.
            words = len(re.sub(r"\[[^\]]*\]", " ",
                               s.get("narr_plain") or s.get("narr") or "").split())
            # Голос НЕ замедляем: растягивание портит тембр. Быстрой реплике
            # добавляем воздух между предложениями — речь цела, средний темп падает,
            # кадр просто держится дольше.
            kf = T / f"a{s['id']:04d}.ckey"
            key = f"{f:.4f}|{WPM_CAP:.0f}"
            if not a.exists() or not kf.exists() or kf.read_text().strip() != key:
                tmp = T / f"t{s['id']:04d}.mp3"
                speed(d / s["audio"], tmp, f)
                if words >= 6 and not s.get("no_speedup"):
                    breathe(tmp, a, words, WPM_CAP)
                else:
                    tmp.replace(a)
                tmp.unlink(missing_ok=True)
                kf.write_text(key, encoding="utf-8")
        s["adur"] = round((dur(a) if a.exists() else 0.0) + 0.35, 2)
    t = 0.0
    for s in r:
        s["t_in"] = round(t, 2); s["dur"] = s["adur"]; s["t_out"] = round(t + s["dur"], 2)
        t += s["dur"]
    if not lim:
        (d / "timed.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  хронометраж {int(t)//60}:{int(t)%60:02d}", flush=True)
    # разброс темпа: без этого замера неровная озвучка ловится только ухом
    import re as _re
    rates = []
    for s in r:
        a = T / f"a{s['id']:04d}.mp3"
        if not a.exists():
            continue
        w = len(_re.sub(r"\[[^\]]*\]", " ", s.get("narr_plain") or s.get("narr") or "").split())
        dd = dur(a)
        if w >= 6 and dd > 0.5:
            rates.append(w / dd * 60)
    if rates:
        rates.sort()
        hi = sum(1 for x in rates if x > WPM_CAP)
        print(f"  темп речи: {rates[0]:.0f}…{rates[-1]:.0f} слов/мин, "
              f"медиана {rates[len(rates)//2]:.0f}, выше потолка {hi}", flush=True)

    # соседей на одной картинке склеиваем в один кадр ДО рендера: перетекание
    # между одинаковыми изображениями читается как скачок камеры назад.
    # Делать это после рендера нельзя — сегмент останется старой длины, и группа
    # обрывается на середине (Проспери: группа из 34 кадров дала 22 с вместо 214).
    rv = []
    for s_ in r:
        if (rv and s_.get("tier") in ("still", "freeze", "overlay")
                and rv[-1].get("tier") in ("still", "freeze", "overlay")
                and rv[-1].get("img_id") == s_.get("img_id")
                and s_.get("transition") == "dissolve"):
            rv[-1]["dur"] = round(rv[-1]["dur"] + s_["dur"], 2)
            rv[-1]["merged_ids"] = rv[-1].get("merged_ids", []) + [s_["id"]]
            continue
        rv.append(dict(s_))
    if len(rv) != len(r):
        print(f"  склеено одинаковых соседей: {len(r) - len(rv)}", flush=True)

    # 2) кадры
    print("кадры…", flush=True)
    t0 = time.time()
    for n, s in enumerate(rv, 1):
        seg = T / f"s{s['id']:04d}.mp4"
        L = s["dur"] + (OV if n < len(r) else 0.0)
        if seg.exists() and abs(dur(seg) - L) < 0.08:
            continue
        tier = s.get("tier")
        if tier == "card":
            lines = [x.strip() for x in (s.get("card_text") or "").split("\n") if x.strip()][:4]
            run(["npx", "--no-install", "remotion", "render", "src/index.ts", "Card", str(seg),
                 "--codec", "h264", "--crf", "17", "--props",
                 json.dumps({"lines": lines or ["—"], "kicker": "", "seconds": round(L, 2)})],
                cwd=str(MOTION))
        elif tier == "anim" and (d / "clips" / f"{s['id']:03d}.mp4").exists():
            clip = d / "clips" / f"{s['id']:03d}.mp4"
            cd = dur(clip) or 4.0
            run(["ffmpeg", "-v", "error", "-i", str(clip), "-an", "-vf",
                 f"setpts={L/cd:.5f}*PTS,scale={W}:{H}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H},fps={FPS}", "-t", f"{L:.3f}", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(seg), "-y"])
        elif tier == "overlay":
            # картинка с проездом + титр Remotion с альфой поверх
            img = d / "storyboard" / f"{s.get('img_id', s['id']):03d}.jpg"
            px = T / f"p{s['id']:04d}.mp4"
            if px.exists() and abs(dur(px) - L) > 0.12:
                px.unlink()
            if not px.exists():
                run([str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/parallax_df.py"),
                     str(img), str(px), "--dur", f"{L:.2f}", "--fps", str(FPS),
                     "--mode", FXMAP.get(s.get("fx", "push"), "push"),
                     "--strength", str(s.get("px_strength", 1.0))], env=ENV)
            ov = T / f"o{s['id']:04d}.mov"
            if not ov.exists() or abs(dur(ov) - L) > 0.12:
                lines = [x.strip() for x in (s.get("overlay_text") or "").split("\n") if x.strip()][:4]
                run(["npx", "--no-install", "remotion", "render", "src/index.ts", "Overlay", str(ov),
                     "--codec", "prores", "--prores-profile", "4444",
                     "--pixel-format", "yuva444p10le", "--image-format", "png",
                     "--props", json.dumps({"lines": lines or ["—"], "kicker": "",
                                            "side": s.get("ov_side", "left"),
                                            "pos": "lower", "seconds": round(L, 2)})],
                    cwd=str(MOTION))
            run(["ffmpeg", "-v", "error", "-i", str(px), "-i", str(ov), "-filter_complex",
                 f"[0:v]scale={W}:{H},fps={FPS}[bg];[1:v]scale={W}:{H}[fg];"
                 f"[bg][fg]overlay=0:0:format=auto[v]", "-map", "[v]", "-t", f"{L:.3f}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-pix_fmt", "yuv420p", str(seg), "-y"])
        elif tier == "black":
            run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                 f"color=c=black:s={W}x{H}:r={FPS}", "-t", f"{L:.3f}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-pix_fmt", "yuv420p", str(seg), "-y"])
        elif tier == "freeze":
            img = d / "storyboard" / f"{s.get('img_id', s['id']):03d}.jpg"
            run(["ffmpeg", "-v", "error", "-loop", "1", "-i", str(img), "-t", f"{L:.3f}",
                 "-vf", f"scale={W}:{H},fps={FPS}", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "18", "-pix_fmt", "yuv420p", str(seg), "-y"])
        else:
            img = d / "storyboard" / f"{s.get('img_id', s['id']):03d}.jpg"
            if not img.exists():
                # картинки нет — не роняем фильм, ставим чёрный кадр и пишем в лог
                print(f"  ! кадр {s['id']}: нет {img.name}, ставлю чёрный", flush=True)
                run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                     f"color=c=black:s={W}x{H}:r={FPS}", "-t", f"{L:.3f}",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                     "-pix_fmt", "yuv420p", str(seg), "-y"])
                continue
            px = T / f"p{s['id']:04d}.mp4"
            key = (f"{FXMAP.get(s.get('fx','push'),'push')}|{s.get('px_strength',1.0):.2f}"
                   f"|{int(bool(s.get('end_neutral')))}|{L:.2f}")
            kf = T / f"p{s['id']:04d}.ckey"
            # кэш проверяем по параметрам, а не только по длине: сила проезда могла
            # измениться при той же длительности, и по длине это не поймать
            if px.exists() and (not kf.exists() or kf.read_text().strip() != key):
                have = dur(px)
                # проезд камеры плавный: если длина изменилась немного, растягиваем
                # готовый файл вместо пересчёта карты глубины — секунды вместо минут
                if have > 0.5 and 0.7 <= L / have <= 1.45:
                    rt = T / f"r{s['id']:04d}.mp4"
                    run(["ffmpeg", "-v", "error", "-i", str(px), "-an", "-vf",
                         f"setpts={L/have:.5f}*PTS,fps={FPS}", "-t", f"{L:.3f}",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                         "-pix_fmt", "yuv420p", str(rt), "-y"])
                    rt.replace(px)
                    kf.write_text(key, encoding="utf-8")
                else:
                    px.unlink()
            if not px.exists():
                cmd = [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/parallax_df.py"),
                       str(img), str(px), "--dur", f"{L:.2f}", "--fps", str(FPS),
                       "--mode", FXMAP.get(s.get("fx", "push"), "push"),
                       "--strength", str(s.get("px_strength", 1.0))]
                if s.get("end_neutral"):
                    cmd.append("--end-neutral")
                run(cmd, env=ENV)
                kf.write_text(key, encoding="utf-8")
            run(["ffmpeg", "-v", "error", "-i", str(px), "-t", f"{L:.3f}", "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                 str(seg), "-y"])
        if n % 20 == 0:
            print(f"  {n}/{len(rv)}  {int(time.time()-t0)} c", flush=True)

    # 3) склейка группами между жёсткими переходами
    print("склейка…", flush=True)

    runs, cur = [], []
    for s in rv:
        if s.get("transition") in ("cut", "dip") and cur:
            runs.append(cur); cur = [s]
        else:
            cur.append(s)
    if cur:
        runs.append(cur)
    parts = []
    for gi, grp in enumerate(runs, 1):
        out = T / f"run{gi:03d}.mp4"
        glen_exp = sum(x["dur"] for x in grp)
        # номер группы в превью и в полном фильме один и тот же, а содержимое разное:
        # без проверки длины полная сборка переиспользует куски превью
        if out.exists() and abs(dur(out) - glen_exp) > 0.15:
            out.unlink()
        if not out.exists():
            segs = [T / f"s{x['id']:04d}.mp4" for x in grp]
            if len(segs) == 1:
                run(["ffmpeg", "-v", "error", "-i", str(segs[0]), "-t", f"{grp[0]['dur']:.3f}",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt",
                     "yuv420p", str(out), "-y"])
            else:
                inputs = []
                for p in segs:
                    inputs += ["-i", str(p)]
                fc = [f"[{i}:v]settb=AVTB,fps={FPS},format=yuv420p,scale={W}:{H},setsar=1[v{i}]"
                      for i in range(len(segs))]
                prev, acc = "v0", 0.0
                for i in range(1, len(segs)):
                    acc += grp[i - 1]["dur"]
                    fc.append(f"[{prev}][v{i}]xfade=transition=fade:duration={OV}:"
                              f"offset={acc:.3f}[x{i}]")
                    prev = f"x{i}"
                glen = sum(x["dur"] for x in grp)   # хвостовой нахлёст последнего кадра лишний
                run(["ffmpeg", "-v", "error", *inputs, "-filter_complex", ";".join(fc),
                     "-map", f"[{prev}]", "-t", f"{glen:.3f}",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                     "-pix_fmt", "yuv420p", "-r", str(FPS), str(out), "-y"])
        parts.append(out)
        if gi % 5 == 0:
            print(f"  группа {gi}/{len(runs)}", flush=True)
    lst = T / "v.txt"
    lst.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    silent = T / "video.mp4"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(silent), "-y"])

    # 4) звук встык и сведение
    print("звук…", flush=True)
    ap = []
    for s in r:
        w = T / f"w{s['id']:04d}.wav"
        src = T / f"a{s['id']:04d}.mp3"
        # длину проверяем: от прошлых сборок остаются куски другой длины,
        # и дорожка молча недосчитывается (Селби: минус 10 с на фильм)
        if w.exists() and abs(dur(w) - s["dur"]) > 0.05:
            w.unlink()
        if not w.exists():
            if src.exists():
                run(["ffmpeg", "-v", "error", "-i", str(src), "-af",
                     f"apad=whole_dur={s['dur']:.3f}", "-t", f"{s['dur']:.3f}",
                     "-ar", "48000", "-ac", "1", str(w), "-y"])
            else:
                run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                     "-t", f"{s['dur']:.3f}", str(w), "-y"])
        ap.append(w)
    alist = T / "a.txt"
    alist.write_text("\n".join(f"file '{p.resolve()}'" for p in ap), encoding="utf-8")
    voice = T / "voice.wav"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(alist),
         "-c:a", "pcm_s16le", str(voice), "-y"])
    tot = dur(voice)
    music = Path("/mnt/d/youtube/music/jlr_neutral.mp3")
    name = d.name.split("_", 1)[-1].replace("-", "_")
    out = d / f"FILM_{name}.mp4"       # имя из папки проекта, а не зашитое
    run(["ffmpeg", "-v", "error", "-i", str(silent), "-i", str(voice),
         "-stream_loop", "-1", "-i", str(music), "-filter_complex",
         f"[2:a]volume=0.14,atrim=0:{tot:.3f},afade=t=in:st=0:d=3,"
         f"afade=t=out:st={max(tot-5,0):.3f}:d=5[m];"
         f"[1:a][m]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400[mx];"
         f"[1:a][mx]amix=inputs=2:duration=first:weights=1 0.9,"
         f"loudnorm=I=-14:TP=-1.5:LRA=11[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         # 48 кГц стерео: ElevenLabs отдаёт моно 96 кГц, такую дорожку
         # часть плееров и браузеров не воспроизводит — звука просто нет
         "-ar", "48000", "-ac", "2",
         "-shortest", str(out), "-y"])
    print(f"готово: {out}  {dur(out)/60:.1f} мин, видео {dur(silent):.1f} c, звук {tot:.1f} c")


if __name__ == "__main__":
    main()
