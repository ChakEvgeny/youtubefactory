#!/usr/bin/env python3
"""Субтитры и переводы заголовка/описания на YouTube через API, без Studio.

Зачем: 2026-09-18 Studio перестал сохранять субтитры во всех роликах, а ручная
загрузка 5 языков на каждый ролик — это 10 действий в интерфейсе.

Доступ — OAuth от имени владельца канала (ключ API умеет только читать).
  Клиент: один на всё, JSON из Google Cloud Console (тип «Desktop app»),
          путь в .env: YT_OAUTH_CLIENT=/home/chak/.config/yt/client_secret.json
  Токен:  один на канал, ~/.config/yt/tokens/<канал>.json — вне репозитория и
          вне NAS (правило о секретах).

  python scripts/yt_publish.py auth survival          # один раз на канал
  python scripts/yt_publish.py captions survival <video_id> <папка ролика>
  python scripts/yt_publish.py meta survival <video_id> <папка ролика>

Квота: captions.insert/update = 400 единиц, videos.update = 50, list = 1.
Ролик с 5 языками субтитров ≈ 2050 единиц из 10 000 в сутки.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl",
          # аналитика (показы, CTR, удержание) — добавлено 2026-09-19, нужен перевход
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
CONF = Path.home() / ".config" / "yt"
LANG_NAMES = {"en": "English", "es-419": "Español (Latinoamérica)", "pt-BR": "Português (Brasil)",
              "de": "Deutsch", "fr": "Français"}


def creds(channel: str) -> Credentials:
    tok = CONF / "tokens" / f"{channel}.json"
    if not tok.exists():
        sys.exit(f"нет доступа к каналу «{channel}»: сначала  yt_publish.py auth {channel}")
    # права берём из самого токена: старые токены выданы без аналитики
    c = Credentials.from_authorized_user_file(str(tok))
    if not c.valid:
        c.refresh(Request())
        tok.write_text(c.to_json(), encoding="utf-8")
    return c


def auth(channel: str):
    from google_auth_oauthlib.flow import InstalledAppFlow
    client = os.getenv("YT_OAUTH_CLIENT") or str(CONF / "client_secret.json")
    if not Path(client).exists():
        sys.exit(f"нет OAuth-клиента: {client}")
    flow = InstalledAppFlow.from_client_secrets_file(client, SCOPES)
    # WSL: браузер открываешь сам в Windows, localhost пробрасывается в WSL
    c = flow.run_local_server(port=8765, open_browser=False,
                              authorization_prompt_message="Открой в браузере и выбери канал:\n{url}\n")
    (CONF / "tokens").mkdir(parents=True, exist_ok=True)
    tok = CONF / "tokens" / f"{channel}.json"
    tok.write_text(c.to_json(), encoding="utf-8"); tok.chmod(0o600)
    yt = build("youtube", "v3", credentials=c)
    ch = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    print(f"канал «{channel}» → {ch['snippet']['title']} ({ch['id']}), токен: {tok}")


def srt_files(d: Path) -> dict[str, Path]:
    out = {"en": d / "subs_en.srt"}
    for f in sorted((d / "i18n").glob("subs_*.srt")):
        out[f.stem.removeprefix("subs_")] = f
    return {k: v for k, v in out.items() if v.exists()}


def captions(channel: str, vid: str, d: Path, only_missing: bool = False):
    yt = build("youtube", "v3", credentials=creds(channel))
    # Английскую дорожку кладём под ЯЗЫК ЗВУКА ролика (у нас en-US). Залитая как «en»
    # на «Карлуке» она встала отдельной строкой, а у оригинала субтитров не было.
    audio = yt.videos().list(part="snippet", id=vid).execute()["items"][0]["snippet"] \
        .get("defaultAudioLanguage") or "en"
    orig = audio if audio.startswith("en") else "en"
    tracks = [c for c in yt.captions().list(part="snippet", videoId=vid).execute().get("items", [])
              if c["snippet"].get("trackKind") != "asr"]    # автосубтитры YouTube не трогаем
    for c in tracks:
        # английская дорожка не под тем кодом — удаляем, иначе будет два English
        if c["snippet"]["language"].startswith("en") and c["snippet"]["language"] != orig:
            yt.captions().delete(id=c["id"]).execute()
            print(f"  {c['snippet']['language']}: удалена (оригинал — {orig})")
    have = {c["snippet"]["language"]: c["id"] for c in tracks
            if not (c["snippet"]["language"].startswith("en") and c["snippet"]["language"] != orig)}
    files = {(orig if k == "en" else k): v for k, v in srt_files(d).items()}
    for lang, f in files.items():
        if only_missing and lang in have:
            print(f"  {lang}: уже есть, не трогаю")   # дорожку мог залить сам автор
            continue
        media = MediaFileUpload(str(f), mimetype="application/octet-stream", resumable=False)
        if lang in have:
            yt.captions().update(part="snippet", media_body=media,
                                 body={"id": have[lang], "snippet": {"isDraft": False}}).execute()
            print(f"  {lang}: обновлены")
        else:
            yt.captions().insert(part="snippet", media_body=media, body={"snippet": {
                "videoId": vid, "language": lang,
                "name": LANG_NAMES.get(lang, LANG_NAMES["en"] if lang.startswith("en") else lang),
                "isDraft": False}}).execute()
            print(f"  {lang}: загружены")


def meta(channel: str, vid: str, d: Path):
    """Переводы заголовка и описания из i18n/meta_<язык>.txt (формат translate_subs.py)."""
    yt = build("youtube", "v3", credentials=creds(channel))
    v = yt.videos().list(part="snippet,localizations", id=vid).execute()["items"][0]
    sn = v["snippet"]
    loc = v.get("localizations", {})
    for f in sorted((d / "i18n").glob("meta_*.txt")):
        lang = f.stem.removeprefix("meta_")
        title, _, desc = f.read_text(encoding="utf-8").partition("=" * 60)
        loc[lang] = {"title": title.strip()[:100], "description": desc.strip()[:5000]}
    body = {"id": vid, "localizations": loc,
            "snippet": {"title": sn["title"], "description": sn.get("description", ""),
                        "categoryId": sn["categoryId"], "tags": sn.get("tags", []),
                        "defaultLanguage": sn.get("defaultLanguage") or "en",
                        # snippet перезаписывается целиком: всё, что не передали, сбросится
                        **({"defaultAudioLanguage": sn["defaultAudioLanguage"]}
                           if sn.get("defaultAudioLanguage") else {})}}
    yt.videos().update(part="snippet,localizations", body=body).execute()
    print(f"  переводы заголовка/описания: {', '.join(sorted(loc))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["auth", "captions", "meta"])
    ap.add_argument("channel")
    ap.add_argument("video", nargs="?")
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--only-missing", action="store_true", help="не перезаписывать существующие дорожки")
    a = ap.parse_args()
    if a.cmd == "auth":
        return auth(a.channel)
    if not (a.video and a.dir):
        sys.exit("нужны video_id и папка ролика")
    if a.cmd == "captions":
        return captions(a.channel, a.video, Path(a.dir), a.only_missing)
    meta(a.channel, a.video, Path(a.dir))


if __name__ == "__main__":
    main()
