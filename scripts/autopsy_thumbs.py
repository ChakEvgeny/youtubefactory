#!/usr/bin/env python3
"""Format autopsy, часть 4: обложки референсов через Haiku vision.

Композиция, число слов, цвета, лицо/логотип, где стоит объект, где текст.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))
from pipeline.util import claude_cost, parse_json_block  # noqa: E402

SYSTEM = (
    "Ты разбираешь обложку YouTube-ролика. Верни ТОЛЬКО JSON без markdown:\n"
    "{\"words\": <число слов текста>, \"text\": \"сам текст\", \"text_pos\": \"top|center|bottom|left|right\","
    " \"text_share\": <доля площади под текстом 0-1>, \"object\": \"главный объект одной фразой\","
    " \"object_pos\": \"left|center|right\", \"object_kind\": \"logo|product|person|building|abstract|screenshot\","
    " \"face\": true|false, \"logo\": true|false, \"colors\": [\"#hex\",\"#hex\",\"#hex\"],"
    " \"bg\": \"dark|light|color\", \"effects\": [\"crack\",\"fire\",\"arrow\",\"red-x\",\"glow\",\"none\"],"
    " \"style\": \"одной фразой по-русски\"}"
)


def analyse(thumb: Path, client) -> dict:
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(thumb.read_bytes()).decode()}},
               {"type": "text", "text": "Разбери обложку."}]
    r = client.messages.create(model="claude-opus-5", max_tokens=600, system=SYSTEM,
                               messages=[{"role": "user", "content": content}])
    d = parse_json_block("".join(b.text for b in r.content if b.type == "text"))
    d["cost"] = round(claude_cost("claude-opus-5", r.usage), 4)
    return d


if __name__ == "__main__":
    root = Path(sys.argv[1])
    client = anthropic.Anthropic()
    out = {}
    for d in sorted(root.iterdir()):
        t = d / "video.jpg"
        if not t.exists():
            continue
        try:
            out[d.name] = analyse(t, client)
            x = out[d.name]
            print(f"  {d.name}: {x.get('words')} слов «{str(x.get('text'))[:30]}», объект {x.get('object_kind')} "
                  f"({x.get('object_pos')}), лицо {x.get('face')}, лого {x.get('logo')}, фон {x.get('bg')}, "
                  f"эффекты {x.get('effects')}")
        except Exception as e:
            print(f"  {d.name}: ошибка {str(e)[:70]}")
    (root / "thumbs.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
