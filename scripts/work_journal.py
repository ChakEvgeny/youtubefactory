#!/usr/bin/env python3
"""Журнал правок раскадровки: что просили, что сделано, что отклонено.

Четыре правки из ревью терялись молча: в отчёте они значились внесёнными, в
раскадровке их не было. Журнал делает перенос проверяемым — у каждой строки
статус, а `applied` обязана двигать `visual`, иначе отпечаток не сдвинется.

    python scripts/work_journal.py <папка> --add "922|карта штатов, Монтана красная|ревью|pending"
    python scripts/work_journal.py <папка> --check
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path


def load(P: Path) -> list:
    f = P / "edits.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save(P: Path, rows: list) -> None:
    (P / "edits.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--add", action="append", default=[],
                    help="шот|что|откуда|статус[|причина]")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    P = Path(a.dir)
    rows = load(P)
    now = datetime.date.today().isoformat()

    for line in a.add:
        parts = (line.split("|") + ["", "", "", "", ""])[:5]
        rows.append({"shot": parts[0].strip(), "what": parts[1].strip(),
                     "from": parts[2].strip(), "status": parts[3].strip() or "pending",
                     "why": parts[4].strip(), "date": now})
    if a.add:
        save(P, rows)

    sb = {s["id"]: s for s in json.loads((P / "storyboard.json").read_text(encoding="utf-8"))}
    bad = []
    for r in rows:
        if r["status"] != "applied" or not r["shot"].isdigit():
            continue
        s = sb.get(int(r["shot"]))
        if s is None:
            bad.append((r["shot"], "шота нет в раскадровке"))
        elif s.get("kind") not in ("card",) and not s.get("visual"):
            bad.append((r["shot"], "applied, но описания нет"))
    from collections import Counter
    c = Counter(r["status"] for r in rows)
    print(f"строк {len(rows)}: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    for s, why in bad:
        print(f"  ! шот {s}: {why}")
    if a.check:
        for r in rows:
            mark = {"applied": "✓", "rejected": "✗", "pending": "·"}.get(r["status"], "?")
            print(f"  {mark} {r['shot']:>5}  {r['what'][:58]:<58} {r['from']:<8} {r['why'][:40]}")


if __name__ == "__main__":
    main()
