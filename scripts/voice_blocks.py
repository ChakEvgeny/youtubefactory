#!/usr/bin/env python3
"""Озвучка целыми смысловыми блоками, а не отдельными репликами.

Зачем: при поштучном синтезе модель не помнит предыдущую фразу, интонация
обнуляется каждые три секунды и речь звучит механически. Плюс каждый стык —
это склейка и лишнее поколение кодека.

Здесь блок синтезируется одним файлом, а границы кадров берутся из посимвольных
таймкодов, которые возвращает сам ElevenLabs. Резать звук не нужно вообще.
"""
from __future__ import annotations
import argparse, base64, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from pipeline import costs

MODEL = "eleven_v3"


def say(key, vid, text, out: Path, stab=0.35, style=0.55):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/with-timestamps"
    body = json.dumps({"text": text, "model_id": MODEL,
                       "voice_settings": {"stability": stab, "similarity_boost": 0.8,
                                          "style": style, "use_speaker_boost": True}}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=body,
                    headers={"xi-api-key": key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            out.write_bytes(base64.b64decode(d["audio_base64"]))
            return d.get("alignment") or d.get("normalized_alignment") or {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                time.sleep(6 * (attempt + 1)); continue
            print(f"  ! HTTP {e.code}: {e.read()[:160]!r}", flush=True)
            return None
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="ускорение готового блока; таймкоды делятся на него")
    a = ap.parse_args()
    d = Path(a.dir)
    key = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY")
    cast = json.loads((d / "cast.json").read_text(encoding="utf-8"))
    vid = cast["narrator"]["id"]
    # фильмы держат кадры в timed.json, объяснялки — в board.json (explain_board.py).
    # Дальше по конвейеру все скрипты читают timed.json, поэтому на объяснялке
    # переносим раскадровку в timed.json один раз, здесь.
    src = d / "timed.json"
    if not src.exists():
        board = d / "board.json"
        if not board.exists():
            sys.exit(f"нет ни timed.json, ни board.json в {d}")
        src.write_text(board.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"timed.json создан из board.json ({board.name})")
    shots = json.loads(src.read_text(encoding="utf-8"))
    vdir = d / "voice"; vdir.mkdir(exist_ok=True)

    # группируем кадры по смысловым блокам, паузы в текст не идут
    blocks, cur, name = [], [], None
    for s in shots:
        b = s.get("block") or "—"
        if name is None:
            name = b
        if b != name:
            blocks.append((name, cur)); cur, name = [], b
        cur.append(s)
    if cur:
        blocks.append((name, cur))

    total = 0.0
    for bi, (bname, part) in enumerate(blocks, 1):
        spoken = [s for s in part if (s.get("narr") or "").strip()]
        if not spoken:
            for s in part:
                s["audio"] = ""; s["a_off"] = 0.0
            continue
        raw = vdir / f"block{bi:02d}_raw.mp3"
        f = vdir / f"block{bi:02d}.mp3"
        # склеиваем реплики блока в один текст; помним, сколько символов занял каждый
        pieces, bounds, pos = [], [], 0
        for s in spoken:
            t = (s.get("narr_tagged") or s["narr"]).strip()
            pieces.append(t)
            bounds.append((s, pos, pos + len(t)))
            pos += len(t) + 1            # пробел-разделитель
        text = " ".join(pieces)

        al = None
        if raw.exists() and (vdir / f"block{bi:02d}.json").exists():
            al = json.loads((vdir / f"block{bi:02d}.json").read_text(encoding="utf-8"))
        else:
            al = say(key, vid, text, raw)
            if al:
                (vdir / f"block{bi:02d}.json").write_text(json.dumps(al), encoding="utf-8")
        if not al:
            print(f"  ! блок {bi} ({bname}) не озвучен", flush=True)
            continue

        # ускоряем целым блоком: интонация сохраняется, стыков нет
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(raw), "-af", f"atempo={a.speed}",
                        "-ar", "48000", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
                        str(f), "-y"], check=True)
        st = [x / a.speed for x in al["character_start_times_seconds"]]
        en = [x / a.speed for x in al["character_end_times_seconds"]]
        n = len(st)
        # Режем ВСТЫК: конец кадра = начало следующего. Если брать «от начала до
        # конца реплики», между окнами копится погрешность выравнивания и соседние
        # куски перекрываются — слово звучит дважды.
        starts = [min(max(c0, 0), n - 1) for _, c0, _ in bounds]
        blk_end = en[-1]
        for k, (s, c0, c1) in enumerate(bounds):
            beg = st[starts[k]]
            fin = st[starts[k + 1]] if k + 1 < len(starts) else blk_end
            if fin <= beg:
                fin = min(beg + 0.4, blk_end)
            s["audio"] = f"voice/block{bi:02d}.mp3"
            s["a_off"] = round(beg, 3)
            s["a_end"] = round(fin, 3)
            s["dur"] = round(fin - beg, 2)
        blen = en[-1]
        total += blen
        print(f"  блок {bi:2} {bname[:16]:16} {len(spoken):3} реплик, {blen:6.1f} c", flush=True)

    # паузы между блоками сохраняют свою длительность
    t = 0.0
    for s in shots:
        if s["kind"] == "pause":
            s["dur"] = s.get("dur") or 0.7
            s["audio"] = ""
        s["t_in"] = round(t, 2); s["t_out"] = round(t + s["dur"], 2); t += s["dur"]
    (d / "timed.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    costs.log(costs.project_of(d), "voice", MODEL, 0.0, len(blocks), "блоков")
    print(f"озвучено блоков {len(blocks)}, речь {total:.0f} c, "
          f"с паузами {int(t)//60}:{int(t)%60:02d}")


if __name__ == "__main__":
    main()
