#!/usr/bin/env python3
"""Ведущий: кипящая линия + липсинк по выравниванию ElevenLabs, всё из одного рисунка.

Собирается покадрово в Python, а не в Remotion: нужен mesh-warp, которого в CSS нет.
  - база: утверждённый кадр с сомкнутым ртом;
  - рот: шесть артикуляций, вырезанных из ТОГО ЖЕ кадра (родная борода, единый размер);
  - кипение: микродеформация сетки, новая раз в 2-3 кадра — «на двойках», как в рисованной;
  - дыхание: медленный дрейф масштаба и наклона, чтобы фигура не стояла колом.

  python scripts/host_anim.py <папка> --start 24.2 --dur 5
"""
from __future__ import annotations
import argparse, json, math, random, subprocess, sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.boil import warp   # noqa: E402

FPS = 25
# m0 читается зубами наружу, m5 — оскал; в речи они не нужны
VIS = {"a": 3, "á": 3, "e": 2, "i": 2, "y": 2, "o": 4, "u": 4, "w": 4,
       "m": 1, "b": 1, "p": 1, "f": 2, "v": 2}
REST = 1          # пауза и знаки препинания — сомкнутые губы


def viseme(c: str) -> int:
    ch = c.lower()
    if ch in VIS:
        return VIS[ch]
    return 2 if ch.isalpha() else REST


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--start", type=float, default=24.2)
    ap.add_argument("--dur", type=float, default=5.0)
    ap.add_argument("--amp", type=float, default=2.2)
    ap.add_argument("--hold", type=int, default=3, help="сколько кадров держится один рисунок кипения")
    ap.add_argument("--out", default="host_anim.mp4")
    ap.add_argument("--base", default="host_closed.jpg", help="базовый кадр в anim/")
    ap.add_argument("--visemes", default="", help="папка артикуляций в anim/ (пусто — набор по умолчанию)")
    ap.add_argument("--patch", default="", help="json с прямоугольником накладки в anim/")
    ap.add_argument("--pose-b", default="", help="конечная поза: файл кадра в anim/")
    ap.add_argument("--vis-b", default="visemesB2", help="папка артикуляций конечной позы")
    ap.add_argument("--patch-b", default="poseB2_patch.json")
    ap.add_argument("--switch", type=float, default=0.0, help="секунда начала движения")
    ap.add_argument("--phases", default="", help="промежуточные фазы через запятую, файлы в anim/")
    ap.add_argument("--phase-hold", type=int, default=3, help="кадров на фазу")
    # озвучка теперь блочная: у каждого появления своя дорожка и своё выравнивание
    # фон держим НЕПОДВИЖНЫМ: кипение и дыхание, применённые ко всему кадру,
    # заставляют гулять комнату — на составном фоне с окном это сразу видно
    ap.add_argument("--bg", default="", help="статичный фон")
    ap.add_argument("--figure", default="", help="фигура с альфой, её и оживляем")
    ap.add_argument("--audio", default="voice/hook_a.mp3")
    ap.add_argument("--align", default="voice/hook_a_align.json")
    # выравнивание идёт в шкале ИСХОДНОЙ записи, а дорожка ускорена: если не
    # поделить времена на скорость, марионетка ищет звук не в том месте текста
    # и рисует сомкнутый рот — липсинка нет вообще
    ap.add_argument("--speed", type=float, default=1.0)
    # разбег: сборка центрирует перетекание на стыке, поэтому картинка сегмента
    # ложится на половину перетекания раньше своего звука. Без разбега рот весь
    # кусок идёт впереди голоса — слышно сразу, видно на стоп-кадре
    ap.add_argument("--lead", type=float, default=0.0)
    a = ap.parse_args()
    P = Path(a.dir); A = P / "anim"
    plate = Image.open(P / a.bg).convert("RGB") if a.bg else None
    if a.figure:
        base = Image.open(P / a.figure).convert("RGBA")
    else:
        base = Image.open(A / a.base).convert("RGB")
    W, H = base.size
    if plate is not None:
        plate = plate.resize((W, H))
    vdir = (A / a.visemes) if a.visemes else Path("/home/chak/yt/motion/public/work/visemes")
    vis = [Image.open(vdir / f"v{i}.png").convert("RGBA") for i in range(6)]
    # вторая поза: свой кадр, свои артикуляции и свой прямоугольник накладки
    baseB = visB = pbB = None
    phases = []
    if a.pose_b:
        baseB = Image.open(A / a.pose_b).convert("RGB").resize((W, H))
        visB = [Image.open(A / a.vis_b / f"v{i}.png").convert("RGBA") for i in range(6)]
        pbB = tuple(json.loads((A / a.patch_b).read_text())["patch"])
        phases = [Image.open(A / f.strip()).convert("RGB").resize((W, H))
                  for f in a.phases.split(",") if f.strip()]
    al = json.loads((P / a.align).read_text(encoding="utf-8"))
    ch = al["characters"]
    st = [x / a.speed for x in al["character_start_times_seconds"]]
    en = [x / a.speed for x in al["character_end_times_seconds"]]
    # прямоугольник накладки — тот же, из которого вырезаны рты
    PB = tuple(json.loads((A / a.patch).read_text())["patch"]) if a.patch \
        else (0.400, 0.479, 0.592, 0.672)
    px = (int(PB[0] * W), int(PB[1] * H))
    size = (int((PB[2] - PB[0]) * W), int((PB[3] - PB[1]) * H))

    tmp = A / "_frames"; tmp.mkdir(exist_ok=True)
    for f in tmp.glob("*.jpg"):
        f.unlink()
    n = int((a.dur + a.lead) * FPS)
    for i in range(n):
        t = a.start - a.lead + i / FPS
        idx = REST
        for k, s in enumerate(st):
            if s <= t < en[k]:
                idx = viseme(ch[k]); break
        def compose(bs, vv, pb):
            f = bs.copy()
            p0 = (int(pb[0] * W), int(pb[1] * H))
            sz = (int((pb[2] - pb[0]) * W), int((pb[3] - pb[1]) * H))
            m = vv[idx].resize(sz)
            f.paste(m, p0, m)
            return f
        frame = compose(base, vis, PB)
        if baseB is not None:
            # Движение идёт фазами и РЕЗКИМИ склейками, как в рисованной анимации.
            # Перетекание между позами давало призрак руки: промежуточных фаз у
            # смешивания нет, оно просто показывает два рисунка сразу.
            fi = i - int(a.switch * FPS)
            span = len(phases) * a.phase_hold
            if fi >= span:
                frame = compose(baseB, visB, pbB)
            elif fi >= 0 and phases:
                frame = phases[min(fi // a.phase_hold, len(phases) - 1)].copy()
        # дыхание: медленный наклон и масштаб
        ang = math.sin(t * 0.8) * 0.35
        sc = 1.012 + math.sin(t * 0.55) * 0.006
        frame = frame.rotate(ang, Image.BICUBIC, expand=False)
        nw, nh = int(W * sc), int(H * sc)
        frame = frame.resize((nw, nh), Image.LANCZOS).crop(((nw - W) // 2, (nh - H) // 2,
                                                           (nw - W) // 2 + W, (nh - H) // 2 + H))
        frame = warp(frame, 1000 + i // a.hold, a.amp)
        if plate is not None:
            out = plate.copy()
            out.paste(frame.convert("RGB"), (0, 0), frame.split()[-1])
            frame = out
        frame.convert("RGB").save(tmp / f"f{i:04d}.jpg", quality=93)
    out = A / a.out
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(tmp / "f%04d.jpg"),
                    "-ss", str(a.start), "-t", str(a.dur + a.lead), "-i", str(P / a.audio),
                    "-map", "0:v", "-map", "1:a", "-vf", "scale=1920:1080", "-c:v", "libx264",
                    "-crf", "18", "-pix_fmt", "yuv420p",
                    # моно из ElevenLabs переводим в стерео: часть плееров на моно-AAC молчит
                    # (docs/montage_rules.md) — правило уже стоило одной пересборки
                    # apad: у последней реплики голос кончается раньше слота, и
                    # -shortest резал по нему ВИДЕО — клип выходил короче заказанного
                    "-af", "aformat=channel_layouts=stereo,aresample=48000,"
                           f"adelay={int(a.lead*1000)}:all=1,"
                           f"asetpts=N/SR/TB,apad,atrim=0:{a.dur + a.lead:.3f}",
                    "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000",
                    "-shortest", str(out)], check=True)
    print(f"{out}  {n} кадров, кипение на {a.hold} кадра, амплитуда {a.amp} px")


if __name__ == "__main__":
    main()
