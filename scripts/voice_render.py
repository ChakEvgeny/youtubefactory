#!/usr/bin/env python3
"""Озвучка всего фильма по timed.json: каждая реплика своим голосом из cast.json.

Длительность кадра после этого берётся из реального звука, а не из оценки
по словам в минуту. Файлы: voice/NNN.mp3.
"""
from __future__ import annotations
import json, re, subprocess, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.config import Config

cfg = Config()
H = {"xi-api-key": cfg.key("ELEVENLABS_API_KEY"), "Content-Type": "application/json"}
MODEL = "eleven_v3"
# voice_settings.speed на eleven_v3 НЕ РАБОТАЕТ: замерено тремя повторами,
# speed=1.0 даёт 217 слов/мин в среднем, speed=0.7 даёт 227 — разницы нет.
# Разброс самой генерации ±16 сл/мин, поэтому перегенерация тоже не лечит.
# Темп правится только растяжением готового звука в build_film.py.


def dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def say(voice_id: str, text: str, out: Path, stab: float, style: float,
        spd: float = 1.0) -> bool:
    # speed задаётся при синтезе, а не растяжением готового звука: пометка
    # [slowly] на короткой однофразовой реплике не держит — замерено, кадр 3
    # Селби с [slowly] всё равно читался 173 слова в минуту при цели 138.
    vs = {"stability": stab, "similarity_boost": 0.8,
          "style": style, "use_speaker_boost": True}
    if abs(spd - 1.0) > 0.01:
        vs["speed"] = round(max(0.7, min(1.2, spd)), 2)
    body = json.dumps({"text": text, "model_id": MODEL, "voice_settings": vs}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}", data=body, headers=H)
            with urllib.request.urlopen(req, timeout=240) as r:
                out.write_bytes(r.read())
            return True
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                time.sleep(5 * (attempt + 1))
                continue
            print(f"  ! {out.stem}: HTTP {e.code} {e.read()[:120]!r}", flush=True)
            return False
        except Exception as e:
            time.sleep(4 * (attempt + 1))
            last = e
    print(f"  ! {out.stem}: не удалось", flush=True)
    return False


def main():
    d = Path(sys.argv[1])
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    cast = json.loads((d / "cast.json").read_text(encoding="utf-8"))
    vdir = d / "voice"
    vdir.mkdir(exist_ok=True)
    only = {int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else []) if x.strip().isdigit()}
    todo = [s for s in r if (s.get("narr") or "").strip() and (not only or s["id"] in only)]
    print(f"реплик {len(todo)}, знаков {sum(len(s['narr']) for s in todo)}")

    def one(s):
        f = vdir / f"{s['id']:03d}.mp3"
        if f.exists() and dur(f) > 0.3:
            return s['id'], dur(f)
        who = s.get("speaker", "narrator")
        v = cast.get(who) or cast["narrator"]
        stab, style = (0.45, 0.45) if who != "narrator" else (0.35, 0.6)
        txt = s.get("narr_tagged") or s["narr"]
        ok = say(v["id"], txt, f, stab, style)
        if not ok:
            return s['id'], 0.0
        return s['id'], dur(f)

    got = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for n, (i, sec) in enumerate(ex.map(one, todo), 1):
            got[i] = sec
            if n % 25 == 0:
                print(f"  … {n}/{len(todo)}", flush=True)

    bad = [i for i, s in got.items() if s <= 0.3]
    if bad:
        print(f"не озвучено: {bad}")
    t = 0.0
    for s in r:
        sec = got.get(s['id'], 0.0) or (dur(vdir / f"{s['id']:03d}.mp3") if (vdir / f"{s['id']:03d}.mp3").exists() else 0.0)
        s['audio'] = f"voice/{s['id']:03d}.mp3" if sec > 0.3 else ""
        s['dur'] = round(max(sec + 0.35, 2.0), 2)      # 0.35 с воздуха после реплики
        s['t_in'] = round(t, 2); s['t_out'] = round(t + s['dur'], 2)
        t += s['dur']
    (d / "timed.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"озвучено {sum(1 for v in got.values() if v>0.3)}/{len(todo)}, "
          f"хронометраж по звуку {int(t)//60}:{int(t)%60:02d}")


if __name__ == "__main__":
    main()
