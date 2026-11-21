# -*- coding: utf-8 -*-
"""Текстові звіти та генерація нотаток Obsidian."""
import os
import re
import collections
import math
import tempfile

from . import lore_data as LD
from . import engine as E
from . import politics as PO
from . import dnd_tools as DT

DEFAULT_VAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "DnD1", "D&D1", "Симуляція")

# Обмеження для Journal-імпорту: звіт не має читати нескінченний файл.
MAX_JOURNAL_LINES = 50_000
_UNSAFE_NAME_RE = re.compile(r'[\\/:*?"<>|#^\[\]]')


def fmt_n(x):
    x = float(x)
    if abs(x) >= 1e6:
        return f"{x/1e6:.2f} млн"
    if abs(x) >= 1e3:
        return f"{x/1e3:.1f} тис."
    return f"{x:.0f}"


def safe(name):
    """Ім'я файлу зі світових даних: без шляхів, '.'/'..' та порожніх значень."""
    s = _UNSAFE_NAME_RE.sub("", str(name if name is not None else "")).strip()
    if not s or s in (".", "..") or not s.strip(". "):
        return ""
    return s


def file_name(name, fallback="Без назви"):
    return (safe(name) or fallback) + ".md"


def _num(value, default=0.0):
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError, OverflowError):
        return default


def md_escape(value):
    """Спільне екранування рядків світу для Markdown і YAML."""
    s = "" if value is None else str(value)
    s = s.replace("\\", "\\\\")
    for ch in ("|", "[", "]", "<", ">", "`", "*", "_"):
        s = s.replace(ch, "\\" + ch)
    return (s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")).strip()


def yaml_scalar(value):
    return '"' + md_escape(value).replace('"', '\\"') + '"'


def _bounded_int(value, lo, hi):
    try:
        if isinstance(value, bool):
            return None
        v = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if lo <= v <= hi else None


def month_name(m):
    months = getattr(LD, "MONTHS_UK", []) or []
    try:
        mi = int(m)
    except (TypeError, ValueError, OverflowError):
        return str(m if m is not None else "—")
    if 1 <= mi <= len(months):
        return str(months[mi - 1])
    return str(mi)


def _within(root, path):
    root = os.path.realpath(root)
    try:
        return os.path.commonpath([root, os.path.realpath(path)]) == root
    except (ValueError, OSError):
        return False


def _vault_target(vault, path, used=None):
    root = os.path.abspath(vault)
    target = os.path.abspath(path)
    if not _within(root, target):
        raise ValueError(f"Шлях {path!r} виходить за межі сховища {vault!r}")
    if used is not None:
        key = os.path.normcase(target)
        if key in used:
            base, ext = os.path.splitext(target)
            i = 2
            while os.path.normcase(f"{base}-{i}{ext}") in used:
                i += 1
            target = f"{base}-{i}{ext}"
            print(f"Попередження: дублікат назви {path!r} → {os.path.basename(target)}")
        used.add(os.path.normcase(target))
    return target


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
    a = ", ".join(md_escape(sim.sname(x)) for x in (wr.get("attackers") or []))
    d = ", ".join(md_escape(sim.sname(x)) for x in (wr.get("defenders") or []))
    try:
        score = float(wr.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    since = f"{month_name(wr.get('start_month'))[:3]} {wr.get('start_year', '—')}"
    return (f"{md_escape(wr.get('name', '—'))}: [{a}] ↔ [{d}] з {since}, рахунок {score:+.0f} "
            f"(+ на користь агресора), захоплено міст: {len(wr.get('captured') or [])}")


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
        base = max(float(sim.goods[g]["value"]), 1e-9)
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
    geo = getattr(sim, "geography", None) or {}
    reg = (geo.get("regions") or {}).get(pid) or {}
    reg_specialties = ", ".join(LD.good_uk(g, sim.goods) for g in (reg.get("specialties") or [])
                                if g in sim.goods)
    center_geo = (geo.get("market_geo") or {}).get(sim.burgs.get(pr.get("burg"), {}).get("market")) or {}
    geo_line = f"Географія: {reg.get('band', '—')}" + (f", біом {reg['biome']}" if reg.get("biome") is not None else "")
    if reg.get("coast"):
        geo_line += ", узбережжя"
    if reg.get("river"):
        geo_line += ", річка"
    if center_geo.get("lat") is not None:
        geo_line += f"; широта {center_geo['lat']}°"
    pop_tot = sum(b["pop"] + b["rural"] for b in p_burgs)
    status = f"Окупована ({sim.sname(occ)})" if occ else (f"В облозі ({pr.get('siege', 0):.0f}%)" if pr.get("siege", 0) > 0 else ("Корінна земля" if core == sid else f"Анексована (корінна: {sim.sname(core)})"))
    lines = [
        f"{pr['uk']} ({pr['name']}) — {sim.sname(sid)} [{status}]",
        f"Адмін. центр: {sim.bname(pr.get('burg'))}; населення провінції: {fmt_n(pop_tot)} ({len(p_burgs)} міст)",
        f"Намісник: {gov.get('name', '—')}" + (f", {gov['age']} р." if gov.get("age") else "") + f"; риси: {traits}; лояльність: {gov.get('loyalty', 70):.0f}%",
        f"Герб: {pr.get('blazon', '—')}",
        f"Економічний профіль: {pr.get('specialty', '—')}",
        geo_line,
        f"Регіональні товари: {reg_specialties or '—'}",
        f"Лор: {pr.get('lore', '—')}",
        "Міста провінції: " + ", ".join(f"{b['uk']} ({fmt_n(b['pop'] + b['rural'])})" for b in p_burgs[:10]),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Obsidian
# ---------------------------------------------------------------------------
HDR = "---\ntags: [симуляція, авто]\nоновлено: \"{d}\"\n---\n> [!warning] Файл генерується автоматично (`python -m feria_sim report`). Ручні правки буде перезаписано.\n\n"


def _w(path, text, vault=None, used=None):
    """Атомарний запис із перевіркою, що файл лишається всередині vault."""
    target = _vault_target(vault, path, used) if vault is not None else os.path.abspath(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".md", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def write_all(sim, vault=None):
    if not vault:
        if sim.w.get("meta", {}).get("is_feria", True):
            vault = DEFAULT_VAULT
        else:
            vault = os.path.join(DEFAULT_VAULT, safe(sim.w.get("meta", {}).get("world_name", "Світ")))
    d = E.date_str(sim.w)
    hdr = HDR.format(d=d)
    used = set()
    n = 0
    n += write_dashboard(sim, vault, hdr, used=used)
    n += write_states(sim, vault, hdr, used=used)
    n += write_markets(sim, vault, hdr, used=used)
    n += write_goods(sim, vault, hdr, used=used)
    n += write_journal(sim, vault, hdr, used=used)
    n += write_misc(sim, vault, hdr, used=used)
    n += write_session_prep(sim, vault, hdr, used=used)
    print(f"Нотатки Obsidian оновлено: {n} файлів → {vault}")


def write_dashboard(sim, vault, hdr, used=None):
    w = sim.w
    tot_pop = sum(st.get("pop", 0) for st in sim.states.values())
    tot_gdp = sum(st.get("gdp", 0) for st in sim.states.values())
    L = [hdr, f"# Дашборд симуляції Ферії\n\n**Дата:** {md_escape(E.date_str(w))}  \n**Населення світу:** {fmt_n(tot_pop)}  \n"
         f"**ВВП за місяць:** {fmt_n(tot_gdp)} од. (1 од. = {md_escape(LD.fmt_coins(1))})  \n**Індекс цін на їжу:** {sim.price_index('food'):.2f} (1.00 = база)  \n"
         f"**Активних війн:** {len(w.get('wars') or [])}  \n\nНавігація: [[Наступна сесія]] · [[Війни]] · [[Товари]] · [[Квести]] · [[Маршрути та небезпека]] · [[Персонажі та фракції]] · [[Гільдії та найманці]] · [[Похід на Кірос]] · [[Правила симуляції]]\n"]
    L.append("\n## Держави (за ВВП)\n\n| Держава | Континент | Населення | ВВП/міс | Казна | Стабільність | Армія (сила) | Годування |\n|---|---|---:|---:|---:|---:|---:|---:|")
    for sid, st in sorted(sim.states.items(), key=lambda kv: -_num(kv[1].get("gdp"), 0.0)):
        s = state_summary(sim, sid)
        uk = md_escape(st.get("uk", "—"))
        slink = safe(st.get("uk")) or "Без назви"
        L.append(f"| [[Держави/{slink}\\|{uk}]] | {md_escape(st.get('continent'))} | {fmt_n(s['pop'])} | "
                 f"{fmt_n(s['gdp'])} | {fmt_n(s['treasury'])} | {s['stab']:.0f} | {fmt_n(s['power'])} | "
                 f"{_num(st.get('food_sat'))*100:.0f}% |")
    L.append("\n## Війни\n")
    L.append("\n".join("- " + wars_line(sim, wr) for wr in (w.get("wars") or []) if isinstance(wr, dict)) or "Мир.")
    L.append("\n## Активні події\n")
    ev = sorted((e for e in (w.get("active_events") or []) if isinstance(e, dict)),
                key=lambda e: -_num(e.get("sev"), 1.0))[:25]
    y0 = _num((w.get("meta") or {}).get("start_year", LD.START_YEAR), LD.START_YEAR)
    lines = []
    for e in ev:
        until = _num(e.get("until"), 0.0)
        lines.append(f"- **{md_escape(e.get('title'))}** ({md_escape(e.get('target'))}, ступінь {_num(e.get('sev'), 1.0):.0f}, "
                     f"до {int(until) // 12 + int(y0)} р.): {md_escape(e.get('text'))}")
    L.append("\n".join(lines) or "—")
    L.append("\n## Останні важливі події\n")
    for r in [r for r in (w.get("journal") or []) if isinstance(r, dict) and _num(r.get("sev"), 1.0) >= 2][-30:][::-1]:
        L.append(f"- *{month_name(r.get('m'))} {md_escape(r.get('y'))}* — {md_escape(r.get('text'))}")
    _w(os.path.join(vault, "Дашборд.md"), "\n".join(L) + "\n", vault=vault, used=used)
    return 1


def write_states(sim, vault, hdr, used=None):
    n = 0
    states_dir = os.path.join(vault, "Держави")
    for sid, st in sim.states.items():
        burgs_list = sim.state_burgs.get(sid, [])
        if not burgs_list:
            continue
        fname = file_name(st.get("uk"))
        s = state_summary(sim, sid)
        r = st.get("ruler") or {}
        fm = (f"---\ntags: [симуляція, авто, держава]\nоновлено: {yaml_scalar(E.date_str(sim.w))}\n"
              f"континент: {yaml_scalar(st.get('continent'))}\n"
              f"населення: {int(_num(s['pop']))}\nввп_міс: {_num(s['gdp']):.1f}\nказна: {_num(s['treasury']):.1f}\n"
              f"стабільність: {_num(s['stab']):.1f}\nсила_армії: {_num(s['power']):.1f}\n"
              f"війни: {len(PO.in_war(sim, sid))}\n---\n")
        uk = md_escape(st.get("uk", "—"))
        lore = md_escape(st.get("lore"))
        L = [fm, "> [!warning] Файл генерується автоматично.\n", f"# {uk}\n",
             f"*{md_escape(st.get('full_name'))}* · {md_escape(st.get('continent'))} · [[Світ]]\n",
             lore + "\n" if lore else ""]
        traits = ", ".join(md_escape((LD.RULER_TRAITS.get(t) or {}).get("label", t))
                           for t in (r.get("traits") or []))
        age = r.get("age")
        L.append(f"- **Правитель:** {md_escape(r.get('name', '—'))}" + (f" ({_num(age):.0f} р.)" if age else "") +
                 f" — {traits}")
        L.append(f"- **Форма правління:** {md_escape(st.get('gov_text'))}\n"
                 f"- **Культура / релігія:** {md_escape(st.get('culture_name'))} / {md_escape(st.get('religion_name'))}\n"
                 f"- **Валюта:** {md_escape(st.get('coins'))}")
        L.append(f"- **Населення:** {fmt_n(s['pop'])} · **міст:** {len(burgs_list)} · "
                 f"**столиця:** {md_escape(sim.bname(st.get('capital')))}")
        L.append(f"- **Економіка:** ВВП/міс {fmt_n(s['gdp'])} од.; казна {fmt_n(s['treasury'])} "
                 f"({md_escape(LD.fmt_coins(s['treasury']))}); борг {fmt_n(s['debt'])}")
        ib = st.get("income_breakdown") or {}
        if isinstance(ib, dict) and ib:
            L.append("- **Бюджет/міс:** " + ", ".join(f"{md_escape(k)} {_num(v):,.0f}" for k, v in ib.items()))
        L.append(f"- **Стабільність:** {_num(st.get('stability')):.0f} · легітимність {_num(st.get('legitimacy')):.0f} · "
                 f"виснаження війною {_num(st.get('war_exhaustion')):.0f} · їжа {_num(st.get('food_sat'))*100:.0f}%")
        army = st.get("army") or {}
        if not isinstance(army, dict):
            army = {}
        L.append("- **Армія:** " + ", ".join(f"{md_escape(u)} {_num(c):.0f}" for u, c in army.items()) +
                 f" (сила {fmt_n(s['power'])}, готовність {_num(st.get('readiness')):.2f})")
        mercs = st.get("mercs") or []
        if isinstance(mercs, list) and mercs:
            L.append("- **Найманці:** " + ", ".join(md_escape(m.get("name", "—")) for m in mercs if isinstance(m, dict)))
        ws = PO.in_war(sim, sid)
        L.append("\n## Війни\n" + ("\n".join("- " + wars_line(sim, wr) for wr in ws if isinstance(wr, dict)) or "Мир."))
        low, high = top_relations(sim, sid, 5)
        L.append("\n## Відносини\n\n**Найгірші:** " +
                 ", ".join(f"{md_escape(sim.sname(o))} ({_num(sc):+.0f})" for sc, o in low) +
                 "\n\n**Найкращі:** " +
                 ", ".join(f"{md_escape(sim.sname(o))} ({_num(sc):+.0f})" for sc, o in high))
        bl = sorted(burgs_list, key=lambda b: -_num(sim.burgs[b].get("pop")))[:12]
        L.append("\n## Найбільші міста\n\n| Місто | Населення | Ринок | Особливості |\n|---|---:|---|---|")
        for b in bl:
            bb = sim.burgs[b]
            mk = sim.markets.get(bb.get("market")) or {}
            mk_name = md_escape(mk.get("uk", "—"))
            L.append(f"| {md_escape(bb.get('uk'))} | {fmt_n(_num(bb.get('pop')) + _num(bb.get('rural')))} | "
                     f"[[Ринки/{safe(mk.get('uk')) or 'Без назви'}\\|{mk_name}]] | "
                     f"{'столиця ' if bb.get('capital') else ''}{'порт ' if bb.get('port') else ''}"
                     f"{'мури ' if bb.get('walls') else ''}{'храм' if bb.get('temple') else ''} |")
        pids = sim.state_provinces.get(sid, [])
        if pids:
            L.append("\n## Провінції та намісники\n\n| Провінція | Центр | Намісник | Лояльність | Спеціалізація | Статус |\n|---|---|---|---:|---|---|")
            for pid in sorted(pids, key=lambda x: -sum(_num(sim.burgs[b].get("pop")) + _num(sim.burgs[b].get("rural"))
                                                       for b in (sim.provinces.get(x) or {}).get("burgs", []) if b in sim.burgs))[:25]:
                pr = sim.provinces.get(pid) or {}
                gov = pr.get("governor") or {}
                occ = pr.get("occupied_by")
                siege = _num(pr.get("siege"))
                st_str = (f"Окупована ({md_escape(sim.sname(occ))})" if occ else
                          (f"Облога {siege:.0f}%" if siege > 0 else
                           ("Корінна" if pr.get("core_state", sid) == sid else
                            f"Анексована ({md_escape(sim.sname(pr.get('core_state')))})")))
                L.append(f"| {md_escape(pr.get('uk'))} | {md_escape(sim.bname(pr.get('burg')))} | "
                         f"{md_escape(gov.get('name', '—'))} | {_num(gov.get('loyalty'), 70):.0f}% | "
                         f"{md_escape(pr.get('specialty', '—'))} | {st_str} |")
        L.append(f"\n## Ціни в державі\n\nІндекс цін на їжу: **{sim.price_index('food', sid):.2f}**, "
                 f"побут: {sim.price_index('utilities', sid):.2f}, розкіш: {sim.price_index('luxury', sid):.2f} "
                 f"(множник до роздрібних цін з [[Ціна]]).")
        cap = st.get("capital")
        cap_id = cap if isinstance(cap, int) and cap in sim.burgs else (bl[0] if bl else None)
        if cap_id in sim.burgs:
            try:
                retail = DT.city_retail_prices(sim, cap_id)
                L.append(f"\n### Роздрібні D&D-ціни ({md_escape(retail['burg_uk'])})\n\n"
                         f"| Позиція | Ціна | % бази | Наявність |\n|---|---:|---:|---|")
                for it in retail["items"][:12]:
                    L.append(f"| {md_escape(it.get('name'))} | {md_escape(it.get('coins'))} | "
                             f"{it.get('pct')}% | {md_escape(it.get('status'))} |")
            except Exception:
                pass
        ev = [r for r in (sim.w.get("journal") or []) if isinstance(r, dict) and
              (sid in (r.get("states") or []) or r.get("state") == sid)][-12:][::-1]
        L.append("\n## Хроніка\n" + "\n".join(
            f"- *{month_name(r.get('m'))} {md_escape(r.get('y'))}* — {md_escape(r.get('text'))}" for r in ev))
        _w(os.path.join(states_dir, fname), "\n".join(L) + "\n", vault=vault, used=used)
        n += 1

    # Не чіпаємо чужі нотатки: генератор не повинен архівувати користувацькі файли.
    return n


def write_markets(sim, vault, hdr, used=None):
    n = 0
    for mid, m in sim.markets.items():
        sid = sim.market_state.get(mid)
        sname = md_escape(sim.sname(sid))
        L = [hdr, f"# Ринок {md_escape(m.get('uk'))}\n",
             f"Держава: [[Держави/{safe(sim.sname(sid)) or 'Без назви'}\\|{sname}]] · "
             f"міст на ринку: {len(m.get('burgs') or [])} · торгових шляхів: {len(m.get('edges') or [])}\n"]
        routes = []
        for ei in (m.get("edges") or []):
            edges = sim.edges
            if isinstance(edges, dict):
                e = edges.get(ei)
            elif isinstance(edges, (list, tuple)) and 0 <= int(ei) < len(edges):
                e = edges[int(ei)]
            else:
                e = None
            if not isinstance(e, dict):
                continue
            o = e.get("b") if e.get("a") == mid else e.get("a")
            other = sim.markets.get(o) or {}
            routes.append(f"{md_escape(other.get('uk', '—'))} ({_num(e.get('dist')):.0f} км, "
                          f"{'море' if e.get('sea') else 'суша'}, потік {_num(e.get('flow')):.0f})")
        L.append("**Маршрути:** " + "; ".join(routes) + "\n")
        L.append("| Товар | Ціна | Монети | % бази | Запас |\n|---|---:|---|---:|---:|")
        for g in sorted(m.get("price") or {}, key=lambda g: -_num((sim.goods.get(g) or {}).get("value"))):
            p = _num(m["price"][g])
            base = max(_num((sim.goods.get(g) or {}).get("value")), 1e-9)
            unit = md_escape((sim.goods.get(g) or {}).get("unit", "—"))
            L.append(f"| {md_escape(LD.good_uk(g, sim.goods))} ({unit}) | {p:.2f} | {md_escape(LD.fmt_coins(p))} | "
                     f"{p/base*100:.0f}% | {_num((m.get('stock') or {}).get(g)):.0f} |")
        _w(os.path.join(vault, "Ринки", file_name(m.get("uk"))), "\n".join(L) + "\n", vault=vault, used=used)
        n += 1
    return n


def write_goods(sim, vault, hdr, used=None):
    L = [hdr, "# Товари: світові ціни\n\nОдиниця вартості = 1 віз зерна ≈ 1 зм (оптові лоти, не роздріб).\n",
         "| Товар | Одиниця | База | Мін | Середня | Макс | Де дешево | Де дорого |\n|---|---|---:|---:|---:|---:|---|---|"]
    markets = [m for m in sim.markets.values() if isinstance(m, dict)]
    for g in sorted(sim.goods):
        rows = sorted((_num((m.get("price") or {}).get(g)), m.get("uk", "—")) for m in markets)
        if not rows:
            continue
        avg = sum(p for p, _ in rows) / len(rows)
        good = sim.goods.get(g) or {}
        L.append(f"| {md_escape(LD.good_uk(g, sim.goods))} | {md_escape(good.get('unit', '—'))} | "
                 f"{md_escape(good.get('value', '—'))} | {rows[0][0]:.2f} | {avg:.2f} | {rows[-1][0]:.2f} | "
                 f"{md_escape(rows[0][1])} | {md_escape(rows[-1][1])} |")
    _w(os.path.join(vault, "Товари.md"), "\n".join(L) + "\n", vault=vault, used=used)
    return 1


def write_journal(sim, vault, hdr, used=None):
    """Експорт журналу: лише коректні роки/місяці, обмежений обсяг, без чужих шляхів."""
    import json
    default_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "save", "journal.jsonl")
    rows = [r for r in (sim.w.get("journal") or []) if isinstance(r, dict)][:MAX_JOURNAL_LINES]
    if not rows:
        path = getattr(sim, "journal_path", None)
        meta = sim.w.get("meta") or {}
        meta_path = meta.get("journal_file")
        # Шлях із метаданих світу не є довіреним: приймаємо лише сусідній файл.
        if not path and meta_path and _within(os.path.dirname(default_path), str(meta_path)):
            path = meta_path
        path = path or default_path
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        if len(rows) >= MAX_JOURNAL_LINES:
                            break
                        if not line.strip():
                            continue
                        try:
                            rec = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(rec, dict):
                            rows.append(rec)
        except (OSError, UnicodeError):
            pass
    by_year = collections.defaultdict(list)
    for r in rows:
        y = _bounded_int(r.get("y"), 1, 9999)
        m = _bounded_int(r.get("m"), 1, 12)
        if y is None or m is None:
            continue
        by_year[y].append(dict(r, y=y, m=m))
    era = md_escape((sim.w.get("meta") or {}).get("era", LD.ERA_SHORT))
    journal_dir = os.path.join(vault, "Журнал")
    written = 0
    for y in sorted(by_year):
        rs = by_year[y]
        # y вже int, але перевірка контейнера лишається обов'язковою.
        target = os.path.join(journal_dir, f"{int(y)}.md")
        if not _within(journal_dir, target):
            continue
        L = [hdr, f"# Журнал {y} {era}\n"]
        cur = None
        for r in rs:
            if r["m"] != cur:
                cur = r["m"]
                L.append(f"\n### {month_name(cur)}\n")
            L.append(f"- `{md_escape(r.get('kind'))}` {md_escape(r.get('text'))}")
        _w(target, "\n".join(L) + "\n", vault=vault, used=used)
        written += 1
    return written


def write_misc(sim, vault, hdr, used=None):
    w = sim.w
    # війни
    L = [hdr, "# Війни\n\n## Активні\n"]
    L.append("\n".join("- " + wars_line(sim, wr) for wr in (w.get("wars") or []) if isinstance(wr, dict)) or "Мир.")
    L.append("\n## Завершені\n")
    for h in (w.get("war_history") or [])[-60:][::-1]:
        if not isinstance(h, dict):
            continue
        L.append(f"- {md_escape(h.get('name'))} ({md_escape(h.get('start'))}–{md_escape(h.get('end') or '…')}): "
                 f"{md_escape(sim.sname(h.get('attacker')))} проти {md_escape(sim.sname(h.get('defender')))}" +
                 (f" — {md_escape(h.get('result'))}" if h.get("result") else ""))
    _w(os.path.join(vault, "Війни.md"), "\n".join(L) + "\n", vault=vault, used=used)
    # гільдії
    L = [hdr, "# Гільдії та найманці\n\n## Гільдії\n\n| Гільдія | Тип | Місто | Багатство | Монополії |\n|---|---|---|---:|---|"]
    for g in (w.get("guilds") or []):
        if not isinstance(g, dict):
            continue
        goods = ", ".join(md_escape(LD.good_uk(x, sim.goods)) for x in (g.get("goods") or []))
        L.append(f"| {md_escape(g.get('name'))} | {md_escape(g.get('kind'))} | "
                 f"{md_escape(sim.bname(g.get('burg')))} ({md_escape(sim.sname(g.get('state')))}) | "
                 f"{fmt_n(_num(g.get('wealth')))} | {goods} |")
    L.append("\n## Найманці\n")
    for m in (w.get("mercs") or []):
        if not isinstance(m, dict):
            continue
        emp = (md_escape(sim.sname(m.get("employer")))
               if m.get("employer") and sim.tick_index() < _num(m.get("contract_end")) else "вільні")
        home = md_escape(sim.sname(m.get("home"))) if m.get("home") else "—"
        L.append(f"- **{md_escape(m.get('name'))}** — {_num(m.get('size')):.0f} бійців ({md_escape(m.get('unit'))}); "
                 f"база: {home}; зараз: {emp}")
    L.append("\n## Ордени\n")
    for o in (w.get("orders") or []):
        if not isinstance(o, dict):
            continue
        owner = md_escape(sim.sname(o.get("state"))) if o.get("state") else "наддержавний"
        L.append(f"- **{md_escape(o.get('name'))}** — {_num(o.get('strength')):.0f} ({md_escape(o.get('unit'))}), держава: {owner}")
    _w(os.path.join(vault, "Гільдії та найманці.md"), "\n".join(L) + "\n", vault=vault, used=used)
    # похід
    cr = w.get("crusade") or {}
    L = [hdr, f"# {md_escape(cr.get('name'))}\n\n**Фаза:** {md_escape(cr.get('phase'))} · "
              f"готовність постачання {_num(cr.get('progress'))*100:.0f}% · "
              f"результат: {md_escape(cr.get('result') or 'невідомий')}\n",
         "**Спонсори:** " + ", ".join(md_escape(sim.sname(s)) for s in (cr.get("sponsors") or []) if s in sim.states) + "\n",
         "Дивись [[Четвертий Похід на Кірос]] та [[Хронологія Епох і Походи на Кірос]]."]
    L.append("\n## Журнал Походу\n")
    for r in [r for r in (w.get("journal") or []) if isinstance(r, dict) and r.get("kind") == "crusade"]:
        L.append(f"- *{month_name(r.get('m'))} {md_escape(r.get('y'))}* — {md_escape(r.get('text'))}")
    _w(os.path.join(vault, "Похід на Кірос.md"), "\n".join(L) + "\n", vault=vault, used=used)
    n = (3 + write_quests(sim, vault, hdr, used=used) +
         write_route_notes(sim, vault, hdr, used=used) +
         write_npc_notes(sim, vault, hdr, used=used))
    _w(os.path.join(vault, "Правила симуляції.md"), rules_text(sim, hdr), vault=vault, used=used)
    return n + 1


def write_quests(sim, vault, hdr, used=None):
    # Експорт не змінює стан світу: прострочення обробляє ГМ через dnd_tools.
    board = sim.w.get("quests") or {}
    if not isinstance(board, dict):
        board = {}
    L = [hdr, "# Квести та доручення\n\nАктивні справи й чутки, зібрані з подій, війн, епідемій і дефіцитів.\n"]
    L.append("## Прийняті\n")
    active = [q for q in (board.get("active") or []) if isinstance(q, dict)]
    L.append("\n".join(
        f"- **{md_escape(q.get('title'))}** ({md_escape(q.get('patron', '—'))}, нагорода "
        f"{md_escape(q.get('reward', '—'))}, термін до tick {md_escape(q.get('due_tick', '—'))}): "
        f"{md_escape(q.get('text', ''))}" for q in active) or "- Немає активних доручень.")
    L.append("\n## Дошка оголошень\n")
    try:
        hooks = DT.generate_quest_hooks(sim, limit=12)
    except Exception:
        hooks = []
    for h in hooks:
        if not isinstance(h, dict):
            continue
        L.append(f"- **[{md_escape(h.get('category'))}] {md_escape(h.get('title'))}** — "
                 f"{md_escape(h.get('patron', '—'))}; нагорода {md_escape(h.get('reward', '—'))}. "
                 f"{md_escape(h.get('text', ''))}")
    L.append("\n## Завершені\n")
    for q in [q for q in (board.get("completed") or []) if isinstance(q, dict)][-12:][::-1]:
        L.append(f"- {md_escape(q.get('title'))} — {md_escape(q.get('status'))}, "
                 f"виплачено {_num(q.get('paid_zm')):.0f} зм")
    _w(os.path.join(vault, "Квести.md"), "\n".join(L) + "\n", vault=vault, used=used)
    return 1


def write_route_notes(sim, vault, hdr, used=None):
    top = sorted(sim.burgs.values(), key=lambda b: -(_num(b.get("pop")) + _num(b.get("rural"))))[:8]
    L = [hdr, "# Маршрути та небезпека\n\nОцінка шляхів між найбільшими містами для планування D&D-сесії.\n"]
    highways = [r for r in (sim.w.get("trade_routes") or []) if isinstance(r, dict)]
    if highways:
        L.append("## Готові караванні магістралі\n")
        L.append("| Маршрут | Ринків | Відстань | Море | Провідність |")
        L.append("|---|---|---:|---|---:|")
        geo = getattr(sim, "geography", None) or {}
        mgeo = geo.get("market_geo") or {}
        regions = geo.get("regions") or {}
        spec_lines = []
        for r in highways[:32]:
            mids = r.get("markets") or []
            names = [sim.markets.get(m, {}).get("uk", str(m)) for m in mids]
            L.append(f"| {md_escape(r.get('name', '—'))} | {len(names)} | {_num(r.get('dist')):.0f} | "
                     f"{'так' if r.get('sea') else 'ні'} | {_num(r.get('cap')):.1f} |")
            found = set()
            for mid in mids:
                region = regions.get((mgeo.get(mid) or {}).get("region")) or {}
                found.update(g for g in (region.get("specialties") or []) if g in sim.goods)
            if found:
                spec_lines.append(f"- **{md_escape(r.get('name', '—'))}**: " +
                                  md_escape(", ".join(LD.good_uk(g, sim.goods) for g in sorted(found))))
        L.append("")
        if spec_lines:
            L.append("### Спеціалізації вздовж магістралей\n")
            L.extend(spec_lines)
            L.append("")
    L.append("| Звідки | Куди | Режим | Км | Днів | Вартість | Небезпека | Зустрічі |")
    L.append("|---|---|---|---:|---:|---:|---|---|")
    for a in top:
        for b in top:
            if a.get("id", 0) >= b.get("id", 0):
                continue
            try:
                rt = DT.travel_route(sim, a["id"], b["id"], mode="wagon")
            except Exception:
                continue
            L.append(f"| {md_escape(a.get('uk'))} | {md_escape(b.get('uk'))} | {md_escape(rt.get('mode_name'))} | "
                     f"{rt.get('total_km')} | {rt.get('total_days')} | {md_escape(rt.get('cost_coins'))} | "
                     f"{rt.get('danger_score')} ({md_escape(rt.get('danger_level'))}) | "
                     f"{len(rt.get('encounters') or [])} |")
    _w(os.path.join(vault, "Маршрути та небезпека.md"), "\n".join(L) + "\n", vault=vault, used=used)
    return 1


def write_npc_notes(sim, vault, hdr, used=None):
    L = [hdr, "# Персонажі та фракції\n\nГотові заготовки для швидкого запуску сцени.\n"]
    for _ in range(6):
        try:
            npc = DT.generate_npc(sim)
        except Exception:
            continue
        if not isinstance(npc, dict):
            continue
        L.append(f"\n## {md_escape(npc.get('name'))} — {md_escape(npc.get('role'))}\n")
        traits = ", ".join(md_escape(t) for t in (npc.get("traits") or []))
        L.append(f"- **Фракція:** {md_escape(npc.get('faction'))}\n- **Місце:** {md_escape(npc.get('location'))}\n"
                 f"- **Риси:** {traits}\n- **Привід:** {md_escape(npc.get('hook'))}")
    L.append("\n## Гільдії й держустанови\n")
    for g in (sim.w.get("guilds") or []):
        if isinstance(g, dict):
            L.append(f"- {md_escape(g.get('name'))} ({md_escape(g.get('kind', '—'))}), "
                     f"база: {md_escape(sim.bname(g.get('burg')))}")
    _w(os.path.join(vault, "Персонажі та фракції.md"), "\n".join(L) + "\n", vault=vault, used=used)
    return 1


def rules_text(sim, hdr):
    cfg = sim.w.get("config", {}) or {}
    goods_n = len(sim.goods)
    event_n = len(getattr(LD, "EVENT_TABLE", {}))
    recipes_n = sum(len(g.get("recipes", [])) for g in sim.goods.values())
    return f"""{hdr}
# Правила симуляції економіки та подій

Крок = 1 місяць. Світ: {len(sim.states)} держав, {len(sim.burgs)} міст, {len(sim.markets)} ринків, {goods_n} товарів, {recipes_n} варіантів рецептів.

1. **Виробництво.** Сировина за біомом/родовищем плюс ремесло міст. Рецепти обираються щомісяця за поточними цінами; збиткові цехи зупиняються. Сезонність за широтою.
2. **Торгівля.** Частина вантажу йде караванами готовими магістралями карти (`trade_routes`): між столицями й найбільшими ринками, з транзитом і митом на кожній ділянці. Попарна торгівля лишається як «остання миля» й послаблена на маршрутних ребрах. Торгівля обмежена капіталом ринку; один товар не можна перепродати двічі в тому ж місяці.
3. **Споживання.** Їжа, побут, будівництво, розкіш. Попит помірно реагує на ціну; нестача впливає на смертність і стабільність.
4. **Ціни.** `ціна = база × (цільовий запас / запас)^0.5`, межі 0.3×…6× бази; згладжування 35%/міс.
5. **Держави.** Податки, утримання армії, закупівля спорядження. Борг викликає жорстку економію; позики гільдій реально переказуються в казну.
6. **Політика.** Відносини (-100…100), війни, облоги, анексії з поступовою асиміляцією; технології обмежені й повільно повертаються до бази.
7. **Події.** {event_n} типів; частота масштабується розміром світу, кількість на місяць обмежена. Деякі події мають варіанти рішень для ГМ.
8. **D&D інструменти.** Роздрібні ціни залежать від ринку, податків, війни й Іржі; маршрути мають реальну надбавку за небезпеку; квести можна приймати й закривати.
9. **Географія й спецтовари.** Біом, широтний пояс, порт/річка й провінція з .map визначають регіональні specialty. Їх виробляють конверсією частини базової сировини зі збереженням вартості; далі вони беруть участь у торгівлі, цінах і караванах на загальних підставах.

**Налаштування:** event_rate={md_escape(cfg.get('event_rate', 1))}, war_rate={md_escape(cfg.get('war_rate', 1))}, carry_cap={md_escape(cfg.get('carry_cap', 1.65))}, tech_cap={md_escape(cfg.get('tech_cap', 3.0))}.
**Монети:** 1 од. = 1 зм = 100 см = 10 000 мм.
**Керування:** `python -m feria_sim run --months 1 --report`, `fire`, `declare`, `peace`, `set`, `city`, `price`, `retail`, `route`, `quests`, `npc`, `undo`.
"""


def write_session_prep(sim, vault, hdr, used=None):
    w = sim.w
    cur_t = sim.tick_index()
    y0 = _num((w.get("meta") or {}).get("start_year", LD.START_YEAR), LD.START_YEAR)
    recent = []
    for r in (w.get("journal") or []):
        if not isinstance(r, dict):
            continue
        try:
            if ((_num(r.get("y"), 0.0) - y0) * 12 + _num(r.get("m"), 1.0) - 1) >= cur_t - 3:
                recent.append(r)
        except (TypeError, ValueError):
            continue
    recent = recent[-25:][::-1]
    L = [hdr, f"# Підготовка до наступної сесії ({md_escape(E.date_str(w))})\n",
         "Швидке зведення для Майстра гри: останні події, готові квестові гачки та роздрібні D&D-ціни у найбільших містах.\n",
         "## Події за останні 3 місяці\n"]
    if recent:
        for r in recent:
            L.append(f"- *{month_name(r.get('m'))} {md_escape(r.get('y'))}* "
                     f"(`{md_escape(r.get('kind'))}`) — {md_escape(r.get('text'))}")
    else:
        L.append("- За останні місяці великих змін не зафіксовано.")

    L.append("\n## Квестові гачки та чутки для партії\n")
    try:
        hooks = DT.generate_quest_hooks(sim, limit=10)
    except Exception:
        hooks = []
    for h in hooks:
        if not isinstance(h, dict):
            continue
        L.append(f"- **[{md_escape(h.get('category'))}] {md_escape(h.get('title'))}** "
                 f"(*{md_escape(h.get('patron'))}*, нагорода: **{md_escape(h.get('reward'))}**, "
                 f"{md_escape(h.get('urgency'))}): {md_escape(h.get('text'))}")

    L.append("\n## Роздрібні D&D-ціни у 6 найбільших містах\n")
    top_cities = sorted(sim.burgs.values(), key=lambda b: -(_num(b.get("pop")) + _num(b.get("rural"))))[:6]
    if top_cities:
        pick_ids = ["inn_modest", "rations", "longsword", "chain_mail", "warhorse", "healing_potion"]
        names = {it.get("id"): it.get("name", "—") for it in DT.RETAIL_CATALOG}
        cols = [md_escape(names.get(pid, pid)) for pid in pick_ids]
        L.append("| Місто (Держава) | " + " | ".join(cols) + " |")
        L.append("|---|" + "|".join("---:" for _ in cols) + "|")
        for b in top_cities:
            try:
                rt = DT.city_retail_prices(sim, b["id"])
            except Exception:
                continue
            by_id = {it.get("id"): it.get("coins", "—") for it in rt.get("items", [])}
            L.append(f"| {md_escape(b.get('uk'))} ({md_escape(sim.sname(b.get('state')))}) | " +
                     " | ".join(md_escape(by_id.get(pid, "—")) for pid in pick_ids) + " |")

    _w(os.path.join(vault, "Наступна сесія.md"), "\n".join(L) + "\n", vault=vault, used=used)
    return 1
