# -*- coding: utf-8 -*-
"""Генератор подій: природа, хвороби, економіка, політика, магія."""
import math

from . import lore_data as LD
from .engine import clamp
from . import politics as PO

SEV_WORD = {1: "помірна", 2: "серйозна", 3: "катастрофічна"}


def _wchoice(rng, items, weights):
    tot = sum(weights)
    if tot <= 0:
        return rng.choice(items)
    r = rng.random() * tot
    for it, wt in zip(items, weights):
        r -= wt
        if r <= 0:
            return it
    return items[-1]


def step_events(sim, rng):
    w = sim.w
    cfg = w["config"]
    t = sim.tick_index()
    w["active_events"] = [e for e in w.get("active_events", []) if e["until"] > t]
    step_epidemics(sim, rng)
    for key, spec in LD.EVENT_TABLE.items():
        p = spec["weight"] * 0.10 * cfg["event_rate"]
        if rng.random() < p:
            fire(sim, rng, key)


def fire(sim, rng, key, target=None, sev=None):
    spec = LD.EVENT_TABLE[key]
    sev = sev or rng.randint(*spec["sev"])
    dur = rng.randint(*spec["dur"]) if spec["dur"][1] else 0
    scope = spec["scope"]
    tgt = target if target is not None else pick_target(sim, rng, key, scope)
    if tgt is None:
        return None
    fn = HANDLERS.get(key)
    if not fn:
        return None
    return fn(sim, rng, tgt, sev, dur)


def pick_target(sim, rng, key, scope):
    states = list(sim.states)
    if scope == "state":
        wts = []
        for s in states:
            st = sim.states[s]
            wt = math.sqrt(max(sim.acc["pop"].get(s, st.get("pop_cache", 1)), 1))
            if key in ("undead_incursion", "monster_horde", "black_rust") and st["continent"] == "Кірос":
                wt *= 3.5
            if key == "black_rust" and st["name"] == "Galg":
                wt *= 4.0
            if key in ("peasant_revolt", "coup", "noble_conspiracy", "succession_crisis"):
                wt *= (1.6 - st["stability"] / 100.0) ** 2
            wts.append(wt)
        return _wchoice(rng, states, wts)
    if scope == "market":
        ids = list(sim.markets)
        if key in ("sea_storm", "piracy_surge"):
            ids = [m for m in ids if sim.burgs[sim.markets[m]["center"]]["port"]] or ids
        return rng.choice(ids)
    if scope == "burg":
        ids = list(sim.burgs)
        wts = [math.sqrt(sim.burgs[b]["pop"]) * (1.3 if key in ("dungeon_breach", "dragon_attack") else 1) for b in ids]
        return _wchoice(rng, ids, wts)
    if scope == "marker":
        vol = [m for m in sim.w["markers"] if "volcan" in m["type"].lower()]
        return rng.choice(vol) if vol else None
    if scope == "pair":
        a = _wchoice(rng, states, [1.0] * len(states))
        nb = [n for n in sim.states[a]["neighbors"] if n in sim.states]
        if not nb:
            return None
        return (a, rng.choice(nb))
    if scope == "edge":
        return rng.randrange(len(sim.edges))
    return None


def _record(sim, key, scope, target_name, sev, dur, text, states=None, **kw):
    t = sim.tick_index()
    if dur:
        sim.w.setdefault("active_events", []).append(dict(key=key, title=LD.EVENT_TITLES[key], target=target_name,
                                                          sev=sev, until=t + dur, text=text))
    sim.log("event", text, event=key, sev=sev, states=states or [], **kw)


# ---------------------------------------------------------------- хендлери
def h_drought(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_agri", 1 - 0.12 * sev, dur, "drought")
    text = f"{SEV_WORD[sev].capitalize()} посуха в державі {sim.sname(s)}: врожаї впадуть на {int(12*sev)} % ({dur} міс.)."
    _record(sim, "drought", "state", sim.sname(s), sev, dur, text, [s])


def h_flood(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_agri", 1 - 0.09 * sev, dur, "flood")
    sim.add_mod("state", s, "rebuild", 1 + 0.5 * sev, dur + 3, "flood")
    sim.add_mod("state", s, "mort", 0.0006 * sev, dur, "flood", kind="add")
    _record(sim, "flood", "state", sim.sname(s), sev, dur,
            f"Повінь у державі {sim.sname(s)} ({SEV_WORD[sev]}): знищені поля й мости, зростає попит на будматеріали.", [s])


def h_bumper(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_agri", 1 + 0.12 * sev, dur, "bumper")
    _record(sim, "bumper_harvest", "state", sim.sname(s), sev, dur,
            f"Рясний врожай у державі {sim.sname(s)}: ціни на їжу підуть донизу.", [s])


def h_locusts(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_agri", 1 - 0.17 * sev, dur, "locusts")
    sim.add_mod("state", s, "stab", -1.5 * sev, dur, "locusts", kind="add")
    _record(sim, "locusts", "state", sim.sname(s), sev, dur, f"Нашестя сарани в державі {sim.sname(s)}: поля спустошені.", [s])


def h_winter(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "util_need", 1 + 0.3 * sev, dur, "winter")
    sim.add_mod("state", s, "mort", 0.0008 * sev, dur, "winter", kind="add")
    sim.add_mod("state", s, "prod_agri", 1 - 0.05 * sev, dur, "winter")
    _record(sim, "harsh_winter", "state", sim.sname(s), sev, dur,
            f"Люта зима в державі {sim.sname(s)}: різко зростає попит на паливо й одяг.", [s])


def h_storm(sim, rng, mid, sev, dur):
    sim.add_mod("market", mid, "trade", 1 - 0.25 * sev, dur, "storm")
    m = sim.markets[mid]
    for g in (11, 37, 53):
        m["stock"][g] = m["stock"].get(g, 0.0) * (1 - 0.06 * sev)
    sid = sim.market_state[mid]
    _record(sim, "sea_storm", "market", m["uk"], sev, dur,
            f"Морська буря біля порту {m['uk']} ({sim.sname(sid)}): судна затримані, торгівля сповільнюється.", [sid])


def h_quake(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    b["pop"] *= 1 - 0.02 * sev
    sim.add_mod("burg", bid, "prod_all", 1 - 0.12 * sev, dur, "quake")
    sim.add_mod("burg", bid, "rebuild", 1 + 1.2 * sev, dur + 4, "quake")
    sim.add_mod("burg", bid, "mort", 0.002 * sev, 3, "quake", kind="add")
    _record(sim, "earthquake", "burg", sim.bname(bid), sev, dur,
            f"Землетрус у місті {sim.bname(bid)} ({sim.sname(b['state'])}): {SEV_WORD[sev]} руйнування.", [b["state"]], burg=bid)


def h_volcano(sim, rng, mk, sev, dur):
    near = [bid for bid, b in sim.burgs.items() if (b["x"] - mk["x"]) ** 2 + (b["y"] - mk["y"]) ** 2 < 60 ** 2]
    for bid in near:
        sim.add_mod("burg", bid, "prod_all", 1 - 0.18 * sev, dur, "volcano")
        sim.add_mod("burg", bid, "mort", 0.001 * sev, dur, "volcano", kind="add")
    sid = mk["state"]
    sim.add_mod("state", sid, "prod_agri", 1 - 0.07 * sev, dur, "ash")
    _record(sim, "volcano", "marker", mk["name"], sev, dur,
            f"Виверження вулкана {mk['name']}: попіл накрив {len(near)} міст держави {sim.sname(sid)}.", [sid])


def h_wildfire(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    m = sim.markets[b["market"]]
    m["stock"][1] = m["stock"].get(1, 0.0) * (1 - 0.25 * sev)
    sim.add_mod("burg", bid, "prod_all", 1 - 0.1 * sev, dur, "fire")
    sim.add_mod("burg", bid, "rebuild", 1 + 0.8 * sev, dur + 3, "fire")
    _record(sim, "wildfire", "burg", sim.bname(bid), sev, dur,
            f"Велика пожежа у {sim.bname(bid)} ({sim.sname(b['state'])}): згоріли склади деревини.", [b["state"]], burg=bid)


def h_plague(sim, rng, mid, sev, dur):
    t = sim.tick_index()
    eps = sim.w.setdefault("epidemics", [])
    if len(eps) >= 2:
        return None
    imm = sim.w.setdefault("market_immunity", {})
    if imm.get(mid, -1) > t or any(mid in ep.get("markets", {}) for ep in eps):
        cand = [m for m in sim.markets if imm.get(m, -1) <= t and all(m not in ep.get("markets", {}) for ep in eps)]
        if not cand:
            return None
        mid = rng.choice(cand)
    max_mk = 3 + sev * 3
    ep = dict(
        id=int(sim.w.get("_ep_seq", 0)) + 1,
        sev=sev,
        markets={mid: 0.85},
        visited=[mid],
        max_markets=max_mk,
        name=rng.choice(["Сіра пошесть", "Червоний кашель", "Чорна лихоманка", "Жовта волога", "Пошесть Трьох Місяців"]),
        start=t,
        end=t + dur + 2,
    )
    sim.w["_ep_seq"] = ep["id"]
    eps.append(ep)
    imm[mid] = t + dur + 24
    m = sim.markets[mid]
    sid = sim.market_state[mid]
    _record(sim, "plague", "market", m["uk"], sev, dur,
            f"У {m['uk']} ({sim.sname(sid)}) спалахнула епідемія «{ep['name']}» ({SEV_WORD[sev]}).", [sid], market=mid)


def step_epidemics(sim, rng):
    w = sim.w
    t = sim.tick_index()
    imm = w.setdefault("market_immunity", {})
    for k in [k for k, until in imm.items() if until <= t]:
        del imm[k]
    eps = w.get("epidemics", [])
    for ep in list(eps):
        if t > ep.get("end", t) + 4:
            eps.remove(ep)
            sim.log("disease", f"Епідемія «{ep['name']}» згасла.", sev=1)
            continue
        visited = set(ep.get("visited") or ep["markets"].keys())
        max_mk = int(ep.get("max_markets", 3 + ep.get("sev", 2) * 3))
        new = {}
        for mid, inten in list(ep["markets"].items()):
            if mid not in sim.markets:
                continue
            m = sim.markets[mid]
            sim.add_mod("market", mid, "mort", 0.0012 * ep["sev"] * inten, 1, "plague", kind="add")
            sim.add_mod("market", mid, "trade", 1 - 0.20 * inten, 1, "quarantine")
            if t < ep["end"] and inten >= 0.30 and (len(visited) + len(new)) < max_mk:
                for ei in m["edges"]:
                    if (len(visited) + len(new)) >= max_mk:
                        break
                    e = sim.edges[ei]
                    other = e["b"] if e["a"] == mid else e["a"]
                    if other in ep["markets"] or other in new or other in visited or imm.get(other, -1) > t:
                        continue
                    if sim.at_war(sim.market_state[mid], sim.market_state[other]):
                        continue
                    flow_f = clamp(math.log1p(max(e.get("flow", 0.0), 0.0)) / 10.0, 0.15, 0.85)
                    sea_f = 0.45 if e.get("sea") else 1.0
                    if rng.random() < 0.055 * inten * flow_f * sea_f:
                        new[other] = round(inten * 0.65, 3)
                        visited.add(other)
                        imm[other] = t + 24
                        sim.log("disease", f"Епідемія «{ep['name']}» дісталася {sim.markets[other]['uk']}.", market=other,
                                states=[sim.market_state[other]], sev=2)
            ep["markets"][mid] = inten * (0.72 if t < ep["end"] else 0.45)
        ep["markets"].update(new)
        ep["visited"] = list(visited)
        ep["markets"] = {k: v for k, v in ep["markets"].items() if v > 0.10}
        if not ep["markets"]:
            eps.remove(ep)
            sim.log("disease", f"Епідемія «{ep['name']}» згасла.", sev=1)


def h_murrain(sim, rng, s, sev, dur):
    for g in (10, 30, 18):
        sim.add_mod("state", s, f"prod_g{g}", 1 - 0.2 * sev, dur, "murrain")
    _record(sim, "cattle_murrain", "state", sim.sname(s), sev, dur,
            f"Мор худоби в державі {sim.sname(s)}: дорожчають м'ясо, шкіра, коні.", [s])


def h_goldrush(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    if 8 not in b["raw"]:
        b["raw"][8] = 0.4
    sim.add_mod("burg", bid, "prod_g8", 1 + 0.7 * sev, dur, "goldrush")
    sim.add_mod("burg", bid, "pop_growth", 1.5, dur, "goldrush")
    _record(sim, "gold_rush", "burg", sim.bname(bid), sev, dur,
            f"Золота лихоманка біля {sim.bname(bid)} ({sim.sname(b['state'])}): старателі стікаються до нових розсипів.",
            [b["state"]], burg=bid)


def h_mine(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    for g in (4, 5, 6, 7, 8, 2, 34):
        sim.add_mod("burg", bid, f"prod_g{g}", 1 - 0.3 * sev, dur, "mine")
    sim.add_mod("burg", bid, "mort", 0.001 * sev, 2, "mine", kind="add")
    _record(sim, "mine_collapse", "burg", sim.bname(bid), sev, dur,
            f"Обвал у копальнях {sim.bname(bid)} ({sim.sname(b['state'])}): видобуток руди зупинено.", [b["state"]], burg=bid)


def h_piracy(sim, rng, mid, sev, dur):
    m = sim.markets[mid]
    cnt = 0
    for ei in m["edges"]:
        if sim.edges[ei]["sea"]:
            sim.add_mod("edge", ei, "piracy", 1 - 0.28 * sev, dur, "piracy")
            cnt += 1
    sid = sim.market_state[mid]
    _record(sim, "piracy_surge", "market", m["uk"], sev, dur,
            f"Сплеск піратства біля {m['uk']} ({sim.sname(sid)}): під ударом {cnt} морських маршрутів.", [sid], market=mid)


def h_bandits(sim, rng, s, sev, dur):
    for mid in [m for m, st in sim.market_state.items() if st == s]:
        sim.add_mod("market", mid, "trade", 1 - 0.14 * sev, dur, "bandits")
    _record(sim, "bandit_roads", "state", sim.sname(s), sev, dur,
            f"Розбійники на шляхах держави {sim.sname(s)}: купці вимагають ескорту, торгівля сповільнюється.", [s])


def h_panic(sim, rng, mid, sev, dur):
    m = sim.markets[mid]
    gs = rng.sample(list(sim.goods), 3)
    for g in gs:
        sim.add_mod("market", mid, f"price_g{g}", 1 + 0.4 * sev, dur, "panic")
    sid = sim.market_state[mid]
    _record(sim, "market_panic", "market", m["uk"], sev, dur,
            f"Паніка на ринку {m['uk']}: скупка ({', '.join(LD.good_uk(g, sim.goods) for g in gs)}) розганяє ціни.", [sid], market=mid)


def h_strike(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    sim.add_mod("burg", bid, "prod_all", 1 - 0.3 * sev, dur, "strike")
    _record(sim, "guild_strike", "burg", sim.bname(bid), sev, dur,
            f"Ремісники {sim.bname(bid)} ({sim.sname(b['state'])}) оголосили страйк.", [b["state"]], burg=bid)


def h_boom(sim, rng, mid, sev, dur):
    m = sim.markets[mid]
    sim.add_mod("market", mid, "trade", 1 + 0.3 * sev, dur, "boom")
    sid = sim.market_state[mid]
    sim.states[sid]["income_once"] = sim.states[sid].get("income_once", 0.0) + sim.states[sid]["rev0"] * 0.05 * sev
    _record(sim, "trade_boom", "market", m["uk"], sev, dur, f"Торговий бум на ринку {m['uk']} ({sim.sname(sid)}).", [sid], market=mid)


def h_tech(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_all", 1 + 0.03 * sev, dur, "tech")
    sim.states[s]["tech"] = round(sim.states[s]["tech"] * (1 + 0.02 * sev), 3)
    _record(sim, "tech_advance", "state", sim.sname(s), sev, dur,
            f"Майстри держави {sim.sname(s)} зробили відкриття: зростає продуктивність ремесел.", [s])


def h_caravan(sim, rng, ei, sev, dur):
    e = sim.edges[ei]
    sim.add_mod("edge", ei, "trade", 0.4, dur, "caravan")
    a, b = sim.markets[e["a"]], sim.markets[e["b"]]
    _record(sim, "caravan_lost", "edge", f"{a['uk']}–{b['uk']}", sev, dur,
            f"Пограбовано великий караван між {a['uk']} та {b['uk']}.", [sim.market_state[e["a"]], sim.market_state[e["b"]]])


def h_succession(sim, rng, s, sev, dur):
    st = sim.states[s]
    sim.add_mod("state", s, "stab", -3 * sev, dur, "succession", kind="add")
    st["legitimacy"] = clamp(st["legitimacy"] - 6 * sev, 10, 100)
    _record(sim, "succession_crisis", "state", st["uk"], sev, dur, f"Криза престолонаслідування в державі {st['uk']}.", [s])


def h_conspiracy(sim, rng, s, sev, dur):
    st = sim.states[s]
    sim.add_mod("state", s, "stab", -2 * sev, dur, "conspiracy", kind="add")
    _record(sim, "noble_conspiracy", "state", st["uk"], sev, dur, f"Змова знаті в державі {st['uk']} загрожує двору.", [s])
    if sev == 3 and rng.random() < 0.3:
        fire(sim, rng, "coup", target=s, sev=2)


def h_revolt(sim, rng, s, sev, dur):
    st = sim.states[s]
    bl = sim.state_burgs.get(s, [])
    if not bl:
        return None
    for bid in rng.sample(bl, min(len(bl), 2 + sev)):
        sim.add_mod("burg", bid, "prod_all", 1 - 0.1 * sev, dur, "revolt")
    sim.add_mod("state", s, "stab", -2 * sev, dur, "revolt", kind="add")
    for u in st["army"]:
        st["army"][u] = int(st["army"][u] * (1 - 0.02 * sev))
    _record(sim, "peasant_revolt", "state", st["uk"], sev, dur, f"Селянський заколот у державі {st['uk']} ({SEV_WORD[sev]}).", [s])
    if sev == 3 and st["stability"] < 35 and len(bl) > 4 and rng.random() < 0.4:
        cands = [b for b in bl if not sim.burgs[b]["capital"]]
        if cands:
            secede(sim, rng, rng.choice(cands))


def secede(sim, rng, bid):
    w = sim.w
    b = sim.burgs[bid]
    old = b["state"]
    so = sim.states[old]
    nid = max(sim.states) + 1
    name = f"Вільне місто {b['uk']}"
    ns = dict(so)
    ns.update(id=nid, name=f"Free {b['name']}", full_name=f"Free City of {b['name']}", uk=name, prefix_uk="Вільне місто",
              capital=bid, neighbors=[old], army={"infantry": 400, "archers": 200}, army0={"infantry": 400, "archers": 200},
              treasury=so["rev0"] * 0.1, debt=0.0, stability=55.0, legitimacy=60.0, war_exhaustion=0.0, truce={}, mercs=[],
              diplo_labels={}, known=False, form="Republic", ruler=dict(name="Міська рада", age=None, traits=["mercantile", "cautious"], collective=True),
              rev0=max(so["rev0"] * 0.02, 1.0), army_cost=so["army_cost"], campaigns=[], income_once=0.0)
    ns["pop_cache"] = b["pop"] + b["rural"]
    w["states"][nid] = ns
    sim.states = w["states"]
    b["state"] = nid
    so["neighbors"] = so["neighbors"] + [nid]
    for s2 in sim.states:
        if s2 != nid:
            rel = -60 if s2 == old else rng.uniform(-10, 20)
            lo, hi = min(s2, nid), max(s2, nid)
            w["relations"].setdefault(lo, {})[hi] = rel
    sim.refresh_ownership()
    PO.war_pairs(sim)
    sim.log("politics", f"{b['uk']} відокремилась від {so['uk']} і проголосила себе вільним містом!", states=[old, nid], sev=3)


def h_wedding(sim, rng, pair, sev, dur):
    a, b = pair
    PO.rel_add(sim, a, b, 22)
    sim.log("politics", f"Династичний шлюб між домами {sim.sname(a)} і {sim.sname(b)} зміцнює їхні відносини.", states=[a, b], sev=1, event="royal_wedding")


def h_incident(sim, rng, pair, sev, dur):
    a, b = pair
    PO.rel_add(sim, a, b, -7 * sev)
    sim.log("politics", f"Прикордонний інцидент між {sim.sname(a)} і {sim.sname(b)} загострює напруженість.", states=[a, b], sev=sev, event="border_incident")


def h_embargo(sim, rng, pair, sev, dur):
    a, b = pair
    key = (min(a, b), max(a, b))
    sim.add_mod("pair", key, "embargo", 0.1, dur, "embargo")
    PO.rel_add(sim, a, b, -10)
    _record(sim, "trade_embargo", "pair", f"{sim.sname(a)}–{sim.sname(b)}", sev, dur,
            f"{sim.sname(a)} запроваджує торгове ембарго проти {sim.sname(b)} на {dur} міс.", [a, b])


def h_taxreform(sim, rng, s, sev, dur):
    st = sim.states[s]
    up = rng.random() < 0.5
    if up:
        st["tax_mult"] = clamp(st["tax_mult"] * 1.12, 0.6, 1.6)
        sim.add_mod("state", s, "stab", -2.0, 6, "taxreform", kind="add")
        txt = f"{st['uk']} підвищує податки (+12 %): казна зросте, невдоволення також."
    else:
        st["tax_mult"] = clamp(st["tax_mult"] * 0.9, 0.6, 1.6)
        sim.add_mod("state", s, "stab", 2.0, 6, "taxreform", kind="add")
        txt = f"{st['uk']} знижує податки (−10 %): населення полегшено зітхає."
    sim.log("politics", txt, state=s, states=[s], sev=1, event="tax_reform")


def h_coup(sim, rng, s, sev, dur):
    st = sim.states[s]
    r = st["ruler"]
    if not r["collective"]:
        from .worldgen import _make_name
        title = r["name"].split(" ")[0]
        r["name"] = f"{title} {_make_name(rng, st['culture_name'])}"
        r["age"] = rng.randint(24, 55)
    r["traits"] = rng.sample(LD.RANDOM_TRAIT_POOL, 2)
    st["legitimacy"] = clamp(st["legitimacy"] - 15, 5, 100)
    sim.add_mod("state", s, "stab", -5, dur, "coup", kind="add")
    _record(sim, "coup", "state", st["uk"], sev, dur, f"Державний переворот у {st['uk']}! До влади прийшов {r['name']}.", [s])


def _army_hit(sim, s, f):
    for u in sim.states[s]["army"]:
        sim.states[s]["army"][u] = int(sim.states[s]["army"][u] * (1 - f))


def h_horde(sim, rng, s, sev, dur):
    bl = sim.state_burgs.get(s, [])
    for bid in rng.sample(bl, min(len(bl), 1 + sev)) if bl else []:
        sim.add_mod("burg", bid, "prod_all", 1 - 0.12 * sev, dur, "horde")
        sim.add_mod("burg", bid, "mort", 0.0012 * sev, dur, "horde", kind="add")
    _army_hit(sim, s, 0.015 * sev)
    _record(sim, "monster_horde", "state", sim.sname(s), sev, dur,
            f"Орда монстрів вийшла з пустищ у державі {sim.sname(s)}; авантюристів кличуть на допомогу.", [s])


def h_breach(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    sim.add_mod("burg", bid, "prod_all", 1 - 0.1 * sev, dur, "breach")
    sim.add_mod("burg", bid, "mort", 0.001 * sev, dur, "breach", kind="add")
    loot = rng.random() < 0.3
    if loot:
        sim.states[b["state"]]["income_once"] = sim.states[b["state"]].get("income_once", 0.0) + sim.states[b["state"]]["rev0"] * 0.04 * sev
    _record(sim, "dungeon_breach", "burg", sim.bname(bid), sev, dur,
            f"Прорив підземелля поблизу {sim.bname(bid)} ({sim.sname(b['state'])})" + ("; здобичі вистачить, щоб поповнити казну." if loot else "."),
            [b["state"]], burg=bid)


def h_dragon(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    b["pop"] *= 1 - 0.03 * sev
    sim.add_mod("burg", bid, "prod_all", 0.5, dur, "dragon")
    sim.add_mod("state", b["state"], "stab", -1.5 * sev, dur, "dragon", kind="add")
    colour = rng.choice(["червоний", "синій", "зелений", "чорний", "білий"])
    _record(sim, "dragon_attack", "burg", sim.bname(bid), sev, dur,
            f"{colour.capitalize()} дракон напав на {sim.bname(bid)} ({sim.sname(b['state'])}): виробництво паралізоване.",
            [b["state"]], burg=bid)


def h_mana(sim, rng, s, sev, dur):
    good = rng.random() < 0.6
    if good:
        sim.add_mod("state", s, "prod_all", 1 + 0.04 * sev, dur, "mana")
        txt = f"Сплеск мани над державою {sim.sname(s)}: магічні ремесла процвітають."
    else:
        sim.add_mod("state", s, "prod_all", 1 - 0.05 * sev, dur, "mana")
        sim.add_mod("state", s, "stab", -1.0 * sev, dur, "mana", kind="add")
        txt = f"Нестабільний сплеск мани в державі {sim.sname(s)}: аномалії зривають роботу майстерень."
    _record(sim, "mana_surge", "state", sim.sname(s), sev, dur, txt, [s])


def h_artifact(sim, rng, s, sev, dur):
    st = sim.states[s]
    st["income_once"] = st.get("income_once", 0.0) + st["rev0"] * 0.5
    st["legitimacy"] = clamp(st["legitimacy"] + 6, 0, 100)
    sim.log("magic", f"У державі {st['uk']} знайдено стародавній артефакт; двір отримав престиж і скарб.", states=[s], sev=2, event="artifact_found")


def h_undead(sim, rng, s, sev, dur):
    bl = sim.state_burgs.get(s, [])
    for bid in rng.sample(bl, min(len(bl), 1 + sev)) if bl else []:
        sim.add_mod("burg", bid, "prod_all", 1 - 0.1 * sev, dur, "undead")
        sim.add_mod("burg", bid, "mort", 0.0015 * sev, dur, "undead", kind="add")
    _army_hit(sim, s, 0.02 * sev)
    _record(sim, "undead_incursion", "state", sim.sname(s), sev, dur,
            f"Вторгнення нежиті в державі {sim.sname(s)}; Іконоборці й гарнізони тримають оборону.", [s])


def h_tower(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_all", 1 + 0.03 * sev, dur, "tower")
    sim.states[s]["tech"] = round(sim.states[s]["tech"] * (1 + 0.03 * sev), 3)
    _record(sim, "tower_breakthrough", "state", sim.sname(s), sev, dur,
            f"Магічна башта держави {sim.sname(s)} зробила прорив: зростають продуктивність і військова міць.", [s])


def h_black_rust(sim, rng, s, sev, dur):
    for g in (4, 58, 59, 61):
        sim.add_mod("state", s, f"prod_g{g}", 1 - 0.18 * sev, dur, "black_rust")
    sim.add_mod("state", s, "prod_all", 1 - 0.06 * sev, dur, "black_rust")
    _record(sim, "black_rust", "state", sim.sname(s), sev, dur,
            f"Спалах прокляття «Чорної Іржі» в державі {sim.sname(s)}: залізо, зброя та інструменти швидко псуються.", [s])


HANDLERS = {
    "drought": h_drought, "flood": h_flood, "bumper_harvest": h_bumper, "locusts": h_locusts, "harsh_winter": h_winter,
    "sea_storm": h_storm, "earthquake": h_quake, "volcano": h_volcano, "wildfire": h_wildfire, "plague": h_plague,
    "cattle_murrain": h_murrain, "gold_rush": h_goldrush, "mine_collapse": h_mine, "piracy_surge": h_piracy,
    "bandit_roads": h_bandits, "market_panic": h_panic, "guild_strike": h_strike, "trade_boom": h_boom,
    "tech_advance": h_tech, "caravan_lost": h_caravan, "succession_crisis": h_succession, "noble_conspiracy": h_conspiracy,
    "peasant_revolt": h_revolt, "royal_wedding": h_wedding, "border_incident": h_incident, "trade_embargo": h_embargo,
    "tax_reform": h_taxreform, "coup": h_coup, "monster_horde": h_horde, "dungeon_breach": h_breach,
    "dragon_attack": h_dragon, "mana_surge": h_mana, "artifact_found": h_artifact, "undead_incursion": h_undead,
    "tower_breakthrough": h_tower, "black_rust": h_black_rust,
}
