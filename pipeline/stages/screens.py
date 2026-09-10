"""screens — карточки прессы: Playwright-скриншот шапки статьи + Remotion PressCard.

Fair use: ≤4с на карточку, только под комментарий, источник в описании и в паспорте.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from ..util import Cache, sha1

PUBLIC = "press"
MAX_SEC = 4.0
COOKIE_SELECTORS = ["#onetrust-accept-btn-handler", "button:has-text('Accept all')",
                    "button:has-text('Accept')", "button:has-text('Agree')",
                    "button:has-text('I agree')", "button:has-text('Got it')"]


def screenshot(url: str, cache: Cache) -> Path | None:
    p = cache.blob_path("press_shots", sha1("press", url), ".png")
    if p.exists():
        return p
    from playwright.sync_api import sync_playwright
    # некоторые сайты (ITV) рвут HTTP/2 для headless — второй заход без него
    for args in ([], ["--disable-http2"]):
        if p.exists():
            break
        try:
            _grab(url, p, args)
        except Exception as e:
            print(f"    ! скриншот {url[:60]} ({'http1' if args else 'http2'}): {str(e)[:70]}")
    return p if p.exists() else None


def _grab(url: str, p: Path, args: list[str]) -> None:
    from playwright.sync_api import sync_playwright
    if True:
        with sync_playwright() as pw:
            b = pw.chromium.launch(args=args)
            pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5,
                            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36")
            pg.goto(url, timeout=45000, wait_until="domcontentloaded")
            # баннеры согласия догружаются с задержкой — три захода с паузами
            for _ in range(3):
                pg.wait_for_timeout(1500)
                for sel in COOKIE_SELECTORS:
                    try:
                        pg.click(sel, timeout=700)
                        break
                    except Exception:
                        pass
            pg.evaluate("""() => {
                document.querySelectorAll('[class*=cookie],[id*=cookie],[class*=consent],[id*=consent],'
                  + '[class*=privacy],[id*=privacy],[class*=paywall],[class*=newsletter],[role=dialog]')
                  .forEach(e => e.remove());
                // всё, что фиксировано поверх страницы и перекрывает центр — долой
                for (const el of Array.from(document.querySelectorAll('body *'))) {
                  const cs = getComputedStyle(el);
                  if ((cs.position === 'fixed' || cs.position === 'sticky') && el.offsetHeight > 120
                      && el.getBoundingClientRect().top < 500) el.remove();
                }
                document.body.style.overflow = 'visible';
            }""")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(p), clip={"x": 0, "y": 0, "width": 1440, "height": 900})
            b.close()


def outlet_of(url: str, title: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    names = {"bbc.co.uk": "BBC", "bbc.com": "BBC", "theguardian.com": "The Guardian",
             "ft.com": "Financial Times", "news.sky.com": "Sky News", "reuters.com": "Reuters",
             "itv.com": "ITV News", "cnbc.com": "CNBC", "bloomberg.com": "Bloomberg",
             "expressandstar.com": "Express & Star", "autocar.co.uk": "Autocar",
             "smmt.co.uk": "SMMT", "carbuzz.com": "CarBuzz", "techcrunch.com": "TechCrunch",
             "theregister.com": "The Register", "evo.co.uk": "evo", "bild.de": "Bild"}
    return names.get(host, host.split(".")[0].capitalize())


def rank_sources(press: str, text: str, sources: list[dict], used: dict | None = None,
                 dead: set | None = None) -> list[dict]:
    """Кандидаты-источники для карточки по убыванию совпадения: сначала издание,
    названное в shotlist, затем факты брифа, чьи слова/числа совпадают с текстом
    кадра. Уже показанные URL получают штраф (одна статья не крутится по кругу),
    недоступные (dead) исключаются."""
    used, dead = used or {}, dead or set()
    key = (press or "").lower()
    alias = {"bbc": "bbc", "financial times": "ft.com", "ft": "ft.com", "sky": "sky",
             "smmt": "smmt", "bild": "bild", "itv": "itv", "reuters": "reuters", "guardian": "guardian"}
    needle = next((v for k, v in alias.items() if k in key), key.split()[0] if key else "")
    words = set(re.findall(r"[a-z]{5,}", text.lower()))
    nums = set(re.findall(r"\d[\d,.]*", text))
    scored = []
    for s in sources:
        url = s.get("source_url") or ""
        if not url or url in dead:
            continue
        ft = (s.get("fact", "") or "") + " " + str(s.get("number") or "")
        sc = len(words & set(re.findall(r"[a-z]{5,}", ft.lower()))) + 2 * len(nums & set(re.findall(r"\d[\d,.]*", ft)))
        if needle and needle in (url + " " + s.get("source_title", "")).lower():
            sc += 5
        sc -= 1.5 * used.get(url, 0)
        if sc >= (1 if not press else 2):
            scored.append((sc, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored]


def match_source(press: str, text: str, sources: list[dict], used: dict | None = None) -> dict | None:
    r = rank_sources(press, text, sources, used)
    return r[0] if r else None


def run_stage(cfg, ctx: Path, cost, preview_sec: float | None = None) -> dict:
    from .motion import MOTION_DIR, render_one, COMP
    COMP.setdefault("press", "PressCard")
    cache = Cache(cfg.paths.cache_dir)
    shots = json.loads((ctx / "shotlist.json").read_text(encoding="utf-8"))
    brief = json.loads((ctx / "brief.json").read_text(encoding="utf-8"))
    sources = brief.get("facts", [])
    todo = [s for s in shots if s.get("src_kind") == "screens"
            and (preview_sec is None or s["start"] < preview_sec)]
    palette = cfg.channel["thumb_palette"]
    pub = MOTION_DIR / "public" / PUBLIC
    pub.mkdir(parents=True, exist_ok=True)
    out_dir = cfg.paths.cache_dir / "screens"
    out_dir.mkdir(parents=True, exist_ok=True)

    done, log, fallback, used, dead = [], [], 0, {}, set()
    scene_text: dict = {}
    for x in shots:
        scene_text[x.get("scene")] = scene_text.get(x.get("scene"), "") + " " + (x.get("text") or "")
    for sh in todo:
        src = shot = None
        press = sh.get("press") or ""
        cands = rank_sources(press, sh.get("text", ""), sources, used, dead)
        if not cands:                            # по кадру пусто -> по всей сцене
            cands = rank_sources(press, scene_text.get(sh.get("scene"), ""), sources, used, dead)
        if not cands and not press:              # все факты брифа — про эту историю: наименее показанный
            cands = sorted([x for x in sources if x.get("source_url") and x["source_url"] not in dead],
                           key=lambda x: used.get(x["source_url"], 0))
        # до трёх кандидатов: недоступный сайт запоминаем и больше не пробуем
        for cand in cands[:3]:
            shot = screenshot(cand["source_url"], cache)
            if shot:
                src = cand
                used[cand["source_url"]] = used.get(cand["source_url"], 0) + 1
                break
            dead.add(cand["source_url"])
        if not shot:
            # источник не нашёлся: показываем визуальный объект фразы, карточка — последней
            sh["src_kind"] = "collage" if sh.get("visual") else "card"
            fallback += 1
            log.append({"idx": sh["idx"], "press": sh.get("press"),
                        "result": f"no source -> {sh['src_kind']}"})
            continue
        if not (pub / shot.name).exists():
            shutil.copy(shot, pub / shot.name)
        outlet = outlet_of(src["source_url"], src.get("source_title", ""))
        date = (src.get("date") or "")[:10]
        dur = min(sh["dur"], MAX_SEC)
        props = {"shot": f"{PUBLIC}/{shot.name}", "outlet": outlet, "date": date,
                 "headline": f"{(src.get('source_title') or '')[:70]} — {urlparse(src['source_url']).netloc}",
                 "palette": palette, "durationInFrames": int(dur * 30)}
        clip = out_dir / f"{sha1('press', json.dumps(props, sort_keys=True))}.mp4"
        if not clip.exists():
            cwd = os.getcwd()
            os.chdir(MOTION_DIR)
            try:
                render_one("press", props, clip)
            finally:
                os.chdir(cwd)
        if sh["dur"] > MAX_SEC + 0.3:        # карточка ≤4с, хвост слота уходит в карточку-callout
            sh["press_tail"] = round(sh["dur"] - MAX_SEC, 2)
        done.append({"idx": sh["idx"], "file": str(clip), "outlet": outlet, "url": src["source_url"]})
        log.append({"idx": sh["idx"], "press": sh.get("press"), "result": "press_card",
                    "outlet": outlet, "url": src["source_url"], "title": src.get("source_title"),
                    "date": date, "basis": "fair use, ≤4s, commentary"})

    (ctx / "shotlist.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    (ctx / "screens.json").write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    lp = ctx / "sources_log.json"
    prev = [x for x in (json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else [])
            if x.get("stage") != "screens"]
    lp.write_text(json.dumps(prev + [{"stage": "screens", **x} for x in log],
                             ensure_ascii=False, indent=1), encoding="utf-8")
    return {"screens_shots": len(todo), "rendered": len(done), "fallback_to_card": fallback}
