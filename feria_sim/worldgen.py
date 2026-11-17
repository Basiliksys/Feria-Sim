# -*- coding: utf-8 -*-
"""Допис світу: перетворює сирий імпорт .map на повний ігровий `world`.

Додає те, чого немає на карті: українські назви, правителів і риси, відносини
між державами, війни, гільдії, найманців, калібрування економіки та казни.
"""
import json
import os
import random
import re

from . import lore_data as LD
from . import engine as E

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


def _generate_generic_orgs(w, rng):
    """Генерує гільдії, найманців і ордени для довільної карти з Azgaar."""
    burgs = sorted(w["burgs"].values(), key=lambda b: -b["pop"])
    states = sorted(w["states"].values(), key=lambda s: -(s["urban_k"] + s["rural_k"]))
    templates = [
        ("g_iron", "Гільдія гірників і ковалів", "craft", [4, 34, 58, 59], "Видобуток заліза, вугілля та кузня."),
        ("g_grain", "Торговий союз землеробів", "food", [9, 10, 66, 67], "Постачання зерна, худоби та харчів."),
        ("g_sea", "Ліга морських купців", "maritime", [52, 53, 48, 27], "Морська торгівля, верфі та прянощі.", True),
        ("g_cloth", "Цех ткачів і кравців", "craft", [43, 44, 45, 54], "Виробництво сукна, одягу та взуття."),
        ("g_bank", "Міняйли та ювеліри", "finance", [7, 8, 62, 63], "Карбування монет і банківські векселі."),
        ("g_alch", "Колегія алхіміків і книгарів", "arcane", [33, 49, 50, 51, 60], "Книги, чорнила, скло та селітра."),
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
            state=hb["state"], goods=tpl[3], wealth=round(max(2000.0, hb["pop"] * 0.4), 1),
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
        return {}, {}
    worlds = overrides.get("worlds")
    if isinstance(worlds, dict):
        if world_name in worlds:
            src = worlds[world_name] or {}
            return src.get("states", {}), src.get("burgs", {})
        if not is_feria:
            return {}, {}
    if not is_feria and overrides.get("world_name") not in (None, world_name):
        return {}, {}
    if not is_feria and overrides and "world_name" not in overrides and "worlds" in overrides:
        return {}, {}
    return overrides.get("states", {}), overrides.get("burgs", {})


def build_world(imp, seed=1, overrides=None, start_year=None, era=None):
    rng = random.Random(seed)
    overrides = overrides or {}
    w = imp
    cultures = w["cultures"]
    start_year = int(LD.START_YEAR if start_year is None else start_year)
    era = LD.ERA_SHORT if era is None else era
    matched_known = sum(1 for st in w["states"].values() if st["name"] in LD.KNOWN_STATES)
    world_name = w["meta"].get("world_name", "Feria")
    is_feria = (world_name == "Feria") or (matched_known >= 3)
    ov_states, ov_burgs = _resolve_overrides(overrides, world_name, is_feria)

    # ---- міста
    for b in w["burgs"].values():
        ov_b = ov_burgs.get(str(b["id"]))
        ov_b_uk = ov_b.get("uk") if isinstance(ov_b, dict) else ov_b
        b["uk"] = ov_b_uk or LD.translit(b["name"])
        b["pop0"] = b["pop"] + b["rural"]
        b["sat"] = {}
    for m in w["markets"].values():
        m["name"] = w["burgs"][m["center"]]["name"]
        m["uk"] = w["burgs"][m["center"]]["uk"]
        m["capital"] = 0.0
        m["want"] = {}
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
    map_yr = w["meta"].get("map_year")
    if is_feria:
        shift = start_year - (map_yr or LD.MAP_YEAR)
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
    w["config"] = dict(
        per_capita={"food": 10.0, "utilities": 4.0, "construction": 1.5, "luxury": 0.8},
        craft_scale=1.0, transport_rate=0.012, birth=0.0042, death=0.0028,
        poll_k=1.0, mil_k=1.0, mil_goods_per_head=0.002, admin_share=0.2,
        event_rate=1.0, war_rate=1.0,
    )
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
def calibrate(sim, log=print, warm_iters=30, months_per=3):
    w = sim.w
    cfg = w["config"]
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
            sim.tick(politics=False, events=False, advance=False, finance=False)
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
        sim.tick(politics=False, events=False, advance=False, finance=False)
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
    for m in sim.markets.values():
        m["capital"] = 0.0


def _state_pop(sim, sid):
    return sum(sim.burgs[b]["pop"] + sim.burgs[b]["rural"] for b in sim.state_burgs.get(sid, []))
