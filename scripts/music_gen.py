#!/usr/bin/env python3
"""Музыка и джинглы через ElevenLabs /v1/music.

Своё, а не Pixabay: на сгенерированное не прилетает Content ID.
Треки складываются в /mnt/d/youtube/music/ и переиспользуются между роликами,
поэтому генерация — редкая операция, а не часть сборки.

    python scripts/music_gen.py <имя> <длина_сек> "<описание>" [--n 3]

Даёт <имя>_1.mp3 … <имя>_N.mp3; выбранный вариант переименовать руками.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUSIC = Path("/mnt/d/youtube/music")
API = "https://api.elevenlabs.io/v1/music"
USD_PER_MIN = 0.30  # тариф eleven music, для costs.jsonl


def key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("нет ELEVENLABS_API_KEY в .env")


def compose(prompt: str, ms: int, k: str) -> bytes:
    body = json.dumps({"prompt": prompt, "music_length_ms": ms}).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"xi-api-key": k, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def log_cost(name: str, sec: float, n: int) -> None:
    import datetime
    rec = {
        "ts": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": "music", "stage": "music", "service": "elevenlabs-music",
        "usd": round(USD_PER_MIN * sec / 60 * n, 3), "units": n,
        "unit": f"{name} {sec:g} с", "note": "",
    }
    with open("/mnt/nas/output/costs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("seconds", type=float)
    ap.add_argument("prompt")
    ap.add_argument("--n", type=int, default=3, help="сколько вариантов")
    ap.add_argument("--out", default=str(MUSIC))
    args = ap.parse_args()

    k = key()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ms = int(args.seconds * 1000)

    for i in range(1, args.n + 1):
        p = out / f"{args.name}_{i}.mp3"
        p.write_bytes(compose(args.prompt, ms, k))
        print(f"  {p}  {p.stat().st_size // 1024} КБ")

    log_cost(args.name, args.seconds, args.n)
    print(f"~${USD_PER_MIN * args.seconds / 60 * args.n:.2f}")


if __name__ == "__main__":
    main()
