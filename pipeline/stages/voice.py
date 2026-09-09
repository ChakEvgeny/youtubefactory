"""voice — ElevenLabs, пословные таймкоды, чанки по абзацам с кэшем по hash."""
from __future__ import annotations

import base64
import json
import re
import urllib.request
from pathlib import Path

from ..util import Cache, run, sha1

API = "https://api.elevenlabs.io/v1"
MODEL = "eleven_v3"
# $/1000 символов, тариф Creator; уточняется при первом вызове
PRICE_PER_1K_CHARS = 0.15
SCENE_RE = re.compile(r"^\[SCENE:.+?\]\s*$", re.IGNORECASE | re.MULTILINE)


def _req(path: str, key: str, payload=None, method="GET"):
    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"xi-api-key": key, "Content-Type": "application/json",
                                          "Accept": "application/json",
                                          "User-Agent": "yt-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def list_voices(key: str, limit: int = 8) -> list[dict]:
    """Голоса, доступные аккаунту, с пометкой пригодности для v3."""
    data = _req("/voices", key)
    out = []
    for v in data.get("voices", []):
        labels = v.get("labels") or {}
        out.append({
            "voice_id": v.get("voice_id"), "name": v.get("name"),
            "gender": labels.get("gender", "—"), "age": labels.get("age", "—"),
            "accent": labels.get("accent", "—"),
            "use_case": labels.get("use_case") or labels.get("use case", "—"),
            "description": (v.get("description") or labels.get("description") or "")[:80],
            "preview": v.get("preview_url"),
        })
    return out


def list_models(key: str) -> list[dict]:
    return _req("/models", key)


def split_paragraphs(script: str, max_chars: int = 2500) -> list[str]:
    text = SCENE_RE.sub("", script)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 > max_chars and cur:
            chunks.append(cur.strip())
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def synth_chunk(key: str, voice_id: str, text: str, cache: Cache) -> dict:
    """Возвращает {'mp3': Path, 'alignment': {...}} с кэшем по hash текста."""
    h = sha1(voice_id, MODEL, text)
    mp3 = cache.blob_path("tts", h, ".mp3")
    meta = cache.get_json("tts", h, ttl_hours=None)
    if mp3.exists() and meta:
        return {"mp3": mp3, "alignment": meta.get("alignment"), "cached": True,
                "chars": len(text)}

    payload = {"text": text, "model_id": MODEL,
               "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    url = f"{API}/text-to-speech/{voice_id}/with-timestamps"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read().decode())
    mp3.write_bytes(base64.b64decode(data["audio_base64"]))
    align = data.get("alignment") or data.get("normalized_alignment")
    cache.put_json("tts", h, {"alignment": align, "chars": len(text)})
    return {"mp3": mp3, "alignment": align, "cached": False, "chars": len(text)}


def words_from_alignment(align: dict, offset: float) -> list[dict]:
    """Схлопывает посимвольные таймкоды ElevenLabs в пословные."""
    if not align:
        return []
    chars = align.get("characters") or []
    starts = align.get("character_start_times_seconds") or []
    ends = align.get("character_end_times_seconds") or []
    words, cur, st = [], "", None
    for i, c in enumerate(chars):
        if c.isspace():
            if cur:
                words.append({"word": cur, "start": round(st + offset, 3),
                              "end": round(ends[i - 1] + offset, 3)})
                cur, st = "", None
            continue
        if not cur:
            st = starts[i]
        cur += c
    if cur and st is not None:
        words.append({"word": cur, "start": round(st + offset, 3),
                      "end": round(ends[-1] + offset, 3)})
    return words


def run_stage(cfg, ctx, cost) -> dict:
    key = cfg.key("ELEVENLABS_API_KEY")
    voice_id = (cfg.channel.get("voice_id") or "").strip()
    if not voice_id:
        raise SystemExit(f"voice_id для канала {cfg.channel_id} не задан в config/channels.yaml "
                         "— сначала выбери голос (--list-voices)")
    cache = Cache(cfg.paths.cache_dir)
    script = (ctx / "script.md").read_text(encoding="utf-8")
    chunks = split_paragraphs(script)

    parts, words, offset, chars, cached_n = [], [], 0.0, 0, 0
    for i, ch_text in enumerate(chunks):
        res = synth_chunk(key, voice_id, ch_text, cache)
        dur = _dur(res["mp3"])
        words += words_from_alignment(res["alignment"], offset)
        offset += dur
        parts.append(res["mp3"])
        chars += res["chars"]
        cached_n += int(res["cached"])

    lst = ctx / "voice_parts.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
    out = ctx / "voice.mp3"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(out)])
    (ctx / "timestamps.json").write_text(
        json.dumps({"words": words, "duration": offset, "voice_id": voice_id,
                    "model": MODEL}, ensure_ascii=False), encoding="utf-8")

    billed = chars - sum(len(c) for i, c in enumerate(chunks) if i < cached_n)
    cost.add("voice", MODEL, max(billed, 0) / 1000 * PRICE_PER_1K_CHARS,
             f"{chars} симв., из кэша чанков {cached_n}/{len(chunks)}")
    return {"chunks": len(chunks), "cached": cached_n, "chars": chars,
            "duration_sec": round(offset, 1), "words": len(words)}


def _dur(p: Path) -> float:
    from ..util import ffprobe_duration
    return ffprobe_duration(p)
