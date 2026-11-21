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

# Спільний контракт конфігурації. worldgen.py копіює ці значення у world["config"],
# а Sim.cfg() використовує їх як фолбек для старих збережень.
CONFIG_DEFAULTS = {
    "price_elasticity": 0.18,
    "carry_cap": 1.65,
    "tech_cap": 3.0,
    "tech_decay": 0.002,
    "max_events_per_month": 4,
    "event_scale_by_size": True,
    "neighbor_drift": -0.03,
    "army_recovery_rate": 0.03,
    "trade_budget_factor": 2.0,
    "guild_invest_rate": 0.02,
    "demand_elasticity_enabled": True,
    "dynamic_recipes": True,
    "capital_constraint": True,
    "mil_k": 1.0,
    "mil_goods_per_head": 0.002,
    "event_rate": 1.0,
    "war_rate": 1.0,
    # каравани за готовими магістралями з карти
    "caravan_enabled": True,
    "caravan_share": 0.35,
    "caravan_max_active": 64,
    "caravan_hub_count": 5,
    # регіональна географія та спеціалізовані товари
    "geography_enabled": True,
    "special_goods_enabled": True,
    "specialty_rate": 1.0,
    # існуючі ключі (фолбек для старих/неповних збережень)
    "per_capita": {"food": 10.0, "utilities": 4.0, "construction": 1.5, "luxury": 0.8},
    "craft_scale": 1.0,
    "transport_rate": 0.012,
    "birth": 0.0042,
    "death": 0.0028,
    "poll_k": 1.0,
    "admin_share": 0.2,
}


def seed_market_capital(pop):
    """Початковий капітал ринку, похідний від населення його центру."""
    return max(100.0, float(pop or 0.0) * 0.01)


# ---------------------------------------------------------------------------
# Збереження / завантаження
# ---------------------------------------------------------------------------
def _intkeys(o):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            ik = None
            if isinstance(k, str) and k:
                try:
                    ik = int(k)
                except ValueError:
                    ik = None
                # лише канонічні десяткові рядки ("1", "-2"); "01"/"+1" лишаємо як є
                if ik is not None and str(ik) != k:
                    ik = None
            if ik is not None and ik not in out:
                k = ik
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
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(world, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    finally:
        world.update(skip)


# ---------------------------------------------------------------------------
# Допоміжне
# ---------------------------------------------------------------------------
def clamp(x, a, b):
    return a if x < a else b if x > b else x


def _finite(value, default=0.0):
    """Безпечне приведення до скінченного float (для недовірених даних)."""
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return v if math.isfinite(v) else default


def _as_int(value, default=0):
    """Безпечне приведення до int (рядки типу 'x' дають default)."""
    return int(_finite(value, default))


def _normalize_caravan(c, goods, markets):
    """Приводить караван зі старого/пошкодженого сейву до безпечного вигляду."""
    if not isinstance(c, dict):
        return None
    g, dest = c.get("good"), _as_int(c.get("dest"), -1)
    if g not in goods or dest not in markets:
        return None
    out = dict(c)
    out["good"] = g
    out["dest"] = dest
    out["route_id"] = _as_int(c.get("route_id"), 0)
    out["qty"] = max(0.0, _finite(c.get("qty"), 0.0))
    out["leg_index"] = max(-1, _as_int(c.get("leg_index"), -1))
    out["next_edge"] = _as_int(c.get("next_edge"), -1)
    out["unit_price"] = max(0.0, _finite(c.get("unit_price"), 0.0))
    out["margin"] = _finite(c.get("margin"), 0.0)
    out["eta_days"] = max(0.0, _finite(c.get("eta_days"), 0.0))
    out["created_tick"] = _as_int(c.get("created_tick"), 0)
    out["id"] = str(c.get("id", ""))
    for key in ("at_market", "origin", "origin_market"):
        if key in out:
            out[key] = _as_int(out[key], -1)
    out["origin_state"] = _as_int(c.get("origin_state"), -1) if c.get("origin_state") is not None else None
    return out


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
        self.rng = random.Random(self.seed)
        self.rt = None
        mods = world.get("mods")
        if not isinstance(mods, list):
            mods = []
            world["mods"] = mods
        for m in mods:
            if isinstance(m, dict) and m.get("scope") == "pair" and isinstance(m.get("id"), list):
                m["id"] = tuple(m["id"])
        self.build_runtime()
        self._index_mods()

    # ------------------------------------------------------------------ runtime
    def build_runtime(self):
        w = self.w
        cfg = w.setdefault("config", {})
        for key, val in CONFIG_DEFAULTS.items():
            if key not in cfg:
                cfg[key] = dict(val) if isinstance(val, dict) else val
        self.goods = w["goods"]
        self.markets = w["markets"]
        self.burgs = w["burgs"]
        self.states = w["states"]
        self.provinces = w.setdefault("provinces", {})
        self.edges = w["edges"]
        from . import geography as GT, routes as RT
        self.geography = GT.ensure_geography(w)
        self.routes_by_id = RT.ensure_highways(self)
        cars = w.get("caravans")
        raw_cars = cars if isinstance(cars, list) else []
        self.caravans = [c for c in (_normalize_caravan(x, self.goods, self.markets) for x in raw_cars) if c is not None]
        w["caravans"] = self.caravans
        self._ensure_provinces()
        # Нормалізація недовірених/старих даних: жоден товар чи значення не має
        # вибити симуляцію (KeyError / NaN / inf).
        goods = self.goods
        for gid, gd in list(goods.items()):
            if not isinstance(gd, dict):
                del goods[gid]
                continue
            gd["value"] = max(1e-9, _finite(gd.get("value"), 1.0))
            cov = gd.get("cover")
            gd["cover"] = {c: max(0.0, _finite(cov.get(c), 0.0)) if isinstance(cov, dict) else 0.0
                           for c in LD.CATEGORIES}
            tags = gd.get("tags")
            gd["tags"] = [t for t in tags if isinstance(t, str)] if isinstance(tags, (list, tuple)) else []
            recipes = gd.get("recipes")
            norm_recipes = []
            if isinstance(recipes, (list, tuple)):
                for rec in recipes:
                    if not isinstance(rec, dict):
                        continue
                    nrec = {}
                    for i, q in rec.items():
                        if i in goods:
                            qq = _finite(q, 0.0)
                            if qq > 0:
                                nrec[i] = qq
                    if nrec:
                        norm_recipes.append(nrec)
            gd["recipes"] = norm_recipes
        for b in self.burgs.values():
            raw = b.get("raw")
            b["raw"] = {g: max(0.0, _finite(u, 0.0)) for g, u in raw.items() if g in goods} \
                if isinstance(raw, dict) else {}
            craft = b.get("craft")
            norm_craft = []
            if isinstance(craft, (list, tuple)):
                for sl in craft:
                    if not isinstance(sl, dict) or sl.get("good") not in goods:
                        continue
                    rec = sl.get("recipe")
                    sl["recipe"] = {i: max(0.0, _finite(q, 0.0)) for i, q in rec.items() if i in goods} \
                        if isinstance(rec, dict) else {}
                    sl["units"] = max(0.0, _finite(sl.get("units"), 0.0))
                    norm_craft.append(sl)
            b["craft"] = norm_craft
        meta = w["meta"]
        lat_n = _finite(meta.get("lat_n"), 60.0)
        lat_s = _finite(meta.get("lat_s"), -60.0)
        height = _finite(meta.get("height"), 800.0)
        if height <= 0:
            height = 800.0
            meta["height"] = height
        self.lat = {bid: lat_n - _finite(b.get("y"), 0.0) / height * (lat_n - lat_s)
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
            if g in stack or len(stack) >= 64:
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
        non_agri = set()
        for name in ("salt", "honey"):
            gid = LD.GOOD_IDS.get(name)
            if gid is not None:
                non_agri.add(gid)
        self.agri_goods = {g for g, d in self.goods.items()
                           if (set(d["tags"]) & AGRI_TAGS) and "aquatic" not in d["tags"] and not d["recipes"]
                           and g not in non_agri}
        for mid, m in self.markets.items():
            cb = self.burgs.get(m.get("center"), {})
            for key in ("stock", "price", "want", "want_now", "shop_reserved"):
                d = m.get(key)
                m[key] = {g: max(0.0, _finite(v, 0.0)) for g, v in d.items() if g in goods} \
                    if isinstance(d, dict) else {}
            m["capital"] = _finite(m.get("capital"), seed_market_capital(_finite(cb.get("pop"), 0.0)))
        self.market_state = {}
        self.refresh_ownership()
        self._mods_dirty = True
        from . import politics as PO
        PO.war_pairs(self)

    def _ensure_provinces(self):
        """Мігрує старі збереження без повної прив'язки провінцій чи намісників."""
        if not self.burgs:
            return
        by_st = collections.defaultdict(list)
        for p in self.provinces.values():
            by_st[p["state"]].append(p)
        next_pid = (max(self.provinces) if self.provinces else 0) + 1
        for sid in self.states:
            if not by_st.get(sid):
                bl = sorted((b for b in self.burgs.values() if b["state"] == sid),
                            key=lambda x: (-int(bool(x.get("capital"))), -x["pop"]))
                if bl:
                    c = bl[0]
                    pid = next_pid
                    next_pid += 1
                    pr = dict(id=pid, name=c["name"], full_name=c["name"], state=sid, burg=c["id"],
                              form="Capital", color=self.states[sid].get("color", "#6a8caf"),
                              pole=[c["x"], c["y"]], coa=None, burgs=[])
                    self.provinces[pid] = pr
                    by_st[sid].append(pr)
        for pid, p in list(self.provinces.items()):
            p.setdefault("burgs", [])
            p.setdefault("core_state", p["state"])
            p.setdefault("occupied_by", None)
            p.setdefault("siege", 0.0)
            p.setdefault("assimilation", 0)
            p.setdefault("form_uk", LD.PROVINCE_FORM_UK.get(p.get("form") or "", "Провінція"))
            p.setdefault("uk", f"{p['form_uk']} {LD.translit(p['name'])}")
            p.setdefault("blazon", LD.blazon_coa(p.get("coa")))
            p.setdefault("specialty", "Змішане господарство")
            p.setdefault("lore", f"Край держави {self.sname(p['state'])}.")
            if not isinstance(p.get("governor"), dict):
                title = LD.GOVERNOR_TITLE.get(p["form_uk"], "Намісник")
                p["governor"] = dict(name=f"{title} {LD.translit(p['name'])}", age=40,
                                     traits=["wise_steward", "iron_commander"], loyalty=75.0)
        for b in self.burgs.values():
            b.setdefault("core_state", b["state"])
            b.setdefault("occupied_by", None)
            if b.get("province") not in self.provinces:
                st_p = by_st.get(b["state"]) or list(self.provinces.values())
                if st_p:
                    chosen = min(st_p, key=lambda pr: math.hypot(
                        b["x"] - (pr.get("pole") or [b["x"], b["y"]])[0],
                        b["y"] - (pr.get("pole") or [b["x"], b["y"]])[1]
                    ))
                    b["province"] = chosen["id"]
                    if b["id"] not in chosen["burgs"]:
                        chosen["burgs"].append(b["id"])

    def refresh_ownership(self):
        w = self.w
        self.state_burgs = collections.defaultdict(list)
        self.prov_burgs = collections.defaultdict(list)
        for bid, b in self.burgs.items():
            self.state_burgs[b["state"]].append(bid)
            if b.get("province") in self.provinces:
                self.prov_burgs[b["province"]].append(bid)
        self.state_provinces = collections.defaultdict(list)
        for pid, p in self.provinces.items():
            p["burgs"] = list(self.prov_burgs.get(pid, []))
            self.state_provinces[p["state"]].append(pid)
        for mid, m in self.markets.items():
            self.market_state[mid] = self.burgs[m["center"]]["state"]
        self.market_burgs = {mid: [b for b in m["burgs"]] for mid, m in self.markets.items()}

    # ------------------------------------------------------------------ модифікатори
    def add_mod(self, scope, sid, key, val, months, src="", kind="mult"):
        value = _finite(val, 0.0)
        try:
            span = max(1, min(int(_finite(months, 1)), 120))
        except (TypeError, ValueError, OverflowError):
            span = 1
        until = self.tick_index() + span
        self.w["mods"].append(dict(scope=scope, id=sid, key=key, val=value, until=until,
                                   src=str(src)[:200], kind="mult" if kind == "mult" else "add"))
        self._mods_dirty = True

    def tick_index(self):
        d = self.w["date"]
        y0 = self.w.get("meta", {}).get("start_year", LD.START_YEAR)
        return (d["year"] - y0) * 12 + d["month"] - 1

    def _index_mods(self):
        t = self.tick_index()
        mods = self.w.get("mods")
        if not isinstance(mods, list):
            mods = []
            self.w["mods"] = mods
        keep = [m for m in mods if isinstance(m, dict) and _finite(m.get("until"), 0) > t]
        if len(keep) != len(mods):
            self.w["mods"] = keep
        mult, add = collections.defaultdict(lambda: 1.0), collections.defaultdict(float)
        for m in keep:
            sid = m.get("id")
            if isinstance(sid, list):
                sid = tuple(sid)
            if not isinstance(sid, (int, str, tuple)):
                continue
            k = (m.get("scope"), sid, m.get("key"))
            val = _finite(m.get("val"), 0.0)
            if m.get("kind") == "mult":
                mult[k] *= val
            else:
                add[k] += val
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
        nj = self.w.get("_new_journal")
        if not isinstance(nj, list):
            nj = []
            self.w["_new_journal"] = nj
        nj.append(rec)
        if len(self.w["journal"]) > 6000:
            del self.w["journal"][:1000]
        if len(nj) > 6000:
            del nj[:1000]

    def sname(self, sid):
        st = self.states.get(sid)
        return st["uk"] if st else f"держава #{sid}"

    def bname(self, bid):
        b = self.burgs.get(bid)
        return b.get("uk", b["name"]) if b else f"місто #{bid}"

    # ------------------------------------------------------------------ контракт модулів
    def cfg(self, key, default=None):
        """Читає world.config з фолбеком до загального контракту (старі збереження)."""
        cfg = self.w.get("config")
        if not isinstance(cfg, dict):
            cfg = CONFIG_DEFAULTS
        if key in cfg:
            return cfg[key]
        return CONFIG_DEFAULTS.get(key, default)

    def gid(self, name, default=None):
        """Стабільна назва товару -> канонічний ID (див. LD.GOOD_IDS)."""
        return LD.GOOD_IDS.get(name, default)

    def state_mult(self, sid, key, default=1.0):
        """Безпечний мультиплікатор держави (trade_mod/tariff_mod/war_power)."""
        st = self.states.get(sid)
        if not isinstance(st, dict):
            return default
        val = st.get(key, default)
        if val is None:
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def state_power(self, sid):
        """Потужність держави для історії/відображення; відсутнє war_power = 1.0."""
        st = self.states.get(sid, {})
        val = st.get("power")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0
        try:
            from . import politics as PO
            return float(PO.state_power(self, sid))
        except (ImportError, AttributeError, TypeError, ValueError):
            return 0.0

    def mil_demand_units(self, sid, war=None):
        """Обсяг військового попиту держави з урахуванням mil_k (використовує й politics.py)."""
        st = self.states.get(sid)
        if not st:
            return 0.0
        heads = sum(st.get("army", {}).values()) + sum(m.get("size", 0.0) for m in st.get("mercs", []))
        if war is None:
            war = any(sid in wr.get("attackers", []) or sid in wr.get("defenders", [])
                      for wr in self.w.get("wars", []))
        mult = 1.0 + 0.6 * bool(war)
        return heads * float(self.cfg("mil_goods_per_head", 0.002)) * float(self.cfg("mil_k", 1.0)) * mult

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
                pr = self.provinces.get(b.get("province"))
                prov_f = 1.0
                if pr:
                    gov = pr.get("governor") or {}
                    for tr in gov.get("traits", []):
                        prov_f *= LD.GOVERNOR_TRAITS.get(tr, {}).get("prod", 1.0)
                    if pr.get("occupied_by") or b.get("occupied_by"):
                        prov_f *= 0.55
                    elif pr.get("siege", 0) > 0:
                        prov_f *= 0.75
                elif b.get("occupied_by"):
                    prov_f *= 0.55
                base = labor * stab_f * st.get("prod_dev", 1.0) * prov_f \
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
            # 2) ремесло: щомісяця обираємо найкращий наявний рецепт
            want = m.setdefault("want", {})
            dynamic = bool(self.cfg("dynamic_recipes", True))
            for _, bid, sl in slots:
                b = self.burgs[bid]
                cap = sl["units"] * cs * (((b["pop"] + b["rural"]) / max(b["pop0"], 1.0)) ** 0.7) \
                    * b["_base"] * math.sqrt(max(b["pop0"], 1000.0) / 20000.0)
                if cap <= 0:
                    continue
                g = sl["good"]
                if g not in self.goods:
                    continue
                gp = price.get(g, self.goods[g]["value"])
                recipes = self.goods[g].get("recipes") or []
                chosen = None
                if recipes and dynamic:
                    for idx, rec in enumerate(recipes):
                        if not rec:
                            continue
                        rcost = sum(q * price.get(i, self.goods[i]["value"])
                                    for i, q in rec.items() if i in self.goods)
                        rfrac = 1.0
                        for i, q in rec.items():
                            need = q * cap
                            if need > 1e-9:
                                rfrac = min(rfrac, max(0.0, stock.get(i, 0.0)) / need)
                        # пріоритет: прибутковість і наявність сировини; idx — стабільний тайбрейк
                        score = (gp - rcost + 0.01) * rfrac - idx * 1e-6
                        if chosen is None or score > chosen[0]:
                            chosen = (score, rec, rcost, rfrac)
                if chosen is None:
                    rec = sl.get("recipe") or (recipes[0] if recipes else {})
                    if not rec:
                        continue
                    rcost = sum(q * price.get(i, self.goods[i]["value"])
                                for i, q in rec.items() if i in self.goods)
                    rfrac = 1.0
                    for i, q in rec.items():
                        need = q * cap
                        if need > 1e-9:
                            rfrac = min(rfrac, max(0.0, stock.get(i, 0.0)) / need)
                    chosen = (0.0, rec, rcost, rfrac)
                _, recipe, cost, frac = chosen
                # збиткове ремесло не споживає сировину взагалі
                if gp < cost:
                    frac = 0.0
                else:
                    for i, q in recipe.items():
                        want[i] = want.get(i, 0.0) + q * cap * 0.8
                if frac <= 0.0:
                    continue
                for i, q in recipe.items():
                    stock[i] = max(0.0, stock.get(i, 0.0) - q * cap * frac)
                q_out = cap * frac
                stock[g] = stock.get(g, 0.0) + q_out
                b["_out"] += q_out * gp - cap * frac * cost
            for bid in bl:
                b = self.burgs[bid]
                self.acc["gdp"][b["state"]] += b.get("_out", 0.0)
                self.acc["pop"][b["state"]] += b["pop"] + b["rural"]

    # ------------------------------------------------------------------ торгівля
    def trade(self, rng):
        cfg = self.w["config"]
        rate = max(0.0, _finite(cfg.get("transport_rate"), 0.012))
        capital_on = bool(self.cfg("capital_constraint", True))
        budget_factor = float(self.cfg("trade_budget_factor", 2.0))
        caravan_share = clamp(_finite(self.cfg("caravan_share"), 0.35), 0.0, 1.0)
        # тимчасові (несеріалізовані) лічильники поточного місяця
        self.imported_this_tick = collections.defaultdict(set)
        self.trade_spent = collections.defaultdict(float)
        # Каравани йдуть готовими магістралями; попарна торгівля нижче —
        # лише «остання миля» й послаблена на маршрутних ребрах.
        self._step_caravans()
        self._dispatch_caravans(rng)
        self.route_edges = set()
        for r in self.w.get("trade_routes", []):
            if isinstance(r, dict):
                self.route_edges.update(int(x) for x in (r.get("edges") or []) if isinstance(x, int))
        for ei, e in enumerate(self.edges):
            if e.get("a") not in self.markets or e.get("b") not in self.markets:
                continue
            ma, mb = self.markets[e["a"]], self.markets[e["b"]]
            sa, sb = self.market_state[e["a"]], self.market_state[e["b"]]
            tmult = self.mm("edge", ei, "trade") * self.mm("market", e["a"], "trade") * self.mm("market", e["b"], "trade")
            if e["sea"]:
                tmult *= self.mm("edge", ei, "piracy")
            if ei in self.route_edges:
                tmult *= caravan_share
            tariff = 0.0
            if sa != sb:
                f = self.trade_friction(sa, sb)
                if f is None:
                    tmult *= 0.04                      # контрабанда під час війни/ембарго
                    tariff = 0.3
                else:
                    tariff = f
            # runtime-модифікатори торгівлі від politics/events (відсутні = 1.0)
            tmult *= self.state_mult(sa, "trade_mod", 1.0) * self.state_mult(sb, "trade_mod", 1.0)
            moved_edge = 0.0
            if tmult > 0.001:
                seaf = 0.45 if e["sea"] else 1.0
                for src, dst, ms, md, sd in ((e["a"], e["b"], ma, mb, sb), (e["b"], e["a"], mb, ma, sa)):
                    eff_tariff = clamp(tariff * self.state_mult(sd, "tariff_mod", 1.0), 0.0, 0.6)
                    for g, ps in ms["price"].items():
                        # імпортоване цього місяця не можна перепродати в тому ж місяці
                        if g in self.imported_this_tick[src]:
                            continue
                        pd = md["price"].get(g)
                        if pd is None:
                            continue
                        gd = self.goods[g]
                        bulk = 1.0
                        for tg in gd["tags"]:
                            bulk *= LD.BULKY_TAGS.get(tg, 1.0)
                        bulk = clamp(bulk, 0.1, 3.0)
                        dist = max(0.0, _finite(e.get("dist"), 0.0))
                        cost = math.sqrt(max(gd["value"], 0.5)) * rate * (dist / 100.0) * bulk * seaf
                        margin = pd * (1 - eff_tariff) - ps - cost
                        if margin <= 0:
                            continue
                        avail = max(0.0, _finite(ms["stock"].get(g, 0.0), 0.0))
                        if avail <= 0.5:
                            continue
                        # попит у кінці маршруту обмежує потік
                        dem = md.get("want", {}).get(g, 0.0)
                        room = max(dem * 2.5 - md["stock"].get(g, 0.0), dem * 0.3)
                        # Модифікатори торгівлі (бум, контрабанда, ...) можуть давати
                        # tmult > 1. Стеля 3.0 разом із лімітом 28% лишає обсяг
                        # у межах реального запасу: 0.28 * 3 = 0.84 < 1.
                        flow_mult = clamp(tmult, 0.0, 3.0)
                        qty = min(avail * 0.28, room if dem > 0 else avail * 0.05) * clamp(margin / max(ps, 0.01), 0.05, 1.0) * flow_mult
                        if capital_on:
                            budget = max(50.0, float(ms.get("capital", 0.0)) * budget_factor)
                            qty = min(qty, (budget - self.trade_spent[src]) / max(ps, 0.01))
                        if qty <= 0.05:
                            continue
                        # велика відстань не може з'їсти більше чверті вантажу
                        loss = clamp(0.01 + (0.02 if "food" in gd["tags"] else 0.0) * (dist / 300.0), 0.0, 0.25)
                        ms["stock"][g] = max(0.0, avail - qty)
                        md["stock"][g] = md["stock"].get(g, 0.0) + qty * (1 - loss)
                        val = qty * ps
                        prof = qty * margin
                        self.imported_this_tick[dst].add(g)
                        self.trade_spent[src] += val
                        self.acc["tariff"][sd] += qty * pd * eff_tariff * 0.6
                        self.acc["trade_val"][sd] += val
                        self.acc["export_val"][self.market_state[src]] += val
                        self.acc["import_val"][sd] += val
                        src_cap = float(ms.get("capital", 0.0))
                        ms["capital"] = max(0.0, src_cap - val + prof * 0.5) if capital_on else src_cap + prof * 0.5
                        md["capital"] = float(md.get("capital", 0.0)) + prof * 0.5
                        moved_edge += val
                        key = (sa, sb) if src == e["a"] else (sb, sa)
                        self.acc["trade_edge"][key] += val
            e["flow"] = round(0.7 * _finite(e.get("flow"), 0.0) + 0.3 * moved_edge, 2)

    # ------------------------------------------------------------------ каравани
    def _caravan_hazard(self, ei, sea):
        trade_m = clamp(_finite(self.mm("edge", ei, "trade"), 1.0), 0.1, 2.0)
        hazard = 1.0 / trade_m
        if sea:
            pir = clamp(_finite(self.mm("edge", ei, "piracy"), 1.0), 0.1, 2.0)
            hazard *= 1.0 / pir
        return clamp(hazard, 0.5, 6.0)

    def _caravan_loss(self, ei, good, sea):
        e = self.edges[ei]
        dist = max(0.0, _finite(e.get("dist"), 0.0))
        tags = good.get("tags", []) if isinstance(good, dict) else []
        loss = 0.01 + (0.02 if "food" in tags else 0.0) * (dist / 300.0)
        if sea:
            loss += 0.015
        return clamp(loss * self._caravan_hazard(ei, sea), 0.0, 0.8)

    def _drop_caravan(self, caravan):
        self.caravans = [c for c in self.caravans if c is not caravan]
        self.w["caravans"] = self.caravans

    def _deliver_caravan(self, caravan):
        mid, g = caravan.get("dest"), caravan.get("good")
        if mid not in self.markets or g not in self.goods:
            self._drop_caravan(caravan)
            return
        qty = max(0.0, _finite(caravan.get("qty"), 0.0))
        if qty <= 0.05:
            self._drop_caravan(caravan)
            return
        m = self.markets[mid]
        m["stock"][g] = m["stock"].get(g, 0.0) + qty
        self.imported_this_tick[mid].add(g)
        self.log("trade", f"Караван прибув у {m['uk']}: {self.goods[g].get('name', g)} ×{qty:.1f}.")
        sd = self.market_state[mid]
        val = qty * _finite(caravan.get("unit_price"), 0.0)
        prof = qty * _finite(caravan.get("margin"), 0.0)
        self.acc["trade_val"][sd] += val
        self.acc["import_val"][sd] += val
        od = caravan.get("origin_state")
        if od is not None:
            self.acc["export_val"][od] += val
            self.acc["trade_edge"][(od, sd)] += val
        if self.cfg("capital_constraint", True):
            om = caravan.get("origin_market")
            if om in self.markets:
                self.markets[om]["capital"] = max(0.0, float(self.markets[om].get("capital", 0.0)) + prof * 0.5)
            m["capital"] = float(m.get("capital", 0.0)) + prof * 0.5
        self._drop_caravan(caravan)

    def _dump_caravan(self, caravan, mid):
        """Війна/ембарго перекрили шлях — вантаж продається на поточному ринку."""
        g, qty = caravan.get("good"), max(0.0, _finite(caravan.get("qty"), 0.0))
        if mid in self.markets and g in self.goods and qty > 0.0:
            m = self.markets[mid]
            m["stock"][g] = m["stock"].get(g, 0.0) + qty
            self.imported_this_tick[mid].add(g)
        om = caravan.get("origin_market")
        if self.cfg("capital_constraint", True) and om in self.markets:
            loss = max(0.0, _finite(caravan.get("unit_price"), 0.0)) * qty * 0.5
            self.markets[om]["capital"] = max(0.0, float(self.markets[om].get("capital", 0.0)) - loss)
        self._drop_caravan(caravan)

    def _dump_caravan_safe(self, caravan, fallback=None):
        """Повертає вантаж на поточний/початковий ринок, якщо маршрут зламано."""
        mid = _as_int(caravan.get("at_market"), -1)
        if mid not in self.markets:
            mid = _as_int(caravan.get("origin_market"), -1)
        if mid not in self.markets:
            mid = fallback
        if mid in self.markets:
            self._dump_caravan(caravan, mid)
        else:
            self._drop_caravan(caravan)

    def _step_caravans(self):
        active = []
        cap_active = int(clamp(_finite(self.cfg("caravan_max_active", 64), 64), 0, 256))
        for c in list(self.caravans):
            if not isinstance(c, dict):
                continue
            rid = _as_int(c.get("route_id"), 0)
            route = self.routes_by_id.get(rid)
            if route is None:
                self._dump_caravan_safe(c)
                continue
            legs, mids = route.get("edges") or [], route.get("markets") or []
            nxt = int(_finite(c.get("leg_index", -1), -1)) + 1
            if nxt < 0 or nxt >= len(legs) or nxt + 1 >= len(mids):
                self._dump_caravan_safe(c, mids[-1] if mids else None)
                continue
            ei = _as_int(legs[nxt], -1)
            if ei < 0 or ei >= len(self.edges):
                self._dump_caravan_safe(c, mids[nxt] if nxt < len(mids) else None)
                continue
            e = self.edges[ei]
            cur_mid, dst_mid = mids[nxt], mids[nxt + 1]
            if cur_mid == e["a"] and dst_mid == e["b"]:
                sd, dd = self.market_state[e["a"]], self.market_state[e["b"]]
            elif cur_mid == e["b"] and dst_mid == e["a"]:
                sd, dd = self.market_state[e["b"]], self.market_state[e["a"]]
            else:
                sd = dd = self.market_state.get(cur_mid)
            friction = self.trade_friction(sd, dd) if sd != dd else 0.0
            if friction is None:
                self._dump_caravan(c, cur_mid)
                continue
            tariff = clamp(friction * self.state_mult(dd, "tariff_mod", 1.0), 0.0, 0.6) if sd != dd else 0.0
            qty = max(0.0, _finite(c.get("qty"), 0.0))
            qty *= 1.0 - self._caravan_loss(ei, self.goods.get(c.get("good")), bool(e.get("sea")))
            c["qty"] = qty
            c["leg_index"] = nxt
            c["at_market"] = dst_mid
            c["next_edge"] = _as_int(legs[nxt + 1], -1) if nxt + 1 < len(legs) else -1
            if qty <= 0.05:
                self._dump_caravan_safe(c, dst_mid)
                continue
            unit = _finite(c.get("unit_price"), 0.0)
            if tariff > 0.0 and sd != dd:
                self.acc["tariff"][dd] += qty * unit * tariff * 0.6
            self.acc["trade_edge"][(sd, dd)] += qty * unit
            if nxt == len(legs) - 1:
                self._deliver_caravan(c)
            else:
                active.append(c)
        self.caravans = active[:cap_active]
        self.w["caravans"] = self.caravans

    def _dispatch_caravans(self, rng):
        if not self.cfg("caravan_enabled", True):
            return
        share = clamp(_finite(self.cfg("caravan_share"), 0.35), 0.0, 1.0)
        if share <= 0.0:
            return
        cap_active = int(clamp(_finite(self.cfg("caravan_max_active", 64), 64), 0, 256))
        rate = max(0.0, _finite(self.cfg("transport_rate"), 0.012))
        capital_on = bool(self.cfg("capital_constraint", True))
        budget_factor = float(self.cfg("trade_budget_factor", 2.0))
        t = self.tick_index()
        for route in self.w.get("trade_routes", []):
            if len(self.caravans) >= cap_active:
                break
            if not isinstance(route, dict):
                continue
            mids, legs = route.get("markets") or [], route.get("edges") or []
            if len(mids) < 2 or not legs:
                continue
            rid = _as_int(route.get("id"), 0)
            if any(_as_int(c.get("route_id"), 0) == rid for c in self.caravans):
                continue
            dist = max(0.0, _finite(route.get("dist"), 0.0))
            seaf = 0.6 if route.get("sea") else 1.0
            for a_mid, b_mid in ((mids[0], mids[-1]), (mids[-1], mids[0])):
                if a_mid not in self.markets or b_mid not in self.markets:
                    continue
                sa, sb = self.market_state[a_mid], self.market_state[b_mid]
                fr = 0.0 if sa == sb else self.trade_friction(sa, sb)
                if fr is None:
                    continue
                tariff = clamp(fr * self.state_mult(sb, "tariff_mod", 1.0), 0.0, 0.6) if sa != sb else 0.0
                ms, md = self.markets[a_mid], self.markets[b_mid]
                best = None
                for g, ps in ms.get("price", {}).items():
                    if g in self.imported_this_tick[a_mid] or g not in self.goods:
                        continue
                    pd = md.get("price", {}).get(g)
                    if pd is None:
                        continue
                    gd = self.goods[g]
                    bulk = 1.0
                    for tg in gd.get("tags", ()):
                        bulk *= LD.BULKY_TAGS.get(tg, 1.0)
                    bulk = clamp(bulk, 0.1, 3.0)
                    cost = math.sqrt(max(_finite(gd.get("value"), 0.5), 0.5)) * rate * (dist / 100.0) * bulk * seaf
                    margin = pd * (1.0 - tariff) - ps - cost
                    if margin <= 0.1:
                        continue
                    avail = _finite(ms.get("stock", {}).get(g), 0.0)
                    if avail <= 1.0:
                        continue
                    dem = _finite(md.get("want", {}).get(g), 0.0)
                    room = max(dem * 3.0 - _finite(md.get("stock", {}).get(g), 0.0), 0.0)
                    if dem > 0.0 and room <= 0.0:
                        continue
                    qty = min(avail * clamp(0.3 * share * 2.0, 0.05, 0.5), room if dem > 0 else avail * 0.05)
                    qty *= clamp(margin / max(ps, 0.01), 0.05, 1.0)
                    if capital_on:
                        budget = max(50.0, _finite(ms.get("capital"), 0.0) * budget_factor)
                        qty = min(qty, max(0.0, (budget - self.trade_spent[a_mid]) / max(ps, 0.01)))
                    if qty <= 0.5:
                        continue
                    score = margin * qty
                    if best is None or score > best[0]:
                        best = (score, g, qty, ps, margin)
                if best is None:
                    continue
                _, g, qty, ps, margin = best
                ms["stock"][g] = max(0.0, _finite(ms.get("stock", {}).get(g), 0.0) - qty)
                val = qty * ps
                self.trade_spent[a_mid] += val
                if capital_on:
                    ms["capital"] = max(0.0, _finite(ms.get("capital"), 0.0) - val)
                self.caravans.append(dict(
                    id=f"c{t}-{rid}-{a_mid}-{b_mid}",
                    route_id=rid, good=g, qty=round(qty, 3), leg_index=-1,
                    at_market=a_mid, origin=a_mid, dest=b_mid,
                    origin_market=a_mid, origin_state=sa,
                    unit_price=ps, margin=margin,
                    eta_days=round(dist / 28.0, 1), created_tick=t,
                    next_edge=_as_int(legs[0], -1) if legs else -1,
                ))
                break

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
        cats = ("food", "utilities", "construction", "luxury")
        elast_on = bool(self.cfg("demand_elasticity_enabled", True))
        elast_k = float(self.cfg("price_elasticity", 0.18))
        for mid, m in self.markets.items():
            stock, price = m["stock"], m["price"]
            want = m["want_now"] = m.get("want_now", {})
            # м'яка еластичність попиту: дорожчий кошик -> менша душова норма
            factors = {}
            for c in cats:
                wsum = wtot = 0.0
                for g in self.cat_goods[c]:
                    wgt = max(m.get("want", {}).get(g, 0.0) + stock.get(g, 0.0) * 0.05, 0.5)
                    ratio = price.get(g, self.goods[g]["value"]) / max(self.goods[g]["value"], 1.0)
                    wsum += ratio * wgt
                    wtot += wgt
                idx = max(wsum / wtot, 1e-6) if wtot else 1.0
                factors[c] = clamp(idx ** -elast_k, 0.55, 1.45) if elast_on else 1.0
            # відсортовані пропозиції по категоріях
            lists = {}
            for c in cats:
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
                    "food": k * dpc["food"] * factors["food"] * self.mm("burg", bid, "food_need"),
                    "utilities": k * dpc["utilities"] * factors["utilities"] * (1 + 0.9 * cold)
                    * self.mm("state", sid, "util_need"),
                    "construction": k * dpc["construction"] * factors["construction"]
                    * (0.6 + LD.URBAN_CONSTR_BOOST * urb) * self.mm("burg", bid, "rebuild")
                    * self.mm("state", sid, "rebuild"),
                    "luxury": k * dpc["luxury"] * factors["luxury"] * (0.4 + LD.URBAN_LUXURY_BOOST * urb)
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
                            stock[g] = max(0.0, avail - qty)
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
            # планова військова потреба (mil_k, через mil_demand_units) — лише ціновий сигнал;
            # фактичне списання військових товарів робить politics.step_finance()
            mil_goods = self.cat_goods.get("military", [])
            if mil_goods:
                for sid, st in self.states.items():
                    cb = self.burgs.get(st.get("capital"))
                    if not cb or cb.get("market") != mid:
                        continue
                    units = self.mil_demand_units(sid)
                    if units <= 0:
                        continue
                    cheapest = sorted(mil_goods, key=lambda g: price.get(g, self.goods[g]["value"])
                                      / max(self.goods[g]["cover"].get("military", 1.0), 1e-6))[:3]
                    share = units * 0.35 / len(cheapest)
                    for g in cheapest:
                        cv = max(self.goods[g]["cover"].get("military", 1.0), 1e-6)
                        want[g] = want.get(g, 0.0) + share / cv
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
                wnt = want.get(g, 0.0)
                base = d["value"]
                target = wnt * COVER_MONTHS
                # Storage overflow: a stockpile many months beyond local demand
                # wastes away (spoilage, theft, upkeep). Without this, raw goods
                # with a large fixed output (e.g. hemp) grow without bound and
                # crowd every other good out of the market. The ceiling scales
                # with real demand, so staples with genuine consumption are safe.
                ceiling = max(target * 8.0, 50.0)
                if s > ceiling:
                    s = ceiling + (s - ceiling) * 0.6
                stock[g] = s
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
        carry = max(1.01, float(self.cfg("carry_cap", 1.65)))
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
                # мінімальний підйом для зруйнованих міст (не діє при ratio >= 1, тобто не веде до перевищення капу)
                recovery = 1.0 + 0.02 * clamp(1.0 - ratio, 0.0, 1.0) * clamp((fs - 0.4) / 0.6, 0.0, 1.0)
                growth_factor = max(growth_factor, recovery)
            else:
                # Плавне сповільнення приросту; на carry_cap*pop0 приріст стає рівним нулю
                growth_factor = clamp(1.0 - (ratio - 1.0) / max(carry - 1.0, 0.01), 0.0, 1.0)
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
            # сирий ВВП може бути від'ємним (збиткове ремесло); для історії/відображення показуємо 0
            st["gdp"] = round(max(0.0, self.acc["gdp"].get(sid, 0.0)), 2)
            st["pop"] = round(self.acc["pop"].get(sid, 0.0))
            row[sid] = [st["gdp"], st["pop"], round(st["treasury"], 1), round(st["stability"], 1),
                        st["food_sat"], round(self.state_power(sid), 1)]
        h["states"].append([t, row])
        if len(h["states"]) > 240:
            del h["states"][:len(h["states"]) - 240]
        tot_pop = sum(self.acc["pop"].values())
        tot_gdp = max(0.0, sum(self.acc["gdp"].values()))
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

