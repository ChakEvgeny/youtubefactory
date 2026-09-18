#!/usr/bin/env python3
"""Перенос наработок опубликованного ролика на NAS с проверкой и удалением с SSD.

Порядок жёсткий: копируем -> сверяем контрольные суммы каждого файла ->
только после полного совпадения удаляем локальное. Без --yes ничего не удаляется.

Секреты на NAS не попадают никогда (правило проекта): .env, secrets/, ключи
сервисных аккаунтов исключаются, и если такой файл найден внутри проекта —
перенос останавливается.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, sys, time
from pathlib import Path

NAS = Path(os.getenv("NAS_DIR", "/mnt/nas/output"))
SECRET_NAMES = {".env", ".env.local", "credentials.json", "service_account.json"}
SECRET_DIRS = {"secrets", ".git"}
SECRET_SUFFIX = {".pem", ".key", ".p12"}


def sha(p: Path, buf=1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(buf):
            h.update(chunk)
    return h.hexdigest()


def walk(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(root)
        if any(part in SECRET_DIRS for part in rel.parts):
            continue
        yield p, rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="папка проекта на SSD")
    ap.add_argument("--dest", default="", help="папка на NAS (по умолчанию канал/имя)")
    ap.add_argument("--yes", action="store_true", help="удалить локальное после сверки")
    ap.add_argument("--keep", default="", help="через запятую: что оставить на SSD")
    a = ap.parse_args()

    src = Path(a.src).resolve()
    if not src.is_dir():
        sys.exit(f"нет папки {src}")
    keep = {k.strip() for k in a.keep.split(",") if k.strip()}

    # проверка на секреты
    found = [str(p.relative_to(src)) for p, rel in walk(src)
             if rel.name in SECRET_NAMES or rel.suffix in SECRET_SUFFIX]
    if found:
        sys.exit("СТОП: внутри проекта найдены секреты, перенос отменён:\n  " + "\n  ".join(found))

    # если проект лежит прямо в OUTPUT_DIR, имя папки не задваиваем
    out_root = Path(os.getenv('OUTPUT_DIR', '/mnt/d/youtube/output')).resolve()
    rel_parent = '' if src.parent == out_root else src.parent.name
    dest = Path(a.dest) if a.dest else (NAS / rel_parent / src.name if rel_parent else NAS / src.name)
    dest.mkdir(parents=True, exist_ok=True)
    files = [(p, rel) for p, rel in walk(src) if rel.parts[0] not in keep]
    total = sum(p.stat().st_size for p, _ in files)
    print(f"{src}\n  файлов {len(files)}, {total/1e9:.2f} ГБ → {dest}")
    if keep:
        print(f"  остаётся на SSD: {', '.join(sorted(keep))}")

    t0, done = time.time(), 0
    manifest = []
    for p, rel in files:
        d = dest / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if not (d.exists() and d.stat().st_size == p.stat().st_size):
            shutil.copy2(p, d)
        manifest.append({"path": str(rel), "bytes": p.stat().st_size})
        done += p.stat().st_size
        if len(manifest) % 50 == 0:
            print(f"  … {done/1e9:.2f}/{total/1e9:.2f} ГБ", flush=True)
    print(f"  копирование за {int(time.time()-t0)} c")

    print("  сверка контрольных сумм…", flush=True)
    bad = []
    for i, (p, rel) in enumerate(files, 1):
        h1, h2 = sha(p), sha(dest / rel)
        manifest[i - 1]["sha256"] = h1
        if h1 != h2:
            bad.append(str(rel))
        if i % 100 == 0:
            print(f"    {i}/{len(files)}", flush=True)
    if bad:
        sys.exit(f"РАСХОЖДЕНИЕ в {len(bad)} файлах, ничего не удаляю:\n  " + "\n  ".join(bad[:10]))
    print(f"  сверено {len(files)} файлов, расхождений нет")

    (dest / "ARCHIVE.json").write_text(json.dumps(
        {"source": str(src), "archived_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "files": len(files), "bytes": total, "kept_on_ssd": sorted(keep),
         "manifest": manifest}, ensure_ascii=False, indent=1), encoding="utf-8")

    if not a.yes:
        print("\nЛокальное НЕ удалено (нет --yes). Освободится "
              f"{total/1e9:.2f} ГБ.")
        return
    for p, rel in files:
        p.unlink()
    for d in sorted((x for x in src.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
        try:
            d.rmdir()
        except OSError:
            pass
    if not keep:
        try:
            src.rmdir()
        except OSError:
            pass
    print(f"\nудалено с SSD, освобождено {total/1e9:.2f} ГБ")


if __name__ == "__main__":
    main()
