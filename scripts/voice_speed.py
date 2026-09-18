#!/usr/bin/env python3
"""Ускорение речи с сохранением пауз.

Обычный atempo сжимает и речь, и паузы, из-за чего интонационные остановки
пропадают. Здесь паузы вырезаются, ускоряется только речь, паузы возвращаются
исходной длины.
"""
from __future__ import annotations
import re, shutil, subprocess, sys, tempfile
from pathlib import Path


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(" ".join(map(str, cmd))[:160] + "\n" + r.stderr[-400:])
    return r


def dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def silences(p: Path, thresh="-38dB", minlen=0.22):
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(p), "-af",
                        f"silencedetect=noise={thresh}:d={minlen}", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(starts, ends + [dur(p)] * (len(starts) - len(ends))))


def stretch(factor: float) -> str:
    """Фильтр растяжения. atempo годится для мелких правок, на сильных коэффициентах
    мылит голос. rubberband сохраняет форманты и держит до 0.6 без артефактов."""
    # ВСЕ реплики через один фильтр, даже при коэффициенте 1.0. Если часть реплик
    # обработана, а часть нет, тембр гуляет на стыках и дорожка звучит нарезкой:
    # на Проспери 3 растянутых из 18 давали слышимые швы.
    return f"rubberband=tempo={max(0.5, min(2.0, factor))}:pitchq=quality"


def speed(src: Path, out: Path, factor: float = 1.3, keep_pauses: bool = True):
    # Коэффициент 1.0 — копируем как есть. Прогон через rubberband при tempo=1.0
    # не бесплатен: он всё равно раскладывает и пересобирает сигнал и портит звук.
    # На Селби так были испорчены 147 реплик из 229 без всякой нужды.
    if abs(factor - 1.0) < 0.005:
        shutil.copyfile(src, out)
        return out
    total = dur(src)
    if not keep_pauses:
        run(["ffmpeg", "-v", "error", "-i", str(src), "-filter:a", stretch(factor),
             str(out), "-y"])
        return out
    sil = [(a, b) for a, b in silences(src) if b - a >= 0.22 and a > 0.05 and b < total - 0.05]
    if not sil:
        run(["ffmpeg", "-v", "error", "-i", str(src), "-filter:a", stretch(factor),
             str(out), "-y"])
        return out
    tmp = Path(tempfile.mkdtemp())
    parts, t, i = [], 0.0, 0
    for a, b in sil:
        if a - t > 0.05:                                    # кусок речи — ускоряем
            f = tmp / f"s{i:03d}.wav"; i += 1
            run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-to", f"{a:.3f}", "-i", str(src),
                 "-filter:a", stretch(factor), "-ar", "48000", "-ac", "1", str(f), "-y"])
            parts.append(f)
        f = tmp / f"p{i:03d}.wav"; i += 1                    # пауза — как была
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
             "-t", f"{b - a:.3f}", str(f), "-y"])
        parts.append(f)
        t = b
    if total - t > 0.05:
        f = tmp / f"s{i:03d}.wav"
        run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src),
             "-filter:a", stretch(factor), "-ar", "48000", "-ac", "1", str(f), "-y"])
        parts.append(f)
    lst = tmp / "l.txt"
    lst.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(out), "-y"])
    for p in parts:
        p.unlink()
    lst.unlink(); tmp.rmdir()
    return out


if __name__ == "__main__":
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    f = float(sys.argv[3]) if len(sys.argv) > 3 else 1.3
    speed(src, out, f)
    print(f"{dur(src):.2f} -> {dur(out):.2f} с (ускорение {f}, паузы сохранены)")

def breathe(src: Path, out: Path, words: int, target_wpm: float = 150.0,
            max_add: float = 3.0) -> float:
    """Дать реплике воздуха вместо растягивания голоса.

    Быструю реплику нельзя замедлить, не испортив тембр. Но можно удлинить
    ПАУЗЫ между предложениями: речь остаётся нетронутой, а средний темп по
    кадру падает и тараторенье пропадает. Возвращает новую длительность.
    """
    total = dur(src)
    if words < 5 or total <= 0.3:
        shutil.copyfile(src, out); return total
    need = words / target_wpm * 60.0
    extra = min(need - total, max_add)
    if extra <= 0.12:
        shutil.copyfile(src, out); return total
    gaps = [(a, b) for a, b in silences(src)
            if b - a >= 0.14 and a > 0.25 and b < total - 0.15]
    tmp = Path(tempfile.mkdtemp())
    parts, t = [], 0.0
    if gaps:
        per = extra / len(gaps)
        for i, (a, b) in enumerate(gaps):
            seg = tmp / f"s{i}.wav"
            run(["ffmpeg", "-v", "error", "-i", str(src), "-ss", f"{t:.3f}",
                 "-to", f"{b:.3f}", "-ar", "48000", "-ac", "1", str(seg), "-y"])
            pad = tmp / f"p{i}.wav"
            run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                 "-t", f"{per:.3f}", str(pad), "-y"])
            parts += [seg, pad]; t = b
    tail = tmp / "tail.wav"
    run(["ffmpeg", "-v", "error", "-i", str(src), "-ss", f"{t:.3f}",
         "-ar", "48000", "-ac", "1", str(tail), "-y"])
    parts.append(tail)
    if not gaps:
        # пауз внутри нет — добавляем воздух в конец, кадр просто подержится дольше
        pad = tmp / "pend.wav"
        run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
             "-t", f"{extra:.3f}", str(pad), "-y"])
        parts.append(pad)
    lst = tmp / "l.txt"
    lst.write_text("\n".join(f"file '{x.resolve()}'" for x in parts), encoding="utf-8")
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(out), "-y"])
    return dur(out)
