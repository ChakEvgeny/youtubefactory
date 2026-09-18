#!/usr/bin/env python3
"""Перевод субтитров, заголовка и описания ролика на несколько языков.

Тайминги SRT не трогаются вообще: переводится только текст реплик, номера и
таймкоды переносятся из оригинала. Главы в описании сохраняют исходные секунды.
Модель — claude-opus-5 (ниже Opus в конвейере не ставим).
"""
from __future__ import annotations
import json, re, sys, textwrap
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import anthropic
from pipeline.util import claude_cost, parse_json_block

MODEL = "claude-opus-5"
# Только платёжеспособные рынки: дешёвые по RPM страны не берём (решение Евгения).
LANGS = {
    "es-419": "Latin American Spanish", "pt-BR": "Brazilian Portuguese",
    "de": "German", "fr": "French",
}
STYLE = ("Tone: dry documentary true-crime narration. Short, clipped sentences. "
         "No exclamation marks, no slang, no added adjectives, no moralising. "
         "Keep every number, date, sum, proper name and quoted court language exact — "
         "sums spelled out in words stay spelled out in words. "
         "Keep quotation marks around quotes.")


def parse_srt(p: Path):
    out = []
    for blk in p.read_text(encoding="utf-8").strip().split("\n\n"):
        L = blk.split("\n")
        if len(L) >= 3:
            out.append({"n": L[0], "t": L[1], "text": " ".join(L[2:])})
    return out


def _ask(client, texts: list[str], lang: str, budget: dict) -> list[str]:
    """Нумерованный формат: модель обязана вернуть ключ на каждую строку."""
    numbered = {str(i + 1): t for i, t in enumerate(texts)}
    prompt = (f"Translate these subtitle lines into {lang}.\n{STYLE}\n"
              "The input is a JSON object: key = line number, value = English text.\n"
              "Return ONLY a JSON object with EXACTLY the same keys, each mapped to the "
              "translation of that line. Never merge, split, drop or renumber lines. "
              f"There are {len(texts)} keys and your answer must have {len(texts)} keys.\n\n"
              + json.dumps(numbered, ensure_ascii=False, indent=0))
    r = client.messages.create(model=MODEL, max_tokens=12000,
                               messages=[{"role": "user", "content": prompt}])
    budget["usd"] += claude_cost(MODEL, r.usage)
    res = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
    if not isinstance(res, dict):
        raise RuntimeError(f"{lang}: ответ не объект")
    miss = [k for k in numbered if k not in res]
    if miss:
        raise RuntimeError(f"{lang}: нет строк {miss[:5]} из {len(texts)}")
    return [str(res[str(i + 1)]) for i in range(len(texts))]


def translate_batch(client, texts: list[str], lang: str, budget: dict) -> list[str]:
    """При расхождении длины режем партию пополам и повторяем."""
    try:
        return _ask(client, texts, lang, budget)
    except Exception as e:
        if len(texts) <= 2:
            raise
        print(f"    повтор половинками ({len(texts)}): {str(e)[:60]}", flush=True)
        h = len(texts) // 2
        return (translate_batch(client, texts[:h], lang, budget)
                + translate_batch(client, texts[h:], lang, budget))


def wrap(t: str) -> str:
    return "\n".join(textwrap.wrap(t, 42, break_long_words=False)) or t


def main():
    d = Path(sys.argv[1])
    srt = parse_srt(d / "subs_en.srt")
    title = (d / "title_en.txt").read_text(encoding="utf-8").strip()
    desc = (d / "description.md").read_text(encoding="utf-8")
    client = anthropic.Anthropic()
    budget = {"usd": 0.0}
    outdir = d / "i18n"
    outdir.mkdir(exist_ok=True)

    def do_lang(item):
        code, lang = item
        # 1) субтитры — партии по 25 реплик, параллельно; тайминги из оригинала
        sub_p = outdir / f"subs_{code}.srt"
        if sub_p.exists():
            print(f"  {code}: субтитры уже есть, пропуск", flush=True)
        else:
            parts = [srt[i:i + 25] for i in range(0, len(srt), 25)]
            done = [0]

            def work(chunk):
                r = translate_batch(client, [c["text"] for c in chunk], lang, budget)
                done[0] += len(r)
                print(f"  {code}: {done[0]}/{len(srt)}", flush=True)
                return r

            with ThreadPoolExecutor(max_workers=len(parts)) as ex:
                tr = [x for sub in ex.map(work, parts) for x in sub]
            blocks = [f"{c['n']}\n{c['t']}\n{wrap(x)}\n" for c, x in zip(srt, tr)]
            (outdir / f"subs_{code}.srt").write_text("\n".join(blocks), encoding="utf-8")

        # 2) заголовок и описание; таймкоды глав переносятся как есть
        meta_p = outdir / f"meta_{code}.txt"
        if meta_p.exists():
            print(f"  {code}: заголовок/описание уже есть, пропуск", flush=True)
            return
        prompt = (f"Translate this YouTube title and description into {lang}.\n{STYLE}\n"
                  "Rules: keep chapter timecodes (00:00 etc.) byte-identical and in the same order, "
                  "translate only the chapter titles; keep all URLs unchanged; keep the section "
                  "headers CHAPTERS / SOURCES / ABOUT / DISCLOSURE translated into the target language; "
                  "in the TITLE and DESCRIPTION write every number and sum the natural way for the target language, never leaving the English form; the numeric value must stay exactly the same. Keep the title under 80 characters.\n"
                  'Return ONLY JSON: {"title":"...","description":"..."}\n\n'
                  f"TITLE:\n{title}\n\nDESCRIPTION:\n{desc}")
        r = client.messages.create(model=MODEL, max_tokens=8000,
                                   messages=[{"role": "user", "content": prompt}])
        budget["usd"] += claude_cost(MODEL, r.usage)
        md = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
        (outdir / f"meta_{code}.txt").write_text(
            f"{md['title']}\n\n{'='*60}\n\n{md['description']}\n", encoding="utf-8")
        print(f"{code} готов: {md['title']}", flush=True)


    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(do_lang, LANGS.items()))

    print(f"\nвсего: {len(LANGS)} языков, ${budget['usd']:.2f}")


if __name__ == "__main__":
    main()
