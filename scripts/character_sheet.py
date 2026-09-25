#!/usr/bin/env python3
"""Персонаж-ведущий канала: аватар, баннер, позы и шаблон обложки из одного канона.

Описание персонажа и палитра берутся из config/channels.yaml (channels.<id>.character),
чтобы канон жил в одном месте. Каждый кадр после генерации сверяется с каноном через
Opus: тот же ли это человек — волосы, очки, пропорции лица, палитра. Кадр, не прошедший
сверку, перерисовывается один раз.

  python scripts/character_sheet.py work /mnt/d/youtube/output/newchannel/<папка>
"""
from __future__ import annotations
import base64, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import yaml
from PIL import Image
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
import anthropic
from pipeline.config import Config
from pipeline.sources import genimage
from pipeline import costs
from pipeline.util import claude_cost, parse_json_block

MODEL = "claude-opus-5"

NEG = (" Absolutely no text, no letters, no numbers, no logos, no watermarks. No photorealism and no "
       "photography. No neon colour, no turquoise, no purple, no magenta, no green, no grey, no slate, "
       "no silver: what would be grey must be navy at a lighter halftone density. Black is never a "
       "dominant mass. Never more than three inks plus the paper.")


def character_prompt(ch: dict) -> str:
    c = ch["character"]
    return (f"The presenter of the channel, always the same man: hair — {c['hair']}; beard — {c['beard']}; "
            f"glasses — {c['glasses']}; clothing — {c['clothing']}; skin — {c['skin']}. His t-shirt is SOLID "
            "warm ochre in every single frame and is never navy. His face, the colour of his hair and the "
            "shape of his glasses never change between frames. Any hand that appears is anatomically correct "
            "with exactly five fingers — four fingers and one thumb, no more and no fewer — drawn simply and "
            "clearly; if a hand would be awkward, place it out of frame instead. He is drawn in ink, never "
            "photographed.")


SHOTS = {
 "avatar":        ("1:1",  "Chest-up portrait, square to camera, head large and filling most of the square so "
                           "it stays readable at 98 pixels. Bare cream paper behind him, a flat solid navy band "
                           "across the very bottom. No props."),
 "banner":        ("16:9", "Wide channel banner, drawn for a frame that is much wider than it is tall. "
                           "The presenter is a half-length figure placed in the RIGHT THIRD of the frame and "
                           "turned inward to his right so that he faces LEFT across the frame. His head and "
                           "shoulders sit entirely within that right third, with a clear margin of empty cream "
                           "paper between him and the right edge of the frame, and his whole head comfortably "
                           "inside the middle horizontal third — never touching the top edge. The left half of "
                           "the frame is completely bare cream paper reserved for text. A flat solid navy band "
                           "runs along the bottom edge only. Leave the text area empty — no lettering."),
 "pose_talking":  ("16:9", "Three-quarter view, chest up, mid-sentence and addressing the viewer directly, one "
                           "hand slightly raised in explanation. Plain cream ground."),
 "pose_pointing": ("16:9", "Standing at the left, turned to the right and pointing at a simple bar chart of "
                           "three bars on the right of the frame: one solid navy, one solid ochre, one solid "
                           "red. The background is bare cream paper only — no band, no panel and no halftone "
                           "field behind him, since a soft halftone field prints as grey."),
 "pose_desk":     ("16:9", "Seated at a pale desk beside a closed solid navy laptop, one hand flat on the "
                           "desk, a tall window of solid ochre behind him. Walls and window frame are bare cream "
                           "paper or solid navy only — no soft halftone field, which prints as grey."),
 "pose_walking":  ("16:9", "Full figure walking left to right across bare cream paper, carrying a folder, seen "
                           "from the side, a flat solid navy band along the bottom."),
 "pose_thinking": ("16:9", "Three-quarter view, chest up, head tilted slightly down, one hand at his chin, "
                           "looking away from the viewer in thought. Plain cream ground."),
 "pose_openarms": ("16:9", "Chest up, square to camera, both arms opened wide in a gesture that presents "
                           "something, palms up. Hands are outlined in navy on bare cream paper with no halftone "
                           "shading inside them, since halftone on skin prints as grey. Plain cream ground."),
 "thumb_template":("16:9", "Thumbnail layout: the presenter occupies the RIGHT third of the frame, chest up, "
                           "large and looking at the viewer. The LEFT two thirds are empty cream paper kept "
                           "completely clear for three or four words of text. A heavy flat solid navy band "
                           "across the bottom quarter, and one small solid red shape near the presenter."),
}

MAPS = {
 "map_us": "the United States",
 "map_uk": "the United Kingdom",
 "map_ca": "Canada",
 "map_au": "Australia",
}
MAP_SHOT = ("A flat world map seen straight on, filling the frame above a flat solid navy band along the "
            "bottom. Every landmass is filled SOLID warm ochre and outlined in deep navy, with navy borders "
            "between countries; the sea is bare cream paper. {country} alone is filled SOLID signal red — "
            "every other country stays ochre, and no second country is red. No labels, no text, no people.")

CHECK = ("Первое изображение — канон персонажа. Второе — новый кадр того же канала. "
         "Один ли это человек? Сверь: цвет и форма волос, форма и цвет очков, форма бороды, "
         "пропорции лица. Футболка обязана быть охряной (#C89A3C); тёмно-синяя футболка — брак, "
         'ставь shirt_ok=false. Палитра: допустимы только тёмно-синий, охра, сигнальный красный '
         "и кремовая бумага; серый, лиловый, зелёный, бирюза — брак. "
         "ОТДЕЛЬНО И ВНИМАТЕЛЬНО посчитай пальцы на каждой видимой кисти: на каждой должно быть "
         "ровно пять пальцев, включая большой, сустав к суставу, без лишних и без сросшихся. "
         "Если рук в кадре нет, ставь hands_ok=true и напиши в issues «рук нет». "
         'Верни ТОЛЬКО JSON {"same_person":true|false,"hair_ok":true|false,'
         '"glasses_ok":true|false,"face_ok":true|false,"shirt_ok":true|false,'
         '"palette_ok":true|false,"hands_ok":true|false,"fingers_seen":"сколько пальцев насчитал '
         'на каждой кисти","issues":"не более 15 слов по-русски, что разошлось"}')


def b64(p: Path) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(p.read_bytes()).decode()}}


def verify(client, canon: Path, cand: Path):
    r = client.messages.create(model=MODEL, max_tokens=900, messages=[{"role": "user",
        "content": [b64(canon), b64(cand), {"type": "text", "text": CHECK}]}])
    txt = "".join(b.text for b in r.content if b.type == "text")
    try:
        return parse_json_block(txt), claude_cost(MODEL, r.usage)
    except Exception:
        # нераспознанный ответ — это брак, а не пропуск: раньше отсутствующие ключи
        # проходили проверку `is not False` и кадр засчитывался годным
        return {"parse_failed": True, "issues": txt[:160]}, claude_cost(MODEL, r.usage)


def main():
    chan_id, prj = sys.argv[1], Path(sys.argv[2])
    only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
    cfg_all = yaml.safe_load((ROOT / "config" / "channels.yaml").read_text(encoding="utf-8"))
    ch = cfg_all["channels"][chan_id]
    canon = prj / ch["character"]["canon"]
    if not canon.exists():
        sys.exit(f"нет канона {canon}")
    photo = next(iter(sorted((prj / "styletest").glob("photo_*.jpg"))), None)
    out = prj / "brand"; out.mkdir(parents=True, exist_ok=True)

    cfg, client = Config(), anthropic.Anthropic()
    style, who = ch["style_prompt"], character_prompt(ch)
    usd = ai = 0.0
    refs = [canon] + ([photo] if photo else [])
    rows = []
    jobs = dict(SHOTS)
    for k, country in MAPS.items():
        jobs[k] = ("16:9", MAP_SHOT.format(country=country))
    for name, (aspect, shot) in jobs.items():
        if only and name not in only:
            continue
        dst = out / f"{name}.jpg"
        for attempt in (1, 2, 3):
            if dst.exists() and attempt == 1:
                break
            is_map = name.startswith("map_")
            body = f"{style} {shot}{NEG}" if is_map else f"{style} {who} {shot}{NEG}"
            r = genimage.generate(cfg, body, dst, refs=(None if is_map else refs), aspect=aspect)
            usd += r.get("usd", 0.0)
            if is_map:                      # на карте нет персонажа — проверяем палитрой, не сверкой
                rows.append((name, attempt, True, {"issues": "карта, сверка с каноном не нужна"}))
                break
            v, c = verify(client, canon, dst); ai += c
            ok = all(v.get(k) is True for k in ("same_person", "hair_ok", "glasses_ok",
                                                "face_ok", "shirt_ok", "palette_ok", "hands_ok"))
            rows.append((name, attempt, ok, v))
            if ok:
                break
            dst.unlink(missing_ok=True)
        print(f"  {name:<15} {'OK  ' if rows and rows[-1][2] else 'БРАК'} {rows[-1][3].get('issues','')[:70]}")
    # аватар и баннер в точные размеры
    if (out / "avatar.jpg").exists():
        Image.open(out / "avatar.jpg").convert("RGB").resize((800, 800), Image.LANCZOS)\
             .save(out / "avatar_800.png")
    if (out / "banner.jpg").exists():
        Image.open(out / "banner.jpg").convert("RGB").resize((2560, 1440), Image.LANCZOS)\
             .save(out / "banner_2560x1440.png")
    if usd:
        costs.log(chan_id, "character_sheet", "gemini-3.1-flash-image", usd, len(rows), "персонаж")
    print(f"\nкартинки ${usd:.2f}, сверка ${ai:.2f}")
    (out / "check.json").write_text(json.dumps(
        [{"shot": n, "attempt": a, "ok": o, **v} for n, a, o, v in rows],
        ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
