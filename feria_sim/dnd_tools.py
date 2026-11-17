# -*- coding: utf-8 -*-
"""Прикладні інструменти для Майстра гри (D&D 5e): роздрібні ціни, маршрути подорожі, квестові гачки."""
import heapq
import math

from . import lore_data as LD
from . import engine as E
from . import politics as PO

COIN_NAMES = [("пм", 1_000_000), ("зм", 10_000), ("см", 100), ("мм", 1)]

RETAIL_CATEGORIES = [
    "Таверна та їжа",
    "Спорядження й побут",
    "Зброя та обладунки",
    "Транспорт і тварини",
    "Послуги та магія",
]

RETAIL_CATALOG = [
    # Таверна та їжа
    dict(id="ale_mug", name="Кухоль елю", cat="Таверна та їжа", base_mm=400, weights={67: 0.7, 9: 0.3}, rust=False),
    dict(id="wine_flask", name="Фляга вина", cat="Таверна та їжа", base_mm=2500, weights={13: 1.0}, rust=False),
    dict(id="inn_poor", name="Таверна: бідний обід і нічліг", cat="Таверна та їжа", base_mm=600, weights={9: 0.7, 34: 0.3}, rust=False),
    dict(id="inn_modest", name="Таверна: скромний постій", cat="Таверна та їжа", base_mm=2000, weights={9: 0.4, 10: 0.3, 67: 0.3}, rust=False),
    dict(id="inn_comf", name="Таверна: комфортний постій", cat="Таверна та їжа", base_mm=8000, weights={10: 0.4, 66: 0.3, 13: 0.3}, rust=False),
    dict(id="inn_wealthy", name="Таверна: багатий постій", cat="Таверна та їжа", base_mm=25000, weights={13: 0.4, 27: 0.3, 63: 0.3}, rust=False),
    dict(id="rations", name="Дорожній пайок (1 день)", cat="Таверна та їжа", base_mm=1500, weights={64: 0.6, 9: 0.4}, rust=False),
    # Спорядження й побут
    dict(id="torch_bundle", name="Факел (в'язка 5 шт.)", cat="Спорядження й побут", base_mm=100, weights={1: 0.6, 32: 0.4}, rust=False),
    dict(id="lamp_oil", name="Олія для ліхтаря (фляга)", cat="Спорядження й побут", base_mm=500, weights={35: 0.6, 37: 0.4}, rust=False),
    dict(id="rope_50", name="Мотузка конопляна (50 фт)", cat="Спорядження й побут", base_mm=1000, weights={48: 0.7, 21: 0.3}, rust=False),
    dict(id="artisan_tools", name="Набір ремісничих інструментів", cat="Спорядження й побут", base_mm=50000, weights={58: 0.8, 4: 0.2}, rust=True),
    dict(id="travel_clothes", name="Дорожній одяг і плащ", cat="Спорядження й побут", base_mm=15000, weights={45: 0.6, 54: 0.4}, rust=False),
    # Зброя та обладунки
    dict(id="spear_dagger", name="Спис або кинджал", cat="Зброя та обладунки", base_mm=10000, weights={59: 0.7, 1: 0.3}, rust=True),
    dict(id="longsword", name="Довгий меч / бойова сокира", cat="Зброя та обладунки", base_mm=120000, weights={59: 0.7, 4: 0.3}, rust=True),
    dict(id="longbow", name="Довгий лук і сагайдак (20 стріл)", cat="Зброя та обладунки", base_mm=180000, weights={1: 0.5, 59: 0.5}, rust=False),
    dict(id="leather_armor", name="Шкіряний обладунок", cat="Зброя та обладунки", base_mm=80000, weights={43: 0.8, 45: 0.2}, rust=False),
    dict(id="chain_mail", name="Кольчуга", cat="Зброя та обладунки", base_mm=550000, weights={59: 0.6, 4: 0.4}, rust=True),
    dict(id="plate_armor", name="Повний латний обладунок", cat="Зброя та обладунки", base_mm=4500000, weights={59: 0.7, 4: 0.3}, rust=True),
    # Транспорт і тварини
    dict(id="draft_horse", name="Тягловий кінь", cat="Транспорт і тварини", base_mm=250000, weights={18: 1.0}, rust=False),
    dict(id="warhorse", name="Бойовий / верховий кінь", cat="Транспорт і тварини", base_mm=650000, weights={18: 0.8, 55: 0.2}, rust=False),
    dict(id="wagon", name="Віз із упряжжю", cat="Транспорт і тварини", base_mm=150000, weights={1: 0.6, 55: 0.4}, rust=False),
    dict(id="ship_ticket", name="Квиток на корабель (за 100 км)", cat="Транспорт і тварини", base_mm=10000, weights={53: 0.6, 52: 0.4}, rust=False),
    # Послуги та магія
    dict(id="healing_potion", name="Зілля лікування (мале)", cat="Послуги та магія", base_mm=350000, weights={25: 0.4, 68: 0.3, 47: 0.3}, rust=False),
    dict(id="spell_scroll_1", name="Сувій закляття 1-го кола", cat="Послуги та магія", base_mm=250000, weights={49: 0.4, 50: 0.4, 51: 0.2}, rust=False),
    dict(id="guard_hire", name="Найм охоронця / провідника (доба)", cat="Послуги та магія", base_mm=10000, weights={9: 0.5, 59: 0.5}, rust=False),
    dict(id="forge_repair", name="Ремонт зброї чи обладунку в кузні", cat="Послуги та магія", base_mm=15000, weights={58: 0.6, 34: 0.4}, rust=True),
]

MODES = {
    "foot": dict(name="Пішки", land_km=36.0, sea_km=95.0, day_mm=1500),
    "wagon": dict(name="Обоз / віз", land_km=28.0, sea_km=90.0, day_mm=4500),
    "horse": dict(name="Верхи", land_km=55.0, sea_km=95.0, day_mm=8500),
    "ship": dict(name="Кораблем (морський пріоритет)", land_km=36.0, sea_km=115.0, day_mm=12000),
}


def fmt_mm(mm: float) -> str:
    """Форматує роздрібну вартість у монетах за курсом 1:100 (до 2 старших номіналів)."""
    val = int(round(mm))
    if val <= 0:
        return "0 мм"
    parts = []
    for name, size in COIN_NAMES:
        q, val = divmod(val, size)
        if q:
            parts.append(f"{q} {name}")
    return " ".join(parts[:2])


def _dist_km(sim, a, b):
    scale = float(sim.w.get("meta", {}).get("units", {}).get("distance", {}).get("scale", 3.0) or 3.0)
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"]) * scale


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
        items.append(dict(
            id=item["id"], name=item["name"], cat=item["cat"],
            base_mm=item["base_mm"], base_coins=fmt_mm(item["base_mm"]),
            mm=mm, coins=fmt_mm(mm), pct=pct, status=status,
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
        dist_km = max(float(e["dist"]), 1.0)
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

    # Зустрічі для D&D-сесії
    encounters = []
    if war_states:
        encounters.append("Військовий роз'їзд або загін дезертирів вимагає документи чи мито на переправі.")
    if has_sea:
        encounters.append("Піратська шхуна чи морський змій переслідує судно на відкритій ділянці маршруту.")
    if any("нежит" in h.lower() or "монстр" in h.lower() or "дракон" in h.lower() for h in hazards):
        encounters.append("Засідка потвор або нежиті біля покинутої застави / руїн уздовж шляху.")
    if any("епідем" in h.lower() for h in hazards):
        encounters.append("Карантинний кордон вартових і натовп біженців перед міською брамою.")
    if has_land and len(encounters) < 3:
        encounters.append("Зламаний купецький віз перекрив шлях; купці просять охорону до найближчого ринку.")
    if cold_max > 0.35 and len(encounters) < 3:
        encounters.append("Раптова хуртовина або зграя голодних вовків змушує шукати прихисток у заїзді.")
    fallbacks = [
        "Мандрівний трубадур або вісник гільдії ділиться свіжими чутками про ціни та інтриги сусідів.",
        "Дорожні розбійники влаштували хибний завал на тракті й очікують плату за проїзд.",
        "Загадковий караван алхіміків шукає провідника в обмін на знижку на зілля.",
    ]
    for fb in fallbacks:
        if len(encounters) >= 3:
            break
        if fb not in encounters:
            encounters.append(fb)

    return dict(
        from_id=b1_id, from_uk=b1["uk"], to_id=b2_id, to_uk=b2["uk"],
        mode=mode, mode_name=mc["name"],
        total_km=round(total_km, 1), total_days=round(total_days, 1),
        cost_mm=cost_mm, cost_coins=fmt_mm(cost_mm),
        danger_score=danger, danger_level=d_level,
        legs=legs, hazards=hazards, encounters=encounters[:3], points=points,
    )


def generate_quest_hooks(sim, state_id=None, limit=10):
    """Генерує пригодницькі квести й чутки для партії з поточних подій, війн, епідемій і дефіцитів."""
    sid_filter = int(state_id) if state_id not in (None, "", "all") else None
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
            text=f"Гострий дефіцит ресурсу «{g_uk}» на ринку {sim.markets[mid]['uk']} ({fmt_mm(p * LD.VALUE_TO_MM)} за {sim.goods[g]['unit']}). Торговці щедро платять за безпечний супровід партії.",
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
    return hooks[:limit]
