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
# ВСЯ разметка, а не только SCENE: строки [MOTION: ...] раньше попадали в озвучку
# и диктор читал вслух «counter from=0 to=4000 label=...».
MARK_RE = re.compile(r"^\[(?:SCENE|MOTION|BEAT|SHOT):.+?\]\s*$", re.IGNORECASE | re.MULTILINE)


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


def quota(key: str) -> dict:
    """Остаток символов. ElevenLabs на исчерпанной квоте отвечает 401, а не 429,
    поэтому проверяем заранее — иначе ошибка выглядит как неверный ключ."""
    s = _req("/user/subscription", key)
    used, lim = s.get("character_count") or 0, s.get("character_limit") or 0
    return {"tier": s.get("tier"), "used": used, "limit": lim, "left": max(lim - used, 0),
            "reset_unix": s.get("next_character_count_reset_unix")}


def split_paragraphs(script: str, max_chars: int = 2500) -> list[str]:
    text = MARK_RE.sub("", script)
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


def synth_chunk(key: str, voice_id: str, text: str, cache: Cache,
                speed: float = 1.0, stability: float = 0.5, style: float = 0.0) -> dict:
    """Возвращает {'mp3': Path, 'alignment': {...}} с кэшем по hash текста."""
    h = sha1(voice_id, MODEL, text, speed, stability, style)
    mp3 = cache.blob_path("tts", h, ".mp3")
    meta = cache.get_json("tts", h, ttl_hours=None)
    if mp3.exists() and meta:
        return {"mp3": mp3, "alignment": meta.get("alignment"), "cached": True,
                "chars": len(text)}

    payload = {"text": text, "model_id": MODEL,
               "voice_settings": {"stability": stability, "similarity_boost": 0.75,
                                  "style": style, "speed": speed}}
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
    # аудио-теги ElevenLabs v3 не звучат — из таймкодов их выкидываем
    tag = re.compile(r"^\[(?:pause|thoughtful|firmly|quietly|sighs)\]$", re.I)
    return [w for w in words if not tag.match(w["word"])]


def trim_silence(parts: list[Path], words: list[dict], out: Path,
                 sil_max: float, sil_to: float, xfade_ms: int) -> tuple[list[dict], float]:
    """Склейка чанков с кроссфейдом + сжатие длинных пауз.
    Таймкоды слов пересчитываются, иначе кадры и motion разъезжаются."""
    # 1) склейка с кроссфейдом между чанками
    joined = out.parent / "_voice_joined.mp3"
    if len(parts) == 1:
        run(["ffmpeg", "-y", "-v", "error", "-i", str(parts[0]), "-c", "copy", str(joined)])
    else:
        ins, filt, prev = [], [], "[0:a]"
        for i, pth in enumerate(parts):
            ins += ["-i", str(pth)]
        for i in range(1, len(parts)):
            lbl = f"[a{i}]"
            filt.append(f"{prev}[{i}:a]acrossfade=d={xfade_ms/1000:.3f}:c1=tri:c2=tri{lbl}")
            prev = lbl
        run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", ";".join(filt),
             "-map", prev, str(joined)])

    # 2) какие куски оставляем: паузу длиннее sil_max режем до sil_to
    keep, cuts, prev_end = [], [], 0.0
    for w in words:
        gap = w["start"] - prev_end
        if gap > sil_max and prev_end > 0:
            keep.append((prev_end - 0.0, prev_end + sil_to))
            cuts.append((prev_end + sil_to, w["start"]))
        prev_end = w["end"]
    if not cuts:
        joined.replace(out)
        return words, 0.0

    segs, pos = [], 0.0
    for a, b in cuts:
        segs.append((pos, a))
        pos = b
    total = max(w["end"] for w in words) + 1.0
    segs.append((pos, total))

    filt = "".join(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[s{i}];"
                   for i, (a, b) in enumerate(segs))
    filt += "".join(f"[s{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1[o]"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-filter_complex", filt,
         "-map", "[o]", str(out)], timeout=1800)
    joined.unlink(missing_ok=True)

    # 3) пересчёт таймкодов: вычитаем вырезанное, что было раньше слова
    removed = [(a, b - a) for a, b in cuts]
    def shift(t):
        return round(t - sum(d for a, d in removed if a <= t), 3)
    new = [{"word": w["word"], "start": shift(w["start"]), "end": shift(w["end"])} for w in words]
    return new, round(sum(d for _, d in removed), 2)


def run_stage(cfg, ctx, cost, preview_sec: float | None = None) -> dict:
    key = cfg.key("ELEVENLABS_API_KEY")
    voice_id = (cfg.channel.get("voice_id") or "").strip()
    if not voice_id:
        raise SystemExit(f"voice_id для канала {cfg.channel_id} не задан в config/channels.yaml "
                         "— сначала выбери голос (--list-voices)")
    cache = Cache(cfg.paths.cache_dir)
    script = (ctx / "script.md").read_text(encoding="utf-8")
    chunks = split_paragraphs(script)
    if preview_sec:
        # превью: озвучиваем только начало (+50% запаса), полный голос — после вердикта по минуте
        wpm = float(cfg.defaults.get("words_per_minute", 150))
        budget_words, kept, acc = preview_sec / 60 * wpm * 1.5, [], 0
        for c in chunks:
            kept.append(c); acc += len(MARK_RE.sub("", c).split())
            if acc >= budget_words:
                break
        print(f"    · превью {preview_sec:.0f}с: озвучиваю {len(kept)} из {len(chunks)} фрагментов (~{acc} слов)")
        chunks = kept

    # сколько реально придётся оплатить: чанки из кэша не тарифицируются
    speed = float(cfg.defaults.get("narration_speed", 1.0))
    stab = float(cfg.defaults.get("voice_stability", 0.5))
    style = float(cfg.defaults.get("voice_style", 0.0))
    need = sum(len(c) for c in chunks
               if not cache.blob_path("tts", sha1(voice_id, MODEL, c, speed, stab, style), ".mp3").exists())
    q = quota(key)
    if need > q["left"]:
        raise SystemExit(
            f"ElevenLabs: не хватает символов. Тариф «{q['tier']}», "
            f"осталось {q['left']:,} из {q['limit']:,}, сценарию нужно {need:,}. "
            f"Не хватает {need - q['left']:,}. Нужен план побольше или ждать сброса лимита.")

    parts, words, offset, chars, cached_n = [], [], 0.0, 0, 0
    for i, ch_text in enumerate(chunks):
        res = synth_chunk(key, voice_id, ch_text, cache, speed, stab, style)
        dur = _dur(res["mp3"])
        words += words_from_alignment(res["alignment"], offset)
        offset += dur
        parts.append(res["mp3"])
        chars += res["chars"]
        cached_n += int(res["cached"])

    out = ctx / "voice.mp3"
    d = cfg.defaults
    words, removed = trim_silence(parts, words, out,
                                  float(d.get("silence_max", 0.7)),
                                  float(d.get("silence_to", 0.35)),
                                  int(d.get("chunk_crossfade_ms", 50)))
    # ускорение темпа: atempo не меняет высоту тона
    tempo = float(d.get("narration_tempo", 1.0))
    if abs(tempo - 1.0) > 0.005:
        sped = ctx / "_voice_tempo.mp3"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(out), "-filter:a",
             f"atempo={tempo:.3f}", str(sped)], timeout=1800)
        sped.replace(out)
        words = [{"word": x["word"], "start": round(x["start"] / tempo, 3),
                  "end": round(x["end"] / tempo, 3)} for x in words]
    from ..util import ffprobe_duration as _dur2
    final = _dur2(out)
    (ctx / "timestamps.json").write_text(
        json.dumps({"words": words, "duration": final, "voice_id": voice_id,
                    "model": MODEL, "speed": speed, "tempo": tempo, "trimmed_sec": removed},
                   ensure_ascii=False), encoding="utf-8")

    cost.add("voice", MODEL, need / 1000 * PRICE_PER_1K_CHARS,
             f"{chars} симв., оплачено {need}, из кэша {cached_n}/{len(chunks)} чанков")
    gaps = sum(1 for i in range(1, len(words))
               if words[i]["start"] - words[i - 1]["end"] > float(d.get("silence_max", 0.7)))
    return {"chunks": len(chunks), "cached": cached_n, "chars": chars, "billed": need,
            "speed": speed, "tempo": tempo, "raw_sec": round(offset, 1), "duration_sec": round(final, 1),
            "trimmed_sec": removed, "long_pauses_left": gaps, "words": len(words),
            "wpm": round(len(words) / (final / 60)) if final else 0}


def _dur(p: Path) -> float:
    from ..util import ffprobe_duration
    return ffprobe_duration(p)
