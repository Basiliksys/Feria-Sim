# -*- coding: utf-8 -*-
"""Прикладні інструменти для Майстра гри (D&D 5e): роздрібні ціни, маршрути подорожі, квестові гачки."""
import hashlib
import heapq
import math
import random
import re
import uuid

from . import lore_data as LD
from . import engine as E
from . import politics as PO

COIN_NAMES = [("пм", 1_000_000), ("зм", 10_000), ("см", 100), ("мм", 1)]

# Stable ids from goods_default.json. LD.GOOD_IDS wins when the core workstream
# has installed it; the local table keeps D&D tools working on older saves.
_FALLBACK_GOOD_IDS = {
    "wood": 1, "stone": 2, "marble": 3, "iron": 4, "copper": 5, "tin": 6,
    "silver": 7, "gold": 8, "grain": 9, "cattle": 10, "fish": 11, "game": 12,
    "wine": 13, "olives": 14, "honey": 15, "salt": 16, "dates": 17,
    "horses": 18, "elephants": 19, "camels": 20, "hemp": 21, "pearls": 22,
    "gemstones": 23, "dyes": 24, "incense": 25, "silk": 26, "spices": 27,
    "amber": 28, "furs": 29, "sheep": 30, "slaves": 31, "tar": 32,
    "saltpeter": 33, "coal": 34, "oil": 35, "mahogany": 36, "whales": 37,
    "sugarcane": 38, "tea": 39, "tobacco": 40, "clay": 41, "white_sand": 42,
    "leather": 43, "cloth": 44, "garments": 45, "ceramics": 46, "glass": 47,
    "ropes": 48, "paper": 49, "ink": 50, "books": 51, "sails": 52,
    "ships": 53, "boots": 54, "harnesses": 55, "barrels": 56, "bronze": 57,
    "tools": 58, "arms": 59, "gunpowder": 60, "artillery": 61, "coins": 62,
    "jewelry": 63, "preserved_food": 64, "vinegar": 65, "cheese": 66,
    "beer": 67, "liquor": 68, "candles": 69, "soap": 70, "perfume": 71,
}


def _gid(name, fallback=None):
    """Resolve a canonical good id without breaking on older lore modules."""
    ids = getattr(LD, "GOOD_IDS", None)
    if isinstance(ids, dict) and name in ids:
        try:
            return int(ids[name])
        except (TypeError, ValueError):
            pass
    if fallback is not None:
        try:
            return int(fallback)
        except (TypeError, ValueError):
            pass
    # Unknown ids must not make catalog construction fail on a partial save.
    return int(_FALLBACK_GOOD_IDS.get(name, 0))

RETAIL_CATEGORIES = [
    "Таверна та їжа",
    "Спорядження й побут",
    "Зброя та обладунки",
    "Транспорт і тварини",
    "Послуги та магія",
]

RETAIL_CATALOG = [
    # Таверна та їжа
    dict(id="ale_mug", name="Кухоль елю", cat="Таверна та їжа", base_mm=400, weights={_gid("beer"): 0.7, _gid("grain"): 0.3}, rust=False, units=1),
    dict(id="wine_flask", name="Фляга вина", cat="Таверна та їжа", base_mm=2500, weights={_gid("wine"): 1.0}, rust=False, units=1),
    dict(id="inn_poor", name="Таверна: бідний обід і нічліг", cat="Таверна та їжа", base_mm=600, weights={_gid("grain"): 0.7, _gid("coal"): 0.3}, rust=False, units=1),
    dict(id="inn_modest", name="Таверна: скромний постій", cat="Таверна та їжа", base_mm=2000, weights={_gid("grain"): 0.4, _gid("cattle"): 0.3, _gid("beer"): 0.3}, rust=False, units=1),
    dict(id="inn_comf", name="Таверна: комфортний постій", cat="Таверна та їжа", base_mm=8000, weights={_gid("cattle"): 0.4, _gid("cheese"): 0.3, _gid("wine"): 0.3}, rust=False, units=1),
    dict(id="inn_wealthy", name="Таверна: багатий постій", cat="Таверна та їжа", base_mm=25000, weights={_gid("wine"): 0.4, _gid("spices"): 0.3, _gid("jewelry"): 0.3}, rust=False, units=1),
    dict(id="rations", name="Дорожній пайок (1 день)", cat="Таверна та їжа", base_mm=1500, weights={_gid("preserved_food"): 0.6, _gid("grain"): 0.4}, rust=False, units=1),
    # Спорядження й побут
    dict(id="torch_bundle", name="Факел (в'язка 5 шт.)", cat="Спорядження й побут", base_mm=100, weights={_gid("wood"): 0.6, _gid("tar"): 0.4}, rust=False, units=5),
    dict(id="lamp_oil", name="Олія для ліхтаря (фляга)", cat="Спорядження й побут", base_mm=500, weights={_gid("oil"): 0.6, _gid("whales"): 0.4}, rust=False, units=1),
    dict(id="rope_50", name="Мотузка конопляна (50 фт)", cat="Спорядження й побут", base_mm=1000, weights={_gid("ropes"): 0.7, _gid("hemp"): 0.3}, rust=False, units=1),
    dict(id="artisan_tools", name="Набір ремісничих інструментів", cat="Спорядження й побут", base_mm=50000, weights={_gid("tools"): 0.8, _gid("iron"): 0.2}, rust=True, units=1),
    dict(id="travel_clothes", name="Дорожній одяг і плащ", cat="Спорядження й побут", base_mm=15000, weights={_gid("garments"): 0.6, _gid("boots"): 0.4}, rust=False, units=1),
    # Зброя та обладунки
    dict(id="spear_dagger", name="Спис або кинджал", cat="Зброя та обладунки", base_mm=10000, weights={_gid("arms"): 0.7, _gid("wood"): 0.3}, rust=True, units=1),
    dict(id="longsword", name="Довгий меч / бойова сокира", cat="Зброя та обладунки", base_mm=120000, weights={_gid("arms"): 0.7, _gid("iron"): 0.3}, rust=True, units=1),
    dict(id="longbow", name="Довгий лук і сагайдак (20 стріл)", cat="Зброя та обладунки", base_mm=180000, weights={_gid("wood"): 0.5, _gid("arms"): 0.5}, rust=False, units=1),
    dict(id="leather_armor", name="Шкіряний обладунок", cat="Зброя та обладунки", base_mm=80000, weights={_gid("leather"): 0.8, _gid("garments"): 0.2}, rust=False, units=1),
    dict(id="chain_mail", name="Кольчуга", cat="Зброя та обладунки", base_mm=550000, weights={_gid("arms"): 0.6, _gid("iron"): 0.4}, rust=True, units=1),
    dict(id="plate_armor", name="Повний латний обладунок", cat="Зброя та обладунки", base_mm=4500000, weights={_gid("arms"): 0.7, _gid("iron"): 0.3}, rust=True, units=1),
    # Транспорт і тварини
    dict(id="draft_horse", name="Тягловий кінь", cat="Транспорт і тварини", base_mm=250000, weights={_gid("horses"): 1.0}, rust=False, units=1),
    dict(id="warhorse", name="Бойовий / верховий кінь", cat="Транспорт і тварини", base_mm=650000, weights={_gid("horses"): 0.8, _gid("harnesses"): 0.2}, rust=False, units=1),
    dict(id="wagon", name="Віз із упряжжю", cat="Транспорт і тварини", base_mm=150000, weights={_gid("wood"): 0.6, _gid("harnesses"): 0.4}, rust=False, units=1),
    dict(id="ship_ticket", name="Квиток на корабель (за 100 км)", cat="Транспорт і тварини", base_mm=10000, weights={_gid("ships"): 0.6, _gid("sails"): 0.4}, rust=False, units=1),
    # Послуги та магія
    dict(id="healing_potion", name="Зілля лікування (мале)", cat="Послуги та магія", base_mm=350000, weights={_gid("incense"): 0.4, _gid("liquor"): 0.3, _gid("glass"): 0.3}, rust=False, units=1),
    dict(id="spell_scroll_1", name="Сувій закляття 1-го кола", cat="Послуги та магія", base_mm=250000, weights={_gid("paper"): 0.4, _gid("ink"): 0.4, _gid("books"): 0.2}, rust=False, units=1),
    dict(id="guard_hire", name="Найм охоронця / провідника (доба)", cat="Послуги та магія", base_mm=10000, weights={_gid("grain"): 0.5, _gid("arms"): 0.5}, rust=False, units=1),
    dict(id="forge_repair", name="Ремонт зброї чи обладунку в кузні", cat="Послуги та магія", base_mm=15000, weights={_gid("tools"): 0.6, _gid("coal"): 0.4}, rust=True, units=1),
]

MODES = {
    "foot": dict(name="Пішки", land_km=36.0, sea_km=95.0, day_mm=1500),
    "wagon": dict(name="Обоз / віз", land_km=28.0, sea_km=90.0, day_mm=4500),
    "horse": dict(name="Верхи", land_km=55.0, sea_km=95.0, day_mm=8500),
    "ship": dict(name="Кораблем (морський пріоритет)", land_km=36.0, sea_km=115.0, day_mm=12000),
}


def _value_to_mm():
    """Курс збереження з безпечним запасним значенням для старих lore-модулів."""
    try:
        v = float(LD.VALUE_TO_MM)
    except (AttributeError, TypeError, ValueError):
        v = 10000.0
    return v if math.isfinite(v) and v > 0 else 10000.0


def fmt_mm(mm: float) -> str:
    """Форматує роздрібну вартість у монетах; дрібні номінали не губити."""
    val = int(round(mm))
    if val <= 0:
        return "0 мм"
    parts = []
    for name, size in COIN_NAMES:
        q, val = divmod(val, size)
        if q:
            parts.append(f"{q} {name}")
    return " ".join(parts) if parts else "0 мм"


def _km_factor(sim):
    """Переводить одиниці відстані метаданих у кілометри."""
    try:
        unit = str((((sim.w.get("meta") or {}).get("units") or {}).get("distance") or {}).get("unit", "km") or "km").strip().lower()
    except AttributeError:
        unit = "km"
    return 1.609344 if unit in ("mi", "mile", "miles") else 1.0


def _dist_km(sim, a, b):
    try:
        scale = float((((sim.w.get("meta") or {}).get("units") or {}).get("distance") or {}).get("scale", 3.0) or 3.0)
    except (TypeError, ValueError):
        scale = 3.0
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"]) * scale * _km_factor(sim)


def _edge_km(sim, edge):
    """Відстань ребра ринкової мережі в км (з урахуванням одиниць метаданих)."""
    try:
        d = float(edge.get("dist", 0.0))
    except (TypeError, ValueError):
        d = 0.0
    return max(d, 1.0) * _km_factor(sim)


def _has_black_rust(sim, sid, st_uk):
    t = sim.tick_index()
    for mod in sim.w.get("mods", []):
        if mod.get("scope") == "state" and mod.get("id") == sid and mod.get("src") == "black_rust" and mod.get("until", 0) > t:
            return True
    for ev in sim.w.get("active_events", []):
        if ev.get("key") == "black_rust" and ev.get("until", t + 1) > t:
            if sid in (ev.get("states") or []) or ev.get("target") == st_uk:
                return True
    return False


def city_retail_prices(sim, burg_id):
    """Розраховує роздрібні D&D-ціни крамниць, таверн, кузні й транспорту в обраному місті."""
    bid = int(burg_id)
    if bid not in sim.burgs:
        raise KeyError(f"Місто {burg_id} не знайдено")
    b = sim.burgs[bid]
    m = sim.markets[b["market"]]
    sid = b["state"]
    st = sim.states[sid]
    has_rust = _has_black_rust(sim, sid, st["uk"])
    in_war = bool(PO.in_war(sim, sid))
    is_cap = bool(b.get("capital"))
    tax_rate = st.get("sales_tax", 0.04) * max(st.get("tax_mult", 1.0), 0.5)

    reserved = m.get("shop_reserved") or {}
    items = []
    for item in RETAIL_CATALOG:
        raw_ratio = 0.0
        w_tot = 0.0
        for g, wt in item["weights"].items():
            gobj = sim.goods.get(g)
            if not gobj:
                continue
            base = max(float(gobj["value"]), 0.1)
            cur = float(m["price"].get(g, base))
            raw_ratio += wt * (cur / base)
            w_tot += wt
        raw_ratio = (raw_ratio / w_tot) if w_tot > 0 else 1.0
        mult = (max(raw_ratio, 0.2) ** 0.72) * (1.0 + tax_rate)
        if is_cap:
            mult *= 1.06
        if item.get("rust") and has_rust:
            mult *= 1.65
        if in_war and item["cat"] == "Зброя та обладунки":
            mult *= 1.20
        mm = max(10, int(round(item["base_mm"] * mult)))
        pct = int(round((mm / item["base_mm"]) * 100))
        if pct >= 210:
            status = "Критичний дефіцит"
        elif pct >= 140:
            status = "Дефіцит"
        elif pct <= 75:
            status = "Надлишок"
        else:
            status = "В наявності"
        # Реальна доступність рахується від ефективного запасу: сирий запас
        # мінус уже зарезервований під інші пропозиції. Резерв ніколи не
        # витрачається самою купівлею (див. purchase_shop_item).
        need_units = max(float(item.get("units", 1) or 1), 1e-9)
        wsum = sum(item["weights"].values()) or 1.0
        stock = {}
        per_unit = {}
        for g in item["weights"]:
            try:
                raw_stock = float(m.get("stock", {}).get(g, 0.0))
                raw_reserved = float(reserved.get(g, 0.0))
            except (TypeError, ValueError):
                raw_stock, raw_reserved = 0.0, 0.0
            eff = max(0.0, raw_stock - raw_reserved)
            stock[g] = eff
            per_unit[g] = max(need_units * (float(item["weights"][g]) / wsum), 1e-9)
        ratios = [stock[g] / per_unit[g] for g in stock]
        # Невеликий epsilon захищає від втрати однієї одиниці через float-шум.
        available = max(0, int(math.floor(min(ratios) + 1e-9))) if ratios else 0
        if available <= 0:
            status = "Немає в наявності"
        items.append(dict(
            id=item["id"], name=item["name"], cat=item["cat"],
            base_mm=item["base_mm"], base_coins=fmt_mm(item["base_mm"]),
            mm=mm, coins=fmt_mm(mm), pct=pct, status=status,
            available=available, units=need_units, stock={str(g): round(v, 1) for g, v in stock.items()},
        ))

    return dict(
        burg_id=bid, burg_uk=b["uk"], state_id=sid, state_uk=st["uk"],
        market_id=m["id"], market_uk=m["uk"], coins_name=st.get("coins", "Золота монета"),
        modifiers=dict(
            tax_pct=round(tax_rate * 100, 1),
            is_capital=is_cap,
            in_war=in_war,
            black_rust=has_rust,
            food_index=round(sim.price_index("food", sid), 2),
        ),
        categories=list(RETAIL_CATEGORIES),
        items=items,
    )


def purchase_shop_item(sim, burg_id, item_id, qty=1):
    """Списує придбаний D&D-предмет із ринкового запасу й повертає квитанцію."""
    bid = int(burg_id)
    if bid not in sim.burgs:
        raise KeyError(f"Місто {burg_id} не знайдено")
    try:
        q = float(qty)
        if not math.isfinite(q):
            raise ValueError("quantity must be finite")
        count = int(max(1.0, min(99.0, q)))
    except (TypeError, ValueError, OverflowError):
        count = 1
    retail = city_retail_prices(sim, bid)
    item = next((it for it in retail["items"] if it["id"] == str(item_id)), None)
    if item is None:
        return dict(ok=False, reason="Товар не знайдено у каталозі")
    if item["available"] < count:
        return dict(ok=False, reason=f"На ринку є лише {item['available']} шт.", available=item["available"])
    catalog = next((x for x in RETAIL_CATALOG if x["id"] == item["id"]), None)
    if catalog is None:
        return dict(ok=False, reason="Товар не знайдено у каталозі")
    m = sim.markets[sim.burgs[bid]["market"]]
    stock = m.setdefault("stock", {})
    # shop_reserved лише читаємо в city_retail_prices: продаж не має зменшувати
    # резерв, бо тоді резервовані товари ніколи не зникають з пропозиції.
    wsum = sum(catalog["weights"].values()) or 1.0
    for g, wt in catalog["weights"].items():
        take = count * float(catalog.get("units", 1) or 1) * (wt / wsum)
        try:
            before = float(stock.get(g, 0.0))
        except (TypeError, ValueError):
            before = 0.0
        stock[g] = max(0.0, before - take)
    mm_cost = item["mm"] * count
    value_cost = mm_cost / _value_to_mm()
    # Позабалансовий роздріб: виручка йде лише до капіталу ринку (крамниці).
    # Казна не отримує окремої частки з тієї самої суми — інакше гроші
    # подвоюються. Податок уже закладений у роздрібну ціну (tax_rate).
    m["capital"] = float(m.get("capital", 0.0) or 0.0) + max(0.0, value_cost * 0.5)
    sim.log("gm", f"Купівля в {retail['burg_uk']}: {item['name']} ×{count} на {fmt_mm(mm_cost)}.")
    # Доступність перераховуємо за ефективним запасом, а не за збереженим
    # значенням з попереднього розрахунку.
    fresh = next((it for it in city_retail_prices(sim, bid)["items"] if it["id"] == item["id"]), None)
    return dict(ok=True, item=item["name"], qty=count, mm=mm_cost, coins=fmt_mm(mm_cost),
                available=fresh["available"] if fresh else max(0, item["available"] - count))


def travel_route(sim, from_burg_id, to_burg_id, mode="foot"):
    """Прокладає маршрут між двома містами, рахує час, витрати, загрози та D&D-зустрічі."""
    b1_id, b2_id = int(from_burg_id), int(to_burg_id)
    if b1_id not in sim.burgs or b2_id not in sim.burgs:
        raise KeyError("Одне з міст не знайдено")
    if mode not in MODES:
        mode = "foot"
    mc = MODES[mode]
    b1, b2 = sim.burgs[b1_id], sim.burgs[b2_id]

    def _node_info(node):
        kind, nid = node
        if kind == "b":
            bb = sim.burgs[nid]
            return dict(name=bb["uk"], x=bb["x"], y=bb["y"], state=bb["state"], market=bb["market"],
                        feature=bb.get("feature"), port=bb.get("port", False))
        mk = sim.markets[nid]
        cb = sim.burgs[mk["center"]]
        return dict(name=mk["uk"], x=cb["x"], y=cb["y"], state=sim.market_state[nid], market=nid,
                    feature=cb.get("feature"), port=cb.get("port", False))

    if b1_id == b2_id:
        st1 = sim.states[b1["state"]]
        return dict(
            from_id=b1_id, from_uk=b1["uk"], to_id=b2_id, to_uk=b2["uk"],
            mode=mode, mode_name=mc["name"],
            total_km=0.0, total_days=0.0, cost_mm=0, cost_coins="0 мм",
            danger_score=0, danger_level="Безпечно",
            legs=[], hazards=[], encounters=["Спокійна зупинка у місті призначення."],
            points=[dict(x=b1["x"], y=b1["y"], name=b1["uk"], sea=False, state_uk=st1["uk"])],
        )

    adj = {}

    def _add_edge(u, v, dist_km, sea):
        speed = mc["sea_km"] if sea else mc["land_km"]
        days = dist_km / max(speed, 1.0)
        if sea and mode != "ship":
            days += 0.5  # очікування попутного судна / порому
        pref = 0.75 if (sea and mode == "ship") else (1.6 if (sea and mode != "ship") else 1.0)
        wt = max(days * pref, 0.01)
        adj.setdefault(u, []).append((v, wt, dist_km, days, bool(sea)))
        adj.setdefault(v, []).append((u, wt, dist_km, days, bool(sea)))

    # Ринкова мережа
    for e in sim.edges:
        dist_km = _edge_km(sim, e)
        _add_edge(("m", e["a"]), ("m", e["b"]), dist_km, bool(e["sea"]))

    # Пряме ребро між містами поруч на одній суші
    direct_km = _dist_km(sim, b1, b2)
    same_land = (b1.get("feature") == b2.get("feature")) and (b1.get("feature") is not None)
    if (b1["market"] == b2["market"] or same_land) and direct_km < 260.0:
        d_road = max(1.0, direct_km * 1.22)
        _add_edge(("b", b1_id), ("b", b2_id), d_road, not same_land and not (b1["market"] == b2["market"]))

    # Прив'язка стартового й кінцевого міст до їхніх ринків та 3 найближчих ринків
    mk_list = [(mid, sim.burgs[m["center"]]) for mid, m in sim.markets.items()]
    for bid, bb in ((b1_id, b1), (b2_id, b2)):
        seen_m = set()
        cand_m = []
        own = bb["market"]
        if own in sim.markets:
            seen_m.add(own)
            cand_m.append((own, sim.burgs[sim.markets[own]["center"]]))
        near = sorted(mk_list, key=lambda pair: _dist_km(sim, bb, pair[1]))
        for mid, cb in near:
            if mid not in seen_m:
                seen_m.add(mid)
                cand_m.append((mid, cb))
            if len(cand_m) >= 4:
                break
        for mid, cb in cand_m:
            dkm = _dist_km(sim, bb, cb) * 1.15
            sea = (bb.get("feature") != cb.get("feature")) and (bb.get("port") or cb.get("port"))
            if bb.get("feature") != cb.get("feature") and not (bb.get("port") or cb.get("port")):
                sea = True
            _add_edge(("b", bid), ("m", mid), max(dkm, 0.5), bool(sea))

    start, goal = ("b", b1_id), ("b", b2_id)
    pq = [(0.0, start)]
    best = {start: 0.0}
    prev = {}
    while pq:
        cost, u = heapq.heappop(pq)
        if u == goal:
            break
        if cost > best.get(u, 1e18):
            continue
        for v, wt, d_km, days, sea in adj.get(u, []):
            nc = cost + wt
            if nc < best.get(v, 1e18):
                best[v] = nc
                prev[v] = (u, d_km, days, sea)
                heapq.heappush(pq, (nc, v))

    # Якщо графи раптом роз'єднані (рідкісний кейс) — прямий маршрут
    if goal not in prev and start != goal:
        d_km = max(1.0, direct_km * 1.25)
        sea = b1.get("feature") != b2.get("feature")
        spd = mc["sea_km"] if sea else mc["land_km"]
        path_edges = [(start, goal, d_km, d_km / spd, sea)]
    else:
        path_edges = []
        cur = goal
        while cur != start:
            u, d_km, days, sea = prev[cur]
            path_edges.append((u, cur, d_km, days, sea))
            cur = u
        path_edges.reverse()

    legs = []
    points = []
    route_states = set()
    route_markets = set()
    route_burgs = {b1_id, b2_id}
    has_sea = False
    has_land = False
    sea_km_total = 0.0
    total_km = 0.0
    total_days = 0.0

    for idx, (u, v, d_km, days, sea) in enumerate(path_edges):
        iu, iv = _node_info(u), _node_info(v)
        if idx == 0:
            points.append(dict(x=iu["x"], y=iu["y"], name=iu["name"], sea=False))
        points.append(dict(x=iv["x"], y=iv["y"], name=iv["name"], sea=bool(sea)))
        sid = iv["state"]
        route_states.add(iu["state"])
        route_states.add(iv["state"])
        route_markets.add(iu["market"])
        route_markets.add(iv["market"])
        total_km += d_km
        total_days += days
        if sea:
            has_sea = True
            sea_km_total += d_km
        else:
            has_land = True
        legs.append(dict(
            from_name=iu["name"], to_name=iv["name"],
            dist_km=round(d_km, 1), days=round(days, 1), sea=bool(sea),
            state_id=sid, state_uk=sim.sname(sid),
        ))

    # Вартість дороги з урахуванням цін на їжу
    food_avg = sum(sim.price_index("food", s) for s in route_states) / max(len(route_states), 1)
    sea_fare = (sea_km_total / 100.0) * 10000.0 * (1.2 if mode == "ship" else 1.0)
    cost_mm = int(round((total_days * mc["day_mm"] * (0.6 + 0.4 * food_avg)) + sea_fare))

    # Загрози та небезпека
    hazards = []
    danger = 6  # базова небезпека дикої дороги
    war_states = set()
    for wr in sim.w.get("wars", []):
        ws = set(wr["attackers"]) | set(wr["defenders"])
        hit = ws & route_states
        if hit:
            war_states |= hit
            hazards.append(f"Війна «{wr['name']}» зачіпає держави маршруту ({', '.join(sim.sname(s) for s in sorted(hit))}).")
    danger += min(50, 25 * len(war_states))

    t = sim.tick_index()
    for ep in sim.w.get("epidemics", []):
        m_hits = [mid for mid in ep.get("markets", {}) if mid in route_markets]
        if m_hits:
            danger += 25
            hazards.append(f"Епідемія «{ep['name']}» на ринках: {', '.join(sim.markets[mid]['uk'] for mid in m_hits)}.")

    hazard_keys = {
        "bandit_roads", "piracy_surge", "sea_storm", "harsh_winter",
        "monster_horde", "undead_incursion", "dragon_attack", "peasant_revolt",
    }
    state_names = {sim.sname(s) for s in route_states}
    market_names = {sim.markets[mid]["uk"] for mid in route_markets if mid in sim.markets}
    burg_names = {sim.bname(bid) for bid in route_burgs}
    all_target_names = state_names | market_names | burg_names
    seen_ev = set()
    for ev in sim.w.get("active_events", []):
        if ev.get("until", t + 1) <= t or ev.get("key") not in hazard_keys:
            continue
        tgt = ev.get("target")
        if tgt in all_target_names or any(s in route_states for s in (ev.get("states") or [])):
            sig = (ev["key"], tgt)
            if sig in seen_ev:
                continue
            seen_ev.add(sig)
            danger += 10 + 5 * int(ev.get("sev", 1))
            hazards.append(f"{ev['title']} ({tgt}): {ev['text']}")

    cold_max = max((E.season(sim.w["date"]["month"], sim.lat[bid])[1] for bid in (b1_id, b2_id)), default=0.0)
    if cold_max > 0.35:
        danger += 12
        hazards.append(f"Суворі зимові холоди ({LD.MONTHS_UK[sim.w['date']['month'] - 1]}): додатковий ризик замерзання та занесень.")

    danger = min(100, max(0, int(round(danger))))
    if danger >= 70:
        d_level = "Смертельно небезпечно"
    elif danger >= 45:
        d_level = "Небезпечно"
    elif danger >= 20:
        d_level = "Помірний ризик"
    else:
        d_level = "Безпечно"

    # Небезпека тепер має вагу: повільніший і дорожчий шлях, а не лише текст.
    risk_days = total_days * (1.0 + danger / 400.0)
    cost_mm = int(round(cost_mm * (1.0 + danger / 200.0)))

    # Зустрічі для D&D-сесії. Рівень небезпеки визначає, які саме три
    # зустрічі потраплять у підбірку — високий ризик витискає «тихі» варіанти.
    encounter_pool = []
    if war_states:
        encounter_pool.append("Військовий роз'їзд або загін дезертирів вимагає документи чи мито на переправі.")
    if has_sea:
        encounter_pool.append("Піратська шхуна чи морський змій переслідує судно на відкритій ділянці маршруту.")
    if any("нежит" in h.lower() or "монстр" in h.lower() or "дракон" in h.lower() for h in hazards):
        encounter_pool.append("Засідка потвор або нежиті біля покинутої застави / руїн уздовж шляху.")
    if any("епідем" in h.lower() for h in hazards):
        encounter_pool.append("Карантинний кордон вартових і натовп біженців перед міською брамою.")
    if has_land:
        encounter_pool.append("Зламаний купецький віз перекрив шлях; купці просять охорону до найближчого ринку.")
    if cold_max > 0.35:
        encounter_pool.append("Раптова хуртовина або зграя голодних вовків змушує шукати прихисток у заїзді.")
    fallbacks = [
        "Мандрівний трубадур або вісник гільдії ділиться свіжими чутками про ціни та інтриги сусідів.",
        "Дорожні розбійники влаштували хибний завал на тракті й очікують плату за проїзд.",
        "Загадковий караван алхіміків шукає провідника в обмін на знижку на зілля.",
    ]
    for fb in fallbacks:
        if fb not in encounter_pool:
            encounter_pool.append(fb)
    rotation = (danger // 20) % len(encounter_pool)
    encounters = [encounter_pool[(rotation + i) % len(encounter_pool)] for i in range(3)]

    return dict(
        from_id=b1_id, from_uk=b1["uk"], to_id=b2_id, to_uk=b2["uk"],
        mode=mode, mode_name=mc["name"],
        total_km=round(total_km, 1), total_days=round(risk_days, 1),
        cost_mm=cost_mm, cost_coins=fmt_mm(cost_mm),
        danger_score=danger, danger_level=d_level,
        legs=legs, hazards=hazards, encounters=encounters, points=points,
    )


def generate_quest_hooks(sim, state_id=None, limit=10, include_claimed=False, include_accepted=False):
    """Генерує пригодницькі квести й чутки для партії з поточних подій, війн, епідемій і дефіцитів."""
    try:
        sid_filter = int(state_id) if state_id not in (None, "", "all") else None
    except (TypeError, ValueError, OverflowError):
        sid_filter = None
    state_name_filter = sim.sname(sid_filter) if sid_filter is not None and sid_filter in sim.states else None
    t = sim.tick_index()
    hooks = []

    def _matches(ev_states, tgt_name):
        if sid_filter is None:
            return True
        if sid_filter in (ev_states or []):
            return True
        if tgt_name == state_name_filter:
            return True
        for bid in sim.state_burgs.get(sid_filter, []):
            b = sim.burgs[bid]
            if tgt_name in (b["uk"], sim.markets[b["market"]]["uk"]):
                return True
        return False

    def _gov_for_target(tgt_name, ev_states):
        for b in sim.burgs.values():
            if b["uk"] == tgt_name or sim.markets[b["market"]]["uk"] == tgt_name:
                pr = sim.provinces.get(b.get("province"))
                if pr and pr.get("governor"):
                    return f"{pr['governor']['name']} ({pr['uk']})"
        for sid in (ev_states or []):
            pids = sim.state_provinces.get(sid, [])
            if pids:
                pr = sim.provinces[pids[0]]
                if pr.get("governor"):
                    return f"{pr['governor']['name']} ({pr['uk']})"
        return None

    # 1. Активні події
    ev_patrons = {
        "mine_collapse": ("Гільдія рудокопів", "Економіка", "Врятувати заблокованих гірників та зачистити новий обвал тунелю"),
        "monster_horde": ("Міська рада та варта", "Бойовий", "Відбити набіг потвор на прикордонні села й знайти їхнє лігво"),
        "dungeon_breach": ("Магічна колегія", "Дослідження", "Запечатати розлом підземелля, звідки лізуть тварюки"),
        "dragon_attack": ("Королівський намісник", "Бойовий", "Вистежити дракона, що нищить хутори, або евакуювати скарбницю"),
        "undead_incursion": ("Орден Іконоборців", "Містика", "Знищити вогнище некромантії та врятувати біженців"),
        "piracy_surge": ("Ліга морських купців", "Морський", "Влаштувати пастку на піратську флотилію й повернути викрадений вантаж"),
        "bandit_roads": ("Купецька гільдія", "Охорона", "Провести караван небезпечним трактом та розгромити ватажка розбійників"),
        "black_rust": ("Ковальський цех", "Розслідування", "Знайти джерело прокляття «Чорної Іржі» та здобути захисний реагент"),
        "guild_strike": ("Магістрат міста", "Дипломатія", "Врегулювати суперечку між цехами та купецтвом або викрити провокаторів"),
        "noble_conspiracy": ("Таємна канцелярія", "Інтрига", "Викрити змовників при дворі, перш ніж почнеться заколот"),
        "peasant_revolt": ("Місцевий префект", "Дипломатія", "Домовитися з ватажками повстанців або приборкати бунт"),
    }
    for ev in sorted(sim.w.get("active_events", []), key=lambda x: -x.get("sev", 1)):
        if ev.get("until", t + 1) <= t:
            continue
        tgt = ev.get("target", "Світ")
        if not _matches(ev.get("states"), tgt):
            continue
        sev = int(ev.get("sev", 1))
        patron, cat, summary = ev_patrons.get(
            ev["key"], ("Місцева влада", "Пригода", f"Допомогти містянам подолати наслідки події «{ev['title']}»")
        )
        gov_patron = _gov_for_target(tgt, ev.get("states"))
        if gov_patron and ev["key"] in ("monster_horde", "dragon_attack", "undead_incursion", "peasant_revolt", "bandit_roads", "dungeon_breach"):
            patron = gov_patron
        reward_zm = 60 * sev + (40 if ev["key"] in ("dragon_attack", "undead_incursion", "black_rust") else 0)
        hooks.append(dict(
            title=f"{ev['title']}: {tgt}",
            category=cat,
            location=tgt,
            state_uk=tgt if any(st["uk"] == tgt for st in sim.states.values()) else "Регіон",
            patron=patron,
            reward=f"{reward_zm} зм",
            urgency=f"Ступінь {sev}",
            text=f"{summary}. Привід: {ev['text']}",
        ))

    # 1б. Облоги, окупація провінцій і змови нелояльних намісників
    for pid, pr in sim.provinces.items():
        sid = pr["state"]
        occ = pr.get("occupied_by")
        if sid_filter is not None and sid != sid_filter and occ != sid_filter:
            continue
        gov = pr.get("governor") or {}
        if pr.get("siege", 0.0) > 0:
            hooks.append(dict(
                title=f"Прорив облоги: {pr['uk']}",
                category="Війна",
                location=sim.bname(pr.get("burg")),
                state_uk=sim.sname(sid),
                patron=f"{gov.get('name', 'Комендант')} ({pr['uk']})",
                reward="180 зм",
                urgency=f"Облога {pr['siege']:.0f}%",
                text=f"Ворог тримає в облозі {sim.bname(pr.get('burg'))}, столицю провінції {pr['uk']}. Потрібен прорив блокади або вилазка проти облогової артилерії.",
            ))
        elif occ:
            hooks.append(dict(
                title=f"Підпілля в окупованій провінції {pr['uk']}",
                category="Війна",
                location=pr["uk"],
                state_uk=sim.sname(sid),
                patron=f"Лоялісти ({sim.sname(sid)})",
                reward="160 зм",
                urgency="Окупація",
                text=f"Провінція {pr['uk']} окупована силами {sim.sname(occ)}. Місцеві повстанці шукають допомоги для диверсії або порятунку полоненого намісника.",
            ))
        elif gov.get("loyalty", 70.0) < 35.0:
            hooks.append(dict(
                title=f"Змова намісника: {pr['uk']}",
                category="Інтрига",
                location=sim.bname(pr.get("burg")),
                state_uk=sim.sname(sid),
                patron=f"Таємна канцелярія ({sim.sname(sid)})",
                reward="130 зм",
                urgency=f"Лояльність {gov.get('loyalty', 0):.0f}%",
                text=f"{gov.get('name', 'Намісник')} підозрюється в сепаратизмі й таємних перемовинах. Партія може викрити змову — або стати на бік заколотників.",
            ))

    # 2. Війни
    for wr in sim.w.get("wars", []):
        ws = wr["attackers"] + wr["defenders"]
        if sid_filter is not None and sid_filter not in ws:
            continue
        a_uk = ", ".join(sim.sname(s) for s in wr["attackers"])
        d_uk = ", ".join(sim.sname(s) for s in wr["defenders"])
        hooks.append(dict(
            title=f"Військове доручення ({wr['name']})",
            category="Війна",
            location=d_uk,
            state_uk=a_uk,
            patron="Штаб війська / Контрабандисти",
            reward="150 зм + трофеї",
            urgency="Терміново",
            text=f"Між {a_uk} та {d_uk} точиться війна (рахунок {wr['score']:+.0f}). Потрібна розвідка тилу, визволення полонених або таємна доставка припасів.",
        ))

    # 3. Епідемії
    for ep in sim.w.get("epidemics", []):
        for mid in list(ep.get("markets", {}))[:3]:
            if mid not in sim.markets:
                continue
            ms = sim.market_state[mid]
            if sid_filter is not None and ms != sid_filter:
                continue
            hooks.append(dict(
                title=f"Карантин і ліки: {sim.markets[mid]['uk']}",
                category="Порятунок",
                location=sim.markets[mid]["uk"],
                state_uk=sim.sname(ms),
                patron="Орден цілителів / Магістрат",
                reward="120 зм",
                urgency="Висока",
                text=f"Спалах хвороби «{ep['name']}» на ринку {sim.markets[mid]['uk']}. Потрібно терміново доставити алхімічні інгредієнти або ізолювати носіїв.",
            ))

    # 4. Гострі товарні дефіцити
    scarcities = []
    for mid, m in sim.markets.items():
        ms = sim.market_state[mid]
        if sid_filter is not None and ms != sid_filter:
            continue
        for g, p in m.get("price", {}).items():
            base = max(sim.goods[g]["value"], 1.0)
            ratio = p / base
            if ratio >= 4.2 and sim.goods[g]["value"] >= 3:
                scarcities.append((ratio, mid, g, p))
    scarcities.sort(reverse=True)
    for ratio, mid, g, p in scarcities[:4]:
        g_uk = LD.good_uk(g, sim.goods)
        ms = sim.market_state[mid]
        hooks.append(dict(
            title=f"Контракт на доставку: {g_uk} → {sim.markets[mid]['uk']}",
            category="Торгівля",
            location=sim.markets[mid]["uk"],
            state_uk=sim.sname(ms),
            patron="Місцевий торговий дім",
            reward=f"{int(round(ratio * 25))} зм + % від прибутку",
            urgency=f"Ціна {int(ratio * 100)}%",
            text=f"Гострий дефіцит ресурсу «{g_uk}» на ринку {sim.markets[mid]['uk']} ({fmt_mm(p * _value_to_mm())} за {sim.goods[g]['unit']}). Торговці щедро платять за безпечний супровід партії.",
        ))

    if not hooks:
        hooks.append(dict(
            title="Супровід дипломатичної пошти",
            category="Подорож",
            location="Столиця",
            state_uk=state_name_filter or "Світ",
            patron="Канцелярія",
            reward="50 зм",
            urgency="Звичайна",
            text="Ситуація у світі відносно спокійна; гільдія пропонує оплачувану охорону кур'єра між сусідніми ринками.",
        ))

    # Прийняті квести більше не підміняються як свіжі пропозиції — дошка
    # активних справ доступна окремо. Повернути їх можна явним прагцем.
    board = sim.w.get("quests") or {}
    if not isinstance(board, dict):
        board = {}
    if include_accepted and isinstance(board.get("active"), list):
        for q in board["active"]:
            if not isinstance(q, dict):
                continue
            if sid_filter is not None and q.get("state_uk") not in (state_name_filter, "Світ"):
                continue
            hooks.insert(0, dict(q, accepted=True))

    for h in hooks:
        sig = "|".join(str(h.get(k, "")) for k in ("title", "category", "location", "patron"))
        h.setdefault("id", "q-" + hashlib.sha1(sig.encode("utf-8")).hexdigest()[:10])

    if not include_claimed:
        claimed = set()
        for key in ("claimed", "active", "completed", "expired"):
            for q in (board.get(key) or []):
                claimed.add(str(q.get("id")) if isinstance(q, dict) else str(q))
        hooks = [h for h in hooks if str(h.get("id")) not in claimed]
    return hooks[:limit]


def _quest_due(q, fallback):
    """Безпечно читає due_tick: бите/нечислове значення не ламає expiry."""
    try:
        v = q.get("due_tick", fallback) if isinstance(q, dict) else fallback
        if v is None or isinstance(v, bool):
            return fallback
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _due_offset(hook):
    """Термін виконання залежить від терміновості/ступеня квесту."""
    urg = str((hook or {}).get("urgency") or "").lower()
    m = re.search(r"\d+", urg)
    sev = int(m.group(0)) if m else 0
    span = max(6, 20 - 2 * sev) if sev else 18
    if any(k in urg for k in ("терміново", "висока", "облога", "окупація")):
        span = min(span, 12)
    elif "звичайна" in urg:
        span = max(span, 20)
    return max(3, min(60, span))


def _quest_store(sim):
    board = sim.w.get("quests")
    if not isinstance(board, dict):
        board = {}
        sim.w["quests"] = board
    for key in ("active", "completed", "expired", "claimed"):
        if not isinstance(board.get(key), list):
            board[key] = []
    try:
        board["next_id"] = int(board.get("next_id", 1))
    except (TypeError, ValueError, OverflowError):
        board["next_id"] = 1
    # Coerce due_tick once on load so every consumer sees a plain int.
    fallback = sim.tick_index() + 18
    for q in board["active"]:
        if isinstance(q, dict):
            q["due_tick"] = _quest_due(q, fallback)
    return board


def _reward_zm(text):
    """Парсить звичайні та групування суми: «120 зм», «1 200 зм», «1,200 зм»."""
    m = re.search(r"(\d+(?:[\s,\u00a0]\d+)*)\s*зм", str(text or ""), re.IGNORECASE)
    if not m:
        return 0
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else 0


def _state_id_by_uk(sim, uk):
    if uk in (None, "", "Світ", "Регіон"):
        return None
    for sid, st in sim.states.items():
        if st.get("uk") == uk or st.get("name") == uk:
            return sid
    return None


def accept_quest(sim, quest_id, state_id=None):
    """Бере квест із дошки в роботу; нагорода ще не виплачується."""
    board = _quest_store(sim)
    raw_id = str(quest_id)
    # Повторне прийняття будь-якого вже заявленого ID заборонено.
    for key in ("active", "completed", "expired"):
        for q in board[key]:
            if not isinstance(q, dict):
                continue
            if str(q.get("id")) == raw_id or str(q.get("quest_id")) == raw_id:
                return q if key == "active" else None
    if raw_id in {str(x) for x in board["claimed"]}:
        return None
    hook = next((h for h in generate_quest_hooks(sim, state_id, limit=200)
                 if str(h.get("id")) == raw_id), None)
    if hook is None:
        return None
    qid = int(board["next_id"])
    board["next_id"] = qid + 1
    tick = sim.tick_index()
    quest = dict(hook, quest_id=qid, accepted_tick=tick,
                 due_tick=tick + _due_offset(hook), status="active")
    board["active"].append(quest)
    board["claimed"].append(str(hook["id"]))
    sim.log("gm", f"Прийнято квест «{quest['title']}» (нагорода {quest.get('reward', '—')}).")
    return quest


def complete_quest(sim, quest_id, success=True):
    """Завершує квест і списує/виплачує нагороду з казни відповідної держави."""
    board = _quest_store(sim)
    quest = next((q for q in board["active"] if isinstance(q, dict) and
                  (str(q.get("id")) == str(quest_id) or str(q.get("quest_id")) == str(quest_id))), None)
    if quest is None:
        return None
    board["active"].remove(quest)
    sid = _state_id_by_uk(sim, quest.get("state_uk"))
    reward_zm = max(0, _reward_zm(quest.get("reward")))
    paid = 0.0
    if success and sid:
        try:
            available = max(0.0, float(sim.states[sid].get("treasury", 0.0)))
        except (TypeError, ValueError, OverflowError):
            available = 0.0
        paid = min(reward_zm, available)
        sim.states[sid]["treasury"] = available - paid
    note = ""
    if not success:
        note = "Нагороду не виплачено: квест провалено."
    elif not sid:
        note = "Нагороду не виплачено: державу-замовника не знайдено."
    out = dict(quest, status="completed" if success else "failed",
               completed_tick=sim.tick_index(), paid_zm=int(paid), payment_note=note)
    board["completed"].append(out)
    sim.log("gm", f"Квест «{quest['title']}»: {'успішно' if success else 'провал'}." +
            (f" Виплачено {int(paid)} зм." if paid else " Нагороди не виплачено."))
    return out


def expire_quests(sim):
    """Закриває прострочені квести; викликається ГМ або перед звітом."""
    board = _quest_store(sim)
    t = sim.tick_index()
    expired = [q for q in board["active"] if isinstance(q, dict) and _quest_due(q, t + 1) <= t]
    for q in expired:
        board["active"].remove(q)
        board["expired"].append(dict(q, status="expired", expired_tick=t))
        sim.log("gm", f"Термін квесту «{q.get('title', q.get('id', '—'))}» минув.")
    return len(expired)


def generate_npc(sim, state_id=None, role=None):
    """Генерує ім'я, риси та привід для NPC на основі лору й поточних подій."""
    sid = None
    if state_id not in (None, "", "all"):
        try:
            cand = int(state_id)
        except (TypeError, ValueError, OverflowError):
            cand = None
        if cand in sim.states:
            sid = cand
    st = sim.states.get(sid) if sid is not None else None
    culture = str((st or {}).get("culture") or "Generic")
    syllable_table = getattr(LD, "CULTURE_SYLLABLES", {}) or {}
    syllables = syllable_table.get(culture) or syllable_table.get("Generic")
    role_txt = role if isinstance(role, str) else ("" if role is None else str(role))
    role_txt = role_txt.strip()[:64]
    npcs = sim.w.get("npcs")
    if not isinstance(npcs, list):
        npcs = []
    # Кожен виклик у межах одного тіка має давати нового NPC.
    seed = (sim.w.get("meta") or {}).get("sim_seed", 1)
    rng = random.Random(f"{seed}-npc-{sim.tick_index()}-{sid}-{role_txt}-{len(npcs)}-{uuid.uuid4().hex[:8]}")
    if isinstance(syllables, (list, tuple)) and len(syllables) >= 2 and syllables[0] and syllables[1]:
        name = str(rng.choice(syllables[0])) + str(rng.choice(syllables[1]))
    else:
        name = "Мандрівник"
    name = name.strip()[:64] or "Мандрівник"
    roles = ["купець", "намісник", "лицар", "алхімік", "вісник", "розбійник", "жриця", "капітан"]
    role_out = role_txt or rng.choice(roles)
    traits = rng.sample(["дратливий", "завжди тримає слово", "борг гільдії", "таємний покровитель", "поранена рука",
                         "любить ризик", "підозрілий до чужинців", "має вплив при дворі"], 2)
    try:
        hooks = generate_quest_hooks(sim, sid, limit=5)
    except Exception:
        hooks = []
    hook = "Шукає роботу в найближчому місті"
    if hooks:
        picked = rng.choice(hooks)
        hook = str((picked.get("title") if isinstance(picked, dict) else picked) or hook)[:160]
    candidates = [g.get("name") for g in (sim.w.get("guilds") or []) if isinstance(g, dict)] or \
                 [x.get("uk") for x in sim.states.values() if isinstance(x, dict)] or ["Місцева громада"]
    candidates = [str(x).strip()[:80] for x in candidates if str(x or "").strip()]
    faction = rng.choice(candidates) if candidates else "Місцева громада"
    return dict(name=name, role=role_out, faction=faction, traits=traits, hook=hook,
                location=sim.sname(sid) if sid is not None else "Світ")
