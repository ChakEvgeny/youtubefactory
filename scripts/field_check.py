#!/usr/bin/env python3
"""Проверка конкурентного поля темы ДО производства.

Смысл: мы трижды заходили в тему, где верхние ролики держат миллионы просмотров.
Поиск — единственная органическая дверь для канала без подписчиков, и в занятой
теме она закрыта. Проверять на этапе брифа, а не после публикации.

  python scripts/field_check.py "jerry selbee lottery" "cash winfall loophole"
  python scripts/field_check.py --dir /mnt/d/youtube/output/heists/2026-09-15_...
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FMT = "%(view_count)s|%(duration)s|%(channel)s|%(title)s"


def search(q: str, n: int = 8) -> list[dict]:
    try:
        out = subprocess.run(["yt-dlp", "--flat-playlist", "--print", FMT, f"ytsearch{n}:{q}"],
                             capture_output=True, text=True, timeout=120).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ! {q}: {type(e).__name__}"); return []
    rows = []
    for line in out.splitlines():
        p = line.strip().split("|", 3)
        if len(p) < 4:
            continue
        try:
            rows.append({"views": int(p[0]), "dur": int(p[1]), "chan": p[2], "title": p[3]})
        except ValueError:
            continue
    return rows


def verdict(top: int, longest: int) -> tuple[str, str]:
    if top >= 1_000_000:
        return "НЕ БРАТЬ", "тему держат каналы-миллионники, поиск закрыт"
    if top >= 500_000:
        return "риск", "верх занят прочно, нужен другой угол или другая тема"
    if top >= 150_000:
        return "можно", "лидер сильный, но поле не монолитное"
    return "хорошее поле", "лидера нет, место свободно"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="*", help="поисковые запросы по теме")
    ap.add_argument("--dir", default="", help="папка проекта: запросы возьмутся из brief.json")
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args()

    qs = list(a.queries)
    if a.dir:
        b = json.loads((Path(a.dir) / "brief.json").read_text(encoding="utf-8"))
        qs += b.get("search_queries") or [b.get("topic", "")]
    qs = [q for q in qs if q.strip()]
    if not qs:
        sys.exit("не заданы запросы")

    all_rows, seen = [], set()
    for q in qs:
        print(f"\n=== {q}")
        for r in search(q, a.n):
            key = (r["chan"], r["title"])
            mark = "  " if key in seen else "* "
            if key not in seen:
                seen.add(key); all_rows.append(r)
            print(f" {mark}{r['views']:>10,} | {r['dur']//60:>2}:{r['dur']%60:02d} | "
                  f"{r['chan'][:22]:22} | {r['title'][:46]}")

    if not all_rows:
        sys.exit("\nничего не нашлось")
    all_rows.sort(key=lambda x: -x["views"])
    top = all_rows[0]["views"]
    longs = [r for r in all_rows if r["dur"] >= 900]
    v, why = verdict(top, max((r["dur"] for r in longs), default=0))

    print("\n" + "─" * 66)
    print(f"уникальных роликов: {len(all_rows)}")
    print(f"верхний: {top:,} — {all_rows[0]['title'][:44]}")
    print(f"медиана топ-10: {sorted((r['views'] for r in all_rows), reverse=True)[:10][-1]:,}")
    print(f"длинных (15 мин+): {len(longs)} из {len(all_rows)}"
          + (f", лучший {max(longs, key=lambda r: r['views'])['views']:,}" if longs else " — ниша длинного формата свободна"))
    print(f"\nВЕРДИКТ: {v} — {why}")


if __name__ == "__main__":
    main()
