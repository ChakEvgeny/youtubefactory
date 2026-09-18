"""Стиллы через Gemini image-модели (gemini-3.1-flash-image и др.) с референсами:
лист героя + лист локации подаются картинками, чтобы персонаж и мир не менялись от кадра к кадру.
Цены (ориентир, 2026-09): ~$0.04 за изображение 1376×768."""
from __future__ import annotations

import io
import time
from pathlib import Path

def gclient(cfg):
    """Vertex AI (квоты в минуту, биллинг GCP), если задан GOOGLE_CLOUD_PROJECT; иначе AI Studio по ключу."""
    import os
    from google import genai
    proj = cfg.key("GOOGLE_CLOUD_PROJECT")
    cred = cfg.key("GOOGLE_APPLICATION_CREDENTIALS")
    if proj and cred and Path(cred).exists():        # Vertex только когда ключ сервисного аккаунта на месте
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred
        return genai.Client(vertexai=True, project=proj, location=cfg.key("GOOGLE_CLOUD_LOCATION") or "us-central1")
    key = cfg.key("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("нет GOOGLE_API_KEY и GOOGLE_CLOUD_PROJECT")
    return genai.Client(api_key=key)


# Ставки сверены со счётом Google 2026-09-17: за 1238 кадров сентября выставлено
# $146.60, то есть $0.118 за кадр независимо от выбранной модели. Прежние значения
# ($0.04 у flash) занижали учёт в 2.6 раза и создавали иллюзию экономии на модели.
PRICE_PER_IMAGE = {"gemini-3.1-flash-image": 0.118, "gemini-3.1-flash-lite-image": 0.118,
                   "gemini-3-pro-image": 0.12, "gemini-2.5-flash-image": 0.118}


def generate(cfg, prompt: str, out: Path, refs: list[Path] | None = None,
             model: str = "gemini-3.1-flash-image", aspect: str = "16:9", retries: int = 2) -> dict:
    """Одна картинка -> out (.jpg). refs — до 3 референсов (герой, локация, палитра)."""
    from google import genai
    from google.genai import types
    from PIL import Image
    # картинки — через AI Studio (там pro-image доступен и квот хватает); Vertex — для Veo
    from google import genai
    key = cfg.key("GOOGLE_API_KEY")
    client = genai.Client(api_key=key) if key else gclient(cfg)
    contents: list = [prompt] + [Image.open(r) for r in (refs or [])[:3] if Path(r).exists()]
    last = None
    for attempt in range(retries + 1):
        try:
            r = client.models.generate_content(
                model=model, contents=contents,
                config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"],
                                                   image_config=types.ImageConfig(aspect_ratio=aspect)))
            cand = (r.candidates or [None])[0]
            if not cand or not cand.content or not cand.content.parts:
                last = f"модель не вернула изображение (finish_reason={getattr(cand,'finish_reason',None)})"
                raise RuntimeError(last)
            for p in cand.content.parts:
                data = getattr(getattr(p, "inline_data", None), "data", None)
                if data:
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    img.save(out, quality=92)
                    return {"file": str(out), "model": model, "usd": PRICE_PER_IMAGE.get(model, 0.04),
                            "size": img.size}
            last = "нет изображения в ответе: " + " ".join(getattr(p, "text", "") or "" for p in cand.content.parts)[:160]
        except Exception as e:
            last = str(e)[:200]
        time.sleep(2 + attempt * 3)
    raise RuntimeError(f"genimage: {last}")
