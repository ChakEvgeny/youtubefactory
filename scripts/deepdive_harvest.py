#!/usr/bin/env python3
"""Сбор через yt-dlp: автосубтитры (первые 60 сек) и плейлисты каналов-целей.
YouTube Data API не используется."""
import json, random, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

YTDLP = "/home/chak/.local/bin/yt-dlp"
WORKERS, PAUSE = 3, (1.0, 2.0)
SC = Path(sys.argv[1])
PRE = sys.argv[2] if len(sys.argv) > 2 else "dd"
data = json.loads((SC / f"{PRE}_data.json").read_text(encoding="utf-8"))
subdir = SC / "subs"; subdir.mkdir(exist_ok=True)

def run(cmd, timeout=180):
    time.sleep(random.uniform(*PAUSE))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def ts(s):
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))

def first60(vtt: Path):
    if not vtt.exists(): return ""
    txt, seen = [], set()
    cur_ok = False
    for line in vtt.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "-->" in line:
            try: cur_ok = ts(line.split("-->")[0].strip().split()[0]) < 60.0
            except Exception: cur_ok = False
            continue
        if not cur_ok: continue
        c = re.sub(r"<[^>]+>", "", line).strip()
        if not c or c.startswith(("WEBVTT", "Kind:", "Language:")): continue
        if c in seen: continue
        seen.add(c); txt.append(c)
    return " ".join(txt)[:1200]

def get_subs(v):
    out = subdir / v["id"]
    r = run([YTDLP, "--write-auto-sub", "--sub-lang", "en", "--skip-download",
             "--sub-format", "vtt", "--no-warnings", "-o", str(out),
             f"https://www.youtube.com/watch?v={v['id']}"])
    cand = list(subdir.glob(f"{v['id']}*.vtt"))
    return v["id"], (first60(cand[0]) if cand else ""), r.returncode

def get_playlist(cid):
    r = run([YTDLP, "--flat-playlist", "--dump-json", "--no-warnings", "--ignore-errors",
             "--playlist-end", "20", f"https://www.youtube.com/channel/{cid}/videos"])
    items = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"): continue
        try: d = json.loads(line)
        except Exception: continue
        items.append({"id": d.get("id"), "title": d.get("title"),
                      "views": d.get("view_count"), "duration": d.get("duration")})
    oldest_date = None
    if items:
        r2 = run([YTDLP, "--dump-json", "--skip-download", "--no-warnings",
                  f"https://www.youtube.com/watch?v={items[-1]['id']}"], timeout=120)
        try: oldest_date = json.loads(r2.stdout).get("upload_date")
        except Exception: pass
    return cid, items, oldest_date

jobs_subs, jobs_pl = [], []
for niche, d in data.items():
    for v in d["top_vs"][:10]:
        jobs_subs.append((niche, v))
    for t in d["targets"]:
        jobs_pl.append((niche, t["channel_id"]))

subs_out, pl_out = {}, {}
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    fs = {ex.submit(get_subs, v): (n, v) for n, v in jobs_subs}
    fp = {ex.submit(get_playlist, c): (n, c) for n, c in jobs_pl}
    for f in as_completed(list(fs) + list(fp)):
        try:
            res = f.result()
        except Exception as e:
            print("  ! ", str(e)[:90]); continue
        if f in fs:
            n, v = fs[f]; vid, text, rc = res
            subs_out.setdefault(n, {})[vid] = text
            print(f"  субтитры {n}/{vid}: {len(text)} симв.")
        else:
            n, c = fp[f]; cid, items, od = res
            pl_out.setdefault(n, {})[cid] = {"items": items, "oldest_date": od}
            print(f"  плейлист {n}/{cid}: {len(items)} роликов, старейший {od}")

(SC / f"{PRE}_subs.json").write_text(json.dumps(subs_out, ensure_ascii=False, indent=1), encoding="utf-8")
(SC / f"{PRE}_playlists.json").write_text(json.dumps(pl_out, ensure_ascii=False, indent=1), encoding="utf-8")
print("готово")
