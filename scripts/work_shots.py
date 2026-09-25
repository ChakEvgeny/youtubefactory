#!/usr/bin/env python3
"""Кадры канала Terms of Employment: свой промпт на каждый шот, канон героя
референсом, отсев похожих по pHash, проверка палитры числом.

Библиотеки ассетов у канала нет — каждый кадр рисуется под свой шот
(`channels.work.shots_rule`). Кадр пишется в `.new.jpg` и подменяет старый
только после того, как прошёл проверки: на одной перегенерации кончились
кредиты и девять уже удалённых кадров восстанавливать было неоткуда.

    python scripts/work_shots.py <папка>                 # все недостающие
    python scripts/work_shots.py <папка> --only 90,91    # выборочно
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from pipeline import costs
from pipeline.config import Config
from pipeline.sources import genimage
from pipeline.util import SeenFrames

def to_archive(dst: Path) -> None:
    """Заменяемый кадр уносим в archive/, не затираем (правило Евгения 2026-09-24).

    Вызов стоял в коде, а определения не было: при первой же перерисовке
    существующего кадра падал NameError и кадр терялся вместе с прогоном.
    """
    if not dst.exists():
        return
    import datetime
    arc = dst.parent.parent / "archive" / dst.parent.name
    arc.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst.replace(arc / f"{dst.stem}_{stamp}{dst.suffix}")


def stamp(sh) -> str:
    """отпечаток описания, по которому кадр нарисован: по нему видно, что
    картинка отстала от раскадровки. Без него описание правится, кадр остаётся
    старым, и расхождение вылезает только на просмотре глазами."""
    key = f"{sh.get('kind')}|{sh.get('visual') or ''}|{sh.get('file') or ''}"
    return hashlib.sha1(key.encode()).hexdigest()[:10]


# Разрешение на надпись — по кадру, полем allow_text. Нужно там, где само
# содержание кадра это число: заголовок газеты с «75%» без числа не кадр.
# Везде, где флага нет, запрет остаётся жёстким: модель пишет бессмыслицу.
NEG_TEXT = (" No text, no letters, no numbers, no handwriting, no labels, no signage, no logos, no "
            "watermark — nothing in the frame that resembles writing of any kind. ")
NEG_TEXT_OK = (" The ONLY readable thing anywhere in the frame is the short number named in the "
               "description, printed large and cleanly and spelled exactly as written there. "
               "Every other line of writing — headlines, body text, captions — is drawn as plain "
               "ruled bars with no readable letters at all. No logos, no brand names, no watermark. ")

NEG = (NEG_TEXT +
       # красный на коже читается как порезы и кровь — ловилось на костяшках и ладонях
       "The signal red ink NEVER touches skin: hands, fingers, knuckles, fingernails, faces and "
       "all bare skin are OUTLINED IN DEEP NAVY like every other object and filled with the FLAT "
       "paper tone — no red outlines, no red strokes, marks, dots, nails or shading on skin, and "
       "no red or pink fill anywhere on skin: no blush, no rosy cheeks, no flushed nose or ears, "
       "no warm tint on the face. The face is flat paper colour with navy lines and nothing else. "
       "No photorealism. No neon, no turquoise, no purple, no magenta, no green, no grey, no slate. "
       "Never more than three inks plus the paper. "
       "Every hand in the frame has exactly five fingers: four fingers and one thumb. "
       # Принцип вместо списка запретов: список кончается тем, что модель находит
       # символ, которого в списке нет. Кадр показывает МЕСТО, где норма
       # происходит, а не объясняет норму.
       # «пустая голова у всех, кроме ведущего» стоит в стиле, но не держит:
       # модель дорисовывает людей туда, где их не просили, и с чертами лица
       "Do not add any person who is not described. If the description mentions no people, the "
       "frame is completely empty of people. Any person who is not the presenter has a "
       "COMPLETELY BLANK head: no eyes, no nose, no mouth, no eyebrows, no facial features at "
       "all, not even faint ones, in any angle including profile. "
       "This frame shows the place where the rule happens. It does not explain the rule — the "
       "voice does that. Everything in the frame must be something that could genuinely be in "
       "this room, at this moment, belonging to this person. "
       "NO textbook symbolism of any kind: nothing is present merely to stand for an idea. If a "
       "viewer sitting in that room would ask why the object is there, it does not belong. "
       "The meaning comes from the RELATION between real things — thicker or thinner, earlier or "
       "later, one or many, open or closed, occupied or empty — not from an emblem. "
       "NO landscape, nature or street: no fields, sunsets, horizons, trees, weather, roads, "
       "shopfronts. The world is one office: desks, chairs, corridors, doorways, lifts, meeting "
       "rooms, staff rooms, reception, filing drawers, folders, lanyards, keyboards, screens, "
       "mugs, envelopes, document boxes, coat racks.")
HERO = (" The man in the reference image, and recognisably him: same face, same short red hair swept "
        "back, same heavy rectangular navy glasses with a red temple, same short beard, always a "
        "completely plain SOLID ochre t-shirt with no print, no logo and no marking of any kind. "
        "Draw him in ink, never photograph him. Any hand has exactly five fingers. "
        "He wears the ochre t-shirt DIRECTLY on his body with nothing over it and nothing "
        "under it: no jacket, no blazer, no coat, no cardigan, no overshirt, no collar, no "
        "buttons, no lapels, no second layer of any colour showing at neck, chest or arms. "
        "His eyes are drawn and clearly visible behind the lenses, pupils and irises inked, "
        "looking straight at the viewer — empty or blank lenses are a failure. "
        # кадр потом анимируется марионеткой: рот вырезается прямоугольником и
        # подменяется, поэтому он обязан быть виден целиком и ничем не закрыт
        "His head faces the camera almost straight on, never in profile and never from behind. "
        "His mouth is fully visible, closed, lips together, seen clearly and unobstructed: "
        "nothing crosses the lower half of his face — no hand, no cup, no phone, no microphone, "
        "no object, no other person, no hair. His chin and jaw are inside the frame with room "
        "to spare, and the head is not tilted more than slightly. "
        # рамка кадра ведущего: talking-head, а не персонаж в сцене
        "Camera at eye level, square to him. Framing runs from mid-chest to the top of his head "
        "with air above it, and his head sits in the upper third of the frame. Any desk or "
        "counter is low, no higher than the bottom quarter of the frame. Nothing at all stands "
        "between him and the camera. He is the ONLY person in the frame: no other shoulders, "
        "backs, silhouettes or figures anywhere, in front of him or behind. He sits or stands "
        "straight, shoulders square to camera, leaning no more than ten degrees, looking "
        "straight into the lens, calm, mouth closed. He reads as the author of the channel "
        "talking to camera, not as a character inside a scene. "
        # торчащая ладонь мешает и марионетке, и глазу: рук в кадре с ним нет
        "His hands are NOT raised and NOT visible near his face: either out of frame entirely "
        "or resting flat and low on a surface, below the chest. No pointing, no raised finger, "
        "no open palm toward the camera, no gesture.")
SIZE = {"wide": "wide establishing shot", "medium": "medium shot", "close": "close-up",
        "insert": "insert detail shot", "hero": "medium shot",
        # схема work_board.py: сцена и кадр под фишку рисуются одинаково,
        # крупность задаёт само описание кадра
        "scene": "shot", "chip": "shot"}
PAL = [(0x1B, 0x2A, 0x5E), (0xC8, 0x9A, 0x3C), (0xE4, 0x53, 0x3A), (0xF2, 0xEC, 0xE0)]


def palette_ok(p: Path) -> bool:
    """Палитра — числом, а не на глаз: доля пикселей далеко от четырёх красок
    и доля серого. Серое появляется, когда модель тихо уходит в фотореализм."""
    a = np.asarray(Image.open(p).convert("RGB").resize((240, 135)), dtype=float).reshape(-1, 3)
    best = np.full(len(a), 1e9)
    for c in PAL:
        best = np.minimum(best, np.linalg.norm(a - np.array(c), axis=1))
    hsv = np.array([colorsys.rgb_to_hsv(*(x / 255)) for x in a])
    s, v = hsv[:, 1], hsv[:, 2]
    grey = float(((s < 0.12) & (v > 0.20) & (v < 0.80)).mean())
    return float((best > 95).mean()) <= 0.08 and grey <= 0.07


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--only", default="", help="номера кадров через запятую")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    P = Path(a.dir)
    out = P / "stills"
    out.mkdir(exist_ok=True)
    ch = yaml.safe_load((ROOT / "config" / "channels.yaml").read_text(encoding="utf-8"))["channels"]["work"]
    style = ch["style_prompt"]
    canon = P / "brand" / "canon_host.jpg"

    allsh = json.loads((P / "storyboard.json").read_text(encoding="utf-8"))
    # раскадровка режет предложения, и в кадр попадает обрывок: «is a cover
    # story. That's the shape of it —». По обрывку модель выдумывает картинку,
    # поэтому подаём соседние реплики как контекст.
    ctx = {}
    for i, s in enumerate(allsh):
        before = " ".join((x.get("narr") or "") for x in allsh[max(0, i - 2):i])
        after = " ".join((x.get("narr") or "") for x in allsh[i + 1:i + 2])
        ctx[s["id"]] = (before[-220:], after[:120])
    shots = allsh
    only = {int(x) for x in a.only.split(",") if x.strip().isdigit()}
    if only:
        shots = [s for s in shots if s["id"] in only]
    seen = SeenFrames(P, thr=int(ch.get("gen", {}).get("seen_frames_threshold", 8)))
    cfg = Config()
    spent, bad = [0.0], []

    def one(sh):
        # старый кадр НЕ удаляется: генерация пишет в .new.jpg и подменяет файл
        # только после проверок. Удалять руками до прогона нельзя — на кончившихся
        # кредитах так уже терялись кадры, дважды.
        dst = out / f"s{sh['id']:03d}.jpg"
        if dst.exists() and not only:
            return
        if only and dst.exists() and sh.get("_keep") is None:
            pass                       # перерисовка поверх: подмена в конце, не сейчас
        tmp = dst.with_suffix(".new.jpg")
        hero = sh["kind"] == "hero"
        before, after = ctx.get(sh["id"], ("", ""))
        said = (sh.get("narr") or "").strip()
        if sh.get("kind") == "card" or not sh.get("visual"):
            return                      # карточку рисует Remotion, не модель
        base = (f"{SIZE.get(sh['kind'], 'shot')}: {sh['visual']}."
                f" The narrator is saying over this frame: \"{said}\"."
                + (f" Just before: \"...{before}\"." if before else "")
                + (f" Just after: \"{after}...\"." if after else "")
                + " The line may be a fragment of a longer sentence — use the surrounding"
                  " lines to understand what is actually being discussed, and keep the frame"
                  " in the same visual thread as the neighbouring shots.")
        # img2img: кадр-пара рисуется ОТ соседнего, иначе «та же форма» каждый раз
        # выходит другой формой. Ссылка ставится в поле ref номером шота.
        ref = sh.get("ref")
        refs = [canon] if hero else None
        if ref:
            rp = out / f"s{int(ref):03d}.jpg"
            if rp.exists():
                refs = [rp]
        for attempt in range(3):
            extra = "" if attempt == 0 else " Completely different composition and camera angle."
            if ref and refs:
                extra += (" Keep the same objects, the same layout, the same camera angle and the "
                          "same lighting as the reference image — change only what is described.")
            neg = NEG.replace(NEG_TEXT, NEG_TEXT_OK) if sh.get("allow_text") else NEG
            prompt = f"{style} {base}{HERO if hero else ''}{extra}{neg}"
            try:
                r = genimage.generate(cfg, prompt, tmp, refs=refs)
            except Exception as e:
                bad.append((sh["id"], str(e)[:60]))
                return
            spent[0] += r.get("usd", 0.0)
            if seen.similar(tmp) and attempt < 2:
                tmp.unlink(missing_ok=True)
                continue
            if not palette_ok(tmp) and attempt < 2:
                tmp.unlink(missing_ok=True)
                continue
            if not palette_ok(tmp):
                # третья попытка принимается, но молчать об этом нельзя:
                # так в сборку уехал кадр 93 с серым 8% при пороге 7%
                bad.append((sh["id"], "принят с третьей попытки, палитра не прошла"))
            to_archive(dst)
            tmp.replace(dst)
            seen.add(dst, sh["id"])
            sh["drawn"] = stamp(sh)
            return
        bad.append((sh["id"], "не прошёл 3 попытки"))

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, shots))
    # отпечатки возвращаем в раскадровку: она и есть источник правды
    (P / "storyboard.json").write_text(json.dumps(allsh, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    costs.log("work", "stills", "gemini-3.1-flash-image", spent[0], len(shots), "кадры ролика")
    print(f"готово, ${spent[0]:.2f}")
    for i, e in bad[:10]:
        print("  брак", i, e)


if __name__ == "__main__":
    main()
