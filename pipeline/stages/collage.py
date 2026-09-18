"""collage — кадры с конкретным субъектом: Commons -> vision-отбор -> rembg -> Remotion Collage.

Если легального изображения субъекта нет — карточка (brand/quote), никогда сток.
Лицензии и авторы — в sources_log.json (уходит в паспорт и описание).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
from pathlib import Path

import anthropic

from ..cutout import cutout
from ..sources import commons
from ..util import SeenFrames, Cache, claude_cost, parse_json_block, run, sha1

VISION = "claude-opus-5"      # Haiku резала JSON и отбраковывала лишнее; +$0.3/ролик
VISION_SYS = (
    "Ты выбираешь фотографию для коллажа в документальном ролике. Нужен кадр, где НАЗВАННЫЙ "
    "субъект — главный и единственный объект: портрет человека (не толпа, не групповое фото), "
    "одна машина/модель, одно здание. Групповые снимки, где субъект — один из многих, "
    "не годятся. Читаемые логотипы, бренд-стены (пресс-волл, стенд), вывески и водяные знаки — брак.\\n"
    "Отвечай ТОЛЬКО JSON: {\"best\": <индекс с нуля или -1>, \"score\": <0-10>, "
    "\"portrait\": true|false, \"modern\": true|false (снимок нашего времени, не архив "
    "другой эпохи), \"other_person\": true|false (в кадре узнаваемое или частное лицо, "
    "которое НЕ является субъектом), \"readable\": true|false (кадр светлый и различимый), "
    "\"logos\": true|false (в кадре читаемые логотипы, бренд-стена, вывеска или водяной знак), "
    "\"why\": \"кратко по-русски\"}"
)
PUBLIC = "cuts"


PERSON_TITLE = re.compile(r"^File:[A-Z][a-z]+ [A-Z][a-z]+")   # «Steve Turner, 2016 …» — фото человека


def norm_type(stype: str | None) -> str:
    t = (stype or "object").lower()
    if t in ("organization", "organisation", "union", "brand", "company", "institution"):
        return "company"
    return t if t in ("person", "product", "building", "place", "object") else "object"


def name_filter(subject: str, stype: str, cands: list[dict]) -> list[dict]:
    """Личность и организацию vision не проверит: ключевое слово субъекта обязано быть
    в названии или описании файла на Commons (фамилия для людей, имя для организаций).
    Файл, названный именем человека, для не-персонального субъекта не годится."""
    if stype != "person":
        cands = [c for c in cands if not PERSON_TITLE.match(c["title"])]
    if stype == "person":
        key = subject.split()[-1].lower()
    elif stype in ("company",):
        words = [w for w in re.findall(r"[A-Za-z]+", subject) if len(w) > 2 and w.lower() not in ("the", "union", "group")]
        key = (words[0] if words else subject).lower()
        return [c for c in cands if key in c["title"].lower()]
    else:
        return cands
    return [c for c in cands if key in (c["title"] + " " + c["desc"]).lower()]


def pick(client, subject: str, stype: str, cands: list[dict], cache: Cache, cost,
         context: str = "", min_score: float = 5):
    content = [{"type": "text", "text": f"СУБЪЕКТ: {subject} ({stype})\nКОНТЕКСТ: {context[:200]}"}]
    shown = []
    for c in cands:
        try:
            p = commons.download(c, cache)
        except Exception as e:
            print(f"    ! commons: {str(e)[:70]}")
            continue
        prev = cache.blob_path("previews", sha1("cprev", str(p)), ".jpg")
        if not prev.exists():
            try:
                run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf", "scale=360:-2", str(prev)])
            except Exception:
                continue
        shown.append((c, p))
        content.append({"type": "text", "text": f"вариант {len(shown)-1}: {c['title'][5:70]}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(prev.read_bytes()).decode()}})
    if not shown:
        return None
    r = client.messages.create(model=VISION, max_tokens=300, system=VISION_SYS,
                               messages=[{"role": "user", "content": content}])
    cost.add("collage", VISION, claude_cost(VISION, r.usage), f"выбор: {subject[:30]}")
    try:
        d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
        bi, score = int(d.get("best", -1)), float(d.get("score", 0))
    except Exception as e:
        print(f"    ! vision ответ: {str(e)[:60]}")
        return None
    hard = []
    if not d.get("modern", True):
        hard.append("архив")
    if d.get("other_person") and stype != "person":
        hard.append("чужое лицо")
    if not d.get("readable", True):
        hard.append("нечитаемо")
    if d.get("logos"):
        hard.append("логотипы")
    if bi < 0 or bi >= len(shown) or score < min_score or hard:
        print(f"    · vision отверг «{subject}»: best={bi} score={score} {'/'.join(hard)} — {str(d.get('why',''))[:70]}")
        return None
    c, p = shown[bi]
    return {**c, "file": str(p), "score": score, "portrait": bool(d.get("portrait")),
            "why": str(d.get("why", ""))[:80]}


def run_stage(cfg, ctx: Path, cost, preview_sec: float | None = None) -> dict:
    from .motion import MOTION_DIR, render_one, COMP
    COMP.setdefault("collage", "Collage")
    cache = Cache(cfg.paths.cache_dir)
    client = anthropic.Anthropic()
    shots = json.loads((ctx / "shotlist.json").read_text(encoding="utf-8"))
    todo = [s for s in shots if s.get("src_kind") == "collage"
            and (preview_sec is None or s["start"] < preview_sec)]
    palette = cfg.channel["thumb_palette"]
    pub = MOTION_DIR / "public" / PUBLIC
    pub.mkdir(parents=True, exist_ok=True)
    out_dir = cfg.paths.cache_dir / "collage"
    out_dir.mkdir(parents=True, exist_ok=True)

    log, done, fallback = [], [], 0
    prev_subject_side = "right"
    used_urls: set[str] = set()
    seen = SeenFrames(ctx)
    seen.reset()                          # новый прогон коллажей — новый реестр кадров
    for sh in todo:
        # именованный субъект, иначе — визуальный объект фразы
        by_visual = sh.get("collage_by") == "visual" or not sh.get("subject")
        subject = (sh.get("visual") if by_visual else sh.get("subject")) or sh.get("subject") or ""
        stype = norm_type(sh.get("visual_type") if by_visual else sh.get("subject_type"))
        context = f"ролик про автопром (Jaguar Land Rover). Звучит: {sh.get('text','')[:160]}"
        # Commons ищет по «И»: длинные запросы дают ноль. Лестница — от короткого
        # имени субъекта к уточнениям; портрет для людей ищем по имени + организации.
        org = ""
        if stype == "person":
            m = re.search(r"\b(Unite|JLR|Jaguar Land Rover|Tata|Labour|Government|MP)\b",
                          sh.get("text", "") or "", re.I)
            org = m.group(1) if m else ""
        queries = {
            "person":   [subject, f"{subject} {org}".strip(), f"{subject} official portrait"],
            "product":  [subject, f"{subject} car"],
            "building": [subject, f"{subject} plant", f"{subject} factory"],
            "company":  [f"{subject} plant", f"{subject} factory", f"{subject} headquarters", subject],
            "place":    [subject],
            "object":   [subject],
        }.get(stype, [subject])
        # марка Jaguar без слова car — это животное на Commons
        if stype in ("product", "company") and re.fullmatch(r"jaguar", subject.strip(), re.I):
            queries = ["Jaguar car", "Jaguar F-Pace", "Jaguar Land Rover"]
        if by_visual:
            parts = [x.strip() for x in re.split(r"[,;/]", subject) if x.strip()]
            queries = parts[:3] + [" ".join(parts[0].split()[:2])] if parts else [subject]
        if stype in ("company", "organization", "brand") and not by_visual:
            queries = [f"{subject} car", f"{subject} factory", f"{subject} headquarters", f"{subject} dealership"] + queries
        queries = [q for i, q in enumerate(queries) if q and q not in queries[:i]]
        chosen, best = None, None
        for q in queries:
            cands = commons.search(q, cache, limit=10)
            cands = name_filter(subject, stype, cands)
            cands = [c for c in cands if c["url"] not in used_urls]   # один файл — один раз на ролик
            if not cands:
                continue
            res = pick(client, subject, stype, cands[:5], cache, cost, context,
                       min_score=7 if by_visual else 5)
            if not res:
                continue
            # для людей нужен портрет (или очень уверенный выбор) — иначе ищем дальше
            if stype == "person" and not res.get("portrait") and res["score"] < 8:
                if best is None or res["score"] > best["score"]:
                    best = res
                continue
            if res.get("file") and seen.similar(res["file"]):   # почти тот же кадр уже был
                used_urls.add(res["url"])
                continue
            chosen = res
            break
        # персона: только чистый портрет; групповое фото с чужими лицами — никогда, лучше quote-карточка
        chosen = chosen or (best if stype != "person" else None)
        if chosen:
            used_urls.add(chosen["url"])
            if chosen.get("file"):
                seen.add(chosen["file"], sh["idx"])
        if not chosen:
            # легального изображения нет: абстрактный visual без именованного субъекта —
            # в сток (как в референсе), именованный субъект — карточка
            sh["src_kind"] = "card" if sh.get("subject") else "stock"
            fallback += 1
            log.append({"idx": sh["idx"], "subject": subject, "result": f"no_image -> {sh['src_kind']}"})
            continue
        mode = "cutout" if stype in ("person", "product") else "photo"
        if mode == "cutout":
            cut = out_dir / f"{sha1('cut', chosen['file'])}.png"
            if not cut.exists():
                try:
                    cutout(Path(chosen["file"]), cut)
                except Exception as e:
                    sh["src_kind"] = "card"
                    fallback += 1
                    log.append({"idx": sh["idx"], "subject": subject, "result": f"cutout failed: {str(e)[:60]}"})
                    continue
        else:                                   # здание / место / предмет — фото целиком в рамке
            cut = out_dir / f"{sha1('photo', chosen['file'])}.jpg"
            if not cut.exists():
                run(["ffmpeg", "-y", "-v", "error", "-i", chosen["file"],
                     "-vf", "scale='min(1600,iw)':-2", "-q:v", "3", str(cut)])
        rel = f"{PUBLIC}/{cut.name}"
        if not (pub / cut.name).exists():
            shutil.copy(cut, pub / cut.name)
        side = "left" if prev_subject_side == "right" else "right"
        prev_subject_side = side
        attrib = commons.attribution(chosen) if chosen.get("needs_attribution") else ""
        frames = int(max(sh["dur"], 2.0) * 30)
        props = {"cutout": rel, "text": sh.get("fact") or "", "sub": "",
                 "attribution": attrib, "palette": palette, "side": side,
                 "objectScale": 1.0, "portrait": bool(chosen.get("portrait")),
                 "mode": mode, "durationInFrames": frames}
        clip = out_dir / f"{sha1('clip', json.dumps(props, sort_keys=True))}.mp4"
        if not clip.exists():
            cwd = os.getcwd()
            os.chdir(MOTION_DIR)
            try:
                render_one("collage", props, clip)
            finally:
                os.chdir(cwd)
        done.append({"idx": sh["idx"], "file": str(clip), "subject": subject, "mode": mode,
                     "photo": str(cut) if mode == "photo" else None, "source_url": chosen.get("url")})
        log.append({"idx": sh["idx"], "subject": subject, "result": f"collage/{mode}",
                    "title": chosen["title"], "page": chosen["page"], "license": chosen["license"],
                    "author": chosen["author"], "attribution": attrib or "(не требуется)",
                    "vision_score": chosen["score"], "why": chosen["why"]})

    (ctx / "shotlist.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    (ctx / "collage.json").write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    prev_log = []
    lp = ctx / "sources_log.json"
    if lp.exists():
        prev_log = [x for x in json.loads(lp.read_text(encoding="utf-8")) if x.get("stage") != "collage"]
    lp.write_text(json.dumps(prev_log + [{"stage": "collage", **x} for x in log],
                             ensure_ascii=False, indent=1), encoding="utf-8")
    return {"collage_shots": len(todo), "rendered": len(done), "fallback_to_card": fallback,
            "licenses": sorted({x["license"] for x in log if "license" in x})}
