#!/usr/bin/env python3
"""Шортс из готового фильма Terms of Employment.

Кадры канала горизонтальные, поэтому вертикаль не режется из них кропом — в
9:16 от офисной сцены остаётся середина стола. Вместо этого кадр кладётся во всю
ширину на бумагу канала, сверху строка-зацепка брендовым шрифтом, снизу вшитые
субтитры: шортсы смотрят без звука.

  python scripts/work_short.py <фильм> --start 707.7 --end 738.1 \
      --title "Marry him" --subs subs_en.srt --out shorts/marry.mp4
"""
from __future__ import annotations
import argparse, re, subprocess, tempfile
from pathlib import Path

W, H, FPS = 1080, 1920, 25
PAPER = "0xF2ECE0"
FONTS = Path.home() / ".fonts"


def subs_window(src: Path, start: float, end: float, dst: Path) -> None:
    """Окно субтитров из srt — сразу в ass, со сдвигом к нулю.

    Через `subtitles=...:force_style` не выходит: ffmpeg конвертирует srt в ass
    с заголовком PlayResY: 288, libass считает кегль и отступы в этих координатах
    и растягивает их до 1920 — текст вырастал в 6,7 раза и уезжал за верх кадра.
    Поэтому ass пишется здесь, с разрешением настоящего кадра.
    """
    def ms(t):
        h, m, s = t.split(":"); s, msec = s.split(",")
        return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(msec)
    def fmt(v):
        v = max(v, 0); h, v = divmod(v, 3600000); m, v = divmod(v, 60000); s, msec = divmod(v, 1000)
        return f"{h:d}:{m:02d}:{s:02d}.{msec // 10:02d}"
    ev = []
    for blk in re.split(r"\n\s*\n", src.read_text(encoding="utf-8").strip()):
        lines = blk.strip().split("\n")
        if len(lines) < 3:
            continue
        a, b = [ms(x.strip()) for x in lines[1].split("-->")]
        if b <= start * 1000 or a >= end * 1000:
            continue
        txt = "\\N".join(x.strip() for x in lines[2:])
        ev.append(f"Dialogue: 0,{fmt(a - int(start*1000))},{fmt(b - int(start*1000))},"
                  f"S,,0,0,0,,{txt}")
    # цвет в ass задаётся как &HAABBGGRR: navy #1B2A5E → &H005E2A1B,
    # бумага #F2ECE0 → &H00E0ECF2. Обводка бумагой держит текст читаемым,
    # если реплика заедет на кадр.
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: S,Archivo Black,54,&H005E2A1B,&H005E2A1B,&H00E0ECF2,&H00E0ECF2,0,0,0,0,100,100,0,0,1,5,0,2,90,90,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dst.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("film"); ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--subs", default="")
    a = ap.parse_args()
    dur = a.end - a.start
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # кадр во всю ширину, по центру; сверху и снизу поля бумаги
        # После -ss метки времени у входа остаются исходными, а окно субтитров
        # сдвинуто к нулю — без сброса PTS фильтр ищет реплики на 707-й секунде
        # и не находит ни одной. Молча, без ошибки.
        vf = ["setpts=PTS-STARTPTS", f"scale={W}:-2",
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={PAPER}", f"fps={FPS}"]
        if a.title:
            # каждая строка — свой drawtext: перевод строки внутри text ffmpeg
            # не понимает и печатает буквой «n»
            for k, line in enumerate(a.title.split("|")):
                t = line.strip().replace("'", "").replace(":", "\\:")
                vf.append(f"drawtext=fontfile={FONTS/'SpecialElite-Regular.ttf'}:text='{t}'"
                          f":fontcolor=0x1B2A5E:fontsize=64:x=(w-tw)/2:y={300 + k * 86}")
        if a.subs:
            sw = td / "w.ass"
            subs_window(Path(a.subs), a.start, a.end, sw)
            vf.append(f"ass={sw}:fontsdir={FONTS}")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{a.start:.3f}", "-t", f"{dur:.3f}",
             "-i", a.film, "-vf", ",".join(vf),
             "-af", "asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.5:LRA=11",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             a.out], check=True)
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", a.out], capture_output=True, text=True).stdout.strip()
    print(f"{a.out}  {float(d):.1f} c  {W}x{H}")


if __name__ == "__main__":
    main()
