#!/usr/bin/env python3
"""Оркестратор конвейера. Стадии с кэшем артефактов, --from для пересборки."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from .config import STAGES, Config, OPTIONAL_KEYS, REQUIRED_KEYS
from .util import CostLog, human_money, mask, slugify

# артефакт, по наличию которого стадия считается выполненной
ARTIFACT = {"brief": "brief.json", "script": "script.md", "critic": "critic.md",
            "voice": "voice.mp3", "assets": "assets.json", "motion": "motion.json",
            "assemble": "video.mp4",
            "thumbs": "thumbs.json", "meta": "meta.json", "passport": "passport.json"}

# ориентировочная стоимость стадии для --dry-run, USD
EST = {"brief": 0.45, "script": 1.20, "critic": 0.90, "voice": 2.60, "assets": 1.40,
       "motion": 0.0, "assemble": 0.0, "thumbs": 0.02, "meta": 0.06, "passport": 0.0}


# ── --check ────────────────────────────────────────────────────────────────
def _ok(name, good, note=""):
    print(f"  {'✅' if good else '❌'} {name:<26} {note}")
    return good


def cmd_check(cfg: Config) -> int:
    print("Ключи в .env:")
    all_ok = True
    for k in REQUIRED_KEYS:
        all_ok &= _ok(k, bool(cfg.key(k)), mask(cfg.key(k)))
    for k in OPTIONAL_KEYS:
        _ok(f"{k} (опц.)", True, mask(cfg.key(k)))

    print("\nДоступ к API (по одному минимальному вызову):")
    # Anthropic
    try:
        import anthropic
        r = anthropic.Anthropic().messages.create(
            model="claude-haiku-4-5", max_tokens=8,
            messages=[{"role": "user", "content": "ping"}])
        all_ok &= _ok("Anthropic", True, f"ответ получен, {r.usage.input_tokens} вх. токенов")
    except Exception as e:
        all_ok &= _ok("Anthropic", False, str(e)[:90])
    # ElevenLabs
    try:
        from .stages.voice import list_models
        ms = list_models(cfg.key("ELEVENLABS_API_KEY"))
        ids = [m.get("model_id") for m in ms]
        has_v3 = "eleven_v3" in ids
        all_ok &= _ok("ElevenLabs", True, f"моделей {len(ids)}, eleven_v3: "
                                          f"{'есть' if has_v3 else 'НЕТ в аккаунте'}")
        if not has_v3:
            print(f"       доступны: {', '.join(i for i in ids if i)[:110]}")
    except Exception as e:
        all_ok &= _ok("ElevenLabs", False, str(e)[:90])
    # Pexels
    try:
        req = urllib.request.Request(
            "https://api.pexels.com/videos/search?query=earth&per_page=1",
            headers={"Authorization": cfg.key("PEXELS_API_KEY"),
                     "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) yt-pipeline/1.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=30).read())
        all_ok &= _ok("Pexels", True, f"найдено {d.get('total_results', '?')}")
    except Exception as e:
        all_ok &= _ok("Pexels", False, str(e)[:90])
    # Pixabay
    try:
        d = json.loads(urllib.request.urlopen(
            f"https://pixabay.com/api/videos/?key={cfg.key('PIXABAY_API_KEY')}&q=earth&per_page=3",
            timeout=30).read())
        all_ok &= _ok("Pixabay", True, f"найдено {d.get('totalHits', '?')}")
    except Exception as e:
        all_ok &= _ok("Pixabay", False, str(e)[:90])
    # Supabase
    try:
        from supabase import create_client
        sb = create_client(cfg.key("SUPABASE_URL"), cfg.key("SUPABASE_SERVICE_KEY"))
        n = sb.table("productions").select("*", count="exact").limit(0).execute().count
        all_ok &= _ok("Supabase productions", True, f"строк {n}")
    except Exception as e:
        all_ok &= _ok("Supabase productions", False, str(e)[:90])
    # Kling
    from .stages.assets import KLING_BASE, UA, kling_auth
    auth = kling_auth(cfg)
    if auth:
        try:
            req = urllib.request.Request(f"{KLING_BASE}/v1/videos/text2video?pageSize=1",
                                         headers={"Authorization": auth, "User-Agent": UA})
            urllib.request.urlopen(req, timeout=30).read()
            _ok("Kling", True, "ключ принят")
        except Exception as e:
            _ok("Kling", False, str(e)[:110])
    else:
        _ok("Kling (опц.)", True, "ключей нет — генеративные вставки отключены")

    print("\nЛокальное окружение:")
    import shutil
    from .stages.motion import MOTION_DIR
    node_ok = bool(shutil.which("node") and shutil.which("npx"))
    _ok("node / npx", node_ok, shutil.which("node") or "не найден")
    rem_ok = (MOTION_DIR / "node_modules" / "remotion").exists()
    all_ok &= _ok("Remotion", rem_ok,
                  "установлен" if rem_ok else "нет: cd pipeline/motion && npm install")
    # headless Chrome тянет системные библиотеки, без них рендер motion падает
    missing = []
    if rem_ok:
        import subprocess as _sp
        rem = MOTION_DIR / "node_modules" / ".remotion"
        shell = [q for q in rem.rglob("chrome-headless-shell") if q.is_file()] if rem.exists() else []
        if shell:
            ld = _sp.run(["ldd", str(shell[0])], capture_output=True, text=True)
            missing = sorted({ln.split()[0] for ln in ld.stdout.splitlines() if "not found" in ln})
        else:
            missing = ["chrome-headless-shell не скачан"]
    pkgs = sorted({"libnss3" if m.startswith(("libnss", "libsmime")) else
                   "libnspr4" if m.startswith("libnspr") else m for m in missing})
    all_ok &= _ok("Chrome для Remotion", not missing,
                  "библиотеки на месте" if not missing
                  else f"нет {', '.join(missing)} → sudo apt-get install -y {' '.join(pkgs)}")
    for tool in ("ffmpeg", "ffprobe", "rsync"):
        all_ok &= _ok(tool, bool(shutil.which(tool)), shutil.which(tool) or "не найден")
    for name, p in (("OUTPUT_DIR", cfg.paths.out_dir), ("CACHE_DIR", cfg.paths.cache_dir),
                    ("MUSIC_DIR", cfg.paths.music_dir)):
        p.mkdir(parents=True, exist_ok=True)
        _ok(name, p.exists(), str(p))
    _ok("NAS_DIR", cfg.paths.nas_dir.exists(),
        str(cfg.paths.nas_dir) + ("" if cfg.paths.nas_dir.exists() else " — недоступен"))
    n_music = len([f for f in cfg.paths.music_dir.glob("*")
                   if f.suffix.lower() in (".mp3", ".m4a", ".wav", ".flac", ".ogg")])
    _ok("треки музыки", True, f"{n_music} шт." + (" — сборка пойдёт без музыки" if not n_music else ""))

    print("\nКаналы:")
    voices_ok = True
    for cid, ch in cfg.channels.items():
        v = bool(ch.get("voice_id"))
        voices_ok &= v
        _ok(cid, v, f"{ch['niche']}"
                    + (f", voice_id {ch['voice_id']}" if v else ", voice_id НЕ ЗАДАН"))
    if all_ok and voices_ok:
        print("\nВСЁ ЗЕЛЁНОЕ")
    elif all_ok:
        print("\nИНФРАСТРУКТУРА ЗЕЛЁНАЯ; не хватает только voice_id — выбери голоса "
              "(--list-voices) и впиши в config/channels.yaml")
    else:
        print("\nЕСТЬ КРАСНЫЕ — см. выше")
    all_ok &= voices_ok
    return 0 if all_ok else 1


def cmd_list_voices(cfg: Config) -> int:
    from .stages.voice import list_models, list_voices
    key = cfg.key("ELEVENLABS_API_KEY")
    ids = [m.get("model_id") for m in list_models(key)]
    print(f"Модели аккаунта: {', '.join(i for i in ids if i)}\n")
    voices = list_voices(key)
    males = [v for v in voices if str(v["gender"]).lower().startswith("m")]
    females = [v for v in voices if str(v["gender"]).lower().startswith("f")]
    other = [v for v in voices if v not in males and v not in females]
    for label, group in (("МУЖСКИЕ", males), ("ЖЕНСКИЕ", females), ("БЕЗ ПОМЕТКИ", other)):
        if not group:
            continue
        print(f"=== {label} ({len(group)}) ===")
        for v in group[:8]:
            print(f"  {v['name']:<22} {v['voice_id']}")
            print(f"     {v['age']}, {v['accent']}, {v['use_case']}  {v['description']}")
            if v.get("preview"):
                print(f"     превью: {v['preview']}")
        print()
    print("Выбери три id и впиши в config/channels.yaml -> channels.<id>.voice_id")
    return 0


# ── прогон ──────────────────────────────────────────────────────────────────
def cmd_run(cfg: Config, args) -> int:
    from .stages import (assemble, assets, brief, critic, meta, motion, passport,
                         script, thumbs)
    topic = args.topic
    if not topic:
        raise SystemExit("нужен --topic \"текст\" (очередь тем из Supabase подключим позже)")
    ctx = cfg.video_dir(args.slug or topic, args.date)
    ctx.mkdir(parents=True, exist_ok=True)
    start_at = STAGES.index(args.from_stage) if args.from_stage else 0
    plan = STAGES[start_at:]
    if args.only:
        plan = [s for s in plan if s in args.only.split(",")]

    todo = [s for s in plan if args.from_stage or not (ctx / ARTIFACT[s]).exists()]
    skipped = [s for s in plan if s not in todo]

    if args.dry_run:
        print(f"Канал: {cfg.channel_id} ({cfg.channel['niche']})")
        print(f"Папка: {ctx}")
        print(f"Тема:  {topic}\n")
        print(f"{'стадия':<12} {'статус':<12} оценка")
        for s in plan:
            st = "пропуск (есть)" if s in skipped else "выполнить"
            print(f"{s:<12} {st:<14} {human_money(EST[s]) if s in todo else '—'}")
        print(f"\nИтого оценка: {human_money(sum(EST[s] for s in todo))} "
              f"(коридор себестоимости по CLAUDE.md — $10-20)")
        return 0

    cost = CostLog()
    results: dict = {}
    for s in plan:
        if s in skipped:
            print(f"⏭  {s}: артефакт есть, пропускаю")
            continue
        t0 = time.time()
        print(f"▶  {s} …")
        if s == "brief":
            results[s] = brief.run(cfg, ctx, topic, cost)
        elif s == "script":
            results[s] = script.run(cfg, ctx, cost)
        elif s == "critic":
            results[s] = critic.run(cfg, ctx, cost)
        elif s == "voice":
            results[s] = voice_run(cfg, ctx, cost)
        elif s == "assets":
            results[s] = assets.run_stage(cfg, ctx, cost)
        elif s == "motion":
            results[s] = motion.run_stage(cfg, ctx, cost)
        elif s == "assemble":
            results[s] = assemble.run_stage(cfg, ctx, cost)
        elif s == "thumbs":
            results[s] = thumbs.run_stage(cfg, ctx, cost)
        elif s == "meta":
            results[s] = meta.run_stage(cfg, ctx, cost)
        elif s == "passport":
            results[s] = passport.run_stage(cfg, ctx, cost, results, topic)
        print(f"   {json.dumps(results[s], ensure_ascii=False)[:200]}  "
              f"[{time.time()-t0:.0f}с, {human_money(cost.total)}]")
    print(f"\nГотово. Стоимость: {human_money(cost.total)} — " +
          ", ".join(f"{k} {human_money(v)}" for k, v in cost.by_stage().items()))
    print(f"Папка: {ctx}")
    return 0


def voice_run(cfg, ctx, cost):
    from .stages import voice
    return voice.run_stage(cfg, ctx, cost)


def main():
    ap = argparse.ArgumentParser(prog="pipeline", description="Конвейер производства роликов")
    ap.add_argument("--channel", help="space | business | geography")
    ap.add_argument("--topic", help="тема ролика")
    ap.add_argument("--slug", help="имя папки; по умолчанию из темы")
    ap.add_argument("--date", help="YYYY-MM-DD; по умолчанию сегодня")
    ap.add_argument("--from", dest="from_stage", choices=STAGES,
                    help="пересобрать начиная с этой стадии")
    ap.add_argument("--only", help="только эти стадии через запятую")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list-voices", action="store_true")
    args = ap.parse_args()

    if args.check or args.list_voices:
        cfg = Config(args.channel) if args.channel else Config()
        return cmd_check(cfg) if args.check else cmd_list_voices(cfg)
    if not args.channel:
        raise SystemExit("нужен --channel")
    return cmd_run(Config(args.channel), args)


if __name__ == "__main__":
    sys.exit(main())
