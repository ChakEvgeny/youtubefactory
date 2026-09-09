"""Общее: пути, кэш, учёт стоимости, безопасное логирование."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha1(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def slugify(text: str, maxlen: int = 60) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return (t[:maxlen] or "untitled").rstrip("-")


def mask(value: str) -> str:
    """Ключи в логи не попадают никогда — только факт наличия."""
    return "задан" if value else "ПУСТО"


def human_money(v: float) -> str:
    return f"${v:.4f}" if v < 0.01 else f"${v:.2f}"


class Cache:
    """Файловый кэш в CACHE_DIR. Ключ — sha1, значение — json или бинарь."""

    def __init__(self, root: Path, ttl_hours: float | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_hours

    def _p(self, ns: str, key: str, ext: str) -> Path:
        d = self.root / ns
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}{ext}"

    def fresh(self, path: Path, ttl_hours: float | None = None) -> bool:
        ttl = self.ttl if ttl_hours is None else ttl_hours
        if not path.exists():
            return False
        if ttl is None:
            return True
        return (time.time() - path.stat().st_mtime) < ttl * 3600

    def get_json(self, ns: str, key: str, ttl_hours: float | None = None):
        p = self._p(ns, key, ".json")
        if self.fresh(p, ttl_hours):
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def put_json(self, ns: str, key: str, data) -> Path:
        p = self._p(ns, key, ".json")
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return p

    def blob_path(self, ns: str, key: str, ext: str) -> Path:
        return self._p(ns, key, ext)


@dataclass
class CostLog:
    """Стоимость по стадиям. Пишется в passport.json."""
    items: list = field(default_factory=list)

    def add(self, stage: str, what: str, usd: float, detail: str = ""):
        self.items.append({"stage": stage, "what": what, "usd": round(usd, 6),
                           "detail": detail, "at": utcnow().isoformat()})

    def by_stage(self) -> dict:
        out: dict = {}
        for i in self.items:
            out[i["stage"]] = round(out.get(i["stage"], 0.0) + i["usd"], 6)
        return out

    @property
    def total(self) -> float:
        return round(sum(i["usd"] for i in self.items), 6)

    def to_json(self) -> dict:
        return {"by_stage": self.by_stage(), "total": self.total, "items": self.items}


# Тарифы Claude API, $/1M токенов (вход, выход)
CLAUDE_PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def claude_cost(model: str, usage) -> float:
    pi, po = CLAUDE_PRICES.get(model, (5.0, 25.0))
    it = getattr(usage, "input_tokens", 0) or 0
    ot = getattr(usage, "output_tokens", 0) or 0
    return it / 1e6 * pi + ot / 1e6 * po


def parse_json_block(text: str):
    """Достаёт JSON из ответа модели, даже если он обёрнут в ``` или текст."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    for op, cl in (("{", "}"), ("[", "]")):
        a, b = t.find(op), t.rfind(cl)
        if a != -1 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"в ответе нет валидного JSON: {(text or '')[:200]!r}")


def run(cmd: list[str], timeout: int = 3600, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} rc={p.returncode}: {(p.stderr or '')[-600:]}")
    return p


def ffprobe_duration(path: Path) -> float:
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0
