# -*- coding: utf-8 -*-
"""Спільний граф ринкових шляхів і генератор магістралей для караванів.

Джерело графа — ``world["edges"]``, імPORTований з Azgaar ``trade``
(див. importer.py). Той самий граф використовує й D&D-калькулятор, тож
караван і маршрут Майстра гри йдуть одними й тими самими дорогами.
"""
import collections
import heapq
import json
import math
import os

from . import lore_data as LD

_KIND_GRAPH_W = {"road": 0.78, "trail": 1.05, "sea": 1.25, "prospective": 1.65}


def _road_build_cost(e):
    dist = max(10.0, _num(e.get("dist"), 50.0))
    kind = e.get("kind") or ("sea" if e.get("sea") else "trail")
    mult = 1.6 if kind == "trail" else 3.0
    return float(round(max(60.0, dist * mult)))


def simplify_polyline(pts, max_pts=18):
    """Стискає полілінію маршруту до max_pts опорних точок зі збереженням кінців."""
    clean = []
    for p in pts or ():
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            x, y = round(_num(p[0]), 1), round(_num(p[1]), 1)
            if not clean or clean[-1] != [x, y]:
                clean.append([x, y])
    if len(clean) <= max_pts or max_pts < 2:
        return clean
    step = (len(clean) - 1) / (max_pts - 1)
    out = [clean[0]]
    for i in range(1, max_pts - 1):
        pt = clean[int(round(i * step))]
        if pt != out[-1]:
            out.append(pt)
    if clean[-1] != out[-1]:
        out.append(clean[-1])
    return out


def _edge_midpoint(pts):
    if not pts:
        return 0.0, 0.0
    if len(pts) == 1:
        return float(pts[0][0]), float(pts[0][1])
    if len(pts) >= 3:
        m = pts[len(pts) // 2]
        return float(m[0]), float(m[1])
    return round((pts[0][0] + pts[-1][0]) * 0.5, 1), round((pts[0][1] + pts[-1][1]) * 0.5, 1)


def _trace_route_paths(pairs_by_src, mk_xy, routes_raw, land_only):
    """Будує граф доріг/стежок/морських шляхів із FMG pack.routes і знаходить шляхи."""
    if not routes_raw or not pairs_by_src:
        return {}
    adj = collections.defaultdict(list)
    for r in routes_raw:
        if not isinstance(r, dict):
            continue
        grp = r.get("group") or "trails"
        if land_only and grp == "searoutes":
            continue
        pts = r.get("points") or []
        if len(pts) < 2:
            continue
        w_mult = 1.0 if grp == "roads" else (1.20 if grp == "searoutes" else 1.50)
        for k in range(len(pts) - 1):
            p1, p2 = pts[k], pts[k + 1]
            if not (isinstance(p1, (list, tuple)) and isinstance(p2, (list, tuple)) and len(p1) >= 2 and len(p2) >= 2):
                continue
            n1 = (round(float(p1[0]), 1), round(float(p1[1]), 1))
            n2 = (round(float(p2[0]), 1), round(float(p2[1]), 1))
            if n1 == n2:
                continue
            d = math.hypot(n2[0] - n1[0], n2[1] - n1[1])
            adj[n1].append((n2, d * w_mult, d, grp))
            adj[n2].append((n1, d * w_mult, d, grp))
    if not adj:
        return {}

    nodes = list(adj.keys())
    mk_node = {}
    needed_mids = set(pairs_by_src) | {v for vs in pairs_by_src.values() for v in vs}
    for mid in needed_mids:
        cx, cy = mk_xy[mid][0], mk_xy[mid][1]
        best = min(nodes, key=lambda n: (n[0] - cx) ** 2 + (n[1] - cy) ** 2)
        if math.hypot(best[0] - cx, best[1] - cy) <= 65.0:
            mk_node[mid] = best

    out = {}
    for src, targets in pairs_by_src.items():
        start = mk_node.get(src)
        if start is None:
            continue
        target_nodes = {mk_node[t]: t for t in targets if t in mk_node}
        if not target_nodes:
            continue
        max_straight = max(
            math.hypot(mk_xy[src][0] - mk_xy[t][0], mk_xy[src][1] - mk_xy[t][1])
            for t in targets if t in mk_node
        )
        cost_limit = max(120.0, max_straight * 3.8)
        dist = {start: 0.0}
        prev = {}
        pq = [(0.0, start)]
        remaining = set(target_nodes)
        while pq and remaining:
            c, u = heapq.heappop(pq)
            if c > cost_limit:
                break
            if c > dist.get(u, math.inf) + 1e-9:
                continue
            if u in remaining:
                remaining.remove(u)
                if not remaining:
                    break
            for v, wc, ed, grp in adj[u]:
                nc = c + wc
                if nc < dist.get(v, math.inf) - 1e-9:
                    dist[v] = nc
                    prev[v] = (u, ed, grp)
                    heapq.heappush(pq, (nc, v))
        for tnode, dst in target_nodes.items():
            if tnode not in dist:
                continue
            pts = [tnode]
            cur = tnode
            tot_d = 0.0
            grps = collections.Counter()
            while cur in prev:
                pu, ed, grp = prev[cur]
                pts.append(pu)
                tot_d += ed
                grps[grp] += ed
                cur = pu
            pts.reverse()
            pair = (min(src, dst), max(src, dst))
            if src > dst:
                pts.reverse()
            out[pair] = dict(dist=tot_d, grps=grps, pts=pts)
    return out


def build_geographic_edges(markets, mk_center, pair_units, routes_raw=None, dist_scale=3.0):
    """Будує планарну географічну мережу ринків (дороги, стежки, морські та перспективні)."""
    mids = sorted(markets)
    if len(mids) <= 1:
        return []

    mk_xy = {}
    for mid in mids:
        cb = mk_center[mid]
        mk_xy[mid] = (
            float(cb.get("x", 0.0)),
            float(cb.get("y", 0.0)),
            cb.get("feature"),
            bool(cb.get("port")),
            max(1.0, float(cb.get("pop", 0.0)) + float(cb.get("rural", 0.0))),
        )

    # 1) Сухопутні сусіди за графом Габріеля в межах одного континенту/острова
    land_pairs = set()
    for i, a in enumerate(mids):
        ax, ay, af, _, _ = mk_xy[a]
        for b in mids[i + 1:]:
            bx, by, bf, _, _ = mk_xy[b]
            if af != bf:
                continue
            d2 = (ax - bx) ** 2 + (ay - by) ** 2
            blocked = False
            for c in mids:
                if c == a or c == b or mk_xy[c][2] != af:
                    continue
                cx, cy = mk_xy[c][0], mk_xy[c][1]
                if ((ax - cx) ** 2 + (ay - cy) ** 2 + (bx - cx) ** 2 + (by - cy) ** 2) < d2 * 1.02:
                    blocked = True
                    break
            if not blocked:
                land_pairs.add((a, b))

    # 2) Морські маршрути: 2 найближчі порти + 1 головний морський партнер із trade_raw
    port_mids = [m for m in mids if mk_xy[m][3]]
    sea_pairs = set()
    for a in port_mids:
        ax, ay, af, _, _ = mk_xy[a]
        cands = []
        best_vol = None
        for b in port_mids:
            if a == b:
                continue
            pair = (min(a, b), max(a, b))
            if pair in land_pairs:
                continue
            bx, by, bf, _, _ = mk_xy[b]
            d = math.hypot(ax - bx, ay - by)
            cands.append((d * (0.85 if af != bf else 1.0), pair))
            vol = float(pair_units.get(pair, 0.0))
            if vol > 0 and (best_vol is None or vol > best_vol[0]):
                best_vol = (vol, pair)
        cands.sort()
        for _, pair in cands[:2]:
            sea_pairs.add(pair)
        if best_vol is not None:
            sea_pairs.add(best_vol[1])

    all_pairs = land_pairs | sea_pairs

    # 3) Зв'язність усього графа (MST-містки для ізольованих островів/анклавів)
    adj = collections.defaultdict(set)
    for a, b in all_pairs:
        adj[a].add(b)
        adj[b].add(a)

    def _comps():
        seen, out = set(), []
        for m in mids:
            if m in seen:
                continue
            comp, st = set(), [m]
            while st:
                x = st.pop()
                if x in comp:
                    continue
                comp.add(x)
                st.extend(adj[x])
            seen |= comp
            out.append(comp)
        return out

    cs = _comps()
    while len(cs) > 1:
        a_comp, rest = cs[0], cs[1:]
        best = None
        for m1 in a_comp:
            x1, y1, f1, p1, _ = mk_xy[m1]
            for c_comp in rest:
                for m2 in c_comp:
                    x2, y2, f2, p2, _ = mk_xy[m2]
                    d = math.hypot(x1 - x2, y1 - y2)
                    # віддаємо перевагу морю через порти або найближчому сухопутному переходу
                    score = d * (0.85 if (f1 != f2 and p1 and p2) else 1.0)
                    if best is None or score < best[0]:
                        best = (score, m1, m2)
        _, m1, m2 = best
        pair = (min(m1, m2), max(m1, m2))
        if mk_xy[m1][2] == mk_xy[m2][2] and not (mk_xy[m1][3] and mk_xy[m2][3]):
            land_pairs.add(pair)
        else:
            sea_pairs.add(pair)
        all_pairs.add(pair)
        adj[m1].add(m2)
        adj[m2].add(m1)
        cs = _comps()

    # 4) Трасування реальних доріг/стежок/морських ліній з pack.routes
    land_by_src = collections.defaultdict(list)
    for a, b in sorted(land_pairs):
        land_by_src[a].append(b)
    sea_by_src = collections.defaultdict(list)
    for a, b in sorted(sea_pairs):
        sea_by_src[a].append(b)

    traced_land = _trace_route_paths(land_by_src, mk_xy, routes_raw or (), land_only=True)
    traced_sea = _trace_route_paths(sea_by_src, mk_xy, routes_raw or (), land_only=False)

    edges = []
    has_raw_routes = bool(routes_raw and (traced_land or traced_sea))
    for a, b in sorted(all_pairs):
        ax, ay, _, _, pop_a = mk_xy[a]
        bx, by, _, _, pop_b = mk_xy[b]
        straight = max(1.0, math.hypot(ax - bx, ay - by))
        is_sea = (a, b) in sea_pairs and (a, b) not in land_pairs
        raw_cap = float(pair_units.get((a, b), 0.0))
        if raw_cap <= 0.0:
            raw_cap = max(6.0, math.sqrt((pop_a / 1000.0) * (pop_b / 1000.0)) * 0.65)

        if is_sea:
            tr = traced_sea.get((a, b))
            if tr and tr["dist"] <= straight * 2.5 and len(tr["pts"]) >= 2:
                pts = simplify_polyline([[ax, ay]] + tr["pts"] + [[bx, by]], max_pts=18)
                d_map = tr["dist"]
            else:
                pts = [[round(ax, 1), round(ay, 1)], [round(bx, 1), round(by, 1)]]
                d_map = straight
            kind = "sea"
        else:
            tr = traced_land.get((a, b))
            if has_raw_routes:
                if tr and tr["dist"] <= straight * 2.25 and len(tr["pts"]) >= 2:
                    pts = simplify_polyline([[ax, ay]] + tr["pts"] + [[bx, by]], max_pts=18)
                    d_map = tr["dist"]
                    r_share = tr["grps"].get("roads", 0.0) / max(d_map, 1e-6)
                    kind = "road" if r_share >= 0.40 else "trail"
                else:
                    pts = [[round(ax, 1), round(ay, 1)], [round(bx, 1), round(by, 1)]]
                    d_map = straight
                    kind = "prospective"
            else:
                pts = [[round(ax, 1), round(ay, 1)], [round(bx, 1), round(by, 1)]]
                d_map = straight
                kind = "trail"

        edges.append(dict(
            a=a, b=b,
            dist=round(d_map * dist_scale, 1),
            cap=round(raw_cap, 2),
            sea=bool(is_sea),
            kind=kind,
            pts=pts,
            flow=0.0,
        ))

    if not has_raw_routes:
        land_edges = [e for e in edges if not e["sea"]]
        if land_edges:
            caps = sorted(e["cap"] for e in land_edges)
            med_cap = caps[len(caps) // 2]
            for e in land_edges:
                if e["cap"] >= med_cap and len(land_edges) >= 2:
                    e["kind"] = "road"
            if len(land_edges) >= 3:
                weakest = max(land_edges, key=lambda e: e["dist"] / max(e["cap"], 1.0))
                weakest["kind"] = "prospective"

    return edges


def _load_routes_for_world(sim):
    meta = sim.w.get("meta") or {}
    src = meta.get("source_file") or ""
    if not src:
        return []
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands = [os.path.join(pkg_root, "save", "maps", src)]
    jpath = getattr(sim, "journal_path", "") or meta.get("journal_file") or ""
    if jpath:
        cands.insert(0, os.path.join(os.path.dirname(os.path.abspath(jpath)), "maps", src))
    if meta.get("is_feria"):
        maps_dir = os.path.join(pkg_root, "save", "maps")
        if os.path.isdir(maps_dir):
            for fn in sorted(os.listdir(maps_dir)):
                if fn.lower().endswith((".map", ".gz")):
                    p_cand = os.path.join(maps_dir, fn)
                    if p_cand not in cands:
                        cands.append(p_cand)
    for p in cands:
        if os.path.isfile(p):
            try:
                from .importer import read_map_text
                txt = read_map_text(p)
                for line in txt.splitlines():
                    if '"group"' in line and '"points"' in line and line.lstrip().startswith("["):
                        obj = json.loads(line)
                        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "points" in obj[0]:
                            return obj
            except Exception:
                return []
    return []


def upgrade_legacy_edges(sim):
    """Перетворює застарілі хордові зв'язки сейву на географічну мережу доріг."""
    if len(sim.markets) <= 1:
        return False
    edges = sim.edges
    bloated = len(edges) > max(16, int(len(sim.markets) * 2.8))
    missing = any(not isinstance(e, dict) or "kind" not in e or "pts" not in e for e in edges)
    if not (not edges or bloated or missing):
        return False

    old_flow = {}
    pair_units = collections.Counter()
    for e in edges:
        if not isinstance(e, dict):
            continue
        a, b = e.get("a"), e.get("b")
        if a in sim.markets and b in sim.markets and a != b:
            pair = (min(a, b), max(a, b))
            old_flow[pair] = max(old_flow.get(pair, 0.0), _num(e.get("flow"), 0.0))
            pair_units[pair] += max(0.0, _num(e.get("cap"), 0.0))

    mk_center = {
        mid: sim.burgs[m["center"]]
        for mid, m in sim.markets.items()
        if m.get("center") in sim.burgs
    }
    if len(mk_center) != len(sim.markets):
        return False

    dist_scale = _num((sim.w.get("meta") or {}).get("units", {}).get("distance", {}).get("scale"), 3.0)
    if dist_scale <= 0:
        dist_scale = 3.0
    routes_raw = _load_routes_for_world(sim)
    new_edges = build_geographic_edges(sim.markets, mk_center, pair_units, routes_raw=routes_raw, dist_scale=dist_scale)
    for e in new_edges:
        pair = (e["a"], e["b"])
        if pair in old_flow:
            e["flow"] = round(old_flow[pair], 2)

    for m in sim.markets.values():
        m["edges"] = []
    for ei, e in enumerate(new_edges):
        sim.markets[e["a"]]["edges"].append(ei)
        sim.markets[e["b"]]["edges"].append(ei)
    sim.w["edges"] = new_edges
    sim.edges = new_edges
    return True


def recommend_roads(sim, limit=10):
    """Ранжує перспективні сухопутні дороги (стежки чи відсутні прямі шляхи) для будівництва."""
    m_pops = {}
    for mid, m in sim.markets.items():
        m_pops[mid] = sum(
            max(0.0, _num(sim.burgs[bid].get("pop"), 0.0) + _num(sim.burgs[bid].get("rural"), 0.0))
            for bid in m.get("burgs", ()) if bid in sim.burgs
        )
    recs = []
    for ei, e in enumerate(sim.edges):
        if e.get("sea"):
            continue
        kind = e.get("kind") or "trail"
        if kind not in ("trail", "prospective"):
            continue
        a, b = e.get("a"), e.get("b")
        if a not in sim.markets or b not in sim.markets:
            continue
        ma, mb = sim.markets[a], sim.markets[b]
        sa, sb = sim.market_state.get(a), sim.market_state.get(b)
        dist = max(10.0, _num(e.get("dist"), 50.0))
        pop_a = max(1000.0, m_pops.get(a, 1000.0))
        pop_b = max(1000.0, m_pops.get(b, 1000.0))
        gravity = math.sqrt((pop_a / 1000.0) * (pop_b / 1000.0)) / max(dist / 80.0, 0.5)

        comp_items = []
        pa, pb = ma.get("price", {}), mb.get("price", {})
        ka, kb = ma.get("stock", {}), mb.get("stock", {})
        for g in sim.goods:
            va = _num(pa.get(g), 0.0)
            vb = _num(pb.get(g), 0.0)
            if va > 0 and vb > va * 1.12 and _num(ka.get(g), 0.0) > 1.0:
                comp_items.append(((vb - va) * min(20.0, _num(ka.get(g), 0.0) * 0.25), g))
            elif vb > 0 and va > vb * 1.12 and _num(kb.get(g), 0.0) > 1.0:
                comp_items.append(((va - vb) * min(20.0, _num(kb.get(g), 0.0) * 0.25), g))
        comp_items.sort(reverse=True)
        comp_score = sum(v for v, _ in comp_items[:5])
        top_goods = [LD.good_uk(g, sim.goods) for _, g in comp_items[:3]]

        flow = max(0.0, _num(e.get("flow"), 0.0))
        potential = round(gravity * 1.8 + comp_score + flow * 0.12 + (80.0 if kind == "prospective" else 35.0), 1)
        cost_zm = _road_build_cost(e)
        roi = round(potential / max(cost_zm, 1.0), 2)
        pts = e.get("pts")
        if not pts:
            ca, cb = sim.burgs[ma["center"]], sim.burgs[mb["center"]]
            pts = [[round(ca["x"], 1), round(ca["y"], 1)], [round(cb["x"], 1), round(cb["y"], 1)]]
        mx, my = _edge_midpoint(pts)
        recs.append(dict(
            edge_index=ei,
            a=a, b=b, a_uk=ma.get("uk", str(a)), b_uk=mb.get("uk", str(b)),
            state_a=sa, state_b=sb,
            state_a_uk=sim.sname(sa) if sa in sim.states else "—",
            state_b_uk=sim.sname(sb) if sb in sim.states else "—",
            kind=kind,
            action_uk="Прокласти новий тракт" if kind == "prospective" else "Розбудувати стежку до тракту",
            dist=round(dist, 1),
            flow=round(flow, 1),
            potential=potential,
            cost_zm=cost_zm,
            roi=roi,
            goods=top_goods,
            pts=pts,
            mid_x=mx, mid_y=my,
        ))
    recs.sort(key=lambda r: (-r["roi"], -r["potential"], r["edge_index"]))
    return recs[:max(1, int(limit))]


def build_road(sim, edge_index):
    """Будує або модернізує сухопутний шлях (edge_index) до повноцінного тракту."""
    idx = int(edge_index)
    if idx < 0 or idx >= len(sim.edges):
        raise ValueError("Маршрут не знайдено")
    e = sim.edges[idx]
    if e.get("sea"):
        raise ValueError("Неможливо прокласти суходільну дорогу по морському маршруту")
    if e.get("kind") == "road":
        raise ValueError("На цьому маршруті вже є капітальний тракт")

    cost_zm = _road_build_cost(e)
    a, b = e["a"], e["b"]
    sa, sb = sim.market_state.get(a), sim.market_state.get(b)
    if sa in sim.states and sb in sim.states and sa != sb:
        half = cost_zm * 0.5
        sim.states[sa]["treasury"] = max(0.0, float(sim.states[sa].get("treasury", 0.0)) - half)
        sim.states[sb]["treasury"] = max(0.0, float(sim.states[sb].get("treasury", 0.0)) - half)
    elif sa in sim.states:
        sim.states[sa]["treasury"] = max(0.0, float(sim.states[sa].get("treasury", 0.0)) - cost_zm)
    elif sb in sim.states:
        sim.states[sb]["treasury"] = max(0.0, float(sim.states[sb].get("treasury", 0.0)) - cost_zm)

    e["kind"] = "road"
    e["cap"] = round(max(_num(e.get("cap"), 10.0) * 1.5, 25.0), 2)
    ma_uk = sim.markets.get(a, {}).get("uk", str(a))
    mb_uk = sim.markets.get(b, {}).get("uk", str(b))
    sim.log("trade", f"Збудовано торговий тракт {ma_uk} — {mb_uk} (бюджет {LD.fmt_coins(cost_zm)}).",
            states=[s for s in {sa, sb} if s in sim.states], sev=2)
    ensure_highways(sim, rebuild=True)
    return e, cost_zm


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
        kind = e.get("kind") or ("sea" if sea else "trail")
        kw = _KIND_GRAPH_W.get(kind, 1.25 if sea else 1.0)
        w = max(dist, 1.0) / math.sqrt(cap) * kw
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
