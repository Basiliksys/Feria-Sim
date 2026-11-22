# -*- coding: utf-8 -*-
"""Бенчмарк ключових етапів Feria-Sim: I/O, Sim.tick(), SVG/geo та короткий баланс-прогін."""
import os
import random
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    from feria_sim import engine as E, events as EV, politics as PO
    wpath = os.path.join(ROOT, "save", "world.json")
    if not os.path.isfile(wpath):
        print("save/world.json не знайдено — спершу виконайте `python -m feria_sim init`.")
        return

    t0 = time.perf_counter()
    w = E.load_world(wpath)
    t_load = time.perf_counter() - t0

    t0 = time.perf_counter()
    sim = E.Sim(w)
    t_build = time.perf_counter() - t0

    sim.tick()
    t0 = time.perf_counter()
    sim.tick()
    t_tick = time.perf_counter() - t0

    rng = random.Random(42)
    sim._index_mods()
    stages = {}
    for name, fn in [
        ("events", lambda: EV.step_events(sim, rng)),
        ("produce", lambda: sim.produce(1, rng)),
        ("trade", lambda: sim.trade(rng)),
        ("consume", lambda: sim.consume(1, rng)),
        ("prices", lambda: sim.update_prices()),
        ("finance", lambda: PO.step_finance(sim, rng)),
        ("pop", lambda: sim.update_population(1, rng)),
        ("politics", lambda: PO.step_politics(sim, rng)),
    ]:
        ts = time.perf_counter()
        fn()
        stages[name] = time.perf_counter() - ts

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "bench.json")
        ts = time.perf_counter()
        E.save_world(w, out)
        t_save = time.perf_counter() - ts

    print(f"load_world={t_load:.4f}s | build_runtime={t_build:.4f}s | 1_tick={t_tick:.4f}s | save_world={t_save:.4f}s")
    print("tick breakdown:", ", ".join(f"{k}={v:.4f}s" for k, v in stages.items()))


if __name__ == "__main__":
    main()
