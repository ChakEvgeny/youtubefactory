#!/usr/bin/env python3
"""Линтер канала Terms of Employment: проверяет правила кодом, а не памятью.

Правила живут в docs/rules_terms_of_employment.md. Здесь — их исполняемая версия.
Правило без проверки тут не работает: после сжатия контекста оно теряется.

    python scripts/lint_terms.py <папка> --stage all --vision

Возвращает 1 при любом нарушении — этого достаточно, чтобы уронить сборку.
Вызывается автоматически после стадий script и storyboard.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import colorsys
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

NAVY, OCHRE, RED, PAPER = (0x1B, 0x2A, 0x5E), (0xC8, 0x9A, 0x3C), (0xE4, 0x53, 0x3A), (0xF2, 0xEC, 0xE0)
PAL = [NAVY, OCHRE, RED, PAPER]
MODEL = "claude-opus-5"

# обещания зрителю в хуке: клик с уходом на 24-й секунде хуже отсутствия клика
PROMISES = [
    "the last thing i", "stay until the end", "stay till the end", "by the end of this video",
    "at the end of this video", "before you go", "make sure you watch", "keep watching",
    "i'll tell you at the end", "wait for it", "more on that later", "we'll get to that",
]
# автор говорит как человек, который это делал, а не как эксперт-комментатор
VOICE_BAN = ["as a recruiter, i can tell you", "as an hr", "i walked this path",
             "trust me,", "believe me,"]
EMPLOYER_HINTS = [r"\bi worked (?:at|for)\s+[A-Z]", r"\bmy employer,\s+[A-Z]",
                  r"\bwhen i was at\s+[A-Z]", r"\bat my company,\s+[A-Z]"]
NUM = re.compile(r"(?<![\w$])(?:\d[\d,\.]*\s*(?:%|percent|days?|weeks?|months?|years?|employees?)"
                 r"|[$£€]\s?\d[\d,\.]*|\b(?:19|20)\d{2}\b)", re.I)


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, sev: str, rule: str, msg: str) -> None:
        self.rows.append((sev, rule, msg))

    def dump(self) -> int:
        if not self.rows:
            print("нарушений нет")
            return 0
        bad = [r for r in self.rows if r[0] == "БРАК"]
        for sev, rule, msg in sorted(self.rows, key=lambda r: r[0] != "БРАК"):
            print(f"  [{sev}] {rule}: {msg}")
        print(f"\nвсего {len(self.rows)}, из них брак {len(bad)}")
        return 1 if bad else 0


# ─────────────────────────────── сценарий ───────────────────────────────

def script_path(P: Path) -> Path:
    """Сценарий канала — покадровый script.txt (решение Евгения 2026-09-24).

    script.md остаётся как запасной вариант для старых роликов, снятых до
    перехода на единый формат.
    """
    txt = P / "script.txt"
    return txt if txt.exists() else P / "script.md"


def parse_script_txt(p: Path):
    """Покадровый формат: `═══ БЛОК N · НАЗВАНИЕ ═══`, шоты `[id] KIND`, речь `EN:`."""
    blocks, cur, field = [], None, None
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^═══\s*БЛОК\s*([\d.]+)\s*·\s*(.+?)\s*═══\s*$", line)
        if m:
            cur = {"n": m.group(1), "title": m.group(2), "t0": None, "t1": None,
                   "lines": [], "raw": []}
            blocks.append(cur)
            field = None
            continue
        if cur is None:
            continue
        cur["raw"].append(line)
        st = line.strip()
        if st.startswith("EN:"):
            cur["lines"].append(st[3:].strip())
            field = "en"
        elif st.startswith("ФАКТ:"):
            # источник живёт строкой рядом с репликой, а не внутри озвучки:
            # ✅ приклеивается к тексту кадра, чтобы проверка факта его видела
            if cur["lines"]:
                cur["lines"][-1] += " " + st
            field = None
        elif st.startswith(("RU:", "КАДР:", "КАРТОЧКА:", "[", ">>>")) or not st:
            field = None
        elif field == "en" and cur["lines"]:
            cur["lines"][-1] += " " + st
    return blocks


def parse_script(p: Path):
    """Блоки `## Блок N. Название — 0:00–0:29` и строки диктора `> ...`."""
    if p.suffix == ".txt":
        return parse_script_txt(p)
    blocks, cur = [], None
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s*Блок\s*([\d.]+)\.\s*(.+?)\s*(?:—\s*([\d:]+)\s*[–-]\s*([\d:]+))?\s*$", line)
        if m:
            cur = {"n": m.group(1), "title": m.group(2), "t0": m.group(3), "t1": m.group(4),
                   "lines": [], "raw": []}
            blocks.append(cur)
            continue
        if cur is not None:
            cur["raw"].append(line)
            # дикторский текст в markdown разорван по ширине строки; проверять
            # надо абзац целиком, иначе ✅ в конце абзаца не виден первой строке
            if line.startswith("> "):
                if cur["lines"] and cur.get("_open"):
                    cur["lines"][-1] += " " + line[2:].strip()
                else:
                    cur["lines"].append(line[2:].strip())
                cur["_open"] = True
            else:
                cur["_open"] = False
    return blocks


def secs(t: str | None) -> float | None:
    if not t:
        return None
    parts = [int(x) for x in t.split(":")]
    return parts[0] * 60 + parts[1] if len(parts) == 2 else float(parts[0])


def lint_script(P: Path, rep: Report) -> None:
    sp = script_path(P)
    if not sp.exists():
        rep.add("БРАК", "сценарий", f"нет файла {sp}")
        return
    text = sp.read_text(encoding="utf-8")
    blocks = parse_script(sp)
    if not blocks:
        rep.add("БРАК", "сценарий", "не разобрались блоки (## Блок N. …)")
        return

    # ⚠️ — непроверенный источник: с ним ролик не пишется
    warn_in_narr = [(b["title"], l) for b in blocks for l in b["lines"] if "⚠️" in l]
    for t, l in warn_in_narr:
        rep.add("БРАК", "факт без источника", f"{t}: ⚠️ в дикторском тексте — «{l[:60]}…»")
    legend = sum(1 for l in text.splitlines()
                 if "⚠️" in l and ("источник" in l.lower() or "не проверен" in l.lower()))
    n_warn = text.count("⚠️") - len(warn_in_narr) - legend
    if n_warn > 0:
        rep.add("ПРЕДУПР", "источники", f"{n_warn} ⚠️ в таблице источников — блоки на них не писать")

    # числа без пометки проверенного источника
    for b in blocks:
        for l in b["lines"]:
            if NUM.search(l) and "✅" not in l and "⚠️" not in l:
                rep.add("БРАК", "факт без источника",
                        f"{b['title']}: число без ✅ — «{l[:70]}…»")

    low = text.lower()
    hook = next((b for b in blocks if "хук" in b["title"].lower()), None)
    for ph in PROMISES:
        if hook and ph in " ".join(hook["lines"]).lower():
            rep.add("БРАК", "обещание в хуке", f"«{ph}»")
        elif ph in low:
            rep.add("ПРЕДУПР", "обещание зрителю", f"«{ph}» вне хука")
    for ph in VOICE_BAN:
        if ph in low:
            rep.add("БРАК", "голос автора", f"запрещённый оборот «{ph}»")
    for pat in EMPLOYER_HINTS:
        for m in re.finditer(pat, text, re.I):
            rep.add("БРАК", "работодатель назван", f"«{text[m.start():m.start()+50]}…»")

    # рамка не длиннее 30 с
    fr = next((b for b in blocks if "рамк" in b["title"].lower()), None)
    if fr:
        a, z = secs(fr["t0"]), secs(fr["t1"])
        if a is not None and z is not None and z - a > 30:
            rep.add("БРАК", "рамка", f"{z - a:.0f} с при пороге 30")
    else:
        rep.add("ПРЕДУПР", "рамка", "блок «Рамка» не найден")

    # риторические вопросы к зрителю
    q = [l for b in blocks for l in b["lines"]
         if l.rstrip().endswith("?") and re.search(r"\byou\b|\byour\b", l, re.I)]
    if len(q) > 2:
        rep.add("БРАК", "риторические вопросы", f"{len(q)} при пороге 2: "
                + "; ".join(x[:40] for x in q[:4]))

    # финал — вопрос зрителю
    last = blocks[-1]
    tail = [l for l in last["lines"] if l.strip()]
    if not tail or not tail[-1].rstrip().endswith("?"):
        rep.add("БРАК", "финал", f"последний блок «{last['title']}» не кончается вопросом")
    if re.search(r"(?m)^\s*\W{0,2}the end\W{0,2}\s*$", low):
        rep.add("БРАК", "финал", "«The End» на этом канале запрещён")

    # смена ритма между однотипными страновыми блоками
    names = [b["title"] for b in blocks]
    cn = [i for i, t in enumerate(names)
          if re.search(r"США|Британ|Канад|Австрал", t)]
    for a, z in zip(cn, cn[1:]):
        if z - a == 1:
            rep.add("БРАК", "смена ритма",
                    f"«{names[a]}» и «{names[z]}» подряд без блока смены ритма")

    # мост не должен пересказывать первую фразу следующего блока
    import difflib
    for a, b in zip(blocks, blocks[1:]):
        if "ритм" not in a["title"].lower() or not a["lines"] or not b["lines"]:
            continue
        def norm(s):
            return re.sub(r"[^a-z ]", "", s.lower()).split()
        x, y = norm(a["lines"][-1]), norm(b["lines"][0])
        if not x or not y:
            continue
        r = difflib.SequenceMatcher(None, x, y).ratio()
        if r > 0.5:
            rep.add("БРАК", "мост повторяет блок",
                    f"«{a['title']}» и начало «{b['title']}» совпадают на {r*100:.0f}%")

    # незакрытые заглушки автора
    for m in re.finditer(r"\[INSIDE — нужен твой пример[^\]]*\]", text):
        if m.group(0).endswith(": ...]"):
            continue          # это пример формата в легенде, а не заглушка
        rep.add("ПРЕДУПР", "INSIDE", f"заглушка не закрыта: {m.group(0)[:60]}")


# ───────────────────────────── раскадровка ─────────────────────────────

def phash(p: Path) -> int:
    a = np.asarray(Image.open(p).convert("L").resize((32, 32)), dtype=float)
    d = np.fft.dct if hasattr(np.fft, "dct") else None
    # честный dct через scipy, если он есть; иначе усреднённый хэш
    try:
        from scipy.fftpack import dct
        c = dct(dct(a, axis=0, norm="ortho"), axis=1, norm="ortho")[:8, :8]
    except Exception:
        c = a[:8, :8]
    v = c.flatten()[1:]
    bits = v > np.median(v)
    out = 0
    for b in bits:
        out = (out << 1) | int(b)
    return out


def shares(p: Path) -> tuple[float, float, float]:
    """доли: красного, серого, далёкого от палитры."""
    a = np.asarray(Image.open(p).convert("RGB").resize((240, 135)), dtype=float).reshape(-1, 3)
    dist = np.stack([np.linalg.norm(a - np.array(c), axis=1) for c in PAL])
    red = float((dist.argmin(axis=0) == 2).mean())
    off = float((dist.min(axis=0) > 95).mean())
    hsv = np.array([colorsys.rgb_to_hsv(*(x / 255)) for x in a])
    grey = float(((hsv[:, 1] < 0.12) & (hsv[:, 2] > 0.20) & (hsv[:, 2] < 0.80)).mean())
    return red, grey, off


def vision(shots, P: Path, rep: Report) -> None:
    """Проверки, которые числом не берутся: текст в кадре, футболка, пальцы,
    соответствие кадра строке. Батчами по одному кадру — модель путает кадры,
    когда их в запросе несколько."""
    import anthropic
    cl = anthropic.Anthropic()
    sysmsg = (
        "Ты технический контролёр кадров рисованного ролика. Отвечай ТОЛЬКО JSON.\n"
        "Поля: has_text (bool — виден ли в кадре хоть один читаемый символ, буква, "
        "цифра, надпись, вывеска или подпись; каракули и имитация письма тоже true), "
        "matches_line (bool — читается ли из КАРТИНКИ мысль реплики; не «есть ли "
        "нужное число предметов», а передаёт ли кадр смысл), why (строка до 90 "
        "символов), shirt_ochre (bool или null — если в кадре ведущий, сплошная ли "
        "у него охряная футболка без второго слоя), fingers_ok (bool или null — "
        "если видны кисти, ровно ли пять пальцев на каждой), "
        "red_on_skin (bool — есть ли красные штрихи или красный контур на коже), "
        "one_country_red (bool или null — если это карта, выделена ли красным "
        "ровно одна страна), country_big (bool или null — если это карта, занимает "
        "ли выделенная страна не меньше трети кадра)."
    )

    def one(sh):
        f = P / (sh.get("file") or f"stills/s{sh['id']:03d}.jpg")
        if not f.exists() or f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            return
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(f.read_bytes()).decode()}},
                   {"type": "text", "text":
                    f"Реплика поверх кадра: «{sh.get('narr') or '—'}»\n"
                    "Реплика может быть обрывком фразы — оценивай, не противоречит ли кадр "
                    "тому, о чём идёт речь, а не буквальное ли это её изображение. "
                    "Описание кадра из раскадровки не подаётся намеренно: оно устаревает "
                    "после перерисовки."}]
        try:
            r = cl.messages.create(model=MODEL, max_tokens=1500, system=sysmsg,
                                   messages=[{"role": "user", "content": content}])
            # первым блоком ответа может прийти рассуждение модели, а не текст
            txt = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
            j = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        except Exception as e:
            rep.add("ПРЕДУПР", "vision", f"кадр {sh['id']}: {str(e)[:60]}")
            return
        i = sh["id"]
        if j.get("has_text"):
            rep.add("БРАК", "текст в кадре", f"кадр {i}: модель нарисовала читаемое")
        if j.get("matches_line") is False:
            rep.add("БРАК", "кадр не по смыслу", f"кадр {i}: {j.get('why', '')[:80]}")
        if j.get("shirt_ochre") is False:
            rep.add("БРАК", "футболка", f"кадр {i}: не сплошная охра")
        if j.get("fingers_ok") is False:
            rep.add("БРАК", "пальцы", f"кадр {i}: не пять пальцев")
        if j.get("red_on_skin"):
            rep.add("БРАК", "красный на коже", f"кадр {i}: читается как порез")
        if j.get("one_country_red") is False and "world map" not in str(sh.get("visual", "")):
            rep.add("БРАК", "карта", f"кадр {i}: красным больше одной страны")
        if j.get("country_big") is False:
            rep.add("БРАК", "карта", f"кадр {i}: страна меньше трети кадра")

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(one, shots))


def lint_board(P: Path, rep: Report, use_vision: bool) -> None:
    bp = P / "storyboard.json"
    if not bp.exists():
        rep.add("БРАК", "раскадровка", f"нет файла {bp}")
        return
    # запас и библиотека вставок — не кадры ролика, а исходники
    sb = [s for s in json.loads(bp.read_text(encoding="utf-8"))
          if s.get("block") not in ("запас", "библиотека вставок")]
    # вступительный хук — только блок «0 · хук»; «8 · Хук в конце» это финал,
    # у него правила обычного блока, а не хука
    hook = [s for s in sb if str(s.get("block", "")).strip().startswith("0 ")]
    rest = [s for s in sb if s not in hook]

    # «70–100 кадров» было написано под ролик на десять минут и на тринадцати
    # арифметически невыполнимо: при потолке 10 с на кадр минимум уже 78.
    # Смысл правила — плотность, поэтому считаем на минуту.
    # склейка реплик кадров обязана давать текст сценария: модель вернула три
    # блока пустыми, и это прошло незамеченным до просмотра глазами
    sp = script_path(P)
    if sp.exists():
        def norm(x):
            x = re.sub(r"\[[^\]]+\]", " ", x)          # служебные пометки не звучат
            return re.sub(r"[^a-z0-9]+", "", x.lower())
        said = norm(" ".join(s.get("narr") or "" for s in sb))
        want = norm(" ".join(l for b in parse_script(sp) for l in b["lines"]))
        if said != want:
            import difflib
            sm = difflib.SequenceMatcher(None, want, said, autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag == "equal":
                    continue
                miss, extra = want[i1:i2], said[j1:j2]
                where = want[max(0, i1 - 40):i1]
                if miss:
                    rep.add("БРАК", "текст потерян",
                            f"после «…{where[-40:]}» нет «{miss[:70]}»")
                if extra:
                    rep.add("БРАК", "текст лишний",
                            f"после «…{where[-40:]}» в кадрах есть «{extra[:70]}»")

    # картинка отстала от описания — молчаливое расхождение, которое видно
    # только глазами; отпечаток кладёт генератор при отрисовке
    for s in sb:
        if (s.get("kind") == "card" or s.get("clip") or not s.get("visual")
                or str(s["block"]).startswith("0 ")):
            continue
        key = f"{s.get('kind')}|{s.get('visual') or ''}|{s.get('file') or ''}"
        if s.get("drawn") != hashlib.sha1(key.encode()).hexdigest()[:10]:
            rep.add("БРАК", "кадр отстал от описания", f"кадр {s['id']}: перерисовать")

    # служебные пометки в дикторском тексте: [INSIDE], [АКЦЕНТ] и прочее
    for s in sb:
        if re.search(r"\[[^\]]+\]", s.get("narr") or ""):
            rep.add("БРАК", "служебный тег в реплике",
                    f"кадр {s['id']}: {re.search(r'\[[^\]]+\]', s['narr']).group(0)}")

    # одинаковая реплика у соседей — след неудачной склейки или дубля
    seq2 = [s for s in sb if s.get("narr")]
    for a, b in zip(seq2, seq2[1:]):
        if a["narr"].strip() == b["narr"].strip():
            rep.add("БРАК", "дубль реплики", f"кадры {a['id']} и {b['id']} говорят одно и то же")

    n = len(sb)
    mins = (sb[-1]["t_in"] + sb[-1]["dur"]) / 60 if sb else 0
    per = n / mins if mins else 0
    if mins and not 6 <= per <= 9:
        rep.add("БРАК", "плотность кадров",
                f"{n} кадров на {mins:.1f} мин = {per:.1f}/мин, норма 6–9")

    for s in rest:
        d = s.get("dur", 0)
        # потолок длины нужен, чтобы статичная картинка не висела на экране;
        # ведущий анимирован марионеткой, на него это не распространяется
        if s.get("kind") in ("hero", "card"):
            continue
        if d > 10:
            rep.add("БРАК", "длина кадра", f"кадр {s['id']}: {d:.1f} с, потолок 10")
        elif d and not 4 <= d <= 8:
            rep.add("ПРЕДУПР", "длина кадра", f"кадр {s['id']}: {d:.1f} с, норма 4–8")
    # хук режется по словам из выравнивания: 1.2–3.5 с, выход — брак.
    # Исключение: первые тридцать секунд ролика 1 собраны, утверждены и
    # пересмотру не подлежат — правило введено уже после их сборки.
    approved = (P / "cuts" / "first30.mp4").exists()
    for s in hook:
        if approved:
            break
        d = s.get("dur", 0)
        if d and not 1.2 <= d <= 3.5:
            how = "делить по границе слова" if d > 3.5 else "склеить с соседним"
            rep.add("БРАК", "хук: темп", f"кадр {s['id']}: {d:.2f} с вне 1.2–3.5 — {how}")

    is_map = lambda s: bool(re.search(r"\bmap\b|карт", str(s.get("visual", "")), re.I)
                            or "map_" in str(s.get("file", "")))

    # ведущий в кадре обязан быть анимирован марионеткой, не статикой
    for s in sb:
        if s.get("kind") != "hero":
            continue
        clip = s.get("clip")
        if not clip:
            rep.add("БРАК", "ведущий не анимирован",
                    f"кадр {s['id']}: статичный рисунок ведущего — нужен host_anim.py")
        elif not (P / clip).exists():
            rep.add("БРАК", "ведущий не анимирован", f"кадр {s['id']}: нет файла {clip}")

    # карта берётся под реплику про географию, а не вместо кадра
    maps = [s for s in sb if is_map(s)]
    # 8 было написано до того, как появились отбивки перед странами и визовая
    # четвёрка с фишками: и то и другое — заданный ритм, а не подпорка
    if len(maps) > 14:
        rep.add("БРАК", "карты", f"{len(maps)} карт на ролик, потолок 14")
    seq = [s for s in sb if s.get("dur")]
    for a, b in zip(seq, seq[1:]):
        if a in hook and b in hook:
            continue          # хук собран и утверждён, его состав не пересматриваем
        if is_map(a) and is_map(b) and not (a.get("chip") and b.get("chip")):
            rep.add("БРАК", "карты подряд", f"кадры {a['id']} и {b['id']} — две карты подряд")

    chips = [s for s in sb if s.get("chip") and not is_map(s)]
    if len(chips) > 5:
        rep.add("БРАК", "инфографика", f"{len(chips)} штук, потолок 5")

    # повторы мотивов и палитра
    hs, files = {}, {}
    for s in sb:
        f = P / (s.get("file") or f"stills/s{s['id']:03d}.jpg")
        if f.exists() and f.suffix.lower() in (".jpg", ".jpeg", ".png"):
            files[s["id"]] = f
            hs[s["id"]] = phash(f)
    # тег мотива: повтор предмета ловится раньше, чем pHash, и до отрисовки
    # словарь предметный: «chair» одинаково описывал кресло в переговорной,
    # стул в приёмной юриста и складной стул — на таком теге правило вырождается
    MOTIFS = {"drawer","card-index","filing-cabinet","shelf","pigeonhole","noticeboard",
              "whiteboard","wall-planner","door","turnstile","corridor","stairs","lift",
              "lobby","reception","meeting-room","hearing-room","waiting-room","back-room",
              "open-plan","small-office","locker","coat-rack","desk","trestle","chair",
              "folding-chair","bench","gallery","laptop","screen","keyboard","phone",
              "printer","calculator","envelope","folder","personnel-file","brief","notepad",
              "pen","hand-on-paper","waste-basket","box","trolley","tray","suitcase",
              "briefcase","backpack","passport","permit","badge","lanyard","calendar",
              "diary","clock","timecard","mug","kettle","water-jug","coins","binder",
              "map","hero","cable","window"}
    seen_motif, order_seen = {}, []
    for s in sb:
        if s.get("kind") in ("hero", "card") or is_map(s) or str(s["block"]).startswith("0 "):
            continue
        m = s.get("motif")
        if not m:
            rep.add("БРАК", "мотив не проставлен", f"кадр {s['id']}: нет поля motif")
            continue
        if m not in MOTIFS:
            rep.add("БРАК", "мотив вне списка", f"кадр {s['id']}: «{m}»")
        if s.get("callback"):
            continue
        # строгая уникальность на весь ролик невыполнима: 88 предметных кадров
        # против закрытого списка из 30 тегов. Смысл правила — соседство,
        # поэтому мотив уникален внутри блока и в окне из десяти кадров.
        prev = seen_motif.get(m)
        if prev and (prev[1] == s["block"] or len(order_seen) - prev[2] < 10):
            where = "в одном блоке" if prev[1] == s["block"] else "в окне из десяти кадров"
            rep.add("БРАК", "повтор мотива",
                    f"кадры {prev[0]} и {s['id']} — оба «{m}», {where}")
        seen_motif[m] = (s["id"], s["block"], len(order_seen))
        order_seen.append(s["id"])

    # приёмы ролика, которые по pHash выглядят повтором, но повтором не являются:
    # карта с одной красной страной — сквозной приём; карточка Remotion —
    # один и тот же лист, на котором копится текст; callback помечен вручную
    hero = {s["id"] for s in sb if s.get("kind") in ("hero", "card")
            or is_map(s) or s.get("callback") or s.get("sting")}
    ids = list(hs)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if a in hero or b in hero:
                continue
            if bin(hs[a] ^ hs[b]).count("1") <= 8:
                rep.add("БРАК", "повтор мотива", f"кадры {a} и {b} — один мотив")
    order = [s["id"] for s in sb if s["id"] in hs]
    for a, b, c in zip(order, order[1:], order[2:]):
        if all(x not in hero for x in (a, b, c)) and \
           bin(hs[a] ^ hs[b]).count("1") <= 14 and bin(hs[b] ^ hs[c]).count("1") <= 14:
            rep.add("БРАК", "мотив подряд", f"кадры {a}, {b}, {c} — три подряд об одном")

    map_ids = {s["id"] for s in sb if is_map(s)}
    for i, f in files.items():
        red, grey, off = shares(f)
        # на карте красное — само содержание, и страна обязана занимать треть
        # кадра, поэтому общий потолок 10% там физически невыполним
        cap = 0.40 if i in map_ids else 0.10
        if red > cap:
            rep.add("БРАК", "красного много", f"кадр {i}: {red*100:.0f}%, потолок {cap*100:.0f}%")
        if grey > 0.07:
            rep.add("БРАК", "серый полутон", f"кадр {i}: {grey*100:.0f}%, потолок 7%")
        if off > 0.08:
            rep.add("БРАК", "вне палитры", f"кадр {i}: {off*100:.0f}%, потолок 8%")

    # карточка рисуется Remotion поверх кадра из поля over — своего файла у неё нет
    missing = [s["id"] for s in sb
               if s["id"] not in files and not s.get("clip") and s.get("kind") != "card"]
    if missing:
        rep.add("ПРЕДУПР", "кадры не нарисованы", f"{len(missing)} шт: {missing[:12]}")

    if use_vision:
        vision([s for s in sb if s["id"] in files], P, rep)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--stage", choices=["script", "storyboard", "all"], default="all")
    ap.add_argument("--vision", action="store_true", help="проверки Opus по кадрам (платно)")
    a = ap.parse_args()
    P = Path(a.dir)
    rep = Report()
    if a.stage in ("script", "all"):
        print("— сценарий —")
        lint_script(P, rep)
    if a.stage in ("storyboard", "all"):
        print("— раскадровка —")
        lint_board(P, rep, a.vision)
    sys.exit(rep.dump())


if __name__ == "__main__":
    main()
