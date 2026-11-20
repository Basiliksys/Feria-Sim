# -*- coding: utf-8 -*-
"""Фінанси держав, дипломатія, війни, найманці та сценарій Походу на Кірос."""
import collections
import math
import random

from . import lore_data as LD
from .engine import clamp

UNIT_POWER = {"infantry": 1.0, "archers": 1.0, "cavalry": 2.0, "artillery": 12.0, "fleet": 50.0}
LAND_WEIGHT = {"fleet": 0.35}
REL_LABELS = [(75, "Ally"), (40, "Friendly"), (-10, "Neutral"), (-35, "Suspicion"), (-65, "Rival"), (-1000, "Enemy")]

# Резервні імена товарів для старих збережень, де LD.GOOD_IDS ще немає.
# Ідентифікатори збігаються з полем `i` у goods_default.json (1-базові).
_GOOD_FALLBACK = {
    "wood": 1, "stone": 2, "marble": 3, "iron": 4, "copper": 5, "tin": 6,
    "silver": 7, "gold": 8, "grain": 9, "cattle": 10, "fish": 11, "game": 12,
    "horses": 18, "elephants": 19, "sheep": 30, "whales": 37, "tools": 58,
    "arms": 59, "artillery": 61, "sails": 52, "ships": 53, "barrels": 56,
    "preserved food": 64, "oil": 35,
}


def _finite_num(value, default=0.0):
    """Повертає скінченне число або безпечне значення за замовчуванням."""
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return f if math.isfinite(f) else default


def _finite_int(value, default=0, lo=None, hi=None):
    iv = int(_finite_num(value, default))
    if lo is not None:
        iv = max(lo, iv)
    if hi is not None:
        iv = min(hi, iv)
    return iv


def get_cfg(sim, key, default):
    """Читає ключ конфігурації, підтримуючи новий `sim.cfg` і старі словники."""
    fn = getattr(sim, "cfg", None)
    if callable(fn):
        try:
            return fn(key, default)
        except TypeError:
            # Старий callable може не приймати значення за замовчуванням.
            try:
                return fn(key)
            except TypeError:
                pass
    config = sim.w.get("config", {})
    return config.get(key, default) if isinstance(config, dict) else default


def good_id(name, fallback=None):
    """Стабільний id товару з LD.GOOD_IDS або резервне число."""
    if fallback is None:
        fallback = _GOOD_FALLBACK.get(str(name).strip().lower())
    table = getattr(LD, "GOOD_IDS", None)
    if isinstance(table, dict) and table:
        keys = (name, str(name), str(name).strip(), str(name).strip().lower(),
                str(name).strip().upper(), str(name).strip().lower().replace(" ", "_"),
                str(name).strip().lower().replace(" ", ""))
        for k in keys:
            if k in table:
                try:
                    return int(table[k])
                except (TypeError, ValueError):
                    return table[k]
    return fallback


def tech_cap(sim):
    raw = _finite_num(get_cfg(sim, "tech_cap", 3.0), 3.0)
    if not math.isfinite(raw) or raw <= 0.0:
        return 3.0
    return clamp(raw, 1.0, 100.0)


def clamp_tech(sim, value):
    t = _finite_num(value, 1.0)
    if not math.isfinite(t) or t <= 0.0:
        t = 1.0
    return clamp(t, 1.0, tech_cap(sim))


def decay_tech(sim, st):
    """М’який щомісячний дрейд технологій до 1.0 з урахуванням стелі."""
    rate = _finite_num(get_cfg(sim, "tech_decay", 0.002), 0.002)
    if not math.isfinite(rate) or rate < 0.0:
        rate = 0.002
    rate = clamp(rate, 0.0, 0.25)
    t = _finite_num(st.get("tech", 1.0), 1.0)
    if not math.isfinite(t) or t <= 0.0:
        t = 1.0
    st["tech"] = round(clamp_tech(sim, 1.0 + (t - 1.0) * (1.0 - rate)), 4)


def truce_until(sim, a, b):
    """Термін дії перемир’я між двома державами (враховує обидва напрямки)."""
    tick = sim.tick_index()
    ta = sim.states.get(a, {}).get("truce", {}).get(b, -1)
    tb = sim.states.get(b, {}).get("truce", {}).get(a, -1)
    return max(ta, tb) if ta > tick or tb > tick else -1


def truce_active(sim, a, b):
    return truce_until(sim, a, b) > sim.tick_index()


def ruler_trait_mod(st, key):
    """Добуток відповідних рис правителя (для under-the-hood множників)."""
    val = 1.0
    for t in st.get("ruler", {}).get("traits", []):
        raw = LD.RULER_TRAITS.get(t, {}).get(key, 1.0)
        if isinstance(raw, (int, float)):
            val *= float(raw) ** 0.5
    return val


def _safe_mod(sim, scope, sid, key, default=1.0):
    """Модифікатор без NaN/inf (наслідки подій не ламають похідні поля)."""
    value = _finite_num(sim.mm(scope, sid, key), default)
    return value if math.isfinite(value) and abs(value) < 1e6 else default


def sync_ruler_fields(sim):
    """Оновлює похідні поля держави від рис правителя та модифікаторів подій."""
    for sid, st in sim.states.items():
        base = _finite_num(ruler_trait_mod(st, "trade"), 1.0)
        if not math.isfinite(base):
            base = 1.0
        # Події можуть змінювати торгівлю/мита через модифікатори; не перезаписуємо їх.
        trade = clamp(base * _safe_mod(sim, "state", sid, "trade"), 0.65, 1.5)
        tariff = clamp(trade * _safe_mod(sim, "state", sid, "tariff"), 0.75, 1.35)
        st["trade_mod"] = round(trade, 4)
        st["tariff_mod"] = round(tariff, 4)
        st["war_power"] = round(clamp(_finite_num(ruler_trait_mod(st, "war"), 1.0), 0.6, 1.6), 4)


def rel_get(sim, a, b):
    if a == b:
        return 0.0
    row = sim.w["relations"].get(min(a, b))
    if not isinstance(row, dict):
        return 0.0
    value = _finite_num(row.get(max(a, b), 0.0), 0.0)
    return value if math.isfinite(value) else 0.0


def rel_add(sim, a, b, v):
    lo, hi = min(a, b), max(a, b)
    r = sim.w["relations"].setdefault(lo, {})
    if not isinstance(r, dict):
        r = sim.w["relations"][lo] = {}
    delta = _finite_num(v, 0.0)
    old = _finite_num(r.get(hi, 0.0), 0.0)
    if not math.isfinite(delta):
        delta = 0.0
    if not math.isfinite(old):
        old = 0.0
    r[hi] = clamp(old + delta, -100.0, 100.0)


def rel_label(score):
    for th, lab in REL_LABELS:
        if score >= th:
            return lab
    return "Enemy"


def state_power(sim, sid, land=True):
    st = sim.states[sid]
    p = 0.0
    for u, n in st["army"].items():
        p += n * UNIT_POWER.get(u, 1.0) * (LAND_WEIGHT.get(u, 1.0) if land else 1.0)
    for mc in st.get("mercs", []):
        p += mc["size"] * UNIT_POWER.get(mc["unit"], 1.0)
    for o in sim.w["orders"]:
        if o["state"] == sid:
            p += o["strength"] * UNIT_POWER.get(o["unit"], 1.0)
    q = st["readiness"] * st["tech"] * (0.6 + 0.4 * st["stability"] / 100.0) \
        * st.get("war_power", 1.0) * sim.mm("state", sid, "war_power")
    return p * q


def heads(st):
    return sum(st["army"].values()) + sum(m["size"] for m in st.get("mercs", []))


def war_pairs(sim):
    """Перебудовує кеш пар воюючих і узгоджує persisted-лічильник воєн."""
    pairs = set()
    seq = _finite_int(sim.w.get("_war_seq", 0), 0)
    for wr in sim.w.get("wars", []):
        if not isinstance(wr, dict):
            continue
        wid = _finite_int(wr.get("id", 0), 0)
        wr["id"] = wid
        seq = max(seq, wid)
        for a in wr.get("attackers", []) or []:
            for d in wr.get("defenders", []) or []:
                pairs.add((min(a, d), max(a, d)))
    sim.w["_war_seq"] = seq
    sim.w["war_pairs"] = pairs
    return pairs


def in_war(sim, sid):
    return [wr for wr in sim.w["wars"] if sid in wr["attackers"] or sid in wr["defenders"]]


# ---------------------------------------------------------------------------
# Фінанси
# ---------------------------------------------------------------------------
def step_finance(sim, rng):
    w = sim.w
    cfg = w["config"]
    tick = sim.tick_index()
    war_pairs(sim)
    # Одноразові надходження споживаємо лише в першому фінансовому кроці місяця.
    first_finance = w.get("_finance_tick") != tick
    w["_finance_tick"] = tick
    cr = w["crusade"]
    sync_ruler_fields(sim)
    invest_rate = clamp(float(get_cfg(sim, "guild_invest_rate", 0.02)), 0.0, 0.25)

    # Розрахунок податкового коефіцієнта намісників та воєнної частки окупованих провінцій
    gov_tax_k = {}
    free_pop_share = {}
    occ_loot = collections.Counter()
    for sid, st in sim.states.items():
        pids = sim.state_provinces.get(sid, [])
        if not pids:
            gov_tax_k[sid] = 1.0
            free_pop_share[sid] = 1.0
            continue
        tot_p = 0.0
        free_p = 0.0
        w_tax = 0.0
        pop_est = max(sim.acc["pop"].get(sid, st.get("pop_cache", 0)), 1.0)
        base_poll = cfg["poll_k"] * st["poll_tax"] * pop_est / 1000.0 / 12.0
        for pid in pids:
            pr = sim.provinces.get(pid)
            if not pr:
                continue
            pp = sum(sim.burgs[bid]["pop"] + sim.burgs[bid]["rural"]
                     for bid in pr.get("burgs", []) if bid in sim.burgs) or 1.0
            tot_p += pp
            occ = pr.get("occupied_by")
            if occ and occ in sim.states:
                occ_loot[occ] += base_poll * (pp / max(pop_est, 1.0)) * 0.40
            else:
                free_p += pp
                gt = 1.0
                gov = pr.get("governor") or {}
                for tr_k in gov.get("traits", []):
                    gt *= LD.GOVERNOR_TRAITS.get(tr_k, {}).get("tax", 1.0)
                if gov.get("loyalty", 70.0) < 35.0:
                    gt *= 0.70
                w_tax += pp * gt
        free_pop_share[sid] = free_p / tot_p if tot_p > 0 else 1.0
        gov_tax_k[sid] = (w_tax / free_p) if free_p > 0 else 1.0

    for sid, st in sim.states.items():
        pop = sim.acc["pop"].get(sid, st.get("pop_cache", 0))
        tr = 1.0
        for t in st["ruler"]["traits"]:
            tr *= LD.RULER_TRAITS.get(t, {}).get("tax", 1.0) ** 0.5
        gp = LD.GOV_PARAMS.get(st["form"], LD.GOV_PARAMS["Monarchy"])
        tax_norm = float(gp.get("tax_norm", 1.0) or 1.0)
        tm = st["tax_mult"] * sim.mm("state", sid, "tax") * tr * gov_tax_k.get(sid, 1.0) / tax_norm
        fshare = free_pop_share.get(sid, 1.0)
        poll = cfg["poll_k"] * st["poll_tax"] * pop / 1000.0 / 12.0 * tm * fshare
        sales = sim.acc["sales"].get(sid, 0.0) * tm * (0.4 + 0.6 * fshare)
        tariff = sim.acc["tariff"].get(sid, 0.0)
        once = _finite_num(st.get("income_once", 0.0), 0.0)
        if first_finance:
            st["income_once"] = 0.0
        extra = once + occ_loot.get(sid, 0.0)
        rev = poll + sales + tariff + extra
        upkeep = st["army_cost"] * sum(n * UNIT_POWER.get(u, 1.0) for u, n in st["army"].items())
        merc_fee = 0.0
        for mc in list(st.get("mercs", [])):
            fee = mc["size"] * mc["fee"] * (st["rev0"] / max(sum(st["army0"].values()), 1)) * 0.25
            merc_fee += fee
            if tick >= mc["until"]:
                st["mercs"].remove(mc)
                sim.log("military", f"Контракт найманців «{mc['name']}» з державою {st['uk']} завершено.", state=sid)
        admin = cfg["admin_share"] * st["rev0"] * (pop / max(st.get("pop_cache", pop), 1.0))
        # військове постачання з ринку столиці
        spent_goods = 0.0
        cap_burg = sim.burgs.get(st["capital"])
        if cap_burg:
            mk = sim.markets[cap_burg["market"]]
            need = heads(st) * cfg["mil_goods_per_head"] * (1.0 + 0.6 * bool(in_war(sim, sid)))
            got = 0.0
            lst = sorted(((mk["price"].get(g, sim.goods[g]["value"]) / sim.goods[g]["cover"]["military"], g)
                          for g in sim.cat_goods["military"]))
            remaining = need
            for _, g in lst:
                if remaining <= 1e-9:
                    break
                cv = sim.goods[g]["cover"]["military"]
                q = min(remaining / cv, mk["stock"].get(g, 0.0) * 0.5)
                if q <= 0:
                    continue
                mk["stock"][g] -= q
                spent_goods += q * mk["price"].get(g, sim.goods[g]["value"])
                remaining -= q * cv
                got += q * cv
                mk.setdefault("want", {})[g] = mk["want"].get(g, 0.0) + q
            if remaining > 1e-9 and lst:
                for _, g in lst[:3]:
                    mk.setdefault("want", {})[g] = mk["want"].get(g, 0.0) + remaining / 3 / sim.goods[g]["cover"]["military"]
            ratio = got / need if need > 0 else 1.0
            st["readiness"] = clamp(0.8 * st["readiness"] + 0.2 * (0.55 + 0.5 * ratio), 0.35, 1.15)
        # ордени теж коштують утримання — не безкоштовна вічна армія
        order_upkeep = sum(o["strength"] * UNIT_POWER.get(o["unit"], 1.0) * 0.00004
                           for o in w.get("orders", []) if o.get("state") == sid)
        exp = upkeep + merc_fee + admin + spent_goods + order_upkeep
        st["rev"], st["exp"] = round(rev, 2), round(exp, 2)
        st["income_breakdown"] = dict(poll=round(poll, 1), sales=round(sales, 1), tariff=round(tariff, 1),
                                      upkeep=round(upkeep, 1), admin=round(admin, 1), goods=round(spent_goods, 1),
                                      mercs=round(merc_fee, 1), orders=round(order_upkeep, 2), guild_loan=0.0)
        st["treasury"] += rev - exp
        if st["treasury"] < 0:
            st["debt"] += -st["treasury"]
            st["treasury"] = 0.0
        elif st["debt"] > 0 and st["treasury"] > st["rev0"] * 2:
            pay = min(st["debt"], st["treasury"] * 0.3)
            st["debt"] -= pay
            st["treasury"] -= pay
        st["debt"] *= 1.0 + 0.10 / 12.0
        # гільдії реально кредитують заборговані держави зі свого гаманця
        if st["debt"] > 0 and w.get("guilds"):
            lender = max(w["guilds"], key=lambda g: g.get("wealth", 0.0))
            loan = min(st["debt"], max(0.0, lender.get("wealth", 0.0)) * invest_rate, st["rev0"] * 0.25)
            if loan > 0.01:
                lender["wealth"] = max(0.0, lender.get("wealth", 0.0) - loan)
                st["treasury"] += loan
                st["debt"] -= loan
                st["income_breakdown"]["guild_loan"] = round(loan, 2)
                sim.log("finance", f"Гільдія «{lender['name']}» позичила {LD.fmt_coins(loan)} державі {st['uk']} "
                        f"під боргову заборгованість.", state=sid, guild=lender.get("id"), sev=1)
        if st["debt"] > st["rev0"] * 4 and order_upkeep > 0:
            for o in w.get("orders", []):
                if o.get("state") == sid and o.get("strength", 0) > 0:
                    o["strength"] = max(0, int(o["strength"] * 0.998))
        if st["debt"] > st["rev0"] * 8 and heads(st) > 0:       # режим жорсткої економії
            for u in st["army"]:
                st["army"][u] = int(st["army"][u] * 0.98)
            sim.add_mod("state", sid, "stab", -1.5, 2, "austerity", kind="add")
    # доходи гільдій з торгових потоків + пасивні інвестиції в ринковий капітал
    for g in w["guilds"]:
        mk = sim.markets.get(g.get("market"))
        if mk is None:
            continue
        share = mk.get("capital", 0.0)
        g["wealth"] += share * 0.02 * g["power"] + 0.002 * g["wealth"]
        inv = max(0.0, g.get("wealth", 0.0) * invest_rate)
        g["wealth"] -= inv
        mk["capital"] = mk.get("capital", 0.0) + inv
    # комісія від ємності ринку / природний відтік капіталу
    for m in sim.markets.values():
        m["capital"] = m.get("capital", 0.0) * 0.96


# ---------------------------------------------------------------------------
# Політика
# ---------------------------------------------------------------------------
def step_politics(sim, rng):
    w = sim.w
    tick = sim.tick_index()
    pairs = war_pairs(sim)
    _ensure_valid_capitals(sim)
    sync_ruler_fields(sim)
    for st in sim.states.values():
        decay_tech(sim, st)
    step_alert(sim, rng)
    step_diplomacy(sim, rng)
    step_stability(sim, rng)
    step_governors(sim, rng)
    step_army_recovery(sim, rng)
    step_wars(sim, rng)
    step_declarations(sim, rng)
    step_mercs(sim, rng)
    step_crusade(sim, rng)
    step_rulers(sim, rng)


def step_alert(sim, rng):
    """Тривога падає в мирний час і зростає від воєн та активних подій."""
    w = sim.w
    events = w.get("active_events", [])
    for sid, st in sim.states.items():
        alert = float(st.get("alert", 1.0) or 1.0)
        wars = bool(in_war(sim, sid))
        ev_press = sum(0.02 * float(e.get("sev", 1) or 1) for e in events if sid in (e.get("states") or []))
        target = 0.65 if not wars else 1.8
        target += ev_press
        speed = 0.10 if (wars or ev_press) else 0.04
        st["alert"] = round(clamp(alert + speed * (target - alert), 0.4, 3.0), 3)


def step_governors(sim, rng):
    w = sim.w
    new_year = (w["date"]["month"] == 1)
    gov_pool = list(LD.GOVERNOR_TRAITS)
    for pid, pr in sim.provinces.items():
        sid = pr["state"]
        st = sim.states.get(sid)
        if not st:
            continue
        if pr.get("assimilation", 0) > 0:
            pr["assimilation"] = max(0, pr["assimilation"] - 1)
            if pr["assimilation"] <= 0 and pr.get("core_state") != sid:
                pr["core_state"] = sid
                for bid in pr.get("burgs", []):
                    if bid in sim.burgs:
                        sim.burgs[bid]["core_state"] = sid
                sim.log("politics", f"Провінція {pr['uk']} остаточно інтегрована до складу {st['uk']}; "
                        "старі претензії на неї згасають.", state=sid, sev=1)
        gov = pr.get("governor")
        if not gov:
            continue
        base = (
            40.0
            + 0.35 * st["stability"]
            + 0.25 * st["legitimacy"]
            + 15.0 * (st["food_sat"] - 0.9)
            - 18.0 * max(0.0, st["tax_mult"] - 1.1)
            - (18.0 if pr.get("core_state", sid) != sid else 0.0)
            - 0.3 * pr.get("assimilation", 0)
        )
        drift = sum(LD.GOVERNOR_TRAITS.get(tr, {}).get("loyalty_drift", 0.0) for tr in gov.get("traits", []))
        gov["loyalty"] = round(clamp(gov.get("loyalty", 70.0) + 0.08 * (base - gov.get("loyalty", 70.0)) + drift, 0.0, 100.0), 1)
        if gov["loyalty"] < 24.0 and not pr.get("occupied_by") and rng.random() < 0.015:
            cb_id = pr.get("burg")
            if cb_id in sim.burgs:
                sim.add_mod("burg", cb_id, "prod_all", 0.75, 4, "gov_revolt")
            sim.log("unrest", f"Саботаж у провінції {pr['uk']} ({st['uk']}): намісник {gov['name']} відмовляється коритися короні!",
                    state=sid, sev=2)
        if new_year:
            gov["age"] = gov.get("age", 40) + 1
            p_die = max(0.0, (gov["age"] - 56) * 0.005) + 0.002
            if rng.random() < p_die:
                from .worldgen import _make_name
                old_name = gov["name"]
                title = LD.GOVERNOR_TITLE.get(pr.get("form_uk", "Провінція"), "Намісник")
                cb = sim.burgs.get(pr.get("burg"))
                cult = sim.w["cultures"].get(cb.get("culture"), {}).get("name", st["culture_name"]) if cb else st["culture_name"]
                gov["name"] = f"{title} {_make_name(rng, cult)}"
                gov["age"] = rng.randint(24, 48)
                gov["traits"] = rng.sample(gov_pool, 2)
                gov["loyalty"] = round(rng.uniform(68.0, 90.0), 1)
                sim.log("politics", f"У провінції {pr['uk']} ({st['uk']}) змінився намісник після смерті {old_name}: призначено {gov['name']}.",
                        state=sid, sev=1)


def step_diplomacy(sim, rng):
    w = sim.w
    ids = sorted(sim.states)
    te = sim.acc["trade_edge"]
    try:
        drift = float(get_cfg(sim, "neighbor_drift", -0.03))
    except (TypeError, ValueError):
        drift = -0.03
    for i, a in enumerate(ids):
        sa = sim.states[a]
        for b in ids[i + 1:]:
            if truce_active(sim, a, b):
                continue
            old = rel_get(sim, a, b)
            if old == 0 and b not in sa["neighbors"] and te.get((a, b), 0) + te.get((b, a), 0) <= 0 and rng.random() < 0.9:
                continue
            sb = sim.states[b]
            # Relations mean-revert toward a mildly positive baseline. The old
            # weak pull (0.012) let shared religion/culture plus trade bonuses
            # pin neighbors at +60..+100 forever, which made AI war declarations
            # mathematically impossible (the score needs low relations).
            d = rng.gauss(0, 1.0) - old * 0.025
            if b in sa["neighbors"]:
                d += drift
            tv = te.get((a, b), 0) + te.get((b, a), 0)
            if tv > 0:
                d += min(1.2, math.log1p(tv) * 0.12)
            if sa["religion"] == sb["religion"]:
                d += 0.04
            if sa["culture"] == sb["culture"]:
                d += 0.03
            if (min(a, b), max(a, b)) in w["war_pairs"]:
                d -= 3.0
            d += sim.ma("pair", (a, b), "rel")
            new = clamp(old + d, -100, 100)
            lo, hi = a, b
            w["relations"].setdefault(lo, {})[hi] = new
            la, lb = rel_label(old), rel_label(new)
            if la != lb and (lb in ("Ally", "Enemy") or la in ("Ally",)):
                if lb == "Ally":
                    sim.log("diplomacy", f"{sa['uk']} і {sb['uk']} уклали союз.", states=[a, b])
                elif lb == "Enemy":
                    sim.log("diplomacy", f"Відносини {sa['uk']} і {sb['uk']} зруйновані: відкрита ворожнеча.", states=[a, b])
                elif la == "Ally":
                    sim.log("diplomacy", f"Союз {sa['uk']} і {sb['uk']} розірвано.", states=[a, b])


def step_stability(sim, rng):
    w = sim.w
    for sid, st in sim.states.items():
        gp = LD.GOV_PARAMS.get(st["form"], LD.GOV_PARAMS["Monarchy"])
        war_tol = float(gp.get("war_tolerance", 1.0) or 1.0)
        tax_norm = float(gp.get("tax_norm", 1.0) or 1.0)
        at_war = bool(in_war(sim, sid))
        st["war_exhaustion"] = clamp(st["war_exhaustion"] + (2.0 if at_war else -1.5), 0, 100)
        taxp = max(0.0, st["tax_mult"] * sim.mm("state", sid, "tax") / tax_norm - 1.15) * 12
        debt_pen = min(12.0, st["debt"] / max(st["rev0"], 1.0) * 1.5)
        target = gp["stab_base"] + 28 * (st["food_sat"] - 0.95) + 12 * (st["lux_sat"] - 0.8) \
            - (0.22 / max(war_tol, 0.4)) * st["war_exhaustion"] - taxp - debt_pen \
            + (st["legitimacy"] - 60) * 0.15 + sim.ma("state", sid, "stab")
        st["stability"] = clamp(st["stability"] + 0.12 * (target - st["stability"]), 0, 100)
        # Legitimacy follows a soft target tied to how well the state is run.
        # The old hard step (+0.05 above 60 stability, -0.08 below) pinned
        # legitimacy at the floor after a run of bad events: low legitimacy
        # lowered the stability target, which kept stability under 60, which
        # kept legitimacy falling — a one-way death spiral. A functioning
        # state now slowly rebuilds legitimacy; a failing one still loses it.
        leg_target = clamp(60.0 + 0.8 * (st["stability"] - 55.0), 10.0, 100.0)
        st["legitimacy"] = clamp(st["legitimacy"] + 0.03 * (leg_target - st["legitimacy"]), 10.0, 100.0)
        # виробничий розвиток: інвестиції відновлюють, нестабільність/борги з’їдають
        strain = max(0.0, (35.0 - st["stability"]) / 35.0) + min(1.0, st["debt"] / max(st["rev0"], 1.0) / 3.0)
        invest = st["treasury"] > st["rev0"] * 2.0 and st["stability"] > 55 and st["debt"] < st["rev0"]
        pd = float(st.get("prod_dev", 1.0) or 1.0)
        if strain > 0.4:
            pd = max(0.5, pd - 0.004 * strain)
        elif invest:
            pd = min(1.25, pd + 0.0035 * st.get("trade_mod", 1.0))
        elif pd > 1.0:
            pd = max(1.0, pd - 0.002)
        st["prod_dev"] = round(clamp(pd, 0.5, 1.25), 4)
        if st["stability"] < 28 and rng.random() < 0.03:
            lost = 0.04
            for u in st["army"]:
                st["army"][u] = int(st["army"][u] * (1 - lost))
            sim.add_mod("state", sid, "prod_all", 0.9, 5, "revolt")
            st["stability"] += 7
            sim.log("unrest", f"Хвилювання в державі {st['uk']}: бунти придушуються, армія втратила частину сил.",
                    state=sid, sev=2)


def step_army_recovery(sim, rng):
    try:
        rate = clamp(float(get_cfg(sim, "army_recovery_rate", 0.03)), 0.0, 0.25)
    except (TypeError, ValueError):
        rate = 0.03
    for sid, st in sim.states.items():
        if st["debt"] > st["rev0"] * 8:
            continue
        at_war = bool(in_war(sim, sid))
        for u, n0 in st["army0"].items():
            cur = st["army"].get(u, 0)
            target = n0 * (1.0 + 0.4 * max(0.0, st.get("alert", 1) - 1) * at_war)
            if cur < target:
                st["army"][u] = int(cur + min(target - cur, max(1.0, n0 * rate)))
        st["power"] = state_power(sim, sid)


def step_declarations(sim, rng):
    w = sim.w
    cfg = w["config"]
    tick = sim.tick_index()
    for sid, st in sim.states.items():
        if len(in_war(sim, sid)) >= 2 or st["stability"] < 30 or st["treasury"] < st["rev0"] * 1.5:
            continue
        wm = 1.0
        for t in st["ruler"]["traits"]:
            wm *= LD.RULER_TRAITS.get(t, {}).get("war", 1.0) ** 0.6
        p = 0.0016 * cfg["war_rate"] * wm * (max(st["expansionism"], 0.3) ** 0.7)
        if rng.random() > p:
            continue
        mine = state_power(sim, sid)
        best, bs = None, 0.0
        for t in st["neighbors"]:
            if t not in sim.states or t == sid:
                continue
            if truce_active(sim, sid, t) or in_war_between(sim, sid, t):
                continue
            if any([min(sid, t), max(sid, t)] == [min(a, b), max(a, b)] for a, b in w["vassals"]):
                continue
            rel = rel_get(sim, sid, t)
            rev_prov = next((sim.provinces[pid] for pid in sim.state_provinces.get(t, [])
                             if sim.provinces[pid].get("core_state") == sid), None)
            if rel > 55 and rev_prov is None:
                continue
            tp = state_power(sim, t)
            ratio = mine / max(tp, 1.0)
            if ratio < 0.8:
                continue
            sc = -rel / 100.0 * 1.2 + (min(ratio, 3) - 1) * 0.6 + (0.3 if st["religion"] != sim.states[t]["religion"] else 0) \
                + (0.55 if rev_prov is not None else 0.0) + rng.random() * 0.4 - 0.1
            if sc > bs:
                best, bs = (t, rev_prov), sc
        # The old 0.55 bar was unreachable at the friendly relations produced
        # by step_diplomacy, so only scripted "border incident" events ever
        # started a war. 0.30 lets a real power imbalance or genuine hostility
        # trigger one while still rejecting opportunistic declarations.
        if best is not None and bs > 0.30:
            tgt_sid, rev_prov = best
            cas = f"повернення корінної провінції {rev_prov['uk']}" if rev_prov else None
            declare_war(sim, sid, tgt_sid, rng, casus=cas)


def in_war_between(sim, a, b):
    return (min(a, b), max(a, b)) in sim.w["war_pairs"]


def _war_between(sim, a, b):
    """Повертає чинну війну між двома державами (або None)."""
    for wr in sim.w.get("wars", []):
        if not isinstance(wr, dict):
            continue
        att, dfn = wr.get("attackers") or [], wr.get("defenders") or []
        if (a in att and b in dfn) or (a in dfn and b in att):
            return wr
    return None


def declare_war(sim, a, d, rng, name=None, casus=None):
    w = sim.w
    if a not in sim.states or d not in sim.states or a == d:
        return None
    war_pairs(sim)
    existing = _war_between(sim, a, d)
    if existing is not None:
        return existing
    if truce_active(sim, a, d):
        return None
    sa, sd = sim.states[a], sim.states[d]
    tick = sim.tick_index()
    attackers, defenders = [a], [d]
    for s2, side, enemy in ((a, attackers, d), (d, defenders, a)):
        for o in sim.states:
            if o in (a, d) or o in attackers or o in defenders:
                continue
            rel = rel_get(sim, s2, o)
            vassal = [o, s2] in w["vassals"]
            rel_enemy = rel_get(sim, o, enemy)
            # Союзник не повинен мати чинного перемир'я чи війни з жодним лідером.
            if truce_active(sim, o, a) or truce_active(sim, o, d):
                continue
            if in_war_between(sim, o, a) or in_war_between(sim, o, d):
                continue
            if (rel >= 75 and rel_enemy < 20 and rng.random() < 0.5) or (vassal and rng.random() < 0.9):
                side.append(o)
    # не більш ніж по 3 союзники
    attackers, defenders = attackers[:4], defenders[:4]
    cas = casus or rng.choice(["суперечка за прикордонні землі", "образа посольства", "претензії на спадщину",
                               "боротьба за торгові шляхи", "релігійні розбіжності", "помста за набіги"])
    nm = name or f"Війна {sa['uk']} проти {sd['uk']}"
    seq = _finite_int(w.get("_war_seq", 0), 0) + 1
    used = {_finite_int(x.get("id", 0), 0) for x in w["wars"] if isinstance(x, dict)}
    while seq in used:
        seq += 1
    w["_war_seq"] = seq
    wr = dict(id=seq, name=nm, attackers=attackers, defenders=defenders,
              score=0.0, exhaustion=0.0, start_year=w["date"]["year"], start_month=w["date"]["month"],
              captured=[], log=[], casus=cas)
    w["wars"].append(wr)
    war_pairs(sim)
    for x in attackers:
        for y in defenders:
            rel_add(sim, x, y, -35)
    allies_a = ", ".join(sim.sname(x) for x in attackers[1:])
    allies_d = ", ".join(sim.sname(x) for x in defenders[1:])
    sim.log("war", f"{nm}: {sa['uk']} оголошує війну {sd['uk']} ({cas})."
            + (f" На боці агресора: {allies_a}." if allies_a else "")
            + (f" На боці захисника: {allies_d}." if allies_d else ""),
            states=attackers + defenders, war=wr["id"], sev=3)
    return wr


def side_power(sim, side, land=True):
    return sum(state_power(sim, s, land) for s in side)


def apply_losses(sim, side, frac_total, rng):
    """Втрати розподіляються між арміями, найманцями й орденами пропорційно силі."""
    pw = [(s, state_power(sim, s)) for s in side if s in sim.states]
    tot = sum(p for _, p in pw) or 1.0
    for s, p in pw:
        st = sim.states[s]
        f = clamp(frac_total * (p / tot) * len(side), 0, 0.05)
        for u in list(st["army"]):
            st["army"][u] = int(st["army"][u] * (1 - f))
        for mc in st.get("mercs", []):
            mc["size"] = max(0, int(mc.get("size", 0) * (1 - f)))
        for wm in sim.w.get("mercs", []):
            if wm.get("employer") == s:
                wm["size"] = max(0, int(wm.get("size", 0) * (1 - f)))
        for o in sim.w.get("orders", []):
            if o.get("state") == s:
                o["strength"] = max(0, int(o.get("strength", 0) * (1 - f)))
        st["war_exhaustion"] = clamp(st["war_exhaustion"] + f * 40, 0, 100)


def _sanitize_war(sim, wr):
    """Очищує поля війни; False = учасників немає, війну знімаємо."""
    for key in ("attackers", "defenders"):
        side = wr.get(key)
        side = side if isinstance(side, list) else []
        wr[key] = [s for s in side if s in sim.states]
    if not wr["attackers"] or not wr["defenders"]:
        return False
    s = _finite_num(wr.get("score", 0.0), 0.0)
    wr["score"] = clamp(s if math.isfinite(s) else 0.0, -100.0, 100.0)
    exh = _finite_num(wr.get("exhaustion", 0.0), 0.0)
    wr["exhaustion"] = max(0.0, exh if math.isfinite(exh) else 0.0)
    date = sim.w.get("date", {})
    year = _finite_int(date.get("year", LD.START_YEAR), LD.START_YEAR, 1, 9999)
    month = _finite_int(date.get("month", 1), 1, 1, 12)
    wr["start_year"] = _finite_int(wr.get("start_year", year), year, 1, 9999)
    wr["start_month"] = _finite_int(wr.get("start_month", month), month, 1, 12)
    for key in ("captured", "occupied_provs"):
        value = wr.get(key)
        wr[key] = [x for x in value if isinstance(x, (int, str))] if isinstance(value, list) else []
    return True


def step_wars(sim, rng):
    w = sim.w
    ended = []
    for wr in list(w["wars"]):
        if not isinstance(wr, dict):
            w["wars"].remove(wr)
            continue
        if not _sanitize_war(sim, wr):
            w["wars"].remove(wr)
            war_pairs(sim)
            continue
        pa = side_power(sim, wr["attackers"])
        pd = side_power(sim, wr["defenders"]) * 1.12
        ratio = pa / max(pa + pd, 1e-9)
        wr["score"] = clamp(wr["score"] + (ratio - 0.5) * 12.0 * (0.6 + 0.8 * rng.random()), -100, 100)
        # Менш асиметричні втрати: переможець також платить кров’ю.
        la = clamp(0.009 * (0.6 + 0.4 * math.sqrt(pd / max(pa, 1e-9))) * (0.6 + 0.6 * rng.random()), 0, 0.035)
        ld = clamp(0.009 * (0.6 + 0.4 * math.sqrt(pa / max(pd, 1e-9))) * (0.6 + 0.6 * rng.random()), 0, 0.035)
        apply_losses(sim, wr["attackers"], la, rng)
        apply_losses(sim, wr["defenders"], ld, rng)
        wr["exhaustion"] += 1.0
        # руйнування на фронті
        if rng.random() < 0.5:
            tgt = rng.choice(wr["defenders"] if wr["score"] > 0 else wr["attackers"])
            bl = sim.state_burgs.get(tgt, [])
            if bl:
                bid = rng.choice(bl)
                sim.add_mod("burg", bid, "prod_all", 0.8, 4, "war_dev")
                sim.add_mod("burg", bid, "mort", 0.002, 4, "war_dev", kind="add")
        # облоги й територіальний фронт по провінціях
        winner_att = wr["score"] > 18
        winner_def = wr["score"] < -18
        if (winner_att or winner_def) and rng.random() < 0.45:
            winners = wr["attackers"] if winner_att else wr["defenders"]
            losers = wr["defenders"] if winner_att else wr["attackers"]
            step_provincial_front(sim, wr, winners, losers, rng)
        # завершення
        s = wr["score"]
        months = (w["date"]["year"] - wr["start_year"]) * 12 + (w["date"]["month"] - wr["start_month"])
        lead_a, lead_d = wr["attackers"][0], wr["defenders"][0]
        exh = max(sim.states[lead_a]["war_exhaustion"], sim.states[lead_d]["war_exhaustion"])
        bankrupt = any(sim.states[x]["debt"] > sim.states[x]["rev0"] * 5 for x in (lead_a, lead_d))
        unocc_a = any(not sim.provinces[pid].get("occupied_by") for pid in sim.state_provinces.get(lead_a, []))
        unocc_d = any(not sim.provinces[pid].get("occupied_by") for pid in sim.state_provinces.get(lead_d, []))
        if months >= 36 or abs(s) >= 85 or exh > 88 or bankrupt or (months > 18 and rng.random() < 0.05) \
                or not sim.state_burgs.get(lead_d) or not sim.state_burgs.get(lead_a) \
                or (sim.state_provinces.get(lead_d) and not unocc_d) \
                or (sim.state_provinces.get(lead_a) and not unocc_a):
            ended.append(wr)
    for wr in ended:
        end_war(sim, wr, rng)
    if ended:
        war_pairs(sim)


def _ensure_valid_capitals(sim):
    for sid, st in sim.states.items():
        bl = [bid for bid in sim.state_burgs.get(sid, []) if bid in sim.burgs]
        if not bl:
            # Держава втратила останнє місто: stale-столицю треба зняти.
            cap_b = sim.burgs.get(st.get("capital"))
            if cap_b and cap_b.get("capital"):
                cap_b["capital"] = False
            st["capital"] = None
            st["extinct"] = True
            continue
        st["extinct"] = False
        cap_b = sim.burgs.get(st.get("capital"))
        if cap_b and cap_b.get("state") == sid:
            cap_b["capital"] = True
            continue
        if cap_b and cap_b.get("capital"):
            cap_b["capital"] = False
        new_cap = max((sim.burgs[bid] for bid in bl),
                      key=lambda x: (int(bool(x.get("walls"))), int(bool(x.get("citadel"))),
                                     _finite_num(x.get("pop", 0.0), 0.0)))
        new_cap["capital"] = True
        st["capital"] = new_cap["id"]
        sim.log("politics", f"{sim.sname(sid)} переносить столицю до {new_cap['uk']}.", state=sid, sev=2)
    # Не допускаємо двох столиць в одному місті після воєн/сецесій.
    for bid, b in sim.burgs.items():
        if not b.get("capital"):
            continue
        owner = sim.states.get(b["state"])
        if owner is not None and owner.get("capital") != bid:
            b["capital"] = False


def refresh_neighbors(sim):
    """Оновлює список прикордонних/сусідніх держав за фактичним розташуванням міст."""
    active_ids = [sid for sid, bl in sim.state_burgs.items() if bl]
    pts = {}
    for sid in active_ids:
        bs = [sim.burgs[bid] for bid in sim.state_burgs[sid]]
        if len(bs) > 40:
            bs = sorted(bs, key=lambda x: -x["pop"])[:40]
        pts[sid] = bs
    for sid in sim.states:
        if sid not in pts:
            sim.states[sid]["neighbors"] = []
            continue
        nbrs = set()
        for oid in active_ids:
            if oid == sid:
                continue
            d2 = min((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 for a in pts[sid] for b in pts[oid])
            if d2 <= 160000:
                nbrs.add(oid)
        sim.states[sid]["neighbors"] = sorted(nbrs)


def annex_province(sim, pid, new_owner, rng=None):
    pr = sim.provinces.get(pid)
    if not pr:
        return
    old_owner = pr["state"]
    pr["state"] = new_owner
    pr["occupied_by"] = None
    pr["siege"] = 0.0
    for bid in list(pr.get("burgs", [])):
        if bid in sim.burgs:
            b = sim.burgs[bid]
            b["state"] = new_owner
            b["occupied_by"] = None
            b["capital"] = False
    if new_owner != pr.get("core_state"):
        pr["assimilation"] = 36
        gov = pr.get("governor")
        if gov and gov.get("loyalty", 70) >= 25:
            from .worldgen import _make_name
            rng = rng or sim.rng
            title = LD.GOVERNOR_TITLE.get(pr.get("form_uk", "Провінція"), "Намісник")
            st_new = sim.states[new_owner]
            pr["governor"] = dict(
                name=f"{title} {_make_name(rng, st_new['culture_name'])}",
                age=rng.randint(26, 55),
                traits=rng.sample(list(LD.GOVERNOR_TRAITS), 2),
                loyalty=round(rng.uniform(72.0, 92.0), 1),
            )
    else:
        pr["assimilation"] = 0
        if pr.get("governor"):
            pr["governor"]["loyalty"] = clamp(pr["governor"].get("loyalty", 70.0) + 15.0, 0.0, 100.0)
    if old_owner != new_owner and old_owner in sim.states and new_owner in sim.states:
        sim.states[new_owner]["legitimacy"] = clamp(sim.states[new_owner]["legitimacy"] + 2.0, 0, 100)
        sim.states[old_owner]["legitimacy"] = clamp(sim.states[old_owner]["legitimacy"] - 3.5, 0, 100)


def step_provincial_front(sim, wr, winners=None, losers=None, rng=None):
    if rng is None and isinstance(winners, random.Random):
        rng = winners
        winners = losers = None
    if winners is None or losers is None:
        att_lead = wr["score"] >= 0
        winners = wr["attackers"] if att_lead else wr["defenders"]
        losers = wr["defenders"] if att_lead else wr["attackers"]
    rng = rng or sim.rng

    # 1) Першочергово звільняємо власні окуповані провінції переможців
    for s in winners:
        for pid in sim.state_provinces.get(s, []):
            pr = sim.provinces.get(pid)
            if pr and pr.get("occupied_by") in losers:
                pr["occupied_by"] = None
                pr["siege"] = 0.0
                for bid in pr.get("burgs", []):
                    if bid in sim.burgs:
                        sim.burgs[bid]["occupied_by"] = None
                sim.log("war", f"{wr['name']}: війська {sim.sname(winners[0])} звільняють провінцію {pr['uk']}!",
                        states=[s, winners[0]], war=wr["id"], sev=3)
                return

    # 2) Контрольовані переможцем міста (власні неокуповані або вже окуповані ним)
    own_cities = []
    for b in sim.burgs.values():
        ctrl = b.get("occupied_by") or b["state"]
        if ctrl in winners:
            own_cities.append(b)
    if not own_cities:
        return
    has_fleet = sum(sim.states[s]["army"].get("fleet", 0) for s in winners if s in sim.states) > 0
    has_port = any(b.get("port") for b in own_cities)
    has_artillery = sum(sim.states[s]["army"].get("artillery", 0) for s in winners if s in sim.states) > 0
    own_sample = rng.sample(own_cities, min(len(own_cities), 60))
    own_feats = {b.get("feature") for b in own_cities if b.get("feature") is not None}

    best_pr, best_score = None, 1e18
    for s in losers:
        if s not in sim.states:
            continue
        st_pids = sim.state_provinces.get(s, [])
        unocc_pids = [pid for pid in st_pids if not sim.provinces[pid].get("occupied_by")]
        st_cap_id = sim.states[s]["capital"]
        for pid in unocc_pids:
            pr = sim.provinces[pid]
            cb = sim.burgs.get(pr.get("burg"))
            if not cb:
                continue
            p_burgs = [sim.burgs[bid] for bid in pr.get("burgs", []) if bid in sim.burgs]
            has_st_cap = (st_cap_id in pr.get("burgs", [])) or (cb["id"] == st_cap_id)
            if has_st_cap and abs(wr["score"]) < 55 and len(unocc_pids) > 1:
                continue
            # Перевірка сухопутної або морської досяжності
            land_d2 = [
                (cb["x"] - o["x"]) ** 2 + (cb["y"] - o["y"]) ** 2
                for o in own_sample if o.get("feature") == cb.get("feature") or cb.get("feature") is None
            ]
            d2 = min(land_d2) if land_d2 else 1e18
            can_sea = has_fleet and has_port and any(pb.get("port") for pb in p_burgs)
            if d2 > 145000 and not can_sea:
                continue
            score_dist = min(d2, 95000.0) if can_sea and d2 > 145000 else d2
            if pr.get("siege", 0.0) > 0:
                score_dist *= 0.25   # продовжити вже розпочату облогу
            if pr.get("core_state") in winners:
                score_dist *= 0.55   # пріоритет повернення корінної провінції
            if score_dist < best_score:
                best_pr, best_score = pr, score_dist

    if not best_pr:
        return
    cb = sim.burgs[best_pr["burg"]]
    old = best_pr["state"]
    gov = best_pr.get("governor") or {}
    gov_def = 1.0
    for tr_k in gov.get("traits", []):
        gov_def *= LD.GOVERNOR_TRAITS.get(tr_k, {}).get("siege_def", 1.0)
    defense = (1.0 + (0.35 if cb.get("walls") else 0.0) + (0.35 if cb.get("citadel") else 0.0)
               + (0.25 if cb.get("capital") else 0.0)) * gov_def

    betrayal = gov.get("loyalty", 70.0) < 25.0 and rng.random() < 0.35
    if betrayal:
        best_pr["siege"] = 100.0
    else:
        base_prog = rng.uniform(34.0, 56.0) * (1.25 if has_artillery else 1.0)
        best_pr["siege"] = min(100.0, best_pr.get("siege", 0.0) + base_prog / max(defense, 0.5))

    if best_pr["siege"] < 100.0:
        sim.log("war", f"{wr['name']}: війська {sim.sname(winners[0])} тримають в облозі {cb['uk']} (провінція {best_pr['uk']}, прогрес {best_pr['siege']:.0f}%).",
                states=[winners[0], old], burg=cb["id"], war=wr["id"], sev=2)
        return

    # Окупація всієї провінції
    best_pr["siege"] = 0.0
    best_pr["occupied_by"] = winners[0]
    for bid in best_pr.get("burgs", []):
        if bid in sim.burgs:
            b = sim.burgs[bid]
            b["occupied_by"] = winners[0]
            b["pop"] *= 0.94
            b["rural"] *= 0.96
            sim.add_mod("burg", bid, "mort", 0.002, 3, "conquest", kind="add")
    occ_list = wr.setdefault("occupied_provs", [])
    if best_pr["id"] not in occ_list:
        occ_list.append(best_pr["id"])
    cap_list = wr.setdefault("captured", [])
    if cb["id"] not in cap_list:
        cap_list.append(cb["id"])
    wr["score"] += 10.0 if winners[0] in wr["attackers"] else -10.0
    sim.states[old]["stability"] = clamp(sim.states[old]["stability"] - 2.5, 0, 100)
    if betrayal:
        sim.log("war", f"{wr['name']}: намісник {gov.get('name', '')} зрадив {sim.sname(old)} і без бою здав провінцію {best_pr['uk']} державі {sim.sname(winners[0])}!",
                states=[winners[0], old], burg=cb["id"], war=wr["id"], sev=3)
    else:
        sim.log("war", f"{wr['name']}: {sim.sname(winners[0])} окуповує провінцію {best_pr['uk']} ({sim.sname(old)}, центр {cb['uk']}).",
                states=[winners[0], old], burg=cb["id"], war=wr["id"], sev=3)
    if cb["id"] == sim.states[old]["capital"] or any(sim.burgs[bid].get("capital") for bid in best_pr.get("burgs", []) if bid in sim.burgs):
        sim.log("war", f"Столицю держави {sim.sname(old)} окуповано! Країна на межі капітуляції.",
                states=[winners[0], old], sev=3)
        wr["score"] = 90.0 if winners[0] in wr["attackers"] else -90.0


def capture_burg(sim, wr, winners, losers, rng):
    return step_provincial_front(sim, wr, winners, losers, rng)


def end_war(sim, wr, rng):
    w = sim.w
    s = wr["score"]
    att_won = s >= 20
    def_won = s <= -20
    tick = sim.tick_index()
    lead_a, lead_d = wr["attackers"][0], wr["defenders"][0]
    if att_won:
        winner, loser = lead_a, lead_d
        win_side, lose_side = wr["attackers"], wr["defenders"]
    elif def_won:
        winner, loser = lead_d, lead_a
        win_side, lose_side = wr["defenders"], wr["attackers"]
    else:
        winner = loser = None
        win_side = lose_side = []

    annexed_names = []
    if winner:
        # 1) Звільнити всі провінції переможців, які були окуповані переможеними
        for pr in sim.provinces.values():
            if pr["state"] in win_side and pr.get("occupied_by") in lose_side:
                pr["occupied_by"] = None
                pr["siege"] = 0.0
                for bid in pr.get("burgs", []):
                    if bid in sim.burgs:
                        sim.burgs[bid]["occupied_by"] = None

        # 2) Зібрати провінції переможених, окуповані переможцями
        occ_provs = [pr for pr in sim.provinces.values()
                     if pr["state"] in lose_side and pr.get("occupied_by") in win_side]
        max_annex = len(occ_provs) if abs(s) >= 65 else (max(1, int(abs(s) // 22)) if occ_provs else 0)
        occ_provs.sort(key=lambda pr: (
            0 if pr.get("core_state") in win_side else 1,
            1 if sim.states.get(pr["state"], {}).get("capital") in pr.get("burgs", []) else 0,
            -len(pr.get("burgs", [])),
        ))
        annexed_pids = set()
        for pr in occ_provs:
            if len(annexed_pids) >= max_annex:
                break
            st_los = sim.states.get(pr["state"])
            is_cap_prov = st_los and st_los["capital"] in pr.get("burgs", [])
            other_provs = [pid for pid in sim.state_provinces.get(pr["state"], []) if pid != pr["id"] and pid not in annexed_pids]
            if is_cap_prov and abs(s) < 75 and other_provs:
                continue
            new_owner = pr.get("occupied_by") or winner
            annex_province(sim, pr["id"], new_owner, rng)
            annexed_pids.add(pr["id"])
            annexed_names.append(pr["uk"])

        # Неанексовані окуповані провінції повертаються власнику
        for pr in occ_provs:
            if pr["id"] not in annexed_pids:
                pr["occupied_by"] = None
                pr["siege"] = 0.0
                for bid in pr.get("burgs", []):
                    if bid in sim.burgs:
                        sim.burgs[bid]["occupied_by"] = None

        sim.refresh_ownership()
        _ensure_valid_capitals(sim)
        sim.refresh_ownership()
        refresh_neighbors(sim)

        sw, sl = sim.states[winner], sim.states[loser]
        rep = max(0.0, _finite_num(sl.get("treasury", 0.0), 0.0) * 0.2)
        sl["treasury"] = max(0.0, _finite_num(sl.get("treasury", 0.0), 0.0) - rep)
        sw["income_once"] = _finite_num(sw.get("income_once", 0.0), 0.0) + rep
        sl["legitimacy"] = clamp(sl["legitimacy"] - 6, 0, 100)
        txt = f"{wr['name']} завершено перемогою {sim.sname(winner)}; {sim.sname(loser)} сплатить контрибуцію {LD.fmt_coins(rep)}."
        if annexed_names:
            txt += f" Анексовано провінції: {', '.join(annexed_names)}."
        if not sim.state_burgs.get(loser):
            txt += f" {sim.sname(loser)} припинила існування."
            sim.log("war", txt, states=[winner, loser], war=wr["id"], sev=3)
        else:
            sim.log("war", txt, states=[winner, loser], war=wr["id"], sev=3)
            if rng.random() < 0.3 and [loser, winner] not in w["vassals"] and sim.states[loser]["legitimacy"] < 45:
                w["vassals"].append([loser, winner])
                rel_add(sim, winner, loser, 40)
                sim.log("diplomacy", f"{sim.sname(loser)} стає васалом {sim.sname(winner)}.", states=[loser, winner], sev=2)
    else:
        # Білий мир — повернення всіх окупованих провінцій
        for pr in sim.provinces.values():
            if pr.get("occupied_by") in (wr["attackers"] + wr["defenders"]) or pr["state"] in (wr["attackers"] + wr["defenders"]):
                if pr.get("occupied_by") in (wr["attackers"] + wr["defenders"]):
                    pr["occupied_by"] = None
                    pr["siege"] = 0.0
                    for bid in pr.get("burgs", []):
                        if bid in sim.burgs:
                            sim.burgs[bid]["occupied_by"] = None
        sim.log("war", f"{wr['name']} завершується перемир'ям (status quo): усі окуповані провінції повернуто.",
                states=wr["attackers"] + wr["defenders"], war=wr["id"], sev=2)

    for a in wr["attackers"]:
        for d in wr["defenders"]:
            if a not in sim.states or d not in sim.states:
                continue
            sim.states[a].setdefault("truce", {})[d] = tick + 36
            sim.states[d].setdefault("truce", {})[a] = tick + 36
            rel_add(sim, a, d, 20)
    w["war_history"].append(dict(name=wr["name"], start=wr["start_year"], end=w["date"]["year"],
                                 attacker=lead_a, defender=lead_d, result=("attacker" if att_won else "defender" if def_won else "draw"),
                                 captured=list(wr["captured"]), annexed=annexed_names))
    w["wars"].remove(wr)


def step_mercs(sim, rng):
    w = sim.w
    tick = sim.tick_index()
    for sid, st in sim.states.items():
        wars = in_war(sim, sid)
        if not wars or st.get("mercs") or st["treasury"] < st["rev0"] * 4 or rng.random() > 0.08:
            continue
        free = [m for m in w["mercs"] if m["employer"] is None or m["contract_end"] <= tick]
        free = [m for m in free if m["home"] != sid and rel_get(sim, sid, m["home"]) > -30 and m["home"] in sim.states
                and not in_war_between(sim, sid, m["home"])]
        if not free:
            continue
        m = rng.choice(free)
        months = rng.randint(8, 18)
        m["employer"], m["contract_end"] = sid, tick + months
        st["mercs"].append(dict(id=m["id"], name=m["name"], size=m["size"], unit=m["unit"], fee=m["fee"],
                                until=tick + months))
        sim.log("military", f"{st['uk']} наймає «{m['name']}» ({m['size']} бійців) на {months} міс.", state=sid, sev=2)


def step_rulers(sim, rng):
    w = sim.w
    if w["date"]["month"] != 1:
        return
    for sid, st in sim.states.items():
        r = st["ruler"]
        if r["collective"]:
            continue
        r["age"] += 1
        p = max(0.0, (r["age"] - 55) * 0.004) + 0.003
        if rng.random() < p:
            from .worldgen import _make_name
            cult = st["culture_name"]
            old = r["name"]
            title = old.split(" ")[0] if " " in old else "Правитель"
            new_name = f"{title} {_make_name(rng, cult)}"
            r["name"], r["age"] = new_name, rng.randint(19, 45)
            r["traits"] = rng.sample(LD.RANDOM_TRAIT_POOL, 2)
            cris = rng.random() < 0.35
            sim.log("politics", f"Помер правитель держави {st['uk']} ({old}). Новий володар — {new_name}." +
                    (" Престолонаслідування спірне." if cris else ""), state=sid, sev=2)
            if cris:
                sim.add_mod("state", sid, "stab", -4, 8, "succession", kind="add")
                st["legitimacy"] = clamp(st["legitimacy"] - 12, 10, 100)


# ---------------------------------------------------------------------------
# Сценарій: Четвертий Похід на Кірос
# ---------------------------------------------------------------------------
def step_crusade(sim, rng):
    w = sim.w
    cr = w["crusade"]
    cfg = LD.CRUSADE
    t = sim.tick_index()
    if cr["phase"] in ("done", "inactive"):
        return
    sp = [s for s in cr["sponsors"] if s in sim.states
          and not sim.states[s].get("extinct")
          and sim.burgs.get(sim.states[s].get("capital")) is not None]
    t0 = cr["start_tick"]
    ships_gid = good_id("Ships", 53)
    if cr["phase"] == "rumors" and t >= t0:
        cr["phase"] = "muster"
        cr["muster_end"] = t + cfg["muster_months"]
        for s in sp:
            sim.add_mod("state", s, "tax", cfg["tax_boost"], cfg["muster_months"] + cfg["sail_months"], "crusade")
        sim.log("crusade", f"Оголошено {cfg['name']}: {', '.join(sim.sname(s) for s in sp)} починають збір флоту й постачання. "
                "Податки зростають, на верфях і в арсеналах — гарячка.", sev=3)
    if cr["phase"] == "muster":
        for s in sp:
            st = sim.states[s]
            cb = sim.burgs[st["capital"]]
            mk = sim.markets[cb["market"]]
            goods = [g for g in cfg["demand_goods"] if g in sim.goods]
            if not goods:
                continue
            need = max(0.0, _finite_num(cfg["demand_units"], 0.0)) / len(goods)
            for g in goods:
                stock = max(0.0, _finite_num(mk["stock"].get(g, 0.0), 0.0))
                q = max(0.0, min(need, stock * 0.3))
                mk["stock"][g] = max(0.0, stock - q)
                mk.setdefault("want", {})[g] = _finite_num(mk["want"].get(g, 0.0), 0.0) + need
                price = max(0.0, _finite_num(mk["price"].get(g, sim.goods[g]["value"]), 0.0))
                cost = q * price
                st["treasury"] -= cost                  # реальна оплата з казни спонсора
                cr["supplies"] += q * max(0.0, _finite_num(sim.goods[g]["value"], 0.0))
                if g == ships_gid:
                    cr["fleet"] += q
        want_total = len(sp) * _finite_num(cfg["demand_units"], 0.0) * _finite_num(cfg["muster_months"], 0.0) * 6.0
        cr["progress"] = clamp(_finite_num(cr["supplies"], 0.0) / max(want_total, 1.0), 0, 1.0)
        if t >= cr["muster_end"]:
            cr["phase"] = "sail"
            cr["sail_end"] = t + cfg["sail_months"]
            sim.log("crusade", f"Флот Походу (готовність постачання {cr['progress']*100:.0f} %) вирушає через океан до Кіросу.", sev=3)
    elif cr["phase"] == "sail":
        if rng.random() < 0.25:
            lost = cr["fleet"] * 0.12
            cr["fleet"] = max(0.0, cr["fleet"] - lost)
            cr["progress"] *= 0.93
            sim.log("crusade", "Флот Походу потрапив у шторм і втратив частину суден та припасів.", sev=2)
        if t >= cr["sail_end"]:
            cr["phase"] = "campaign"
            cr["camp_end"] = t + cfg["campaign_months"]
            sim.log("crusade", "Висадка на Кіросі: починається кампанія проти орд нежиті.", sev=3)
    elif cr["phase"] == "campaign":
        cr["fleet"] = max(0.0, cr["fleet"] * 0.995)   # флот витрачається під час кампанії
        for s in sp:
            st = sim.states[s]
            for u in st["army"]:
                st["army"][u] = int(st["army"][u] * 0.995)
            st["war_exhaustion"] = clamp(st["war_exhaustion"] + 0.5, 0, 100)
        if t >= cr["camp_end"]:
            progress = clamp(cr["progress"], 0.0, 1.0)
            fleet_factor = clamp(0.55 + 0.45 * min(1.0, cr["fleet"] / 10.0), 0.55, 1.0)
            p = clamp(0.35 * (0.4 + progress * fleet_factor), 0.08, 0.70)
            ok = rng.random() < p
            cr["result"] = "success" if ok else "failure"
            cr["phase"] = "done"
            if ok:
                for s in sp:
                    sim.states[s]["legitimacy"] = clamp(sim.states[s]["legitimacy"] + 10, 0, 100)
                    sim.add_mod("state", s, "stab", 3, 12, "crusade_win", kind="add")
                sim.log("crusade", f"{cfg['name']} завершено успіхом (шанс був {p*100:.0f} %): плацдарм на Кіросі утримано, "
                        "відкрито нові торгові шляхи.", sev=3)
            else:
                for s in sp:
                    st = sim.states[s]
                    for u in st["army"]:
                        st["army"][u] = int(st["army"][u] * 0.9)
                    st["legitimacy"] = clamp(st["legitimacy"] - 8, 0, 100)
                    sim.add_mod("state", s, "stab", -4, 12, "crusade_fail", kind="add")
                sim.log("crusade", f"{cfg['name']} провалено (шанс успіху був {p*100:.0f} %): величезні втрати, крах довіри до коаліції.",
                        sev=3)
