#!/usr/bin/env bash
# Синхронизация заметок и правил на сторону Windows (Claude Code в Windows держит
# свой каталог настроек и WSL-овские заметки не видит).
#
#   bash scripts/sync_windows.sh
#
# Копирует:
#   заметки  ~/.claude/projects/-home-chak-yt/memory  ->  C:\Users\chake\.claude\projects\d--youtube\memory
#   правила  docs/*.md (выборка)                      ->  D:\youtube\docs
# Оригиналы всегда в репозитории; на стороне Windows — копии только для чтения.
set -euo pipefail

MEM_SRC="$HOME/.claude/projects/-home-chak-yt/memory"
MEM_DST="/mnt/c/Users/chake/.claude/projects/d--youtube/memory"
DOC_SRC="$(cd "$(dirname "$0")/.." && pwd)/docs"
DOC_DST="/mnt/d/youtube/docs"
DOCS=(channels_state.md thumbnail_standard.md explain_channel.md notebook_channel.md case_room_channel.md)

[ -d "$MEM_DST" ] || { echo "нет папки $MEM_DST — открой Claude Code в Windows на D:\\youtube хотя бы раз"; exit 1; }
mkdir -p "$DOC_DST"
cp "$MEM_SRC"/*.md "$MEM_DST"/
for d in "${DOCS[@]}"; do cp "$DOC_SRC/$d" "$DOC_DST/$d"; done
echo "заметки: $(ls "$MEM_DST" | wc -l) файлов -> $MEM_DST"
echo "правила: ${#DOCS[@]} файлов -> $DOC_DST"
echo "правила верхнего уровня — D:\\youtube\\CLAUDE.md (правится вручную)"
