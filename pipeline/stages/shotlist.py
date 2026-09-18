"""shotlist — единица сборки не сцена, а кадр 4-7 сек.

Режет каждую сцену по пословным таймкодам на границах предложений и запятых,
для каждого кадра просит модель составить конкретный сток-запрос
(существительное + действие + контекст), motion оставляет одним слотом.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import anthropic

from ..util import claude_cost, parse_json_block

MODEL = "claude-opus-5"        # типизация кадров: Haiku обрезала JSON батча
BATCH = 25

SYSTEM = (
    "Ты подбираешь поисковые запросы к стоковому видео для конкретных кадров ролика. "
    "Тебе дают текст, который звучит в этот момент, и описание сцены.\n"
    "Запрос должен быть КОНКРЕТНЫМ: существительное + действие + контекст. "
    "Хорошо: «Range Rover assembly line robots welding», «empty car showroom salesman waiting», "
    "«cargo ship loading cars at port». Плохо: «factory», «business», «cars».\n"
    "3-6 слов на английском. Запрос строится по тому, что ЗВУЧИТ в кадре; описание "
    "сцены — только подсказка о месте действия, НЕ повторяй его в каждом запросе. "
    "Внутри одной сцены чередуй крупность по кругу: общий план → средний план с людьми → "
    "деталь предмета → интерьер. Один и тот же объект (например aerial view) — не чаще "
    "одного раза на три соседних кадра. Три аэросъёмки завода подряд — брак.\n"
    "Отвечай ТОЛЬКО JSON без markdown: {\"<shot_id>\": \"query\"}"
)

BOUND = re.compile(r"[.!?,;:—]$")

TYPE_SYSTEM = (
    "Ты размечаешь кадры документального ролика. Для каждого кадра по тексту, который "
    "в нём звучит, определи:\n"
    "subject — конкретный именованный субъект, который в ЭТОМ кадре уместно ПОКАЗАТЬ: "
    "человек, названный по имени (Sharon Graham), продукт/модель (Land Rover Defender), "
    "здание/площадка (Solihull plant, Halewood). Компанию (Jaguar Land Rover, Vertu) ставь "
    "субъектом ТОЛЬКО если кадр именно про её завод, штаб-квартиру или продукт как объект; "
    "простое упоминание компании в тексте — это null. Цифры, решения, реакции — null.\n"
    "subject_type — person | product | building | company | null.\n"
    "query — поисковый запрос для фотоархива по субъекту, 2-5 слов на английском "
    "(имя + контекст: 'Sharon Graham Unite', 'Halewood plant Jaguar Land Rover').\n"
    "fact — 3-7 слов на английском для кинетического текста в кадре: ключевая цифра или "
    "суть фразы, без вводных слов.\n"
    "press — если в кадре звучит название издания или ссылка на публикацию (BBC, Financial "
    "Times, Sky News, Bild, SMMT report) — это название, иначе null.\n"
    "visual — ВСЕГДА: конкретная фотографируемая вещь, которую уместно показать под эту "
    "фразу, даже когда именованного субъекта нет: 'Range Rover Sport', 'Jaguar showroom', "
    "'Whitehall government building', 'Chery Omoda SUV', 'Unite union banner march', "
    "'car factory robots'. Не абстракции ('decision', 'uncertainty'), а предметы, здания, "
    "машины, места. visual_type — person | product | building | place | object.\n"
    "Отвечай ТОЛЬКО JSON: {\"<shot_id>\": {\"subject\":..., \"subject_type\":..., "
    "\"query\":..., \"fact\":..., \"press\":..., \"visual\":..., \"visual_type\":...}} "
    "без markdown."
)

BUDGET = {"collage": 0.40, "motion": 0.25, "screens": 0.10, "kling": 0.12, "stock": 0.10}


def assign_kinds(shots: list[dict], budget: dict) -> dict:
    """Тип источника кадра по субъекту и beat, затем подгонка под бюджет.
    Сток — только текстура для story без субъекта, никогда на субъекте."""
    n = len(shots)
    # real-footage у нас нет: его долю по замеру закрывают карточки прессы (fair use)
    # и коллажи — честные заменители новостной съёмки
    screens_cap = budget.get("screens", 0.1) + budget.get("footage", 0.0) * 0.6
    stock_cap = budget.get("stock", 0.0)
    for sh in shots:
        has_quote = bool(re.search(r'"[^"]{12,}"', sh.get("text", "") or ""))
        if sh["kind"] == "motion":
            sh["src_kind"] = "motion"
        elif sh.get("press"):
            sh["src_kind"] = "screens"
        elif sh.get("beat") == "quote" and has_quote and not sh.get("subject"):
            sh["src_kind"] = "card"             # цитата без лица — quote-карточка
        elif sh.get("subject") or sh.get("visual"):
            sh["src_kind"] = "collage"          # именованный субъект или визуальный объект фразы
        elif sh.get("kling") and budget.get("kling", 0) > 0:
            sh["src_kind"] = "kling"
        else:
            sh["src_kind"] = "card"
    def share(k):
        return sum(1 for x in shots if x["src_kind"] == k) / max(n, 1)

    def spread(cands: list[dict], k: int, kind: str):
        """k кадров из кандидатов с равным шагом — как в референсе, где типы
        чередуются, а не идут блоками"""
        k = min(k, len(cands))
        if k <= 0:
            return
        step = len(cands) / k
        for i in range(k):
            cands[int(i * step)]["src_kind"] = kind
    free = lambda beats: [x for x in shots if x["src_kind"] == "collage" and not x.get("subject") and x.get("beat") in beats]
    # карточки прессы: источник факта на кадрах без субъекта, до потолка screens (+доля footage)
    spread(free(("fact", "turn", "exposition", "story")), round(n * screens_cap) - sum(1 for x in shots if x["src_kind"] == "screens"), "screens")
    # сток по замеру — только без субъекта
    spread(free(("story", "exposition", "turn")), round(n * stock_cap), "stock")
    # карточки (logo/brand + text-kinetic по замеру) — из оставшихся кадров без субъекта
    spread(free(("fact", "turn", "exposition", "story", "quote")), round(n * budget.get("card", 0)) - sum(1 for x in shots if x["src_kind"] == "card"), "card")
    # генеративка (если включена): i2v — коллажи-фото зданий/мест/предметов (реальное фото есть),
    # t2v — атмосферные кадры без именованного субъекта; доли — shot_budget_gen
    gb = budget.get("_gen") or {}
    if gb:
        i2v = [x for x in shots if x["src_kind"] == "collage" and x.get("subject")
               and (x.get("subject_type") or "") not in ("person", "product")]
        t2v = [x for x in shots if x["src_kind"] in ("stock", "card") and not x.get("subject") and x.get("visual")]
        k = min(round(n * gb.get("i2v", 0)), len(i2v))
        for i in range(k):
            i2v[int(i * len(i2v) / k)]["gen"] = "i2v"
        k = min(round(n * gb.get("t2v", 0)), len(t2v))
        for i in range(k):
            t2v[int(i * len(t2v) / k)]["gen"] = "t2v"
        # первая минута — витрина: все подходящие кадры в генеративку (лимит стоимости всё равно сверху)
        fl = float(gb.get("front_load_sec") or 0)
        for x in i2v:
            if x["start"] < fl:
                x["gen"] = "i2v"
        for x in t2v:
            if x["start"] < fl:
                x["gen"] = "t2v"
    # не больше двух карточек прессы подряд: третью — в коллаж по visual
    run = 0
    for sh in shots:
        run = run + 1 if sh["src_kind"] == "screens" else 0
        if run >= 3:
            sh["src_kind"] = "collage"
            run = 0
    # тот же субъект два коллажа подряд: во втором показываем визуальный объект фразы,
    # если он другой; иначе остаётся коллаж — другой файл обеспечит стадия collage
    prev_subj = None
    for sh in shots:
        if sh["src_kind"] == "collage":
            if sh.get("subject") and sh.get("subject") == prev_subj and sh.get("visual") \
                    and sh["visual"].lower() != sh["subject"].lower():
                sh["collage_by"] = "visual"
            prev_subj = sh.get("subject")
        elif sh["src_kind"] not in ("card", "motion"):
            prev_subj = None
    out = {k: round(share(k), 3) for k in ("collage", "motion", "card", "screens", "kling", "stock")}
    out["gen_i2v"] = sum(1 for x in shots if x.get("gen") == "i2v")
    out["gen_t2v"] = sum(1 for x in shots if x.get("gen") == "t2v")
    return out


# Ритм-профиль по типу фрагмента: (мин, макс) секунд на кадр
PACING = {"hook": (2.0, 3.2), "exposition": (5.0, 7.0), "fact": (5.0, 7.0),
          "story": (8.0, 12.0), "quote": (8.0, 12.0), "turn": (5.0, 7.0)}


def break_monotony(shots: list[dict], tol: float = 1.0, run_max: int = 3) -> int:
    """Правило: кадр не похож длиной на соседа (±tol) больше run_max раз подряд.
    Идём слева направо и, как только серия достигает run_max, сдвигаем границу
    между текущим и следующим кадром так, чтобы следующий отличался на tol+0.3.
    Сдвиг не трогает motion и dip-границы, и не даёт кадру стать короче 1.5с."""
    fixed, run = 0, 1
    for i in range(1, len(shots)):
        a, b = shots[i - 1], shots[i]
        da, db = a["end"] - a["start"], b["end"] - b["start"]
        run = run + 1 if abs(da - db) <= tol else 1
        if run <= run_max:
            continue
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        if (a["kind"] != "stock" or b["kind"] != "stock" or b.get("dip_before")
                or not nxt or nxt["kind"] != "stock" or nxt.get("dip_before")):
            run = 1
            continue
        # укорачиваем b на (tol+0.3) и отдаём это время следующему кадру
        want = da - (tol + 0.3)
        if want < 1.5:
            want = da + (tol + 0.3)       # короче нельзя — тогда длиннее, за счёт nxt
            take = want - db
            if (nxt["end"] - nxt["start"]) - take < 1.5:
                run = 1
                continue
            b["end"] += take
            nxt["start"] += take
        else:
            give = db - want
            b["end"] -= give
            nxt["start"] -= give
        fixed += 1
        run = 1
    return fixed


def jl_offsets(shots: list[dict], off: float) -> int:
    """J/L-cut: стык картинки сдвигается относительно стыка фраз на ±off,
    чередуясь. Стыки с motion и dip-to-black не трогаем — там точность важнее."""
    n = 0
    for i in range(1, len(shots)):
        a, b = shots[i - 1], shots[i]
        if a["kind"] != "stock" or b["kind"] != "stock" or b.get("dip_before"):
            continue
        d = off if i % 2 else -off
        if (a["end"] + d) - a["start"] < 1.5 or b["end"] - (b["start"] + d) < 1.5:
            continue
        a["end"] += d
        b["start"] += d
        n += 1
    return n


def merge_short(shots: list[dict], smin_default: float) -> list[dict]:
    """Кадр короче СВОЕЙ нижней границы сливаем с предыдущим того же beat.
    Порог обязан быть у каждого кадра свой: раньше брался smin последней
    сцены цикла (quote = 8с), и всё короче 6.4с схлопывалось — так хук
    из 2-3-секундных кадров превратился в один 30-секундный."""
    merged: list[dict] = []
    for sh in shots:
        d = sh["end"] - sh["start"]
        thr = float(sh.get("smin", smin_default)) * 0.8
        prev = merged[-1] if merged else None
        if (prev and d < thr and prev["kind"] == sh["kind"] == "stock"
                and prev.get("beat") == sh.get("beat")):
            prev["end"] = sh["end"]
            prev["text"] = (prev["text"] + " " + sh["text"]).strip()
        else:
            merged.append(sh)
    return merged


def cut_scene(words: list[dict], lo: float, hi: float, smin: float, smax: float) -> list[tuple]:
    """Режет окно [lo, hi) на кадры профиля smin..smax.

    Считаем, сколько кадров влезает при средней длине профиля, и ставим границы
    на равных долях, притягивая каждую к ближайшему концу предложения (иначе —
    к концу слова). Так не бывает ни 30-секундных хвостов, ни обрезков по 1с."""
    span = hi - lo
    if span <= smax + 0.3:
        return [(lo, hi)]
    target = (smin + smax) / 2
    n = max(2, round(span / target))
    # чередуем короткий/длинный внутри профиля: соседние кадры отличаются
    # на (smax - smin), иначе нарезка равными долями даёт монотонный ритм
    pattern = [smin * 1.02 if k % 2 == 0 else smax * 0.98 for k in range(n)]
    scale = span / sum(pattern)
    acc, ideal = lo, []
    for L in pattern[:-1]:
        acc += L * scale
        ideal.append(acc)
    ends = [w["end"] for w in words if lo < w["end"] < hi]
    sent = [w["end"] for w in words if lo < w["end"] < hi and BOUND.search(w["word"])]
    win = min((smax - smin) / 2, 0.45)      # узкое окно, чтобы чередование не съедалось
    cuts, prev = [], lo
    for t in ideal:
        cand = [e for e in sent if abs(e - t) <= win and e - prev >= smin * 0.8]
        if not cand:
            cand = [e for e in ends if abs(e - t) <= 0.6 and e - prev >= smin * 0.8]
        c = min(cand, key=lambda e: abs(e - t)) if cand else t
        if hi - c < smin * 0.8:          # не оставляем огрызок в конце
            break
        cuts.append(c)
        prev = c
    pts = [lo] + cuts + [hi]
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


def text_between(words: list[dict], lo: float, hi: float) -> str:
    return " ".join(w["word"] for w in words if lo <= w["start"] < hi)


def run_stage(cfg, ctx: Path, cost) -> dict:
    from .assemble import scene_times
    scenes = json.loads((ctx / "scenes.json").read_text(encoding="utf-8"))
    ts = json.loads((ctx / "timestamps.json").read_text(encoding="utf-8"))
    words, total = ts["words"], ts["duration"]
    smin_d, smax_d = cfg.defaults["shot_seconds"]
    mmax = cfg.defaults["motion_max_seconds"]
    times = scene_times(ctx, scenes, words, total)

    shots = []
    # текст ДО первого маркера (обычно хук) тоже должен быть покрыт кадрами
    if times and times[0][0] > 0.6:
        beat0 = scenes[0].get("beat", "hook")
        smin0, smax0 = PACING.get(beat0, (smin_d, smax_d))
        desc0 = "opening — follow the spoken text, vary shot size"
        for a, b in cut_scene(words, 0.0, times[0][0], smin0, smax0):
            shots.append({"scene": -1, "kind": "stock", "start": a, "end": b,
                          "text": text_between(words, a, b), "beat": beat0,
                          "smin": smin0, "scene_desc": desc0})
    hook_max = float(cfg.defaults.get("hook_max_sec", 18.0))
    # профиль ритма из замера референса (channel.format.pacing) перекрывает зашитый
    fmt = (cfg.channel.get("format") or {}).get("pacing") or {}
    if fmt.get("middle"):
        mid = tuple(fmt["middle"])
        PACING.update({"exposition": mid, "fact": mid, "turn": mid, "story": mid, "quote": mid})
    if fmt.get("hook"):
        PACING["hook"] = tuple(fmt["hook"])
    for sc, (lo, hi) in zip(scenes, times):
        beat = sc.get("beat", "exposition")
        if beat == "hook" and lo >= hook_max:   # LLM тянет хук на три абзаца — режем по времени
            beat = "exposition"
        smin, smax = PACING.get(beat, (smin_d, smax_d))
        if sc["type"] == "motion":
            # motion — один слот; в хуке короче, иначе счётчик съедает весь темп
            cap = min(mmax, 4.0) if beat == "hook" else mmax
            end = min(hi, lo + cap)
            if hi - end < smin * 0.8:           # огрызок после motion — отдаём самому motion
                end = hi
            shots.append({"scene": sc["idx"], "kind": "motion", "start": lo, "end": end,
                          "motion_kind": sc["motion_kind"], "motion_data": sc["motion_data"],
                          "text": text_between(words, lo, end), "beat": beat,
                          "smin": smin, "scene_desc": sc["description"]})
            if hi - end > 1.0:
                nxt_stock = next((x for x in scenes[sc["idx"] + 1:] if x["type"] == "stock"), None)
                tail_desc = (nxt_stock["description"] if nxt_stock
                             else "follow the spoken text, vary shot size")
                segs = [(end, hi, beat, smin, smax)]
                if beat == "hook" and hi > hook_max > end:
                    e_min, e_max = PACING["exposition"]
                    segs = [(end, hook_max, "hook", smin, smax),
                            (hook_max, hi, "exposition", e_min, e_max)]
                elif beat == "hook" and end >= hook_max:
                    e_min, e_max = PACING["exposition"]
                    segs = [(end, hi, "exposition", e_min, e_max)]
                for a0, b0, bt, mn, mx in segs:
                    for a, b in cut_scene(words, a0, b0, mn, mx):
                        shots.append({"scene": sc["idx"], "kind": "stock", "start": a, "end": b,
                                      "text": text_between(words, a, b), "beat": bt,
                                      "smin": mn, "scene_desc": tail_desc})
        else:
            segs = [(lo, hi, beat, smin, smax)]
            if beat == "hook" and hi > hook_max > lo:
                e_min, e_max = PACING["exposition"]
                segs = [(lo, hook_max, "hook", smin, smax), (hook_max, hi, "exposition", e_min, e_max)]
            for a0, b0, bt, mn, mx in segs:
                for a, b in cut_scene(words, a0, b0, mn, mx):
                    shots.append({"scene": sc["idx"], "kind": "stock", "start": a, "end": b,
                                  "text": text_between(words, a, b), "beat": bt,
                                  "smin": mn, "scene_desc": sc["description"]})
    shots = merge_short(shots, smin_d)
    # сначала J/L-сдвиги, потом анти-монотонность: иначе сдвиги ±0.15с
    # ломают уже выстроенное чередование длин
    jl_shifted = jl_offsets(shots, float(cfg.defaults.get("jl_cut_ms", 150)) / 1000)
    monotony_fixed = break_monotony(shots)
    prev_beat = None
    for i, sh in enumerate(shots):
        sh["idx"] = i
        sh["dur"] = round(sh["end"] - sh["start"], 2)
        # эффекты по типу фрагмента (исполняет assemble)
        b = sh.get("beat", "exposition")
        sh["fx"] = {"hook": "speedramp" if i < 2 else "cut",
                    "fact": "pushin", "quote": "zoomout",
                    "story": "kenburns_slow"}.get(b, "cut")
        sh["dip_before"] = bool(prev_beat and b in ("turn", "fact") and b != prev_beat)
        prev_beat = b

    # запросы к стоку — батчами
    client = anthropic.Anthropic()
    need = [sh for sh in shots if sh["kind"] == "stock"]
    ROT = ["средний план с людьми", "деталь предмета крупно", "интерьер / рабочее место",
           "общий план места", "руки / документы / экран"]
    seen_scene: dict = {}
    for sh in need:
        k = sh["scene"]
        n = seen_scene.get(k, 0)
        seen_scene[k] = n + 1
        if n == 0:
            sh["hint"] = sh["scene_desc"]
            sh["first_in_scene"] = True
        else:   # не даём модели переписывать описание сцены в каждый запрос
            sh["hint"] = (f"та же локация, что и предыдущий кадр этой сцены, но ДРУГОЙ объект: "
                          f"{ROT[(n - 1) % len(ROT)]}")
    for i in range(0, len(need), BATCH):
        chunk = need[i:i + BATCH]
        listing = "\n\n".join(
            f'shot {sh["idx"]} ({sh["dur"]}с)\nПОДСКАЗКА: {sh.get("hint", sh["scene_desc"])[:90]}\n'
            f'ЗВУЧИТ: {sh["text"][:200] or "(без слов)"}' for sh in chunk)
        try:
            r = client.messages.create(model=MODEL, max_tokens=3000, system=SYSTEM,
                                       messages=[{"role": "user", "content": listing}])
            cost.add("shotlist", MODEL, claude_cost(MODEL, r.usage), f"кадры {chunk[0]['idx']}+")
            q = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
            # модель возвращает ключи как "shot_1", "shot 1" или "1" — нормализуем
            byid, ordered = {}, []
            for k, v in q.items():
                digits = re.findall(r"\d+", str(k))
                ordered.append(str(v))
                if digits:
                    byid[int(digits[-1])] = str(v)
            for pos, sh in enumerate(chunk):
                val = byid.get(sh["idx"])
                if val is None and pos < len(ordered):
                    val = ordered[pos]          # запасной путь — по позиции в батче
                sh["query"] = (val or sh["scene_desc"])[:70]
                sh["query_from"] = "llm" if val else "fallback"
        except Exception as e:
            print(f"    ! запросы для кадров {chunk[0]['idx']}+: {str(e)[:80]}")
            for sh in chunk:
                sh["query"] = sh["scene_desc"][:70]
                sh["query_from"] = "fallback"

    # ── субъект / пресса / факт для каждого кадра ─────────────────────────
    def type_chunk(chunk: list[dict], max_tokens: int = 6000):
        """Один батч типизации. Обрезанный/битый JSON — повтор половинками:
        без субъектов весь батч уходит в карточки, и превью превращается в плашки."""
        listing = "\n\n".join(f'shot {sh["idx"]} ({sh["dur"]}с)\nЗВУЧИТ: {sh["text"][:220] or "(без слов)"}'
                               for sh in chunk)
        try:
            r = client.messages.create(model=MODEL, max_tokens=max_tokens, system=TYPE_SYSTEM,
                                       messages=[{"role": "user", "content": listing}])
            cost.add("shotlist", MODEL, claude_cost(MODEL, r.usage), f"субъекты {chunk[0]['idx']}+")
            q = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
        except Exception as e:
            if len(chunk) > 4:
                half = len(chunk) // 2
                type_chunk(chunk[:half], max_tokens)
                type_chunk(chunk[half:], max_tokens)
            else:
                print(f"    ! типизация кадров {chunk[0]['idx']}+: {str(e)[:80]}")
            return
        byid = {}
        for k, v in q.items():
            d = re.findall(r"\d+", str(k))
            if d and isinstance(v, dict):
                byid[int(d[-1])] = v
        for sh in chunk:
            v = byid.get(sh["idx"], {})
            sh["subject"] = v.get("subject") or None
            sh["subject_type"] = v.get("subject_type") or None
            sh["subject_query"] = (v.get("query") or sh.get("subject") or "")[:70]
            sh["fact"] = (v.get("fact") or "")[:60]
            sh["press"] = v.get("press") or None
            sh["visual"] = (v.get("visual") or "")[:60] or None
            sh["visual_type"] = v.get("visual_type") or None

    for i in range(0, len(need), BATCH):
        type_chunk(need[i:i + BATCH])
    budget = {**BUDGET, **(cfg.defaults.get("shot_budget") or {})}
    gen_on = bool({**(cfg.defaults.get("gen") or {}), **(cfg.channel.get("gen") or {})}.get("enabled"))
    if gen_on and cfg.defaults.get("shot_budget_gen"):
        gb = dict(cfg.defaults["shot_budget_gen"])
        gb["front_load_sec"] = {**(cfg.defaults.get("gen") or {}), **(cfg.channel.get("gen") or {})}.get("front_load_sec", 0)
        budget = {**budget, **{k: v for k, v in gb.items() if k in BUDGET or k in ("screens", "card")}, "_gen": gb}
    if not cfg.defaults.get("kling_enabled", False):
        budget["kling"] = 0.0                # генерация Kling ещё не подключена — кадры не должны выйти чёрными
    kinds_share = assign_kinds(shots, budget)

    # соседние запросы про одно и то же — переспрашиваем точечно
    STOP = {"the", "a", "of", "in", "at", "on", "with", "and", "view", "shot", "scene"}
    def sig(q):
        return {w for w in re.findall(r"[a-z]+", (q or "").lower()) if w not in STOP and len(w) > 2}
    dup, prev, prev2 = [], None, None
    for sh in shots:
        if sh["kind"] != "stock":
            continue
        cur = sig(sh.get("query"))
        desc = sig(sh["scene_desc"])
        anchored = bool(desc) and len(cur & desc) / max(len(desc), 1) >= 0.6
        near = any(p is not None and cur and len(cur & p) / max(len(cur | p), 1) >= 0.3
                   for p in (prev, prev2))
        if (near or anchored) and not sh.get("first_in_scene"):
            dup.append(sh)
        prev2, prev = prev, cur
    requeried = 0
    if dup:
        listing = "\n\n".join(
            f'shot {sh["idx"]} ({sh["dur"]}с)\nУЖЕ ПОКАЗАНО РЯДОМ: '
            f'{shots[sh["idx"]-1].get("query")}; {shots[max(sh["idx"]-2,0)].get("query")}\n'
            f'ЗАПРЕЩЕНО ПОВТОРЯТЬ: {sh["scene_desc"][:60]}\n'
            f'ЗВУЧИТ: {sh["text"][:200] or "(без слов)"}' for sh in dup)
        try:
            r = client.messages.create(
                model=MODEL, max_tokens=2000,
                system=SYSTEM + "\nСЕЙЧАС: для каждого кадра дай запрос про ДРУГОЙ объект и другую "
                                "крупность, чем предыдущий кадр. Повтор объекта — брак.",
                messages=[{"role": "user", "content": listing}])
            cost.add("shotlist", MODEL, claude_cost(MODEL, r.usage), "разведение соседей")
            q = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
            byid = {}
            for k, v in q.items():
                d = re.findall(r"\d+", str(k))
                if d:
                    byid[int(d[-1])] = str(v)
            for sh in dup:
                if sh["idx"] in byid:
                    sh["query"] = byid[sh["idx"]][:70]
                    sh["query_from"] = "requery"
                    requeried += 1
        except Exception as e:
            print(f"    ! разведение соседей: {str(e)[:80]}")

    (ctx / "shotlist.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    durs = sorted(sh["dur"] for sh in shots)
    import collections
    return {"shots": len(shots), "stock": sum(1 for s in shots if s["kind"] == "stock"),
            "by_beat": dict(collections.Counter(s.get("beat") for s in shots)),
            "dips": sum(1 for s in shots if s.get("dip_before")),
            "monotony_fixed": monotony_fixed, "jl_shifted": jl_shifted,
            "neighbor_requeried": requeried, "src_share": kinds_share,
            "subjects": sum(1 for x in shots if x.get("subject")),
            "motion": sum(1 for s in shots if s["kind"] == "motion"),
            "median_sec": durs[len(durs) // 2] if durs else 0,
            "min_sec": durs[0] if durs else 0, "max_sec": durs[-1] if durs else 0,
            "per_minute": round(len(shots) / (total / 60), 1)}
