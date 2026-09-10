"""Загрузка .env и config/channels.yaml, пути к папке ролика."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .util import ROOT, slugify

STAGES = ["brief", "script", "critic", "voice", "shotlist", "screens",
          "collage", "generate", "assets", "motion", "assemble", "review", "thumbs", "meta", "passport"]

REQUIRED_KEYS = ["ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "PEXELS_API_KEY",
                 "PIXABAY_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
OPTIONAL_KEYS = ["KLING_ACCESS_KEY", "KLING_SECRET_KEY", "KLING_API_KEY", "YOUTUBE_API_KEY"]


@dataclass
class Paths:
    out_dir: Path
    cache_dir: Path
    nas_dir: Path
    music_dir: Path


class Config:
    def __init__(self, channel: str | None = None):
        load_dotenv(ROOT / ".env")
        self.env = os.environ
        raw = yaml.safe_load((ROOT / "config" / "channels.yaml").read_text(encoding="utf-8"))
        self.defaults = raw["defaults"]
        self.channels = raw["channels"]
        self.channel_id = channel
        self.channel = self.channels.get(channel) if channel else None
        if channel and not self.channel:
            raise SystemExit(f"Неизвестный канал: {channel}. Есть: {', '.join(self.channels)}")

        self.paths = Paths(
            out_dir=Path(os.getenv("OUTPUT_DIR", "/mnt/d/youtube/output")),
            cache_dir=Path(os.getenv("CACHE_DIR", "/mnt/d/youtube/cache")),
            nas_dir=Path(os.getenv("NAS_DIR", "/mnt/nas/output")),
            music_dir=Path(os.getenv("MUSIC_DIR", "/mnt/d/youtube/music")),
        )

    def key(self, name: str) -> str:
        return (self.env.get(name) or "").strip()

    def opt(self, name, default=None):
        """Значение из канала, иначе из defaults."""
        if self.channel and name in self.channel:
            return self.channel[name]
        return self.defaults.get(name, default)

    def video_dir(self, slug: str, date: str | None = None) -> Path:
        s = slugify(slug)
        if not date:
            # ролик, начатый вчера, после полуночи должен продолжаться в своей папке,
            # а не уезжать в новую с сегодняшней датой
            existing = sorted((self.paths.out_dir / self.channel_id).glob(f"????-??-??_{s}"))
            if existing:
                return existing[-1]
        d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.paths.out_dir / self.channel_id / f"{d}_{s}"

    def target_seconds(self) -> tuple[int, int]:
        lo, hi = self.channel["target_minutes"]
        return lo * 60, hi * 60

    def target_words(self) -> int:
        lo, hi = self.channel["target_minutes"]
        wpm = self.defaults.get("words_per_minute", 150)
        return int((lo + hi) / 2 * wpm)
