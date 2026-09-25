#!/usr/bin/env python3
"""Находит кадры-метафоры и пейзажи и переписывает их описания на предметные.

Запрет метафор появился в правилах позже, чем была нарисована большая часть
ролика, и в раскадровке у старых кадров метафора записана прямо в `visual` —
«перетягивание каната», «мешок через горы». Перерисовать мало: генератор
послушно повторит описание. Поэтому сначала vision помечает такие кадры, потом
Opus переписывает описание по правилам канала, и только потом кадр рисуется.

    python scripts/work_fixvis.py <папка> --ids 959,960,961
    python scripts/work_fixvis.py <папка> --scan 959,960,961   # только поиск
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
import anthropic  # noqa: E402

MODEL = "claude-opus-5"

SCAN = ("Ты технический контролёр кадров рисованного ролика о трудовом праве. "
        "Мир этого канала — офис: столы, стулья, коридоры, двери, лифты, переговорные, "
        "картотеки, папки, бейджи, конверты, кружки, парковки.\n"
        "Ответь ТОЛЬКО JSON: {\"metaphor\": bool, \"outdoors\": bool, \"off_topic\": bool, "
        "\"why\": \"до 90 символов\"}\n"
        "metaphor — в кадре буквально нарисован оборот речи: перетягивание каната, мешок на "
        "плечах, щит, весы правосудия, канатоходец, лестница, лампочка, клетка, цепь, горы, "
        "обрыв, страховочная сетка, песочные часы, развилка, кража предмета.\n"
        "outdoors — кадр происходит на природе или на улице вне офисного мира: поле, лес, "
        "закат, горизонт, скалы, побережье, деревня.\n"
        "off_topic — кадр ПРОТИВОРЕЧИТ реплике или уводит зрителя в другую тему. "
        "Внимание: на отвлечённой юридической реплике кадр НАМЕРЕННО показывает обычный "
        "предмет из мира работы и не обязан объяснять норму — мысль несёт голос. Такой "
        "кадр не off_topic. Ставь off_topic только если картинка сбивает с толку.")

REWRITE = ("Ты режиссёр раскадровки рисованного ролика о трудовом праве, от первого лица "
           "бывшего рекрутера. Тебе дают реплику диктора и негодное описание кадра.\n"
           "Напиши НОВОЕ описание кадра для художника, по-английски, 12–25 слов.\n"
           "ЖЁСТКО: никакой метафоры буквально — ни каната, ни мешка, ни щита, ни весов, ни "
           "гор, ни обрыва, ни песочных часов, ни лестницы, ни лампочки. Никакой природы и "
           "улицы вне офисного мира. Никакого текста, букв, цифр, вывесок в кадре. "
           "Берётся обычный предмет или помещение, где это правило проживается на практике: "
           "стол, стул, дверь, коридор, лифт, переговорная, картотека, папка, бейдж, конверт, "
           "кружка, парковка. Кадр должен передавать МЫСЛЬ реплики, а не её слово.\n"
           "Верни ТОЛЬКО JSON: {\"visual\": \"...\"}")


def ask(cl, system, content, retries=3):
    for _ in range(retries):
        try:
            r = cl.messages.create(model=MODEL, max_tokens=1500, system=system,
                                   messages=[{"role": "user", "content": content}])
            txt = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
            return json.loads(re.search(r"\{.*?\}", txt, re.S).group(0))
        except Exception:
            continue
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--ids", default="", help="проверить и переписать эти кадры")
    ap.add_argument("--scan", default="", help="только проверить, ничего не менять")
    a = ap.parse_args()

    P = Path(a.dir)
    sb = json.loads((P / "storyboard.json").read_text(encoding="utf-8"))
    want = {int(x) for x in (a.ids or a.scan).split(",") if x.strip().isdigit()}
    shots = [s for s in sb if s["id"] in want]
    cl = anthropic.Anthropic()

    def scan(sh):
        f = P / (sh.get("file") or f"stills/s{sh['id']:03d}.jpg")
        if not f.exists():
            return None
        j = ask(cl, SCAN, [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(f.read_bytes()).decode()}},
            {"type": "text", "text": f"Реплика поверх кадра: «{sh.get('narr') or '—'}»"}])
        if not j:
            return None
        if j.get("metaphor") or j.get("outdoors") or j.get("off_topic"):
            tags = [k for k in ("metaphor", "outdoors", "off_topic") if j.get(k)]
            return (sh["id"], ",".join(tags), (j.get("why") or "")[:80])
        return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        bad = [r for r in ex.map(scan, shots) if r]
    bad.sort()
    print(f"проверено {len(shots)}, негодных {len(bad)}")
    for i, tags, why in bad:
        print(f"  {i:>4}  {tags:<28} {why}")
    if a.scan or not bad:
        Path("/tmp/fixvis.txt").write_text(",".join(str(i) for i, _, _ in bad))
        return

    by = {s["id"]: s for s in sb}

    def rewrite(row):
        sh = by[row[0]]
        j = ask(cl, REWRITE, f"Реплика: «{sh.get('narr')}»\nНегодное описание: {sh.get('visual')}")
        if j and j.get("visual"):
            sh["visual"] = j["visual"]
            return sh["id"]
        return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        done = [r for r in ex.map(rewrite, bad) if r]
    (P / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    Path("/tmp/fixvis.txt").write_text(",".join(map(str, done)))
    print(f"описаний переписано: {len(done)} -> /tmp/fixvis.txt")


if __name__ == "__main__":
    main()
