# -*- coding: utf-8 -*-
"""Фінанси держав, дипломатія, війни, найманці та сценарій Походу на Кірос."""
import math

from . import lore_data as LD
from .engine import clamp

UNIT_POWER = {"infantry": 1.0, "archers": 1.0, "cavalry": 2.0, "artillery": 12.0, "fleet": 50.0}
LAND_WEIGHT = {"fleet": 0.35}
REL_LABELS = [(75, "Ally"), (40, "Friendly"), (-10, "Neutral"), (-35, "Suspicion"), (-65, "Rival"), (-1000, "Enemy")]


def rel_get(sim, a, b):
    if a == b:
        return 0.0
    return sim.w["relations"].get(min(a, b), {}).get(max(a, b), 0.0)


def rel_add(sim, a, b, v):
    lo, hi = min(a, b), max(a, b)
    r = sim.w["relations"].setdefault(lo, {})
    r[hi] = clamp(r.get(hi, 0.0) + v, -100.0, 100.0)


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
    q = st["readiness"] * st["tech"] * (0.6 + 0.4 * st["stability"] / 100.0) * sim.mm("state", sid, "war_power")
    return p * q


def heads(st):
    return sum(st["army"].values()) + sum(m["size"] for m in st.get("mercs", []))


def war_pairs(sim):
    pairs = set()
    for wr in sim.w["wars"]:
        for a in wr["attackers"]:
            for d in wr["defenders"]:
                pairs.add((min(a, d), max(a, d)))
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
    if w["war_pairs"] == [] or isinstance(w["war_pairs"], list):
        war_pairs(sim)
    cr = w["crusade"]
    for sid, st in sim.states.items():
        pop = sim.acc["pop"].get(sid, st.get("pop_cache", 0))
        tr = 1.0
        for t in st["ruler"]["traits"]:
            tr *= LD.RULER_TRAITS.get(t, {}).get("tax", 1.0) ** 0.5
        tm = st["tax_mult"] * sim.mm("state", sid, "tax") * tr
        poll = cfg["poll_k"] * st["poll_tax"] * pop / 1000.0 / 12.0 * tm
        sales = sim.acc["sales"].get(sid, 0.0) * tm
        tariff = sim.acc["tariff"].get(sid, 0.0)
        extra = st.pop("income_once", 0.0)
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
        exp = upkeep + merc_fee + admin + spent_goods
        st["rev"], st["exp"] = round(rev, 2), round(exp, 2)
        st["income_breakdown"] = dict(poll=round(poll, 1), sales=round(sales, 1), tariff=round(tariff, 1),
                                      upkeep=round(upkeep, 1), admin=round(admin, 1), goods=round(spent_goods, 1),
                                      mercs=round(merc_fee, 1))
        st["treasury"] += rev - exp
        if st["treasury"] < 0:
            st["debt"] += -st["treasury"]
            st["treasury"] = 0.0
            lender = max(w["guilds"], key=lambda g: g["wealth"]) if w["guilds"] else None
            if lender and lender["wealth"] > 1:
                lender["wealth"] += 0  # кредит гільдії умовно покриває дефіцит
        elif st["debt"] > 0 and st["treasury"] > st["rev0"] * 2:
            pay = min(st["debt"], st["treasury"] * 0.3)
            st["debt"] -= pay
            st["treasury"] -= pay
        st["debt"] *= 1.0 + 0.10 / 12.0
        if st["debt"] > st["rev0"] * 8 and heads(st) > 0:       # режим жорсткої економії
            for u in st["army"]:
                st["army"][u] = int(st["army"][u] * 0.98)
            sim.add_mod("state", sid, "stab", -1.5, 2, "austerity", kind="add")
    # доходи гільдій з торгових потоків
    tv = sim.acc["trade_val"]
    tot = sum(tv.values()) or 1.0
    for g in w["guilds"]:
        mk = sim.markets[g["market"]]
        share = mk.get("capital", 0.0)
        g["wealth"] += share * 0.02 * g["power"] + 0.002 * g["wealth"]
        mk["capital"] = mk.get("capital", 0.0) * 0.95
    # наближення казначейств гільдій до реальності: комісія від ємності ринку
    for m in sim.markets.values():
        m["capital"] = m.get("capital", 0.0) * 0.98


# ---------------------------------------------------------------------------
# Політика
# ---------------------------------------------------------------------------
def step_politics(sim, rng):
    w = sim.w
    tick = sim.tick_index()
    pairs = war_pairs(sim)
    step_diplomacy(sim, rng)
    step_stability(sim, rng)
    step_army_recovery(sim, rng)
    step_wars(sim, rng)
    step_declarations(sim, rng)
    step_mercs(sim, rng)
    step_crusade(sim, rng)
    step_rulers(sim, rng)


def step_diplomacy(sim, rng):
    w = sim.w
    ids = sorted(sim.states)
    te = sim.acc["trade_edge"]
    for i, a in enumerate(ids):
        sa = sim.states[a]
        for b in ids[i + 1:]:
            old = rel_get(sim, a, b)
            if old == 0 and b not in sa["neighbors"] and te.get((a, b), 0) + te.get((b, a), 0) <= 0 and rng.random() < 0.9:
                continue
            sb = sim.states[b]
            d = rng.gauss(0, 1.0) - old * 0.012
            if b in sa["neighbors"]:
                d -= 0.12
            tv = te.get((a, b), 0) + te.get((b, a), 0)
            if tv > 0:
                d += min(1.2, math.log1p(tv) * 0.12)
            if sa["religion"] == sb["religion"]:
                d += 0.10
            if sa["culture"] == sb["culture"]:
                d += 0.08
            if (min(a, b), max(a, b)) in w["war_pairs"]:
                d -= 3.0
            d += sim.ma("pair", (a, b), "rel")
            new = clamp(old + d, -100, 100)
            lo, hi = a, b
            w["relations"].setdefault(lo, {})[hi] = new
            la, lb = rel_label(old), rel_label(new)
            if la != lb and (lb in ("Ally", "Enemy") or la in ("Ally",)) and not (a in sa.get("truce", {}) and False):
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
        at_war = bool(in_war(sim, sid))
        st["war_exhaustion"] = clamp(st["war_exhaustion"] + (2.0 if at_war else -1.5), 0, 100)
        taxp = max(0.0, st["tax_mult"] * sim.mm("state", sid, "tax") - 1.15) * 12
        debt_pen = min(12.0, st["debt"] / max(st["rev0"], 1.0) * 1.5)
        target = gp["stab_base"] + 28 * (st["food_sat"] - 0.95) + 12 * (st["lux_sat"] - 0.8) \
            - 0.22 * st["war_exhaustion"] - taxp - debt_pen + (st["legitimacy"] - 60) * 0.15 \
            + sim.ma("state", sid, "stab")
        st["stability"] = clamp(st["stability"] + 0.12 * (target - st["stability"]), 0, 100)
        st["legitimacy"] = clamp(st["legitimacy"] + (0.05 if st["stability"] > 60 else -0.08), 10, 100)
        st["prod_dev"] = clamp(st["prod_dev"] + 0.02, 0.5, 1.0)
        if st["stability"] < 28 and rng.random() < 0.03:
            lost = 0.04
            for u in st["army"]:
                st["army"][u] = int(st["army"][u] * (1 - lost))
            sim.add_mod("state", sid, "prod_all", 0.9, 5, "revolt")
            st["stability"] += 7
            sim.log("unrest", f"Хвилювання в державі {st['uk']}: бунти придушуються, армія втратила частину сил.",
                    state=sid, sev=2)


def step_army_recovery(sim, rng):
    for sid, st in sim.states.items():
        if st["debt"] > st["rev0"] * 6:
            continue
        for u, n0 in st["army0"].items():
            cur = st["army"].get(u, 0)
            target = n0 * (1.0 + 0.4 * max(0.0, st.get("alert", 1) - 1) * bool(in_war(sim, sid)))
            if cur < target:
                st["army"][u] = int(cur + min(target - cur, max(1.0, n0 * 0.015)))
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
            if st["truce"].get(t, -1) > tick or in_war_between(sim, sid, t):
                continue
            if any([min(sid, t), max(sid, t)] == [min(a, b), max(a, b)] for a, b in w["vassals"]):
                continue
            rel = rel_get(sim, sid, t)
            if rel > 55:
                continue
            tp = state_power(sim, t)
            ratio = mine / max(tp, 1.0)
            if ratio < 0.8:
                continue
            sc = -rel / 100.0 * 1.2 + (min(ratio, 3) - 1) * 0.6 + (0.3 if st["religion"] != sim.states[t]["religion"] else 0) \
                + rng.random() * 0.4 - 0.3
            if sc > bs:
                best, bs = t, sc
        if best is not None and bs > 0.55:
            declare_war(sim, sid, best, rng)


def in_war_between(sim, a, b):
    return (min(a, b), max(a, b)) in sim.w["war_pairs"]


def declare_war(sim, a, d, rng, name=None, casus=None):
    w = sim.w
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
            if (rel >= 75 and rel_enemy < 20 and rng.random() < 0.5) or (vassal and rng.random() < 0.9):
                side.append(o)
    # не більш ніж по 3 союзники
    attackers, defenders = attackers[:4], defenders[:4]
    cas = casus or rng.choice(["суперечка за прикордонні землі", "образа посольства", "претензії на спадщину",
                               "боротьба за торгові шляхи", "релігійні розбіжності", "помста за набіги"])
    nm = name or f"Війна {sa['uk']} проти {sd['uk']}"
    wr = dict(id=max([x["id"] for x in w["wars"]] + [0]) + 1, name=nm, attackers=attackers, defenders=defenders,
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
    pw = [(s, state_power(sim, s)) for s in side]
    tot = sum(p for _, p in pw) or 1.0
    for s, p in pw:
        st = sim.states[s]
        f = clamp(frac_total * (p / tot) * len(side), 0, 0.08)
        for u in list(st["army"]):
            st["army"][u] = int(st["army"][u] * (1 - f))
        st["war_exhaustion"] = clamp(st["war_exhaustion"] + f * 40, 0, 100)


def step_wars(sim, rng):
    w = sim.w
    ended = []
    for wr in w["wars"]:
        pa = side_power(sim, wr["attackers"])
        pd = side_power(sim, wr["defenders"]) * 1.12
        ratio = pa / max(pa + pd, 1e-9)
        wr["score"] = clamp(wr["score"] + (ratio - 0.5) * 12.0 * (0.6 + 0.8 * rng.random()), -100, 100)
        la = clamp(0.012 * math.sqrt(pd / max(pa, 1e-9)) * (0.5 + rng.random()), 0, 0.06)
        ld = clamp(0.012 * math.sqrt(pa / max(pd, 1e-9)) * (0.5 + rng.random()), 0, 0.06)
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
        # облоги
        winner_att = wr["score"] > 28
        winner_def = wr["score"] < -28
        if (winner_att or winner_def) and rng.random() < 0.3:
            winners = wr["attackers"] if winner_att else wr["defenders"]
            losers = wr["defenders"] if winner_att else wr["attackers"]
            capture_burg(sim, wr, winners, losers, rng)
        # завершення
        s = wr["score"]
        months = (w["date"]["year"] - wr["start_year"]) * 12 + (w["date"]["month"] - wr["start_month"])
        lead_a, lead_d = wr["attackers"][0], wr["defenders"][0]
        exh = max(sim.states[lead_a]["war_exhaustion"], sim.states[lead_d]["war_exhaustion"])
        bankrupt = any(sim.states[x]["debt"] > sim.states[x]["rev0"] * 5 for x in (lead_a, lead_d))
        if abs(s) >= 85 or exh > 88 or bankrupt or (months > 18 and rng.random() < 0.05) \
                or not sim.state_burgs.get(lead_d) or not sim.state_burgs.get(lead_a):
            ended.append(wr)
    for wr in ended:
        end_war(sim, wr, rng)
    if ended:
        war_pairs(sim)


def capture_burg(sim, wr, winners, losers, rng):
    # найближчий до переможців місто програвших
    tgt_states = [s for s in losers if sim.state_burgs.get(s)]
    if not tgt_states:
        return
    own = [sim.burgs[b] for s in winners for b in sim.state_burgs.get(s, [])]
    if not own:
        return
    sample = rng.sample(own, min(len(own), 60))
    best, bd = None, 1e18
    for s in tgt_states:
        bl = sim.state_burgs[s]
        capital = sim.states[s]["capital"]
        for bid in bl:
            b = sim.burgs[bid]
            if bid == capital and abs(wr["score"]) < 70 and len(bl) > 1:
                continue
            d = min((b["x"] - o["x"]) ** 2 + (b["y"] - o["y"]) ** 2 for o in sample) \
                + (4000.0 if b["walls"] else 0.0)
            if d < bd:
                best, bd = b, d
    if best is None or bd > 120000:      # надто далеко — немає спільного фронту
        return
    old, new = best["state"], winners[0]
    best["state"] = new
    best["pop"] *= 0.9
    best["rural"] *= 0.93
    wr["captured"].append(best["id"])
    wr["score"] -= 12.0 if wr["score"] > 0 else -12.0
    sim.refresh_ownership()
    sim.add_mod("burg", best["id"], "prod_all", 0.6, 6, "conquest")
    sim.add_mod("burg", best["id"], "mort", 0.003, 4, "conquest", kind="add")
    sim.states[new]["legitimacy"] = clamp(sim.states[new]["legitimacy"] + 2, 0, 100)
    sim.states[old]["legitimacy"] = clamp(sim.states[old]["legitimacy"] - 4, 0, 100)
    sim.states[old]["stability"] = clamp(sim.states[old]["stability"] - 3, 0, 100)
    sim.log("war", f"{wr['name']}: {sim.sname(new)} захоплює {sim.bname(best['id'])} ({sim.sname(old)}).",
            states=[new, old], burg=best["id"], war=wr["id"], sev=3)
    if best["capital"]:
        sim.log("war", f"Столицю {sim.sname(old)} взято! Режим {sim.sname(old)} перебуває на межі краху.",
                states=[new, old], sev=3)
        wr["score"] = 100.0 if new in wr["attackers"] else -100.0


def end_war(sim, wr, rng):
    w = sim.w
    s = wr["score"]
    att_won = s > 20
    def_won = s < -20
    tick = sim.tick_index()
    lead_a, lead_d = wr["attackers"][0], wr["defenders"][0]
    la, ld = sim.states[lead_a], sim.states[lead_d]
    if att_won:
        winner, loser = lead_a, lead_d
    elif def_won:
        winner, loser = lead_d, lead_a
    else:
        winner = loser = None
    if winner:
        sw, sl = sim.states[winner], sim.states[loser]
        rep = sl["treasury"] * 0.2
        sl["treasury"] -= rep
        sw["income_once"] = sw.get("income_once", 0.0) + rep
        sl["legitimacy"] = clamp(sl["legitimacy"] - 6, 0, 100)
        txt = f"{wr['name']} завершено перемогою {sim.sname(winner)}; {sim.sname(loser)} сплатить контрибуцію {LD.fmt_coins(rep)}."
        for bid in wr["captured"]:
            pass
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
        sim.log("war", f"{wr['name']} завершується перемир'ям: жодна зі сторін не здобула переваги.",
                states=wr["attackers"] + wr["defenders"], war=wr["id"], sev=2)
    for a in wr["attackers"]:
        for d in wr["defenders"]:
            sim.states[a]["truce"][d] = tick + 36
            sim.states[d]["truce"][a] = tick + 36
            rel_add(sim, a, d, 20)
    w["war_history"].append(dict(name=wr["name"], start=wr["start_year"], end=w["date"]["year"],
                                 attacker=lead_a, defender=lead_d, result=("attacker" if att_won else "defender" if def_won else "draw"),
                                 captured=list(wr["captured"])))
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
    sp = [s for s in cr["sponsors"] if s in sim.states]
    t0 = cr["start_tick"]
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
            for g in cfg["demand_goods"]:
                need = cfg["demand_units"] / len(cfg["demand_goods"])
                q = min(need, mk["stock"].get(g, 0.0) * 0.3)
                mk["stock"][g] = mk["stock"].get(g, 0.0) - q
                mk.setdefault("want", {})[g] = mk["want"].get(g, 0.0) + need
                cost = q * mk["price"].get(g, sim.goods[g]["value"])
                st["treasury"] -= cost * 0.0 + 0       # оплата вже враховується податковим бустом
                cr["supplies"] += q * sim.goods[g]["value"]
                if g == 53:
                    cr["fleet"] += q
        want_total = len(sp) * cfg["demand_units"] * cfg["muster_months"] * 6.0
        cr["progress"] = clamp(cr["supplies"] / max(want_total, 1.0), 0, 1.5)
        if t >= cr["muster_end"]:
            cr["phase"] = "sail"
            cr["sail_end"] = t + cfg["sail_months"]
            sim.log("crusade", f"Флот Походу (готовність постачання {cr['progress']*100:.0f} %) вирушає через океан до Кіросу.", sev=3)
    elif cr["phase"] == "sail":
        if rng.random() < 0.25:
            cr["progress"] *= 0.93
            sim.log("crusade", "Флот Походу потрапив у шторм і втратив частину суден та припасів.", sev=2)
        if t >= cr["sail_end"]:
            cr["phase"] = "campaign"
            cr["camp_end"] = t + cfg["campaign_months"]
            sim.log("crusade", "Висадка на Кіросі: починається кампанія проти орд нежиті.", sev=3)
    elif cr["phase"] == "campaign":
        for s in sp:
            st = sim.states[s]
            for u in st["army"]:
                st["army"][u] = int(st["army"][u] * 0.995)
            st["war_exhaustion"] = clamp(st["war_exhaustion"] + 0.5, 0, 100)
        if t >= cr["camp_end"]:
            p = clamp(cfg["base_success"] * (0.5 + cr["progress"]) , 0.1, 0.85)
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
