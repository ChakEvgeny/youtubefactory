#!/usr/bin/env python3
"""Всё для загрузки ролика одним текстовым файлом: release.txt.

Пожелание Евгения 2026-09-18: заголовок, запасные заголовки, описание и теги —
в одном файле, а не в четырёх. Собирается из title_en.txt, title_alt.txt,
description.md, tags.txt и thumbs/ папки ролика.

  python scripts/release_pack.py <папка ролика> [<папка> ...]
"""
from __future__ import annotations
import sys
from pathlib import Path


def pack(d: Path) -> Path:
    rd = lambda n: (d / n).read_text(encoding="utf-8").strip() if (d / n).exists() else ""
    alts = [l for l in rd("title_alt.txt").splitlines() if l.strip() and not l.startswith("#")]
    thumbs = sorted(p.name for p in (d / "thumbs").glob("thumb_*.jpg")) if (d / "thumbs").exists() else []
    film = next(iter(sorted(d.glob("FILM_*.mp4"))), None)
    parts = [f"ВИДЕО: {film.name if film else '—'}",
             f"ОБЛОЖКИ: {', '.join(thumbs) or '—'}  (папка thumbs/)",
             "", "=== ЗАГОЛОВОК ===", rd("title_en.txt"),
             "", "=== ЗАПАСНЫЕ ЗАГОЛОВКИ (A/B) ===", *(alts or ["—"]),
             "", "=== ОПИСАНИЕ ===", rd("description.md"),
             "", "=== ТЕГИ ===", rd("tags.txt"),
             "", "=== НАСТРОЙКИ ===", "Категория: Образование. Язык видео: English (US).",
             "Субтитры и переводы: после публикации — scripts/yt_publish.py captions/meta."]
    out = d / "release.txt"
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(pack(Path(a)))
