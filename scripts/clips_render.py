#!/usr/bin/env python3
"""Клипы Veo по утверждённой раскадровке: image-to-video из готовых картинок.

Оживляем только кадры tier=='anim'. Первый кадр клипа — та самая картинка,
которую утвердили, поэтому композиция и персонаж не уезжают.
"""
from __future__ import annotations
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from pipeline.config import Config
from pipeline import costs
from pipeline.sources import genvideo

NEG = ("camera movement, zoom, whip pan, warping, melting, morphing, extra limbs, distorted face, "
       "duplicated person, text, captions, watermark, modern objects")
SOFT = {"walks toward camera": "shifts weight", "turns around": "turns her head slightly",
        "opens the door": "stands still", "runs": "moves slowly"}


def main():
    d = Path(sys.argv[1])
    only = {int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else []) if x.strip().isdigit()}
    r = json.loads((d / "timed.json").read_text(encoding="utf-8"))
    cfg = Config()
    cdir = d / "clips"; cdir.mkdir(exist_ok=True)
    shots = [s for s in r if s.get("tier") == "anim" and (not only or s["id"] in only)]
    print(f"клипов к генерации: {len(shots)}")
    spent = {"usd": 0.0, "fail": []}

    def one(s):
        out = cdir / f"{s['id']:03d}.mp4"
        if out.exists() and out.stat().st_size > 100_000:
            return out
        img = d / "storyboard" / f"{s['id']:03d}.jpg"
        if not img.exists():
            spent["fail"].append((s["id"], "нет картинки")); return out
        motion = s.get("motion") or "very slow push-in"
        for k, v in SOFT.items():
            motion = motion.replace(k, v)
        prompt = (f"{s['visual']}. {motion}. The camera does not move. One simple continuous action, "
                  "nothing else changes. Photoreal, natural light, no stylisation.")
        secs = int(s.get("seconds") or 6)
        model = s.get("model") or "veo-3.1-fast-generate-preview"
        for attempt in range(3):
            try:
                res = genvideo.veo(cfg, prompt, out, seconds=secs, image=img,
                                   model=model, resolution="720p", negative=NEG)
                spent["usd"] += res.get("usd", 0.0)
                print(f"  {s['id']:03d} {secs}с {model.split('-')[2]} ${res.get('usd',0):.2f}", flush=True)
                return out
            except Exception as e:
                msg = str(e)[:110]
                if attempt == 0:
                    prompt = (f"{s['visual']}. Very slight movement only, almost still. "
                              "The camera does not move. Photoreal.")
                    continue
                if attempt == 1:
                    model = "veo-3.1-fast-generate-preview"
                    continue
                spent["fail"].append((s["id"], msg))
                print(f"  ! {s['id']:03d} {msg}", flush=True)
        return out

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(one, shots))
    ok = sum(1 for s in shots if (cdir / f"{s['id']:03d}.mp4").exists())
    print(f"\nготово {ok}/{len(shots)}, ${spent['usd']:.2f}, {int(time.time()-t0)} c")
    costs.log(costs.project_of(d), "clips", "veo-3.1", spent["usd"], ok, "клипов")
    for i, m in spent["fail"]:
        print(f"  ! {i}: {m}")


if __name__ == "__main__":
    main()
