# -*- coding: utf-8 -*-
"""Автоматизований набір інженерних та інтеграційних тестів Feria-Sim."""
import gzip
import json
import math
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request

from feria_sim import cli, dnd_tools as DT, engine as E, events as EV, importer as IM, web, worldgen as WG


def _sample_vanilla_map_lines(with_svg=True):
    svg = [
        '<svg id="map" width="1200" height="600">',
        '<g id="featurePaths"><path d="M50,50 L1100,50 L1100,550 L50,550 Z" id="feature_1" data-f="1"/></g>',
        '<g id="statesBody">'
        '<path d="M100,100 L550,100 L550,500 L100,500 Z" fill="#66c2a5" id="state1"/>'
        '<path d="M600,100 L1050,100 L1050,500 L600,500 Z" fill="#fc8d62" id="state2"/>'
        '</g>',
        '<g id="stateBorders"><path d="M575,100 L575,500"/></g>',
        '<g id="rivers"><path id="river1" d="M200,150 L400,350"/></g>',
        '</svg>',
    ] if with_svg else ["<defs></defs>"]

    lines = [
        "1.99.0|File can be loaded in azgaar.github.io/Fantasy-Map-Generator|2026-11-15|424242|1200|600|1",
        json.dumps({
            "seed": "424242",
            "graph": {"width": 1200, "height": 600},
            "geography": {"coordinates": {"latN": 55, "latS": -45}},
            "lore": {"name": "Testia", "calendar": {"year": 1240}},
            "units": {"distance": {"unit": "km", "scale": 2}},
        }),
        "",
        json.dumps([{"i": 0, "name": "Marine", "habitability": 0}, {"i": 6, "name": "Temperate", "habitability": 100}]),
    ] + svg + [
        json.dumps({"spacing": 10, "cellsX": 120, "cellsY": 60}),
        "0", "0", "0", "0", "0",
        json.dumps([0, {"i": 1, "type": "island", "land": True, "cells": 6, "name": "Alderland"}]),
        json.dumps([
            {"i": 0, "name": "Wildlands", "type": "Generic", "shield": "round"},
            {"i": 1, "name": "Alderian", "type": "Generic", "shield": "heater"},
        ]),
        json.dumps([
            {"i": 0, "name": "Neutral"},
            {"i": 1, "name": "Valoria", "fullName": "Kingdom of Valoria", "form": "Monarchy", "capital": 1,
             "culture": 1, "urban": 24, "rural": 160, "diplomacy": ["x", "x", "Friendly"], "neighbors": [2], "campaigns": []},
            {"i": 2, "name": "Mordar", "fullName": "Duchy of Mordar", "form": "Duchy", "capital": 3,
             "culture": 1, "urban": 15, "rural": 110, "diplomacy": ["x", "Friendly", "x"], "neighbors": [1], "campaigns": []},
        ]),
        json.dumps([
            {},
            {"i": 1, "name": "Aurelia", "state": 1, "culture": 1, "x": 280, "y": 240, "capital": True, "port": 1, "population": 18, "cell": 0, "feature": 1},
            {"i": 2, "name": "Riverford", "state": 1, "culture": 1, "x": 420, "y": 290, "capital": False, "port": 0, "population": 6, "cell": 1, "feature": 1},
            {"i": 3, "name": "Ironhold", "state": 2, "culture": 1, "x": 780, "y": 310, "capital": True, "port": 1, "population": 15, "cell": 4, "feature": 1},
        ]),
        "6,6,6,6,6,6", "1,2,0,0,3,0", "0,0,0,0,0,0", "1,1,1,1,1,1", "0,0,0,0,0,0",
        "12,12,12,12,12,12", "0,0,0,0,0,0", "", "0,0,0,0,0,0", "1,1,1,2,2,2", "0,0,0,0,0,0", "0,0,0,0,0,0",
        json.dumps([{"i": 0, "name": "No religion"}]),
        json.dumps([0]),
        "German|5|12|lt|0",
        json.dumps([]),
        "",
        json.dumps([]),
        json.dumps([]),
        json.dumps([]),
    ]
    return "\n".join(lines)


def _build_calibrated_test_world(td, seed=1):
    mpath = os.path.join(td, "testia.map")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(_sample_vanilla_map_lines(with_svg=True))
    imp = IM.import_map(mpath)
    w = WG.build_world(imp, seed=seed, start_year=1250, era="Н.Е.")
    w = E._intkeys(json.loads(json.dumps(w)))
    sim = E.Sim(w, seed=seed)
    WG.calibrate(sim, log=lambda *_: None, warm_iters=5, months_per=2)
    w["history"] = dict(states=[], world=[])
    w["journal"] = []
    w["mods"] = []
    geo = IM.extract_map_geometry(mpath, w)
    wpath = os.path.join(td, "world.json")
    jpath = os.path.join(td, "journal.jsonl")
    gpath = os.path.join(td, "map_geo.json")
    E.save_world(w, wpath)
    IM.save_map_geo(geo, gpath)
    return mpath, wpath, jpath, gpath, sim


class TestFeriaSim(unittest.TestCase):
    def test_import_formats(self):
        with tempfile.TemporaryDirectory() as td:
            # 1) Ванільний .map без економіки + SVG геометрія
            mp = os.path.join(td, "vanilla.map")
            with open(mp, "w", encoding="utf-8") as f:
                f.write(_sample_vanilla_map_lines(with_svg=True))
            imp = IM.import_map(mp)
            self.assertEqual(imp["meta"]["world_name"], "Testia")
            self.assertFalse(imp["meta"]["has_native_economy"])
            self.assertEqual(len(imp["goods"]), 71)
            self.assertGreaterEqual(len(imp["markets"]), 2)
            self.assertEqual(len(imp["burgs"]), 3)
            geo = IM.extract_map_geometry(mp, imp)
            self.assertTrue(geo["has_svg"])
            self.assertEqual(len(geo["land"]), 1)
            self.assertIn("1", geo["states"])
            self.assertIn("2", geo["states"])
            self.assertEqual(len(geo["borders"]), 1)
            self.assertEqual(len(geo["rivers"]), 1)

            # 2) Стиснутий .map.gz
            gzp = os.path.join(td, "gz_world.map")
            with open(gzp, "wb") as f:
                f.write(gzip.compress(_sample_vanilla_map_lines(with_svg=False).encode("utf-8")))
            imp_gz = IM.import_map(gzp)
            self.assertEqual(len(imp_gz["states"]), 2)

            # 3) FMG Save -> JSON + фолбек опуклих оболонок без SVG
            fmg_json = {
                "info": {"version": "1.105", "mapName": "Jsonia", "seed": "77", "width": 1000, "height": 500},
                "settings": {"distanceScale": 2, "distanceUnit": "km"},
                "biomesData": {"name": ["Marine", "Grassland"], "habitability": [0, 40]},
                "pack": {
                    "features": [0, {"i": 1, "type": "island", "land": True, "cells": 3, "name": "Solis"}],
                    "cultures": [{"i": 0, "name": "Wildlands", "type": "Generic"}, {"i": 1, "name": "Solari", "type": "Naval"}],
                    "states": [
                        {"i": 0, "name": "Neutral"},
                        {"i": 1, "name": "Solaria", "fullName": "Republic of Solaria", "form": "Republic",
                         "capital": 1, "culture": 1, "urban": 15, "rural": 90, "diplomacy": ["x", "x"], "neighbors": []},
                    ],
                    "burgs": [
                        {},
                        {"i": 1, "name": "Solport", "state": 1, "culture": 1, "x": 300, "y": 200, "capital": True, "port": 1, "population": 12, "cell": 0, "feature": 1},
                        {"i": 2, "name": "Solvilla", "state": 1, "culture": 1, "x": 450, "y": 260, "capital": False, "port": 0, "population": 6, "cell": 1, "feature": 1},
                        {"i": 3, "name": "Solcrest", "state": 1, "culture": 1, "x": 360, "y": 140, "capital": False, "port": 0, "population": 5, "cell": 2, "feature": 1},
                    ],
                    "cells": {"biome": [1, 1, 1], "burg": [1, 2, 3], "culture": [1, 1, 1], "state": [1, 1, 1], "religion": [0, 0, 0], "province": [0, 0, 0]},
                    "religions": [{"i": 0, "name": "No religion"}],
                    "provinces": [0],
                },
            }
            jp = os.path.join(td, "jsonia.json")
            with open(jp, "w", encoding="utf-8") as f:
                json.dump(fmg_json, f)
            imp_j = IM.import_map(jp)
            self.assertEqual(imp_j["meta"]["world_name"], "Jsonia")
            geo_j = IM.extract_map_geometry(jp, imp_j)
            self.assertTrue(geo_j["has_svg"])
            self.assertTrue(geo_j["states"]["1"].startswith("M"))
            self.assertTrue(geo_j["states"]["1"].endswith("Z"))

    def test_calibration_and_simulation_invariants(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=7)
            self.assertEqual(E.date_str(sim.w), "Січень 1250 Н.Е.")
            sim.run(6)
            self.assertEqual(E.date_str(sim.w), "Липень 1250 Н.Е.")
            for mid, m in sim.markets.items():
                for g, p in m["price"].items():
                    base = sim.goods[g]["value"]
                    self.assertFalse(math.isnan(p) or math.isinf(p))
                    self.assertGreaterEqual(p, E.PMIN * base * 0.999)
                    self.assertLessEqual(p, E.PMAX * base * 1.001)
                for g, st_val in m["stock"].items():
                    self.assertFalse(math.isnan(st_val) or math.isinf(st_val))
                    self.assertGreaterEqual(st_val, 0.0)
            tot_pop = sum(st.get("pop", 0) for st in sim.states.values())
            self.assertGreater(tot_pop, 0.0)
            for st in sim.states.values():
                self.assertFalse(math.isnan(st["treasury"]) or math.isinf(st["treasury"]))

    def test_dnd_tools_retail_and_routes(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=3)
            rt1 = DT.city_retail_prices(sim, 1)
            self.assertGreaterEqual(len(rt1["items"]), 22)
            self.assertEqual(len(rt1["items"]), len(DT.RETAIL_CATALOG))
            sword_before = next(it["mm"] for it in rt1["items"] if it["id"] == "longsword")

            # Перевіряємо вплив податку і прокляття «Чорної Іржі»
            sim.states[1]["tax_mult"] = 2.0
            sim.acc = dict(pop={}, gdp={})
            EV.fire(sim, sim.rng, "black_rust", target=1, sev=2)
            rt2 = DT.city_retail_prices(sim, 1)
            self.assertTrue(rt2["modifiers"]["black_rust"])
            sword_after = next(it["mm"] for it in rt2["items"] if it["id"] == "longsword")
            self.assertGreater(sword_after, sword_before)

            # Перевіряємо маршрути у 4 режимах
            for mode in ("foot", "wagon", "horse", "ship"):
                route = DT.travel_route(sim, 1, 3, mode=mode)
                self.assertGreater(route["total_km"], 0.0)
                self.assertGreater(route["total_days"], 0.0)
                self.assertGreaterEqual(route["danger_score"], 0)
                self.assertLessEqual(route["danger_score"], 100)
                self.assertEqual(len(route["encounters"]), 3)
                self.assertGreaterEqual(len(route["points"]), 2)

            # Квестові гачки мають реагувати на активну подію Чорної Іржі
            hooks = DT.generate_quest_hooks(sim)
            self.assertTrue(hooks)
            self.assertTrue(any("Ірж" in h["title"] or "Іржі" in h["title"] for h in hooks))

    def test_overrides_undo_and_slots(self):
        with tempfile.TemporaryDirectory() as td:
            _, wpath, jpath, _, _ = _build_calibrated_test_world(td, seed=5)
            ov_path = os.path.join(td, "overrides.json")
            app = web.AppState(wpath, jpath)
            app.overrides_file = ov_path

            # 1) Редагування overrides.json + перевірка повторного build_world
            res_ov = app.apply_override("state", 1, {
                "uk": "Королівство Сонця",
                "coins": "Сонячний дукат",
                "ruler": "Король Марко I",
                "lore": "Оновлений лор.",
            })
            self.assertTrue(res_ov["ok"])
            self.assertTrue(os.path.exists(ov_path))
            with open(ov_path, encoding="utf-8") as f:
                ov_data = json.load(f)
            self.assertEqual(ov_data["worlds"]["Testia"]["states"]["1"]["uk"], "Королівство Сонця")
            self.assertEqual(app.sim.states[1]["uk"], "Королівство Сонця")

            # Перевірка, що worldgen підхопить цей override при новому імпорті
            mp = os.path.join(td, "testia.map")
            w2 = WG.build_world(IM.import_map(mp), seed=1, overrides=ov_data, start_year=1250, era="Н.Е.")
            self.assertEqual(w2["states"][1]["uk"], "Королівство Сонця")
            self.assertEqual(w2["states"][1]["coins"], "Сонячний дукат")
            self.assertEqual(w2["states"][1]["ruler"]["name"], "Король Марко I")

            # 2) Слоти збережень + Step + Undo
            slot_res = app.save_slot("Перед походом")
            self.assertTrue(slot_res["ok"])
            slot_id = slot_res["slot"]["id"]
            self.assertEqual(slot_res["slot"]["date"], "Січень 1250 Н.Е.")

            ov_step = app.step(2)
            self.assertEqual(ov_step["date"], "Березень 1250 Н.Е.")
            self.assertGreaterEqual(ov_step["undo_count"], 1)

            undo_res = app.undo()
            self.assertTrue(undo_res["ok"])
            self.assertEqual(undo_res["overview"]["date"], "Січень 1250 Н.Е.")

            app.step(4)
            self.assertEqual(app.overview()["date"], "Травень 1250 Н.Е.")
            load_res = app.load_slot(slot_id)
            self.assertTrue(load_res["ok"])
            self.assertEqual(load_res["overview"]["date"], "Січень 1250 Н.Е.")

            del_res = app.delete_slot(slot_id)
            self.assertTrue(del_res["ok"])
            self.assertEqual(len(app.list_slots()), 0)

    def test_web_http_endpoints(self):
        with tempfile.TemporaryDirectory() as td:
            _, wpath, jpath, _, _ = _build_calibrated_test_world(td, seed=9)
            app = web.AppState(wpath, jpath)
            app.overrides_file = os.path.join(td, "overrides.json")
            srv = web.ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(app))
            port = srv.server_port
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                base = f"http://127.0.0.1:{port}"
                # GET HTML & APIs
                with urllib.request.urlopen(base + "/", timeout=5) as r:
                    self.assertEqual(r.status, 200)
                    html = r.read().decode("utf-8")
                    self.assertIn("D&D", html)
                    self.assertIn("/api/map_geo", html)

                for ep, req_key in [
                    ("/api/overview", "undo_count"),
                    ("/api/map_geo", "states"),
                    ("/api/retail?burg=1", "items"),
                    ("/api/route?from=1&to=3&mode=horse", "total_km"),
                    ("/api/quests", "quests"),
                    ("/api/slots", "slots"),
                ]:
                    with urllib.request.urlopen(base + ep, timeout=5) as r:
                        self.assertEqual(r.status, 200)
                        data = json.loads(r.read().decode("utf-8"))
                        self.assertIn(req_key, data, msg=ep)

                def post_json(path, payload):
                    req = urllib.request.Request(
                        base + path,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        self.assertEqual(r.status, 200)
                        return json.loads(r.read().decode("utf-8"))

                ov_r = post_json("/api/override", {"kind": "burg", "id": 1, "fields": {"uk": "Аурелія Нова"}})
                self.assertTrue(ov_r["ok"])
                st_r = post_json("/api/step", {"months": 1})
                self.assertEqual(st_r["date"], "Лютий 1250 Н.Е.")
                un_r = post_json("/api/undo", {})
                self.assertTrue(un_r["ok"])
                self.assertEqual(un_r["overview"]["date"], "Січень 1250 Н.Е.")
            finally:
                srv.shutdown()
                srv.server_close()

    def test_epidemic_burnout_and_population_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=11)
            sim.w["config"]["event_rate"] = 0.0
            pop0 = sum(b["pop"] + b["rural"] for b in sim.burgs.values())
            sim.acc = dict(pop={}, gdp={})
            EV.fire(sim, sim.rng, "plague", target=1, sev=3)
            self.assertEqual(len(sim.w.get("epidemics", [])), 1)
            sim.run(24)
            self.assertEqual(len(sim.w.get("epidemics", [])), 0)
            self.assertTrue(sim.w.get("market_immunity"))
            pop_end = sum(b["pop"] + b["rural"] for b in sim.burgs.values())
            self.assertGreaterEqual(pop_end, pop0 * 0.98)

    def test_trade_flow_symmetry(self):
        with tempfile.TemporaryDirectory() as td:
            _, wpath, _, _, sim1 = _build_calibrated_test_world(td, seed=1)
            sim2 = E.Sim(E.load_world(wpath), seed=1)
            for e in sim2.edges:
                e["a"], e["b"] = e["b"], e["a"]
            sim1.tick(politics=False, events=False, advance=False, finance=False)
            sim2.tick(politics=False, events=False, advance=False, finance=False)
            flows1 = sorted(e["flow"] for e in sim1.edges)
            flows2 = sorted(e["flow"] for e in sim2.edges)
            for f1, f2 in zip(flows1, flows2):
                self.assertAlmostEqual(f1, f2, places=2)


if __name__ == "__main__":
    unittest.main()
