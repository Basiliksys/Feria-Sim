# -*- coding: utf-8 -*-
"""Локальний веб-сервер та JSON API для відслідковування й керування симуляцією Ферії."""
import base64
import gzip
import json
import os
import random
import re
import shutil
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import lore_data as LD
from . import engine as E
from . import importer as IM
from . import worldgen as WG
from . import politics as PO
from . import events as EV
from . import report as RP
from . import dnd_tools as DT

UI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")


class AppState:
    def __init__(self, world_file, journal_file, vault=None):
        self.world_file = world_file
        self.journal_file = journal_file
        self.save_dir = os.path.dirname(os.path.abspath(world_file))
        self.maps_dir = os.path.join(self.save_dir, "maps")
        self.geo_file = os.path.join(self.save_dir, "map_geo.json")
        self.undo_dir = os.path.join(self.save_dir, "undo")
        self.slots_dir = os.path.join(self.save_dir, "slots")
        self.overrides_file = os.path.join(os.path.dirname(self.save_dir), "data", "overrides.json")
        self.vault = vault
        self.lock = threading.RLock()
        self.sim = E.Sim(E.load_world(world_file))
        self._ensure_geo()

    def _ensure_geo(self):
        if os.path.exists(self.geo_file):
            return
        src = self.sim.w.get("meta", {}).get("source_file", "")
        cand = ""
        for m in self._list_saved_maps():
            if m["name"] == src and os.path.exists(m["path"]):
                cand = m["path"]
                break
        if not cand:
            default_map = os.path.join(os.path.expanduser("~"), "Downloads", "Feria 2026-09-21-12-26.map")
            if self.sim.w.get("meta", {}).get("is_feria") and os.path.exists(default_map):
                cand = default_map
        geo = IM.extract_map_geometry(cand, self.sim.w)
        IM.save_map_geo(geo, self.geo_file)

    def _list_saved_maps(self):
        out = []
        default_map = os.path.join(os.path.expanduser("~"), "Downloads", "Feria 2026-09-21-12-26.map")
        if os.path.exists(default_map):
            out.append(dict(name=os.path.basename(default_map), path=default_map, builtin=True))
        if os.path.isdir(self.maps_dir):
            for fn in sorted(os.listdir(self.maps_dir)):
                if fn.lower().endswith((".map", ".json", ".gz")):
                    out.append(dict(name=fn, path=os.path.join(self.maps_dir, fn), builtin=False))
        return out

    def save(self):
        new = self.sim.w.pop("_new_journal", [])
        if new:
            os.makedirs(os.path.dirname(self.journal_file), exist_ok=True)
            with open(self.journal_file, "a", encoding="utf-8") as f:
                for r in new:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        E.save_world(self.sim.w, self.world_file)

    def overview(self):
        with self.lock:
            sim = self.sim
            w = sim.w
            states_out = []
            for sid, st in sim.states.items():
                s = RP.state_summary(sim, sid)
                cb = sim.burgs.get(st["capital"], {})
                states_out.append(dict(
                    id=sid, uk=st["uk"], name=st["name"], cont=st["continent"], color=st["color"],
                    form=st["gov_text"], pop=round(s["pop"]), gdp=round(s["gdp"], 1),
                    treasury=round(s["treasury"], 1), debt=round(s["debt"], 1),
                    stab=round(s["stab"], 1), leg=round(st["legitimacy"], 1),
                    power=round(s["power"], 1), food=round(st["food_sat"] * 100, 1),
                    food_idx=round(sim.price_index("food", sid), 2),
                    rev=round(s["rev"], 1), exp=round(s["exp"], 1),
                    ruler=st["ruler"]["name"], cap=cb.get("uk", ""), cx=cb.get("x", 0), cy=cb.get("y", 0),
                    wars=len(PO.in_war(sim, sid)),
                ))
            states_out.sort(key=lambda x: -x["gdp"])
            markets_out = []
            for mid, m in sim.markets.items():
                cb = sim.burgs[m["center"]]
                sid = sim.market_state[mid]
                markets_out.append(dict(
                    id=mid, uk=m["uk"], x=cb["x"], y=cb["y"], state=sid, state_uk=sim.sname(sid),
                    burgs=len(m["burgs"]), port=cb["port"],
                    food_idx=round(sim.price_index("food", sid), 2),
                ))
            burgs_out = [dict(
                id=b["id"], uk=b["uk"], name=b["name"], x=b["x"], y=b["y"], state=b["state"],
                color=sim.states[b["state"]]["color"], pop=round(b["pop"] + b["rural"]),
                cap=b["capital"], port=b["port"], market=b["market"],
            ) for b in sim.burgs.values()]
            edges_out = [dict(
                a=e["a"], b=e["b"], sea=e["sea"], flow=e.get("flow", 0), dist=e["dist"],
                ax=sim.burgs[sim.markets[e["a"]]["center"]]["x"],
                ay=sim.burgs[sim.markets[e["a"]]["center"]]["y"],
                bx=sim.burgs[sim.markets[e["b"]]["center"]]["x"],
                by=sim.burgs[sim.markets[e["b"]]["center"]]["y"],
            ) for e in sim.edges]
            wars_out = [dict(
                id=wr["id"], name=wr["name"], score=round(wr["score"], 1),
                since=f"{LD.MONTHS_UK[wr['start_month']-1][:3]} {wr['start_year']}",
                attackers=[dict(id=x, uk=sim.sname(x)) for x in wr["attackers"]],
                defenders=[dict(id=x, uk=sim.sname(x)) for x in wr["defenders"]],
                captured=[sim.bname(bid) for bid in wr["captured"]],
                casus=wr.get("casus", ""),
            ) for wr in w["wars"]]
            t = sim.tick_index()
            events_active = [dict(
                key=e["key"], title=e["title"], target=e["target"], sev=e["sev"],
                months_left=max(0, e["until"] - t), text=e["text"],
            ) for e in sorted(w.get("active_events", []), key=lambda x: -x["sev"])]
            epidemics = [dict(
                name=ep["name"], sev=ep["sev"],
                markets=[dict(id=mid, uk=sim.markets[mid]["uk"], inten=round(iv, 2))
                         for mid, iv in ep["markets"].items() if mid in sim.markets],
            ) for ep in w.get("epidemics", [])]
            markers = [dict(type=m["type"], name=m["name"], x=m["x"], y=m["y"], state=m["state"])
                       for m in w.get("markers", []) if "volcan" in m["type"].lower()]
            event_defs = [dict(key=k, title=LD.EVENT_TITLES[k], scope=v["scope"], cat=v["cat"])
                          for k, v in LD.EVENT_TABLE.items()]
            cr = w["crusade"]
            crusade_out = dict(
                name=cr["name"], phase=cr["phase"], progress=round(cr["progress"] * 100, 1),
                fleet=round(cr["fleet"], 1), supplies=round(cr["supplies"], 0),
                result=cr["result"],
                sponsors=[sim.sname(s) for s in cr["sponsors"] if s in sim.states],
            )
            return dict(
                date=E.date_str(w), year=w["date"]["year"], month=w["date"]["month"], tick=t,
                world_name=w["meta"].get("world_name", "Ферія"),
                era=w["meta"].get("era", LD.ERA_SHORT),
                start_year=w["meta"].get("start_year", LD.START_YEAR),
                is_feria=w["meta"].get("is_feria", True),
                has_native_economy=w["meta"].get("has_native_economy", True),
                source_file=w["meta"].get("source_file", ""),
                continents=sorted({x["cont"] for x in states_out if x["cont"]}),
                saved_maps=self._list_saved_maps(),
                undo_count=self._undo_info()[0],
                undo_label=self._undo_info()[1],
                slots=self.list_slots(),
                width=w["meta"]["width"], height=w["meta"]["height"],
                tot_pop=round(sum(x["pop"] for x in states_out)),
                tot_gdp=round(sum(x["gdp"] for x in states_out), 1),
                indices={c: round(sim.price_index(c), 3) for c in LD.CATEGORIES},
                history=w["history"]["world"][-180:],
                states=states_out, markets=markets_out, burgs=burgs_out, edges=edges_out,
                wars=wars_out, active_events=events_active, epidemics=epidemics,
                markers=markers, crusade=crusade_out, event_defs=event_defs,
                journal=w["journal"][-60:][::-1],
            )

    def state_detail(self, sid):
        with self.lock:
            sim = self.sim
            if sid not in sim.states:
                return dict(error="Державу не знайдено")
            st = sim.states[sid]
            s = RP.state_summary(sim, sid)
            low, high = RP.top_relations(sim, sid, 8)
            bl = sorted(sim.state_burgs.get(sid, []), key=lambda b: -sim.burgs[b]["pop"])
            cities = [dict(
                id=b, uk=sim.burgs[b]["uk"], name=sim.burgs[b]["name"],
                pop=round(sim.burgs[b]["pop"] + sim.burgs[b]["rural"]),
                market_id=sim.burgs[b]["market"], market_uk=sim.markets[sim.burgs[b]["market"]]["uk"],
                capital=sim.burgs[b]["capital"], port=sim.burgs[b]["port"], walls=sim.burgs[b]["walls"],
                sat={c: round(v * 100, 0) for c, v in sim.burgs[b].get("sat", {}).items()},
            ) for b in bl[:25]]
            hist = []
            for t, row in sim.w["history"]["states"][-60:]:
                if sid in row:
                    hist.append([t] + row[sid])
            ev = [r for r in sim.w["journal"] if sid in (r.get("states") or []) or r.get("state") == sid][-30:][::-1]
            return dict(
                id=sid, uk=st["uk"], full_name=st["full_name"], cont=st["continent"], gov=st["gov_text"],
                lore=st["lore"], culture=st["culture_name"], religion=st["religion_name"], coins=st["coins"],
                ruler=st["ruler"], ruler_traits=[LD.RULER_TRAITS[t]["label"] for t in st["ruler"]["traits"]],
                summary=dict(pop=round(s["pop"]), gdp=round(s["gdp"], 1), treasury=round(s["treasury"], 1),
                             treasury_coins=LD.fmt_coins(s["treasury"]), debt=round(s["debt"], 1),
                             stab=round(s["stab"], 1), leg=round(st["legitimacy"], 1),
                             we=round(st["war_exhaustion"], 1), food=round(s["food"] * 100, 1),
                             lux=round(st["lux_sat"] * 100, 1), power=round(s["power"], 1),
                             readiness=round(st["readiness"], 2), tax_mult=round(st["tax_mult"], 2),
                             poll_tax=st["poll_tax"], sales_tax=st["sales_tax"],
                             rev=round(s["rev"], 1), exp=round(s["exp"], 1)),
                breakdown=st.get("income_breakdown", {}),
                army=st["army"], mercs=[m["name"] for m in st.get("mercs", [])],
                worst=[dict(id=o, uk=sim.sname(o), score=round(sc, 1)) for sc, o in low],
                best=[dict(id=o, uk=sim.sname(o), score=round(sc, 1)) for sc, o in high],
                cities=cities, history=hist, journal=ev,
            )

    def market_detail(self, mid):
        with self.lock:
            sim = self.sim
            if mid not in sim.markets:
                return dict(error="Ринок не знайдено")
            m = sim.markets[mid]
            sid = sim.market_state[mid]
            goods = []
            for g in sorted(sim.goods):
                base = sim.goods[g]["value"]
                p = m["price"].get(g, base)
                goods.append(dict(
                    id=g, name=LD.good_uk(g, sim.goods), unit=sim.goods[g]["unit"], base=base,
                    price=round(p, 2), coins=LD.fmt_coins(p), pct=round(p / base * 100, 0),
                    stock=round(m["stock"].get(g, 0.0), 1), want=round(m.get("want", {}).get(g, 0.0), 1),
                ))
            routes = []
            for ei in m["edges"]:
                e = sim.edges[ei]
                o = e["b"] if e["a"] == mid else e["a"]
                routes.append(dict(id=o, uk=sim.markets[o]["uk"], dist=e["dist"], sea=e["sea"],
                                   flow=round(e.get("flow", 0.0), 1)))
            return dict(id=mid, uk=m["uk"], state=sid, state_uk=sim.sname(sid),
                        burgs=len(m["burgs"]), routes=routes, goods=goods)

    def goods_table(self):
        with self.lock:
            sim = self.sim
            rows = []
            for g in sorted(sim.goods):
                pts = sorted((m["price"].get(g, 0), m["uk"], mid) for mid, m in sim.markets.items())
                avg = sum(p for p, _, _ in pts) / len(pts)
                tot_stock = sum(m["stock"].get(g, 0.0) for m in sim.markets.values())
                tot_want = sum(m.get("want", {}).get(g, 0.0) for m in sim.markets.values())
                rows.append(dict(
                    id=g, name=LD.good_uk(g, sim.goods), unit=sim.goods[g]["unit"], base=sim.goods[g]["value"],
                    tags=sim.goods[g]["tags"], min_p=round(pts[0][0], 2), avg_p=round(avg, 2),
                    max_p=round(pts[-1][0], 2), cheap_at=pts[0][1], cheap_id=pts[0][2],
                    exp_at=pts[-1][1], exp_id=pts[-1][2],
                    stock=round(tot_stock, 1), want=round(tot_want, 1),
                ))
            return dict(goods=rows)

    def guilds_data(self):
        with self.lock:
            sim = self.sim
            w = sim.w
            guilds = [dict(
                id=g["id"], name=g["name"], kind=g["kind"], burg=sim.bname(g["burg"]),
                state=sim.sname(g["state"]), wealth=round(g["wealth"], 1),
                goods=[LD.good_uk(x, sim.goods) for x in g["goods"]], note=g["note"],
            ) for g in w["guilds"]]
            mercs = [dict(
                name=m["name"], size=m["size"], unit=m["unit"],
                home=sim.sname(m["home"]) if m["home"] in sim.states else "—",
                employer=sim.sname(m["employer"]) if m["employer"] and sim.tick_index() < (m["contract_end"] or 0) else "Вільні",
            ) for m in w["mercs"]]
            orders = [dict(
                name=o["name"], strength=o["strength"], unit=o["unit"],
                state=sim.sname(o["state"]) if o["state"] in sim.states else "Наддержавний",
            ) for o in w["orders"]]
            return dict(guilds=guilds, mercs=mercs, orders=orders)

    def journal_query(self, kind="", q="", limit=150):
        with self.lock:
            j = self.sim.w["journal"]
            if kind:
                j = [r for r in j if r.get("kind") == kind]
            if q:
                ql = q.lower()
                j = [r for r in j if ql in r.get("text", "").lower()]
            return dict(rows=j[-limit:][::-1])

    def _undo_files(self):
        if not os.path.isdir(self.undo_dir):
            return []
        return sorted(fn for fn in os.listdir(self.undo_dir) if fn.endswith(".json.gz"))

    def _undo_info(self):
        files = self._undo_files()
        if not files:
            return 0, ""
        latest = os.path.join(self.undo_dir, files[-1])
        try:
            with gzip.open(latest, "rt", encoding="utf-8") as f:
                # швидке читання лише початку для label не обов'язкове, файл ~1-2MB або json.load
                data = json.load(f)
            return len(files), data.get("label", "Останній крок")
        except Exception:
            return len(files), "Останній крок"

    def _push_undo(self, action_label):
        with self.lock:
            os.makedirs(self.undo_dir, exist_ok=True)
            j_text = None
            if os.path.exists(self.journal_file):
                with open(self.journal_file, encoding="utf-8") as jf:
                    j_text = jf.read()
            w = self.sim.w
            skip = {k: w.pop(k) for k in ("war_pairs", "_new_journal") if k in w}
            try:
                snap = dict(label=action_label, world=w, journal_text=j_text)
                fname = f"undo_{time.time_ns():020d}.json.gz"
                fpath = os.path.join(self.undo_dir, fname)
                with gzip.open(fpath + ".tmp", "wt", encoding="utf-8") as f:
                    json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
                os.replace(fpath + ".tmp", fpath)
            finally:
                w.update(skip)
            files = self._undo_files()
            while len(files) > 10:
                old = files.pop(0)
                try:
                    os.remove(os.path.join(self.undo_dir, old))
                except OSError:
                    pass

    def undo(self):
        with self.lock:
            files = self._undo_files()
            if not files:
                return dict(error="Немає дій для скасування")
            latest = os.path.join(self.undo_dir, files[-1])
            with gzip.open(latest, "rt", encoding="utf-8") as f:
                snap = json.load(f)
            world = E._intkeys(snap["world"])
            self.sim = E.Sim(world)
            j_text = snap.get("journal_text")
            if j_text is not None:
                os.makedirs(os.path.dirname(self.journal_file), exist_ok=True)
                with open(self.journal_file, "w", encoding="utf-8") as jf:
                    jf.write(j_text)
            elif os.path.exists(self.journal_file):
                os.remove(self.journal_file)
            E.save_world(self.sim.w, self.world_file)
            os.remove(latest)
            ov = self.overview()
            return dict(ok=True, message=f"Скасовано: {snap.get('label', 'остання дія')}", overview=ov)

    def list_slots(self):
        if not os.path.isdir(self.slots_dir):
            return []
        out = []
        for sid in sorted(os.listdir(self.slots_dir)):
            mp = os.path.join(self.slots_dir, sid, "meta.json")
            if os.path.isfile(mp):
                try:
                    with open(mp, encoding="utf-8") as f:
                        out.append(json.load(f))
                except Exception:
                    pass
        out.sort(key=lambda x: x.get("saved_at", ""), reverse=True)
        return out

    def save_slot(self, name):
        with self.lock:
            label = (name or "").strip() or f"Збереження {E.date_str(self.sim.w)}"
            base_id = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ_-]+", "_", label).strip("_") or "slot"
            slot_id = f"{base_id}_{int(time.time())}"
            sdir = os.path.join(self.slots_dir, slot_id)
            os.makedirs(sdir, exist_ok=True)
            self.save()
            shutil.copy2(self.world_file, os.path.join(sdir, "world.json"))
            if os.path.exists(self.journal_file):
                shutil.copy2(self.journal_file, os.path.join(sdir, "journal.jsonl"))
            if os.path.exists(self.geo_file):
                shutil.copy2(self.geo_file, os.path.join(sdir, "map_geo.json"))
            meta = dict(
                id=slot_id,
                name=label,
                world_name=self.sim.w.get("meta", {}).get("world_name", "Ферія"),
                date=E.date_str(self.sim.w),
                pop=round(sum(st.get("pop", 0) for st in self.sim.states.values())),
                states=len(self.sim.states),
                saved_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            with open(os.path.join(sdir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            return dict(ok=True, message=f"Збережено слот «{label}»", slot=meta, slots=self.list_slots())

    def load_slot(self, slot_id):
        with self.lock:
            if not slot_id or os.path.basename(slot_id) != slot_id:
                return dict(error="Невірний ідентифікатор слоту")
            sdir = os.path.join(self.slots_dir, slot_id)
            wsrc = os.path.join(sdir, "world.json")
            if not os.path.isfile(wsrc):
                return dict(error="Слот не знайдено")
            self._push_undo("завантаження слоту")
            shutil.copy2(wsrc, self.world_file)
            jsrc = os.path.join(sdir, "journal.jsonl")
            if os.path.isfile(jsrc):
                shutil.copy2(jsrc, self.journal_file)
            elif os.path.exists(self.journal_file):
                os.remove(self.journal_file)
            gsrc = os.path.join(sdir, "map_geo.json")
            if os.path.isfile(gsrc):
                shutil.copy2(gsrc, self.geo_file)
            elif os.path.exists(self.geo_file):
                os.remove(self.geo_file)
            self.sim = E.Sim(E.load_world(self.world_file))
            self._ensure_geo()
            ov = self.overview()
            return dict(ok=True, message=f"Завантажено слот «{slot_id}» ({ov['date']})", overview=ov)

    def delete_slot(self, slot_id):
        with self.lock:
            if not slot_id or os.path.basename(slot_id) != slot_id:
                return dict(error="Невірний ідентифікатор слоту")
            sdir = os.path.join(self.slots_dir, slot_id)
            if not os.path.isdir(sdir):
                return dict(error="Слот не знайдено")
            shutil.rmtree(sdir)
            return dict(ok=True, message="Слот видалено", slots=self.list_slots())

    def apply_override(self, kind, target_id, fields):
        with self.lock:
            if kind not in ("state", "burg"):
                return dict(error="Невідомий тип об'єкта (дозволено state або burg)")
            try:
                tid = int(target_id)
            except (TypeError, ValueError):
                return dict(error="Невірний ID об'єкта")
            fields = fields or {}
            world_name = self.sim.w.get("meta", {}).get("world_name", "Feria")

            if kind == "state":
                if tid not in self.sim.states:
                    return dict(error="Державу не знайдено")
                self._push_undo(f"редагування держави {self.sim.sname(tid)}")
                st = self.sim.states[tid]
                cleaned = {}
                for k in ("uk", "ruler", "coins", "gov", "lore"):
                    if k in fields and fields[k] is not None:
                        val = str(fields[k]).strip()
                        if k != "lore" and not val:
                            continue
                        cleaned[k] = val
                        if k == "uk":
                            st["uk"] = val
                        elif k == "ruler":
                            st["ruler"]["name"] = val
                        elif k == "coins":
                            st["coins"] = val
                        elif k == "gov":
                            st["gov_text"] = val
                        elif k == "lore":
                            st["lore"] = val
                log_name = st["uk"]
            else:
                if tid not in self.sim.burgs:
                    return dict(error="Місто не знайдено")
                self._push_undo(f"перейменування міста {self.sim.bname(tid)}")
                b = self.sim.burgs[tid]
                cleaned = {}
                if fields.get("uk") is not None and str(fields["uk"]).strip():
                    val = str(fields["uk"]).strip()
                    b["uk"] = val
                    cleaned["uk"] = val
                    for m in self.sim.markets.values():
                        if m["center"] == tid:
                            m["uk"] = val
                log_name = b["uk"]

            # Збереження у data/overrides.json
            os.makedirs(os.path.dirname(self.overrides_file), exist_ok=True)
            data = {}
            if os.path.exists(self.overrides_file):
                try:
                    with open(self.overrides_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            worlds_map = data.setdefault("worlds", {})
            wblock = worlds_map.setdefault(world_name, {})
            sec = "states" if kind == "state" else "burgs"
            entry = wblock.setdefault(sec, {}).get(str(tid))
            if not isinstance(entry, dict):
                entry = {"uk": entry} if entry else {}
            entry.update(cleaned)
            wblock[sec][str(tid)] = entry
            if self.sim.w.get("meta", {}).get("is_feria"):
                root_entry = data.setdefault(sec, {}).get(str(tid))
                if not isinstance(root_entry, dict):
                    root_entry = {"uk": root_entry} if root_entry else {}
                root_entry.update(cleaned)
                data[sec][str(tid)] = root_entry
            with open(self.overrides_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.sim.log("gm", f"Майстер гри оновив дані ({kind} #{tid}): {log_name}.")
            self.save()
            return dict(ok=True, message=f"Збережено правки для «{log_name}» у overrides.json", overview=self.overview())

    def map_geo(self):
        with self.lock:
            self._ensure_geo()
            return IM.load_map_geo(self.geo_file)

    def retail_prices(self, burg_id):
        with self.lock:
            try:
                return DT.city_retail_prices(self.sim, int(burg_id))
            except Exception as ex:
                return dict(error=str(ex))

    def calc_route(self, from_id, to_id, mode="foot"):
        with self.lock:
            try:
                return DT.travel_route(self.sim, int(from_id), int(to_id), mode=mode)
            except Exception as ex:
                return dict(error=str(ex))

    def quest_hooks(self, state_id=None):
        with self.lock:
            return dict(quests=DT.generate_quest_hooks(self.sim, state_id=state_id))

    def step(self, months, export_report=False):
        months = max(1, min(int(months), 120))
        with self.lock:
            self._push_undo(f"+{months} міс.")
            self.sim.run(months)
            self.save()
            if export_report:
                RP.write_all(self.sim, self.vault)
            return self.overview()

    def fire_event(self, key, target_id=None, sev=None):
        with self.lock:
            if key not in LD.EVENT_TABLE:
                return dict(error="Невідомий тип події")
            self._push_undo(f"подія {LD.EVENT_TITLES.get(key, key)}")
            self.sim.rng = random.Random(int(time.time() * 1000))
            self.sim._index_mods()
            if not hasattr(self.sim, "acc"):
                self.sim.acc = dict(pop={}, gdp={})
            tgt = int(target_id) if target_id not in (None, "", "auto") else None
            EV.fire(self.sim, self.sim.rng, key, target=tgt, sev=int(sev) if sev else None)
            self.save()
            msg = self.sim.w["journal"][-1]["text"] if self.sim.w["journal"] else "Подія відбулася"
            return dict(ok=True, message=msg)

    def declare_war(self, a, b):
        with self.lock:
            a, b = int(a), int(b)
            if a == b or a not in self.sim.states or b not in self.sim.states:
                return dict(error="Невірні держави")
            if PO.in_war_between(self.sim, a, b):
                return dict(error="Ці держави вже воюють")
            self._push_undo(f"війна {self.sim.sname(a)} — {self.sim.sname(b)}")
            self.sim.rng = random.Random(int(time.time() * 1000))
            PO.declare_war(self.sim, a, b, self.sim.rng, casus="воля майстра гри")
            self.save()
            return dict(ok=True, message=self.sim.w["journal"][-1]["text"])

    def end_war(self, war_id):
        with self.lock:
            war_id = int(war_id)
            wr = next((w for w in self.sim.w["wars"] if w["id"] == war_id), None)
            if not wr:
                return dict(error="Війну не знайдено")
            self._push_undo(f"мир ({wr['name']})")
            self.sim.rng = random.Random(int(time.time() * 1000))
            PO.end_war(self.sim, wr, self.sim.rng)
            PO.war_pairs(self.sim)
            self.save()
            return dict(ok=True, message=self.sim.w["journal"][-1]["text"])

    def set_state_field(self, sid, field, value):
        with self.lock:
            sid = int(sid)
            if sid not in self.sim.states:
                return dict(error="Державу не знайдено")
            if field not in ("treasury", "tax_mult", "stability", "legitimacy", "poll_tax", "sales_tax", "debt"):
                return dict(error="Заборонене поле")
            st = self.sim.states[sid]
            self._push_undo(f"зміна {field} ({st['uk']})")
            old = st[field]
            st[field] = float(value)
            self.sim.log("gm", f"Майстер гри змінив {field} держави {st['uk']}: {old} → {value}.", state=sid)
            self.save()
            return dict(ok=True, message=f"{st['uk']}: {field} = {value}")

    def export_report(self):
        with self.lock:
            RP.write_all(self.sim, self.vault)
            return dict(ok=True, message="Нотатки Obsidian оновлено")

    def _init_from_map(self, map_path, year=None, era=None, seed=1):
        imp = IM.import_map(map_path)
        ov_path = os.path.join(os.path.dirname(self.save_dir), "data", "overrides.json")
        over = {}
        if os.path.exists(ov_path):
            with open(ov_path, encoding="utf-8") as f:
                over = json.load(f)
        yr = int(year) if year not in (None, "") else LD.START_YEAR
        er = LD.ERA_SHORT if era is None else str(era).strip()
        sd = int(seed) if seed not in (None, "") else 1
        world = WG.build_world(imp, seed=sd, overrides=over, start_year=yr, era=er)
        world = E._intkeys(json.loads(json.dumps(world)))
        sim = E.Sim(world, seed=sd)
        WG.calibrate(sim, log=lambda *_: None)
        world["history"] = dict(states=[], world=[])
        world["journal"] = []
        world["mods"] = []
        sim.log("start", f"Симуляцію розпочато: {E.date_str(world)}. Світ {world['meta']['world_name']}: "
                f"{len(world['states'])} держав, {len(world['burgs'])} міст, {len(world['markets'])} ринків.")
        if os.path.exists(self.journal_file):
            os.remove(self.journal_file)
        self.sim = sim
        self.save()
        geo = IM.extract_map_geometry(map_path, world)
        IM.save_map_geo(geo, self.geo_file)
        return dict(ok=True, message=f"Карту «{world['meta']['world_name']}» завантажено ({E.date_str(world)})",
                    world_name=world["meta"]["world_name"], date=E.date_str(world),
                    states=len(world["states"]), burgs=len(world["burgs"]), markets=len(world["markets"]),
                    has_native_economy=world["meta"].get("has_native_economy", True))

    def load_map_upload(self, filename, content_b64, year=None, era=None, seed=1):
        with self.lock:
            try:
                safe_name = re.sub(r'[\\/:*?"<>|]+', "_", os.path.basename(filename or "map.map")).strip() or "uploaded.map"
                os.makedirs(self.maps_dir, exist_ok=True)
                raw = base64.b64decode(content_b64)
                out_path = os.path.join(self.maps_dir, safe_name)
                with open(out_path, "wb") as f:
                    f.write(raw)
                return self._init_from_map(out_path, year=year, era=era, seed=seed)
            except Exception as ex:
                return dict(error=f"Помилка імпорту карти: {ex}")

    def switch_map(self, map_path, year=None, era=None, seed=1):
        with self.lock:
            try:
                allowed = {os.path.abspath(m["path"]) for m in self._list_saved_maps()}
                target = os.path.abspath(map_path)
                if target not in allowed or not os.path.exists(target):
                    return dict(error="Карту не знайдено у списку дозволених")
                return self._init_from_map(target, year=year, era=era, seed=seed)
            except Exception as ex:
                return dict(error=f"Помилка завантаження карти: {ex}")


def make_handler(app: AppState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _json(self, data, code=200):
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if u.path == "/":
                with open(UI_FILE, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/api/overview":
                self._json(app.overview())
            elif u.path == "/api/state":
                self._json(app.state_detail(int(qs.get("id", [0])[0])))
            elif u.path == "/api/market":
                self._json(app.market_detail(int(qs.get("id", [0])[0])))
            elif u.path == "/api/goods":
                self._json(app.goods_table())
            elif u.path == "/api/guilds":
                self._json(app.guilds_data())
            elif u.path == "/api/journal":
                self._json(app.journal_query(qs.get("kind", [""])[0], qs.get("q", [""])[0]))
            elif u.path == "/api/map_geo":
                self._json(app.map_geo())
            elif u.path == "/api/retail":
                self._json(app.retail_prices(qs.get("burg", [0])[0]))
            elif u.path == "/api/route":
                self._json(app.calc_route(qs.get("from", [0])[0], qs.get("to", [0])[0], qs.get("mode", ["foot"])[0]))
            elif u.path == "/api/quests":
                self._json(app.quest_hooks(qs.get("state", [None])[0]))
            elif u.path == "/api/slots":
                self._json(dict(slots=app.list_slots()))
            else:
                self._json({"error": "Not found"}, 404)

        def do_POST(self):
            ln = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(ln) or b"{}")
            if self.path == "/api/step":
                self._json(app.step(body.get("months", 1), body.get("report", False)))
            elif self.path == "/api/undo":
                self._json(app.undo())
            elif self.path == "/api/fire":
                self._json(app.fire_event(body.get("key"), body.get("target"), body.get("sev")))
            elif self.path == "/api/declare":
                self._json(app.declare_war(body.get("a"), body.get("b")))
            elif self.path == "/api/peace":
                self._json(app.end_war(body.get("war_id")))
            elif self.path == "/api/set_state":
                self._json(app.set_state_field(body.get("id"), body.get("field"), body.get("value")))
            elif self.path == "/api/override":
                self._json(app.apply_override(body.get("kind"), body.get("id"), body.get("fields", {})))
            elif self.path == "/api/save_slot":
                self._json(app.save_slot(body.get("name", "")))
            elif self.path == "/api/load_slot":
                self._json(app.load_slot(body.get("id", "")))
            elif self.path == "/api/delete_slot":
                self._json(app.delete_slot(body.get("id", "")))
            elif self.path == "/api/report":
                self._json(app.export_report())
            elif self.path == "/api/upload_map":
                self._json(app.load_map_upload(body.get("filename"), body.get("content_b64", ""),
                                               body.get("year"), body.get("era"), body.get("seed", 1)))
            elif self.path == "/api/switch_map":
                self._json(app.switch_map(body.get("path", ""), body.get("year"), body.get("era"), body.get("seed", 1)))
            else:
                self._json({"error": "Not found"}, 404)

    return Handler


def run_server(world_file, journal_file, host="127.0.0.1", port=8765, vault=None, open_browser=True):
    app = AppState(world_file, journal_file, vault=vault)
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    url = f"http://{host}:{port}/"
    print(f"Веб-панель Ферії запущено: {url} (Ctrl+C для зупинки)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер зупинено.")
