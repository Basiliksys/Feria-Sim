# -*- coding: utf-8 -*-
"""Універсальний імпортер .map та .json файлів з Azgaar Fantasy Map Generator.

Підтримує:
- Сучасний .map формат з економічним шаром (1.153.x, зокрема Ферія);
- Стандартний .map з https://azgaar.github.io/Fantasy-Map-Generator/ (різних версій, у т.ч. gzip або без економіки);
- Експорт Save -> JSON із FMG.

Якщо в карті відсутні товари/ринки/торгівля, автоматично синтезує їх на основі
`goods_default.json`, біомів, міст, портів та координат.
"""
import collections
import gzip
import io
import json
import math
import os
import random
import re

from . import lore_data as LD

BULK_RATE = 100.0   # од. сировини на 1000 селян/міс при biomeOutput = 1
POINT_RATE = 18.0   # од. на 1000 селян/міс для «точкових» ресурсів клітинки

# Межі для недовірених .map-файлів: захист від decompression bomb та надто великих файлів.
MAX_MAP_RAW_BYTES = 64 * 1024 * 1024
MAX_MAP_TEXT_BYTES = 64 * 1024 * 1024
MAX_MAP_DIMENSION = 16384
_GZIP_CHUNK = 1 << 20


def _num(value, default=0.0, lo=None, hi=None):
    """Скінченне число з фолбеком іoptional range-клампом (імпортний кордон)."""
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(v):
        return default
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def _integer(value, default=0, lo=None, hi=None):
    return int(_num(value, default, lo, hi))


def _optional_int(value, lo=None, hi=None):
    v = _num(value, None, lo, hi)
    return None if v is None else int(v)


def _sanitize_numbers(obj):
    """Рекурсивно замінює NaN/inf на 0 (останній рубіж перед світом)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else 0.0
    if isinstance(obj, dict):
        return {k: _sanitize_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_numbers(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_numbers(v) for v in obj)
    return obj


def _normalize_geo(geo):
    if not isinstance(geo, dict):
        geo = {}
    return {
        "latN": _num(geo.get("latN"), 60.0, -90.0, 90.0),
        "latS": _num(geo.get("latS"), -60.0, -90.0, 90.0),
    }


def _normalize_units(units):
    if not isinstance(units, dict):
        units = {}
    d = units.get("distance")
    if not isinstance(d, dict):
        d = {}
    return {"distance": {
        "unit": str(d.get("unit") or "km"),
        "scale": _num(d.get("scale"), 3.0, 1e-6, 1000.0),
    }}

# Попит, якого може не бути у .map (злитки, ремесло, гроші) — інакше їх ціна «провалюється».
EXTRA_COVERAGE = {
    LD.GOOD_IDS["iron"]: {"military": 0.15},
    LD.GOOD_IDS["copper"]: {"utilities": 0.15},
    LD.GOOD_IDS["tin"]: {"utilities": 0.15},
    LD.GOOD_IDS["silver"]: {"luxury": 0.4},
    LD.GOOD_IDS["gold"]: {"luxury": 0.5},
    LD.GOOD_IDS["hemp"]: {"utilities": 0.3},
    LD.GOOD_IDS["gemstones"]: {"luxury": 0.5},
    LD.GOOD_IDS["dyes"]: {"luxury": 0.5},
    LD.GOOD_IDS["amber"]: {"utilities": 0.3},
    LD.GOOD_IDS["saltpeter"]: {"military": 0.3},
    LD.GOOD_IDS["paper"]: {"luxury": 0.3},
    LD.GOOD_IDS["ink"]: {"luxury": 0.2},
    LD.GOOD_IDS["bronze"]: {"military": 0.25},
    LD.GOOD_IDS["sails"]: {"military": 0.5},
    LD.GOOD_IDS["coins"]: {"luxury": 0.5},
    LD.GOOD_IDS["jewelry"]: {"luxury": 1.0},
    LD.GOOD_IDS["tar"]: {"utilities": 0.4},
    LD.GOOD_IDS["leather"]: {"utilities": 0.3},
    LD.GOOD_IDS["ropes"]: {"utilities": 0.5},
    LD.GOOD_IDS["slaves"]: {"utilities": 1.0},
    LD.GOOD_IDS["mahogany"]: {"luxury": 1.0},
}

DEFAULT_BIOMES = [
    {"i": 0, "name": "Marine", "habitability": 0},
    {"i": 1, "name": "Hot desert", "habitability": 4},
    {"i": 2, "name": "Cold desert", "habitability": 10},
    {"i": 3, "name": "Savanna", "habitability": 22},
    {"i": 4, "name": "Grassland", "habitability": 30},
    {"i": 5, "name": "Tropical seasonal forest", "habitability": 50},
    {"i": 6, "name": "Temperate deciduous forest", "habitability": 100},
    {"i": 7, "name": "Tropical rainforest", "habitability": 80},
    {"i": 8, "name": "Temperate rainforest", "habitability": 90},
    {"i": 9, "name": "Taiga", "habitability": 12},
    {"i": 10, "name": "Tundra", "habitability": 4},
    {"i": 11, "name": "Glacier", "habitability": 0},
    {"i": 12, "name": "Wetland", "habitability": 12},
]

DEFAULT_GOODS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "goods_default.json")


def _arr(line):
    if not line or not line.strip():
        return []
    out = []
    for x in line.rstrip(",").split(","):
        if not x.strip():
            continue
        try:
            v = float(x)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(v):
            out.append(int(v))
    return out


def _clean(s):
    return s.encode("utf-8", "ignore").decode("utf-8") if isinstance(s, str) else s


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _try_json(line):
    s = line.strip()
    if not s or s[0] not in "[{":
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _is_int_csv(line):
    s = line.strip()
    if not s or s[0] in "[{<":
        return False
    first = s.split(",", 1)[0].strip()
    try:
        float(first)
        return True
    except Exception:
        return False


def _load_default_goods():
    with open(DEFAULT_GOODS_PATH, encoding="utf-8") as f:
        return json.load(f)


def read_map_text(path):
    """Читає .map з жорсткими лімітами на сирий і розпакований розмір."""
    with open(path, "rb") as f:
        raw = f.read(MAX_MAP_RAW_BYTES + 1)
    if len(raw) > MAX_MAP_RAW_BYTES:
        raise ValueError(
            f"Файл карти занадто великий (>{MAX_MAP_RAW_BYTES} байтів): {path}"
        )
    if raw[:2] == b"\x1f\x8b":
        # Потокове розпакування: зупиняємося одразу після перевищення ліміту,
        # щоб decompression bomb не з'їла всю пам'ять.
        dec = gzip.GzipFile(fileobj=io.BytesIO(raw))
        parts, total = [], 0
        try:
            while True:
                chunk = dec.read(_GZIP_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_MAP_TEXT_BYTES:
                    raise ValueError(
                        f"Розпакована карта занадто велика (>{MAX_MAP_TEXT_BYTES} байтів): {path}"
                    )
                parts.append(chunk)
        finally:
            dec.close()
        raw = b"".join(parts)
    if len(raw) > MAX_MAP_TEXT_BYTES:
        raise ValueError(
            f"Карта занадто велика (>{MAX_MAP_TEXT_BYTES} байтів): {path}"
        )
    return raw.decode("utf-8", errors="replace")


def _parse_settings(lines, source_name):
    head = lines[0].split("|") if lines else []
    width = _integer(head[4], 1600, 1, MAX_MAP_DIMENSION) if len(head) > 4 else 1600
    height = _integer(head[5], 800, 1, MAX_MAP_DIMENSION) if len(head) > 5 else 800
    world_name = os.path.splitext(os.path.basename(source_name))[0]
    map_year = None
    geo = {"latN": 60.0, "latS": -60.0}
    units = {"distance": {"unit": "km", "scale": 3}}
    biomes = list(DEFAULT_BIOMES)

    s1 = _try_json(lines[1]) if len(lines) > 1 else None
    if isinstance(s1, dict):
        graph = s1.get("graph")
        if isinstance(graph, dict):
            width = _integer(graph.get("width"), width, 1, MAX_MAP_DIMENSION)
            height = _integer(graph.get("height"), height, 1, MAX_MAP_DIMENSION)
        geography = s1.get("geography")
        coords = geography.get("coordinates") if isinstance(geography, dict) else None
        if isinstance(coords, dict):
            geo = coords
        u = s1.get("units")
        if isinstance(u, dict):
            units = u
        lore = s1.get("lore")
        if not isinstance(lore, dict):
            lore = {}
        if lore.get("name"):
            world_name = str(lore["name"])
        calendar = lore.get("calendar")
        if isinstance(calendar, dict) and calendar.get("year") is not None:
            map_year = _optional_int(calendar.get("year"), -100000, 100000)
    elif len(lines) > 1 and "|" in lines[1]:
        parts = lines[1].split("|")
        scale = _num(parts[1] if len(parts) > 1 and parts[1] else 3.0, 3.0, 1e-6, 1000.0)
        units = {"distance": {"unit": parts[0] or "km", "scale": scale}}
        for p in parts:
            if p.strip().startswith("{"):
                opt = _try_json(p)
                if isinstance(opt, dict) and opt.get("name"):
                    world_name = str(opt["name"])
        if len(parts) > 11 and parts[11] and not parts[11].startswith("{"):
            world_name = parts[11]
        if len(lines) > 2:
            s2 = _try_json(lines[2])
            if isinstance(s2, dict) and "latN" in s2:
                geo = s2

    for i in range(1, min(len(lines), 10)):
        obj = _try_json(lines[i])
        found = None
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "habitability" in obj[0]:
            found = obj
        elif isinstance(obj, dict) and "habitability" in obj and "name" in obj:
            habs, names = obj.get("habitability"), obj.get("name")
            if isinstance(habs, (list, tuple)):
                names = names if isinstance(names, (list, tuple)) else []
                found = [{"i": k, "name": str(names[k]) if k < len(names) else f"Biome {k}",
                          "habitability": habs[k]} for k in range(len(habs))]
        if found is not None:
            biomes = found
            break

    norm_biomes = []
    for k, bi in enumerate(biomes if isinstance(biomes, (list, tuple)) else []):
        if not isinstance(bi, dict):
            continue
        norm_biomes.append({
            "i": _integer(bi.get("i"), k, 0, 10000),
            "name": str(bi.get("name", f"Biome {k}")),
            "habitability": _num(bi.get("habitability"), 0.0, 0.0, 100000.0),
        })
    biomes = norm_biomes or list(DEFAULT_BIOMES)
    return head, width, height, _normalize_geo(geo), _normalize_units(units), world_name, map_year, biomes


def _parse_multiline_map(text, source_name):
    lines = [l.rstrip("\r") for l in text.split("\n")]
    head, width, height, geo, units, world_name, map_year, biomes = _parse_settings(lines, source_name)

    # Пошук gridGeneral (початок секцій даних після SVG)
    grid_idx = None
    for i in range(2, len(lines)):
        s = lines[i].lstrip()
        if s.startswith('{"spacing":') or ('"cellsX"' in s[:160] and s.startswith("{")):
            grid_idx = i
            break
    if grid_idx is None:
        raise ValueError("Не знайдено секцію gridGeneral у .map файлі (некоректний або непідтримуваний формат Azgaar).")

    # Пошук features (список з dict {type, cells}), cultures, states, burgs
    features = cultures = states_raw = burgs_raw = None
    burgs_idx = None
    for i in range(grid_idx + 1, min(len(lines), grid_idx + 25)):
        obj = _try_json(lines[i])
        if not isinstance(obj, list):
            continue
        first = next((x for x in obj if isinstance(x, dict) and x), None)
        if not first:
            continue
        if features is None and "cells" in first and "type" in first and "land" in first:
            features = obj
        elif cultures is None and ("shield" in first or "origins" in first or ("name" in first and "base" in first and "i" in first)) and "diplomacy" not in first:
            cultures = obj
        elif states_raw is None and ("diplomacy" in first or first.get("name") == "Neutral" or "expansionism" in first):
            states_raw = obj
        elif burgs_raw is None and ("cell" in first and "x" in first and "y" in first and ("population" in first or "state" in first)):
            burgs_raw = obj
            burgs_idx = i
            break

    if states_raw is None or burgs_raw is None or burgs_idx is None:
        raise ValueError("У файлі карти відсутні обов'язкові секції (states / burgs).")
    features = features or []
    cultures = cultures or [{"i": 0, "name": "Wildlands", "type": "Generic"}]

    # Збираємо клітинкові масиви pack.cells (між burgs_idx і religions JSON)
    rel_idx = None
    cell_raw_lines = []
    for i in range(burgs_idx + 1, min(len(lines), burgs_idx + 30)):
        obj = _try_json(lines[i])
        if isinstance(obj, list):
            rel_idx = i
            break
        cell_raw_lines.append(lines[i])

    def _cell_arr(idx, default_len=0):
        if idx < len(cell_raw_lines) and _is_int_csv(cell_raw_lines[idx]):
            return _arr(cell_raw_lines[idx])
        return [0] * default_len

    c_biome = _cell_arr(0)
    ncells = len(c_biome)
    c_burg = _cell_arr(1, ncells)
    c_culture = _cell_arr(3, ncells)
    c_state = _cell_arr(9, ncells)
    c_rel = _cell_arr(10, ncells)
    c_prov = _cell_arr(11, ncells)

    # Скануємо решту JSON/CSV секцій після pack.cells
    religions = provinces_raw = markers_raw = campaigns_raw = None
    goods_raw = markets_raw = trade_raw = None
    goods_idx = trade_idx = None
    if rel_idx is not None:
        for i in range(rel_idx, len(lines)):
            obj = _try_json(lines[i])
            if not isinstance(obj, list):
                continue
            first = next((x for x in obj if isinstance(x, dict) and x), None)
            if not first:
                continue
            if religions is None and (first.get("name") == "No religion" or "deity" in first or "origins" in first):
                religions = obj
            elif provinces_raw is None and ("formName" in first or ("center" in first and "burg" in first and "state" in first)):
                provinces_raw = obj
            elif markers_raw is None and ("type" in first and "x" in first and "y" in first and "icon" in first):
                markers_raw = obj
            elif campaigns_raw is None and ("cells" in first and "type" in first and "name" in first and "land" not in first):
                campaigns_raw = obj
            elif goods_raw is None and ("demandCoverage" in first or "biomeOutput" in first):
                goods_raw = obj
                goods_idx = i
            elif markets_raw is None and ("centerBurgId" in first and "goods" in first):
                markets_raw = obj
            elif trade_raw is None and ("seller" in first and "buyer" in first and "sellerType" in first):
                trade_raw = obj
                trade_idx = i

    c_goods = []
    c_market = []
    if goods_idx is not None and goods_idx > 0 and _is_int_csv(lines[goods_idx - 1]):
        c_goods = _arr(lines[goods_idx - 1])
    if trade_idx is not None and trade_idx + 1 < len(lines) and _is_int_csv(lines[trade_idx + 1]):
        c_market = _arr(lines[trade_idx + 1])

    return dict(
        head=head, width=width, height=height, geo=geo, units=units,
        world_name=world_name, map_year=map_year, biomes=biomes,
        features=features, cultures=cultures, states_raw=states_raw, burgs_raw=burgs_raw,
        religions=religions or [{"i": 0, "name": "No religion"}],
        provinces_raw=provinces_raw or [0], markers_raw=markers_raw or [], campaigns_raw=campaigns_raw or [],
        c_biome=c_biome, c_burg=c_burg, c_culture=c_culture, c_state=c_state, c_rel=c_rel, c_prov=c_prov,
        goods_raw=goods_raw, markets_raw=markets_raw, trade_raw=trade_raw, c_goods=c_goods, c_market=c_market,
    )


def _parse_fmg_json(data, source_name):
    if not isinstance(data, dict):
        data = {}
    info = data.get("info")
    settings = data.get("settings")
    pack = data.get("pack")
    cells = pack.get("cells") if isinstance(pack, dict) else None
    info = info if isinstance(info, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    pack = pack if isinstance(pack, dict) else {}
    cells = cells if isinstance(cells, dict) else {}
    width = _integer(info.get("width") or settings.get("width"), 1600, 1, MAX_MAP_DIMENSION)
    height = _integer(info.get("height") or settings.get("height"), 800, 1, MAX_MAP_DIMENSION)
    world_name = info.get("mapName") or settings.get("mapName") or os.path.splitext(os.path.basename(source_name))[0]
    coords = data.get("mapCoordinates") or settings.get("mapCoordinates") or {"latN": 60.0, "latS": -60.0}
    dist_scale = _num(settings.get("distanceScale"), 3.0, 1e-6, 1000.0)
    dist_unit = settings.get("distanceUnit") or "km"
    biomes_data = data.get("biomesData")
    if isinstance(biomes_data, dict) and isinstance(biomes_data.get("habitability"), (list, tuple)):
        habs = biomes_data["habitability"]
        names = biomes_data.get("name")
        names = names if isinstance(names, (list, tuple)) else []
        biomes = [{"i": k, "name": str(names[k]) if k < len(names) else f"Biome {k}",
                   "habitability": _num(habs[k], 0.0, 0.0, 100000.0)} for k in range(len(habs))]
    else:
        biomes = list(DEFAULT_BIOMES)

    return dict(
        head=[info.get("version", "json"), "FMG JSON", info.get("exportedAt", ""), str(info.get("seed", "1"))],
        width=width, height=height, geo=_normalize_geo(coords), units=_normalize_units({"distance": {"unit": dist_unit, "scale": dist_scale}}),
        world_name=world_name, map_year=None, biomes=biomes,
        features=pack.get("features") or [], cultures=pack.get("cultures") or [{"i": 0, "name": "Wildlands", "type": "Generic"}],
        states_raw=pack.get("states") or [], burgs_raw=pack.get("burgs") or [{}],
        religions=pack.get("religions") or [{"i": 0, "name": "No religion"}],
        provinces_raw=pack.get("provinces") or [0], markers_raw=pack.get("markers") or [], campaigns_raw=[],
        c_biome=cells.get("biome") or [], c_burg=cells.get("burg") or [], c_culture=cells.get("culture") or [],
        c_state=cells.get("state") or [], c_rel=cells.get("religion") or [], c_prov=cells.get("province") or [],
        goods_raw=pack.get("goods"), markets_raw=pack.get("markets"), trade_raw=pack.get("trade"),
        c_goods=cells.get("goods") or [], c_market=cells.get("market") or [],
    )


def _synthesize_economy(burgs, states, biomes, cultures, c_biome, c_state, width, height, geo, seed_str):
    """Створює ринки, родовища клітинок, ремесла й торгові маршрути для ванільних карт FMG без економіки."""
    goods_raw = _load_default_goods()
    rng = random.Random(str(seed_str))
    habit = {bi["i"]: bi["habitability"] for bi in biomes}
    n_cells = len(c_biome)

    # 1. Точкові родовища на клітинках (c_goods)
    point_goods = [g["i"] for g in goods_raw if g.get("chance", 0) > 0 and not g.get("biomeOutput")]
    weights = [g["chance"] for g in goods_raw if g.get("chance", 0) > 0 and not g.get("biomeOutput")]
    if not point_goods:
        point_goods = [LD.GOOD_IDS[n] for n in (
            "stone", "iron", "copper", "tin", "silver", "gold", "salt", "gemstones", "coal", "clay"
        )]
        weights = [1] * len(point_goods)
    c_goods = [0] * n_cells
    for c in range(n_cells):
        s = c_state[c] if c < len(c_state) else 0
        b = c_biome[c]
        if s and habit.get(b, 0) > 0 and rng.random() < 0.065:
            c_goods[c] = rng.choices(point_goods, weights=weights, k=1)[0]

    # 2. Вибір центрів ринків (усі столиці + великі віддалені міста)
    min_sep = math.hypot(width, height) * 0.075
    centers = []
    chosen = set()
    for st in states.values():
        cap = st.get("capital")
        if cap in burgs and cap not in chosen:
            centers.append(burgs[cap])
            chosen.add(cap)
    for b in sorted(burgs.values(), key=lambda x: -x["pop"]):
        if b["id"] in chosen:
            continue
        if len(centers) >= 65:
            break
        if all(_dist((b["x"], b["y"]), (c["x"], c["y"])) >= min_sep for c in centers):
            if b["pop"] >= 8000 or b["port"] or len(centers) < max(12, len(states)):
                centers.append(b)
                chosen.add(b["id"])
    if not centers and burgs:
        centers = [max(burgs.values(), key=lambda x: x["pop"])]

    markets_raw = []
    for idx, cb in enumerate(centers, 1):
        markets_raw.append({
            "i": idx,
            "centerBurgId": cb["id"],
            "goods": {str(g["i"]): {"stock": 0.0, "price": float(g["value"])} for g in goods_raw},
        })

    # Прив'язуємо міста до найближчого ринку своєї держави або світу
    by_state_mk = collections.defaultdict(list)
    for m in markets_raw:
        cb = burgs[m["centerBurgId"]]
        by_state_mk[cb["state"]].append((m["i"], cb))
    all_mk = [(m["i"], burgs[m["centerBurgId"]]) for m in markets_raw]

    for b in burgs.values():
        pool = by_state_mk.get(b["state"]) or all_mk
        best_mid = min(pool, key=lambda pair: _dist((b["x"], b["y"]), (pair[1]["x"], pair[1]["y"])))[0]
        b["market"] = best_mid

    # Для клітинок c_market визначимо пізніше по state (у import_map pick_burgs вже бере за державою!)
    state_main_mk = {s: pairs[0][0] for s, pairs in by_state_mk.items()}
    c_market = [state_main_mk.get(c_state[c], markets_raw[0]["i"] if markets_raw else 1) for c in range(n_cells)]

    # 3. Базові рецепти ремесел у містах (з goods_default.json)
    crafted = [g for g in goods_raw if g.get("recipes")]
    for b in burgs.values():
        if b["craft"]:
            continue
        k = max(1, min(6, int(1 + math.log10(max(b["pop"], 500) / 300.0) * 2)))
        picks = rng.sample(crafted, min(k, len(crafted)))
        slots = []
        for g in picks:
            if g["i"] in (LD.GOOD_IDS["sails"], LD.GOOD_IDS["ships"]) and not b["port"]:
                continue
            rec = {int(rk): rv for rk, rv in g["recipes"][0].items()}
            units = round(max(1.0, (b["pop"] / 3000.0) * (1.5 if b["capital"] else 1.0)), 2)
            slots.append(dict(good=g["i"], recipe=rec, units=units))
        b["craft"] = slots

    # 4. Торгові зв'язки між сусідніми ринками й портами
    trade_raw = []
    ports = [m for m in markets_raw if burgs[m["centerBurgId"]]["port"]]
    for m in markets_raw:
        cb = burgs[m["centerBurgId"]]
        nbrs = sorted((_dist((cb["x"], cb["y"]), (burgs[o["centerBurgId"]]["x"], burgs[o["centerBurgId"]]["y"])), o["i"])
                      for o in markets_raw if o["i"] != m["i"])[:4]
        for _, oid in nbrs:
            trade_raw.append({"seller": m["i"], "sellerType": "market", "buyer": oid, "buyerType": "market", "units": 20})
        if cb["port"] and len(ports) > 1:
            sea_nbrs = sorted((_dist((cb["x"], cb["y"]), (burgs[o["centerBurgId"]]["x"], burgs[o["centerBurgId"]]["y"])), o["i"])
                              for o in ports if o["i"] != m["i"])[:3]
            for _, oid in sea_nbrs:
                trade_raw.append({"seller": m["i"], "sellerType": "market", "buyer": oid, "buyerType": "market", "units": 30})

    return goods_raw, markets_raw, trade_raw, c_goods, c_market


def import_map(path):
    text = read_map_text(path)
    if text.lstrip().startswith("{"):
        parsed = _parse_fmg_json(json.loads(text), path)
    else:
        parsed = _parse_multiline_map(text, path)

    head = parsed["head"]
    width, height = parsed["width"], parsed["height"]
    geo = parsed["geo"]
    units = parsed["units"]
    biomes = parsed["biomes"]
    features = parsed["features"]
    cultures = parsed["cultures"]
    states_raw = parsed["states_raw"]
    burgs_raw = parsed["burgs_raw"]
    religions = parsed["religions"]
    provinces_raw = parsed["provinces_raw"]
    markers_raw = parsed["markers_raw"]
    campaigns_raw = parsed["campaigns_raw"]
    c_biome, c_burg = parsed["c_biome"], parsed["c_burg"]
    c_culture, c_state = parsed["c_culture"], parsed["c_state"]
    c_rel, c_prov = parsed["c_rel"], parsed["c_prov"]

    feat = {f["i"]: f for f in features if isinstance(f, dict) and f.get("i")}

    # ---------------- держави
    states = {}
    source_states = states_raw if isinstance(states_raw, (list, tuple)) else []
    if len(source_states) > 1:
        source_states = source_states[1:]
    for s in source_states:
        if not isinstance(s, dict) or not s.get("name") or s.get("removed"):
            continue
        sid = _optional_int(s.get("i"), 0, 1000000)
        if sid is None:
            continue
        army = collections.Counter()
        military = s.get("military")
        if not isinstance(military, (list, tuple)):
            military = []
        for r in military:
            if not isinstance(r, dict):
                continue
            units = r.get("u")
            if not isinstance(units, dict):
                continue
            for u, n in units.items():
                army[u] += _num(n, 0.0, 0.0, 1e7)
        if not army:
            pop_hint = max(1.0, _num(s.get("urban"), 0.0, 0.0, 1e9) + _num(s.get("rural"), 0.0, 0.0, 1e9))
            army["infantry"] = max(200, int(pop_hint * 6))
            army["archers"] = max(80, int(pop_hint * 2))
        diplo = {}
        diplomacy = s.get("diplomacy")
        if isinstance(diplomacy, (list, tuple)):
            for j, lab in enumerate(diplomacy):
                if j and j != sid and lab != "x":
                    diplo[j] = lab
        neighbors = s.get("neighbors")
        provinces_raw_states = s.get("provinces")
        campaigns = s.get("campaigns")
        states[sid] = dict(
            id=sid, name=str(s["name"]), full_name=str(s.get("fullName") or s["name"]),
            form=s.get("form", "Monarchy"), capital=_integer(s.get("capital"), 0, 0, 1000000),
            culture=_integer(s.get("culture"), 0, 0, 1000000),
            expansionism=_num(s.get("expansionism"), 1.0, 0.0, 10.0),
            sales_tax=_num(s.get("salesTax"), 0.04, 0.0, 1.0),
            poll_tax=_num(s.get("pollTax"), 0.1, 0.0, 1.0),
            treasury_map=_num(s.get("treasury"), 0.0, -1e12, 1e12),
            color=s.get("color", "#888"),
            neighbors=[n for n in neighbors] if isinstance(neighbors, (list, tuple)) else [],
            urban_k=_num(s.get("urban"), 0.0, 0.0, 1e9), rural_k=_num(s.get("rural"), 0.0, 0.0, 1e9),
            area=_num(s.get("area"), 0.0, 0.0, 1e9), pole=s.get("pole"),
            provinces=[p for p in provinces_raw_states] if isinstance(provinces_raw_states, (list, tuple)) else [],
            army=dict(army), alert=_num(s.get("alert"), 1.0, 0.0, 10.0), diplo_labels=diplo,
            campaigns=[c for c in campaigns] if isinstance(campaigns, (list, tuple)) else [], regiments=len(military),
        )

    # ---------------- міста
    burgs = {}
    if not isinstance(burgs_raw, (list, tuple)):
        burgs_raw = []
    for b in burgs_raw:
        if not isinstance(b, dict) or "name" not in b or b.get("removed"):
            continue
        bid = _optional_int(b.get("i"), 0, 1000000)
        if bid is None:
            continue
        production = b.get("production")
        if not isinstance(production, (list, tuple)):
            production = []
        craft = collections.OrderedDict()
        for p in production:
            if not isinstance(p, dict) or "goodId" not in p or "recipe" not in p:
                continue
            gid = _optional_int(p.get("goodId"), 0, 1000000)
            if gid is None:
                continue
            rec = {}
            recipe_raw = p.get("recipe")
            if isinstance(recipe_raw, (list, tuple)):
                for r in recipe_raw:
                    if not isinstance(r, dict):
                        continue
                    rig = _optional_int(r.get("goodId"), 0, 1000000)
                    if rig is not None:
                        rec[rig] = _num(r.get("units"), 0.0, 0.0, 1e9)
            units = _num(p.get("units"), 0.0, 0.0, 1e9)
            key = (gid, tuple(sorted(rec.items())))
            craft[key] = craft.get(key, 0.0) + units
        pop_val = _num(b.get("population"), 0.5, 0.0, 1e6) * 1000.0
        burgs[bid] = dict(
            id=bid, name=str(b["name"]), state=_integer(b.get("state"), 0, 0, 1000000),
            culture=_integer(b.get("culture"), 0, 0, 1000000),
            x=_num(b.get("x"), 0.0, -1e7, 1e7), y=_num(b.get("y"), 0.0, -1e7, 1e7),
            capital=bool(b.get("capital")), port=bool(b.get("port")),
            pop=max(200.0, pop_val), kind=str(b.get("type", "Generic")), group=str(b.get("group", "towns")),
            market=_optional_int(b.get("market"), 0, 1000000),
            walls=bool(b.get("walls")), temple=bool(b.get("temple")),
            citadel=bool(b.get("citadel")), plaza=bool(b.get("plaza")),
            cell=_integer(b.get("cell"), 0, 0, 10**9),
            feature=b.get("feature"), treasury_map=_num(b.get("treasury"), 0.0, -1e12, 1e12),
            craft=[dict(good=k[0], recipe=dict(k[1]), units=u) for k, u in craft.items()],
            raw={}, rural=0.0,
        )
        raw_slots = collections.Counter()
        for p in production:
            if isinstance(p, dict) and "goodId" in p and "recipe" not in p:
                gid = _optional_int(p.get("goodId"), 0, 1000000)
                if gid is not None:
                    raw_slots[gid] += _num(p.get("units"), 0.0, 0.0, 1e9)
        burgs[bid]["raw_slots"] = dict(raw_slots)

    # Нейтральні міста (state=0) або якщо в карті взагалі немає держав
    for b in burgs.values():
        if b["state"] not in states:
            if b["state"] == 0 and 0 not in states:
                nm = "Skulls" if "Skulls" in b["name"] else b["name"]
                fnm = "The City of Skulls" if "Skulls" in b["name"] else f"Free City of {b['name']}"
                states[0] = dict(
                    id=0, name=nm, full_name=fnm, form="Republic", capital=b["id"], culture=b["culture"],
                    expansionism=0.1, sales_tax=0.05, poll_tax=0.12, treasury_map=200, color="#888888", neighbors=[],
                    urban_k=b["pop"] / 1000.0, rural_k=3.0, area=50, pole=[b["x"], b["y"]], provinces=[],
                    army={"infantry": 300, "archers": 120}, alert=1.5, diplo_labels={}, campaigns=[], regiments=1)
            else:
                b["state"] = 0

    # Гарантія валідної столиці у кожної держави
    by_st_b = collections.defaultdict(list)
    for b in burgs.values():
        by_st_b[b["state"]].append(b)
    for sid, st in list(states.items()):
        if st["capital"] not in burgs:
            if by_st_b.get(sid):
                st["capital"] = max(by_st_b[sid], key=lambda x: x["pop"])["id"]
            else:
                del states[sid]

    # ---------------- економіка (рідна з .map або синтезована для ванільного Azgaar)
    has_native_econ = bool(parsed["goods_raw"] and parsed["markets_raw"] and parsed["c_goods"] and parsed["c_market"])
    if has_native_econ:
        goods_raw = parsed["goods_raw"]
        markets_raw = parsed["markets_raw"]
        trade_raw = parsed["trade_raw"] or []
        c_goods = parsed["c_goods"]
        c_market = parsed["c_market"]
    else:
        goods_raw, markets_raw, trade_raw, c_goods, c_market = _synthesize_economy(
            burgs, states, biomes, cultures, c_biome, c_state, width, height, geo, head[3] if len(head) > 3 else 1
        )

    goods = {}
    if not isinstance(goods_raw, (list, tuple)):
        goods_raw = []
    for g in goods_raw:
        if not isinstance(g, dict):
            continue
        gid = _optional_int(g.get("i"), 0, 1000000)
        if gid is None:
            continue
        cov_in = g.get("demandCoverage")
        cov = {c: _num(cov_in.get(c), 0.0, 0.0, 100.0) for c in LD.CATEGORIES} \
            if isinstance(cov_in, dict) else {c: 0.0 for c in LD.CATEGORIES}
        for cat, v in EXTRA_COVERAGE.get(gid, {}).items():
            cov.setdefault(cat, v)
        recipes = []
        recipes_in = g.get("recipes")
        if isinstance(recipes_in, (list, tuple)):
            for r in recipes_in:
                if not isinstance(r, dict):
                    continue
                nrec = {}
                for k, v in r.items():
                    rig = _optional_int(k, 0, 1000000)
                    q = _num(v, 0.0, 0.0, 1e9)
                    if rig is not None and q > 0:
                        nrec[rig] = q
                if nrec:
                    recipes.append(nrec)
        biome_in = g.get("biomeOutput")
        biome_out = {}
        if isinstance(biome_in, dict):
            for k, v in biome_in.items():
                bk = _optional_int(k, 0, 10000)
                if bk is not None:
                    biome_out[bk] = _num(v, 0.0, 0.0, 1000.0)
        mult_in = g.get("multipliers")
        ct = mult_in.get("cultureType") if isinstance(mult_in, dict) else None
        cult_mult = {str(k): _num(v, 1.0, 0.0, 100.0) for k, v in ct.items()} if isinstance(ct, dict) else {}
        tags = g.get("tags")
        goods[gid] = dict(
            id=gid, name=str(g.get("name", f"Good #{gid}")), value=_num(g.get("value"), 1.0, 1e-9, 1e9),
            tags=[str(t) for t in tags] if isinstance(tags, (list, tuple)) else [],
            unit=str(g.get("unit", "")),
            cover=cov, recipes=recipes, chance=_num(g.get("chance"), 0.0, 0.0, 1e6),
            biome_out=biome_out, cult_mult=cult_mult,
        )

    markets = {}
    if not isinstance(markets_raw, (list, tuple)):
        markets_raw = []
    for m in markets_raw:
        if not isinstance(m, dict):
            continue
        mid = _optional_int(m.get("i"), 0, 1000000)
        center = _optional_int(m.get("centerBurgId"), 0, 1000000)
        if mid is None or center not in burgs:
            continue
        goods_in = m.get("goods")
        if not isinstance(goods_in, dict):
            goods_in = {}
        stock, price = {}, {}
        for k, entry in goods_in.items():
            gid = _optional_int(k, 0, 1000000)
            if gid is None or gid not in goods:
                continue
            entry = entry if isinstance(entry, dict) else {}
            stock[gid] = _num(entry.get("stock"), 0.0, 0.0, 1e12)
            price[gid] = _num(entry.get("price"), goods[gid]["value"], 1e-9, 1e12)
        markets[mid] = dict(
            id=mid, center=center, stock=stock, price=price, burgs=[], edges=[],
        )

    mk_center = {m["id"]: burgs[m["center"]] for m in markets.values()}
    for b in burgs.values():
        if b["market"] not in markets:
            best = min(mk_center.items(), key=lambda kv: _dist((b["x"], b["y"]), (kv[1]["x"], kv[1]["y"])))
            b["market"] = best[0]
        markets[b["market"]]["burgs"].append(b["id"])

    # ---------------- сільське населення та сировина за клітинками
    habit = {bi["i"]: bi["habitability"] for bi in biomes}
    culture_type = {c["i"]: c.get("type", "Generic") for c in cultures
                    if isinstance(c, dict) and "i" in c}
    cells_by_state = collections.defaultdict(list)
    for c in range(len(c_state)):
        s = c_state[c]
        if s and s in states and habit.get(c_biome[c], 0) > 0:
            cells_by_state[s].append(c)

    by_state_market = collections.defaultdict(list)
    for b in burgs.values():
        by_state_market[(b["state"], b["market"])].append(b)
    by_state = collections.defaultdict(list)
    for b in burgs.values():
        by_state[b["state"]].append(b)

    def pick_burgs(s, mk):
        lst = by_state_market.get((s, mk))
        return lst if lst else by_state.get(s, [])

    for s, cells in cells_by_state.items():
        st = states[s]
        total_rural = (st["rural_k"] or max(1.0, len(cells) * 0.2)) * 1000.0
        w_sum = sum(habit[c_biome[c]] for c in cells)
        if not w_sum:
            continue
        for c in cells:
            pop_cell = total_rural * habit[c_biome[c]] / w_sum
            mk_id = c_market[c] if c < len(c_market) else 1
            targets = pick_burgs(s, mk_id)
            if not targets:
                continue
            ws = sum(t["pop"] for t in targets)
            ctype = culture_type.get(c_culture[c] if c < len(c_culture) else 0, "Generic")
            out = collections.Counter()
            pop_k = pop_cell / 1000.0
            bi = c_biome[c]
            for g in goods.values():
                if bi in g["biome_out"]:
                    out[g["id"]] += pop_k * g["biome_out"][bi] * BULK_RATE * g["cult_mult"].get(ctype, 1.0)
            gp = c_goods[c] if c < len(c_goods) else 0
            if gp and gp in goods:
                gg = goods[gp]
                out[gp] += pop_k * POINT_RATE / math.sqrt(max(gg["value"], 1)) * gg["cult_mult"].get(ctype, 1.0)
            for t in targets:
                share = t["pop"] / ws if ws else 1.0 / len(targets)
                t["rural"] += pop_cell * share
                for gid, u in out.items():
                    t["raw"][gid] = t["raw"].get(gid, 0.0) + u * share

    # водні ресурси: риба/кити/перлини — у портах, на річках і озерах
    lat_n = _num(geo.get("latN"), 60.0, -90.0, 90.0)
    lat_s = _num(geo.get("latS"), -60.0, -90.0, 90.0)
    fish_id = LD.GOOD_IDS.get("fish")
    whales_id = LD.GOOD_IDS.get("whales")
    pearls_id = LD.GOOD_IDS.get("pearls")
    for b in burgs.values():
        tot_k = (b["pop"] + b["rural"]) / 1000.0
        lat = lat_n - b["y"] / max(height, 1) * (lat_n - lat_s)
        if b["port"] or b["kind"] in ("Naval",):
            if fish_id in goods:
                b["raw"][fish_id] = b["raw"].get(fish_id, 0.0) + tot_k * 1.8 * (1.4 if b["kind"] == "Naval" else 1.0)
            if abs(lat) > 35 and whales_id in goods:
                b["raw"][whales_id] = b["raw"].get(whales_id, 0.0) + tot_k * 0.5
            if abs(lat) < 25 and pearls_id in goods and (b["id"] * 2654435761) % 100 < 14:
                b["raw"][pearls_id] = b["raw"].get(pearls_id, 0.0) + tot_k * 0.02
        elif b["kind"] in ("River", "Lake") and fish_id in goods:
            b["raw"][fish_id] = b["raw"].get(fish_id, 0.0) + tot_k * 0.8
    # остаточне фільтрування: невідомий goodId не має потрапити у світ
    for b in burgs.values():
        b["raw"] = {g: u for g, u in b["raw"].items() if g in goods}
        b["raw_slots"] = {g: u for g, u in b.get("raw_slots", {}).items() if g in goods}
        filtered_craft = []
        for sl in b.get("craft", []):
            if not isinstance(sl, dict) or sl.get("good") not in goods:
                continue
            sl["recipe"] = {g: q for g, q in (sl.get("recipe") or {}).items() if g in goods}
            filtered_craft.append(sl)
        b["craft"] = filtered_craft
    for b in burgs.values():
        if b["rural"] <= 0:
            b["rural"] = b["pop"] * 2.0

    # ---------------- торгові лінки між ринками
    pair_units = collections.Counter()
    if not isinstance(trade_raw, (list, tuple)):
        trade_raw = []
    for t in trade_raw:
        if not isinstance(t, dict) or t.get("sellerType") != "market" or t.get("buyerType") != "market":
            continue
        a_m = _optional_int(t.get("seller"), 0, 1000000)
        b_m = _optional_int(t.get("buyer"), 0, 1000000)
        if a_m is None or b_m is None or a_m not in markets or b_m not in markets or a_m == b_m:
            continue
        pair_units[tuple(sorted((a_m, b_m)))] += _num(t.get("units"), 10.0, 0.0, 1e9)
    adj = collections.defaultdict(set)
    for a, b in pair_units:
        adj[a].add(b)
        adj[b].add(a)

    def comps():
        seen, out = set(), []
        for m in markets:
            if m in seen:
                continue
            comp, st = set(), [m]
            while st:
                x = st.pop()
                if x in comp:
                    continue
                comp.add(x)
                st.extend(adj[x])
            seen |= comp
            out.append(comp)
        return out

    cs = comps()
    while len(cs) > 1:
        a, rest = cs[0], cs[1:]
        best = None
        for m1 in a:
            for c in rest:
                for m2 in c:
                    d = _dist((mk_center[m1]["x"], mk_center[m1]["y"]), (mk_center[m2]["x"], mk_center[m2]["y"]))
                    if best is None or d < best[0]:
                        best = (d, m1, m2)
        _, m1, m2 = best
        adj[m1].add(m2)
        adj[m2].add(m1)
        pair_units[tuple(sorted((m1, m2)))] += 1
        cs = comps()

    dist_scale = _num(units.get("distance", {}).get("scale"), 3.0, 1e-6, 1000.0)
    edges = []
    for (a, b), u in pair_units.items():
        ca, cb = mk_center[a], mk_center[b]
        d = _dist((ca["x"], ca["y"]), (cb["x"], cb["y"])) * dist_scale
        sea = (ca["feature"] != cb["feature"]) or (ca["port"] and cb["port"] and d > 150)
        edges.append(dict(a=a, b=b, dist=round(d, 1), cap=round(u, 2), sea=bool(sea)))
    for ei, e in enumerate(edges):
        markets[e["a"]]["edges"].append(ei)
        markets[e["b"]]["edges"].append(ei)

    # ---------------- провінції, прив'язка міст, культури, релігії
    provinces = {}
    source_provs = provinces_raw if isinstance(provinces_raw, (list, tuple)) else []
    if len(source_provs) > 1:
        source_provs = source_provs[1:]
    for p in source_provs:
        if not isinstance(p, dict) or not p.get("name") or p.get("removed"):
            continue
        pid = _optional_int(p.get("i"), 0, 1000000)
        psid = _optional_int(p.get("state"), 0, 1000000)
        if pid is None or psid not in states:
            continue
        pole = p.get("pole")
        if isinstance(pole, (list, tuple)) and len(pole) >= 2:
            pole = [_num(pole[0], 0.0, -1e7, 1e7), _num(pole[1], 0.0, -1e7, 1e7)]
        else:
            pole = None
        provinces[pid] = dict(
            id=pid, name=str(p["name"]), full_name=str(p.get("fullName") or p["name"]),
            state=psid, burg=_optional_int(p.get("burg"), 0, 1000000), form=str(p.get("formName", "")),
            color=p.get("color", "#6a8caf"), pole=pole, coa=p.get("coa"),
            burgs=[],
        )

    def _prov_xy(pr):
        if isinstance(pr.get("pole"), (list, tuple)) and len(pr["pole"]) >= 2:
            return pr["pole"][0], pr["pole"][1]
        cb = burgs.get(pr.get("burg"))
        return (cb["x"], cb["y"]) if cb else (0.0, 0.0)

    by_st_provs = collections.defaultdict(list)
    for pr in provinces.values():
        by_st_provs[pr["state"]].append(pr)

    next_pid = (max(provinces) if provinces else 0) + 1
    for sid, bl_st in by_st_b.items():
        if sid not in states:
            continue
        st_provs = by_st_provs.get(sid, [])
        if not st_provs:
            # Автоматичне створення провінцій для мікро-держав або карт без провінцій
            bl_sorted = sorted(bl_st, key=lambda x: (-int(bool(x["capital"])), -x["pop"]))
            if len(bl_sorted) <= 3:
                centers = [bl_sorted[0]]
                forms = ["Capital"]
            else:
                k = max(2, (len(bl_sorted) + 3) // 4)
                centers = bl_sorted[:k]
                forms = ["Capital" if c["id"] == states[sid]["capital"] else "County" for c in centers]
            for c, frm in zip(centers, forms):
                pid = next_pid
                next_pid += 1
                pr = dict(
                    id=pid, name=c["name"], full_name=c["name"], state=sid, burg=c["id"],
                    form=frm, color=states[sid].get("color", "#6a8caf"), pole=[c["x"], c["y"]],
                    coa=None, burgs=[],
                )
                provinces[pid] = pr
                by_st_provs[sid].append(pr)

    for b in burgs.values():
        sid = b["state"]
        cell_i = b.get("cell", -1)
        pid = c_prov[cell_i] if 0 <= cell_i < len(c_prov) else 0
        if pid in provinces and provinces[pid]["state"] == sid:
            chosen = pid
        else:
            st_provs = by_st_provs.get(sid) or list(provinces.values())
            chosen = min(st_provs, key=lambda pr: _dist((b["x"], b["y"]), _prov_xy(pr)))["id"]
        b["province"] = chosen
        provinces[chosen]["burgs"].append(b["id"])

    for pid in [k for k, pr in provinces.items() if not pr["burgs"]]:
        del provinces[pid]
    for pr in provinces.values():
        if pr.get("burg") not in burgs or burgs[pr["burg"]]["province"] != pr["id"]:
            pr["burg"] = max((burgs[bid] for bid in pr["burgs"]), key=lambda x: x["pop"])["id"]
        if not isinstance(pr.get("pole"), (list, tuple)) or len(pr["pole"]) < 2:
            cb = burgs[pr["burg"]]
            pr["pole"] = [cb["x"], cb["y"]]
    culture_out = {c["i"]: dict(id=c["i"], name=c["name"], type=c.get("type", "Generic"),
                                expansionism=c.get("expansionism", 1))
                   for c in cultures if isinstance(c, dict) and "i" in c}
    religions_out = {}
    for i, r in enumerate(religions):
        if isinstance(r, dict):
            religions_out[r.get("i", i)] = dict(id=r.get("i", i), name=r.get("name", "—"), type=r.get("type"),
                                                form=r.get("form"), culture=r.get("culture"), deity=r.get("deity"))
    rel_cnt = collections.defaultdict(collections.Counter)
    for c in range(min(len(c_state), len(c_rel))):
        if c_state[c]:
            rel_cnt[c_state[c]][c_rel[c]] += 1
    for sid, st in states.items():
        st["religion"] = rel_cnt[sid].most_common(1)[0][0] if rel_cnt[sid] else 0

    # ---------------- маркери
    markers = []
    if burgs:
        bvals = list(burgs.values())
        if not isinstance(markers_raw, (list, tuple)):
            markers_raw = []
        for m in markers_raw:
            if not isinstance(m, dict) or "x" not in m or "y" not in m:
                continue
            mx = _num(m["x"], 0.0, -1e7, 1e7)
            my = _num(m["y"], 0.0, -1e7, 1e7)
            near = min(bvals, key=lambda b: _dist((b["x"], b["y"]), (mx, my)))
            cell_i = _integer(m.get("cell"), -1, -1, 10**9)
            sid = c_state[cell_i] if 0 <= cell_i < len(c_state) else 0
            markers.append(dict(i=_optional_int(m.get("i"), 0, 1000000), type=str(m.get("type", "")),
                                name=_clean(str(m.get("name", ""))),
                                note=_clean(str(m.get("note", ""))), x=mx, y=my,
                                state=sid if sid in states else near["state"], burg=near["id"]))

    # ---------------- війни з карти
    wars_map = {}
    for sid, st in states.items():
        for c in st["campaigns"]:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name", "War"))
            start = _integer(c.get("start"), 0, -100000, 100000)
            end = _optional_int(c.get("end"), -100000, 100000)
            attacker = _optional_int(c.get("attacker"), 0, 1000000)
            defender = _optional_int(c.get("defender"), 0, 1000000)
            key = (name, start, attacker, defender)
            wars_map[key] = dict(name=name, start=start, end=end, attacker=attacker, defender=defender)
    history_wars = sorted(wars_map.values(), key=lambda w: w["start"])
    if not isinstance(campaigns_raw, (list, tuple)):
        campaigns_raw = []
    campaigns_zones = [dict(name=str(c.get("name", "")), type=str(c.get("type", "")))
                       for c in campaigns_raw if isinstance(c, dict)]

    # ---------------- ландмаси столиць
    for st in states.values():
        cb = burgs.get(st["capital"])
        st["landmass"] = feat.get(cb["feature"], {}).get("name") if cb else None

    pop_total = sum(b["pop"] + b["rural"] for b in burgs.values())
    return _sanitize_numbers(dict(
        meta=dict(
            map_version=head[0] if head else "unknown",
            map_date=head[2] if len(head) > 2 else "",
            seed=head[3] if len(head) > 3 else "1",
            width=width, height=height, lat_n=lat_n, lat_s=lat_s,
            world_name=_clean(parsed["world_name"]),
            map_year=parsed["map_year"],
            units=units,
            population_total=round(pop_total),
            has_native_economy=has_native_econ,
            source_file=os.path.basename(path),
        ),
        goods=goods, markets=markets, edges=edges, states=states, burgs=burgs, provinces=provinces,
        cultures=culture_out, religions=religions_out, markers=markers,
        history_wars=history_wars, war_zones=campaigns_zones,
    ))


def _write_json_safe(obj, path, *, compact=False):
    """Атомарний JSON-запис: allow_nan=False і очищення tmp при будь-якій помилці."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    kw = dict(ensure_ascii=False, allow_nan=False)
    if compact:
        kw["separators"] = (",", ":")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, **kw)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def save_import(world, path):
    _write_json_safe(world, path)


# ---------------------------------------------------------------------------
# Векторна геометрія для інтерактивної карти (береги, держави, кордони, річки)
# ---------------------------------------------------------------------------
_RE_DEC = re.compile(r"(-?\d+\.\d)\d+")
_RE_PATH = re.compile(r"<path\b([^>]*)/?>")
_RE_ATTR_D = re.compile(r'\bd="([^"]+)"')
_RE_ATTR_ID = re.compile(r'\bid="([^"]+)"')
_RE_ATTR_DF = re.compile(r'\bdata-f="(\d+)"')


def _round_svg_path(d):
    return _RE_DEC.sub(r"\1", d) if d else ""


def _svg_group_content(text, group_id):
    m = re.search(rf'<g\b[^>]*\bid=["\']{re.escape(group_id)}["\'][^>]*>', text)
    if not m:
        return ""
    pos = m.end()
    depth = 1
    tag_re = re.compile(r"<(/?)g\b[^>]*>")
    for tm in tag_re.finditer(text, pos):
        if tm.group(1) == "/":
            depth -= 1
            if depth == 0:
                return text[pos:tm.start()]
        else:
            if not tm.group(0).rstrip().endswith("/>"):
                depth += 1
    end = text.find("</g>", pos)
    return text[pos:end] if end != -1 else ""


def _convex_hull(pts):
    pts = sorted(set((round(float(x), 1), round(float(y), 1)) for x, y in pts))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _hull_path_from_burgs(pts, pad=22.0):
    if not pts:
        return ""
    if len(pts) == 1:
        cx, cy = pts[0]
        ring = [(round(cx + pad * math.cos(k * math.pi / 4), 1),
                 round(cy + pad * math.sin(k * math.pi / 4), 1)) for k in range(8)]
    elif len(pts) == 2:
        (x1, y1), (x2, y2) = pts
        dx, dy = x2 - x1, y2 - y1
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln * pad, dx / ln * pad
        ux, uy = dx / ln * pad * 0.7, dy / ln * pad * 0.7
        ring = [
            (round(x1 - ux + nx, 1), round(y1 - uy + ny, 1)),
            (round(x2 + ux + nx, 1), round(y2 + uy + ny, 1)),
            (round(x2 + ux - nx, 1), round(y2 + uy - ny, 1)),
            (round(x1 - ux - nx, 1), round(y1 - uy - ny, 1)),
        ]
    else:
        hull = _convex_hull(pts)
        cx = sum(p[0] for p in hull) / len(hull)
        cy = sum(p[1] for p in hull) / len(hull)
        ring = []
        for x, y in hull:
            dx, dy = x - cx, y - cy
            ln = math.hypot(dx, dy) or 1.0
            ring.append((round(x + dx / ln * pad, 1), round(y + dy / ln * pad, 1)))
    return "M" + " L".join(f"{x},{y}" for x, y in ring) + " Z"


def _extract_feat_types(text):
    for line in text.split("\n"):
        obj = _try_json(line)
        if isinstance(obj, list):
            first = next((x for x in obj if isinstance(x, dict) and x), None)
            if first and "cells" in first and "type" in first and "land" in first:
                return {f["i"]: f for f in obj if isinstance(f, dict) and f.get("i")}
    return {}


def extract_map_geometry(text_or_path, world):
    """Витягує векторні SVG-контури (суша, озера, держави, кордони, річки) або будує фолбек по містах."""
    if os.path.exists(text_or_path):
        text = read_map_text(text_or_path)
    else:
        text = text_or_path or ""

    meta = world.get("meta", {})
    width = int(meta.get("width", 1600))
    height = int(meta.get("height", 800))

    land, lakes, borders, prov_borders, rivers = [], [], [], [], []
    states_paths = {}

    if "<svg" in text and not text.lstrip().startswith("{"):
        feat = _extract_feat_types(text)
        # fallback за <mask id="land"> якщо features JSON не знайдено
        land_mask_ids = set()
        if not feat:
            mask_m = _svg_group_content(text, "defs") or text
            lm = re.search(r'<mask\b[^>]*\bid=["\']land["\'][^>]*>(.*?)</mask>', mask_m, re.S)
            if lm:
                land_mask_ids = {int(x) for x in re.findall(r'feature_(\d+)', lm.group(1))}

        fp = _svg_group_content(text, "featurePaths")
        if fp:
            for m in _RE_PATH.finditer(fp):
                attrs = m.group(1)
                dm = _RE_ATTR_D.search(attrs)
                if not dm:
                    continue
                d = _round_svg_path(dm.group(1))
                idm = _RE_ATTR_ID.search(attrs)
                dfm = _RE_ATTR_DF.search(attrs)
                fid = None
                if idm and idm.group(1).startswith("feature_"):
                    fid = int(idm.group(1).split("_", 1)[1])
                elif dfm:
                    fid = int(dfm.group(1))
                if fid is not None and feat:
                    info = feat.get(fid, {})
                    if info.get("land"):
                        land.append(d)
                    elif info.get("type") == "lake":
                        lakes.append(d)
                elif fid is not None and fid in land_mask_ids:
                    land.append(d)

        sb = _svg_group_content(text, "statesBody")
        if sb:
            for m in _RE_PATH.finditer(sb):
                attrs = m.group(1)
                idm = _RE_ATTR_ID.search(attrs)
                if not idm:
                    continue
                pid = idm.group(1)
                if not pid.startswith("state") or pid.startswith("state-gap"):
                    continue
                sid_str = pid[5:]
                if not sid_str.isdigit():
                    continue
                dm = _RE_ATTR_D.search(attrs)
                if dm:
                    d = _round_svg_path(dm.group(1))
                    if sid_str in states_paths:
                        states_paths[sid_str] += " " + d
                    else:
                        states_paths[sid_str] = d

        br = _svg_group_content(text, "stateBorders")
        if br:
            for m in _RE_PATH.finditer(br):
                dm = _RE_ATTR_D.search(m.group(1))
                if dm:
                    borders.append(_round_svg_path(dm.group(1)))

        pbr = _svg_group_content(text, "provinceBorders")
        if pbr:
            for m in _RE_PATH.finditer(pbr):
                dm = _RE_ATTR_D.search(m.group(1))
                if dm:
                    prov_borders.append(_round_svg_path(dm.group(1)))

        rv = _svg_group_content(text, "rivers")
        if rv:
            for m in _RE_PATH.finditer(rv):
                dm = _RE_ATTR_D.search(m.group(1))
                if dm:
                    rivers.append(_round_svg_path(dm.group(1)))

    # Фолбек для карт без SVG (JSON-експорт або синтетичні тести)
    if not states_paths:
        by_state = collections.defaultdict(list)
        all_pts = []
        for b in world.get("burgs", {}).values():
            pt = (b["x"], b["y"])
            by_state[b["state"]].append(pt)
            all_pts.append(pt)
        for sid, pts in by_state.items():
            p = _hull_path_from_burgs(pts, pad=22.0)
            if p:
                states_paths[str(sid)] = p
        if not land and all_pts:
            p_land = _hull_path_from_burgs(all_pts, pad=36.0)
            if p_land:
                land.append(p_land)

    return dict(
        width=width, height=height,
        land=land, lakes=lakes, states=states_paths, borders=borders, prov_borders=prov_borders, rivers=rivers,
        has_svg=bool(land or states_paths),
    )


def save_map_geo(geo, path):
    _write_json_safe(geo, path, compact=True)


def load_map_geo(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
