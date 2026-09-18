#!/bin/bash
# Полный прогон одного фильма без присмотра.
# Ждать процессы по пути ненадёжно: pgrep -f с длинным путём не срабатывал.
# Ждём по простому шаблону имени скрипта.
set -u
D="$1"; LOG="$2"
PY=/home/chak/yt/.venv/bin/python
cd /home/chak/yt
say() { echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }

say "=== старт $(basename "$D")"

# 1) добиваем реплики, которые не записались с первого раза
MISS=$($PY - "$D" <<'EOF'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
sh = json.loads((d/"timed.json").read_text(encoding="utf-8"))
have = {int(f.stem) for f in (d/"voice").glob("*.mp3") if f.stem.isdigit()}
print(",".join(str(s["id"]) for s in sh
               if (s.get("narr") or "").strip() and s["id"] not in have))
EOF
)
if [ -n "$MISS" ]; then
  say "добиваю озвучку: $MISS"
  for try in 1 2 3; do
    $PY scripts/voice_render.py "$D" "$MISS" >> "$LOG" 2>&1
    MISS=$($PY - "$D" <<'EOF'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
sh = json.loads((d/"timed.json").read_text(encoding="utf-8"))
have = {int(f.stem) for f in (d/"voice").glob("*.mp3") if f.stem.isdigit()}
print(",".join(str(s["id"]) for s in sh
               if (s.get("narr") or "").strip() and s["id"] not in have))
EOF
)
    [ -z "$MISS" ] && break
    sleep 30
  done
  say "осталось без озвучки: ${MISS:-нет}"
fi

# 2) ждём клипы Veo, если они уже запущены отдельно
while pgrep -f clips_render.py > /dev/null; do sleep 30; done
IDS=$($PY - "$D" <<'EOF'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
sh = json.loads((d/"timed.json").read_text(encoding="utf-8"))
have = {int(f.stem) for f in (d/"clips").glob("*.mp4")} if (d/"clips").exists() else set()
print(",".join(str(s["id"]) for s in sh if s.get("tier") == "anim" and s["id"] not in have))
EOF
)
if [ -n "$IDS" ]; then
  say "клипы Veo: $(echo "$IDS" | tr ',' '\n' | wc -l) шт"
  $PY scripts/clips_render.py "$D" "$IDS" >> "$LOG" 2>&1 || say "! клипы с ошибкой, идём дальше"
fi
say "клипов всего: $(ls "$D"/clips/*.mp4 2>/dev/null | wc -l)"

# 3) полная сборка
say "сборка…"
if $PY scripts/build_film.py "$D" 1.0 >> "$LOG" 2>&1; then
  say "=== ГОТОВО: $(ls "$D"/FILM_*.mp4 2>/dev/null | head -1)"
else
  say "=== СБОРКА УПАЛА"
fi
