#!/usr/bin/env python3
"""Заливка очереди тем из data/topics_queue.json в Supabase.
Идемпотентна: тема с тем же title и channel не дублируется."""
import json, os, sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
try:
    sb.table("topics").select("id").limit(1).execute()
except Exception:
    sys.exit("Таблицы topics нет — примени supabase/migration_topics.sql в SQL Editor.")

src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "topics_queue.json"
rows = json.loads(src.read_text(encoding="utf-8"))
added = skipped = 0
no_source_col = False
for r in rows:
    ex = (sb.table("topics").select("id").eq("channel", r["channel"])
          .eq("title", r["title"]).limit(1).execute().data)
    if ex:
        skipped += 1
        continue
    row = dict(r)
    if no_source_col:
        row["summary"] = f"[source={row.pop('source', 'manual')}] {row.get('summary') or ''}"
    try:
        sb.table("topics").insert(row).execute()
    except Exception as e:
        if "source" in str(e) and not no_source_col:      # колонки ещё нет — примени migration_topics_source.sql
            no_source_col = True
            row["summary"] = f"[source={row.pop('source', 'manual')}] {row.get('summary') or ''}"
            sb.table("topics").insert(row).execute()
        else:
            raise
    added += 1
if no_source_col:
    print("колонки topics.source нет — пометка source ушла в summary; примени supabase/migration_topics_source.sql")
print(f"добавлено {added}, уже было {skipped}")
for t in sb.table("topics").select("id,channel,title,status,priority,event_date").order("priority").execute().data:
    print(f"  #{t['id']} [{t['status']}] p{t['priority']} {t['event_date']} {t['channel']}: {t['title'][:56]}")
