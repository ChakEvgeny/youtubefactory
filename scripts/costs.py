#!/usr/bin/env python3
"""Отчёт по затратам: сколько стоил каждый фильм и всё вместе."""
from __future__ import annotations
import argparse, json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.costs import NAS, LOCAL


def rows():
    for p in (NAS, LOCAL):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not r.get("project", "").startswith("_selftest"):
                yield r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="", help="только этот проект")
    ap.add_argument("--by", choices=["service", "stage"], default="service")
    a = ap.parse_args()

    per = defaultdict(lambda: defaultdict(float))
    for r in rows():
        if a.project and a.project not in r["project"]:
            continue
        per[r["project"]][r[a.by]] += r["usd"]
    if not per:
        print("журнал пуст"); return

    total = 0.0
    for proj in sorted(per):
        s = sum(per[proj].values()); total += s
        print(f"\n{proj}  —  ${s:.2f}")
        for k, v in sorted(per[proj].items(), key=lambda x: -x[1]):
            print(f"    {k:22} ${v:>8.2f}   {v/s*100:4.1f}%")
    print(f"\n{'ВСЕГО':24} ${total:.2f}   фильмов: {len(per)}")
    if len(per):
        print(f"{'в среднем на фильм':24} ${total/len(per):.2f}")


if __name__ == "__main__":
    main()
