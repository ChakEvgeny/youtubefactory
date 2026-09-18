"""stills — генерация кадров по раскадровке с референсами (герой + локация), QC каждого кадра
(Opus vision: соответствие промпту, тот же герой, нет текста/логотипов), image-to-video на ключевых,
assets.json для сборки. Лимит стоимости — --max-gen-cost (EUR)."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from ..sources import genimage
from ..sources import genvideo as gv
from ..util import SeenFrames, claude_cost, parse_json_block, sha1

MODEL = "claude-opus-5"


def qc_still(client, path: Path, prompt: str, hero_ref: Path | None, cost) -> dict:
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(path.read_bytes()).decode()}}]
    if hero_ref and hero_ref.exists():
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(hero_ref.read_bytes()).decode()}})
    content.append({"type": "text", "text": f"Кадр 1 сгенерирован по промпту: «{prompt}». " + ("Кадр 2 — лист героя. " if hero_ref else "") +
                    "Проверь: (1) кадр показывает то, что в промпте; (2) если герой в кадре — это тот же персонаж, что на листе (лицо, волосы, одежда); "
                    "(3) нет читаемого текста, логотипов, реальных узнаваемых людей; (4) нет уродств (руки, лица). "
                    "Верни ТОЛЬКО JSON {\"ok\":true/false,\"score\":0-10,\"why\":\"кратко\"} — ok=false при нарушении любого пункта."})
    r = client.messages.create(model=MODEL, max_tokens=300, messages=[{"role": "user", "content": content}])
    cost.add("stills", MODEL, claude_cost(MODEL, r.usage), "QC кадра")
    try:
        d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
    except Exception:
        d = {"ok": True, "score": 6, "why": "QC не распарсен"}
    return d


def run_stage(cfg, ctx: Path, cost, preview_sec: float | None = None, max_cost_eur: float | None = None) -> dict:
    import anthropic
    ch = cfg.channel
    g = {**(cfg.defaults.get("gen") or {}), **(ch.get("gen") or {})}
    limit_eur = float(max_cost_eur if max_cost_eur is not None else g.get("max_cost_eur", 120))
    eur = float(g.get("eur_per_usd", 0.92))
    shots = json.loads((ctx / "storyboard.json").read_text(encoding="utf-8"))
    world = json.loads((ctx / "world.json").read_text(encoding="utf-8"))
    style = ch.get("style_prompt", "")
    model = ch.get("image_model", "gemini-3.1-flash-image")
    hero = Path(world["hero"]["file"]) if world.get("hero", {}).get("file") else None
    loc_files = {l["key"]: Path(l["file"]) for l in world.get("locations", []) if l.get("file")}
    out_dir = ctx / "stills"; out_dir.mkdir(exist_ok=True)
    client = anthropic.Anthropic()
    spent = 0.0; log = []; stats = {"stills": 0, "regen": 0, "failed": 0, "i2v": 0, "qc_rejected": 0, "dup_rejected": 0}
    seen = SeenFrames(ctx, thr=8); seen.reset()
    for sh in shots:
        if sh["kind"] != "shot" or (preview_sec is not None and sh["start"] >= preview_sec):
            continue
        if spent * eur > limit_eur:
            log.append({"idx": sh["idx"], "result": "лимит"}); continue
        refs = []
        if sh.get("hero") and hero: refs.append(hero)
        lf = loc_files.get(sh.get("location") or "")
        if lf and sh.get("shot_kind") in ("wide", "medium"):   # на крупных планах референс локации душит композицию
            refs.append(lf)
        ref_note = ""
        if sh.get("hero") and hero: ref_note += " The main character must be the SAME person as in reference image 1: identical face, hair and clothes."
        if lf and lf in refs: ref_note += f" Reference image {len(refs)} shows the location: keep the same space, light and era, but compose a NEW shot, do not copy the reference."
        size = {"wide": "wide establishing shot", "medium": "medium shot", "close": "close-up", "insert": "insert detail shot"}.get(sh.get("shot_kind", "medium"), "medium shot")
        prompt = f"{size}: {sh.get('image_prompt') or sh['prompt']}.{ref_note} No text, no logos, no watermark. {style}"
        key = sha1("still", prompt, str(refs))[:16]
        jp = out_dir / f"s{sh['idx']:04d}_{key}.jpg"
        ok = False
        for attempt in range(3):
            if not jp.exists():
                try:
                    res = genimage.generate(cfg, prompt, jp, refs=refs, model=model); spent += res["usd"]
                    stats["stills"] += 1
                except Exception as e:
                    log.append({"idx": sh["idx"], "result": f"gen failed: {str(e)[:100]}"}); break
            if seen.similar(jp):                     # почти тот же кадр, что уже был — перегенерировать с другой композицией
                stats["dup_rejected"] += 1
                log.append({"idx": sh["idx"], "result": "dup: похож на предыдущий кадр"})
                jp.rename(jp.with_name(jp.stem + f".dup{attempt}.jpg"))
                prompt = prompt + " Completely different composition and camera angle from the previous shot; a different action beat."
                key = sha1("still", prompt, str(refs))[:16]; jp = out_dir / f"s{sh['idx']:04d}_{key}.jpg"
                stats["regen"] += 1
                continue
            qc = qc_still(client, jp, sh.get("image_prompt") or sh["prompt"], hero if sh.get("hero") else None, cost)
            if qc.get("ok"):
                ok = True; sh["qc"] = qc; seen.add(jp, sh["idx"]); break
            stats["qc_rejected"] += 1
            log.append({"idx": sh["idx"], "result": f"QC: {qc.get('why','')[:120]}"})
            jp.rename(jp.with_name(jp.stem + f".rej{attempt}.jpg"))
            prompt = prompt + " Fix: " + str(qc.get("why", ""))[:160]
            key = sha1("still", prompt, str(refs))[:16]; jp = out_dir / f"s{sh['idx']:04d}_{key}.jpg"
            stats["regen"] += 1
        if not ok or not jp.exists():
            stats["failed"] += 1
            sh["file"] = None; sh["source"] = "card"; sh["src_kind"] = "card"
            continue
        sh["file"] = str(jp); sh["source"] = "still"
        # ключевые кадры — движение по стиллу
        if sh.get("i2v") and (spent + 0.6) * eur <= limit_eur:
            mp = out_dir / f"m{sh['idx']:04d}_{key}.mp4"
            if not mp.exists():
                cam = f"{sh.get('camera','slow push-in')}; keep the image exactly as is, no new objects, no text"
                res = None; errs = []
                for prov in g.get("i2v_order", ["veo", "runway"]):     # Veo fast дешевле и без кредитов Runway
                    try:
                        if prov == "veo":
                            res = gv.veo(cfg, cam, mp, seconds=6, image=jp, model=g.get("veo_model", "veo-3.1-fast-generate-preview"),
                                         resolution=g.get("veo_resolution", "720p"))
                        else:
                            res = gv.runway(cfg, cam, mp, seconds=5, image=jp, model=g.get("runway_model", "gen4.5"), ratio=g.get("runway_ratio", "1280:720"))
                        break
                    except Exception as e:
                        errs.append(f"{prov}: {str(e)[:120]}")
                if res:
                    spent += res["usd"]; stats["i2v"] += 1
                else:
                    log.append({"idx": sh["idx"], "result": "i2v failed: " + " | ".join(errs)}); mp = None
            if mp and mp.exists():
                sh["file"] = str(mp); sh["fx"] = "cut"
    cost.add("stills", f"{model}+runway", spent, f"кадров {stats['stills']}, i2v {stats['i2v']} ({spent * eur:.1f} EUR)")
    assets = [{**sh, "source": sh.get("source") or ("motion" if sh["kind"] == "motion" else "card")} for sh in shots
              if preview_sec is None or sh["start"] < preview_sec]
    (ctx / "assets.json").write_text(json.dumps(assets, ensure_ascii=False, indent=1), encoding="utf-8")
    (ctx / "storyboard.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    lp = ctx / "sources_log.json"
    prev = [x for x in (json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else []) if x.get("stage") != "stills"]
    lp.write_text(json.dumps(prev + [{"stage": "stills", **x} for x in log], ensure_ascii=False, indent=1), encoding="utf-8")
    return {**stats, "spent_eur": round(spent * eur, 2), "limit_eur": limit_eur}
