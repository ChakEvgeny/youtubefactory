#!/usr/bin/env python3
"""Пробы голосов для канала: британские narrative-голоса из библиотеки ElevenLabs
(кроме уже занятых) на одном абзаце сценария, eleven_v3 с настройками канала.
Файлы -> /mnt/d/youtube/output/_voice_tests/business_<Name>.mp3."""
from __future__ import annotations
import json, re, sys, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.config import Config

cfg = Config("business")
key = cfg.key("ELEVENLABS_API_KEY")
H = {"xi-api-key": key, "Content-Type": "application/json"}
used = {v["id"] for v in cfg.defaults["voice_pool"] if v.get("used_by")}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=60) as r:
        return json.loads(r.read().decode())
# свои + premade
voices = get("https://api.elevenlabs.io/v2/voices?page_size=100").get("voices", [])
def lab(v, k): return (v.get("labels") or {}).get(k, "").lower()
cands = [v for v in voices if v["voice_id"] not in used and "british" in lab(v, "accent")
         and any(w in (lab(v, "use_case") + lab(v, "descriptive") + lab(v, "description")) for w in ("narrat", "news", "documentary", "informative", "story"))]
if len(cands) < 4:      # добираем из shared library: британцы, narrative, high quality
    try:
        sh = get("https://api.elevenlabs.io/v1/shared-voices?page_size=30&language=en&accent=british&use_cases=narrative_story&sort=cloned_by_count&gender=male")
        for v in sh.get("voices", []):
            if v["voice_id"] not in used and all(v["voice_id"] != c["voice_id"] for c in cands):
                cands.append({"voice_id": v["voice_id"], "name": v["name"], "labels": {"accent": v.get("accent"), "descriptive": v.get("descriptive")},
                              "shared": True, "public_owner_id": v.get("public_owner_id")})
    except Exception as e:
        print("shared library:", str(e)[:120])
want = [n for n in sys.argv[1:]] or None
cands = [c for c in cands if not want or c["name"] in want][:6]
print("кандидаты:", [(c["name"], c["voice_id"], (c.get("labels") or {}).get("descriptive") or (c.get("labels") or {}).get("description")) for c in cands])

ctx = Path(cfg.paths.out_dir) / "business" / "2026-09-09_jaguar-land-rover-three-blows"
text = (ctx / "script.md").read_text(encoding="utf-8")
paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 300 and not p.strip().startswith(("[", "#"))]
sample = re.sub(r"\[[^\]]+\]", "", paras[1] if len(paras) > 1 else paras[0])[:700]
out = Path(cfg.paths.out_dir) / "_voice_tests"; out.mkdir(exist_ok=True)
for c in cands:
    vid = c["voice_id"]
    if c.get("shared"):     # общий голос сначала надо добавить в свою библиотеку
        try:
            req = urllib.request.Request(f"https://api.elevenlabs.io/v1/voices/add/{c['public_owner_id']}/{vid}",
                                         data=json.dumps({"new_name": c["name"]}).encode(), headers=H, method="POST")
            vid = json.loads(urllib.request.urlopen(req, timeout=60).read().decode()).get("voice_id", vid)
        except Exception as e:
            print(f"  {c['name']}: не добавился — {str(e)[:100]}"); continue
    body = {"text": sample, "model_id": cfg.defaults.get("voice_model", "eleven_v3"),
            "voice_settings": {"stability": cfg.defaults.get("voice_stability", 0.35), "style": cfg.defaults.get("voice_style", 0.6),
                               "similarity_boost": 0.8, "use_speaker_boost": True}}
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=mp3_44100_128",
                                 data=json.dumps(body).encode(), headers=H, method="POST")
    try:
        data = urllib.request.urlopen(req, timeout=180).read()
        f = out / f"business_{re.sub(r'[^A-Za-z0-9]+', '_', c['name'])}.mp3"; f.write_bytes(data)
        print(f"  {c['name']:<18} {vid}  -> {f.name} ({len(data)//1024} KB)")
    except Exception as e:
        print(f"  {c['name']}: ошибка {str(e)[:120]}")
(out / "business_sample.txt").write_text(sample, encoding="utf-8")
