#!/usr/bin/env python3
"""Раскадровка Terms of Employment прямо из покадрового script.txt.

`work_board.py` просит модель разбить прозу на кадры. Здесь разбивать нечего:
сценарий уже покадровый, описания написаны руками, и задача чисто механическая —
перенести их в board.json, не потеряв полей, которых у прежнего формата не было:

  ЗАСТАВКА: TEXT   → шот kind=title перед первым кадром блока
  ТЕКСТ: DECEMBER  → allow_text + точные знаки, которые можно писать в кадре
  СВЯЗЬ: …         → person_ref (тот же человек) и ref (тот же кадр/место)

  python scripts/work_board_txt.py <папка>
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

POSE = {"desk": ("anim/desk_refs/desk3.jpg", "visemesD2", "D2_patch.json")}
TITLE_SEC = 2.4


def parse(p: Path):
    blk, title, shots, cur, field = None, None, [], None, None
    for ln in p.read_text(encoding="utf-8").split("\n"):
        st = ln.strip()
        m = re.match(r"^═══ БЛОК (\d+) · (.+?) ═══$", st)
        if m:
            blk, title = f"БЛОК {m.group(1)} · {m.group(2)}", None
            continue
        if st.startswith("ЗАСТАВКА:"):
            title = st[9:].strip(); continue
        m = re.match(r"^\[(\d+)\] (\w+)$", st)
        if m:
            cur = {"id": int(m.group(1)), "tag": m.group(1), "kind": m.group(2),
                   "block": blk, "narr": "", "narr_ru": "", "visual": "",
                   "card": "", "text": "", "link": ""}
            if title:
                cur["_title"] = title; title = None
            shots.append(cur); field = None
            continue
        if cur is None:
            continue
        for tag, key in (("EN:", "narr"), ("RU:", "narr_ru"), ("КАДР:", "visual"),
                         ("КАРТОЧКА:", "card"), ("ТЕКСТ:", "text"), ("СВЯЗЬ:", "link")):
            if st.startswith(tag):
                cur[key] = st[len(tag):].strip(); field = key
                break
        else:
            if st.startswith("ФАКТ:") or st.startswith(">>>"):
                field = None
            elif field and st:
                cur[field] += " " + st
    return shots


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", default="board.json")
    a = ap.parse_args()
    P = Path(a.dir)
    raw = parse(P / "script.txt")

    board = []
    # заставка вставляется ПЕРЕД своим шотом, поэтому идёт внутри того же прохода
    for s in raw:
        title = s.get("_title")
        if title:
            n = int(s["block"].split()[1].rstrip(" ·")) * 100
            board.append({"id": n, "tag": f"t{n}", "kind": "title", "block": s["block"],
                          "narr": "", "narr_ru": "", "text": title, "dur": TITLE_SEC})
        sh = {"id": s["id"], "tag": s["tag"], "block": s["block"],
              "narr": s["narr"].strip(), "narr_ru": s["narr_ru"].strip()}
        if s["kind"] in ("host", "host_inside"):
            f, v, pt = POSE["desk"]
            sh.update(kind="hero", visual="", pose="desk", file=f, visemes=v, patch=pt,
                      speed=1.0 if s["kind"] == "host_inside" else 1.0)
        elif s["kind"] == "card":
            sh.update(kind="card", visual=s["visual"], card=s["card"])
            # карточка — накладка ПОВЕРХ соседнего кадра, а не свой рисунок:
            # без поля over сборка ищет stills/s<id>.jpg, которого нет
            m = re.search(r"поверх кадра (\d+)", s["visual"])
            if m:
                sh["over"] = f"stills/s{int(m.group(1)):03d}.jpg"
        elif s["kind"] == "pause":
            sh.update(kind="pause", visual="", dur=0.8)
        else:
            sh.update(kind="scene", visual=s["visual"])
        if s["text"]:
            sh["allow_text"] = True
            sh["text_exact"] = s["text"]
        # СВЯЗЬ: «место … как в кадре N» держит композицию, «ГЕРОЙ как в кадре N» — человека
        for part in s["link"].split(";"):
            m = re.search(r"как в кадре (\d+)", part)
            if not m:
                continue
            (sh.__setitem__("ref", int(m.group(1))) if "место" in part
             else sh.setdefault("person_ref", int(m.group(1))))
        board.append(sh)

    (P / a.out).write_text(json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8")
    import collections
    print(f"{a.out}: шотов {len(board)}", dict(collections.Counter(x["kind"] for x in board)))


if __name__ == "__main__":
    main()
