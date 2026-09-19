#!/usr/bin/env python3
"""Карта для клочка Survivor's Notebook: настоящая береговая линия, дневниковая манера.

Нейросеть географию выдумывает, поэтому карты рисуем кодом по Natural Earth
(1:50m, /mnt/d/youtube/cache/geo/ne_50m_land.geojson). Проекция — простая
равнопромежуточная с поправкой cos(широты); долготы переводим в 0..360,
чтобы район Берингова пролива не рвался на линии перемены дат.

Описание карты — JSON:
  {"bbox": [lon0, lon1, lat0, lat1],       # lon в 0..360
   "size": [760, 520],
   "points": [{"name": "Point Barrow", "lat": 71.29, "lon": -156.79, "dx": 10, "dy": -30}],
   "route": [[lat, lon], ...], "route_label": "approximate",
   "title": "..."}
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

GEO = Path("/mnt/d/youtube/cache/geo/ne_50m_land.geojson")
F = Path.home() / ".fonts"
INK = (38, 34, 52); RUST = (150, 62, 40); PENCIL = (78, 73, 68)
SEA = (196, 214, 222); LAND = (236, 226, 204)


def lon360(x: float) -> float:
    return x + 360 if x < 0 else x


def render(spec: dict, out: Path):
    W, H = spec.get("size", [760, 520])
    lon0, lon1, lat0, lat1 = spec["bbox"]
    k = math.cos(math.radians((lat0 + lat1) / 2))
    sx = W / ((lon1 - lon0) * k); sy = H / (lat1 - lat0)
    s = min(sx, sy)
    ox = (W - (lon1 - lon0) * k * s) / 2; oy = (H - (lat1 - lat0) * s) / 2

    def P(lat, lon):
        return (ox + (lon360(lon) - lon0) * k * s, oy + (lat1 - lat) * s)

    img = Image.new("RGBA", (W, H), SEA + (140,))
    d = ImageDraw.Draw(img)
    for f in json.loads(GEO.read_text())["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            ring = [(lat, lon) for lon, lat in poly[0]]
            if not any(lat0 - 3 < la < lat1 + 3 for la, _ in ring):
                continue
            # Разворачиваем долготы контура непрерывно (без скачков на ±360) и
            # сдвигаем весь контур к центру карты: так Евразия, пересекающая
            # нулевой меридиан, и Аляска с другой стороны линии дат ложатся рядом.
            un = [ring[0][1]]
            for _, lo in ring[1:]:
                x = lo
                while x - un[-1] > 180: x -= 360
                while x - un[-1] < -180: x += 360
                un.append(x)
            mid = (lon0 + lon1) / 2
            shift = min((0, 360, -360, 720), key=lambda k: abs(sum(un) / len(un) + k - mid))
            pts = [(ox + (lo + shift - lon0) * k * s, oy + (lat1 - la) * s)
                   for (la, _), lo in zip(ring, un)]
            d.polygon(pts, fill=LAND + (255,))
            # контур без шва по 180-му меридиану: это разрез данных, а не берег
            for (a, pa), (b, pb) in zip(zip(ring, pts), zip(ring[1:] + ring[:1], pts[1:] + pts[:1])):
                if abs(abs(a[1]) - 180) < 1e-6 and abs(abs(b[1]) - 180) < 1e-6:
                    continue
                d.line([pa, pb], fill=PENCIL + (230,), width=2)
    # штриховка вдоль берега не нужна: карандашный контур + лёгкое размытие краски
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    d = ImageDraw.Draw(img)
    hand = ImageFont.truetype(str(F / "ReenieBeanie.ttf"), int(H * 0.075))
    small = ImageFont.truetype(str(F / "SpecialElite-Regular.ttf"), int(H * 0.034))

    route = spec.get("route") or []
    if len(route) > 1:
        rp = [P(la, lo) for la, lo in route]
        # пунктир: рисуем отрезки через один
        seg = []
        for a, b in zip(rp, rp[1:]):
            n = max(int(math.dist(a, b) / 9), 1)
            for i in range(n):
                t0, t1 = i / n, (i + 0.55) / n
                seg.append(((a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                            (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)))
        for a, b in seg:
            d.line([a, b], fill=RUST + (255,), width=4)
        # наконечник стрелки на конце
        (x0, y0), (x1, y1) = rp[-2], rp[-1]
        ang = math.atan2(y1 - y0, x1 - x0)
        for da in (2.6, -2.6):
            d.line([(x1, y1), (x1 + 16 * math.cos(ang + da), y1 + 16 * math.sin(ang + da))],
                   fill=RUST + (255,), width=4)
    for p in spec.get("points", []):
        x, y = P(p["lat"], p["lon"])
        if not p.get("region"):           # у региона подпись без точки
            d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=INK + (255,))
        d.text((x + p.get("dx", 10), y + p.get("dy", -34)), p["name"], font=hand, fill=INK + (255,))
    if spec.get("route_label"):
        d.text((W * 0.03, H - H * 0.08), spec["route_label"], font=small, fill=PENCIL + (255,))
    img.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("out")
    a = ap.parse_args()
    print(render(json.loads(Path(a.spec).read_text()), Path(a.out)))


if __name__ == "__main__":
    main()
