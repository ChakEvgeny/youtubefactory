#!/usr/bin/env python3
"""Проба многоголосой озвучки: несколько реплик разными голосами в один файл."""
from __future__ import annotations
import json, subprocess, sys, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.config import Config

cfg = Config()
KEY = cfg.key("ELEVENLABS_API_KEY")
H = {"xi-api-key": KEY, "Content-Type": "application/json"}


def say(voice_id: str, text: str, out: Path, stability=0.35, style=0.6):
    body = json.dumps({"text": text, "model_id": "eleven_v3",
                       "voice_settings": {"stability": stability, "similarity_boost": 0.8,
                                          "style": style, "use_speaker_boost": True}}).encode()
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                                 data=body, headers=H)
    with urllib.request.urlopen(req, timeout=180) as r:
        out.write_bytes(r.read())
    return out


def main():
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    tmp = out.parent / "_voice_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, line in enumerate(plan["lines"], 1):
        f = tmp / f"{i:02d}.mp3"
        if not f.exists():
            say(line["voice_id"], line["text"], f,
                stability=line.get("stability", 0.35), style=line.get("style", 0.6))
        print(f"  {i:02d} {line['who']:<10} {line['text'][:60]}", flush=True)
        parts.append(f)
        sil = tmp / f"{i:02d}_sil.mp3"
        if not sil.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=44100:cl=mono", "-t", str(line.get("gap", 0.6)),
                            "-q:a", "9", str(sil), "-y"], check=True)
        parts.append(sil)
    lst = tmp / "concat.txt"
    lst.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:a", "libmp3lame", "-b:a", "160k", str(out), "-y"], check=True)
    print("готово:", out)


if __name__ == "__main__":
    main()
