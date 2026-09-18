#!/usr/bin/env bash
# Проверка окружения после перезагрузки. Ничего не запускает и не меняет —
# только смотрит, всё ли на месте, чтобы не выяснять это посреди сборки ролика.
#   bash scripts/doctor.sh
cd "$(dirname "$0")/.." || exit 1
ok=0; bad=0
say(){ if [ "$1" = ok ]; then echo "  ✓ $2"; ok=$((ok+1)); else echo "  ✗ $2"; bad=$((bad+1)); fi; }

echo "== диски =="
df -h /mnt/d >/dev/null 2>&1 && say ok "диск D ($(df -h /mnt/d | tail -1 | awk '{print $4}') свободно)" \
                             || say no "диск D не смонтирован"
if df -h /mnt/nas >/dev/null 2>&1 && [ -d /mnt/nas/output ]; then
  say ok "NAS ($(ls /mnt/nas/output/explain 2>/dev/null | wc -l) проектов в explain)"
else
  say no "NAS недоступен — открой диск N в проводнике Windows, он переподключится"
fi

echo "== окружение =="
[ -x .venv/bin/python ] && say ok "venv ($(.venv/bin/python -V 2>&1))" || say no "нет .venv"
[ -d motion/node_modules ] && say ok "Remotion установлен" || say no "нет motion/node_modules — npm i в motion/"
command -v ffmpeg >/dev/null && say ok "ffmpeg" || say no "нет ffmpeg"
command -v yt-dlp  >/dev/null && say ok "yt-dlp"  || say no "нет yt-dlp"

echo "== ключи (наличие, не значение) =="
for k in ELEVENLABS_API_KEY GOOGLE_API_KEY GOOGLE_CLOUD_PROJECT ANTHROPIC_API_KEY YOUTUBE_API_KEY; do
  grep -q "^$k=" .env 2>/dev/null && say ok "$k" || say no "$k отсутствует в .env"
done
[ -f secrets/*.json ] 2>/dev/null || ls secrets/*.json >/dev/null 2>&1 \
  && say ok "ключ сервисного аккаунта GCP" || say no "нет secrets/*.json (нужен только для Veo)"

echo "== квоты =="
.venv/bin/python - <<'PY' 2>/dev/null || echo "  ? ElevenLabs недоступен"
import os, json, urllib.request
from dotenv import load_dotenv; load_dotenv("/home/chak/yt/.env")
k = os.getenv("ELEVENLABS_API_KEY")
r = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": k})
d = json.load(urllib.request.urlopen(r, timeout=20))
free = d["character_limit"] - d["character_count"]
print(f"  ✓ ElevenLabs: свободно {free:,} символов (~{free//13000} роликов)")
PY

echo "== git =="
b=$(git branch --show-current 2>/dev/null)
n=$(git status --porcelain 2>/dev/null | wc -l)
say ok "ветка $b, незакоммиченных файлов: $n"
git ls-remote --heads origin >/dev/null 2>&1 && say ok "GitHub доступен" || say no "GitHub недоступен (ключ SSH?)"

echo
echo "== затраты =="
.venv/bin/python scripts/costs.py 2>/dev/null | tail -3

echo
echo "итог: $ok в порядке, $bad проблем"
[ "$bad" -eq 0 ] && echo "конвейер готов к работе"
