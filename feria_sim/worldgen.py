# -*- coding: utf-8 -*-
"""Допис світу: перетворює сирий імпорт .map на повний ігровий `world`.

Додає те, чого немає на карті: українські назви, правителів і риси, відносини
між державами, війни, гільдії, найманців, калібрування економіки та казни.
"""
import copy
import json
import math
import os
import random
import re

from . import geography as GT, lore_data as LD
from . import engine as E

# Канонічні значення конфігурації живуть в engine.CONFIG_DEFAULTS, щоб Sim міг
# підставляти їх для старих збережень; тут доступний той самий контракт.
CONFIG_DEFAULTS = E.CONFIG_DEFAULTS


def _finite(value, default=None, lo=None, hi=None):
    """Скінченне число з фолбеком (для content pack та інших недовірених даних)."""
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

PREFIX_UK = [
    ("Grand Duchy", "Велике герцогство"), ("Duchy", "Герцогство"), ("Kingdom", "Королівство"),
    ("Principality", "Князівство"), ("Republic", "Республіка"), ("Empire", "Імперія"),
    ("Theocracy", "Теократія"), ("Diocese", "Єпархія"), ("Protectorate", "Протекторат"),
    ("Dominion", "Домініон"), ("Heptarchy", "Гептархія"), ("Marches", "Марка"),
    ("Church", "Церква"), ("Cult", "Культ"), ("Union", "Союз"), ("Canton", "Кантон"),
]
RULER_TITLE = {
    "Королівство": "Король", "Герцогство": "Герцог", "Велике герцогство": "Великий герцог",
    "Князівство": "Князь", "Республіка": "Голова Ради", "Імперія": "Імператор", "Теократія": "Верховний ієрарх",
    "Єпархія": "Єпископ", "Протекторат": "Протектор", "Домініон": "Лорд-володар", "Гептархія": "Голова Гептархії",
    "Марка": "Маркграф", "Церква": "Прелат", "Культ": "Верховний жрець", "Союз": "Голова Союзу",
}


def _prefix(full_name):
    for en, uk in PREFIX_UK:
        if en in full_name:
            return uk
    return "Держава"


def _gids(*names):
    """Стабільні ID товарів за назвою; невідомі назви тихо пропускаємо."""
    table = getattr(LD, "GOOD_IDS", {})
    out = []
    for name in names:
        gid = table.get(name)
        if gid is not None and gid not in out:
            out.append(gid)
    return out


def _generate_generic_orgs(w, rng):
    """Генерує гільдії, найманців і ордени для довільної карти з Azgaar."""
    burgs = sorted(w["burgs"].values(), key=lambda b: -b["pop"])
    states = sorted(w["states"].values(), key=lambda s: -(s["urban_k"] + s["rural_k"]))
    templates = [
        ("g_iron", "Гільдія гірників і ковалів", "craft",
         _gids("iron", "coal", "tools", "arms"), "Видобуток заліза, вугілля та кузня."),
        ("g_grain", "Торговий союз землеробів", "food",
         _gids("grain", "cattle", "cheese", "beer"), "Постачання зерна, худоби та харчів."),
        ("g_sea", "Ліга морських купців", "maritime",
         _gids("sails", "ships", "rope", "spices"), "Морська торгівля, верфі та прянощі.", True),
        ("g_cloth", "Цех ткачів і кравців", "craft",
         _gids("leather", "cloth", "garments", "boots"), "Виробництво сукна, одягу та взуття."),
        ("g_bank", "Міняйли та ювеліри", "finance",
         _gids("silver", "gold", "coins", "jewelry"), "Карбування монет і банківські векселі."),
        ("g_alch", "Колегія алхіміків і книгарів", "arcane",
         _gids("saltpeter", "paper", "ink", "books", "gunpowder"), "Книги, чорнила, скло та селітра."),
    ]
    guilds = []
    ports = [b for b in burgs if b["port"]]
    used = set()
    for tpl in templates:
        need_port = len(tpl) > 5 and tpl[5]
        pool = ports if need_port and ports else burgs
        hb = next((b for b in pool if b["id"] not in used), pool[0] if pool else None)
        if not hb:
            continue
        used.add(hb["id"])
        guilds.append(dict(
            id=tpl[0], name=f"{tpl[1]} ({hb['uk']})", kind=tpl[2], burg=hb["id"], market=hb["market"],
            state=hb["state"], goods=[g for g in tpl[3] if g in w["goods"]],
            wealth=round(max(2000.0, hb["pop"] * 0.4), 1),
            power=0.5, note=tpl[4], rep={},
        ))
    mercs = []
    merc_names = ["Вільний загін «Залізні списи»", "Сотня Блукаючого Меча", "Чорні Арбалетники", "Золота Компанія"]
    for i, st in enumerate(states[:4]):
        mercs.append(dict(
            id=f"merc_{i}", name=merc_names[i % len(merc_names)] + f" ({st['uk']})",
            size=rng.randint(1200, 2800), fee=round(rng.uniform(1.5, 2.2), 1),
            unit="cavalry" if i % 2 else "infantry", home=st["id"], employer=None, contract_end=None, cash=0.0,
        ))
    orders = []
    theo = [s for s in states if s["form"] in ("Theocracy", "Diocese", "Church")] or states[:2]
    for i, st in enumerate(theo[:3]):
        orders.append(dict(
            id=f"ord_{i}", name=f"Орден Вартових ({st['uk']})", state=st["id"],
            strength=rng.randint(500, 950), unit="cavalry",
        ))
    return guilds, mercs, orders


def _resolve_overrides(overrides, world_name, is_feria):
    if not overrides:
        return {}, {}, {}
    worlds = overrides.get("worlds")
    if isinstance(worlds, dict):
        if world_name in worlds:
            src = worlds[world_name] or {}
            return src.get("states", {}), src.get("burgs", {}), src.get("provinces", {})
        if not is_feria:
            return {}, {}, {}
    if not is_feria and overrides.get("world_name") not in (None, world_name):
        return {}, {}, {}
    if not is_feria and overrides and "world_name" not in overrides and "worlds" in overrides:
        return {}, {}, {}
    return overrides.get("states", {}), overrides.get("burgs", {}), overrides.get("provinces", {})


CONTENT_PACK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "content_pack.json"
)
SPECIAL_GOODS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "special_goods.json"
)

# Дозволені ключі config з діапазонами (невідомі ключі ігноруються).
_CONTENT_CONFIG_RANGES = {
    "price_elasticity": (0.0, 2.0),
    "carry_cap": (1.01, 10.0),
    "tech_cap": (1.0, 20.0),
    "tech_decay": (0.0, 1.0),
    "max_events_per_month": (0, 100),
    "neighbor_drift": (-1.0, 1.0),
    "army_recovery_rate": (0.0, 1.0),
    "trade_budget_factor": (0.0, 100.0),
    "guild_invest_rate": (0.0, 1.0),
    "mil_k": (0.0, 100.0),
    "mil_goods_per_head": (0.0, 1.0),
    "event_rate": (0.0, 100.0),
    "war_rate": (0.0, 100.0),
    "craft_scale": (0.0, 100.0),
    "transport_rate": (0.0, 10.0),
    "caravan_share": (0.0, 1.0),
    "caravan_max_active": (0, 256),
    "caravan_hub_count": (2, 12),
    "specialty_rate": (0.0, 2.0),
    "birth": (0.0, 1.0),
    "death": (0.0, 1.0),
    "poll_k": (0.0, 1000.0),
    "admin_share": (0.0, 1.0),
}
_CONTENT_CONFIG_BOOLS = frozenset((
    "event_scale_by_size", "demand_elasticity_enabled", "dynamic_recipes", "capital_constraint",
    "caravan_enabled", "geography_enabled", "special_goods_enabled",
))
_CONTENT_GOOD_KEYS = frozenset((
    "value", "cover", "recipes", "name", "unit", "tags", "chance", "biomeOutput", "multipliers",
))


def _coerce_pack_config(key, val, current):
    """Повертає валідне значення для відомого ключа або поточне (фолбек)."""
    if key in _CONTENT_CONFIG_BOOLS:
        if isinstance(val, bool):
            return val
        if isinstance(val, str) and val.lower() in ("true", "false"):
            return val.lower() == "true"
        return current
    if key == "per_capita":
        if not isinstance(val, dict) or not isinstance(current, dict):
            return current
        pc = dict(current)
        for cat in ("food", "utilities", "construction", "luxury"):
            if cat in val:
                v = _finite(val[cat], None, 0.0, 1e6)
                if v is not None:
                    pc[cat] = v
        return pc
    if key not in _CONTENT_CONFIG_RANGES:
        return current
    v = _finite(val, None)
    if v is None:
        return current
    lo, hi = _CONTENT_CONFIG_RANGES[key]
    v = min(hi, max(lo, v))
    return int(v) if key == "max_events_per_month" else v


def _load_content_pack():
    """Необов'язковий content pack: читає <repo>/data/content_pack.json, якщо він є.

    Файл може містити ``config`` (перевизначення ключів world.config), ``goods``
    (за ID товару) та ``event_weights`` (ваги подій за ключем). Усе інше ігнорується.
    """
    if not os.path.isfile(CONTENT_PACK_PATH):
        return {}
    try:
        with open(CONTENT_PACK_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _apply_content_pack(w):
    """Застосовує content pack до світу; викликається до ініціалізації ринків.

    Контракт навмисно вузький: лише відомі ключі config, ваги подій із EVENT_TABLE
    та перевизначення вже існуючих товарів із перевіреними полями.
    """
    pack = _load_content_pack()
    if not isinstance(pack, dict):
        return
    cfg = w.setdefault("config", {})
    over = pack.get("config")
    if isinstance(over, dict):
        for key, val in over.items():
            current = cfg.get(key, CONFIG_DEFAULTS.get(key))
            cfg[key] = _coerce_pack_config(key, val, current)
    # Ваги подій: базові з EVENT_TABLE + перевизначення з паку (events.py читає cfg["event_weights"]).
    weights = {}
    for key, spec in LD.EVENT_TABLE.items():
        base = spec.get("weight", 1.0) if isinstance(spec, dict) else 1.0
        weights[key] = _finite(base, 1.0, 0.0, 1e6)
    ew = pack.get("event_weights")
    if isinstance(ew, dict):
        for key, val in ew.items():
            if key not in LD.EVENT_TABLE:
                continue
            v = _finite(val, None, 0.0, 1e6)
            if v is not None:
                weights[key] = v
    cfg["event_weights"] = weights
    # Перевизначення товарів за ID (тільки для вже існуючих товарів).
    goods = w.get("goods")
    goods_over = pack.get("goods")
    if not isinstance(goods, dict) or not isinstance(goods_over, dict):
        return
    for key, vals in goods_over.items():
        if not isinstance(key, str) or not key.isdigit():
            continue
        gid = int(key)
        if str(gid) != key or gid <= 0:
            continue
        gd = goods.get(gid)
        if not isinstance(gd, dict) or not isinstance(vals, dict):
            continue
        upd = {}
        for field in _CONTENT_GOOD_KEYS:
            if field not in vals:
                continue
            val = vals[field]
            if field == "value":
                v = _finite(val, None, 1e-9, 1e9)
                if v is not None:
                    upd["value"] = v
            elif field == "cover":
                if isinstance(val, dict):
                    cov = {}
                    for cat, amount in val.items():
                        if cat in LD.CATEGORIES:
                            v = _finite(amount, None, 0.0, 100.0)
                            if v is not None:
                                cov[cat] = v
                    upd["cover"] = cov
            elif field == "recipes":
                if isinstance(val, (list, tuple)):
                    norm = []
                    for rec in val:
                        if not isinstance(rec, dict):
                            continue
                        nrec = {}
                        for iid, qty in rec.items():
                            try:
                                iid_i = int(iid)
                            except (TypeError, ValueError):
                                continue
                            if str(iid_i) != str(iid) or iid_i not in goods:
                                continue
                            q = _finite(qty, None, 1e-9, 1e9)
                            if q is not None:
                                nrec[iid_i] = q
                        if nrec:
                            norm.append(nrec)
                    upd["recipes"] = norm
            elif field in ("name", "unit"):
                if isinstance(val, str):
                    upd[field] = val
            elif field == "tags":
                if isinstance(val, (list, tuple)):
                    upd["tags"] = [str(t) for t in val]
            elif field == "chance":
                v = _finite(val, None, 0.0, 1e6)
                if v is not None:
                    upd["chance"] = v
            elif field == "biomeOutput":
                if isinstance(val, dict):
                    bio = {}
                    for bk, bv in val.items():
                        try:
                            bk_i = int(bk)
                        except (TypeError, ValueError):
                            continue
                        q = _finite(bv, None, 0.0, 1000.0)
                        if str(bk_i) == str(bk) and q is not None:
                            bio[bk_i] = q
                    upd["biomeOutput"] = bio
            elif field == "multipliers":
                if isinstance(val, dict) and isinstance(val.get("cultureType"), dict):
                    mult = {}
                    for k, qv in val["cultureType"].items():
                        q = _finite(qv, None, 0.0, 100.0)
                        if q is not None:
                            mult[str(k)] = q
                    upd["multipliers"] = {"cultureType": mult}
        if upd:
            gd.update(upd)


def _load_special_goods():
    """Читає каталог регіональних товарів; недовірені дані відсіюються нижче."""
    if not os.path.isfile(SPECIAL_GOODS_PATH):
        return []
    try:
        with open(SPECIAL_GOODS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("goods")
    return items if isinstance(items, list) else []


def _special_origin_match(origin, mg):
    """Перевіряє регіональні умови; для старих сейвів біом може бути None."""
    if not isinstance(origin, dict):
        return True
    bands = origin.get("bands")
    if isinstance(bands, (list, tuple)) and bands and mg.get("band") not in bands:
        return False
    biomes = origin.get("biomes")
    if isinstance(biomes, (list, tuple)) and biomes:
        b = mg.get("biome")
        if b is not None and b not in biomes:
            return False
    if origin.get("coast") and not mg.get("coast"):
        return False
    if origin.get("river") and not mg.get("river"):
        return False
    return True


def _apply_special_goods(w):
    """Додає спецтовари й частково конвертує базову сировину в кожному місті."""
    cfg = w.get("config") if isinstance(w.get("config"), dict) else {}
    if not bool(cfg.get("special_goods_enabled", True)):
        return
    rate = _finite(cfg.get("specialty_rate", 1.0), 1.0, 0.0, 2.0)
    if rate <= 0.0:
        return
    goods = w.get("goods")
    burgs = w.get("burgs")
    if not isinstance(goods, dict) or not isinstance(burgs, dict):
        return
    geo = GT.ensure_geography(w)
    mgeo = geo.get("market_geo") or {}
    regions = geo.get("regions") or {}
    seed = str((w.get("meta") or {}).get("seed", "1"))

    for spec in _load_special_goods():
        if not isinstance(spec, dict):
            continue
        try:
            gid = int(_finite(spec.get("id"), -1, 100, 100000))
            base = int(_finite(spec.get("base"), -1, 1, 100000))
        except (TypeError, ValueError, OverflowError):
            continue
        if gid < 100 or gid in goods or base not in goods:
            continue
        vm = _finite(spec.get("value_mult"), 1.0, 1.0, 5.0)
        div = _finite(spec.get("divert"), 0.0, 0.0, 0.9)
        rarity = _finite(spec.get("rarity"), 0.0, 0.0, 1.0)
        if vm <= 0.0 or div <= 0.0 or rarity <= 0.0:
            continue
        base_value = _finite(goods[base].get("value"), 1.0, 1e-9, 1e9)
        tags = spec.get("tags")
        tags = [str(t) for t in tags] if isinstance(tags, (list, tuple)) else []
        if "specialty" not in tags:
            tags.append("specialty")
        # Корисність specialty має дорівнювати корисності витісненої сировини:
        # q_spec = q_base / value_mult, отже cover = base_cover * value_mult.
        # Каталог cover лишається документацією; фактичне значення беремо з базового товару.
        base_cover = goods[base].get("cover") if isinstance(goods[base].get("cover"), dict) else {}
        cover = {}
        for cat, amount in base_cover.items():
            if cat in LD.CATEGORIES:
                cv = _finite(amount, 0.0, 0.0, 10.0)
                if cv > 0.0:
                    cover[cat] = min(10.0, cv * vm)
        origin = spec.get("origin") if isinstance(spec.get("origin"), dict) else {}
        goods[gid] = dict(
            id=gid,
            name=str(spec.get("name") or LD.good_uk(gid))[:120],
            value=min(1e9, max(1e-9, base_value * vm)),
            tags=tags,
            unit=str(spec.get("unit", ""))[:40],
            cover=cover,
            recipes=[],
            chance=0.0,
            biome_out={},
            cult_mult={},
            base=base,
            specialty=True,
            value_mult=vm,
            origin=origin,
        )
        for bid, b in burgs.items():
            mid = b.get("market")
            mg = mgeo.get(mid)
            if not isinstance(mg, dict) or not _special_origin_match(origin, mg):
                continue
            raw = b.get("raw") if isinstance(b.get("raw"), dict) else {}
            avail = _finite(raw.get(base), 0.0, 0.0, 1e12)
            if avail <= 0.0:
                continue
            chance = min(1.0, rarity * rate)
            if random.Random("%s:%d:%s" % (seed, gid, bid)).random() > chance:
                continue
            q = avail * min(0.9, div * min(rate, 1.5))
            if q <= 0.0:
                continue
            raw[base] = max(0.0, avail - q)
            raw[gid] = _finite(raw.get(gid), 0.0, 0.0, 1e12) + q / vm
            b["raw"] = raw
            for bucket in (mg, regions.get(mg.get("region"))):
                if isinstance(bucket, dict):
                    got = bucket.setdefault("specialties", [])
                    if gid not in got:
                        got.append(gid)


def _make_province_lore(w, p, p_burgs):
    goods = w["goods"]
    raw_tot = {}
    craft_tot = {}
    ports = walls = temples = 0
    for b in p_burgs:
        if b.get("port"):
            ports += 1
        if b.get("walls"):
            walls += 1
        if b.get("temple"):
            temples += 1
        for g, u in b.get("raw", {}).items():
            raw_tot[g] = raw_tot.get(g, 0.0) + u * goods[g]["value"]
        for sl in b.get("craft", []):
            craft_tot[sl["good"]] = craft_tot.get(sl["good"], 0.0) + sl["units"] * goods[sl["good"]]["value"]
    top_raw = [LD.good_uk(g, goods) for g, _ in sorted(raw_tot.items(), key=lambda x: -x[1])[:2]]
    top_craft = [LD.good_uk(g, goods) for g, _ in sorted(craft_tot.items(), key=lambda x: -x[1])[:2]]
    parts = []
    if top_raw:
        parts.append("Сировина: " + ", ".join(top_raw))
    if top_craft:
        parts.append("Ремесла: " + ", ".join(top_craft))
    specialty = " · ".join(parts) if parts else "Змішане господарство"
    feats = []
    if ports:
        feats.append("приморська торгівля" if ports == 1 else "мережа портів")
    if walls:
        feats.append("укріплені рубежі")
    if temples:
        feats.append("шановані храми")
    cb = w["burgs"][p["burg"]]
    lore = f"Адміністративний центр — {cb['uk']}. Головний промисел: {specialty}."
    if feats:
        lore += " Особливості краю: " + ", ".join(feats) + "."
    return specialty, lore


def build_world(imp, seed=1, overrides=None, start_year=None, era=None):
    rng = random.Random(seed)
    overrides = overrides or {}
    w = imp
    # Спільний контракт конфігурації +(map-specific) значення.
    w["config"] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in E.CONFIG_DEFAULTS.items()}
    w["config"].update(dict(
        per_capita={"food": 10.0, "utilities": 4.0, "construction": 1.5, "luxury": 0.8},
        craft_scale=1.0, transport_rate=0.012, birth=0.0042, death=0.0028,
        poll_k=1.0, mil_k=1.0, mil_goods_per_head=0.002, admin_share=0.2,
        event_rate=1.0, war_rate=1.0,
    ))
    _apply_content_pack(w)
    _apply_special_goods(w)
    cultures = w["cultures"]
    start_year = int(_finite(start_year, LD.START_YEAR, -100000, 100000))
    era = LD.ERA_SHORT if era is None else era
    matched_known = sum(1 for st in w["states"].values() if st["name"] in LD.KNOWN_STATES)
    world_name = w["meta"].get("world_name", "Feria")
    is_feria = (world_name == "Feria") or (matched_known >= 3)
    ov_states, ov_burgs, ov_provs = _resolve_overrides(overrides, world_name, is_feria)

    # ---- міста
    for b in w["burgs"].values():
        ov_b = ov_burgs.get(str(b["id"]))
        ov_b_uk = ov_b.get("uk") if isinstance(ov_b, dict) else ov_b
        b["uk"] = ov_b_uk or LD.translit(b["name"])
        b["pop0"] = b["pop"] + b["rural"]
        b["sat"] = {}
        b["core_state"] = b["state"]
        b["occupied_by"] = None
    for m in w["markets"].values():
        cb = w["burgs"][m["center"]]
        m["name"] = cb["name"]
        m["uk"] = cb["uk"]
        m["capital"] = E.seed_market_capital(cb.get("pop", 0.0))
        m["shop_reserved"] = {}
        m["want"] = {}
        m.setdefault("stock", {})
        m.setdefault("price", {})
        for g in w["goods"]:
            m["stock"].setdefault(g, 0.0)
            m["price"].setdefault(g, w["goods"][g]["value"])
    # ---- держави
    for sid, st in w["states"].items():
        known = LD.KNOWN_STATES.get(st["name"], {}) if is_feria else {}
        ov_s = ov_states.get(str(sid))
        ov_s_dict = ov_s if isinstance(ov_s, dict) else ({"uk": ov_s} if ov_s else {})
        pref = _prefix(st["full_name"])
        st["uk"] = ov_s_dict.get("uk") or known.get("uk") or f"{pref} {LD.translit(st['name'])}"
        st["prefix_uk"] = pref
        if is_feria:
            st["continent"] = known.get("cont") or ("Кірос" if st.get("landmass") in LD.KIROS_LANDMASSES else "Турс")
        else:
            st["continent"] = LD.translit(st["landmass"]) if st.get("landmass") else "Материк"
        st["known"] = bool(known)
        st["coins"] = ov_s_dict.get("coins") or known.get("coins") or "Золота корона"
        st["gov_text"] = ov_s_dict.get("gov") or known.get("gov") or st["form"]
        st["lore"] = ov_s_dict["lore"] if "lore" in ov_s_dict else known.get("note", "")
        cult = cultures[st["culture"]]["name"] if st["culture"] in cultures else "Wildlands"
        k = known.get("ruler")
        traits = list(known.get("traits", []))
        if ov_s_dict.get("ruler"):
            rname = ov_s_dict["ruler"]
            collective = False
        elif k:
            rname, _g = k
            collective = _g == "collective"
        else:
            rname = _make_name(rng, cult)
            rname = f"{RULER_TITLE.get(pref, 'Правитель')} {rname}"
            collective = False
        pool = [t for t in LD.RANDOM_TRAIT_POOL if t not in traits]
        while len(traits) < 2:
            traits.append(pool.pop(rng.randrange(len(pool))))
        st["ruler"] = dict(name=rname, age=rng.randint(24, 72) if not collective else None,
                           traits=traits, collective=collective)
        gp = LD.GOV_PARAMS.get(st["form"], LD.GOV_PARAMS["Monarchy"])
        st["stability"] = round(gp["stab_base"] + rng.uniform(-8, 8), 1)
        st["legitimacy"] = round(rng.uniform(55, 85), 1)
        st["war_exhaustion"] = 0.0
        st["treasury"] = 0.0
        st["debt"] = 0.0
        st["readiness"] = 1.0
        st["tax_mult"] = 1.0
        st["prod_dev"] = 1.0
        st["truce"] = {}
        st["tech"] = 1.0
        st["food_sat"] = 1.0
        st["lux_sat"] = 1.0
        st["army0"] = dict(st["army"])
        st["mercs"] = []
        st["religion_name"] = w["religions"].get(st["religion"], {}).get("name", "—")
        st["culture_name"] = cult
    # ---- провінції, геральдика та намісники
    gov_pool = list(LD.GOVERNOR_TRAITS)
    for pid, p in w.get("provinces", {}).items():
        ov_p = ov_provs.get(str(pid))
        ov_p_dict = ov_p if isinstance(ov_p, dict) else ({"uk": ov_p} if ov_p else {})
        form_uk = LD.PROVINCE_FORM_UK.get(p.get("form") or "", "Провінція")
        raw_uk = LD.translit(p["name"])
        p["form_uk"] = form_uk
        p["uk"] = ov_p_dict.get("uk") or (f"{form_uk} {raw_uk}" if not raw_uk.lower().startswith(form_uk.lower()) else raw_uk)
        p["core_state"] = p["state"]
        p["occupied_by"] = None
        p["siege"] = 0.0
        p["assimilation"] = 0
        p["blazon"] = LD.blazon_coa(p.get("coa"))
        p_burgs = [w["burgs"][bid] for bid in p.get("burgs", []) if bid in w["burgs"]]
        specialty, lore_text = _make_province_lore(w, p, p_burgs)
        p["specialty"] = ov_p_dict.get("specialty") or specialty
        p["lore"] = ov_p_dict["lore"] if "lore" in ov_p_dict else lore_text
        cb = w["burgs"][p["burg"]]
        cult_p = cultures.get(cb.get("culture"), {}).get("name", w["states"][p["state"]]["culture_name"])
        title = LD.GOVERNOR_TITLE.get(form_uk, "Намісник")
        gname = ov_p_dict.get("governor") or f"{title} {_make_name(rng, cult_p)}"
        loy = float(ov_p_dict["loyalty"]) if ov_p_dict.get("loyalty") not in (None, "") else round(rng.uniform(65, 92), 1)
        p["governor"] = dict(
            name=gname,
            age=rng.randint(25, 66),
            traits=rng.sample(gov_pool, 2),
            loyalty=loy,
        )
    # ---- відносини
    rel = {}
    vassals = []
    ids = sorted(w["states"])
    for a in ids:
        for b in ids:
            if b <= a:
                continue
            la = w["states"][a]["diplo_labels"].get(b, "Unknown")
            lb = w["states"][b]["diplo_labels"].get(a, "Unknown")
            if la == "Suzerain":
                vassals.append([b, a])
            elif la == "Vassal":
                vassals.append([a, b])
            if lb == "Suzerain" and [a, b] not in vassals:
                vassals.append([a, b])
            elif lb == "Vassal" and [b, a] not in vassals:
                vassals.append([b, a])
            sc = (LD.DIPLO_SCORE.get(la, 0) + LD.DIPLO_SCORE.get(lb, 0)) / 2.0
            rel.setdefault(a, {})[b] = sc
    w["relations"] = rel
    w["vassals"] = vassals
    # ---- війни
    map_yr = _finite(w["meta"].get("map_year"), 0, -100000, 100000)
    map_yr = int(map_yr)
    if is_feria:
        shift = (start_year - map_yr) if map_yr else LD.MAP_YEAR_OFFSET + (start_year - LD.START_YEAR)
    else:
        shift = (start_year - map_yr) if map_yr else 0
    wars = []
    hist = []
    for c in w["history_wars"]:
        if c["attacker"] not in w["states"] or c["defender"] not in w["states"]:
            continue
        rec = dict(name=c["name"], start=c["start"] + shift, end=(c["end"] + shift) if c["end"] else None,
                   attacker=c["attacker"], defender=c["defender"])
        if c["end"] is None:
            a, d = c["attacker"], c["defender"]
            wars.append(dict(id=len(wars) + 1, name=c["name"], attackers=[a], defenders=[d], score=0.0,
                             exhaustion=0.0, start_year=rec["start"], start_month=1, captured=[], log=[]))
            w["states"][a]["truce"].pop(d, None)
        else:
            hist.append(rec)
    w["wars"] = wars
    w["war_history"] = hist
    w["war_pairs"] = []
    # ---- гільдії, найманці, ордени, похід
    if is_feria:
        by_name = {}
        for b in w["burgs"].values():
            by_name.setdefault(b["name"], []).append(b)
        name_to_state = {st["name"]: sid for sid, st in w["states"].items()}
        guilds = []
        for g in LD.GUILDS:
            sid = name_to_state.get(g["home_state"])
            cand = [b for b in by_name.get(g["home"], []) if sid is None or b["state"] == sid]
            if not cand and sid:
                cand = [w["burgs"][w["states"][sid]["capital"]]]
            if not cand:
                continue
            hb = cand[0]
            guilds.append(dict(id=g["id"], name=g["name"], kind=g["kind"], burg=hb["id"], market=hb["market"],
                               state=hb["state"], goods=g["goods"], wealth=float(g["wealth"]), power=g["power"],
                               note=g["note"], rep={}))
        w["guilds"] = guilds
        mercs = []
        for mc in LD.MERCENARIES:
            sid = name_to_state.get(mc["home_state"])
            mercs.append(dict(id=mc["id"], name=mc["name"], size=mc["size"], fee=mc["fee_per_head"], unit=mc["unit"],
                              home=sid, employer=None, contract_end=None, cash=0.0))
        w["mercs"] = mercs
        w["orders"] = [dict(id=o["id"], name=o["name"], state=name_to_state.get(o["state"]) if o["state"] else None,
                            strength=o["strength"], unit=o["unit"]) for o in LD.ORDERS]
        cr = LD.CRUSADE
        w["crusade"] = dict(name=cr["name"], phase="rumors", start_tick=cr["start_after_months"],
                            sponsors=[name_to_state[n] for n in cr["sponsor_states"] if n in name_to_state],
                            fleet=0.0, supplies=0.0, progress=0.0, result=None)
    else:
        w["guilds"], w["mercs"], w["orders"] = _generate_generic_orgs(w, rng)
        w["crusade"] = dict(name="Похід (неактивно для цієї карти)", phase="inactive", start_tick=999999,
                            sponsors=[], fleet=0.0, supplies=0.0, progress=0.0, result=None)
    # ---- службові структури
    w["date"] = dict(year=start_year, month=1)
    w["mods"] = []
    w["journal"] = []
    w["history"] = dict(states=[], world=[])
    w["meta"]["sim_seed"] = seed
    w["meta"]["start_year"] = start_year
    w["meta"]["era"] = era
    w["meta"]["is_feria"] = is_feria
    return w


def _make_name(rng, cult):
    a, b = LD.CULTURE_SYLLABLES.get(cult, LD.CULTURE_SYLLABLES["Wildlands"])
    return rng.choice(a) + rng.choice(b)


# ---------------------------------------------------------------------------
# Калібрування економіки
# ---------------------------------------------------------------------------
def _calibrate_in_place(sim, log=print, warm_iters=30, months_per=3):
    """Внутрішня калібрування на тимчасовій копії світу (див. ``calibrate``)."""
    w = sim.w
    cfg = w["config"]
    orig_date = dict(w["date"])
    orig_capital = {mid: m.get("capital", 0.0) for mid, m in sim.markets.items()}
    # калібрування не повинно залишати сліди у службових структурах світу
    orig_mods = list(w.get("mods", []))
    orig_journal = list(w.get("journal", []))
    orig_new_journal = list(w.get("_new_journal", []))
    orig_events = list(w.get("active_events", []))
    orig_history = {k: list(v) for k, v in w.get("history", {}).items()}
    # 1) початкові душові норми з потенційної пропозиції сировини
    pop_k = sum(b["pop"] + b["rural"] for b in sim.burgs.values()) / 1000.0
    sup = {c: 0.0 for c in LD.CATEGORIES}
    for b in sim.burgs.values():
        for g, u in b["raw"].items():
            for c, cv in sim.goods[g]["cover"].items():
                sup[c] = sup.get(c, 0.0) + u * cv
    for c in ("food", "utilities", "construction", "luxury"):
        cfg["per_capita"][c] = sup[c] * LD.CAL_TARGET[c] / pop_k * (1.0 if c == "food" else 0.7)
    # 2) масштаб ремесла: ≈15 % вартості сировини, але не більше 70 % доступної сировини по кожному ресурсу
    raw_tot = {}
    craft_in_1x = {}
    for b in sim.burgs.values():
        for g, u in b["raw"].items():
            raw_tot[g] = raw_tot.get(g, 0.0) + u
        for sl in b["craft"]:
            cap1 = sl["units"] * ((b["pop0"] / 20000.0) ** 0.5)
            for ig, iq in sl["recipe"].items():
                craft_in_1x[ig] = craft_in_1x.get(ig, 0.0) + iq * cap1
    raw_val = sum(u * sim.goods[g]["value"] for g, u in raw_tot.items())
    craft_val = sum(sl["units"] * sim.goods[sl["good"]]["value"] * ((b["pop0"] / 20000.0) ** 0.5)
                    for b in sim.burgs.values() for sl in b["craft"])
    scale = 0.15 * raw_val / max(craft_val, 1e-9)
    for g, req1 in craft_in_1x.items():
        if req1 > 0 and not sim.goods[g]["recipes"] and raw_tot.get(g, 0.0) > 0:
            scale = min(scale, 0.70 * raw_tot[g] / req1)
    cfg["craft_scale"] = max(scale, 0.5)
    log(f"[calib] raw_val={raw_val:,.0f} craft_scale={cfg['craft_scale']:.2f} per_capita={ {k: round(v,2) for k,v in cfg['per_capita'].items()} }")
    # 3) ітерації прогріву без політики/подій: підганяємо душові норми під цінові індекси
    cats = ("food", "utilities", "construction", "luxury")
    for it in range(warm_iters):
        tot_req = {c: 0.0 for c in cats}
        tot_got = {c: 0.0 for c in cats}
        for _ in range(months_per):
            # календар реально йде вперед: RNG і сезонність змінюються від місяця до місяця
            sim.tick(politics=False, events=False, advance=True, finance=False)
            for sid in sim.acc["req"]:
                for c in cats:
                    tot_req[c] += sim.acc["req"][sid].get(c, 0.0)
                    tot_got[c] += sim.acc["got"][sid].get(c, 0.0)
        msg = []
        done = True
        for c in cats:
            r = tot_got[c] / tot_req[c] if tot_req[c] else 1.0
            idx = sim.price_index(c)
            if idx > 1.15 or r < 0.97:
                step = 0.85 if idx > 1.8 else 0.95
                cfg["per_capita"][c] *= step
                done = False
            elif idx < 0.88 and r > 0.995:
                step = 1.12 if idx < 0.7 else 1.05
                cfg["per_capita"][c] *= step
                done = False
            msg.append(f"{c}: sat={r:.3f} idx={idx:.2f}")
        log(f"[calib] iter {it + 1}: " + "; ".join(msg))
        if done:
            break
    # 4) фінанси: податок і утримання армії
    gdp = {s: 0.0 for s in sim.states}
    cons = {s: 0.0 for s in sim.states}
    for _ in range(3):
        sim.tick(politics=False, events=False, advance=True, finance=False)
        for s in sim.states:
            gdp[s] += sim.acc["gdp"].get(s, 0.0) / 3
            cons[s] += sim.acc["cons_val"].get(s, 0.0) / 3
    tot_poll_raw = sum(st["poll_tax"] * (st.get("pop_cache") or _state_pop(sim, s)) / 1000.0 / 12.0
                       for s, st in sim.states.items())
    cfg["poll_k"] = 0.09 * sum(gdp.values()) / max(tot_poll_raw, 1e-9)
    from .politics import UNIT_POWER
    for s, st in sim.states.items():
        pop = _state_pop(sim, s)
        poll = cfg["poll_k"] * st["poll_tax"] * pop / 1000.0 / 12.0
        sales = cons[s] * st["sales_tax"]
        rev = poll + sales + 0.01 * gdp[s]
        st["rev0"] = rev
        raw_up = sum(n * UNIT_POWER.get(u, 1.0) for u, n in st["army"].items())
        target = rev * (0.30 + 0.12 * min(st.get("alert", 1) or 1, 2.5)) * (0.9 + 0.2 * random.Random(s).random())
        st["army_cost"] = target / raw_up if raw_up > 0 else 0.0
        ratio = st["treasury_map"] / max(st["poll_tax"] * pop / 1000.0, 1e-9)
        st["treasury"] = rev * 12.0 * E.clamp(ratio, 0.25, 2.5)
        st["pop_cache"] = pop
    log("[calib] фінанси: poll_k={:.3f}".format(cfg["poll_k"]))
    # повертаємо капітали, дату й службові структури: калібрування не має забруднювати світ
    for mid, m in sim.markets.items():
        cap = orig_capital.get(mid, 0.0)
        if cap <= 0:
            cap = E.seed_market_capital(sim.burgs.get(m["center"], {}).get("pop", 0.0))
        m["capital"] = cap
    w["date"] = orig_date
    w["history"] = orig_history
    w["journal"] = orig_journal
    if orig_new_journal:
        w["_new_journal"] = orig_new_journal
    else:
        w.pop("_new_journal", None)
    w["mods"] = orig_mods
    w["active_events"] = orig_events
    sim._index_mods()


def calibrate(sim, log=print, warm_iters=30, months_per=3):
    """Калібрує економіку, не змінюючи стан гри окрім калібрувальних констант.

    Прогрів тикає симуляцію, тому працюємо на глибокій копії світу й переносимо
    назад лише ``config`` та фінансові похідні держав. Повторний виклик дає той
    самий результат (ідемпотентність).
    """
    original = sim.w
    work = copy.deepcopy(original)
    sim.w = work
    sim.build_runtime()
    # Прогів починається з канонічного порожнього ринку: це робить повторний
    # виклик ідемпотентним навіть після того, як перший калібрував запаси.
    for m in sim.markets.values():
        m["stock"] = {g: 0.0 for g in sim.goods}
        m["price"] = {g: sim.goods[g]["value"] for g in sim.goods}
        m["want"] = {}
        m["want_now"] = {}
        m["shop_reserved"] = {}
        cb = sim.burgs.get(m.get("center"), {})
        m["capital"] = E.seed_market_capital(cb.get("pop", 0.0))
    try:
        _calibrate_in_place(sim, log=log, warm_iters=warm_iters, months_per=months_per)
        cfg_out = copy.deepcopy(work.get("config", {}))
        outputs = {}
        for sid, st in sim.states.items():
            if isinstance(st, dict):
                outputs[sid] = {k: copy.deepcopy(st[k])
                                for k in ("rev0", "army_cost", "treasury", "pop_cache") if k in st}
        # Запаси, набрані під час прогріву, є частиною початкової економіки:
        # без них ринки стартують порожніми й торгівля/крамниці не працюють.
        stocks = {mid: copy.deepcopy(m.get("stock", {})) for mid, m in sim.markets.items()}
    finally:
        sim.w = original
        sim.build_runtime()
    cfg = original.get("config")
    if not isinstance(cfg, dict):
        cfg = {}
        original["config"] = cfg
    cfg.update(cfg_out)
    states = original.get("states")
    if isinstance(states, dict):
        for sid, vals in outputs.items():
            st = states.get(sid)
            if isinstance(st, dict):
                st.update(vals)
    markets = original.get("markets")
    if isinstance(markets, dict):
        for mid, stock in stocks.items():
            m = markets.get(mid)
            if isinstance(m, dict):
                m["stock"] = stock
    sim.build_runtime()
    sim._index_mods()


def _state_pop(sim, sid):
    return sum(sim.burgs[b]["pop"] + sim.burgs[b]["rural"] for b in sim.state_burgs.get(sid, []))
