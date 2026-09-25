#!/usr/bin/env python3
"""Генерация рисованных сцен объясняющего ролика по board.json.

Схемы здесь не трогаем — их рисует Remotion. Стиль берётся из style.txt
папки проекта, он же служит гарантией единообразия всех кадров.
"""
from __future__ import annotations
import argparse, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from pipeline.config import Config
from pipeline.sources import genimage
from pipeline import costs

NEG = (" No text, no letters, no numbers, no labels, no logos, no watermark, "
       "no photo of paper, no desk or table visible. "
       # Люди — часть языка канала, и модель дописывает их в КАЖДЫЙ кадр, даже
       # когда описан голый предмет: часы обрастают толпой, гравюра на стене
       # заменяется сценой на причале. Запрет ставится всегда, а люди приходят
       # из описания кадра, когда они там нужны.
       "Do not add any person who is not described. If the description mentions "
       "no people, the frame is completely empty of people — no figures, no "
       "silhouettes, no hands, no crowd in the background. Draw exactly the "
       "objects described and nothing else.")



def to_archive(dst: Path) -> None:
    """Старый кадр не затираем, а уносим в archive/ (правило Евгения 2026-09-24).

    На ZZZZ Best целая раскадровка была перерисована поверх прежней, и вариант,
    который Евгению нравился, исчез без копии.
    """
    if not dst.exists():
        return
    import datetime
    arc = dst.parent.parent / "archive" / dst.parent.name
    arc.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst.replace(arc / f"{dst.stem}_{stamp}{dst.suffix}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--model", default="gemini-3.1-flash-image")
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--pause", type=float, default=4.0)
    ap.add_argument("--redraw", action="store_true",
                    help="перерисовать указанные в --only поверх существующих")
    a = ap.parse_args()
    d = Path(a.dir)
    style = (d / "style.txt").read_text(encoding="utf-8").strip()
    # timed.json — живой файл: в нём уже прорежены схемы (diagram_trim.py) и
    # проставлены bg_id. board.json — исходная раскадровка, она устаревает.
    src = d / "timed.json" if (d / "timed.json").exists() else d / "board.json"
    shots = json.loads(src.read_text(encoding="utf-8"))
    only = {int(x) for x in a.only.split(",") if x.strip().isdigit()}
    todo = [s for s in shots if s["kind"] == "scene" and (not only or s["id"] in only)]
    out = d / "scenes"; out.mkdir(exist_ok=True)
    cfg = Config()
    spent = {"usd": 0.0, "fail": []}
    t0 = time.time()

    def one(s):
        dst = out / f"{s['id']:03d}.jpg"
        if dst.exists() and not a.redraw:
            return dst
        # Пишем во временный файл и подменяем только после успеха. Старый кадр
        # удалять до генерации нельзя: 2026-09-23 на кончившихся кредитах так
        # разом потерялись девять кадров, восстанавливать их было неоткуда.
        tmp = dst.with_suffix(".new.jpg")
        # преемственность: парный кадр рисуется ОТ соседа по полю ref, иначе
        # «тот же водолаз» каждый раз выходит другим человеком
        refs, cont = None, ""
        ref = s.get("ref")
        if ref:
            # число — соседний кадр ролика; строка — файл в папке проекта
            # (refs/*.jpg): так в кадр заходит настоящая схема или фотография,
            # которую модель по описанию не соберёт — молекула, карта, прибор
            if isinstance(ref, str):
                rp = d / ref
                note = (" Redraw the object shown in the reference image in this drawing "
                        "style — keep its structure and its proportions, change only the "
                        "rendering and the palette.")
            else:
                rp = out / f"{int(ref):03d}.jpg"
                note = (" Keep the same character, the same objects, the same camera angle and the "
                        "same lighting as the reference image — change only what is described.")
            if rp.exists():
                refs = [rp]
                cont = note
        try:
            r = genimage.generate(cfg, style + " " + (s.get("visual") or "") + cont + NEG,
                                  tmp, model=a.model, aspect="16:9", refs=refs)
            spent["usd"] += r.get("usd", 0.0)
            to_archive(dst)          # старый кадр — в archive, и только теперь подмена
            tmp.replace(dst)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            spent["fail"].append(f"{s['id']}: {str(e)[:70]}")
        time.sleep(a.pause)
        return dst

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        done = [f for f in ex.map(one, todo) if f.exists()]
    costs.log(costs.project_of(d), "scenes", a.model, spent["usd"], len(done), "сцен")
    print(f"сцен {len(done)}/{len(todo)}, ${spent['usd']:.2f}, {int(time.time()-t0)} c")
    for f in spent["fail"][:8]:
        print("  !", f)


if __name__ == "__main__":
    main()
