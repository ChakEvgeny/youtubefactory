"""generate — генеративные клипы под библию формата.

Правила выбора (config gen.rules):
 (а) есть реальное фото субъекта (коллаж в режиме photo)  -> Runway image-to-video, движение камеры, 4–6 с;
 (б) реального нет, сцена атмосферная/обобщённая           -> Veo 3.1 text-to-video со звуком (ambient 10–15%);
 (в) провайдер упал / нет ключа                           -> Kling.
Никогда: узнаваемые реальные объекты, здания конкретных компаний, реальные люди —
промпт перед отправкой переписывается в обобщённый (Haiku) и проверяется regex по именам из брифа.
Лимит стоимости на ролик — gen.max_cost_eur (CLI --max-gen-cost); каждый клип — в cost и паспорт.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..sources import genvideo as gv
from ..util import Cache, claude_cost, parse_json_block, sha1

SANITIZE_MODEL = "claude-opus-5"
GENERIC_BAN = re.compile(r"\b(logo|logotype|badge|emblem|brand name|wordmark|trademark)\b", re.I)


def sanitize_prompt(client, text: str, style: str, banned: list[str], cost) -> dict:
    """Переписывает описание кадра в обобщённую сцену без брендов, людей и конкретных зданий."""
    prompt = (f"Описание кадра для генерации видео:\n«{text}»\n\nЗапрещено: названия компаний и брендов, логотипы, "
              f"конкретные здания и заводы конкретных компаний, реальные и узнаваемые люди, читаемый текст в кадре. "
              f"Перепиши как ОБОБЩЁННУЮ документальную сцену (например «a car factory» вместо названия завода), "
              f"одно предложение действия камеры (slow push-in, drift, handheld), 16:9. Стиль: {style}. "
              f"Верни ТОЛЬКО JSON: {{\"prompt\":\"...\",\"removed\":[\"что убрано\"],\"generic\":true/false}} "
              f"— generic=false, если сцену нельзя сделать обобщённой без потери смысла.")
    r = client.messages.create(model=SANITIZE_MODEL, max_tokens=400, messages=[{"role": "user", "content": prompt}])
    cost.add("generate", SANITIZE_MODEL, claude_cost(SANITIZE_MODEL, r.usage), "промпт")
    d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
    p = (d.get("prompt") or "").strip()
    hit = [b for b in banned if b and re.search(rf"\b{re.escape(b)}\b", p, re.I)]
    if GENERIC_BAN.search(p):
        hit.append("logo")
    d["prompt"], d["banned_hit"], d["ok"] = p, hit, bool(p) and d.get("generic", True) and not hit
    return d


def qc_clip(client, file: Path, prompt: str, cost) -> dict:
    """Vision-контроль сгенерированного клипа: 3 кадра -> Haiku ищет артефакты ИИ
    (лишние пальцы/конечности, плывущая геометрия, текст-абракадабра, логотипы, лица)."""
    import base64
    import subprocess
    imgs = []
    for t in (0.3, 2.0, 4.0):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.1f}", "-i", str(file), "-frames:v", "1",
                            "-vf", "scale=640:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"], capture_output=True, timeout=60)
        if r.stdout:
            imgs.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(r.stdout).decode()}})
    if not imgs:
        return {"ok": False, "why": "нет кадров"}
    msg = imgs + [{"type": "text", "text": f"Это 3 кадра сгенерированного ИИ видеоклипа (5–6 с) по промпту: «{prompt[:300]}». "
                   "Клип пойдёт в документальный ролик на 3–5 секунд как атмосферный план. "
                   "БРАК (ok=false) только при: читаемом тексте/вывесках/логотипах; узнаваемом бренде, реальном человеке или "
                   "конкретном здании; уродливых руках/лицах/телах (лишние пальцы, сросшиеся конечности); главном объекте, "
                   "который явно меняет форму между кадрами; сильном смазе (motion blur) или «плывущем» главном объекте — машине, "
                   "станке, здании; мультяшности или «игровой» CG-картинке. Лёгкий дрейф фоновой геометрии (провода, балки, "
                   "перспектива на дальнем плане) — НЕ брак. Отдельно: клип ОБЯЗАН показывать то, что описано в промпте, — пустой щит, "
                   "пустая комната или абстракция вместо названной сцены = брак (\"matches\": false). "
                   "Верни ТОЛЬКО JSON {\"ok\": true/false, \"matches\": true/false, \"defects\": [\"...\"], "
                   "\"score\": 0-10} — score 6 и выше значит годен."}]
    r = client.messages.create(model=SANITIZE_MODEL, max_tokens=700, messages=[{"role": "user", "content": msg}])
    cost.add("generate", SANITIZE_MODEL, claude_cost(SANITIZE_MODEL, r.usage), "QC клипа")
    d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
    sc = d.get("score")
    ok = bool(d.get("ok")) and d.get("matches", True) and (not isinstance(sc, (int, float)) or sc >= 6)
    return {"ok": ok, "why": "; ".join(d.get("defects") or [])[:200], "score": sc}


def banned_terms(ctx: Path, shots: list[dict]) -> list[str]:
    """Имена субъектов, бренды и люди из shotlist/brief — их в промптах быть не должно."""
    terms = set()
    for sh in shots:
        for k in ("subject",):
            if sh.get(k):
                terms.add(sh[k])
                terms.update(w for w in sh[k].split() if len(w) > 3 and w[0].isupper())
    bp = ctx / "brief.json"
    if bp.exists():
        b = json.loads(bp.read_text(encoding="utf-8"))
        for p in b.get("people", []) or []:
            terms.add(p.get("name") if isinstance(p, dict) else str(p))
        for c in b.get("companies", []) or []:
            terms.add(c.get("name") if isinstance(c, dict) else str(c))
    return sorted(t for t in terms if t and len(t) > 2)


def run_stage(cfg, ctx: Path, cost, preview_sec: float | None = None, max_cost_eur: float | None = None) -> dict:
    import anthropic
    g = dict(cfg.defaults.get("gen", {}) or {})
    g.update(cfg.channel.get("gen", {}) or {})
    limit_eur = float(max_cost_eur if max_cost_eur is not None else g.get("max_cost_eur", 120))
    eur = float(g.get("eur_per_usd", 0.92))
    shots = json.loads((ctx / "shotlist.json").read_text(encoding="utf-8"))
    coll = {c["idx"]: c for c in (json.loads((ctx / "collage.json").read_text(encoding="utf-8")) if (ctx / "collage.json").exists() else [])}
    fl = float(g.get("front_load_sec") or 0)
    for s in shots:
        if s["start"] >= fl or s.get("gen"):
            continue
        c = coll.get(s["idx"])
        if s.get("src_kind") == "collage" and c and c.get("photo"):
            s["gen"] = "i2v"                                   # реальное фото есть -> движение камеры
        elif s.get("src_kind") in ("stock", "card") and s.get("visual") and s.get("kind") != "motion":
            s["gen"] = "t2v"                                   # атмосферный план -> Veo
    todo = [s for s in shots if s.get("gen") in ("i2v", "t2v") and (preview_sec is None or s["start"] < preview_sec)]
    if not g.get("enabled") or limit_eur <= 0 or not todo:
        return {"enabled": bool(g.get("enabled")), "shots": len(todo), "rendered": 0, "spent_eur": 0.0, "skipped": "выключено или нечего"}
    client = anthropic.Anthropic()
    cache = Cache(cfg.paths.cache_dir)
    out_dir = cfg.paths.cache_dir / "gen"
    out_dir.mkdir(parents=True, exist_ok=True)
    style = g.get("style_prompt", "")
    negative = g.get("negative_prompt", "")
    refs = [Path(p) for p in (g.get("reference_frames") or [])]
    banned = banned_terms(ctx, shots)
    order = g.get("fallback_order", ["veo", "runway", "kling"])
    spent_usd, done, log = 0.0, [], []
    for sh in todo:
        want = sh["gen"]
        photo = None
        c = coll.get(sh["idx"])
        if want == "i2v":
            photo = Path(c["photo"]) if c and c.get("photo") and Path(c["photo"]).exists() else None
            if not photo:                                  # правило (а) требует реальное фото; иначе — (б)
                want = "t2v"
        if want == "i2v":
            san = {"prompt": "Slow cinematic push-in with subtle parallax, natural light, documentary handheld drift; "
                             "keep the photo exactly as is, no new objects, no text", "removed": [], "ok": True}
        else:
            san = sanitize_prompt(client, f"{sh.get('visual') or sh.get('scene_desc') or ''}. {sh.get('text','')[:160]}", style, banned, cost)
        if not san["ok"]:
            log.append({"idx": sh["idx"], "result": "prompt rejected", "removed": san.get("removed"), "hit": san.get("banned_hit")})
            sh.pop("gen", None)
            continue
        prompt = f"{san['prompt']} {style}".strip()
        seconds = 5 if want == "i2v" else int(g.get("t2v_seconds", 6))
        seconds = max(4, min(seconds, int(sh["dur"]) + 1, 8))
        chain = (["runway", "kling", "veo"] if want == "i2v" else order)
        res, err = None, []
        for prov in chain:
            est = gv.price({"veo": g.get("veo_model", "veo-3.1-fast-generate-preview"), "runway": g.get("runway_model", "gen4.5"),
                            "kling": "kling"}[prov], seconds, g.get("veo_resolution", "720p") if prov == "veo" else "std")
            if (spent_usd + est) * eur > limit_eur:
                err.append(f"{prov}: лимит {limit_eur} EUR")
                break
            key = sha1("gen", prov, prompt, str(photo), str(seconds))
            out = out_dir / f"{key}.mp4"
            rejected = out.with_name(out.stem + ".rejected.mp4")
            if rejected.exists() and not out.exists():     # уже платили — пере-проверяем по текущим правилам QC
                rejected.rename(out)
                out.with_suffix(".qc.json").unlink(missing_ok=True)
            try:
                if out.exists() and out.stat().st_size > 0:
                    res = {"file": str(out), "provider": prov, "model": "cache", "seconds": seconds, "usd": 0.0,
                           "audio": prov == "veo", "elapsed": 0}
                elif prov == "veo":
                    res = gv.veo(cfg, prompt, out, seconds=seconds, image=photo, model=g.get("veo_model", "veo-3.1-fast-generate-preview"),
                                 resolution=g.get("veo_resolution", "720p"), negative=negative, reference_images=refs)
                elif prov == "runway":
                    res = gv.runway(cfg, prompt, out, seconds=min(seconds, 10), image=photo, model=g.get("runway_model", "gen4.5"),
                                    ratio=g.get("runway_ratio", "1280:720"))
                else:
                    res = gv.kling(cfg, prompt, out, seconds=seconds, image=photo, model=g.get("kling_model", "kling-v2-1-master"))
                if res["usd"] > 0 or not out.with_suffix(".qc.json").exists():
                    qc = qc_clip(client, out, prompt, cost)
                    out.with_suffix(".qc.json").write_text(json.dumps(qc, ensure_ascii=False), encoding="utf-8")
                else:
                    qc = json.loads(out.with_suffix(".qc.json").read_text(encoding="utf-8"))
                if not qc["ok"]:                       # видимый ИИ-дефект: платим, но в ролик не берём
                    spent_usd += res["usd"]
                    cost.add("generate", f"{res['provider']}:{res['model']}", res["usd"], f"кадр {sh['idx']} QC отклонён: {qc['why'][:80]}")
                    err.append(f"{prov}: QC — {qc['why'][:80]}")
                    out.rename(out.with_name(out.stem + ".rejected.mp4"))
                    res = None
                    continue
                res["qc"] = qc
                break
            except Exception as e:                         # правило (в): следующий провайдер
                err.append(f"{prov}: {str(e)[:300]}")
                res = None
        if not res:
            log.append({"idx": sh["idx"], "result": "failed", "errors": err})
            sh.pop("gen", None)
            continue
        spent_usd += res["usd"]
        cost.add("generate", f"{res['provider']}:{res['model']}", res["usd"],
                 f"кадр {sh['idx']} {want} {res['seconds']}с ({res['usd'] * eur:.2f} EUR)")
        sh["src_kind"] = "gen"
        sh["gen_mode"] = want
        done.append({"idx": sh["idx"], "file": res["file"], "mode": want, "provider": res["provider"], "model": res["model"],
                     "seconds": res["seconds"], "usd": res["usd"], "eur": round(res["usd"] * eur, 3),
                     "audio": res.get("audio", False), "prompt": prompt, "removed": san.get("removed"), "photo": str(photo) if photo else None,
                     "qc": res.get("qc")})
        log.append({"idx": sh["idx"], "result": f"{res['provider']} {want}", "eur": round(res["usd"] * eur, 3), "errors": err})
    (ctx / "shotlist.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    (ctx / "generate.json").write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    lp = ctx / "sources_log.json"
    prev = [x for x in (json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else []) if x.get("stage") != "generate"]
    lp.write_text(json.dumps(prev + [{"stage": "generate", **x} for x in log], ensure_ascii=False, indent=1), encoding="utf-8")
    return {"enabled": True, "shots": len(todo), "rendered": len(done), "spent_eur": round(spent_usd * eur, 2),
            "limit_eur": limit_eur, "by_provider": {p: sum(1 for d in done if d["provider"] == p) for p in ("veo", "runway", "kling")},
            "failed": sum(1 for x in log if x["result"] in ("failed", "prompt rejected"))}
