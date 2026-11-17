# -*- coding: utf-8 -*-
"""Командний рядок симуляції Ферії.

  python -m feria_sim init   [--map ШЛЯХ] [--seed N]      імпорт карти + калібрування
  python -m feria_sim run    [--months N] [--report]       прогнати N місяців
  python -m feria_sim status                               зведення світу
  python -m feria_sim state  НАЗВА                         паспорт держави
  python -m feria_sim city   НАЗВА                         паспорт міста/ринку
  python -m feria_sim price  ТОВАР [--top N]               найдешевші/найдорожчі ринки
  python -m feria_sim events [--last N] [--kind K]         журнал подій
  python -m feria_sim wars                                 активні війни
  python -m feria_sim fire   КЛЮЧ [--target НАЗВА]         викликати подію вручну
  python -m feria_sim declare А Б                          оголосити війну (втручання майстра)
  python -m feria_sim set    держава поле значення         ручна правка (казна, податки…)
  python -m feria_sim report                               оновити нотатки Obsidian
"""
import argparse
import json
import os
import sys
import time

from . import lore_data as LD
from . import engine as E
from . import importer as IM
from . import worldgen as WG
from . import politics as PO
from . import events as EV
from . import report as RP
from . import dnd_tools as DT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MAP = os.path.join(os.path.expanduser("~"), "Downloads", "Feria 2026-09-21-12-26.map")
SAVE_DIR = os.path.join(ROOT, "save")
WORLD_FILE = os.path.join(SAVE_DIR, "world.json")
GEO_FILE = os.path.join(SAVE_DIR, "map_geo.json")
JOURNAL_FILE = os.path.join(SAVE_DIR, "journal.jsonl")
OVERRIDES = os.path.join(ROOT, "data", "overrides.json")


def _load_sim():
    if not os.path.exists(WORLD_FILE):
        sys.exit("Світ ще не ініціалізовано: python -m feria_sim init")
    w = E.load_world(WORLD_FILE)
    return E.Sim(w)


def _save(sim):
    new = sim.w.pop("_new_journal", [])
    if new:
        os.makedirs(SAVE_DIR, exist_ok=True)
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    E.save_world(sim.w, WORLD_FILE)


def find_state(sim, q):
    q = q.lower()
    for sid, st in sim.states.items():
        if q in (st["uk"].lower(), st["name"].lower(), st["full_name"].lower(), str(sid)):
            return sid
    for sid, st in sim.states.items():
        if q in st["uk"].lower() or q in st["name"].lower():
            return sid
    sys.exit(f"Державу «{q}» не знайдено")


def find_burg(sim, q):
    ql = q.lower()
    best = [b for b in sim.burgs.values() if ql in (b["name"].lower(), b["uk"].lower())]
    if not best:
        best = [b for b in sim.burgs.values() if ql in b["name"].lower() or ql in b["uk"].lower()]
    if not best:
        sys.exit(f"Місто «{q}» не знайдено")
    return max(best, key=lambda b: b["pop"])


def find_good(q):
    ql = q.lower()
    for gid, n in LD.GOODS_UK.items():
        if ql == n.lower() or ql == str(gid):
            return gid
    for gid, n in LD.GOODS_UK.items():
        if ql in n.lower():
            return gid
    sys.exit(f"Товар «{q}» не знайдено")


def cmd_init(a):
    t = time.time()
    src = a.map or DEFAULT_MAP
    if not os.path.exists(src):
        sys.exit(f"Файл карти не знайдено: {src}")
    print(f"Імпорт карти: {src}")
    imp = IM.import_map(src)
    over = {}
    if os.path.exists(OVERRIDES):
        with open(OVERRIDES, encoding="utf-8") as f:
            over = json.load(f)
    world = WG.build_world(imp, seed=a.seed, overrides=over, start_year=a.year, era=a.era)
    # зберігаємо ключі як int-рядки; Sim працює з int
    world = E._intkeys(json.loads(json.dumps(world)))
    sim = E.Sim(world, seed=a.seed)
    WG.calibrate(sim)
    # старт: чисті історія та журнал
    world["history"] = dict(states=[], world=[])
    world["journal"] = []
    world["mods"] = []
    sim.log("start", f"Симуляцію розпочато: {E.date_str(world)}. Світ {world['meta']['world_name']}: "
            f"{len(world['states'])} держав, {len(world['burgs'])} міст, {len(world['markets'])} ринків.")
    if os.path.exists(JOURNAL_FILE):
        os.remove(JOURNAL_FILE)
    _save(sim)
    geo = IM.extract_map_geometry(src, world)
    IM.save_map_geo(geo, GEO_FILE)
    print(f"Готово за {time.time() - t:.1f} с → {WORLD_FILE}")


def cmd_run(a):
    from . import web
    web.AppState(WORLD_FILE, JOURNAL_FILE)._push_undo(f"+{a.months} міс. (CLI)")
    sim = _load_sim()
    t = time.time()
    start = E.date_str(sim.w)

    def prog(i, n):
        if i % 12 == 0 or i == n:
            print(f"  … {i}/{n} міс. ({time.time() - t:.0f} с)", flush=True)
    sim.run(a.months, prog)
    _save(sim)
    print(f"{start} → {E.date_str(sim.w)} ({time.time() - t:.1f} с)")
    if a.report:
        RP.write_all(sim, a.vault)
    cmd_digest(sim, a.digest)


def cmd_digest(sim, n=15):
    new = [r for r in sim.w["journal"] if r.get("sev", 1) >= 3][-n:]
    print("\nОстанні важливі події:")
    for r in new:
        print(f"  [{LD.MONTHS_UK[r['m']-1][:3]} {r['y']}] {r['text']}")


def cmd_status(a):
    sim = _load_sim()
    print(RP.status_text(sim))


def cmd_state(a):
    sim = _load_sim()
    print(RP.state_text(sim, find_state(sim, a.name)))


def cmd_city(a):
    sim = _load_sim()
    print(RP.city_text(sim, find_burg(sim, a.name)["id"]))


def cmd_price(a):
    sim = _load_sim()
    g = find_good(a.good)
    rows = sorted(((m["price"].get(g, 0), m["uk"], m["stock"].get(g, 0), sim.market_state[mid]) for mid, m in sim.markets.items()))
    base = sim.goods[g]["value"]
    print(f"{LD.good_uk(g, sim.goods)} (база {base} од. = {LD.fmt_coins(base)}/{sim.goods[g]['unit']})")
    print("Найдешевше:")
    for p, n, s, sid in rows[:a.top]:
        print(f"  {n:<18} {p:6.2f} од. ({LD.fmt_coins(p)}), запас {s:8.1f}  [{sim.sname(sid)}]")
    print("Найдорожче:")
    for p, n, s, sid in rows[-a.top:][::-1]:
        print(f"  {n:<18} {p:6.2f} од. ({LD.fmt_coins(p)}), запас {s:8.1f}  [{sim.sname(sid)}]")


def cmd_events(a):
    sim = _load_sim()
    j = sim.w["journal"]
    if a.kind:
        j = [r for r in j if r["kind"] == a.kind]
    for r in j[-a.last:]:
        print(f"[{LD.MONTHS_UK[r['m']-1][:3]} {r['y']}] ({r['kind']}) {r['text']}")


def cmd_wars(a):
    sim = _load_sim()
    print(RP.wars_text(sim))


def cmd_fire(a):
    sim = _load_sim()
    spec = LD.EVENT_TABLE.get(a.key)
    if not spec:
        sys.exit("Невідомий ключ. Доступні: " + ", ".join(LD.EVENT_TABLE))
    sim.rng = __import__("random").Random(int(time.time()))
    sim._index_mods()
    sim.acc = dict(pop={}, gdp={})
    tgt = None
    sc = spec["scope"]
    if a.target:
        if sc == "state":
            tgt = find_state(sim, a.target)
        elif sc == "burg":
            tgt = find_burg(sim, a.target)["id"]
        elif sc == "market":
            tgt = find_burg(sim, a.target)["market"]
        else:
            sys.exit("Для цієї події --target не підтримується")
    EV.fire(sim, sim.rng, a.key, target=tgt, sev=a.sev)
    _save(sim)
    print(sim.w["journal"][-1]["text"] if sim.w["journal"] else "—")


def cmd_declare(a):
    sim = _load_sim()
    x, y = find_state(sim, a.a), find_state(sim, a.b)
    sim.rng = __import__("random").Random(int(time.time()))
    PO.declare_war(sim, x, y, sim.rng, casus="воля майстра гри")
    _save(sim)
    print(sim.w["journal"][-1]["text"])


def cmd_set(a):
    sim = _load_sim()
    sid = find_state(sim, a.state)
    st = sim.states[sid]
    if a.field not in ("treasury", "tax_mult", "stability", "legitimacy", "poll_tax", "sales_tax", "debt"):
        sys.exit("Дозволені поля: treasury, tax_mult, stability, legitimacy, poll_tax, sales_tax, debt")
    old = st[a.field]
    st[a.field] = float(a.value)
    sim.log("gm", f"Майстер гри змінив {a.field} держави {st['uk']}: {old} → {a.value}.", state=sid)
    _save(sim)
    print(f"{st['uk']}.{a.field}: {old} → {a.value}")


def cmd_report(a):
    sim = _load_sim()
    RP.write_all(sim, a.vault)


def cmd_serve(a):
    from . import web
    web.run_server(WORLD_FILE, JOURNAL_FILE, host=a.host, port=a.port,
                   vault=a.vault, open_browser=not a.no_browser)


def cmd_retail(a):
    sim = _load_sim()
    b = find_burg(sim, a.city)
    d = DT.city_retail_prices(sim, b["id"])
    mods = d["modifiers"]
    flags = [f"податок {mods['tax_pct']}%", f"індекс їжі {mods['food_index']:.2f}x"]
    if mods["is_capital"]:
        flags.append("столиця")
    if mods["in_war"]:
        flags.append("війна")
    if mods["black_rust"]:
        flags.append("Чорна Іржа")
    print(f"Роздрібні D&D-ціни: {d['burg_uk']} ({d['state_uk']}, ринок {d['market_uk']}) — {', '.join(flags)}")
    print(f"{'Позиція':<36} {'Категорія':<22} {'Ціна':>12} {'База':>7}  {'Наявність'}")
    for it in d["items"]:
        print(f"{it['name'][:35]:<36} {it['cat'][:21]:<22} {it['coins']:>12} {it['pct']:>5}%  {it['status']}")


def cmd_route(a):
    sim = _load_sim()
    b1, b2 = find_burg(sim, a.src), find_burg(sim, a.dst)
    r = DT.travel_route(sim, b1["id"], b2["id"], mode=a.mode)
    print(f"Маршрут: {r['from_uk']} → {r['to_uk']} ({r['mode_name']})")
    print(f"Відстань: {r['total_km']} км · Час: {r['total_days']} днів · Витрати: {r['cost_coins']} · Ризик: {r['danger_score']}/100 ({r['danger_level']})")
    if r["legs"]:
        print("\nВідрізки шляху:")
        for lg in r["legs"]:
            env = "море" if lg["sea"] else "суша"
            print(f"  {lg['from_name']} → {lg['to_name']} ({lg['state_uk']}): {lg['dist_km']} км, {lg['days']} дн., {env}")
    print("\nЗагрози:")
    if r["hazards"]:
        for h in r["hazards"]:
            print(f"  - {h}")
    else:
        print("  - Особливих загроз уздовж маршруту не виявлено.")
    print("\nМожливі D&D-зустрічі:")
    for enc in r["encounters"]:
        print(f"  * {enc}")


def cmd_quests(a):
    sim = _load_sim()
    sid = find_state(sim, a.state) if a.state else None
    hooks = DT.generate_quest_hooks(sim, state_id=sid)
    print(f"Квестові гачки ({len(hooks)}):")
    for i, h in enumerate(hooks, 1):
        print(f"{i}. [{h['category']}] {h['title']} — {h['patron']} | Нагорода: {h['reward']} ({h['urgency']})")
        print(f"   {h['text']}")


def cmd_undo(a):
    if not os.path.exists(WORLD_FILE):
        sys.exit("Світ ще не ініціалізовано.")
    from . import web
    res = web.AppState(WORLD_FILE, JOURNAL_FILE).undo()
    if res.get("error"):
        sys.exit(res["error"])
    ov = res["overview"]
    print(f"{res['message']} (поточна дата: {ov['date']})")


def main(argv=None):
    p = argparse.ArgumentParser(prog="feria_sim", description="Симуляція економіки та подій світу Ферії")
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("init")
    s.add_argument("--map")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--year", type=int, default=LD.START_YEAR)
    s.add_argument("--era", default=LD.ERA_SHORT)
    s.set_defaults(f=cmd_init)
    s = sp.add_parser("run"); s.add_argument("--months", type=int, default=1); s.add_argument("--report", action="store_true")
    s.add_argument("--vault", default=None); s.add_argument("--digest", type=int, default=12); s.set_defaults(f=cmd_run)
    s = sp.add_parser("status"); s.set_defaults(f=cmd_status)
    s = sp.add_parser("state"); s.add_argument("name"); s.set_defaults(f=cmd_state)
    s = sp.add_parser("city"); s.add_argument("name"); s.set_defaults(f=cmd_city)
    s = sp.add_parser("price"); s.add_argument("good"); s.add_argument("--top", type=int, default=5); s.set_defaults(f=cmd_price)
    s = sp.add_parser("events"); s.add_argument("--last", type=int, default=20); s.add_argument("--kind"); s.set_defaults(f=cmd_events)
    s = sp.add_parser("wars"); s.set_defaults(f=cmd_wars)
    s = sp.add_parser("fire"); s.add_argument("key"); s.add_argument("--target"); s.add_argument("--sev", type=int); s.set_defaults(f=cmd_fire)
    s = sp.add_parser("declare"); s.add_argument("a"); s.add_argument("b"); s.set_defaults(f=cmd_declare)
    s = sp.add_parser("set"); s.add_argument("state"); s.add_argument("field"); s.add_argument("value"); s.set_defaults(f=cmd_set)
    s = sp.add_parser("report"); s.add_argument("--vault", default=None); s.set_defaults(f=cmd_report)
    s = sp.add_parser("serve", help="Запустити веб-панель симуляції")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--vault", default=None)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(f=cmd_serve)
    s = sp.add_parser("retail", help="Роздрібні D&D-ціни у місті"); s.add_argument("city"); s.set_defaults(f=cmd_retail)
    s = sp.add_parser("route", help="Маршрут і небезпека подорожі між містами")
    s.add_argument("src"); s.add_argument("dst")
    s.add_argument("--mode", choices=("foot", "wagon", "horse", "ship"), default="foot")
    s.set_defaults(f=cmd_route)
    s = sp.add_parser("quests", help="Квестові гачки з поточних подій світу")
    s.add_argument("--state", default=None); s.set_defaults(f=cmd_quests)
    s = sp.add_parser("undo", help="Відкотити останній крок симуляції"); s.set_defaults(f=cmd_undo)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
