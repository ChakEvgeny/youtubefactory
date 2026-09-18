#!/usr/bin/env python3
"""Раскадровка объясняющего ролика.

Три отличия от документального конвейера:
1. Сцены рисует нейросеть, СХЕМЫ рисуем кодом. Проверено на тесте стиля:
   вместо клетки в разрезе модель выдаёт декоративный шар со стрелками.
2. Границы смысловых блоков берутся из заголовков сценария и сохраняются;
   между блоками вставляется короткая пауза (0.7 с), не такая, как в фильмах.
3. Темп бодрый: эти ролики не убаюкивают. Базовая скорость речи 1.15-1.2.
"""
from __future__ import annotations
import argparse, json, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block
from pipeline import costs

MODEL = "claude-opus-5"
WPM = 150.0          # бодрее документалок (там 138)
GAP = 0.7            # пауза между блоками

SYS = """Ты режиссёр раскадровки объясняющего ролика в рисованной стилистике.

Разбей текст на кадры по 3-5 секунд речи (8-13 слов) — ролик бодрый, кадры
короткие. Текст НЕ менять и НЕ сокращать: склейка narr всех кадров должна
дословно давать исходный текст.

Тип кадра:
- "scene" — живая сцена или предмет: человек на плоту, руки с водой, чайка,
  два стакана, море, больничная койка. Это рисует нейросеть, и она это умеет.
- "diagram" — схема поверх рисунка. Рисуем кодом.

  ЖЁСТКАЯ КВОТА: не больше 15% кадров. На ролик из 120 кадров это 15-18 схем,
  не больше. Схема — событие, а не подпись к каждому предложению.

  Ставь diagram, ТОЛЬКО если выполнено всё сразу:
  1) в кадре есть число, и это число — суть кадра, а не упоминание вскользь;
  2) зритель не поймёт масштаб на слух: нужно СРАВНИТЬ две величины,
     показать долю от целого или провести арифметику в несколько строк;
  3) предыдущие три кадра не были diagram.

  Число, названное мимоходом ("три часа", "в 1962 году", "сорок литров"),
  остаётся scene. Диктор его и так произносит — дублировать текстом незачем.
  Сомневаешься — ставь scene.

Для scene: visual — описание для художника на английском, 12-25 слов,
без текста и цифр в кадре.
Для diagram: объект
  {"kind":"gauge|split|equation|cell|counter","title":"...","items":[...]}
  gauge    сравнение столбиками: [{"label","value","max"}]
  split    одна шкала, поделённая на части: [{"label","value"}]
  equation построчная арифметика: ["1200 + 600","= 1800","/ 1200","= 1.5 L"]
  cell     клетка, отдающая воду: ["подпись слева","подпись справа"]
  counter  одно крупное число: ["1.5 L","urine required"]
Подписи короткие, английские, до трёх слов.

Верни ТОЛЬКО JSON: [{"narr","kind","visual","diagram"}]. У scene diagram=null,
у diagram visual=null."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    a = ap.parse_args()
    d = Path(a.dir)
    raw = (d / "script.md").read_text(encoding="utf-8")

    # режем по заголовкам блоков, границы сохраняем
    blocks, name, buf = [], None, []
    for ln in raw.splitlines():
        if ln.startswith("## "):
            if name and buf:
                blocks.append((name, "\n".join(buf)))
            name, buf = ln[3:].split("—")[0].strip(), []
        elif name and ln.strip() and not ln.startswith("---"):
            buf.append(re.sub(r"\*\*(.+?)\*\*", r"\1", ln))
    if name and buf:
        blocks.append((name, "\n".join(buf)))
    print(f"смысловых блоков: {len(blocks)} — " + ", ".join(b[0][:14] for b in blocks))

    client = anthropic.Anthropic()
    budget = {"usd": 0.0}

    def go(txt):
        for _ in range(3):
            with client.messages.stream(model=MODEL, max_tokens=16000, system=SYS,
                                        messages=[{"role": "user", "content": txt}]) as s:
                out = "".join(t for t in s.text_stream); m = s.get_final_message()
            budget["usd"] += claude_cost(MODEL, m.usage)
            try:
                r = parse_json_block(out)
            except Exception:
                continue
            if isinstance(r, list) and r:
                return r
        return []

    with ThreadPoolExecutor(max_workers=3) as ex:
        parts = list(ex.map(lambda b: go(b[1]), blocks))

    shots, t = [], 0.0
    for (bname, _), part in zip(blocks, parts):
        for s in part:
            s["block"] = bname
            shots.append(s)
        # пауза после блока, кроме последнего
        if (bname, _) != blocks[-1]:
            shots.append({"narr": "", "kind": "pause", "visual": None,
                          "diagram": None, "block": bname})

    for i, s in enumerate(shots, 1):
        w = len((s.get("narr") or "").split())
        s["id"] = i; s["words"] = w
        s["dur"] = GAP if s["kind"] == "pause" else round(max(w / WPM * 60, 1.5), 2)
        s["t_in"] = round(t, 2); s["t_out"] = round(t + s["dur"], 2); t += s["dur"]

    (d / "board.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    costs.log(costs.project_of(d), "board", MODEL, budget["usd"], len(shots), "кадров")
    from collections import Counter
    c = Counter(s["kind"] for s in shots)
    print(f"кадров {len(shots)}, хронометраж {int(t)//60}:{int(t)%60:02d}, "
          + ", ".join(f"{k} {v}" for k, v in c.most_common()) + f", ${budget['usd']:.2f}")


if __name__ == "__main__":
    main()
