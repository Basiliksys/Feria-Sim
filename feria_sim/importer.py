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
import json
import math
import os
import random
import re

BULK_RATE = 100.0   # од. сировини на 1000 селян/міс при biomeOutput = 1
POINT_RATE = 18.0   # од. на 1000 селян/міс для «точкових» ресурсів клітинки

# Попит, якого може не бути у .map (злитки, ремесло, гроші) — інакше їх ціна «провалюється».
EXTRA_COVERAGE = {
    4: {"military": 0.15}, 5: {"utilities": 0.15}, 6: {"utilities": 0.15},
    7: {"luxury": 0.4}, 8: {"luxury": 0.5}, 21: {"utilities": 0.3}, 23: {"luxury": 0.5},
    24: {"luxury": 0.5}, 28: {"utilities": 0.3}, 33: {"military": 0.3},
    49: {"luxury": 0.3}, 50: {"luxury": 0.2}, 57: {"military": 0.25},
    52: {"military": 0.5}, 62: {"luxury": 0.5}, 63: {"luxury": 1.0}, 32: {"utilities": 0.4},
    43: {"utilities": 0.3}, 48: {"utilities": 0.5}, 31: {"utilities": 1.0}, 36: {"luxury": 1.0},
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
    return [int(float(x)) for x in line.rstrip(",").split(",") if x.strip() != ""]


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
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def _parse_settings(lines, source_name):
    head = lines[0].split("|")
    width = int(float(head[4])) if len(head) > 4 and head[4].replace(".", "", 1).isdigit() else 1600
    height = int(float(head[5])) if len(head) > 5 and head[5].replace(".", "", 1).isdigit() else 800
    world_name = os.path.splitext(os.path.basename(source_name))[0]
    map_year = None
    geo = {"latN": 60.0, "latS": -60.0}
    units = {"distance": {"unit": "km", "scale": 3}}
    biomes = list(DEFAULT_BIOMES)

    s1 = _try_json(lines[1]) if len(lines) > 1 else None
    if isinstance(s1, dict):
        width = int(s1.get("graph", {}).get("width") or width)
        height = int(s1.get("graph", {}).get("height") or height)
        geo = s1.get("geography", {}).get("coordinates") or geo
        units = s1.get("units") or units
        lore = s1.get("lore") or {}
        if lore.get("name"):
            world_name = lore["name"]
        map_year = (lore.get("calendar") or {}).get("year")
    elif len(lines) > 1 and "|" in lines[1]:
        parts = lines[1].split("|")
        try:
            scale = float(parts[1]) if len(parts) > 1 and parts[1] else 3.0
        except Exception:
            scale = 3.0
        units = {"distance": {"unit": parts[0] or "km", "scale": scale}}
        for p in parts:
            if p.strip().startswith("{"):
                opt = _try_json(p)
                if isinstance(opt, dict) and opt.get("name"):
                    world_name = opt["name"]
        if len(parts) > 11 and parts[11] and not parts[11].startswith("{"):
            world_name = parts[11]
        if len(lines) > 2:
            s2 = _try_json(lines[2])
            if isinstance(s2, dict) and "latN" in s2:
                geo = s2

    for i in range(1, min(len(lines), 10)):
        obj = _try_json(lines[i])
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "habitability" in obj[0]:
            biomes = obj
            break
        if isinstance(obj, dict) and "habitability" in obj and "name" in obj:
            habs = obj.get("habitability", [])
            names = obj.get("name", [])
            biomes = [{"i": k, "name": names[k] if k < len(names) else f"Biome {k}",
                       "habitability": habs[k]} for k in range(len(habs))]
            break

    return head, width, height, geo, units, world_name, map_year, biomes


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
    info = data.get("info") or {}
    settings = data.get("settings") or {}
    pack = data.get("pack") or {}
    cells = pack.get("cells") or {}
    width = int(info.get("width") or settings.get("width") or 1600)
    height = int(info.get("height") or settings.get("height") or 800)
    world_name = info.get("mapName") or settings.get("mapName") or os.path.splitext(os.path.basename(source_name))[0]
    coords = data.get("mapCoordinates") or settings.get("mapCoordinates") or {"latN": 60.0, "latS": -60.0}
    dist_scale = float(settings.get("distanceScale") or 3.0)
    dist_unit = settings.get("distanceUnit") or "km"
    biomes_data = data.get("biomesData") or {}
    if isinstance(biomes_data, dict) and "habitability" in biomes_data:
        habs = biomes_data["habitability"]
        names = biomes_data.get("name", [])
        biomes = [{"i": k, "name": names[k] if k < len(names) else f"Biome {k}", "habitability": habs[k]}
                  for k in range(len(habs))]
    else:
        biomes = list(DEFAULT_BIOMES)

    return dict(
        head=[info.get("version", "json"), "FMG JSON", info.get("exportedAt", ""), str(info.get("seed", "1"))],
        width=width, height=height, geo=coords, units={"distance": {"unit": dist_unit, "scale": dist_scale}},
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
        point_goods = [2, 4, 5, 6, 7, 8, 16, 23, 34, 41]
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
            if g["i"] in (52, 53) and not b["port"]:
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
    for s in states_raw[1:] if len(states_raw) > 1 else states_raw:
        if not isinstance(s, dict) or not s.get("name") or s.get("removed"):
            continue
        army = collections.Counter()
        for r in s.get("military", []):
            for u, n in (r.get("u") or {}).items():
                army[u] += n
        if not army:
            pop_hint = max(1.0, (s.get("urban", 0) or 0) + (s.get("rural", 0) or 0))
            army["infantry"] = max(200, int(pop_hint * 6))
            army["archers"] = max(80, int(pop_hint * 2))
        diplo = {}
        for j, lab in enumerate(s.get("diplomacy", [])):
            if j and j != s["i"] and lab != "x":
                diplo[j] = lab
        states[s["i"]] = dict(
            id=s["i"], name=s["name"], full_name=s.get("fullName", s["name"]),
            form=s.get("form", "Monarchy"), capital=s.get("capital", 0), culture=s.get("culture", 0),
            expansionism=s.get("expansionism", 1), sales_tax=s.get("salesTax", 0.04),
            poll_tax=s.get("pollTax", 0.1), treasury_map=s.get("treasury", 0), color=s.get("color", "#888"),
            neighbors=[n for n in s.get("neighbors", [])], urban_k=s.get("urban", 0), rural_k=s.get("rural", 0),
            area=s.get("area", 0), pole=s.get("pole"), provinces=s.get("provinces", []),
            army=dict(army), alert=s.get("alert", 1), diplo_labels=diplo,
            campaigns=s.get("campaigns", []), regiments=len(s.get("military", [])),
        )

    # ---------------- міста
    burgs = {}
    for b in burgs_raw:
        if not isinstance(b, dict) or "name" not in b or b.get("removed"):
            continue
        craft = collections.OrderedDict()
        for p in b.get("production", []):
            if "goodId" not in p or "recipe" not in p:
                continue
            rec = {r["goodId"]: r["units"] for r in p["recipe"]}
            key = (p["goodId"], tuple(sorted(rec.items())))
            craft[key] = craft.get(key, 0) + p["units"]
        pop_val = float(b.get("population") or 0.5) * 1000.0
        burgs[b["i"]] = dict(
            id=b["i"], name=b["name"], state=b.get("state", 0), culture=b.get("culture", 0),
            x=b["x"], y=b["y"], capital=bool(b.get("capital")), port=bool(b.get("port")),
            pop=max(200.0, pop_val), kind=b.get("type", "Generic"), group=b.get("group", "towns"),
            market=b.get("market"), walls=bool(b.get("walls")), temple=bool(b.get("temple")),
            citadel=bool(b.get("citadel")), plaza=bool(b.get("plaza")), cell=b.get("cell", 0),
            feature=b.get("feature"), treasury_map=b.get("treasury", 0),
            craft=[dict(good=k[0], recipe=dict(k[1]), units=u) for k, u in craft.items()],
            raw={}, rural=0.0,
        )
        raw_slots = collections.Counter()
        for p in b.get("production", []):
            if "goodId" in p and "recipe" not in p:
                raw_slots[p["goodId"]] += p["units"]
        burgs[b["i"]]["raw_slots"] = dict(raw_slots)

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
    for g in goods_raw:
        cov = dict(g.get("demandCoverage") or {})
        for cat, v in EXTRA_COVERAGE.get(g["i"], {}).items():
            cov.setdefault(cat, v)
        recipes = []
        for r in g.get("recipes") or []:
            recipes.append({int(k): v for k, v in r.items()})
        goods[g["i"]] = dict(
            id=g["i"], name=g["name"], value=g["value"], tags=g.get("tags", []), unit=g.get("unit", ""),
            cover=cov, recipes=recipes, chance=g.get("chance", 0),
            biome_out={int(k): v for k, v in (g.get("biomeOutput") or {}).items()},
            cult_mult=(g.get("multipliers") or {}).get("cultureType", {}),
        )

    markets = {}
    for m in markets_raw:
        if m["centerBurgId"] not in burgs:
            continue
        markets[m["i"]] = dict(
            id=m["i"], center=m["centerBurgId"],
            stock={int(k): v["stock"] for k, v in m["goods"].items()},
            price={int(k): v["price"] for k, v in m["goods"].items()},
            burgs=[], edges=[],
        )

    mk_center = {m["id"]: burgs[m["center"]] for m in markets.values()}
    for b in burgs.values():
        if b["market"] not in markets:
            best = min(mk_center.items(), key=lambda kv: _dist((b["x"], b["y"]), (kv[1]["x"], kv[1]["y"])))
            b["market"] = best[0]
        markets[b["market"]]["burgs"].append(b["id"])

    # ---------------- сільське населення та сировина за клітинками
    habit = {bi["i"]: bi["habitability"] for bi in biomes}
    culture_type = {c["i"]: c.get("type", "Generic") for c in cultures if isinstance(c, dict)}
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
    lat_n, lat_s = float(geo.get("latN", 60.0)), float(geo.get("latS", -60.0))
    for b in burgs.values():
        tot_k = (b["pop"] + b["rural"]) / 1000.0
        lat = lat_n - b["y"] / max(height, 1) * (lat_n - lat_s)
        if b["port"] or b["kind"] in ("Naval",):
            b["raw"][11] = b["raw"].get(11, 0.0) + tot_k * 1.8 * (1.4 if b["kind"] == "Naval" else 1.0)
            if abs(lat) > 35:
                b["raw"][37] = b["raw"].get(37, 0.0) + tot_k * 0.5
            if abs(lat) < 25 and (b["id"] * 2654435761) % 100 < 14:
                b["raw"][22] = b["raw"].get(22, 0.0) + tot_k * 0.02
        elif b["kind"] in ("River", "Lake"):
            b["raw"][11] = b["raw"].get(11, 0.0) + tot_k * 0.8
    for b in burgs.values():
        if b["rural"] <= 0:
            b["rural"] = b["pop"] * 2.0

    # ---------------- торгові лінки між ринками
    pair_units = collections.Counter()
    for t in trade_raw:
        if t.get("sellerType") == "market" and t.get("buyerType") == "market":
            a_m, b_m = t["seller"], t["buyer"]
            if a_m in markets and b_m in markets and a_m != b_m:
                pair_units[tuple(sorted((a_m, b_m)))] += t.get("units", 10)
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

    dist_scale = float(units.get("distance", {}).get("scale", 3.0) or 3.0)
    edges = []
    for (a, b), u in pair_units.items():
        ca, cb = mk_center[a], mk_center[b]
        d = _dist((ca["x"], ca["y"]), (cb["x"], cb["y"])) * dist_scale
        sea = (ca["feature"] != cb["feature"]) or (ca["port"] and cb["port"] and d > 150)
        edges.append(dict(a=a, b=b, dist=round(d, 1), cap=round(u, 2), sea=bool(sea)))
    for ei, e in enumerate(edges):
        markets[e["a"]]["edges"].append(ei)
        markets[e["b"]]["edges"].append(ei)

    # ---------------- провінції, культури, релігії
    provinces = {p["i"]: dict(id=p["i"], name=p["name"], state=p["state"], burg=p.get("burg"),
                              form=p.get("formName", "")) for p in provinces_raw[1:]
                 if isinstance(p, dict) and p.get("name")}
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
        for m in markers_raw:
            if not isinstance(m, dict) or "x" not in m or "y" not in m:
                continue
            near = min(bvals, key=lambda b: _dist((b["x"], b["y"]), (m["x"], m["y"])))
            cell_i = m.get("cell", -1)
            sid = c_state[cell_i] if 0 <= cell_i < len(c_state) else 0
            markers.append(dict(i=m.get("i"), type=m.get("type", ""), name=_clean(m.get("name", "")),
                                note=_clean(m.get("note", "")), x=m["x"], y=m["y"],
                                state=sid if sid in states else near["state"], burg=near["id"]))

    # ---------------- війни з карти
    wars_map = {}
    for sid, st in states.items():
        for c in st["campaigns"]:
            key = (c.get("name", "War"), c.get("start", 0), c.get("attacker"), c.get("defender"))
            wars_map[key] = dict(name=c.get("name", "War"), start=c.get("start", 0), end=c.get("end"),
                                 attacker=c.get("attacker"), defender=c.get("defender"))
    history_wars = sorted(wars_map.values(), key=lambda w: w["start"])
    campaigns_zones = [dict(name=c.get("name", ""), type=c.get("type", "")) for c in campaigns_raw if isinstance(c, dict)]

    # ---------------- ландмаси столиць
    for st in states.values():
        cb = burgs.get(st["capital"])
        st["landmass"] = feat.get(cb["feature"], {}).get("name") if cb else None

    pop_total = sum(b["pop"] + b["rural"] for b in burgs.values())
    return dict(
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
    )


def save_import(world, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(world, f, ensure_ascii=False)


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

    land, lakes, borders, rivers = [], [], [], []
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
        land=land, lakes=lakes, states=states_paths, borders=borders, rivers=rivers,
        has_svg=bool(land or states_paths),
    )


def save_map_geo(geo, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def load_map_geo(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
