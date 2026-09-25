#!/usr/bin/env python3
"""Разметка релевантности роликов нише через Claude API (claude-haiku-4-5).

Берёт из videos ролики без метки, шлёт батчами по 40 (title + первые 300
символов описания + описание ниши из niches.yaml), получает {video_id: 0|1}
и проставляет videos.relevant. Метрики в niche_scores считаются только по
relevant = 1 (см. scripts/scan.py).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-opus-5"
BATCH = 40
DESC_CHARS = 300
MIN_DURATION_SEC = 180
FORMAT_BATCH = 6          # обложки — картинки, батч держим мелким
FORMATS = ["stock_documentary", "stickman_animation", "whiteboard_2d",
           "ai_generated_visuals", "talking_head", "slideshow_text", "gameplay_other"]

SYSTEM_FORMAT = (
    "Ты определяешь визуальный формат ролика YouTube по его обложке и заголовку. "
    "Ровно один вариант из списка:\n"
    "stock_documentary — сток-кадры и реальные съёмки, документальный монтаж;\n"
    "stickman_animation — рисованные человечки, простая векторная анимация;\n"
    "whiteboard_2d — доска, схемы, инфографика, 2D-иллюстрации;\n"
    "ai_generated_visuals — сгенерированные нейросетью изображения;\n"
    "talking_head — человек в кадре говорит на камеру;\n"
    "slideshow_text — статичные картинки с крупным текстом, скриншоты;\n"
    "gameplay_other — игровой процесс или всё, что не подходит выше.\n"
    "Отвечай ТОЛЬКО JSON-объектом {\"video_id\": \"format\"} без пояснений и без markdown."
)

SYSTEM = (
    "Ты классифицируешь ролики YouTube по принадлежности к нише. "
    "Для каждого ролика реши, относится ли он к описанной нише: 1 — относится, "
    "0 — не относится. Суди по смыслу заголовка и описания, а не по отдельным "
    "словам: совпадение ключевого слова при другой теме — это 0. "
    "Отвечай ТОЛЬКО JSON-объектом вида {\"video_id\": 0 или 1} без пояснений, "
    "без markdown-ограждения. Включи в ответ каждый переданный video_id ровно один раз."
)


def parse_json_object(text: str) -> dict:
    """Достаёт JSON-объект из ответа, даже если он обёрнут в ``` или текст."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.MULTILINE).strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(t[start:end + 1])
        except json.JSONDecodeError:
            pass
    # обрезанный/битый ответ: спасаем пары "id": значение регулярным выражением
    pairs = re.findall(r'"([A-Za-z0-9_-]{6,})"\s*:\s*("?[A-Za-z0-9_]+"?)', t)
    if not pairs:
        raise ValueError(f"в ответе нет JSON-объекта: {text[:200]!r}")
    out = {}
    for k, v in pairs:
        v = v.strip('"')
        out[k] = int(v) if v.isdigit() else v
    return out


def classify(client, niche_desc: str, rows: list[dict]) -> dict:
    listing = []
    for v in rows:
        title = (v.get("title") or "").replace("\n", " ")[:200]
        desc = (v.get("description") or "").replace("\n", " ")[:DESC_CHARS]
        listing.append(f"{v['id']}\nЗАГОЛОВОК: {title}\nОПИСАНИЕ: {desc}")
    prompt = (
        f"НИША:\n{niche_desc.strip()}\n\n"
        f"РОЛИКИ ({len(rows)} шт., каждый начинается со своего video_id):\n\n"
        + "\n\n".join(listing)
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    raw = parse_json_object(text)
    out, ids = {}, {v["id"] for v in rows}
    for k, val in raw.items():
        if k in ids:
            try:
                out[k] = 1 if int(val) == 1 else 0
            except (TypeError, ValueError):
                continue
    return out, resp.usage


def thumb_url(v: dict) -> str:
    """Обложка выводится прямо из id — колонка нужна лишь как кэш фактического URL."""
    return v.get("thumbnail_url") or f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg"


def classify_format(client, rows: list[dict]):
    content = [{"type": "text", "text": "Определи формат каждого ролика."}]
    for v in rows:
        content.append({"type": "text",
                        "text": f"video_id: {v['id']} — {(v.get('title') or '')[:120]}"})
        content.append({"type": "image", "source": {"type": "url", "url": thumb_url(v)}})
    resp = client.messages.create(
        model=MODEL, max_tokens=1500, system=SYSTEM_FORMAT,
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    raw = parse_json_object(text)
    ids = {v["id"] for v in rows}
    out = {k: v for k, v in raw.items() if k in ids and v in FORMATS}
    return out, resp.usage


def run_formats(sb, client, langs, niches, batch):
    total, tin, tout = 0, 0, 0
    for niche in niches:
        for lang in langs:
            rows = (sb.table("videos").select("id,title,thumbnail_url")
                    .eq("lang", lang).eq("niche", niche).eq("relevant", 1)
                    .is_("format", "null")
                    .execute().data or [])
            if not rows:
                continue
            print(f"→ формат {lang}/{niche}: {len(rows)} обложек")
            for i in range(0, len(rows), batch):
                chunk = rows[i:i + batch]
                try:
                    labels, usage = classify_format(client, chunk)
                except Exception as e:
                    print(f"   ! батч пропущен: {str(e)[:120]}")
                    continue
                tin += usage.input_tokens
                tout += usage.output_tokens
                by_fmt = {}
                for vid, fmt in labels.items():
                    by_fmt.setdefault(fmt, []).append(vid)
                for fmt, vids in by_fmt.items():
                    sb.table("videos").update({"format": fmt}).in_("id", vids).execute()
                total += len(labels)
                print(f"   батч {len(chunk)}: " + ", ".join(f"{f}={len(v)}" for f, v in by_fmt.items()))
    return total, tin, tout


def main():
    ap = argparse.ArgumentParser(description="Разметка релевантности роликов нише")
    ap.add_argument("--langs", help="через запятую; по умолчанию все")
    ap.add_argument("--niches", help="через запятую; по умолчанию все")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--all-videos", action="store_true",
                    help="размечать и отсеянные (короткие / чужой язык); "
                         "по умолчанию только те, что доходят до метрик")
    ap.add_argument("--dry-run", action="store_true", help="только посчитать, сколько без метки")
    ap.add_argument("--skip-formats", action="store_true", help="не определять визуальный формат")
    ap.add_argument("--formats-only", action="store_true", help="только формат, без релевантности")
    ap.add_argument("--format-batch", type=int, default=FORMAT_BATCH)
    ap.add_argument("--config", default=str(ROOT / "config" / "niches.yaml"),
                    help="матрица ниш; для отдельного канала — свой файл")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    load_dotenv(ROOT / ".env")
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        if not os.getenv(k):
            sys.exit(f"Нет значения в .env для: {k}")
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

    for col in ("relevant", "thumbnail_url", "format"):
        try:
            sb.table("videos").select(col).limit(1).execute()
        except Exception:
            sys.exit(f"В таблице videos нет колонки {col} — примени "
                     "supabase/migration_relevance.sql в SQL Editor "
                     "(в проекте из SUPABASE_URL).")

    langs = [x.strip() for x in args.langs.split(",")] if args.langs else list(cfg["languages"])
    niches = [x.strip() for x in args.niches.split(",")] if args.niches else list(cfg["niches"])

    total_done = total_in = total_out = 0
    if args.formats_only:
        if not os.getenv("ANTHROPIC_API_KEY"):
            sys.exit("Нет значения в .env для: ANTHROPIC_API_KEY")
        import anthropic
        n, ti, to = run_formats(sb, anthropic.Anthropic(), langs, niches, args.format_batch)
        cost = ti / 1e6 * 1.0 + to / 1e6 * 5.0
        print(f"\nФормат проставлен у {n}. Токены: вход {ti:,}, выход {to:,} (~${cost:.3f})")
        return

    for niche in niches:
        desc = cfg["niches"][niche]["description"]
        for lang in langs:
            q = (sb.table("videos").select("*")
                 .eq("lang", lang).eq("niche", niche).is_("relevant", "null"))
            rows = q.execute().data or []
            if not args.all_videos:
                keep = []
                for v in rows:
                    if (v.get("duration_sec") or 0) < MIN_DURATION_SEC:
                        continue
                    dal = (v.get("default_audio_language") or "").lower()
                    if v.get("detected_lang") == lang or dal.startswith(lang):
                        keep.append(v)
                rows = keep
            if not rows:
                continue
            print(f"→ {lang}/{niche}: без метки {len(rows)}")
            if args.dry_run:
                total_done += len(rows)
                continue

            if not os.getenv("ANTHROPIC_API_KEY"):
                sys.exit("Нет значения в .env для: ANTHROPIC_API_KEY")
            import anthropic
            client = anthropic.Anthropic()

            def classify_safe(chunk):
                """Битый ответ (эхо списка, обрыв) -> повтор половинками, потом пропуск батча."""
                try:
                    return classify(client, desc, chunk)
                except ValueError as e:
                    if len(chunk) > 5:
                        a, b = chunk[: len(chunk) // 2], chunk[len(chunk) // 2:]
                        la, ua = classify_safe(a)
                        lb, ub = classify_safe(b)
                        ua.input_tokens += ub.input_tokens; ua.output_tokens += ub.output_tokens
                        return {**la, **lb}, ua
                    print(f"   ! батч {len(chunk)} пропущен: {str(e)[:80]}")
                    class U: input_tokens = 0; output_tokens = 0
                    return {}, U()
            for i in range(0, len(rows), args.batch):
                chunk = rows[i:i + args.batch]
                labels, usage = classify_safe(chunk)
                total_in += usage.input_tokens
                total_out += usage.output_tokens
                ones = [k for k, v in labels.items() if v == 1]
                zeros = [k for k, v in labels.items() if v == 0]
                if ones:
                    sb.table("videos").update({"relevant": 1}).in_("id", ones).execute()
                if zeros:
                    sb.table("videos").update({"relevant": 0}).in_("id", zeros).execute()
                missed = len(chunk) - len(labels)
                total_done += len(labels)
                print(f"   батч {len(chunk):>3}: relevant {len(ones)}, нет {len(zeros)}"
                      + (f", без ответа {missed}" if missed else ""))

    if args.dry_run:
        print(f"\nDRY-RUN: без метки всего {total_done} роликов, "
              f"~{(total_done + BATCH - 1)//BATCH} запросов к {MODEL}")
    else:
        if not args.skip_formats:
            import anthropic
            n, ti, to = run_formats(sb, anthropic.Anthropic(), langs, niches, args.format_batch)
            total_done += n
            total_in += ti
            total_out += to
        cost = total_in / 1e6 * 1.0 + total_out / 1e6 * 5.0   # Haiku 4.5: $1 / $5 за 1M
        print(f"\nРазмечено {total_done}. Токены: вход {total_in:,}, выход {total_out:,} "
              f"(~${cost:.3f} по тарифу {MODEL})")


if __name__ == "__main__":
    main()
