#!/usr/bin/env python3
"""Покадровый сценарий на русском: что слышно, кто говорит, что видим,
и чем кадр делается — анимацией, фотографией с движением камеры или карточкой."""
from __future__ import annotations
import json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block

MODEL = "claude-opus-5"
KIND = {"video": "анимация", "still": "фото + движение", "card": "карточка"}


def batch(client, rows, budget):
    pr = ("Переведи на русский. Это покадровый сценарий документального фильма. "
          "Для каждого кадра дай два поля: sound — что звучит (закадровый текст или реплика), "
          "перевод точный, тон сухой документальный; view — что видно в кадре, коротко, "
          "до 15 слов, назывными фразами.\n"
          'Верни ТОЛЬКО JSON {"<i>": {"sound": "...", "view": "..."}} со всеми ключами.\n\n'
          + json.dumps(rows, ensure_ascii=False))
    for _ in range(3):
        with client.messages.stream(model=MODEL, max_tokens=16000,
                                    messages=[{"role": "user", "content": pr}]) as s:
            out = "".join(t for t in s.text_stream)
            m = s.get_final_message()
        budget["usd"] += claude_cost(MODEL, m.usage)
        if not out.strip():
            continue
        try:
            res = parse_json_block(out)
        except Exception:
            continue
        if isinstance(res, dict) and all(str(x["i"]) in res for x in rows):
            return res
    return {}


def main():
    d = Path(sys.argv[1])
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    cast = json.loads((d / "cast.json").read_text(encoding="utf-8")) if (d / "cast.json").exists() else {}
    names = {k: v.get("name", k) for k, v in cast.items() if isinstance(v, dict)}
    client = anthropic.Anthropic()
    budget = {"usd": 0.0}
    rows = [{"i": s["id"], "sound": s.get("narr", ""), "view": s.get("visual", "")} for s in r]
    chunks = [rows[i:i + 20] for i in range(0, len(rows), 20)]
    tr = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(lambda c: batch(client, c, budget), chunks):
            tr.update(res)
    print(f"переведено {len(tr)}/{len(rows)}, ${budget['usd']:.2f}")

    mm = lambda x: f"{int(x)//60:02d}:{int(x)%60:02d}"
    n_v = sum(1 for s in r if s["kind"] == "video")
    n_s = sum(1 for s in r if s["kind"] == "still")
    n_c = sum(1 for s in r if s["kind"] == "card")
    md = [f"# Покадровый сценарий — {d.name}", "",
          f"Кадров {len(r)}, хронометраж {mm(r[-1]['t_out'])}.",
          f"Анимация {n_v}, фото с движением {n_s}, карточки {n_c}.", "",
          "**Анимация** — клип Veo, в кадре действительно двигаются люди и предметы.",
          "**Фото + движение** — сгенерированная картинка, оживляется медленным наездом или сдвигом кадра.",
          "**Карточка** — текст печатаем сами, нейросеть к нему не подпускаем.", "",
          "| # | время | тип | голос | что слышно | что видим |",
          "|---:|---|---|---|---|---|"]
    for s in r:
        t = tr.get(str(s["id"]), {})
        who = names.get(s.get("speaker", "narrator"), s.get("speaker", ""))
        if s.get("speaker", "narrator") != "narrator":
            who = f"**{who}**"
        view = (t.get("view") or s.get("visual", ""))[:120].replace("|", "/")
        if s.get("card_text"):
            view = "текст: " + s["card_text"].replace("\n", " / ")
        md.append(f"| {s['id']} | {mm(s['t_in'])} | {KIND.get(s['kind'], s['kind'])} | {who} | "
                  f"{(t.get('sound') or s.get('narr','')).replace('|','/')} | {view} |")
    (d / "SCENARIO_RU.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("готово:", d / "SCENARIO_RU.md")


if __name__ == "__main__":
    main()
