"""Журнал затрат. Одна строка JSONL на каждый оплаченный вызов.

Лежит на NAS, чтобы переживал чистку диска D после архивации проекта.
Если NAS не смонтирован — пишем локально, при следующем запуске сольётся.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path

NAS = Path("/mnt/nas/output/costs.jsonl")
LOCAL = Path.home() / "yt" / ".costs_pending.jsonl"


def _target() -> Path:
    try:
        NAS.parent.mkdir(parents=True, exist_ok=True)
        return NAS
    except OSError:
        return LOCAL


def log(project: str, stage: str, service: str, usd: float,
        units: float = 0.0, unit: str = "", note: str = "") -> None:
    """project — имя папки проекта, stage — этап конвейера, service — что оплачено."""
    if not usd:
        return
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "project": project, "stage": stage, "service": service,
           "usd": round(float(usd), 4), "units": units, "unit": unit, "note": note}
    t = _target()
    with t.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # если NAS вернулся — сливаем накопленное локально
    if t is NAS and LOCAL.exists():
        with NAS.open("a", encoding="utf-8") as f:
            f.write(LOCAL.read_text(encoding="utf-8"))
        LOCAL.unlink()


def project_of(d) -> str:
    return Path(d).name
