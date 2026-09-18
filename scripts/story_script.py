#!/usr/bin/env python3
"""Сценарий + посекундная раскадровка по brief.json.

Два прохода: текст пишет claude-fable-5-1 по формуле ниши, раскадровку
размечает claude-opus-5. Тайминги НЕ придумывает модель — они считаются на
Python из числа слов при замеренном темпе 138 сл/мин.
Ниже Opus моделей в конвейере нет.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block
from pipeline import costs

WRITER = "claude-fable-5-1"
MARKER = "claude-opus-5"
WPM = 138.0

BASE = """Ты пишешь закадровый текст документального ролика на 20-22 минуты для канала
в стиле Lume / PLAN: ESCAPE / Atlas One. Английский, носитель языка. Рубленые короткие
предложения. Настоящее время для сцен, прошедшее — для контекста. 138 слов в минуту.

СКЕЛЕТ ХУКА (снят с четырёх взлетевших роликов, соблюдать дословно по структуре):
1. Первая фраза — координата: место и год в настоящем времени, без приветствия,
   без названия канала, без «в этом видео». Пример ритма: "In the middle of the Indian
   Ocean, a strip of white sand barely rises above the water."
2. Отрицание тремя пунктами: "No trees, no river, no shade." либо
   "They aren't window washers and they aren't stuntmen."
3. Бытовой предмет-оружие, названный буквально и без пояснений.
4. Счётчик: срок или число, повторяемый рефреном по ролику.
5. Имя героя — не раньше 40-й секунды. В хуке герой безымянный: "a man", "a seamstress".
6. Два вопроса-обещания, ответ на которые откладывается до финала.

АРКА: холодное открытие → титульная карточка (кто, сколько, как долго) → бэкстори и
мотив → ликбез о системе-антагонисте, поданной как непобедимая → ядро (40-58% длины,
максимальная плотность деталей и цифр) → пик → перелом → протокол последствий сухой
строкой → эпилог или открытая петля → один-два афоризма-перевёртыша, закрывающих
крючок из хука.

ПРИНЦИП ПОДАЧИ. Если в брифе задан FORM — строить ролик по нему, а не по хронологии.
Форма это способ рассказа, а не порядок событий: лестница растущих ставок, две цифры,
гонящиеся друг за другом, инструкция по шагам. Заданная форма должна быть слышна в
каждом блоке, а её единица (ставка, километр, шаг) — повторяться рефреном.

ПЕРВЫЕ ТРИ МИНУТЫ. Замерено на кривой удержания вышедшего фильма: после хука
зритель уходит там, где начинается биография. Поэтому с 1:00 до 3:00 запрещены дата
рождения, место рождения и перечисление прежних работ героя. Сразу после титульной
карточки идёт ПЕРВАЯ ПОПЫТКА героя и её результат — то, ради чего зритель остался.
Биографию раздробить на две-три строки и вплести туда, где уже что-то происходит.

ПРАВИЛО ПОВОРОТА. В каждом блоке между [BEAT] отметь про себя положение дел в начале
и в конце. Если знак не изменился — блок существует только ради изложения фактов;
такой блок вырезать, а факты вплести в соседний блок, где что-то происходит.
Прямое следствие: механику системы НЕ объяснять отдельной лекцией. Механика вводится
через попытку, которая провалилась, — зритель понимает правило по тому, как оно НЕ
сработало. Это сильнее любого объяснения.

ПРОТИВНИК НЕ ОДИН. Выстроить минимум три силы, давящие с разных сторон: институт и его
процедуры; конкурент, который хочет того же и другим способом ломает общий ресурс;
и тот, кто ничего не нарушал, но всем этим закончил. Препятствие (буря, расстояние,
физический объём работы) противником не считается — это среда.

ПРИЁМЫ: ретардация главного вопроса; гиперточность (дата, час, сумма, расстояние);
каскад некруглых цифр; «а вот чего они не знали»; контраст масштабов; второе лицо к
зрителю один-два раза; рефрен; опись как драматургия финала.

НЕЛЬЗЯ: приветствия, «в этом видео», просьбы подписаться до финала, круглые суммы там,
где есть точные, усилители (incredible, shocking, insane, unbelievable), морализаторство,
мораль «преступление не окупается», выдуманные факты. Каждый фактический тезис — из BRIEF.
Где факта нет — прямо говори, что документы молчат, и не выдумывай.

РАЗМЕТКА. Перед каждым смысловым фрагментом отдельной строкой:
[BEAT: hook|title|backstory|system|core|peak|turn|aftermath|epilogue]
РАСКАДРОВКА. Каждые 2-4 предложения (8-15 секунд речи) отдельной строкой ОДИН кадр:
[SHOT: описание для художника, на английском, 10-25 слов: кто в кадре (HERO / nobody /
officer / crowd), где, что делает | wide|medium|close|insert]
"""

LANES = {
 "heists": """ЖАНР: человек обыграл институт вниманием, не нарушив правил. Антагонист — организация
и её процедуры. Автор не судит и не восхищается прямым текстом, ирония только через
сопоставление фактов. Финал без триумфа.""",
 "survival": """ЖАНР: человек против среды, со счётчиком времени. Антагонист — не природа сама по себе,
а чужой замысел и чужая самоуверенность, из-за которых герой там оказался. Без натурализма:
смерть и болезнь называем фактом одной строкой, без описания тел и физиологии. Финал без
триумфа и без морали.""",
}


def stream(client, model, system, prompt, max_tokens=16000):
    out = []
    with client.messages.stream(model=model, max_tokens=max_tokens, system=system,
                                messages=[{"role": "user", "content": prompt}]) as s:
        for t in s.text_stream:
            out.append(t)
        msg = s.get_final_message()
    return "".join(out), msg.usage, msg.stop_reason


def spoken_words(text: str) -> int:
    t = re.sub(r"^\[(BEAT|SHOT)[^\]]*\]\s*$", "", text, flags=re.M)
    return len(re.sub(r"\[[^\]]*\]", " ", t).split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--lane", choices=list(LANES), required=True)
    ap.add_argument("--minutes", type=float, default=21.0)
    ap.add_argument("--resume", action="store_true", help="дописать существующий script.md")
    ap.add_argument("--mark-only", action="store_true", help="только раскадровка по готовому script.md")
    a = ap.parse_args()
    d = Path(a.dir)
    brief = json.loads((d / "brief.json").read_text(encoding="utf-8"))
    words = int(a.minutes * WPM)
    facts = "\n".join(f"- {f['fact']}" + (f" [{f['number']}]" if f.get("number") else "")
                      for f in brief["facts"])
    conf = brief.get("conflicts") or []
    client = anthropic.Anthropic()
    spent = 0.0

    # утверждённая история: форма подачи, порядок блоков, обязательная сцена.
    # Она главнее общей АРКИ из BASE — от неё не отклоняться.
    sf = d / "story.md"
    story = ""
    if sf.exists():
        story = ("\nУТВЕРЖДЁННАЯ ИСТОРИЯ — следовать ей по порядку блоков и по форме подачи.\n"
                 "Она важнее общей АРКИ: где они расходятся, побеждает эта.\n"
                 "Ничего не добавлять сверх фактов брифа; где в истории сказано, что документы\n"
                 "молчат — так и говорить, а не додумывать.\n\n"
                 + sf.read_text(encoding="utf-8") + "\n\n")

    prompt = (f"ИСТОРИЯ: {brief['topic']}\n\nУГОЛ ПОДАЧИ: {brief['angle']}\n\n"
              f"ЦЕЛЕВАЯ ДЛИНА: {a.minutes:.0f} минут, это примерно {words} слов при 138 сл/мин.\n"
              + (("\nПРОТИВОРЕЧИЯ В ИСТОЧНИКАХ (решения обязательны):\n" + "\n".join(f"- {c}" for c in conf) + "\n") if conf else "")
              + f"\nBRIEF — только эти факты, ничего сверх них:\n{facts}\n\n"
              + story
              + "Напиши сценарий с разметкой [BEAT] и [SHOT].")
    system = BASE + "\n" + LANES[a.lane]
    sp = d / "script.md"
    text = sp.read_text(encoding="utf-8") if (a.resume or a.mark_only) and sp.exists() else ""
    if not a.mark_only:
        if not text:
            print("· пишу сценарий…", flush=True)
            text, u, _ = stream(client, WRITER, system, prompt)
            spent += claude_cost(WRITER, u)
            sp.write_text(text, encoding="utf-8")
            print(f"  слов {spoken_words(text)} → ~{spoken_words(text)/WPM:.1f} мин", flush=True)
        # дописываем, пока не наберём целевой объём: модель упирается в лимит токенов
        for attempt in range(8):
            n = spoken_words(text)
            if n >= words * 0.88:
                break
            left = words - n
            print(f"  · дописываю, не хватает ~{left} слов (попытка {attempt+1})", flush=True)
            cont = (prompt + "\n\nУЖЕ НАПИСАНО (не повторять, продолжить ровно с обрыва):\n"
                    + text[-3000:]
                    + f"\n\nПродолжи сценарий с этого места и доведи до конца. Осталось примерно "
                      f"{left} слов. Та же разметка [BEAT] и [SHOT]. Не повторяй уже написанное, "
                      "не начинай заново, не пиши вступление. Если это последний кусок — закончи "
                      "эпилогом и афоризмом-перевёртышем.")
            add, u, _ = stream(client, WRITER, system, cont)
            spent += claude_cost(WRITER, u)
            if spoken_words(add) < 40:
                break
            text = text.rstrip() + "\n\n" + add.lstrip()
            sp.write_text(text, encoding="utf-8")
        n = spoken_words(text)
        print(f"  итого слов {n} → ~{n/WPM:.1f} мин", flush=True)

    print("· размечаю кадры…", flush=True)

    # 1) кадры парсим из сценария кодом — модель их не выдумывает
    parsed, cur = [], None
    for ln in text.split("\n"):
        m = re.match(r"^\[SHOT:\s*(.+?)\s*\]\s*$", ln.strip())
        if m:
            body = m.group(1)
            desc, _, framing = body.rpartition("|")
            cur = {"desc": (desc or body).strip(), "framing": framing.strip(), "narr": ""}
            parsed.append(cur)
            continue
        if ln.strip().startswith("[BEAT"):
            continue
        if cur is not None and ln.strip():
            cur["narr"] += (" " if cur["narr"] else "") + ln.strip()
    parsed = [x for x in parsed if x["narr"]]
    print(f"  кадров в сценарии {len(parsed)}, слов {sum(len(x['narr'].split()) for x in parsed)}", flush=True)

    mark_sys = ("Ты режиссёр раскадровки для конвейера, который генерирует кадры нейросетью. "
                "Жёсткие ограничения нашего рендера, нарушать нельзя:\n"
                "- одно простое действие на кадр; без открывающихся дверей, без передачи предметов "
                "из рук в руки, без поворотов больше четверти оборота, без ходьбы на камеру;\n"
                "- камера статична или очень медленный наезд;\n"
                "- нейросеть НИКОГДА не рисует текст и цифры: если в кадре нужен документ, экран, "
                "табло, карта или вывеска — kind \"card\", а текст укажи в card_text, мы напечатаем сами;\n"
                "- лицо героя показываем редко: предпочитай руки, спину, силуэт, общий план, предмет;\n"
                "- помещения с людьми населяем, пустые залы выглядят неправильно;\n"
                "- у героя в каждом кадре своё состояние, слово \"tired\" по умолчанию запрещено.\n"
                "\nТИП КАДРА — САМОЕ ВАЖНОЕ РЕШЕНИЕ, от него зависит и цена, и ритм.\n"
                "Доли по фильму держать примерно такими, это замерено на вышедших фильмах:\n"
                "  still — 50-60% кадров. Сгенерированная картинка, оживляется движением камеры.\n"
                "          ЭТО ЗНАЧЕНИЕ ПО УМОЛЧАНИЮ. Не уверен — ставь still.\n"
                "  video — НЕ БОЛЬШЕ 25%. Клип нейросети. Ставить ТОЛЬКО когда движение и есть\n"
                "          содержание кадра: человек делает то, о чём говорит текст; среда движется\n"
                "          как событие (буря, огонь, вода, толпа). Если движение можно выкинуть и\n"
                "          кадр не потеряет смысл — это still, а не video.\n"
                "  card  — 12-25%. Только там, где в кадре нужен текст, число, документ или табло.\n"
                "  black — 3-5%. Чёрный кадр-пауза перед датой, перед переломом и на границе акта.\n"
                "          narr у такого кадра пустой.\n"
                "Кадр, где человек просто стоит, сидит, смотрит или держит предмет, — всегда still.\n"
                "Кадр, где сказано что документов нет или что никто не знает, — всегда still, он стоит намертво.")

    def split_batch(batch, idx0):
        payload = [{"i": idx0 + j, "shot": x["desc"], "framing": x["framing"], "narr": x["narr"]}
                   for j, x in enumerate(batch)]
        pr = ("Раздроби каждый кадр на несколько так, чтобы на один кадр приходилось 4-8 секунд речи "
              "при темпе 138 слов в минуту, то есть примерно 9-18 слов. Текст не менять и не сокращать: "
              "объединение narr подкадров должно дословно давать narr исходного кадра.\n"
              "Верни ТОЛЬКО JSON-объект вида {\"<i>\": [подкадры...]}, ключ — исходный номер i, "
              "значение — массив подкадров. Каждый подкадр: "
              "{\"narr\":\"...\",\"visual\":\"промпт на английском 15-35 слов\","
              "\"motion\":\"одно простое действие на английском\","
              "\"kind\":\"video\"|\"still\"|\"card\",\"state\":\"\",\"card_text\":\"\"}\n\n"
              + json.dumps(payload, ensure_ascii=False))
        for _ in range(3):
            out, u2, stop = stream(client, MARKER, mark_sys, pr, max_tokens=32000)
            budget["usd"] += claude_cost(MARKER, u2)
            if not out.strip():
                print(f"    пустой ответ (stop={stop}), повтор", flush=True)
                continue
            try:
                res = parse_json_block(out)
            except Exception as e:
                print(f"    повтор: {str(e)[:60]}", flush=True)
                continue
            if isinstance(res, dict) and all(str(x["i"]) in res for x in payload):
                return res
            print("    неполный ответ, повтор", flush=True)
        return None

    budget = {"usd": 0.0}
    shots = []
    STEP = 6
    for i in range(0, len(parsed), STEP):
        batch = parsed[i:i + STEP]
        res = split_batch(batch, i)
        if res is None:                      # не поддалось — берём исходные кадры как есть
            for x in batch:
                shots.append({"narr": x["narr"], "visual": x["desc"], "motion": "very slow push-in",
                              "kind": "still", "state": "", "card_text": "", "beat": ""})
            print(f"  · {i//STEP+1}: fallback, кадров {len(batch)}", flush=True)
            continue
        for j, x in enumerate(batch):
            subs = res[str(i + j)]
            shots += subs if isinstance(subs, list) else [subs]
        print(f"  · {i//STEP+1}/{(len(parsed)+STEP-1)//STEP}: кадров {len(shots)}", flush=True)
    spent += budget["usd"]

    t = 0.0
    rows = []
    for i, s in enumerate(shots, 1):
        w = len((s.get("narr") or "").split())
        dur = max(w / WPM * 60, 2.0)
        rows.append({**s, "id": i, "t_in": round(t, 1), "t_out": round(t + dur, 1),
                     "dur": round(dur, 1), "words": w})
        t += dur
    (d / "timed.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    def mmss(x):
        return f"{int(x)//60:02d}:{int(x)%60:02d}"

    md = [f"# Посекундная раскадровка — {d.name}", "",
          f"Кадров {len(rows)}, длительность {mmss(t)} при темпе 138 слов в минуту.",
          "Тайминги расчётные; точные придут после озвучки.", "",
          "| # | время | тип | что слышно | что видим | движение |",
          "|---:|---|---|---|---|---|"]
    for r in rows:
        narr = (r.get("narr") or "").replace("|", "/").strip()
        vis = (r.get("visual") or "").replace("|", "/")
        if r.get("card_text"):
            vis += f" · КАРТОЧКА: {r['card_text']}"
        if r.get("state"):
            vis += f" · состояние: {r['state']}"
        md.append(f"| {r['id']} | {mmss(r['t_in'])}–{mmss(r['t_out'])} | {r['kind']} | {narr} | {vis} | "
                  f"{(r.get('motion') or '').replace('|','/')} |")
    (d / "timed.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"  кадров {len(rows)}, хронометраж {mmss(t)}")
    print(f"· готово, ${spent:.2f}")
    costs.log(costs.project_of(d), "script", WRITER + "+" + MARKER, spent)


if __name__ == "__main__":
    main()
