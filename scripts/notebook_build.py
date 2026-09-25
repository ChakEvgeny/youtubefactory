#!/usr/bin/env python3
"""Сборка ролика Survivor's Notebook по timed.json (после voice_blocks.py).

Отличия от explain_build.py:
- Внутри блока кадры перетекают (0.6 с), а не режутся: правило монтажа —
  перетекание по умолчанию. Граница блока — переворот страницы (PageFlip):
  последний рисунок блока открывает первый рисунок следующего, со звуком.
- Инфографика — клочок бумаги (Scrap) прозрачным слоем поверх того же рисунка,
  наезд камеры на нём продолжается без скачка.
- Заставка канала (NotebookIntro) сразу после хука; музыка на ней молчит и
  после неё начинается с начала трека. Финал — светлый трек с момента спасения.
- Аутро — NotebookOutro: последний рисунок перелистывается на «The End».
Склейка, окна звука и наезд — как в explain_build.py (там записано, почему).
"""
from __future__ import annotations
import json, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from voice_speed import dur

FPS, W, H = 24, 1920, 1080
MOTION = ROOT / "motion"
INTRO = Path("/mnt/d/youtube/output/survival/brand_notebook/intro/INTRO_survivors_notebook.mp4")
MUSIC = Path("/mnt/d/youtube/music/notebook_ice.mp3")
MUSIC_END = Path("/mnt/d/youtube/music/notebook_resolve.mp3")
RESOLVE_AT = "On the morning of the seventh of September"   # с этой фразы — светлый трек
XF = 0.6          # перетекание внутри блока, с (docs/montage_rules.md)
ZOOM = 0.05       # наезд за кадр
OUTRO_SEC = 6.0
SCRAP_MIN = 4.5   # клочок короче не прочитать: 25 имён за 2.7 с на «Карлуке» — брак


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(" ".join(map(str, cmd))[:200] + "\n" + r.stderr[-800:])
    return r


def enc(out: Path, L: float | None = None):
    # число кадров задаём жёстко: наложение с -loop даёт лишний кадр на куске
    nf = ["-frames:v", str(int(round(L * FPS)))] if L else []
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-r", str(FPS)] + nf + [str(out), "-y"]


def ken(img: Path, out: Path, L: float, z0: float = 1.0):
    """Наезд без дрожания: исходник втрое крупнее, ошибка округления — треть пикселя."""
    nf = max(int(round(L * FPS)), 1)       # L уже кратна кадру
    run(["ffmpeg", "-v", "error", "-framerate", str(FPS), "-loop", "1", "-i", str(img),
         "-frames:v", str(nf), "-vf",
         f"scale={W*3}:{H*3}:flags=lanczos,"
         f"zoompan=z='{z0}+{ZOOM}*on/{nf}':d=1:"
         f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},setsar=1"] + enc(out))


def remotion(comp: str, out: Path, props: dict, alpha: bool = False):
    extra = (["--codec", "prores", "--prores-profile", "4444", "--pixel-format", "yuva444p10le",
              "--image-format", "png"] if alpha else [])
    run(["npx", "--no-install", "remotion", "render", "src/index.ts", comp, str(out),
         "--props", json.dumps(props), "--log=error"] + extra, cwd=str(MOTION))


def roster_states(r: list, names: list):
    """Список экипажа накапливается: крестики и «?» переходят из клочка в клочок."""
    dead, lost, was = set(), set(), None
    for s in r:
        sc = s.get("scrap") or {}
        if s["kind"] != "scrap" or sc.get("type") != "roster":
            continue
        mark = sc.get("mark") or []
        st = {"names": names, "dead": sorted(dead), "mark": mark,
              "lost": sorted((lost | set(sc.get("lost") or [])) - set(mark)),
              "count": sc.get("count")}
        if was and was != sc.get("count"):
            st["was"] = was
        s["roster"] = st
        dead |= set(mark); lost = (lost | set(sc.get("lost") or [])) - set(mark)
        was = sc.get("count")


# Оформление канала. По умолчанию — Survivor's Notebook; другой канал кладёт
# build.json в папку проекта (The Case Room: NoirCut / Evidence / NoirOutro).
PROFILE = {"intro": str(INTRO), "music": str(MUSIC), "music_end": str(MUSIC_END),
           "resolve_at": RESOLVE_AT, "cut": "PageFlip", "card": "Scrap", "outro": "NotebookOutro",
           "card_direct": False}


def main():
    global INTRO, MUSIC, MUSIC_END, RESOLVE_AT
    d = Path(sys.argv[1])
    prof = dict(PROFILE)
    if (d / "build.json").exists():
        prof.update(json.loads((d / "build.json").read_text(encoding="utf-8")))
    INTRO, MUSIC, MUSIC_END = Path(prof["intro"]), Path(prof["music"]), Path(prof["music_end"])
    RESOLVE_AT = prof["resolve_at"]
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    plan = json.loads((d / "scrap_plan.json").read_text(encoding="utf-8"))
    T = d / "_film"; T.mkdir(exist_ok=True)
    pub = MOTION / "public" / "survival" / "_film" / d.name
    pub.mkdir(parents=True, exist_ok=True)
    for f in (d / "scenes").glob("*.jpg"):
        if not (pub / f.name).exists():
            shutil.copy(f, pub / f.name)
    for f in (d / "maps").glob("*.png"):
        shutil.copy(f, pub / f.name)
    rel = f"survival/_film/{d.name}"
    if plan.get("_roster"):
        roster_states(r, plan["_roster"])

    if not any(s["kind"] == "outro" for s in r):
        r.append({"id": max(s["id"] for s in r) + 1, "kind": "outro", "narr": "",
                  "block": "OUTRO", "dur": OUTRO_SEC})

    # длительность — только из окна ElevenLabs
    for s in r:
        if s.get("audio"):
            s["dur"] = round(float(s["a_end"]) - float(s["a_off"]), 3)
            if s["kind"] == "scrap":
                # короткая фраза — клочок держится дольше, после фразы тишина
                s["dur"] = max(s["dur"], SCRAP_MIN)
        elif s["kind"] == "intro":
            s["dur"] = round(dur(INTRO), 3)
    t = 0.0
    for s in r:
        s["t_in"] = round(t, 3); s["t_out"] = round(t + s["dur"], 3)
        # Кадры куска считаем от ОБЩЕЙ шкалы: округляем границы, а не длину.
        # Иначе 147 округлений по ±1/48 с копятся — на «Карлуке» картинка к концу
        # отставала от голоса на 1.9 с. Звук режется точно, видео — «vl».
        s["nf"] = round((t + s["dur"]) * FPS) - round(t * FPS)
        s["vl"] = s["nf"] / FPS
        t += s["dur"]
    (d / "timed.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"хронометраж {int(t)//60}:{int(t)%60:02d}, кадров {len(r)}", flush=True)

    # какой рисунок под каждым кадром и с какого масштаба идёт наезд
    img_of, zend = {}, {}
    last_img, last_z = None, 1.0
    for s in r:
        if s["kind"] == "scene":
            last_img, last_z = s["id"], 1.0
            img_of[s["id"]] = s["id"]; zend[s["id"]] = 1.0 + ZOOM
        elif s["kind"] == "scrap":
            # клочок в самом начале ролика: подложить нечего — берём следующий рисунок
            img_of[s["id"]] = last_img if last_img is not None else next(
                x["id"] for x in r if x["kind"] == "scene"); s["z0"] = last_z + ZOOM if last_z == 1.0 else last_z
            zend[s["id"]] = s["z0"] + ZOOM * 0.6
        last_z = zend.get(s["id"], last_z)
        s["_prev_img"], s["_prev_z"] = last_img, last_z

    print("кадры…", flush=True)
    t0 = time.time()
    for n, s in enumerate(r):
        seg = T / f"s{s['id']:04d}.mp4"
        L = s["vl"]
        if seg.exists() and abs(dur(seg) - L) < 0.01:
            continue
        k = s["kind"]
        if k == "scene":
            img = d / "scenes" / f"{s['id']:03d}.jpg"
            prev = r[n - 1] if n else None
            if prev is not None and prev["kind"] in ("scene", "scrap") and L > XF + 0.3:
                # перетекание: последний кадр предыдущего куска гаснет поверх нового
                raw = T / f"k{s['id']:04d}.mp4"
                ken(img, raw, L)
                last = T / f"l{prev['id']:04d}.png"
                run(["ffmpeg", "-v", "error", "-sseof", "-0.05", "-i", str(T / f"s{prev['id']:04d}.mp4"),
                     "-frames:v", "1", str(last), "-y"])
                run(["ffmpeg", "-v", "error", "-i", str(raw), "-loop", "1", "-t", f"{L:.3f}",
                     "-i", str(last), "-filter_complex",
                     f"[1:v]format=rgba,fade=t=out:st=0:d={XF}:alpha=1[p];[0:v][p]overlay=0:0[v]",
                     "-map", "[v]", "-t", f"{L:.3f}"] + enc(seg, L))
            else:
                ken(img, seg, L)
        elif k == "scrap":
            sc = dict(s.get("scrap") or {})
            props = {"seconds": round(L, 2), "transparent": True,
                     "side": "left" if s["id"] % 2 else "right"}
            typ = sc.get("type")
            if prof["card_direct"]:
                props.update(sc)            # Evidence понимает описание улики как есть
            elif typ == "roster":
                props.update(type="roster", roster=s["roster"])
            elif typ == "map":
                name = sc.get("route") or "map"   # файл maps/<route>.png ролика
                props.update(type="image", src=f"{rel}/{name}.png", note=sc.get("note", ""))
            elif typ == "letter":
                # подпись берём из плана: раньше тут была зашита подпись «Карлука»,
                # и она уехала на карточку Бейли
                props.update(type="letter", text=sc["text"], note=sc.get("note", ""))
            elif typ == "compare":
                props.update(type="compare", items=sc["items"], note=(sc.get("note") or "").upper())
            else:
                props.update(type="date", big=sc.get("big"), small=(sc.get("small") or "").upper())
            ov = T / f"o{s['id']:04d}.mov"
            remotion(prof["card"], ov, props, alpha=True)
            bg = T / f"b{s['id']:04d}.mp4"
            ken(d / "scenes" / f"{img_of[s['id']]:03d}.jpg", bg, L, z0=s["z0"])
            run(["ffmpeg", "-v", "error", "-i", str(bg), "-i", str(ov), "-filter_complex",
                 "[0:v][1:v]overlay=0:0:format=auto[v]", "-map", "[v]", "-t", f"{L:.3f}"] + enc(seg, L))
        elif k == "flip":
            nxt = next(x for x in r[n + 1:] if x["kind"] == "scene")
            raw = T / f"f{s['id']:04d}.mp4"
            remotion(prof["cut"], raw, {"from": f"{rel}/{s['_prev_img']:03d}.jpg",
                                        "to": f"{rel}/{nxt['id']:03d}.jpg",
                                        "zoom": round(s["_prev_z"], 3), "seconds": L})
            run(["ffmpeg", "-v", "error", "-i", str(raw), "-an", "-t", f"{L:.3f}"] + enc(seg, L))
        elif k == "intro":
            run(["ffmpeg", "-v", "error", "-i", str(INTRO), "-an", "-t", f"{L:.3f}"] + enc(seg, L))
        elif k == "outro":
            raw = T / f"f{s['id']:04d}.mp4"
            remotion(prof["outro"], raw, {"last": f"{rel}/{s['_prev_img']:03d}.jpg",
                                             "zoom": round(s["_prev_z"], 3), "seconds": L})
            run(["ffmpeg", "-v", "error", "-i", str(raw), "-an", "-t", f"{L:.3f}"] + enc(seg, L))
        if (n + 1) % 20 == 0:
            print(f"  {n+1}/{len(r)}  {int(time.time()-t0)} c", flush=True)

    print("склейка…", flush=True)
    tsl = []
    for s in r:
        mp4, ts = T / f"s{s['id']:04d}.mp4", T / f"s{s['id']:04d}.ts"
        if not ts.exists() or ts.stat().st_mtime < mp4.stat().st_mtime:
            run(["ffmpeg", "-v", "error", "-i", str(mp4), "-c", "copy",
                 "-bsf:v", "h264_mp4toannexb", "-f", "mpegts", str(ts), "-y"])
        tsl.append(ts)
    (T / "v.txt").write_text("\n".join(f"file '{p.resolve()}'" for p in tsl), encoding="utf-8")
    silent = T / "video.mp4"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(T / "v.txt"),
         "-c", "copy", str(silent), "-y"])

    print("звук…", flush=True)
    ap = []
    for s in r:
        w = T / f"w{s['id']:04d}.wav"
        if w.exists() and abs(dur(w) - s["dur"]) > 0.05:
            w.unlink()
        if not w.exists():
            if s.get("audio"):
                # режем строго по окну фразы, до длины кадра — тишина: у удлинённого
                # клочка иначе в паузу попадёт начало следующей фразы
                win = float(s["a_end"]) - float(s["a_off"])
                # -t ДО -i: ограничиваем вход (фразу), а не выход — иначе тишина
                # добивки тут же обрезается и звук уезжает от картинки
                run(["ffmpeg", "-v", "error", "-ss", f"{s['a_off']:.3f}", "-t", f"{win:.3f}",
                     "-i", str(d / s["audio"]), "-af", f"apad=whole_dur={s['dur']:.3f}",
                     "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(w), "-y"])
            elif s["kind"] in ("flip", "outro", "intro"):
                # звук страницы берём из самого рендера
                src = INTRO if s["kind"] == "intro" else T / f"f{s['id']:04d}.mp4"
                run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-t", f"{s['dur']:.3f}",
                     "-af", f"apad=whole_dur={s['dur']:.3f}", "-ar", "48000", "-ac", "1",
                     "-c:a", "pcm_s16le", str(w), "-y"])
            else:
                run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                     "-t", f"{s['dur']:.3f}", "-c:a", "pcm_s16le", str(w), "-y"])
        ap.append(w)
    (T / "a.txt").write_text("\n".join(f"file '{p.resolve()}'" for p in ap), encoding="utf-8")
    voice = T / "voice.wav"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(T / "a.txt"),
         "-c:a", "pcm_s16le", str(voice), "-y"])

    # музыка: трек до заставки, тишина на заставке, трек с начала после неё,
    # со спасения — светлый трек, в самом конце затухание
    intro = next(x for x in r if x["kind"] == "intro")
    res = next((x for x in r if (x.get("narr") or "").startswith(RESOLVE_AT)), None)
    t_res = res["t_in"] if res else t
    parts = []

    def piece(src: Path, L: float, name: str, fin=0.8, fout=1.5):
        q = T / name
        run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{L:.3f}",
             "-af", f"afade=t=in:st=0:d={fin},afade=t=out:st={max(L-fout,0):.2f}:d={fout}",
             "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(q), "-y"])
        return q
    parts.append(piece(MUSIC, intro["t_in"], "mA.wav"))
    gap = T / "mG.wav"
    run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", f"{intro['dur']:.3f}", "-c:a", "pcm_s16le", str(gap), "-y"])
    parts.append(gap)
    parts.append(piece(MUSIC, t_res - intro["t_out"], "mB.wav", fout=2.5))
    parts.append(piece(MUSIC_END, t - t_res, "mC.wav", fin=2.5, fout=4.0))
    (T / "m.txt").write_text("\n".join(f"file '{q.resolve()}'" for q in parts), encoding="utf-8")
    track = T / "music.wav"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(T / "m.txt"),
         "-c:a", "pcm_s16le", str(track), "-y"])

    out = d / f"FILM_{d.name.split('_', 1)[-1].replace('-', '_')}.mp4"
    fc = ("[2:a]volume=0.12,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[mu];"
          "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asplit=2[vo1][vo2];"
          "[mu][vo1]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=400[md];"
          "[vo2][md]amix=inputs=2:duration=first:weights=1 0.85,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    run(["ffmpeg", "-v", "error", "-i", str(silent), "-i", str(voice), "-i", str(track),
         "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", str(out), "-y"])
    print(f"готово: {out}  {dur(out)/60:.1f} мин (видео {dur(silent):.1f} c, звук {dur(voice):.1f} c)")


if __name__ == "__main__":
    main()
