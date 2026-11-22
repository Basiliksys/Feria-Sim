# -*- coding: utf-8 -*-
"""Автоматизований набір інженерних та інтеграційних тестів Feria-Sim."""
import argparse
import base64
import contextlib
import gzip
import io
import json
import math
import os
import random
import re
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from unittest import mock

from feria_sim import _accel as AC, cli, dnd_tools as DT, engine as E, events as EV, geography as GEO, importer as IM, lore_data as LD, politics as PO, report as RP, routes as RT, web, worldgen as WG


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

    def test_config_contract_and_content_pack(self):
        with tempfile.TemporaryDirectory() as td:
            pack_path = os.path.join(td, "content_pack.json")
            with open(pack_path, "w", encoding="utf-8") as f:
                json.dump({
                    "config": {"event_rate": 0.75, "carry_cap": 1.9},
                    "event_weights": {"drought": 3.5},
                    "goods": {"9": {"value": 12.5}},
                }, f)
            with mock.patch.object(WG, "CONTENT_PACK_PATH", pack_path):
                mpath = os.path.join(td, "pack.map")
                with open(mpath, "w", encoding="utf-8") as f:
                    f.write(_sample_vanilla_map_lines())
                imp = IM.import_map(mpath)
                w = WG.build_world(imp, seed=2, start_year=1250, era="Н.Е.")

            for key in E.CONFIG_DEFAULTS:
                self.assertIn(key, w["config"], msg=key)
            self.assertEqual(w["config"]["event_rate"], 0.75)
            self.assertEqual(w["config"]["carry_cap"], 1.9)
            self.assertEqual(w["config"]["event_weights"]["drought"], 3.5)
            self.assertEqual(w["goods"][9]["value"], 12.5)

            raw = json.loads(json.dumps(w))
            w = E._intkeys(json.loads(json.dumps(raw)))
            sim = E.Sim(w, seed=2)
            self.assertEqual(sim.cfg("carry_cap"), 1.9)
            self.assertEqual(sim.cfg("missing_key", 42), 42)
            self.assertEqual(sim.gid("grain"), 9)
            for m in sim.markets.values():
                self.assertIsInstance(m.get("capital"), (int, float))
                self.assertIsInstance(m.get("shop_reserved"), dict)

            # Старе збереження без капіталу ринку має отримати значення за замовчуванням.
            old = E._intkeys(json.loads(json.dumps(raw)))
            for m in old["markets"].values():
                m.pop("capital", None)
                m.pop("shop_reserved", None)
            sim_old = E.Sim(old, seed=2)
            for m in sim_old.markets.values():
                self.assertGreater(m["capital"], 0)
                self.assertEqual(m["shop_reserved"], {})

            # Політичні похідні з рис правителя й обмеження технологій.
            PO.sync_ruler_fields(sim)
            for st in sim.states.values():
                for key in ("trade_mod", "tariff_mod", "war_power"):
                    self.assertIsInstance(st[key], (int, float))
            sim.w["config"]["tech_decay"] = 0.1
            sim.states[1]["tech"] = 2.0
            PO.decay_tech(sim, sim.states[1])
            self.assertLess(sim.states[1]["tech"], 2.0)
            self.assertGreaterEqual(sim.states[1]["tech"], 1.0)
            self.assertEqual(PO.clamp_tech(sim, 9.0), 3.0)
            tick = sim.tick_index()
            sim.states[1]["truce"] = {2: tick + 5}
            self.assertTrue(PO.truce_active(sim, 1, 2))
            self.assertTrue(PO.truce_active(sim, 2, 1))
            sim.states[1]["truce"][2] = tick - 1
            self.assertFalse(PO.truce_active(sim, 1, 2))

    def test_event_choices_quest_lifecycle_and_shop_stock(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=13)
            sim.states[1]["treasury"] = 100_000.0
            EV.fire(sim, sim.rng, "drought", target=1, sev=2)
            active = [e for e in sim.w["active_events"] if e.get("key") == "drought"]
            self.assertEqual(len(active), 1)
            uid = active[0].get("uid")
            self.assertIsNotNone(uid)

            choice = LD.EVENT_CHOICES["drought"][0]
            treasury_before = sim.states[1]["treasury"]
            self.assertTrue(EV.apply_event_choice(sim, uid, choice["id"]))
            self.assertFalse(any(e.get("uid") == uid for e in sim.w["active_events"]))
            self.assertLess(sim.states[1]["treasury"], treasury_before)
            self.assertTrue(any(j.get("kind") == "event_choice" for j in sim.w["journal"]))
            self.assertFalse(EV.apply_event_choice(sim, uid, choice["id"]))

            # Квест із активної події можна прийняти, виконати й отримати виплату.
            hooks = DT.generate_quest_hooks(sim, 1, limit=20)
            hook = next(h for h in hooks if h.get("state_uk") == sim.states[1]["uk"])
            quest = DT.accept_quest(sim, hook["id"], state_id=1)
            self.assertIsNotNone(quest)
            self.assertEqual(len(sim.w["quests"]["active"]), 1)
            treasury_before = sim.states[1]["treasury"]
            done = DT.complete_quest(sim, quest["quest_id"])
            self.assertEqual(done["status"], "completed")
            self.assertEqual(len(sim.w["quests"]["active"]), 0)
            self.assertEqual(len(sim.w["quests"]["completed"]), 1)
            self.assertEqual(sim.states[1]["treasury"], treasury_before - done["paid_zm"])

            # Купівля зменшує й доступність, і реальний запас ринку.
            retail = DT.city_retail_prices(sim, 1)
            item = next(it for it in retail["items"] if it["available"] > 0)
            market = sim.markets[retail["market_id"]]
            stock_before = sum(market["stock"].get(int(g), 0.0) for g in item["stock"])
            receipt = DT.purchase_shop_item(sim, 1, item["id"], 1)
            self.assertTrue(receipt["ok"])
            stock_after = sum(market["stock"].get(int(g), 0.0) for g in item["stock"])
            self.assertLess(stock_after, stock_before)
            retail2 = DT.city_retail_prices(sim, 1)
            item2 = next(it for it in retail2["items"] if it["id"] == item["id"])
            self.assertEqual(item2["available"], item["available"] - 1)

            npc = DT.generate_npc(sim, state_id=1, role="купець")
            self.assertEqual(npc["role"], "купець")
            self.assertTrue(npc["name"])
            self.assertTrue(npc["faction"])
            self.assertEqual(DT.fmt_mm(101), "1 см 1 мм")

    def test_long_horizon_invariants(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=17)
            tech_cap = float(sim.cfg("tech_cap", 3.0))
            sim.run(120)
            for mid, m in sim.markets.items():
                for g, price in m["price"].items():
                    base = sim.goods[g]["value"]
                    self.assertTrue(math.isfinite(price), msg=f"market {mid} good {g}")
                    self.assertGreaterEqual(price, E.PMIN * base * 0.99)
                    self.assertLessEqual(price, E.PMAX * base * 1.01)
                for g, stock in m["stock"].items():
                    self.assertTrue(math.isfinite(stock), msg=f"market {mid} good {g}")
                    self.assertGreaterEqual(stock, -1e-6, msg=f"market {mid} good {g}")
            for sid, st in sim.states.items():
                for key in ("treasury", "debt", "pop", "stability", "legitimacy", "tech"):
                    self.assertTrue(math.isfinite(float(st.get(key, 0.0))), msg=f"state {sid} {key}")
                self.assertLessEqual(float(st.get("tech", 1.0)), tech_cap + 1e-6)
                self.assertGreaterEqual(float(st.get("tech", 1.0)), 0.0)
                for unit, count in st.get("army", {}).items():
                    self.assertGreaterEqual(count, 0, msg=f"state {sid} {unit}")
            self.assertGreater(sum(st.get("pop", 0.0) for st in sim.states.values()), 0.0)

    def test_long_horizon_balance_no_spiral_or_stock_dominance(self):
        """Регресія: легітимність може відновлюватися, а один сировинний товар
        не може назавжди витіснити всі інші з ринку."""
        for seed in (42, 777):
            with tempfile.TemporaryDirectory() as td:
                # 1) Ізольований механізм: з мінімуму й без випадкових подій
                #    держава повільно відновлює легітимність, а не лишається
                #    заблокованою на 10 через старий жорсткий крок +/-.
                _, _, _, _, sim = _build_calibrated_test_world(td, seed=seed)
                sim.w["active_events"] = []
                for st in sim.states.values():
                    st["legitimacy"] = 10.0
                for _ in range(60):
                    sim.tick(events=False)
                for sid, st in sim.states.items():
                    self.assertGreater(
                        st["legitimacy"], 40.0,
                        msg=f"seed {seed} state {sid}: легітимність застрягла на мінімумі")

                # 2) Звичайні події більше не створюють односторонню спіраль:
                #    легітимність не просить усі 10 років на дні.
                _, _, _, _, sim2 = _build_calibrated_test_world(td, seed=seed)
                max_leg = {sid: 0.0 for sid in sim2.states}
                pinned = {sid: 0 for sid in sim2.states}
                months = 120
                for _ in range(months):
                    sim2.tick()
                    for sid, st in sim2.states.items():
                        max_leg[sid] = max(max_leg[sid], st["legitimacy"])
                        if st["legitimacy"] <= 10.001:
                            pinned[sid] += 1
                for sid in sim2.states:
                    self.assertGreater(max_leg[sid], 40.0,
                                       msg=f"seed {seed} state {sid}: легітимність не відновилася")
                    self.assertLess(pinned[sid], months // 4,
                                    msg=f"seed {seed} state {sid}: легітимність застрягла на дні")

                # 3) Переповнення складів не дає одному товару (наприклад,
                #    коноплям) зайняти більшість усього ринкового запасу.
                totals = {}
                for m in sim2.markets.values():
                    for g, qty in m["stock"].items():
                        totals[g] = totals.get(g, 0.0) + float(qty or 0)
                total = sum(totals.values())
                self.assertGreater(total, 0.0)
                share = max(totals.values()) / total
                self.assertLess(share, 0.5,
                                msg=f"seed {seed}: один товар тримає {share:.0%} усього запасу")

    def test_report_outputs_are_dynamic_and_keep_unknown_notes(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=23)
            vault = os.path.join(td, "vault")
            states_dir = os.path.join(vault, "Держави")
            os.makedirs(states_dir, exist_ok=True)
            user_note = os.path.join(states_dir, "Моя нотатка.md")
            with open(user_note, "w", encoding="utf-8") as f:
                f.write("Користувацька нотатка — не видаляти.\n")

            RP.write_all(sim, vault)
            for name in ("Квести.md", "Маршрути та небезпека.md", "Персонажі та фракції.md", "Правила симуляції.md"):
                self.assertTrue(os.path.isfile(os.path.join(vault, name)), msg=name)
            self.assertTrue(os.path.isfile(user_note))

            with open(os.path.join(vault, "Правила симуляції.md"), encoding="utf-8") as f:
                rules = f.read()
            self.assertIn(f"{len(sim.states)} держав", rules)
            self.assertIn(f"{len(sim.burgs)} міст", rules)
            self.assertIn("carry_cap=", rules)
            self.assertNotIn("73 держави", rules)

            with open(os.path.join(vault, "Маршрути та небезпека.md"), encoding="utf-8") as f:
                routes = f.read()
            self.assertIn("Небезпека", routes)
            self.assertIn("зустріч", routes.lower())

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
                    ("/api/shop?burg=1", "items"),
                    ("/api/route?from=1&to=3&mode=horse", "total_km"),
                    ("/api/quests", "quests"),
                    ("/api/slots", "slots"),
                    ("/api/config", "config"),
                    ("/api/event_choices", "events"),
                    ("/api/quest_board", "hooks"),
                    ("/api/npc", "npcs"),
                ]:
                    with urllib.request.urlopen(base + ep, timeout=5) as r:
                        self.assertEqual(r.status, 200)
                        data = json.loads(r.read().decode("utf-8"))
                        self.assertIn(req_key, data, msg=ep)

                with self.assertRaises(urllib.error.HTTPError) as bad:
                    urllib.request.urlopen(base + "/api/state?id=abc", timeout=5)
                self.assertEqual(bad.exception.code, 400)
                self.assertIn("error", json.loads(bad.exception.read().decode("utf-8")))

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

                fire_r = post_json("/api/fire", {"key": "drought", "target": 1, "sev": 2})
                self.assertTrue(fire_r["ok"])
                with urllib.request.urlopen(base + "/api/event_choices", timeout=5) as r:
                    choices_data = json.loads(r.read().decode("utf-8"))
                drought = next(e for e in choices_data["events"] if e["key"] == "drought")
                self.assertTrue(drought["choices"])
                choice_r = post_json("/api/event_choice", {
                    "uid": drought["uid"], "choice_id": drought["choices"][0]["id"],
                })
                self.assertTrue(choice_r["ok"])

                cfg_r = post_json("/api/set_config", {"key": "event_rate", "value": 1.25})
                self.assertTrue(cfg_r["ok"])
                self.assertEqual(cfg_r["config"]["event_rate"], 1.25)

                npc_r = post_json("/api/npc", {"state": 1, "role": "купець"})
                self.assertTrue(npc_r["ok"])
                self.assertEqual(npc_r["npc"]["role"], "купець")
                with urllib.request.urlopen(base + "/api/npc", timeout=5) as r:
                    self.assertEqual(len(json.loads(r.read().decode("utf-8"))["npcs"]), 1)

                with urllib.request.urlopen(base + "/api/shop?burg=1", timeout=5) as r:
                    shop = json.loads(r.read().decode("utf-8"))
                buy_item = next(it for it in shop["items"] if it["available"] > 0)
                buy_r = post_json("/api/shop_buy", {
                    "burg": 1, "item": buy_item["id"], "qty": 1,
                })
                self.assertTrue(buy_r["ok"])
                self.assertEqual(buy_r["receipt"]["qty"], 1)

                with urllib.request.urlopen(base + "/api/quest_board", timeout=5) as r:
                    board = json.loads(r.read().decode("utf-8"))
                hook = board["hooks"][0]
                q_accept = post_json("/api/quest_accept", {"id": hook["id"]})
                self.assertTrue(q_accept["ok"])
                q_id = q_accept["quest"]["quest_id"]
                q_done = post_json("/api/quest_complete", {"id": q_id, "success": True})
                self.assertTrue(q_done["ok"])
                self.assertEqual(q_done["quest"]["status"], "completed")

                fork_r = post_json("/api/fork", {"name": "Тестова гілка"})
                self.assertTrue(fork_r["ok"])
                self.assertTrue(any(s["id"] == fork_r["slot"]["id"] for s in fork_r["slots"]))

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

    def test_web_security_hardening(self):
        with tempfile.TemporaryDirectory() as td:
            _, wpath, jpath, _, _ = _build_calibrated_test_world(td, seed=77)
            app = web.AppState(wpath, jpath)
            app.overrides_file = os.path.join(td, "overrides.json")

            # Атомарний запис не псує цільовий файл і прибирає tmp при помилці.
            atomic_target = os.path.join(td, "atomic.txt")
            with open(atomic_target, "w", encoding="utf-8") as f:
                f.write("old")
            with mock.patch.object(web.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    web._write_text_atomic(atomic_target, "new")
            with open(atomic_target, encoding="utf-8") as f:
                self.assertEqual(f.read(), "old")
            self.assertFalse(os.path.exists(atomic_target + ".tmp"))

            self.assertIn("[::1]:8765", web._expected_hosts("::1", 8765))
            self.assertIn("127.0.0.1:8765", web._expected_hosts("::1", 8765))
            self.assertEqual(web._host_key("[::1]"), "::1")

            srv = web.ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(app))
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                base = f"http://127.0.0.1:{srv.server_port}"

                def request(path, data=None, headers=None, method=None):
                    req = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
                    return urllib.request.urlopen(req, timeout=10)

                # Небезпечні ідентифікатори слотів не можуть вийти за межі каталогу save/slots.
                for bad_id in ("..", ".", "a/b", "../world"):
                    body = json.dumps({"id": bad_id}).encode("utf-8")
                    res = json.loads(request("/api/delete_slot", body,
                                             {"Content-Type": "application/json"}, "POST").read())
                    self.assertIn("error", res)
                self.assertTrue(os.path.exists(wpath))

                # Слоти отримують унікальні ID навіть у межах однієї секунди.
                s1 = json.loads(request("/api/save_slot", b'{"name":"A"}',
                                        {"Content-Type": "application/json"}, "POST").read())
                s2 = json.loads(request("/api/save_slot", b'{"name":"A"}',
                                        {"Content-Type": "application/json"}, "POST").read())
                self.assertNotEqual(s1["slot"]["id"], s2["slot"]["id"])
                self.assertTrue(s1["ok"] and s2["ok"])

                # NaN/Infinity у JSON і в рядковому вигляді відхиляються.
                with self.assertRaises(urllib.error.HTTPError) as bad_nan:
                    request("/api/set_state", b'{"id":1,"field":"treasury","value":NaN}',
                            {"Content-Type": "application/json"}, "POST")
                self.assertEqual(bad_nan.exception.code, 400)
                res = json.loads(request("/api/set_state",
                                         b'{"id":1,"field":"treasury","value":"nan"}',
                                         {"Content-Type": "application/json"}, "POST").read())
                self.assertIn("error", res)
                self.assertTrue(math.isfinite(app.sim.states[1]["treasury"]))

                # Origin з іншого сайту та чужий Host відхиляються.
                with self.assertRaises(urllib.error.HTTPError) as bad_origin:
                    request("/api/set_config", b'{"key":"event_rate","value":1.7}',
                            {"Content-Type": "text/plain", "Origin": "https://evil.example"}, "POST")
                self.assertEqual(bad_origin.exception.code, 403)
                self.assertEqual(app.sim.cfg("event_rate"), 1.0)
                with self.assertRaises(urllib.error.HTTPError) as bad_host:
                    request("/api/overview", headers={"Host": "evil.example"})
                self.assertEqual(bad_host.exception.code, 403)

                # IPv6-форма Host для localhost є прийнятною.
                ok_ipv6 = json.loads(request("/api/overview", headers={
                    "Host": f"[::1]:{srv.server_port}"}).read())
                self.assertIn("states", ok_ipv6)

                # Порожня лояльність провінції ігнорується, а не ламає правку.
                province_id = next(iter(app.sim.provinces))
                blank_loyalty = json.dumps({"kind": "province", "id": province_id,
                                            "fields": {"loyalty": ""}}).encode("utf-8")
                res = json.loads(request("/api/override", blank_loyalty,
                                         {"Content-Type": "application/json"}, "POST").read())
                self.assertTrue(res.get("ok"))

                # Ліміт журналу справді застосовується.
                for i in range(8):
                    app.sim.log("test", f"record {i}")
                app.save()
                res = json.loads(request("/api/journal?limit=3").read())
                self.assertEqual(len(res["rows"]), 3)

                # Стиснену карту, що роздувається понад ліміт, не імпортуємо.
                bomb = gzip.compress(b"\0" * (70 * 1024 * 1024))
                payload = json.dumps({"filename": "bomb.map.gz",
                                      "content_b64": base64.b64encode(bomb).decode("ascii")}).encode("utf-8")
                res = json.loads(request("/api/upload_map", payload,
                                         {"Content-Type": "application/json"}, "POST").read())
                self.assertIn("error", res)
                self.assertIn("занадто", res["error"])
            finally:
                srv.shutdown()
                srv.server_close()

    def test_cli_new_commands_and_undo(self):
        with tempfile.TemporaryDirectory() as td:
            _, wpath, jpath, gpath, _ = _build_calibrated_test_world(td, seed=31)
            with mock.patch.multiple(cli, WORLD_FILE=wpath, JOURNAL_FILE=jpath,
                                     GEO_FILE=gpath, _APP=None):
                def run(*args):
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        cli.main(list(args))
                    return buf.getvalue()

                self.assertIn("event_rate", run("config", "get", "event_rate"))
                run("config", "set", "carry_cap", "1.8")
                app = cli.get_app()
                self.assertEqual(app.sim.w["config"]["carry_cap"], 1.8)

                npc_out = run("npc", "--state", app.sim.states[1]["uk"], "--role", "купець")
                self.assertIn("купець", npc_out)
                self.assertEqual(len(app.sim.w["npcs"]), 1)

                hook = app.quest_board()["hooks"][0]
                self.assertIn("Прийнято", run("quests", "accept", hook["id"]))
                active = app.sim.w["quests"]["active"]
                self.assertEqual(len(active), 1)
                run("quests", "complete", str(active[0]["quest_id"]))
                self.assertEqual(len(app.sim.w["quests"]["completed"]), 1)

                retail = DT.city_retail_prices(app.sim, 1)
                item = next(it for it in retail["items"] if it["available"] > 0)
                self.assertIn("Куплено", run("shop", app.sim.burgs[1]["uk"], item["id"], "--qty", "1"))

                run("fork", "CLI гілка")
                self.assertTrue(any(s.get("fork") for s in app.list_slots()))

                run("fire", "drought", "--target", app.sim.states[1]["uk"], "--sev", "2")
                ev = next(e for e in app.sim.w["active_events"] if e["key"] == "drought")
                run("choice", str(ev["uid"]), LD.EVENT_CHOICES["drought"][0]["id"])
                self.assertFalse(any(e.get("uid") == ev["uid"] for e in app.sim.w["active_events"]))

                undo_before = app.overview()["undo_count"]
                run("undo")
                self.assertLess(app.overview()["undo_count"], undo_before)

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

    def test_trade_multiplier_cap_keeps_stock_non_negative(self):
        """Регресія: бум торгівлі (tmult > 1) не може продати більше, ніж є на складі."""
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=3)
            sim.w["mods"] = []
            sim.w["trade_routes"] = []
            sim.w["caravans"] = []
            sim.caravans = []
            sim.w["config"]["caravan_enabled"] = False
            sim.w["config"]["capital_constraint"] = False
            sim._index_mods()
            edge = next(e for e in sim.edges
                        if e.get("a") in sim.markets and e.get("b") in sim.markets and not e.get("sea"))
            src, dst = sim.markets[edge["a"]], sim.markets[edge["b"]]
            g = next(iter(sim.goods))
            base = sim.goods[g]["value"]
            for m in sim.markets.values():
                m["stock"] = {k: 0.0 for k in sim.goods}
            src["stock"][g] = 10.0
            src["price"][g] = base
            dst["price"][g] = base * 3.0
            dst["want"][g] = 10000.0
            # 2.5 * 2.5 = 6.25: без стелі tmult старий код списав би 17.5 з 10.
            sim.add_mod("market", edge["a"], "trade", 2.5, 1, "test_boom")
            sim.add_mod("market", edge["b"], "trade", 2.5, 1, "test_boom")
            sim._index_mods()
            sim.trade(random.Random(1))
            self.assertLessEqual(src["stock"][g], 10.0)
            self.assertGreaterEqual(src["stock"][g], 0.0)
            self.assertGreater(dst["stock"][g], 0.0)
            for mid, m in sim.markets.items():
                for gid, q in m["stock"].items():
                    self.assertGreaterEqual(q, -1e-9, msg=f"market {mid} good {gid}")

    def test_provinces_governors_and_territorial_war(self):
        with tempfile.TemporaryDirectory() as td:
            # 1) Автостворення провінцій для карти без provinces_raw + перевірка відсутності втрачених міст
            _, wpath, jpath, gpath, sim_auto = _build_calibrated_test_world(td, seed=5)
            self.assertGreaterEqual(len(sim_auto.provinces), 2)
            for b in sim_auto.burgs.values():
                self.assertIn(b.get("province"), sim_auto.provinces)
            with open(gpath, encoding="utf-8") as f:
                geo_auto = json.load(f)
            self.assertIn("prov_borders", geo_auto)

            # 2) Карта з явними провінціями, гербами coa та provinceBorders у SVG
            lines = _sample_vanilla_map_lines(with_svg=True).splitlines()
            lines[7] = (
                '<g id="stateBorders"><path d="M575,100 L575,500"/></g>'
                '<g id="provinceBorders"><path d="M350,100 L350,500"/><path d="M700,100 L700,500"/></g>'
            )
            lines[19] = json.dumps([
                {},
                {"i": 1, "name": "Aurelia", "state": 1, "culture": 1, "x": 280, "y": 240, "capital": True, "port": 1, "population": 18, "cell": 0, "feature": 1},
                {"i": 2, "name": "Riverford", "state": 1, "culture": 1, "x": 460, "y": 290, "capital": False, "port": 0, "population": 8, "cell": 1, "feature": 1},
                {"i": 3, "name": "Ironhold", "state": 2, "culture": 1, "x": 860, "y": 310, "capital": True, "port": 1, "population": 15, "cell": 4, "feature": 1},
                {"i": 4, "name": "Dustwatch", "state": 2, "culture": 1, "x": 640, "y": 290, "capital": False, "port": 0, "population": 7, "cell": 3, "feature": 1},
            ])
            lines[21] = "1,2,0,4,3,0"  # c_burg
            lines[31] = "1,2,1,4,3,3"  # c_prov
            lines[33] = json.dumps([
                0,
                {"i": 1, "name": "Valoria", "formName": "Province", "fullName": "Valoria Province", "state": 1, "center": 0, "burg": 1,
                 "color": "#66c2a5", "pole": [280, 240], "coa": {"t1": "gules", "shield": "heater", "ordinaries": [{"ordinary": "fess", "t": "or"}]}},
                {"i": 2, "name": "Riverford", "formName": "Duchy", "fullName": "Riverford Duchy", "state": 1, "center": 1, "burg": 2,
                 "color": "#77d3b6", "pole": [460, 290], "coa": {"t1": "azure", "shield": "round"}},
                {"i": 3, "name": "Ironhold", "formName": "Hold", "fullName": "Ironhold Hold", "state": 2, "center": 4, "burg": 3,
                 "color": "#fc8d62", "pole": [860, 310], "coa": {"t1": "sable", "shield": "swiss"}},
                {"i": 4, "name": "Dustwatch", "formName": "March", "fullName": "Dustwatch March", "state": 2, "center": 3, "burg": 4,
                 "color": "#e78ac3", "pole": [640, 290], "coa": {"t1": "vert", "shield": "heater"}},
            ])
            mp2 = os.path.join(td, "multiprov.map")
            with open(mp2, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            imp2 = IM.import_map(mp2)
            self.assertEqual(len(imp2["provinces"]), 4)
            geo2 = IM.extract_map_geometry(mp2, imp2)
            self.assertEqual(len(geo2["prov_borders"]), 2)

            w2 = WG.build_world(imp2, seed=7, start_year=1250, era="Н.Е.")
            w2 = E._intkeys(json.loads(json.dumps(w2)))
            w2.setdefault("history", dict(states=[], world=[]))
            w2.setdefault("journal", [])
            w2.setdefault("mods", [])
            sim = E.Sim(w2, seed=7)
            self.assertEqual(len(sim.provinces), 4)
            p4 = sim.provinces[4]
            self.assertEqual(p4["state"], 2)
            self.assertEqual(p4["core_state"], 2)
            self.assertTrue(p4["governor"]["name"])
            self.assertTrue(p4["blazon"])
            self.assertTrue(p4["lore"])

            # 3) Війна: облога -> окупація прикордонної провінції 4 -> мирна анексія на користь держави 1
            sim.states[1]["army"] = {"Піхота": 600, "Кіннота": 200, "Маги": 50}
            sim.states[2]["army"] = {"Піхота": 20}
            wr = {
                "id": 1, "name": "Прикордонна війна", "attackers": [1], "defenders": [2],
                "start_year": 1250, "start_month": 1, "score": 28.0, "casus": "Спірні провінції",
                "casualties": {1: 0, 2: 0}, "captured": [], "occupied_provs": [],
            }
            sim.w["wars"].append(wr)
            rng = random.Random(7)
            for _ in range(12):
                PO.step_provincial_front(sim, wr, [1], [2], rng)
                if p4["occupied_by"] == 1:
                    break
            self.assertEqual(p4["occupied_by"], 1)
            self.assertEqual(sim.burgs[4]["occupied_by"], 1)
            self.assertEqual(p4["state"], 2)
            self.assertGreater(wr["score"], 28.0)

            wr["score"] = 35.0
            PO.end_war(sim, wr, rng)
            self.assertEqual(p4["state"], 1)
            self.assertEqual(p4["core_state"], 2)
            self.assertIsNone(p4["occupied_by"])
            self.assertEqual(p4["siege"], 0)
            self.assertEqual(sim.burgs[4]["state"], 1)
            self.assertIsNone(sim.burgs[4]["occupied_by"])
            self.assertEqual(p4["assimilation"], 36)
            PO.step_governors(sim, rng)
            self.assertGreaterEqual(p4["assimilation"], 34)
            # Капітал держави 2 залишається валідним
            self.assertEqual(sim.burgs[sim.states[2]["capital"]]["state"], 2)

            # 4) Web API, overrides для провінції, D&D-квести та Obsidian-текст
            w2_path = os.path.join(td, "w2.json")
            j2_path = os.path.join(td, "j2.jsonl")
            E.save_world(sim.w, w2_path)
            app = web.AppState(w2_path, j2_path)
            app.overrides_file = os.path.join(td, "overrides2.json")
            pd = app.province_detail(4)
            self.assertEqual(pd["state"], 1)
            self.assertEqual(pd["core_state"], 2)
            ov = app.apply_override("province", 4, {"uk": "Пилоград", "loyalty": 88})
            self.assertTrue(ov["ok"])
            self.assertEqual(app.sim.provinces[4]["uk"], "Пилоград")
            self.assertEqual(app.sim.provinces[4]["governor"]["loyalty"], 88)

            quests = DT.generate_quest_hooks(app.sim, limit=6)
            self.assertTrue(len(quests) >= 1)
            md = RP.province_text(app.sim, 4)
            self.assertIn("Пилоград", md)

    def test_audit_core_safety(self):
        with tempfile.TemporaryDirectory() as td:
            bad_path = os.path.join(td, "bad.json")
            with self.assertRaises(ValueError):
                E.save_world({"treasury": float("nan")}, bad_path)
            self.assertFalse(os.path.exists(bad_path))

            bomb = os.path.join(td, "bomb.map.gz")
            with open(bomb, "wb") as f:
                f.write(gzip.compress(b"\0" * (70 * 1024 * 1024)))
            with self.assertRaises(ValueError):
                IM.import_map(bomb)

            _, _, _, _, sim = _build_calibrated_test_world(td, seed=101)
            cfg = json.dumps(sim.w["config"], sort_keys=True)
            stock = {mid: dict(m["stock"]) for mid, m in sim.markets.items()}
            date = dict(sim.w["date"])
            WG.calibrate(sim, log=lambda *_: None, warm_iters=5, months_per=2)
            self.assertEqual(json.dumps(sim.w["config"], sort_keys=True), cfg)
            self.assertEqual(sim.w["date"], date)
            self.assertEqual({mid: dict(m["stock"]) for mid, m in sim.markets.items()}, stock)

            sample_map, _, _, _, _ = _build_calibrated_test_world(td, seed=103)
            with open(sample_map, encoding="utf-8") as f:
                parsed = IM._parse_multiline_map(f.read(), sample_map)
            parsed["states_raw"] = {"1": {"name": "A"}, "2": {"name": "B"}}
            parsed["provinces_raw"] = {"1": {"name": "P"}, "2": {"name": "Q"}}
            malformed = os.path.join(td, "malformed.map")
            with open(malformed, "w", encoding="utf-8") as f:
                f.write("not json")
            with mock.patch.object(IM, "_parse_multiline_map", lambda *_: dict(parsed)):
                # Хибні словники мають відхилятися як ValueError, а не падати з TypeError
                # ще до перевірки типу (historical bug: states_raw[1:] / provinces_raw[1:]).
                with self.assertRaises(ValueError):
                    IM.import_map(malformed)

    def test_ai_war_declarations_are_reachable(self):
        """Регресія: AI має оголошувати війни навіть без подій, а сусідські
        відносини не повинні назавжди лишатися дружніми."""
        wars_total = 0
        max_relation = -101.0
        for seed in range(1, 13):
            with tempfile.TemporaryDirectory() as td:
                _, _, _, _, sim = _build_calibrated_test_world(td, seed=seed)
                sim.w["config"]["war_rate"] = 30.0
                sim.w["active_events"] = []
                for _ in range(360):
                    sim.tick(events=False)
                wars_total += len(sim.w.get("war_history") or [])
                if 1 in sim.states and 2 in sim.states:
                    max_relation = max(max_relation, PO.rel_get(sim, 1, 2))
        self.assertGreater(wars_total, 0, msg="AI жодного разу не оголосив війну без подій")
        self.assertLess(max_relation, 55.0,
                        msg=f"відносини сусідів лишаються дружніми: {max_relation}")

    def test_audit_politics_and_events_safety(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=131)
            sim.w["wars"] = []
            sim.w["war_history"] = []
            sim.w["active_events"] = []
            rng = random.Random(4)

            wr1 = PO.declare_war(sim, 1, 2, rng)
            wr2 = PO.declare_war(sim, 1, 2, rng)
            self.assertIs(wr1, wr2)
            self.assertEqual(len(sim.w["wars"]), 1)
            PO.end_war(sim, wr1, rng)
            self.assertIsNone(PO.declare_war(sim, 1, 2, rng))

            bad_choice = {"id": "evil", "label": "Evil",
                          "effects": {"state": {"capital": 999, "treasury": 50}}}
            sim.w["active_events"] = [dict(
                uid=9001, key="audit_evil", states=[1], sev=1,
                until=sim.tick_index() + 5, title="Хибна подія", target="", text="",
            )]
            capital = sim.states[1]["capital"]
            with mock.patch.dict(LD.EVENT_CHOICES, {"audit_evil": [bad_choice]}):
                self.assertFalse(EV.apply_event_choice(sim, 9001, "evil"))
            self.assertEqual(sim.states[1]["capital"], capital)

            sim.w["active_events"] = [dict(
                uid=9002, key="audit_stale", states=[1], sev=1,
                title="Подія без терміну", target="", text="",
            )]
            EV.step_events(sim, rng)
            self.assertFalse(any(e.get("uid") == 9002 for e in sim.w["active_events"]))

            sim.states[1]["ruler"]["traits"] = []
            sim.w["active_events"] = [dict(
                uid=9003, key="trade_boom", states=[1], sev=1,
                until=sim.tick_index() + 5, title="Торговий бум", target="", text="",
            )]
            self.assertTrue(EV.apply_event_choice(sim, 9003, "lower_tariff"))
            sim._index_mods()
            PO.sync_ruler_fields(sim)
            self.assertGreater(sim.states[1]["trade_mod"], 1.0)

    def test_audit_dnd_report_and_cli_safety(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=137)
            sim.states[1]["treasury"] = 100_000.0
            retail = DT.city_retail_prices(sim, 1)
            item = next(it for it in retail["items"] if it["available"] > 0)
            market = sim.markets[retail["market_id"]]
            reserved = dict(market.get("shop_reserved") or {})
            receipt = DT.purchase_shop_item(sim, 1, item["id"], 1)
            self.assertTrue(receipt["ok"])
            self.assertEqual(market.get("shop_reserved") or {}, reserved)

            hook = next(h for h in DT.generate_quest_hooks(sim, 1, limit=20)
                        if h.get("state_uk") == sim.states[1]["uk"])
            quest = DT.accept_quest(sim, hook["id"], state_id=1)
            self.assertIsNotNone(quest)
            again = DT.accept_quest(sim, hook["id"], state_id=1)
            self.assertEqual(again["quest_id"], quest["quest_id"])
            self.assertEqual(len(sim.w["quests"]["active"]), 1)
            treasury = sim.states[1]["treasury"]
            failed = DT.complete_quest(sim, quest["quest_id"], success=False)
            self.assertEqual(failed.get("paid_zm", 0), 0)
            self.assertEqual(sim.states[1]["treasury"], treasury)

            vault = os.path.join(td, "vault")
            os.makedirs(vault, exist_ok=True)
            sim.w["journal"] = [
                dict(y="../../evil", m=1, kind="x", text="небезпечно"),
                dict(y=1250, m=1, kind="x", text="**жирний** [текст](url)"),
            ]
            RP.write_journal(sim, vault, "hdr")
            self.assertFalse(os.path.exists(os.path.join(td, "evil.md")))
            journal_file = os.path.join(vault, "Журнал", "1250.md")
            with open(journal_file, encoding="utf-8") as f:
                content = f.read()
            self.assertIn(r"\*\*жирний\*\*", content)
            self.assertIn(r"\[текст\](url)", content)

            mpath = os.path.join(td, "testia.map")
            world_file = os.path.join(td, "world.json")
            journal_file_cli = os.path.join(td, "journal.jsonl")
            with open(world_file, "w", encoding="utf-8") as f:
                f.write("old world")
            with open(journal_file_cli, "w", encoding="utf-8") as f:
                f.write("old journal\n")
            args = argparse.Namespace(map=mpath, seed=1, year=1250, era="Н.Е.")
            with mock.patch.multiple(cli, WORLD_FILE=world_file, JOURNAL_FILE=journal_file_cli,
                                     SAVE_DIR=td, OVERRIDES=os.path.join(td, "overrides.json")), \
                    mock.patch.object(cli.WG, "calibrate", lambda *a, **k: None), \
                    mock.patch.object(cli.E, "save_world", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    cli.cmd_init(args)
            with open(world_file, encoding="utf-8") as f:
                self.assertEqual(f.read(), "old world")
            with open(journal_file_cli, encoding="utf-8") as f:
                self.assertEqual(f.read(), "old journal\n")

    def test_ui_templates_escape_dynamic_values(self):
        with open(web.UI_FILE, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("function jsArg", html)
        self.assertIn("chooseEvent(${jsArg(e.uid)},${jsArg(c.id)})", html)
        self.assertIn("loadSlot(${jsArg(s.id)})", html)
        self.assertIn("deleteSlot(${jsArg(s.id)})", html)
        self.assertIn("syncCfgNum(this,${jsArg(f.key)})", html)
        self.assertIn("syncCfgRange(this,${jsArg(f.key)})", html)
        self.assertNotIn("chooseEvent('${escHtml(e.uid)}'", html)
        self.assertNotIn("loadSlot('${escHtml(s.id)}'", html)
        self.assertNotIn("acceptQuest('${escHtml(h.id)}'", html)
        handlers = re.findall(r'on[a-z]+="[^"]*"', html)
        self.assertTrue(handlers)
        for attr in handlers:
            for expr in re.findall(r'\$\{([^}]*)\}', attr):
                self.assertTrue(expr.startswith("jsArg(") and expr.endswith(")"), attr)
        self.assertIn("D&D", html)
        self.assertIn("/api/map_geo", html)

    def test_caravan_highways_and_delivery(self):
        """Каравани існують як об'єкти маршруту, рухаються й розвантажуються."""
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=11)
            routes = sim.w.get("trade_routes") or []
            self.assertGreater(len(routes), 0, "магістралі не згенеровано з карти")
            self.assertLessEqual(len(routes), 24)
            seen_ids = set()
            for r in routes:
                self.assertNotIn(r["id"], seen_ids)
                seen_ids.add(r["id"])
                legs, mids = r["edges"], r["markets"]
                self.assertGreaterEqual(len(legs), 1)
                self.assertEqual(len(mids), len(legs) + 1)
                self.assertEqual(len(set(legs)), len(legs))
                for ei in legs:
                    self.assertGreaterEqual(ei, 0)
                    self.assertLess(ei, len(sim.edges))
                for mid in mids:
                    self.assertIn(mid, sim.markets)
                self.assertIsNotNone(RT.shortest_path(sim, mids[0], mids[-1]))

            saw_caravan = False
            for _ in range(24):
                sim.tick(events=False)
                saw_caravan = saw_caravan or bool(sim.caravans)
                for c in sim.caravans:
                    self.assertGreater(c["qty"], 0.0)
                    self.assertTrue(math.isfinite(c["qty"]))
                    self.assertIn(c["good"], sim.goods)
            self.assertTrue(saw_caravan, "жодного каравана не вирушило")
            arrivals = [r for r in sim.w["journal"] if str(r.get("text", "")).startswith("Караван прибув")]
            self.assertGreater(len(arrivals), 0, "жоден караван не дійшов до призначення")
            for m in sim.markets.values():
                for price in m["price"].values():
                    self.assertTrue(math.isfinite(price))

    def test_caravan_config_and_legacy_save(self):
        """Старі сейви без маршрутів відновлюються; вимкнення караванів нічого не ламає."""
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=12)
            w = sim.w
            w.pop("trade_routes", None)
            w["caravans"] = []
            fresh = E.Sim(w, seed=12)
            self.assertGreater(len(fresh.w["trade_routes"]), 0)
            self.assertEqual(fresh.caravans, [])
            fresh.w["config"]["caravan_enabled"] = False
            for _ in range(6):
                fresh.tick(events=False)
            self.assertEqual(fresh.caravans, [], "каравани створюються попри caravan_enabled=false")

    def test_geography_registry(self):
        """Географія з .map компактна, покриває ринки й провінції."""
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=13)
            geo = sim.w["geography"]
            self.assertTrue(geo["derived"])
            self.assertEqual(len(sim.goods), 83, "71 базовий товар + 12 регіональних")
            self.assertNotIn("c_biome", sim.w)
            self.assertNotIn("c_market", sim.w)
            self.assertEqual(set(geo["market_geo"]), set(sim.markets))
            self.assertEqual(set(geo["regions"]), set(sim.provinces))
            for mid, mg in geo["market_geo"].items():
                self.assertIn(mg["band"], GEO.BANDS)
                self.assertTrue(math.isfinite(mg["lat"]))
                self.assertIn(mg["coast"], (True, False))
                self.assertIn(mg["river"], (True, False))
            for rid, r in geo["regions"].items():
                self.assertTrue(all(mid in sim.markets for mid in r["markets"]))
                self.assertTrue(all(g in sim.goods for g in r["signature"]))
                self.assertTrue(all(g in sim.goods for g in r["specialties"]))
            self.assertGreater(sum(1 for mg in geo["market_geo"].values() if mg["biome"] is not None), 0)

    def test_geography_legacy_save(self):
        """Старий сейв без географії добудовуємо з meta/burgs і зберігаємо."""
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=14)
            w = sim.w
            w.pop("geography", None)
            fresh = E.Sim(w, seed=14)
            self.assertFalse(fresh.geography["derived"])
            self.assertEqual(set(fresh.geography["market_geo"]), set(fresh.markets))
            for mg in fresh.geography["market_geo"].values():
                self.assertIn(mg["band"], GEO.BANDS)
            path = os.path.join(td, "geo_world.json")
            E.save_world(fresh.w, path)
            loaded = E.Sim(E.load_world(path), seed=14)
            self.assertEqual(len(loaded.geography["market_geo"]), len(loaded.markets))
            loaded.tick(events=False)

    def test_special_goods_catalog_and_conversion(self):
        """Спецтовари конвертують сировину без друку вартості й працюють у симуляції."""
        with tempfile.TemporaryDirectory() as td:
            mpath = os.path.join(td, "spec.map")
            with open(mpath, "w", encoding="utf-8") as f:
                f.write(_sample_vanilla_map_lines(with_svg=True))
            imp = IM.import_map(mpath)
            self.assertEqual(len(imp["goods"]), 71)
            raw_before = {bid: dict(b.get("raw") or {}) for bid, b in imp["burgs"].items()}
            w = WG.build_world(imp, seed=13, start_year=1250, era="Н.Е.")
            special = {gid: gd for gid, gd in w["goods"].items() if gd.get("specialty")}
            self.assertEqual(len(w["goods"]), 83)
            self.assertEqual(set(special), set(range(101, 113)))
            for gid, gd in special.items():
                self.assertIn("specialty", gd["tags"])
                self.assertIn(gd["base"], w["goods"])
                self.assertAlmostEqual(gd["value"],
                                       w["goods"][gd["base"]]["value"] * gd["value_mult"], places=6)
                base_cover = w["goods"][gd["base"]]["cover"]
                if any(v > 0 for v in base_cover.values()):
                    self.assertTrue(any(v > 0 for v in gd["cover"].values()))
                for cat, cv in gd["cover"].items():
                    expected = w["goods"][gd["base"]]["cover"].get(cat, 0.0) * gd["value_mult"]
                    self.assertAlmostEqual(cv, expected, places=6, msg=f"{gid}:{cat}")
            converted = False
            for gid, gd in special.items():
                lost = 0.0
                for bid, b in w["burgs"].items():
                    lost += max(0.0, raw_before[bid].get(gd["base"], 0.0)
                                - b.get("raw", {}).get(gd["base"], 0.0))
                made = sum(b.get("raw", {}).get(gid, 0.0) for b in w["burgs"].values())
                if made > 0:
                    converted = True
                    self.assertAlmostEqual(made * gd["value_mult"], lost, places=4)
            self.assertTrue(converted, "жодного спецтовару не вироблено")
            region_specs = [r for r in w["geography"]["regions"].values() if r["specialties"]]
            self.assertGreater(len(region_specs), 0)
            for r in region_specs:
                self.assertTrue(all(g in w["goods"] for g in r["specialties"]))

            sim = E.Sim(E._intkeys(json.loads(json.dumps(w))), seed=13)
            WG.calibrate(sim, log=lambda *_: None, warm_iters=3, months_per=1)
            for _ in range(6):
                sim.tick(events=False)
            for m in sim.markets.values():
                for g in special:
                    self.assertGreaterEqual(m["stock"].get(g, 0.0), 0.0)
                    self.assertTrue(math.isfinite(m["price"].get(g, 0.0)))

    def test_special_goods_can_be_disabled(self):
        """Вимкнення спецтоварів не змінює базовий каталог і сировину."""
        with tempfile.TemporaryDirectory() as td:
            mpath = os.path.join(td, "nospec.map")
            with open(mpath, "w", encoding="utf-8") as f:
                f.write(_sample_vanilla_map_lines(with_svg=True))
            w = IM.import_map(mpath)
            raw_before = {bid: dict(b.get("raw") or {}) for bid, b in w["burgs"].items()}
            w["config"] = {"special_goods_enabled": False, "specialty_rate": 1.0}
            WG._apply_special_goods(w)
            self.assertEqual(len(w["goods"]), 71)
            self.assertEqual(raw_before, {bid: b.get("raw") for bid, b in w["burgs"].items()})
            for r in w["geography"]["regions"].values():
                self.assertEqual(r["specialties"], [])

    def test_corrupted_geography_is_rebuilt(self):
        """Пошкоджений шар географії не ламає завантаження й збереження."""
        with tempfile.TemporaryDirectory() as td:
            _, _, _, _, sim = _build_calibrated_test_world(td, seed=16)
            w = sim.w
            w["geography"] = {"market_geo": {"broken": {"lat": float("nan")}}, "regions": {}}
            fresh = E.Sim(w, seed=16)
            self.assertEqual(set(fresh.geography["market_geo"]), set(fresh.markets))
            self.assertTrue(all(isinstance(mid, int) for mid in fresh.geography["market_geo"]))
            self.assertTrue(all(math.isfinite(mg["lat"]) for mg in fresh.geography["market_geo"].values()))
            path = os.path.join(td, "rebuilt.json")
            E.save_world(fresh.w, path)
            E.Sim(E.load_world(path), seed=16).tick(events=False)

    def test_web_exposes_geography_and_specialties(self):
        """Overview/goods/market API віддає географію й спецтовари без помилок."""
        with tempfile.TemporaryDirectory() as td:
            _, wpath, jpath, _, _ = _build_calibrated_test_world(td, seed=17)
            app = web.AppState(wpath, jpath)
            ov = app.overview()
            self.assertIn("geography", ov)
            self.assertEqual(set(ov["geography"]),
                             {"biomes", "features", "regions", "market_geo", "goods", "derived"})
            self.assertTrue(ov["config_flags"]["geography_enabled"])
            self.assertTrue(ov["config_flags"]["special_goods_enabled"])
            self.assertGreater(len(ov["geography"]["goods"]), 0)
            local_mids = [m["id"] for m in ov["markets"] if m["specialties"]]
            self.assertGreater(len(local_mids), 0)
            for m in ov["markets"]:
                self.assertIn(m["band"], GEO.BANDS)
            rows = app.goods_table()["goods"]
            special_rows = [r for r in rows if r["specialty"]]
            self.assertEqual(len(special_rows), len(ov["geography"]["goods"]))
            detail = app.market_detail(local_mids[0])
            self.assertTrue(detail["geography"]["specialties"])
            self.assertTrue(all(s in ov["geography"]["goods"].values()
                                for s in detail["geography"]["specialties"]))
            cfg = app.config_data()
            keys = {f["key"] for f in cfg["fields"]}
            self.assertIn("specialty_rate", keys)
            self.assertIn("geography_enabled", keys)
            self.assertIn("special_goods_enabled", keys)

    def test_acceleration_geo_polygons_and_web_gzip(self):
        """Прискорення (orjson/numpy/lxml/shapely/pydantic) ідентичне stdlib і має фолбек."""
        sample = {1: {"name": "Ферія", "vals": [1.5, 2.25]}, "ok": True}
        b_fast = AC.json_dumps_bytes(sample, allow_nan=False, compact=True, non_str_keys=True, use_orjson=True)
        b_std = AC.json_dumps_bytes(sample, allow_nan=False, compact=True, non_str_keys=True, use_orjson=False)
        self.assertEqual(E._intkeys(AC.json_loads(b_fast)), E._intkeys(AC.json_loads(b_std, use_orjson=False)))
        with self.assertRaises(ValueError):
            AC.json_dumps_bytes({"x": float("nan")}, allow_nan=False)

        ratios = [0.8 + i * 0.05 for i in range(40)]
        weights = [1.0 + (i % 5) for i in range(40)]
        self.assertAlmostEqual(
            AC.np_weighted_ratio_mean(ratios, weights, use_numpy=True),
            AC.np_weighted_ratio_mean(ratios, weights, use_numpy=False),
            places=10,
        )

        # Самозакривний <g id="provs" .../> не має захоплювати наступні групи
        self.assertEqual(IM._svg_group_content('<svg><g id="provs"/><g id="zones"><path d="M0,0"/></g></svg>', "provs"), "")

        with tempfile.TemporaryDirectory() as td:
            _, wpath, jpath, _, _ = _build_calibrated_test_world(td, seed=19)
            w = E.load_world(wpath)
            raw_map = _sample_vanilla_map_lines(with_svg=True)
            geo_full = IM.extract_map_geometry(raw_map, w)
            with mock.patch.object(AC, "HAS_LXML", False), mock.patch.object(AC, "HAS_SHAPELY", False):
                geo_std = IM.extract_map_geometry(raw_map, w)
            self.assertEqual(geo_full["states"], geo_std["states"])
            self.assertEqual(geo_full["borders"], geo_std["borders"])
            self.assertEqual(geo_std["prov_bodies"], {})
            if AC.HAS_SHAPELY:
                self.assertEqual(set(geo_full["prov_bodies"]), {str(pid) for pid in w["provinces"]})

            app = web.AppState(wpath, jpath)
            app.overrides_file = os.path.join(td, "overrides.json")
            srv = web.ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(app))
            port = srv.server_port
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                base = f"http://127.0.0.1:{port}"
                req = urllib.request.Request(base + "/api/overview", headers={"Accept-Encoding": "gzip"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    self.assertEqual(r.headers.get("Content-Encoding"), "gzip")
                    ov = json.loads(gzip.decompress(r.read()).decode("utf-8"))
                    self.assertIn("accel", ov)

                req_async = urllib.request.Request(
                    base + "/api/step_async",
                    data=json.dumps({"months": 2}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_async, timeout=5) as r:
                    started = json.loads(r.read().decode("utf-8"))
                self.assertTrue(started["ok"])
                job = None
                for _ in range(50):
                    with urllib.request.urlopen(base + "/api/job?id=" + started["job_id"], timeout=5) as r:
                        job = json.loads(r.read().decode("utf-8"))
                    if job["status"] == "done":
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(job)
                self.assertEqual(job["status"], "done")
                self.assertEqual(job["done"], 2)
                self.assertEqual(job["overview"]["date"], "Березень 1250 Н.Е.")
            finally:
                srv.shutdown()
                srv.server_close()

    def test_geographic_edges_and_prospective_road_build(self):
        """Торгові потоки будуються планарно, трасують pack.routes і підтримують будівництво доріг."""
        markets = {1: {"id": 1, "burgs": [1]}, 2: {"id": 2, "burgs": [2]}, 3: {"id": 3, "burgs": [3]}}
        mk_center = {
            1: {"x": 100.0, "y": 200.0, "feature": 1, "port": False, "pop": 5000, "rural": 8000},
            2: {"x": 300.0, "y": 200.0, "feature": 1, "port": False, "pop": 6000, "rural": 9000},
            3: {"x": 500.0, "y": 200.0, "feature": 1, "port": False, "pop": 5500, "rural": 8500},
        }
        # Пара (1, 3) проходить крізь ринок 2 — планарний граф Габріеля має прибрати пряму хорду (1, 3).
        pair_units = {(1, 2): 25.0, (2, 3): 15.0, (1, 3): 40.0}
        routes_raw = [
            {"i": 0, "group": "roads", "points": [[100, 200, 0], [200, 235, 1], [300, 200, 2]]},
            {"i": 1, "group": "trails", "points": [[300, 200, 2], [400, 175, 3], [500, 200, 4]]},
        ]
        edges = RT.build_geographic_edges(markets, mk_center, pair_units, routes_raw=routes_raw, dist_scale=2.0)
        pairs = {(e["a"], e["b"]): e for e in edges}
        self.assertEqual(set(pairs), {(1, 2), (2, 3)})
        self.assertEqual(pairs[(1, 2)]["kind"], "road")
        self.assertGreaterEqual(len(pairs[(1, 2)]["pts"]), 3)
        self.assertEqual(pairs[(2, 3)]["kind"], "trail")

        with tempfile.TemporaryDirectory() as td:
            _, wpath, jpath, _, sim = _build_calibrated_test_world(td, seed=21)
            # Створюємо три ринки й тестуємо апгрейд застарілих хорд + рекомендації доріг
            sim.edges = [{"a": 1, "b": 2, "dist": 120.0, "cap": 10.0, "sea": False, "flow": 55.0}]
            self.assertTrue(RT.upgrade_legacy_edges(sim))
            self.assertEqual(sim.edges[0]["flow"], 55.0)
            self.assertIn("kind", sim.edges[0])
            self.assertIn("pts", sim.edges[0])
            sim.edges[0]["kind"] = "prospective"

            recs = RT.recommend_roads(sim, limit=5)
            self.assertTrue(recs)
            target_idx = recs[0]["edge_index"]
            prev_kind = sim.edges[target_idx]["kind"]

            E.save_world(sim.w, wpath)
            app = web.AppState(wpath, jpath)
            srv = web.ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(app))
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                base = f"http://127.0.0.1:{srv.server_port}"
                req = urllib.request.Request(
                    base + "/api/build_road",
                    data=json.dumps({"edge_index": target_idx}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    res = json.loads(r.read().decode("utf-8"))
                self.assertTrue(res["ok"])
                self.assertEqual(app.sim.edges[target_idx]["kind"], "road")
                undo = app.undo()
                self.assertTrue(undo["ok"])
                self.assertEqual(app.sim.edges[target_idx]["kind"], prev_kind)
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main()
