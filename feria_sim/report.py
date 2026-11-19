# -*- coding: utf-8 -*-
"""Текстові звіти та генерація нотаток Obsidian."""
import os
import re
import shutil
import collections

from . import lore_data as LD
from . import engine as E
from . import politics as PO
from . import dnd_tools as DT

DEFAULT_VAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "DnD1", "D&D1", "Симуляція")


def fmt_n(x):
    x = float(x)
    if abs(x) >= 1e6:
        return f"{x/1e6:.2f} млн"
    if abs(x) >= 1e3:
        return f"{x/1e3:.1f} тис."
    return f"{x:.0f}"


def safe(name):
    return re.sub(r'[\\/:*?"<>|#^\[\]]', "", name).strip()


def sstate(sim, sid):
    return sim.states[sid]


def state_summary(sim, sid):
    st = sim.states[sid]
    heads = PO.heads(st)
    return dict(
        pop=st.get("pop", 0), gdp=st.get("gdp", 0.0), treasury=st["treasury"], stab=st["stability"],
        power=PO.state_power(sim, sid), heads=heads, rev=st.get("rev", 0.0), exp=st.get("exp", 0.0),
        food=st["food_sat"], debt=st["debt"],
    )


def status_text(sim):
    w = sim.w
    lines = [f"Дата: {E.date_str(w)}   Війн: {len(w['wars'])}   Подій у журналі: {len(w['journal'])}"]
    tot_pop = sum(st.get("pop", 0) for st in sim.states.values())
    tot_gdp = sum(st.get("gdp", 0) for st in sim.states.values())
    lines.append(f"Населення світу: {fmt_n(tot_pop)}   ВВП/міс: {fmt_n(tot_gdp)} од.   Індекс цін їжі: {sim.price_index('food'):.2f}")
    top = sorted(sim.states.items(), key=lambda kv: -kv[1].get("gdp", 0))[:12]
    lines.append("\nТоп держав за ВВП:")
    lines.append(f"{'Держава':<32} {'Насел.':>10} {'ВВП':>10} {'Казна':>10} {'Стаб':>5} {'Сила':>11}")
    for sid, st in top:
        s = state_summary(sim, sid)
        lines.append(f"{st['uk'][:31]:<32} {fmt_n(s['pop']):>10} {fmt_n(s['gdp']):>10} {fmt_n(s['treasury']):>10} {s['stab']:>5.0f} {fmt_n(s['power']):>11}")
    if w["wars"]:
        lines.append("\nВійни:")
        for wr in w["wars"]:
            lines.append("  " + wars_line(sim, wr))
    return "\n".join(lines)


def wars_line(sim, wr):
    a = ", ".join(sim.sname(x) for x in wr["attackers"])
    d = ", ".join(sim.sname(x) for x in wr["defenders"])
    since = f"{LD.MONTHS_UK[wr['start_month']-1][:3]} {wr['start_year']}"
    return f"{wr['name']}: [{a}] ↔ [{d}] з {since}, рахунок {wr['score']:+.0f} (+ на користь агресора), захоплено міст: {len(wr['captured'])}"


def wars_text(sim):
    w = sim.w
    if not w["wars"]:
        return "Активних війн немає."
    return "\n".join(wars_line(sim, wr) for wr in w["wars"])


def top_relations(sim, sid, n=5):
    rows = []
    for o in sim.states:
        if o == sid:
            continue
        rows.append((PO.rel_get(sim, sid, o), o))
    rows.sort()
    return rows[:n], rows[-n:][::-1]


def state_text(sim, sid):
    st = sim.states[sid]
    s = state_summary(sim, sid)
    r = st["ruler"]
    lines = [f"{st['uk']} ({st['name']}) — {st['continent']}, {st['gov_text']}",
             f"Правитель: {r['name']}" + (f", {r['age']} р." if r["age"] else "") + f"; риси: {', '.join(LD.RULER_TRAITS[t]['label'] for t in r['traits'])}",
             f"Культура: {st['culture_name']}; релігія: {st['religion_name']}; валюта: {st['coins']}",
             f"Населення {fmt_n(s['pop'])}; міст {len(sim.state_burgs.get(sid, []))}; столиця {sim.bname(st['capital'])}",
             f"ВВП/міс {fmt_n(s['gdp'])}; казна {fmt_n(s['treasury'])} (борг {fmt_n(s['debt'])}); дохід {fmt_n(s['rev'])}, витрати {fmt_n(s['exp'])}",
             f"Стабільність {s['stab']:.0f}; легітимність {st['legitimacy']:.0f}; виснаження війною {st['war_exhaustion']:.0f}; задоволення їжею {st['food_sat']*100:.0f}%",
             f"Армія: {', '.join(f'{u} {n}' for u, n in st['army'].items())} (сила {fmt_n(s['power'])}, готовність {st['readiness']:.2f})"]
    low, high = top_relations(sim, sid, 4)
    lines.append("Найгірші відносини: " + ", ".join(f"{sim.sname(o)} ({sc:+.0f})" for sc, o in low))
    lines.append("Найкращі відносини: " + ", ".join(f"{sim.sname(o)} ({sc:+.0f})" for sc, o in high))
    ws = PO.in_war(sim, sid)
    if ws:
        lines.append("Війни: " + "; ".join(wr["name"] for wr in ws))
    return "\n".join(lines)


def city_text(sim, bid):
    b = sim.burgs[bid]
    m = sim.markets[b["market"]]
    sid = b["state"]
    lines = [f"{b['uk']} ({b['name']}) — {sim.sname(sid)}; ринок {m['uk']}",
             f"Населення: міське {fmt_n(b['pop'])}, сільське {fmt_n(b['rural'])}; {'порт, ' if b['port'] else ''}{'мури, ' if b['walls'] else ''}{'храм' if b['temple'] else ''}",
             "Задоволення потреб: " + ", ".join(f"{LD.CATEGORY_UK[c]} {v*100:.0f}%" for c, v in b.get("sat", {}).items()),
             "Ціни ринку (відхилення від бази):"]
    rows = []
    for g, p in m["price"].items():
        base = sim.goods[g]["value"]
        rows.append((p / base, g, p))
    rows.sort()
    for r, g, p in rows[:6] + rows[-6:]:
        lines.append(f"  {LD.good_uk(g, sim.goods):<18}{p:7.2f} од. ({LD.fmt_coins(p)}) {r*100:5.0f}% бази, запас {m['stock'].get(g,0):9.1f}")
    retail = DT.city_retail_prices(sim, bid)
    lines.append("Роздрібні D&D-ціни (витяг):")
    for it in retail["items"][:8]:
        lines.append(f"  {it['name']:<32} {it['coins']} ({it['pct']}% бази, {it['status']})")
    return "\n".join(lines)


def province_text(sim, pid):
    pr = sim.provinces[pid]
    sid = pr["state"]
    core = pr.get("core_state", sid)
    occ = pr.get("occupied_by")
    gov = pr.get("governor") or {}
    traits = ", ".join(LD.GOVERNOR_TRAITS.get(t, {}).get("label", t) for t in gov.get("traits", []))
    p_burgs = sorted((sim.burgs[b] for b in pr.get("burgs", []) if b in sim.burgs), key=lambda x: -x["pop"])
    pop_tot = sum(b["pop"] + b["rural"] for b in p_burgs)
    status = f"Окупована ({sim.sname(occ)})" if occ else (f"В облозі ({pr.get('siege', 0):.0f}%)" if pr.get("siege", 0) > 0 else ("Корінна земля" if core == sid else f"Анексована (корінна: {sim.sname(core)})"))
    lines = [
        f"{pr['uk']} ({pr['name']}) — {sim.sname(sid)} [{status}]",
        f"Адмін. центр: {sim.bname(pr.get('burg'))}; населення провінції: {fmt_n(pop_tot)} ({len(p_burgs)} міст)",
        f"Намісник: {gov.get('name', '—')}" + (f", {gov['age']} р." if gov.get("age") else "") + f"; риси: {traits}; лояльність: {gov.get('loyalty', 70):.0f}%",
        f"Герб: {pr.get('blazon', '—')}",
        f"Економічний профіль: {pr.get('specialty', '—')}",
        f"Лор: {pr.get('lore', '—')}",
        "Міста провінції: " + ", ".join(f"{b['uk']} ({fmt_n(b['pop'] + b['rural'])})" for b in p_burgs[:10]),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Obsidian
# ---------------------------------------------------------------------------
HDR = "---\ntags: [симуляція, авто]\nоновлено: \"{d}\"\n---\n> [!warning] Файл генерується автоматично (`python -m feria_sim report`). Ручні правки буде перезаписано.\n\n"


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_all(sim, vault=None):
    if not vault:
        if sim.w.get("meta", {}).get("is_feria", True):
            vault = DEFAULT_VAULT
        else:
            vault = os.path.join(DEFAULT_VAULT, safe(sim.w.get("meta", {}).get("world_name", "Світ")))
    d = E.date_str(sim.w)
    hdr = HDR.format(d=d)
    n = 0
    n += write_dashboard(sim, vault, hdr)
    n += write_states(sim, vault, hdr)
    n += write_markets(sim, vault, hdr)
    n += write_goods(sim, vault, hdr)
    n += write_journal(sim, vault, hdr)
    n += write_misc(sim, vault, hdr)
    n += write_session_prep(sim, vault, hdr)
    print(f"Нотатки Obsidian оновлено: {n} файлів → {vault}")


def write_dashboard(sim, vault, hdr):
    w = sim.w
    tot_pop = sum(st.get("pop", 0) for st in sim.states.values())
    tot_gdp = sum(st.get("gdp", 0) for st in sim.states.values())
    L = [hdr, f"# Дашборд симуляції Ферії\n\n**Дата:** {E.date_str(w)}  \n**Населення світу:** {fmt_n(tot_pop)}  \n"
         f"**ВВП за місяць:** {fmt_n(tot_gdp)} од. (1 од. = {LD.fmt_coins(1)})  \n**Індекс цін на їжу:** {sim.price_index('food'):.2f} (1.00 = база)  \n"
         f"**Активних війн:** {len(w['wars'])}  \n\nНавігація: [[Наступна сесія]] · [[Війни]] · [[Товари]] · [[Гільдії та найманці]] · [[Похід на Кірос]] · [[Правила симуляції]] · [[Ціна]] · [[Світ]]\n"]
    L.append("\n## Держави (за ВВП)\n\n| Держава | Континент | Населення | ВВП/міс | Казна | Стабільність | Армія (сила) | Годування |\n|---|---|---:|---:|---:|---:|---:|---:|")
    for sid, st in sorted(sim.states.items(), key=lambda kv: -kv[1].get("gdp", 0)):
        s = state_summary(sim, sid)
        L.append(f"| [[Держави/{safe(st['uk'])}\\|{st['uk']}]] | {st['continent']} | {fmt_n(s['pop'])} | {fmt_n(s['gdp'])} | {fmt_n(s['treasury'])} | {s['stab']:.0f} | {fmt_n(s['power'])} | {st['food_sat']*100:.0f}% |")
    L.append("\n## Війни\n")
    L.append("\n".join("- " + wars_line(sim, wr) for wr in w["wars"]) or "Мир.")
    L.append("\n## Активні події\n")
    ev = sorted(w.get("active_events", []), key=lambda e: -e["sev"])[:25]
    y0 = w.get("meta", {}).get("start_year", LD.START_YEAR)
    L.append("\n".join(f"- **{e['title']}** ({e['target']}, ступінь {e['sev']}, до {(e['until'] - 0) // 12 + y0} р.): {e['text']}" for e in ev) or "—")
    L.append("\n## Останні важливі події\n")
    for r in [r for r in w["journal"] if r.get("sev", 1) >= 2][-30:][::-1]:
        L.append(f"- *{LD.MONTHS_UK[r['m']-1]} {r['y']}* — {r['text']}")
    _w(os.path.join(vault, "Дашборд.md"), "\n".join(L) + "\n")
    return 1


def write_states(sim, vault, hdr):
    n = 0
    states_dir = os.path.join(vault, "Держави")
    archive_dir = os.path.join(states_dir, "Архів")
    active_files = set()
    for sid, st in sim.states.items():
        burgs_list = sim.state_burgs.get(sid, [])
        fname = safe(st["uk"]) + ".md"
        if not burgs_list:
            continue
        active_files.add(fname)
        s = state_summary(sim, sid)
        r = st["ruler"]
        fm = (f"---\ntags: [симуляція, авто, держава]\nоновлено: \"{E.date_str(sim.w)}\"\nконтинент: {st['continent']}\n"
              f"населення: {int(s['pop'])}\nввп_міс: {s['gdp']:.1f}\nказна: {s['treasury']:.1f}\nстабільність: {s['stab']:.1f}\n"
              f"сила_армії: {s['power']:.1f}\nвійни: {len(PO.in_war(sim, sid))}\n---\n")
        L = [fm, "> [!warning] Файл генерується автоматично.\n", f"# {st['uk']}\n",
             f"*{st['full_name']}* · {st['continent']} · [[Світ]]\n", st["lore"] + "\n" if st["lore"] else ""]
        L.append(f"- **Правитель:** {r['name']}" + (f" ({r['age']} р.)" if r["age"] else "") +
                 f" — {', '.join(LD.RULER_TRAITS[t]['label'] for t in r['traits'])}")
        L.append(f"- **Форма правління:** {st['gov_text']}\n- **Культура / релігія:** {st['culture_name']} / {st['religion_name']}\n- **Валюта:** {st['coins']}")
        L.append(f"- **Населення:** {fmt_n(s['pop'])} · **міст:** {len(burgs_list)} · **столиця:** {sim.bname(st['capital'])}")
        L.append(f"- **Економіка:** ВВП/міс {fmt_n(s['gdp'])} од.; казна {fmt_n(s['treasury'])} ({LD.fmt_coins(s['treasury'])}); борг {fmt_n(s['debt'])}")
        ib = st.get("income_breakdown", {})
        if ib:
            L.append("- **Бюджет/міс:** " + ", ".join(f"{k} {v:,.0f}" for k, v in ib.items()))
        L.append(f"- **Стабільність:** {s['stab']:.0f} · легітимність {st['legitimacy']:.0f} · виснаження війною {st['war_exhaustion']:.0f} · їжа {st['food_sat']*100:.0f}%")
        L.append("- **Армія:** " + ", ".join(f"{u} {n}" for u, n in st["army"].items()) + f" (сила {fmt_n(s['power'])}, готовність {st['readiness']:.2f})")
        if st["mercs"]:
            L.append("- **Найманці:** " + ", ".join(m["name"] for m in st["mercs"]))
        ws = PO.in_war(sim, sid)
        L.append("\n## Війни\n" + ("\n".join("- " + wars_line(sim, wr) for wr in ws) or "Мир."))
        low, high = top_relations(sim, sid, 5)
        L.append("\n## Відносини\n\n**Найгірші:** " + ", ".join(f"{sim.sname(o)} ({sc:+.0f})" for sc, o in low) +
                 "\n\n**Найкращі:** " + ", ".join(f"{sim.sname(o)} ({sc:+.0f})" for sc, o in high))
        bl = sorted(burgs_list, key=lambda b: -sim.burgs[b]["pop"])[:12]
        L.append("\n## Найбільші міста\n\n| Місто | Населення | Ринок | Особливості |\n|---|---:|---|---|")
        for b in bl:
            bb = sim.burgs[b]
            L.append(f"| {bb['uk']} | {fmt_n(bb['pop'] + bb['rural'])} | [[Ринки/{safe(sim.markets[bb['market']]['uk'])}\\|{sim.markets[bb['market']]['uk']}]] | "
                     f"{'столиця ' if bb['capital'] else ''}{'порт ' if bb['port'] else ''}{'мури ' if bb['walls'] else ''}{'храм' if bb['temple'] else ''} |")
        pids = sim.state_provinces.get(sid, [])
        if pids:
            L.append("\n## Провінції та намісники\n\n| Провінція | Центр | Намісник | Лояльність | Спеціалізація | Статус |\n|---|---|---|---:|---|---|")
            for pid in sorted(pids, key=lambda x: -sum(sim.burgs[b]["pop"] + sim.burgs[b]["rural"] for b in sim.provinces[x].get("burgs", []) if b in sim.burgs))[:25]:
                pr = sim.provinces[pid]
                gov = pr.get("governor") or {}
                occ = pr.get("occupied_by")
                st_str = f"Окупована ({sim.sname(occ)})" if occ else (f"Облога {pr.get('siege', 0):.0f}%" if pr.get("siege", 0) > 0 else ("Корінна" if pr.get("core_state", sid) == sid else f"Анексована ({sim.sname(pr.get('core_state'))})"))
                L.append(f"| {pr['uk']} | {sim.bname(pr.get('burg'))} | {gov.get('name', '—')} | {gov.get('loyalty', 70):.0f}% | {pr.get('specialty', '—')} | {st_str} |")
        # індекс цін + роздрібні D&D-ціни столиці
        L.append(f"\n## Ціни в державі\n\nІндекс цін на їжу: **{sim.price_index('food', sid):.2f}**, побут: {sim.price_index('utilities', sid):.2f}, розкіш: {sim.price_index('luxury', sid):.2f} "
                 f"(множник до роздрібних цін з [[Ціна]]).")
        cap_id = st["capital"] if st["capital"] in sim.burgs else bl[0]
        retail = DT.city_retail_prices(sim, cap_id)
        L.append(f"\n### Роздрібні D&D-ціни ({retail['burg_uk']})\n\n| Позиція | Ціна | % бази | Наявність |\n|---|---:|---:|---|")
        for it in retail["items"][:12]:
            L.append(f"| {it['name']} | {it['coins']} | {it['pct']}% | {it['status']} |")
        ev = [r for r in sim.w["journal"] if sid in (r.get("states") or []) or r.get("state") == sid][-12:][::-1]
        L.append("\n## Хроніка\n" + "\n".join(f"- *{LD.MONTHS_UK[r['m']-1]} {r['y']}* — {r['text']}" for r in ev))
        _w(os.path.join(states_dir, fname), "\n".join(L) + "\n")
        n += 1

    # Архівація неактивних або ліквідованих держав
    if os.path.isdir(states_dir):
        for fn in os.listdir(states_dir):
            if fn.endswith(".md") and fn not in active_files:
                os.makedirs(archive_dir, exist_ok=True)
                shutil.move(os.path.join(states_dir, fn), os.path.join(archive_dir, fn))
    return n


def write_markets(sim, vault, hdr):
    n = 0
    for mid, m in sim.markets.items():
        sid = sim.market_state[mid]
        L = [hdr, f"# Ринок {m['uk']}\n", f"Держава: [[Держави/{safe(sim.sname(sid))}\\|{sim.sname(sid)}]] · міст на ринку: {len(m['burgs'])} · "
             f"торгових шляхів: {len(m['edges'])}\n"]
        routes = []
        for ei in m["edges"]:
            e = sim.edges[ei]
            o = e["b"] if e["a"] == mid else e["a"]
            routes.append(f"{sim.markets[o]['uk']} ({e['dist']:.0f} км, {'море' if e['sea'] else 'суша'}, потік {e.get('flow', 0):.0f})")
        L.append("**Маршрути:** " + "; ".join(routes) + "\n")
        L.append("| Товар | Ціна | Монети | % бази | Запас |\n|---|---:|---|---:|---:|")
        for g in sorted(m["price"], key=lambda g: -sim.goods[g]["value"]):
            p = m["price"][g]
            base = sim.goods[g]["value"]
            L.append(f"| {LD.good_uk(g, sim.goods)} ({sim.goods[g]['unit']}) | {p:.2f} | {LD.fmt_coins(p)} | {p/base*100:.0f}% | {m['stock'].get(g, 0):.0f} |")
        _w(os.path.join(vault, "Ринки", safe(m["uk"]) + ".md"), "\n".join(L) + "\n")
        n += 1
    return n


def write_goods(sim, vault, hdr):
    L = [hdr, "# Товари: світові ціни\n\nОдиниця вартості = 1 віз зерна ≈ 1 зм (оптові лоти, не роздріб).\n",
         "| Товар | Одиниця | База | Мін | Середня | Макс | Де дешево | Де дорого |\n|---|---|---:|---:|---:|---:|---|---|"]
    for g in sorted(sim.goods):
        rows = sorted((m["price"].get(g, 0), m["uk"]) for m in sim.markets.values())
        avg = sum(p for p, _ in rows) / len(rows)
        L.append(f"| {LD.good_uk(g, sim.goods)} | {sim.goods[g]['unit']} | {sim.goods[g]['value']} | {rows[0][0]:.2f} | {avg:.2f} | {rows[-1][0]:.2f} | {rows[0][1]} | {rows[-1][1]} |")
    _w(os.path.join(vault, "Товари.md"), "\n".join(L) + "\n")
    return 1


def write_journal(sim, vault, hdr):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "save", "journal.jsonl")
    import json
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    by_year = collections.defaultdict(list)
    for r in rows:
        by_year[r["y"]].append(r)
    era = sim.w.get("meta", {}).get("era", LD.ERA_SHORT)
    for y, rs in by_year.items():
        L = [hdr, f"# Журнал {y} {era}\n"]
        cur = None
        for r in rs:
            if r["m"] != cur:
                cur = r["m"]
                L.append(f"\n### {LD.MONTHS_UK[cur-1]}\n")
            L.append(f"- `{r['kind']}` {r['text']}")
        _w(os.path.join(vault, "Журнал", f"{y}.md"), "\n".join(L) + "\n")
    return len(by_year)


def write_misc(sim, vault, hdr):
    w = sim.w
    # війни
    L = [hdr, "# Війни\n\n## Активні\n"]
    L.append("\n".join("- " + wars_line(sim, wr) for wr in w["wars"]) or "Мир.")
    L.append("\n## Завершені\n")
    for h in w["war_history"][-60:][::-1]:
        a, d = h["attacker"], h["defender"]
        L.append(f"- {h['name']} ({h['start']}–{h.get('end') or '…'}): {sim.sname(a)} проти {sim.sname(d)}" + (f" — {h['result']}" if h.get("result") else ""))
    _w(os.path.join(vault, "Війни.md"), "\n".join(L) + "\n")
    # гільдії
    L = [hdr, "# Гільдії та найманці\n\n## Гільдії\n\n| Гільдія | Тип | Місто | Багатство | Монополії |\n|---|---|---|---:|---|"]
    for g in w["guilds"]:
        L.append(f"| {g['name']} | {g['kind']} | {sim.bname(g['burg'])} ({sim.sname(g['state'])}) | {fmt_n(g['wealth'])} | {', '.join(LD.good_uk(x, sim.goods) for x in g['goods'])} |")
    L.append("\n## Найманці\n")
    for m in w["mercs"]:
        emp = sim.sname(m["employer"]) if m["employer"] and sim.tick_index() < (m["contract_end"] or 0) else "вільні"
        L.append(f"- **{m['name']}** — {m['size']} бійців ({m['unit']}); база: {sim.sname(m['home']) if m['home'] else '—'}; зараз: {emp}")
    L.append("\n## Ордени\n")
    for o in w["orders"]:
        L.append(f"- **{o['name']}** — {o['strength']} ({o['unit']}), держава: {sim.sname(o['state']) if o['state'] else 'наддержавний'}")
    _w(os.path.join(vault, "Гільдії та найманці.md"), "\n".join(L) + "\n")
    # похід
    cr = w["crusade"]
    L = [hdr, f"# {cr['name']}\n\n**Фаза:** {cr['phase']} · готовність постачання {cr['progress']*100:.0f}% · результат: {cr['result'] or 'невідомий'}\n",
         "**Спонсори:** " + ", ".join(sim.sname(s) for s in cr["sponsors"] if s in sim.states) + "\n",
         "Дивись [[Четвертий Похід на Кірос]] та [[Хронологія Епох і Походи на Кірос]]."]
    L.append("\n## Журнал Походу\n")
    for r in [r for r in w["journal"] if r["kind"] == "crusade"]:
        L.append(f"- *{LD.MONTHS_UK[r['m']-1]} {r['y']}* — {r['text']}")
    _w(os.path.join(vault, "Похід на Кірос.md"), "\n".join(L) + "\n")
    _w(os.path.join(vault, "Правила симуляції.md"), RULES_MD.replace("{hdr}", hdr))
    return 4


RULES_MD = """{hdr}
# Правила симуляції економіки та подій

Крок = 1 місяць. Дані з карти Azgaar (`Feria 2026-09-21-12-26.map`): 73 держави, 933 міста, 47 ринків, 71 товар із рецептами.

1. **Виробництво.** Село (кожна клітинка карти віддає сировину ринку за біомом/родовищем) + ремесло міст за рецептами (`Інструменти = Залізо + Вугілля` тощо). Сезонність за широтою (південна півкуля — інвертована).
2. **Торгівля.** Купці везуть товар між сусідніми ринками, якщо різниця цін > вартість перевезення + мито. Мито залежить від відносин держав; війна й ембарго майже зупиняють торгівлю (контрабанда).
3. **Споживання.** Їжа, побут/паливо, будівництво, розкіш; нестача їжі = смертність, нестача палива взимку = смертність.
4. **Ціни.** `ціна = база × (цільовий запас / запас)^0.5`, межі 0.3×…6× бази.
5. **Держави.** Податки (подушний + з продажу + мито), утримання армії та двору, закупівля військового спорядження. Борг → жорстка економія → бунти.
6. **Політика.** Відносини (-100…100) дрейфують; війни ведуться за співвідношенням сил, облоги забирають міста; мир із контрибуцією; найманці й ордени.
7. **Події.** 35 типів: природа, епідемії (поширюються торговими шляхами), економіка, політика, магія. Таблиця у `lore_data.py`.
8. **Похід на Кірос.** Сценарій із фазами: збір → перехід → кампанія → результат (залежить від постачання кораблів, зброї, консервів).

**Монети:** 1 од. = 1 зм = 100 см = 10 000 мм (курс сховища [[Ціна]]).
**Керування:** `python -m feria_sim run --months 1 --report`, `fire`, `declare`, `set`, `city`, `price`, `retail`, `route`, `quests`, `undo`.
"""


def write_session_prep(sim, vault, hdr):
    w = sim.w
    cur_t = sim.tick_index()
    y0 = w.get("meta", {}).get("start_year", LD.START_YEAR)
    recent = [r for r in w["journal"] if ((r["y"] - y0) * 12 + r["m"] - 1) >= cur_t - 3][-25:][::-1]
    L = [hdr, f"# Підготовка до наступної сесії ({E.date_str(w)})\n",
         "Швидке зведення для Майстра гри: останні події, готові квестові гачки та роздрібні D&D-ціни у найбільших містах.\n",
         "## Події за останні 3 місяці\n"]
    if recent:
        for r in recent:
            L.append(f"- *{LD.MONTHS_UK[r['m']-1]} {r['y']}* (`{r['kind']}`) — {r['text']}")
    else:
        L.append("- За останні місяці великих змін не зафіксовано.")

    L.append("\n## Квестові гачки та чутки для партії\n")
    hooks = DT.generate_quest_hooks(sim, limit=10)
    for h in hooks:
        L.append(f"- **[{h['category']}] {h['title']}** (*{h['patron']}*, нагорода: **{h['reward']}**, {h['urgency']}): {h['text']}")

    L.append("\n## Роздрібні D&D-ціни у 6 найбільших містах\n")
    top_cities = sorted(sim.burgs.values(), key=lambda b: -(b["pop"] + b["rural"]))[:6]
    if top_cities:
        pick_ids = ["inn_modest", "rations", "longsword", "chain_mail", "warhorse", "healing_potion"]
        cols = [next(it["name"] for it in DT.RETAIL_CATALOG if it["id"] == pid) for pid in pick_ids]
        L.append("| Місто (Держава) | " + " | ".join(cols) + " |")
        L.append("|---|" + "|".join("---:" for _ in cols) + "|")
        for b in top_cities:
            rt = DT.city_retail_prices(sim, b["id"])
            by_id = {it["id"]: it["coins"] for it in rt["items"]}
            L.append(f"| {b['uk']} ({sim.sname(b['state'])}) | " + " | ".join(by_id[pid] for pid in pick_ids) + " |")

    _w(os.path.join(vault, "Наступна сесія.md"), "\n".join(L) + "\n")
    return 1
