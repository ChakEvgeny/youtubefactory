"""Генеративное видео: Veo 3.1 (Gemini API), Runway Gen-4.5, Kling.

Каждый провайдер — одна функция (prompt, image, seconds, out) -> dict с файлом,
фактической длительностью и стоимостью в USD. Цены — за секунду успешной генерации,
по прайсам на 2026-09-10 (см. docs/generative.md). Ключи — только через cfg.key().
"""
from __future__ import annotations

import base64
import json
import mimetypes
import time
import urllib.request
from pathlib import Path

# $/сек. Veo: ai.google.dev/gemini-api/docs/pricing; Runway: docs.dev.runwayml.com/guides/pricing (1 credit = $0.01)
PRICES = {
    "veo-3.1-generate-preview": {"720p": 0.40, "1080p": 0.40, "4k": 0.60},
    "veo-3.1-fast-generate-preview": {"720p": 0.10, "1080p": 0.12, "4k": 0.30},
    "veo-3.1-lite-generate-preview": {"720p": 0.05, "1080p": 0.08},
    "gen4.5": {"any": 0.12}, "gen4_turbo": {"any": 0.05},
    "runway:veo3.1": {"any": 0.40}, "runway:veo3.1_fast": {"any": 0.15},
    "kling": {"std": 0.056, "pro": 0.098},     # ~$0.28 / $0.49 за 5 с
}


def price(model: str, seconds: float, res: str = "720p") -> float:
    p = PRICES.get(model, {})
    return round(seconds * (p.get(res) or p.get("any") or next(iter(p.values()), 0.0)), 4)


def _b64(path: Path) -> tuple[str, str]:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return base64.b64encode(path.read_bytes()).decode(), mime


# ── Veo 3.1 через google-genai ────────────────────────────────────────────────
def veo(cfg, prompt: str, out: Path, seconds: int = 6, image: Path | None = None,
        model: str = "veo-3.1-fast-generate-preview", resolution: str = "720p",
        negative: str = "", reference_images: list[Path] | None = None, timeout: int = 600) -> dict:
    from google import genai
    from google.genai import types
    key = cfg.key("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("нет GOOGLE_API_KEY")
    client = genai.Client(api_key=key)
    kw: dict = {}
    if image:
        data, mime = _b64(image)
        kw["image"] = types.Image(image_bytes=base64.b64decode(data), mime_type=mime)
    conf: dict = {"aspect_ratio": "16:9", "resolution": resolution, "duration_seconds": int(seconds),
                  "person_generation": "allow_adult" if image else "allow_all"}
    if negative:
        conf["negative_prompt"] = negative
    refs = [p for p in (reference_images or []) if Path(p).exists()][:3]
    if refs and not image:
        conf["duration_seconds"] = 8                 # референсы требуют 8 с
        conf["reference_images"] = [types.VideoGenerationReferenceImage(
            image=types.Image(image_bytes=Path(p).read_bytes(), mime_type=mimetypes.guess_type(str(p))[0] or "image/jpeg"),
            reference_type="asset") for p in refs]
    t0 = time.time()
    op = client.models.generate_videos(model=model, prompt=prompt, config=types.GenerateVideosConfig(**conf), **kw)
    while not op.done:
        if time.time() - t0 > timeout:
            raise TimeoutError("veo: операция не завершилась")
        time.sleep(8)
        op = client.operations.get(op)
    if getattr(op, "error", None):
        raise RuntimeError(f"veo: {op.error}")
    vids = op.response.generated_videos
    if not vids:
        raise RuntimeError("veo: пустой ответ (фильтр безопасности?)")
    v = vids[0]
    client.files.download(file=v.video)
    v.video.save(str(out))
    return {"file": str(out), "provider": "veo", "model": model, "seconds": conf["duration_seconds"],
            "usd": price(model, conf["duration_seconds"], resolution), "audio": True,
            "elapsed": round(time.time() - t0, 1)}


# ── Runway через runwayml SDK ──────────────────────────────────────────────────
def runway(cfg, prompt: str, out: Path, seconds: int = 5, image: Path | None = None,
           model: str = "gen4.5", ratio: str = "1280:720", timeout: int = 600) -> dict:
    from runwayml import RunwayML
    key = cfg.key("RUNWAY_API_KEY")
    if not key:
        raise RuntimeError("нет RUNWAY_API_KEY")
    client = RunwayML(api_key=key)
    t0 = time.time()
    if image:
        data, mime = _b64(image)
        task = client.image_to_video.create(model=model, prompt_image=f"data:{mime};base64,{data}",
                                            prompt_text=prompt[:1000], ratio=ratio, duration=int(seconds))
    else:
        task = client.text_to_video.create(model=model, prompt_text=prompt[:1000], ratio=ratio, duration=int(seconds))
    while True:
        t = client.tasks.retrieve(task.id)
        if t.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        if time.time() - t0 > timeout:
            raise TimeoutError("runway: задача не завершилась")
        time.sleep(6)
    if t.status != "SUCCEEDED":
        raise RuntimeError(f"runway: {t.status} {getattr(t, 'failure', '') or ''}")
    url = t.output[0]
    urllib.request.urlretrieve(url, out)
    return {"file": str(out), "provider": "runway", "model": model, "seconds": int(seconds),
            "usd": price(model, seconds), "audio": False, "elapsed": round(time.time() - t0, 1)}


def runway_credits(cfg) -> dict:
    from runwayml import RunwayML
    o = RunwayML(api_key=cfg.key("RUNWAY_API_KEY")).organization.retrieve()
    return {"credit_balance": getattr(o, "credit_balance", None), "tier": str(getattr(o, "tier", ""))[:200]}


# ── Kling (быстрый фолбэк) ─────────────────────────────────────────────────────
def kling(cfg, prompt: str, out: Path, seconds: int = 5, image: Path | None = None,
          model: str = "kling-v2-1", mode: str = "std", timeout: int = 900) -> dict:
    from ..stages.assets import KLING_BASE, UA, kling_auth
    auth = kling_auth(cfg)
    if not auth:
        raise RuntimeError("нет ключей Kling")
    hdr = {"Authorization": auth, "Content-Type": "application/json", "User-Agent": UA}
    body = {"model_name": model, "prompt": prompt[:2500], "duration": str(5 if seconds <= 5 else 10),
            "aspect_ratio": "16:9", "mode": mode}
    kind = "image2video" if image else "text2video"
    if image:
        body["image"] = _b64(image)[0]
    req = urllib.request.Request(f"{KLING_BASE}/v1/videos/{kind}", data=json.dumps(body).encode(), headers=hdr)
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    if d.get("code") != 0:
        raise RuntimeError(f"kling: {d.get('message')}")
    tid = d["data"]["task_id"]
    t0 = time.time()
    while True:
        time.sleep(10)
        req = urllib.request.Request(f"{KLING_BASE}/v1/videos/{kind}/{tid}", headers=hdr)
        with urllib.request.urlopen(req, timeout=60) as r:
            s = json.loads(r.read().decode())["data"]
        if s.get("task_status") == "succeed":
            url = s["task_result"]["videos"][0]["url"]
            break
        if s.get("task_status") == "failed":
            raise RuntimeError(f"kling: {s.get('task_status_msg')}")
        if time.time() - t0 > timeout:
            raise TimeoutError("kling: задача не завершилась")
    urllib.request.urlretrieve(url, out)
    sec = int(body["duration"])
    return {"file": str(out), "provider": "kling", "model": model, "seconds": sec,
            "usd": price("kling", sec, mode), "audio": False, "elapsed": round(time.time() - t0, 1)}


PROVIDERS = {"veo": veo, "runway": runway, "kling": kling}
