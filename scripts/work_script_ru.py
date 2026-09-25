#!/usr/bin/env python3
"""Сценарий в двух языках одним текстовым файлом: строка по-английски, под ней перевод.

Нужен Евгению для вычитки: он правит смысл по-русски, а в ролик идёт английский.

    python scripts/work_script_ru.py <папка> --out script_en_ru.txt
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
import anthropic  # noqa: E402

from pipeline.util import claude_cost, parse_json_block  # noqa: E402

MODEL = "claude-opus-5"
SYS = ("Переводи дикторский текст документального ролика про трудовое право с английского "
       "на русский. Это устная речь от первого лица, не юридический документ: переводи так, "
       "как человек говорит вслух, без канцелярита и без «является». Термины трудового права "
       "давай принятыми русскими соответствиями, в скобках оригинал при первом упоминании. "
       "Пометки ✅ ⚠️ [INSIDE...] переноси без изменений в конец строки. "
       "Верни JSON: {\"ru\": [строка, строка, ...]} — ровно столько строк, сколько пришло.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", default="script_en_ru.txt")
    ap.add_argument("--batch", type=int, default=25)
    a = ap.parse_args()

    P = Path(a.dir)
    src = (P / "script.md").read_text(encoding="utf-8").splitlines()
    blocks, cur, para = [], None, []

    def flush():
        # абзац склеивается целиком: в markdown он разорван по ширине строки,
        # и по кускам получается перевод обрывков вместо предложений
        if para and cur is not None:
            cur["lines"].append(" ".join(para).strip())
        para.clear()

    for line in src:
        m = re.match(r"^##\s*(Блок\s*[\d.]+\..+?)\s*$", line)
        if m:
            flush()
            cur = {"title": m.group(1), "lines": []}
            blocks.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("> "):
            para.append(line[2:].strip())
            continue
        flush()
        # хук записан таблицей: текст диктора в последней колонке
        if line.startswith("|") and line.count("|") >= 3:
            cells = [c.strip() for c in line.strip("|").split("|")]
            txt = cells[-1]
            if txt and not set(txt) <= set("-: ") and "Текст" not in txt:
                cur["lines"].append(re.sub(r"\*\*|`", "", txt))
    flush()
    blocks = [b for b in blocks if b["lines"]]

    flat = [l for b in blocks for l in b["lines"]]
    cl = anthropic.Anthropic()
    ru, usd = [], 0.0
    for i in range(0, len(flat), a.batch):
        part = flat[i:i + a.batch]
        r = cl.messages.create(model=MODEL, max_tokens=8000, system=SYS,
                               messages=[{"role": "user", "content":
                                          json.dumps({"en": part}, ensure_ascii=False)}])
        # первым блоком может прийти рассуждение модели, а не текст
        txt = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
        j = parse_json_block(txt)
        got = j.get("ru", []) if j else []
        if len(got) != len(part):
            got = (got + [""] * len(part))[:len(part)]
        ru += got
        usd += claude_cost(MODEL, r.usage)
        print(f"  {i + len(part)}/{len(flat)}")

    it = iter(ru)
    out = [f"СЦЕНАРИЙ — {P.name}", "Строка по-английски, под ней перевод.",
           "В ролик идёт английский; русский — только для вычитки смысла.", ""]
    for b in blocks:
        out += ["=" * 78, b["title"], "=" * 78, ""]
        for l in b["lines"]:
            out += [f"EN  {l}", f"RU  {next(it, '')}", ""]
    (P / a.out).write_text("\n".join(out), encoding="utf-8")
    print(f"{P / a.out}  строк {len(flat)}  ${usd:.2f}")


if __name__ == "__main__":
    main()
