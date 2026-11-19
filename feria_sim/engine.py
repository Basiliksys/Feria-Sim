# -*- coding: utf-8 -*-
"""Економічне ядро симуляції Ферії.

Крок симуляції = 1 місяць. Порядок місяця:
  події → виробництво (сировина + ремесло за рецептами) → торгівля між ринками
  → споживання → ціни → фінанси держав → населення → політика/війни → журнал.
Стан світу — один JSON-сумісний словник (`world`), детермінований від зерна.
"""
import json
import math
import os
import random
import collections

from . import lore_data as LD

PMIN, PMAX = 0.30, 6.0          # межі ціни відносно базової
COVER_MONTHS = 1.5               # цільовий запас у місяцях попиту
AGRI_TAGS = {"food", "clothing"}


# ---------------------------------------------------------------------------
# Збереження / завантаження
# ---------------------------------------------------------------------------
def _intkeys(o):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if isinstance(k, str) and (k.isdigit() or (k[:1] == "-" and k[1:].isdigit())):
                k = int(k)
            out[k] = _intkeys(v)
        return out
    if isinstance(o, list):
        return [_intkeys(x) for x in o]
    return o


def load_world(path):
    with open(path, encoding="utf-8") as f:
        return _intkeys(json.load(f))


def save_world(world, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    skip = {k: world.pop(k) for k in ("war_pairs", "_new_journal") if k in world}
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(world, f, ensure_ascii=False, separators=(",", ":"))
    finally:
        world.update(skip)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Допоміжне
# ---------------------------------------------------------------------------
def clamp(x, a, b):
    return a if x < a else b if x > b else x


def season(month, lat):
    """(множник врожайності, холод 0..1) для місяця 1..12 на широті lat."""
    m = month if lat >= 0 else (month + 5) % 12 + 1
    warm = math.cos(2 * math.pi * (m - 7) / 12)
    amp = clamp(abs(lat) / 50.0, 0.1, 1.0)
    cold = max(0.0, -warm) * clamp((abs(lat) - 10) / 45.0, 0.0, 1.0)
    agri = 1 + amp * 0.8 * math.cos(2 * math.pi * (m - 9) / 12)
    return agri, cold


def date_str(world):
    d = world["date"]
    era = world.get("meta", {}).get("era", LD.ERA_SHORT)
    return f"{LD.MONTHS_UK[d['month'] - 1]} {d['year']} {era}".strip()


class Sim:
    """Обгортка над `world` з кешами та кроком симуляції."""

    def __init__(self, world, seed=None):
        self.w = world
        self.seed = seed if seed is not None else world["meta"].get("sim_seed", 1)
        self.rt = None
        for m in world.get("mods", []):
            if m["scope"] == "pair" and isinstance(m["id"], list):
                m["id"] = tuple(m["id"])
        self.build_runtime()
        self._index_mods()

    # ------------------------------------------------------------------ runtime
    def build_runtime(self):
        w = self.w
        self.goods = w["goods"]
        self.markets = w["markets"]
        self.burgs = w["burgs"]
        self.states = w["states"]
        self.edges = w["edges"]
        meta = w["meta"]
        self.lat = {bid: meta["lat_n"] - b["y"] / meta["height"] * (meta["lat_n"] - meta["lat_s"])
                    for bid, b in self.burgs.items()}
        self.state_burgs = collections.defaultdict(list)
        for bid, b in self.burgs.items():
            self.state_burgs[b["state"]].append(bid)
        self.cat_goods = {c: [g for g, d in self.goods.items() if d["cover"].get(c, 0) > 0]
                          for c in LD.CATEGORIES}
        # глибина ланцюга виробництва (для порядку ремесла)
        depth = {}

        def dep(g, stack=()):
            if g in depth:
                return depth[g]
            if g in stack:
                return 0
            rec = self.goods[g]["recipes"]
            if not rec:
                depth[g] = 0
                return 0
            d = 1 + max(dep(i, stack + (g,)) for r in rec for i in r)
            depth[g] = d
            return d
        for g in self.goods:
            dep(g)
        self.depth = depth
        self.agri_goods = {g for g, d in self.goods.items()
                           if (set(d["tags"]) & AGRI_TAGS) and "aquatic" not in d["tags"] and not d["recipes"]
                           and g not in (16, 15)}
        self.market_state = {}
        self.refresh_ownership()
        self._mods_dirty = True
        from . import politics as PO
        PO.war_pairs(self)

    def refresh_ownership(self):
        w = self.w
        self.state_burgs = collections.defaultdict(list)
        for bid, b in self.burgs.items():
            self.state_burgs[b["state"]].append(bid)
        for mid, m in self.markets.items():
            self.market_state[mid] = self.burgs[m["center"]]["state"]
        self.market_burgs = {mid: [b for b in m["burgs"]] for mid, m in self.markets.items()}

    # ------------------------------------------------------------------ модифікатори
    def add_mod(self, scope, sid, key, val, months, src="", kind="mult"):
        until = self.tick_index() + max(1, int(months))
        self.w["mods"].append(dict(scope=scope, id=sid, key=key, val=val, until=until, src=src, kind=kind))
        self._mods_dirty = True

    def tick_index(self):
        d = self.w["date"]
        y0 = self.w.get("meta", {}).get("start_year", LD.START_YEAR)
        return (d["year"] - y0) * 12 + d["month"] - 1

    def _index_mods(self):
        t = self.tick_index()
        keep = [m for m in self.w["mods"] if m["until"] > t]
        if len(keep) != len(self.w["mods"]):
            self.w["mods"] = keep
        mult, add = collections.defaultdict(lambda: 1.0), collections.defaultdict(float)
        for m in keep:
            k = (m["scope"], m["id"], m["key"])
            if m["kind"] == "mult":
                mult[k] *= m["val"]
            else:
                add[k] += m["val"]
        self._mult, self._add = mult, add
        self._mods_dirty = False

    def mm(self, scope, sid, key):
        return self._mult.get((scope, sid, key), 1.0)

    def ma(self, scope, sid, key):
        return self._add.get((scope, sid, key), 0.0)

    # ------------------------------------------------------------------ журнал
    def log(self, kind, text, **kw):
        d = self.w["date"]
        rec = dict(y=d["year"], m=d["month"], kind=kind, text=text)
        rec.update(kw)
        self.w["journal"].append(rec)
        self.w.setdefault("_new_journal", []).append(rec)
        if len(self.w["journal"]) > 6000:
            del self.w["journal"][:1000]

    def sname(self, sid):
        st = self.states.get(sid)
        return st["uk"] if st else f"держава #{sid}"

    def bname(self, bid):
        b = self.burgs.get(bid)
        return b.get("uk", b["name"]) if b else f"місто #{bid}"

    # ------------------------------------------------------------------ основний цикл
    def run(self, months, progress=None):
        for i in range(months):
            self.tick()
            if progress:
                progress(i + 1, months)

    def tick(self, politics=True, events=True, advance=True, finance=True):
        from . import events as EV, politics as PO
        w = self.w
        cfg = w["config"]
        rng = random.Random(f"{self.seed}-{self.tick_index()}")
        self.rng = rng
        month = w["date"]["month"]
        self._index_mods()
        self.acc = dict(
            gdp=collections.Counter(), cons_val=collections.Counter(), pop=collections.Counter(),
            req=collections.defaultdict(collections.Counter), got=collections.defaultdict(collections.Counter),
            tariff=collections.Counter(), trade_val=collections.Counter(), poll=collections.Counter(),
            sales=collections.Counter(), food_req=collections.Counter(), food_got=collections.Counter(),
            lux_req=collections.Counter(), lux_got=collections.Counter(), trade_edge=collections.Counter(),
            export_val=collections.Counter(), import_val=collections.Counter(),
        )
        if events:
            EV.step_events(self, rng)
            self._index_mods()
        self.produce(month, rng)
        self.trade(rng)
        self.consume(month, rng)
        self.update_prices()
        if finance:
            PO.step_finance(self, rng)
        self.update_population(month, rng)
        if politics:
            PO.step_politics(self, rng)
        self.record_history()
        if advance:
            d = w["date"]
            d["month"] += 1
            if d["month"] > 12:
                d["month"] = 1
                d["year"] += 1

    # ------------------------------------------------------------------ виробництво
    def produce(self, month, rng):
        cfg = self.w["config"]
        cs = cfg["craft_scale"]
        for mid, m in self.markets.items():
            stock, price = m["stock"], m["price"]
            bl = self.market_burgs[mid]
            # 1) сировина
            slots = []
            for bid in bl:
                b = self.burgs[bid]
                st = self.states[b["state"]]
                tot = b["pop"] + b["rural"]
                labor = (tot / max(b["pop0"], 1.0)) ** 0.85
                stab_f = 0.6 + 0.4 * clamp(st["stability"] / 100.0, 0, 1)
                base = labor * stab_f * st.get("prod_dev", 1.0) \
                    * self.mm("burg", bid, "prod_all") * self.mm("state", b["state"], "prod_all") \
                    * self.mm("market", mid, "prod_all")
                agri, cold = season(month, self.lat[bid])
                b["_base"] = base
                outv = 0.0
                for g, u in b["raw"].items():
                    k = base
                    if g in self.agri_goods:
                        k *= agri * self.mm("state", b["state"], "prod_agri") * self.mm("burg", bid, "prod_agri")
                    k *= self.mm("burg", bid, f"prod_g{g}") * self.mm("state", b["state"], f"prod_g{g}")
                    q = u * k
                    stock[g] = stock.get(g, 0.0) + q
                    outv += q * price.get(g, self.goods[g]["value"])
                b["_out"] = outv
                for sl in b["craft"]:
                    slots.append((self.depth[sl["good"]], bid, sl))
            slots.sort(key=lambda t: t[0])
            # 2) ремесло
            want = m.setdefault("want", {})
            for _, bid, sl in slots:
                b = self.burgs[bid]
                cap = sl["units"] * cs * (((b["pop"] + b["rural"]) / max(b["pop0"], 1.0)) ** 0.7) \
                    * b["_base"] * math.sqrt(max(b["pop0"], 1000.0) / 20000.0)
                if cap <= 0:
                    continue
                g = sl["good"]
                cost = 0.0
                frac = 1.0
                for i, q in sl["recipe"].items():
                    need = q * cap
                    want[i] = want.get(i, 0.0) + need * 0.8
                    cost += q * price.get(i, self.goods[i]["value"])
                    frac = min(frac, stock.get(i, 0.0) / need if need > 0 else 1.0)
                gp = price.get(g, self.goods[g]["value"])
                if gp < cost * 0.85:
                    frac = min(frac, 0.25)
                if frac <= 0.0:
                    continue
                for i, q in sl["recipe"].items():
                    stock[i] = max(0.0, stock.get(i, 0.0) - q * cap * frac)
                q_out = cap * frac
                stock[g] = stock.get(g, 0.0) + q_out
                b["_out"] += q_out * gp - cap * frac * cost
            for bid in bl:
                b = self.burgs[bid]
                self.acc["gdp"][b["state"]] += max(b.get("_out", 0.0), 0.0)
                self.acc["pop"][b["state"]] += b["pop"] + b["rural"]

    # ------------------------------------------------------------------ торгівля
    def trade(self, rng):
        cfg = self.w["config"]
        rate = cfg["transport_rate"]
        for ei, e in enumerate(self.edges):
            ma, mb = self.markets[e["a"]], self.markets[e["b"]]
            sa, sb = self.market_state[e["a"]], self.market_state[e["b"]]
            tmult = self.mm("edge", ei, "trade") * self.mm("market", e["a"], "trade") * self.mm("market", e["b"], "trade")
            if e["sea"]:
                tmult *= self.mm("edge", ei, "piracy")
            tariff = 0.0
            if sa != sb:
                f = self.trade_friction(sa, sb)
                if f is None:
                    tmult *= 0.04                      # контрабанда під час війни/ембарго
                    tariff = 0.3
                else:
                    tariff = f
            moved_edge = 0.0
            if tmult > 0.001:
                seaf = 0.45 if e["sea"] else 1.0
                for src, dst, ms, md, sd in ((e["a"], e["b"], ma, mb, sb), (e["b"], e["a"], mb, ma, sa)):
                    for g, ps in ms["price"].items():
                        pd = md["price"].get(g)
                        if pd is None:
                            continue
                        gd = self.goods[g]
                        bulk = 1.0
                        for tg in gd["tags"]:
                            if tg in LD.BULKY_TAGS:
                                bulk = max(bulk, LD.BULKY_TAGS[tg]) if LD.BULKY_TAGS[tg] > 1 else min(bulk, LD.BULKY_TAGS[tg])
                        cost = math.sqrt(max(gd["value"], 0.5)) * rate * (e["dist"] / 100.0) * bulk * seaf
                        margin = pd * (1 - tariff) - ps - cost
                        if margin <= 0:
                            continue
                        avail = ms["stock"].get(g, 0.0)
                        if avail <= 0.5:
                            continue
                        # попит у кінці маршруту обмежує потік
                        dem = md.get("want", {}).get(g, 0.0)
                        room = max(dem * 2.5 - md["stock"].get(g, 0.0), dem * 0.3)
                        qty = min(avail * 0.28, room if dem > 0 else avail * 0.05) * clamp(margin / max(ps, 0.01), 0.05, 1.0) * tmult
                        if qty <= 0.05:
                            continue
                        loss = 0.01 + (0.02 if "food" in gd["tags"] else 0.0) * (e["dist"] / 300.0)
                        ms["stock"][g] -= qty
                        md["stock"][g] = md["stock"].get(g, 0.0) + qty * (1 - loss)
                        val = qty * ps
                        self.acc["tariff"][sd] += qty * pd * tariff * 0.6
                        self.acc["trade_val"][sd] += val
                        self.acc["export_val"][self.market_state[src]] += val
                        self.acc["import_val"][sd] += val
                        prof = qty * margin
                        ms["capital"] = ms.get("capital", 0.0) + prof * 0.5
                        md["capital"] = md.get("capital", 0.0) + prof * 0.5
                        moved_edge += val
                        key = (sa, sb) if src == e["a"] else (sb, sa)
                        self.acc["trade_edge"][key] += val
            e["flow"] = round(0.7 * e.get("flow", 0.0) + 0.3 * moved_edge, 2)

    def trade_friction(self, a, b):
        """Мито між державами або None, якщо торгівля заборонена (війна/ембарго)."""
        if self.at_war(a, b):
            return None
        if self.mm("pair", (min(a, b), max(a, b)), "embargo") < 0.5:
            return None
        sc = self.w["relations"].get(min(a, b), {}).get(max(a, b), 0)
        base = 0.04 if sc >= 70 else 0.07 if sc >= 40 else 0.10 if sc >= -10 else 0.16 if sc >= -35 else 0.24
        return base

    def at_war(self, a, b):
        wset = self.w.get("war_pairs")
        if wset is None:
            return False
        return (min(a, b), max(a, b)) in wset

    # ------------------------------------------------------------------ споживання
    def consume(self, month, rng):
        cfg = self.w["config"]
        dpc = cfg["per_capita"]
        for mid, m in self.markets.items():
            stock, price = m["stock"], m["price"]
            want = m["want_now"] = m.get("want_now", {})
            # відсортовані пропозиції по категоріях
            lists = {}
            for c in ("food", "utilities", "construction", "luxury"):
                lst = []
                for g in self.cat_goods[c]:
                    cv = self.goods[g]["cover"][c]
                    lst.append((price.get(g, self.goods[g]["value"]) / cv, g, cv))
                lst.sort()
                lists[c] = lst
            bl = list(self.market_burgs[mid])
            rng.shuffle(bl)
            for bid in bl:
                b = self.burgs[bid]
                sid = b["state"]
                st = self.states[sid]
                tot = b["pop"] + b["rural"]
                k = tot / 1000.0
                urb = b["pop"] / max(tot, 1.0)
                agri, cold = season(month, self.lat[bid])
                dem = {
                    "food": k * dpc["food"] * self.mm("burg", bid, "food_need"),
                    "utilities": k * dpc["utilities"] * (1 + 0.9 * cold) * self.mm("state", sid, "util_need"),
                    "construction": k * dpc["construction"] * (0.6 + 2.0 * urb) * self.mm("burg", bid, "rebuild")
                    * self.mm("state", sid, "rebuild"),
                    "luxury": k * dpc["luxury"] * (0.4 + LD.URBAN_LUXURY_BOOST * urb)
                    * (0.6 + 0.4 * st["stability"] / 100.0),
                }
                bs = b.setdefault("sat", {})
                for c, need in dem.items():
                    got = 0.0
                    remaining = need
                    lst = lists[c]
                    for pass_no in (0, 1):
                        cap_share = 0.40 if pass_no == 0 else 1.0
                        for cpc, g, cv in lst:
                            if remaining <= 1e-9:
                                break
                            avail = stock.get(g, 0.0)
                            if avail <= 0:
                                continue
                            take_cover = min(remaining, need * cap_share if pass_no == 0 else remaining, avail * cv)
                            if take_cover <= 0:
                                continue
                            qty = take_cover / cv
                            stock[g] = avail - qty
                            want[g] = want.get(g, 0.0) + qty
                            remaining -= take_cover
                            got += take_cover
                            val = qty * price.get(g, self.goods[g]["value"])
                            self.acc["cons_val"][sid] += val
                            self.acc["sales"][sid] += val * st["sales_tax"]
                    if remaining > 1e-9 and lst:
                        spread = remaining / len(lst)
                        for _c, g, cv in lst:
                            want[g] = want.get(g, 0.0) + spread / cv
                    sat = got / need if need > 0 else 1.0
                    bs[c] = 0.5 * bs.get(c, 1.0) + 0.5 * sat
                    self.acc["req"][sid][c] += need
                    self.acc["got"][sid][c] += got
        # переносимо want_now → want (EMA)
        for m in self.markets.values():
            wn = m.pop("want_now", {})
            wk = m.setdefault("want", {})
            for g in set(wn) | set(wk):
                wk[g] = 0.6 * wk.get(g, 0.0) + 0.4 * wn.get(g, 0.0) if g in wn else 0.9 * wk[g]

    # ------------------------------------------------------------------ ціни
    def update_prices(self):
        for m in self.markets.values():
            stock, price, want = m["stock"], m["price"], m.get("want", {})
            for g, d in self.goods.items():
                s = stock.get(g, 0.0)
                spoil = 0.04 if "food" in d["tags"] and "preservative" not in d["tags"] else 0.004
                s *= (1 - spoil)
                stock[g] = s
                wnt = want.get(g, 0.0)
                base = d["value"]
                target = wnt * COVER_MONTHS
                if target < 0.05:
                    ratio = 0.6 if s > 1 else 1.0
                    ratio = ratio ** 1
                else:
                    ratio = (target / max(s, 0.01)) ** 0.5
                newp = base * clamp(ratio, PMIN, PMAX) * self.mm("market", m["id"], f"price_g{g}")
                old = price.get(g, base)
                price[g] = old + 0.35 * (newp - old)

    # ------------------------------------------------------------------ населення
    def update_population(self, month, rng):
        cfg = self.w["config"]
        for bid, b in self.burgs.items():
            sid = b["state"]
            st = self.states[sid]
            sat = b.get("sat", {})
            fs = sat.get("food", 1.0)
            us = sat.get("utilities", 1.0)
            agri, cold = season(month, self.lat[bid])
            tot = b["pop"] + b["rural"]
            ratio = tot / max(b["pop0"], 1.0)
            if ratio <= 1.0:
                # Компенсаційне відновлення після епідемій та воєн за наявності їжі
                growth_factor = 1.0 + clamp(1.0 - ratio, 0.0, 0.75) * 0.85 * max(0.0, fs - 0.5)
            else:
                # Плавне сповільнення приросту при наближенні до місткості середовища (1.65x pop0)
                growth_factor = clamp(1.0 - (ratio - 1.0) / 0.65, 0.25, 1.0)
            birth = cfg["birth"] * (0.5 + 0.5 * fs) * growth_factor \
                * self.mm("state", sid, "pop_growth") * self.mm("burg", bid, "pop_growth")
            mort_add = min(0.015, self.ma("burg", bid, "mort") + self.ma("state", sid, "mort") + self.ma("market", b["market"], "mort"))
            death = cfg["death"] + max(0.0, 1 - fs) ** 1.2 * 0.02 + max(0.0, 1 - us) * cold * 0.004 + mort_add
            net = birth - death
            b["pop"] *= (1 + net)
            b["rural"] *= (1 + net * 0.98)
            # урбанізація при добрій їжі
            if fs > 0.97 and rng.random() < 0.3:
                mv = b["rural"] * 0.0004
                b["rural"] -= mv
                b["pop"] += mv
            b["pop"] = max(b["pop"], 50.0)
            b["rural"] = max(b["rural"], 50.0)
            # військові втрати/послабленя від мору тощо вже в mort

    # ------------------------------------------------------------------ історія
    def record_history(self):
        w = self.w
        h = w["history"]
        t = self.tick_index()
        row = {}
        for sid, st in self.states.items():
            req = self.acc["req"].get(sid, {})
            got = self.acc["got"].get(sid, {})
            fs = got.get("food", 0) / req["food"] if req.get("food") else 1.0
            st["food_sat"] = round(0.5 * st.get("food_sat", 1.0) + 0.5 * fs, 4)
            ls = got.get("luxury", 0) / req["luxury"] if req.get("luxury") else 1.0
            st["lux_sat"] = round(0.5 * st.get("lux_sat", 1.0) + 0.5 * ls, 4)
            st["gdp"] = round(self.acc["gdp"].get(sid, 0.0), 2)
            st["pop"] = round(self.acc["pop"].get(sid, 0.0))
            row[sid] = [st["gdp"], st["pop"], round(st["treasury"], 1), round(st["stability"], 1),
                        st["food_sat"], round(st.get("power", 0.0), 1)]
        h["states"].append([t, row])
        if len(h["states"]) > 240:
            del h["states"][:len(h["states"]) - 240]
        tot_pop = sum(self.acc["pop"].values())
        tot_gdp = sum(self.acc["gdp"].values())
        fi = self.price_index("food")
        ui = self.price_index("utilities")
        ci = self.price_index("construction")
        li = self.price_index("luxury")
        mi = self.price_index("military")
        h["world"].append([t, round(tot_pop), round(tot_gdp, 1), round(fi, 4), len(w["wars"]),
                           round(ui, 4), round(ci, 4), round(li, 4), round(mi, 4)])
        if len(h["world"]) > 1200:
            del h["world"][:len(h["world"]) - 1200]

    def price_index(self, cat, state=None):
        """Середня ціна кошика категорії відносно базової, зважена за попитом і пропозицією."""
        wsum = 0.0
        wtot = 0.0
        for m in self.markets.values():
            if state is not None and self.market_state[m["id"]] != state:
                continue
            for g in self.cat_goods.get(cat, []):
                w = max(m.get("want", {}).get(g, 0.0) + m["stock"].get(g, 0.0) * 0.05, 0.5)
                ratio = m["price"].get(g, self.goods[g]["value"]) / max(self.goods[g]["value"], 1.0)
                wsum += ratio * w
                wtot += w
        return wsum / wtot if wtot > 0 else 1.0

