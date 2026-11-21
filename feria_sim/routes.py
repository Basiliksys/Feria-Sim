# -*- coding: utf-8 -*-
"""Спільний граф ринкових шляхів і генератор магістралей для караванів.

Джерело графа — ``world["edges"]``, імPORTований з Azgaar ``trade``
(див. importer.py). Той самий граф використовує й D&D-калькулятор, тож
караван і маршрут Майстра гри йдуть одними й тими самими дорогами.
"""
import heapq
import math


def _num(value, default=0.0):
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return v if math.isfinite(v) else default


def _clamp(x, a, b):
    return a if x < a else b if x > b else x


def market_graph(sim):
    """Суміжність ринків: mid -> [(сусід, ei, вага, dist, sea), ...]."""
    adj = {mid: [] for mid in sim.markets}
    for ei, e in enumerate(sim.edges):
        a, b = e.get("a"), e.get("b")
        if a not in adj or b not in adj:
            continue
        dist = max(0.0, _num(e.get("dist"), 0.0))
        cap = max(0.1, _num(e.get("cap"), 1.0))
        sea = bool(e.get("sea"))
        # Штраф за море означає, що суша переважає, якщо різниця невелика.
        w = max(dist, 1.0) / math.sqrt(cap) * (1.25 if sea else 1.0)
        adj[a].append((b, ei, w, dist, sea))
        adj[b].append((a, ei, w, dist, sea))
    return adj


def shortest_path(sim, a, b, adj=None):
    """Найдешевший ланцюг ребер між ринками; список ei або None."""
    if a == b:
        return []
    if a not in sim.markets or b not in sim.markets:
        return None
    adj = market_graph(sim) if adj is None else adj
    best = {a: 0.0}
    prev = {}
    pq = [(0.0, a)]
    while pq:
        cost, u = heapq.heappop(pq)
        if cost > best.get(u, math.inf) + 1e-9:
            continue
        if u == b:
            break
        for v, ei, w, _dist, _sea in adj.get(u, ()):
            nd = cost + w
            if nd < best.get(v, math.inf) - 1e-9:
                best[v] = nd
                prev[v] = (u, ei)
                heapq.heappush(pq, (nd, v))
    if b not in prev:
        return None
    out = []
    cur = b
    while cur != a:
        u, ei = prev[cur]
        out.append(ei)
        cur = u
    out.reverse()
    return out


def _market_weight(sim, mid):
    m = sim.markets.get(mid, {})
    total = 0.0
    for bid in m.get("burgs", ()) or ():
        b = sim.burgs.get(bid, {})
        total += _num(b.get("pop"), 0.0) + _num(b.get("rural"), 0.0)
    cb = sim.burgs.get(m.get("center"), {})
    total += (_num(cb.get("pop"), 0.0) + _num(cb.get("rural"), 0.0)) * 0.5
    return total


def generate_highways(sim, hub_count=5, max_routes=24):
    """Будує реєстр іменних магістралей між столицями й найбільшими ринками."""
    if not sim.markets or not sim.edges:
        return []
    capitals = set()
    for st in sim.states.values():
        cap_burg = sim.burgs.get(st.get("capital"), {})
        mid = cap_burg.get("market")
        if mid in sim.markets:
            capitals.add(mid)
    weights = {mid: _market_weight(sim, mid) for mid in sim.markets}
    ranked = sorted(
        sim.markets,
        key=lambda mid: -(weights.get(mid, 0.0) * (1.35 if mid in capitals else 1.0)),
    )
    hub_limit = max(6, int(_num(hub_count, 5)) * 2)
    hubs = ranked[:hub_limit]
    if len(hubs) < 2:
        return []

    adj = market_graph(sim)
    seen = set()
    drafts = []
    for i, a in enumerate(hubs):
        for b in hubs[i + 1:]:
            legs = shortest_path(sim, a, b, adj)
            if not legs:
                continue
            key = frozenset(legs)
            if key in seen:
                continue
            seen.add(key)
            markets = [a]
            for ei in legs:
                e = sim.edges[ei]
                markets.append(e["b"] if e["a"] == markets[-1] else e["a"])
            dist = sum(max(0.0, _num(sim.edges[ei].get("dist"), 0.0)) for ei in legs)
            cap = min(max(0.1, _num(sim.edges[ei].get("cap"), 1.0)) for ei in legs)
            sea = any(bool(sim.edges[ei].get("sea")) for ei in legs)
            ua = sim.markets.get(a, {}).get("uk", str(a))
            ub = sim.markets.get(b, {}).get("uk", str(b))
            drafts.append(dict(
                markets=markets, edges=list(legs),
                dist=round(dist, 1), cap=round(cap, 2), sea=bool(sea),
                name=f"Шлях {ua} → {ub}",
            ))

    # Спочатку міцні й не надто довгі магістралі.
    drafts.sort(key=lambda r: -(r["cap"] * 100.0 / (r["dist"] / 100.0 + 1.0)))
    out = []
    for idx, r in enumerate(drafts[:max(1, int(_num(max_routes, 24)))], 1):
        r["id"] = idx
        out.append(r)
    return out


def _valid_route(r, sim):
    """Відсіює маршрути з неіснуючими ринками/ребрами або NaN у полях."""
    if not isinstance(r, dict):
        return False
    try:
        rid = int(r["id"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    mids, legs = r.get("markets"), r.get("edges")
    if not isinstance(mids, (list, tuple)) or not isinstance(legs, (list, tuple)):
        return False
    if len(mids) < 2 or not legs or len(mids) != len(legs) + 1:
        return False
    if any(m not in sim.markets for m in mids):
        return False
    for ei in legs:
        try:
            idx = int(ei)
        except (TypeError, ValueError, OverflowError):
            return False
        if idx < 0 or idx >= len(sim.edges):
            return False
    for k in ("dist", "cap"):
        raw = r.get(k)
        try:
            if not math.isfinite(float(raw)):
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    r["id"] = rid
    r["markets"] = list(mids)
    r["edges"] = [int(x) for x in legs]
    r["dist"] = _num(r.get("dist"), 0.0)
    r["cap"] = _num(r.get("cap"), 0.0)
    r["sea"] = bool(r.get("sea"))
    r["name"] = str(r.get("name", ""))
    return True


def ensure_highways(sim, rebuild=False):
    """Гарантує наявність реєстру маршрутів у світі; повертає dict за id."""
    w = sim.w
    routes = w.get("trade_routes")
    clean = [r for r in routes if _valid_route(r, sim)] if isinstance(routes, list) else []
    if rebuild or not clean:
        hub_count = int(_clamp(_num(sim.cfg("caravan_hub_count", 5), 5), 2, 12))
        clean = generate_highways(sim, hub_count=hub_count)
    w["trade_routes"] = clean
    return {int(r["id"]): r for r in clean}
