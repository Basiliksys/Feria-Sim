# -*- coding: utf-8 -*-
"""Похідна географія світу: біоми, кліматичні пояси, риси й регіони.

Модуль навмисно не зберігає масив клітинок: у сейв пишеться лише компактна
агрегація на рівні ринку й провінції. Джерело — ``.map`` (біом/ринок клітинок,
coordinates, провінції, порти/річки), а для старих сейвів — наявні ``meta``
і ``burgs``.
"""
import collections
import math

BANDS = ("polar", "cold", "temperate", "tropical")


def _num(value, default=0.0, lo=None, hi=None):
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(v):
        return default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _as_int(value, default=0, lo=None, hi=None):
    return int(_num(value, default, lo, hi))


def lat_band(lat):
    """Кліматичний пояс за абсолютною широтою."""
    a = abs(_num(lat, 0.0, -90.0, 90.0))
    if a >= 60.0:
        return "polar"
    if a >= 40.0:
        return "cold"
    if a >= 20.0:
        return "temperate"
    return "tropical"


def _dominant(counter, default=None):
    """Найчастіше значення; тайбрейк — стабільний сортований порядок."""
    if not counter:
        return default
    return sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[0][0]


def _lat_for(y, meta):
    lat_n = _num(meta.get("lat_n"), 60.0, -90.0, 90.0)
    lat_s = _num(meta.get("lat_s"), -60.0, -90.0, 90.0)
    height = max(1.0, _num(meta.get("height"), 800.0, 1.0, 1e7))
    return lat_n - (_num(y, 0.0, -1e7, 1e7) / height) * (lat_n - lat_s)


def _normalize_biomes(biomes):
    out = {}
    for i, b in enumerate(biomes if isinstance(biomes, (list, tuple)) else []):
        if not isinstance(b, dict):
            continue
        bid = _as_int(b.get("i"), i, 0, 10000)
        out[bid] = dict(
            name=str(b.get("name", "Biome %d" % bid))[:120],
            habitability=_num(b.get("habitability"), 0.0, 0.0, 1e6),
        )
    return out


def _normalize_features(features):
    out = {}
    for f in features if isinstance(features, (list, tuple)) else []:
        if not isinstance(f, dict):
            continue
        fid = _as_int(f.get("i"), 0, 0, 10 ** 9)
        if not fid:
            continue
        land = f.get("land", True)
        water = (not bool(land)) or any(
            token in str(f.get("type", "")).lower()
            for token in ("ocean", "sea", "lake", "river", "water")
        )
        out[fid] = dict(
            name=str(f.get("name", "Feature %d" % fid))[:120],
            type=str(f.get("type", ""))[:60],
            water=bool(water),
        )
    return out


def build_geography(w, c_biome=None, c_market=None, biomes=None, features=None):
    """Будує ``world["geography"]``; повертає той самий словник."""
    meta = w.get("meta") if isinstance(w.get("meta"), dict) else {}
    markets = w.get("markets") if isinstance(w.get("markets"), dict) else {}
    burgs = w.get("burgs") if isinstance(w.get("burgs"), dict) else {}
    provinces = w.get("provinces") if isinstance(w.get("provinces"), dict) else {}
    goods = w.get("goods") if isinstance(w.get("goods"), dict) else {}
    bio = _normalize_biomes(biomes if biomes is not None else w.get("biomes"))
    feats = _normalize_features(features if features is not None else w.get("features"))

    # Домінуючий біом для кожного ринку — з клітинок карти, без збереження самих клітинок.
    cell_counts = collections.defaultdict(collections.Counter)
    if isinstance(c_biome, (list, tuple)) and isinstance(c_market, (list, tuple)):
        for i in range(min(len(c_biome), len(c_market))):
            mid = _as_int(c_market[i], -1, -1, 10 ** 9)
            bid = _as_int(c_biome[i], -1, -1, 10000)
            if mid in markets and bid in bio and bio[bid]["habitability"] > 0:
                cell_counts[mid][bid] += 1

    market_geo = {}
    for mid, m in markets.items():
        cb = burgs.get(m.get("center"), {}) if isinstance(m, dict) else {}
        lat = _lat_for(cb.get("y"), meta)
        fid = _as_int(cb.get("feature"), 0, 0, 10 ** 9) or None
        f = feats.get(fid, {})
        counts = cell_counts.get(mid)
        bi = _dominant(counts) if counts else None
        if bi is None:
            ci = _as_int(cb.get("cell"), -1, -1, 10 ** 9)
            if 0 <= ci < len(c_biome or ()):
                bi = _as_int(c_biome[ci], -1, -1, 10000)
                if bi not in bio:
                    bi = None
        coast = bool(cb.get("port")) or bool(f.get("water"))
        river = str(cb.get("kind", "")).lower() in ("river", "lake")
        province = _as_int(cb.get("province"), -1, -1, 10 ** 9)
        market_geo[mid] = dict(
            biome=bi, feature=fid, feature_name=f.get("name", ""),
            lat=round(lat, 2), band=lat_band(lat),
            coast=bool(coast), river=bool(river),
            province=province if province in provinces else None,
            region=province if province in provinces else None,
        )

    regions = {}
    for pid, pr in provinces.items():
        pburgs = [burgs[bid] for bid in (pr.get("burgs") or []) if bid in burgs]
        mids = sorted({int(b.get("market")) for b in pburgs if b.get("market") in markets})
        raw_tot = collections.Counter()
        for b in pburgs:
            for gid, amount in (b.get("raw") or {}).items():
                if gid in goods:
                    raw_tot[gid] += _num(amount, 0.0, 0.0, 1e12) * _num(
                        goods[gid].get("value"), 1.0, 1e-9, 1e9)
        signature = [gid for gid, _ in sorted(raw_tot.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        bands = collections.Counter(market_geo[m]["band"] for m in mids)
        bis = collections.Counter(market_geo[m]["biome"] for m in mids
                                  if market_geo[m]["biome"] is not None)
        cb = burgs.get(pr.get("burg"), {})
        center_lat = _lat_for(cb.get("y"), meta)
        regions[int(pid)] = dict(
            name=str(pr.get("name", "—"))[:120],
            state=_as_int(pr.get("state"), -1, -1, 10 ** 9),
            center=_as_int(pr.get("burg"), -1, -1, 10 ** 9),
            markets=mids,
            band=_dominant(bands, lat_band(center_lat)),
            biome=_dominant(bis),
            coast=any(market_geo[m]["coast"] for m in mids),
            river=any(market_geo[m]["river"] for m in mids),
            signature=signature,
            specialties=[],
        )

    geo = dict(
        biomes=bio, features=feats, market_geo=market_geo, regions=regions,
        derived=bool(c_biome is not None and c_market is not None),
    )
    w["geography"] = geo
    return geo


def ensure_geography(w):
    """Гарантує наявність географії; старі/пошкоджені сейви добудовуються з meta/burgs."""
    g = w.get("geography")
    ok = isinstance(g, dict) and isinstance(g.get("market_geo"), dict) \
        and isinstance(g.get("regions"), dict) and bool(g["market_geo"])
    if ok:
        for mid, mg in g["market_geo"].items():
            if not isinstance(mid, int) or not isinstance(mg, dict) \
                    or not math.isfinite(_num(mg.get("lat"), float("nan"))):
                ok = False
                break
    if ok:
        for rid, r in g["regions"].items():
            if not isinstance(rid, int) or not isinstance(r, dict):
                ok = False
                break
            for key in ("signature", "specialties", "markets"):
                if not isinstance(r.get(key), list):
                    ok = False
                    break
            if not ok:
                break
    if ok:
        # Старі версії регіонів можуть не мати specialties — додаємо порожній список.
        for r in g["regions"].values():
            r.setdefault("specialties", [])
            r.setdefault("signature", [])
            r.setdefault("markets", [])
        w["geography"] = g
        return g
    return build_geography(w)


def market_geo(sim, mid):
    """Зручний доступ з Sim: ``sim.geography['market_geo'][mid]``."""
    geo = getattr(sim, "geography", None) or ensure_geography(sim.w)
    return (geo.get("market_geo") or {}).get(mid, {})
