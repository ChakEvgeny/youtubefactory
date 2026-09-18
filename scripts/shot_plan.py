#!/usr/bin/env python3
"""План монтажа: из типа кадра в параметры сборки.

Ставит tier, движение камеры, переход и привязку картинки по правилам из
docs/montage_rules.md. Раньше это делалось руками и потому забывалось.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

TIER = {"still": "still", "video": "anim", "card": "card",
        "black": "black", "overlay": "overlay"}

# движения чередуем, чтобы камера не ездила все 20 минут в одну сторону
CYCLE = ["push", "left", "pull", "right", "push", "down"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--dissolve", type=float, default=0.6)
    a = ap.parse_args()
    d = Path(a.dir)
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))

    # Veo надёжен на руках, предметах, среде и дальних фигурах. На узнаваемом
    # лице он его деформирует: Ларсон, кадр 3; Селби, кадр 5 — исчезла челюсть.
    SAFE = ("from behind", "back of", "hands", "silhouette", "distant", "far away",
            "over the shoulder", "no people", "nobody", "insert", "close on a", "detail")
    RISK = ("face", "profile", "looking", "eyes", "expression", "portrait")
    downgraded = []

    for i, s in enumerate(r):
        s["tier"] = TIER.get(s.get("kind"), "still")
        v = (s.get("visual") or "").lower()
        if s["tier"] == "anim":
            risky = any(w in v for w in RISK) and not any(w in v for w in SAFE)
            # кадр с человеком без явной пометки, что лица не видно, тоже риск
            unclear = bool(s.get("chars")) and not any(w in v for w in SAFE)
            if risky or unclear:
                s["tier"] = "still"
                s["kind"] = "still"
                downgraded.append(s["id"])
        s.setdefault("img_id", s["id"])
        vis = (s.get("visual") or "").lower()

        # движение камеры
        if s["tier"] in ("card", "black"):
            s["fx"] = "push"; s["px_strength"] = 0.0
        elif s.get("chars") or any(w in vis for w in
                                   ("close-up", "close on", "extreme close", "hands", "face")):
            # ЛЮБОЙ кадр с человеком: только мягкий наезд.
            # DepthFlow кладёт голову и тело в разные слои глубины, и при боковом
            # проезде или полной силе голову вытягивает вперёд. Замерено на Селби,
            # кадр 5. Дальние фигуры страдают меньше, но правило общее — дешевле.
            s["fx"] = "push"
            s["px_strength"] = 0.35 if "distant" not in vis and "far away" not in vis else 0.6
        else:
            s["fx"] = CYCLE[i % len(CYCLE)]
            s["px_strength"] = 1.0

        # переход: перетекание по умолчанию, склейка после паузы и при смене места
        prev = r[i - 1] if i else None
        if prev is None:
            s["transition"] = "cut"
        elif prev.get("tier") == "black" or s["tier"] == "black":
            s["transition"] = "cut"
        elif s.get("loc") and prev.get("loc") and s["loc"] != prev["loc"]:
            s["transition"] = "cut"
        else:
            s["transition"] = "dissolve"
        s["trans_sec"] = a.dissolve if s["transition"] == "dissolve" else 0.0

    # кадр ПЕРЕД анимацией показывает ту же картинку, что и клип, и заканчивает
    # проезд в исходной точке — иначе предмет в клипе возникает из ниоткуда
    pre = 0
    for i, s in enumerate(r):
        if s["tier"] == "anim" and i and r[i - 1]["tier"] in ("still", "overlay"):
            r[i - 1]["img_id"] = s["id"]
            r[i - 1]["end_neutral"] = True
            r[i - 1]["fx"] = "push"
            pre += 1

    (d / "timed.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    c = Counter(s["tier"] for s in r)
    t = Counter(s["transition"] for s in r)
    print(f"кадров {len(r)}: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    print(f"переходы: " + ", ".join(f"{k} {v} ({v/len(r)*100:.0f}%)" for k, v in t.most_common()))
    print(f"подводок к анимации: {pre}")
    if downgraded:
        print(f"снято с анимации из-за риска лица: {len(downgraded)} — "
              + ", ".join(str(x) for x in downgraded[:25]) + (" …" if len(downgraded) > 25 else ""))


if __name__ == "__main__":
    main()
