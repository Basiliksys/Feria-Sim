# -*- coding: utf-8 -*-
"""Локальний веб-сервер та JSON API для відслідковування й керування симуляцією Ферії."""
import base64
import gzip
import json
import math
import os
import random
import re
import shutil
import socket
import threading
import time
import urllib.parse
import uuid
import webbrowser
import zlib
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
LEGACY_MAP = os.path.join(os.path.expanduser("~"), "Downloads", "Feria 2026-09-21-12-26.map")

# Поля, які можна правити з панелі/CLI. Дозволені лише числа й правдиві/хибні значення.
# Дotted-ключі (per_capita.*) зберігаються у вкладених словниках config.
CONFIG_FIELDS = [
    ("craft_scale", "Масштаб ремесла", 0.1, 5.0, 0.05),
    ("transport_rate", "Інтенсивність торгівлі", 0.0, 0.1, 0.001),
    ("birth", "Народжуваність", 0.0, 0.02, 0.0001),
    ("death", "Смертність", 0.0, 0.02, 0.0001),
    ("poll_k", "Подушний коефіцієнт", 0.0, 5.0, 0.05),
    ("mil_k", "Військовий попит", 0.0, 5.0, 0.05),
    ("mil_goods_per_head", "Військові товари на воїна", 0.0, 0.02, 0.0001),
    ("admin_share", "Частка адміністрації", 0.0, 1.0, 0.01),
    ("event_rate", "Частота подій", 0.0, 5.0, 0.05),
    ("war_rate", "Частота воєн", 0.0, 5.0, 0.05),
    ("price_elasticity", "Еластичність цін", 0.0, 1.0, 0.01),
    ("carry_cap", "Межа переносу запасів", 1.0, 4.0, 0.05),
    ("tech_cap", "Межа технологій", 1.0, 10.0, 0.1),
    ("tech_decay", "Занепад технологій", 0.0, 0.05, 0.001),
    ("max_events_per_month", "Макс. подій на місяць", 1, 12, 1),
    ("neighbor_drift", "Дрейф до сусідів", -0.2, 0.2, 0.01),
    ("army_recovery_rate", "Відновлення армії", 0.0, 0.3, 0.005),
    ("trade_budget_factor", "Бюджет торгівлі", 0.0, 10.0, 0.1),
    ("guild_invest_rate", "Інвестиції гільдій", 0.0, 0.3, 0.005),
    ("per_capita.food", "Душова норма: їжа", 1.0, 40.0, 0.5),
    ("per_capita.utilities", "Душова норма: комунальне", 0.0, 20.0, 0.25),
    ("per_capita.construction", "Душова норма: будівництво", 0.0, 10.0, 0.1),
    ("per_capita.luxury", "Душова норма: розкіш", 0.0, 10.0, 0.1),
]
CONFIG_BOOL_FIELDS = [
    ("event_scale_by_size", "Масштаб подій за розміром"),
    ("demand_elasticity_enabled", "Еластичний попит"),
    ("dynamic_recipes", "Динамічні рецепти"),
    ("capital_constraint", "Обмеження капіталу"),
]
CONFIG_NUMERIC = {k for k, _, _, _, _ in CONFIG_FIELDS}
CONFIG_BOOLS = {k for k, _ in CONFIG_BOOL_FIELDS}
CONFIG_WHITELIST = CONFIG_NUMERIC | CONFIG_BOOLS

# Обмеження для локального HTTP-сервера й імпорту карт.
MAX_BODY_BYTES = 24 * 1024 * 1024
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
MAX_MAP_TEXT_BYTES = 64 * 1024 * 1024
MAX_TEXT_FIELD = 2000
SAFE_SLOT_ID = re.compile(r"^[0-9A-Za-zА-Яа-яІіЇїЄєҐґ_-]{1,120}$")
SAFE_MAP_NAME = re.compile(r"^[0-9A-Za-zА-Яа-яІіЇїЄєҐґ ._()\-]+$")


def _finite(value):
    """Повертає скінченне float або None."""
    if isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def _host_key(host):
    """Нормалізоване ім'я хоста без квадратних дужок IPv6."""
    value = str(host or "").strip().lower()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return value


def _authorities(host, port):
    """Усі прийнятні Host/Origin-авторитети для одного імені хоста."""
    value = _host_key(host)
    if not value:
        return set()
    if ":" not in value:
        return {f"{value}:{port}"}
    # HTTP-клієнти надсилають IPv6-адреси в дужках; лишаємо й стару форму
    # для сумісності з локальними сценаріями.
    return {f"[{value}]:{port}", f"{value}:{port}"}


def _expected_hosts(host, port):
    host = _host_key(host)
    names = {host}
    if host in ("", "0.0.0.0", "::", "127.0.0.1", "::1", "localhost"):
        names |= {"127.0.0.1", "localhost", "::1"}
    hosts = set()
    for name in names:
        hosts |= _authorities(name, port)
    if host in ("0.0.0.0", "::"):
        try:
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                hosts |= _authorities(ip, port)
        except OSError:
            pass
    return hosts


def _write_text_atomic(path, text):
    """Атомарний запис тексту: тимчасовий файл + os.replace, cleanup при помилці."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _write_json_atomic(path, obj):
    """Атомарний JSON-запис із забороною NaN/Infinity."""
    _write_text_atomic(path, json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False))


def list_saved_maps(maps_dir, include_legacy=True):
    """Список доступних карт: змінна оточення, каталог збережених карт, застарілий шлях."""
    out = []
    seen = set()
    env = (os.environ.get("FERIA_MAP") or os.environ.get("FERIA_DEFAULT_MAP") or "").strip()
    candidates = []
    if env:
        candidates.append((env, True))
    if os.path.isdir(maps_dir):
        for fn in sorted(os.listdir(maps_dir)):
            if fn.lower().endswith((".map", ".json", ".gz")):
                candidates.append((os.path.join(maps_dir, fn), False))
    if include_legacy and os.path.exists(LEGACY_MAP):
        candidates.append((LEGACY_MAP, True))
    for path, builtin in candidates:
        full = os.path.realpath(path)
        if full in seen or not os.path.isfile(full):
            continue
        seen.add(full)
        out.append(dict(name=os.path.basename(full), path=full, builtin=builtin))
    return out


def resolve_default_map(maps_dir=None):
    """Файл карти за замовчуванням: FERIA_MAP/FERIA_DEFAULT_MAP → save/maps → legacy."""
    maps = list_saved_maps(maps_dir or "", include_legacy=True)
    return maps[0]["path"] if maps else ""


def _config_get(sim, key, default=None):
    if "." in key:
        root, sub = key.split(".", 1)
        block = sim.cfg(root, {}) or {}
        return block.get(sub, default) if isinstance(block, dict) else default
    return sim.cfg(key, default)


def _coerce_config_value(key, value):
    """Повертає (ok, value). Для whitelist-полів допускаємо лише number/bool."""
    if key not in CONFIG_WHITELIST:
        return False, None
    if key in CONFIG_BOOLS:
        if isinstance(value, bool):
            return True, value
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True, True
        if s in ("0", "false", "no", "off"):
            return True, False
        return False, None
    if isinstance(value, bool):
        return False, None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return False, None
    if num != num or num in (float("inf"), float("-inf")):
        return False, None
    spec = next((s for s in CONFIG_FIELDS if s[0] == key), None)
    if spec:
        lo, hi = spec[2], spec[3]
        if num < lo or num > hi:
            return False, None
        if spec[4] is not None and float(spec[4]).is_integer() and float(num).is_integer():
            num = int(num)
    return True, num


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
        self.sim.journal_path = journal_file
        self.sim.w.setdefault("meta", {})["journal_file"] = journal_file
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
            default_map = resolve_default_map(self.maps_dir)
            if self.sim.w.get("meta", {}).get("is_feria") and default_map:
                cand = default_map
        geo = IM.extract_map_geometry(cand, self.sim.w)
        IM.save_map_geo(geo, self.geo_file)

    def _list_saved_maps(self):
        return list_saved_maps(self.maps_dir, include_legacy=True)

    def _slot_dir(self, slot_id):
        """Перевірений шлях до слота: жорсткий allowlist + realpath-контейнер."""
        if not isinstance(slot_id, str) or not SAFE_SLOT_ID.fullmatch(slot_id):
            return None
        root = os.path.realpath(self.slots_dir)
        candidate = os.path.join(root, slot_id)
        target = os.path.realpath(candidate)
        try:
            if os.path.commonpath([root, target]) != root:
                return None
        except ValueError:
            return None
        if os.path.islink(candidate):
            return None
        return candidate

    def _new_slot_id(self, label, fork=False):
        base = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ_-]+", "_", label or "").strip("_")[:80] or "slot"
        suffix = "fork" if fork else "slot"
        return f"{base}_{suffix}_{time.time_ns():020d}_{uuid.uuid4().hex[:6]}"

    def _rng(self):
        """Генератор симуляції; створюємо зі збереженого seed, якщо ще немає."""
        rng = getattr(self.sim, "rng", None)
        if rng is None:
            rng = random.Random(getattr(self.sim, "seed", 1))
            self.sim.rng = rng
        return rng

    def save(self):
        with self.lock:
            new = self.sim.w.pop("_new_journal", [])
            if new:
                os.makedirs(os.path.dirname(self.journal_file), exist_ok=True)
                with open(self.journal_file, "a", encoding="utf-8") as f:
                    for r in new:
                        f.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")
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
                ratios = []
                for gid, good in sim.goods.items():
                    base = float(good.get("value", 0) or 0)
                    if base > 0:
                        ratios.append(float(m.get("price", {}).get(gid, base)) / base)
                markets_out.append(dict(
                    id=mid, uk=m["uk"], x=cb["x"], y=cb["y"], state=sid, state_uk=sim.sname(sid),
                    burgs=len(m["burgs"]), port=cb["port"],
                    food_idx=round(sim.price_index("food", sid), 2),
                    scarcity=round(max(ratios) if ratios else 1.0, 2),
                ))
            burgs_out = [dict(
                id=b["id"], uk=b["uk"], name=b["name"], x=b["x"], y=b["y"], state=b["state"],
                color=sim.states[b["state"]]["color"], pop=round(b["pop"] + b["rural"]),
                cap=b["capital"], port=b["port"], market=b["market"],
                sat_food=round(float((b.get("sat") or {}).get("food", 1.0)), 3),
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
            events_active = sorted([dict(
                uid=e.get("uid", i + 1), key=e["key"], title=e["title"], target=e["target"],
                sev=e["sev"], months_left=max(0, e["until"] - t), text=e["text"],
            ) for i, e in enumerate(w.get("active_events", []))], key=lambda x: -x["sev"])
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
            provinces_out = []
            for pid, pr in sim.provinces.items():
                cb = sim.burgs.get(pr.get("burg"), {})
                pole = pr.get("pole") or [cb.get("x", 0), cb.get("y", 0)]
                gov = pr.get("governor") or {}
                provinces_out.append(dict(
                    id=pid, uk=pr["uk"], state=pr["state"], state_uk=sim.sname(pr["state"]),
                    core_state=pr.get("core_state", pr["state"]),
                    occupied_by=pr.get("occupied_by"),
                    siege=round(pr.get("siege", 0.0), 1),
                    burg=pr.get("burg"), burg_uk=cb.get("uk", ""),
                    x=pole[0], y=pole[1],
                    color=sim.states.get(pr.get("occupied_by") or pr["state"], {}).get("color", pr.get("color", "#6a8caf")),
                    governor=gov.get("name", "—"),
                    loyalty=round(gov.get("loyalty", 70.0), 1),
                    specialty=pr.get("specialty", ""),
                ))
            undo_count, undo_label = self._undo_info()
            saved_maps = self._list_saved_maps()
            source_file = w["meta"].get("source_file", "")
            map_path = next((m["path"] for m in saved_maps if m["name"] == source_file), "")
            try:
                map_mtime = int(os.path.getmtime(map_path) * 1000) if map_path else 0
            except OSError:
                map_mtime = 0
            return dict(
                date=E.date_str(w), year=w["date"]["year"], month=w["date"]["month"], tick=t,
                world_name=w["meta"].get("world_name", "Ферія"),
                era=w["meta"].get("era", LD.ERA_SHORT),
                start_year=w["meta"].get("start_year", LD.START_YEAR),
                is_feria=w["meta"].get("is_feria", True),
                has_native_economy=w["meta"].get("has_native_economy", True),
                source_file=source_file,
                map_version=f"{source_file}|{map_mtime}",
                map_divider=w["meta"].get("map_divider", w["meta"].get("divider_x", 1150)),
                continents=sorted({x["cont"] for x in states_out if x["cont"]}),
                saved_maps=saved_maps,
                undo_count=undo_count,
                undo_label=undo_label,
                slots=self.list_slots(),
                width=w["meta"]["width"], height=w["meta"]["height"],
                tot_pop=round(sum(x["pop"] for x in states_out)),
                tot_gdp=round(sum(x["gdp"] for x in states_out), 1),
                indices={c: round(sim.price_index(c), 3) for c in LD.CATEGORIES},
                history=w["history"]["world"][-240:],
                history_states=w["history"]["states"][-240:],
                states=states_out, provinces=provinces_out, markets=markets_out, burgs=burgs_out, edges=edges_out,
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
            provs_out = []
            for pid in sim.state_provinces.get(sid, []):
                pr = sim.provinces.get(pid)
                if not pr:
                    continue
                gov = pr.get("governor") or {}
                pp = round(sum(sim.burgs[b]["pop"] + sim.burgs[b]["rural"] for b in pr.get("burgs", []) if b in sim.burgs))
                occ = pr.get("occupied_by")
                provs_out.append(dict(
                    id=pid, uk=pr["uk"], form_uk=pr.get("form_uk", "Провінція"),
                    burg=pr.get("burg"), burg_uk=sim.bname(pr.get("burg")),
                    pop=pp, occupied_by=occ, occupied_uk=sim.sname(occ) if occ else None,
                    siege=round(pr.get("siege", 0.0), 1),
                    governor=gov.get("name", "—"),
                    gov_traits=[LD.GOVERNOR_TRAITS.get(t, {}).get("label", t) for t in gov.get("traits", [])],
                    loyalty=round(gov.get("loyalty", 70.0), 1),
                    specialty=pr.get("specialty", ""), blazon=pr.get("blazon", ""),
                    is_core=(pr.get("core_state", sid) == sid),
                ))
            provs_out.sort(key=lambda x: -x["pop"])
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
                cities=cities, provinces=provs_out, history=hist, journal=ev,
            )

    def province_detail(self, pid):
        with self.lock:
            sim = self.sim
            pid = int(pid)
            if pid not in sim.provinces:
                return dict(error="Провінцію не знайдено")
            pr = sim.provinces[pid]
            sid = pr["state"]
            core = pr.get("core_state", sid)
            occ = pr.get("occupied_by")
            gov = pr.get("governor") or {}
            p_burgs = sorted(
                (sim.burgs[b] for b in pr.get("burgs", []) if b in sim.burgs),
                key=lambda x: -x["pop"],
            )
            pop_tot = round(sum(b["pop"] + b["rural"] for b in p_burgs))
            return dict(
                id=pid, uk=pr["uk"], name=pr["name"], form_uk=pr.get("form_uk", "Провінція"),
                state=sid, state_uk=sim.sname(sid),
                core_state=core, core_uk=sim.sname(core),
                occupied_by=occ, occupied_uk=sim.sname(occ) if occ else None,
                siege=round(pr.get("siege", 0.0), 1),
                assimilation=pr.get("assimilation", 0),
                burg=pr.get("burg"), burg_uk=sim.bname(pr.get("burg")),
                pop=pop_tot, blazon=pr.get("blazon", ""), specialty=pr.get("specialty", ""),
                lore=pr.get("lore", ""),
                governor=dict(
                    name=gov.get("name", "—"), age=gov.get("age"),
                    loyalty=round(gov.get("loyalty", 70.0), 1),
                    traits=[LD.GOVERNOR_TRAITS.get(t, {}).get("label", t) for t in gov.get("traits", [])],
                ),
                cities=[dict(
                    id=b["id"], uk=b["uk"], pop=round(b["pop"] + b["rural"]),
                    capital=b.get("capital", False), port=b.get("port", False), walls=b.get("walls", False),
                    market_id=b["market"], market_uk=sim.markets[b["market"]]["uk"],
                ) for b in p_burgs],
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
            lim = _finite(limit)
            lim = 150 if lim is None else max(1, min(int(lim), 500))
            j = self.sim.w["journal"]
            if kind:
                j = [r for r in j if r.get("kind") == kind]
            if q:
                ql = q.lower()
                j = [r for r in j if ql in r.get("text", "").lower()]
            return dict(rows=j[-lim:][::-1])

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
            ov_text = None
            if os.path.exists(self.overrides_file):
                with open(self.overrides_file, encoding="utf-8") as of:
                    ov_text = of.read()
            w = self.sim.w
            skip = {k: w.pop(k) for k in ("war_pairs", "_new_journal") if k in w}
            fpath = os.path.join(self.undo_dir, f"undo_{time.time_ns():020d}.json.gz")
            try:
                snap = dict(label=action_label, world=w, journal_text=j_text, overrides_text=ov_text)
                with gzip.open(fpath + ".tmp", "wt", encoding="utf-8") as f:
                    json.dump(snap, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                os.replace(fpath + ".tmp", fpath)
            except BaseException:
                try:
                    os.remove(fpath + ".tmp")
                except OSError:
                    pass
                raise
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
            self.sim.journal_path = self.journal_file
            self.sim.w.setdefault("meta", {})["journal_file"] = self.journal_file
            j_text = snap.get("journal_text")
            if j_text is not None:
                _write_text_atomic(self.journal_file, j_text)
            elif os.path.exists(self.journal_file):
                os.remove(self.journal_file)
            ov_text = snap.get("overrides_text")
            if ov_text is not None:
                _write_text_atomic(self.overrides_file, ov_text)
            elif os.path.exists(self.overrides_file):
                os.remove(self.overrides_file)
            E.save_world(self.sim.w, self.world_file)
            ov = self.overview()
            os.remove(latest)
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
                        meta = json.load(f)
                    if isinstance(meta, dict):
                        out.append(meta)
                except Exception:
                    pass
        out.sort(key=lambda x: x.get("saved_at", ""), reverse=True)
        return out

    def save_slot(self, name):
        with self.lock:
            label = (name or "").strip() or f"Збереження {E.date_str(self.sim.w)}"
            label = label[:200]
            slot_id = self._new_slot_id(label)
            sdir = os.path.join(self.slots_dir, slot_id)
            os.makedirs(sdir, exist_ok=False)
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
            _write_json_atomic(os.path.join(sdir, "meta.json"), meta)
            return dict(ok=True, message=f"Збережено слот «{label}»", slot=meta, slots=self.list_slots())

    def load_slot(self, slot_id):
        with self.lock:
            sdir = self._slot_dir(slot_id)
            if not sdir:
                return dict(error="Невірний ідентифікатор слоту")
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
            self.sim.journal_path = self.journal_file
            self.sim.w.setdefault("meta", {})["journal_file"] = self.journal_file
            self._ensure_geo()
            ov = self.overview()
            return dict(ok=True, message=f"Завантажено слот «{slot_id}» ({ov['date']})", overview=ov)

    def delete_slot(self, slot_id):
        with self.lock:
            sdir = self._slot_dir(slot_id)
            if not sdir:
                return dict(error="Невірний ідентифікатор слоту")
            if not os.path.isdir(sdir) or os.path.islink(sdir):
                return dict(error="Слот не знайдено")
            shutil.rmtree(sdir)
            return dict(ok=True, message="Слот видалено", slots=self.list_slots())

    def apply_override(self, kind, target_id, fields):
        with self.lock:
            if kind not in ("state", "burg", "province"):
                return dict(error="Невідомий тип об'єкта (дозволено state, burg або province)")
            try:
                tid = int(target_id)
            except (TypeError, ValueError):
                return dict(error="Невірний ID об'єкта")
            if not isinstance(fields, dict):
                return dict(error="Поля правки мають бути об'єктом")
            if kind == "province" and "loyalty" in fields:
                raw_loyalty = fields["loyalty"]
                if raw_loyalty is not None and str(raw_loyalty).strip() and _finite(raw_loyalty) is None:
                    return dict(error="Лояльність має бути скінченним числом")
            world_name = str(self.sim.w.get("meta", {}).get("world_name", "Feria"))[:200]
            if world_name in ("", ".", ".."):
                world_name = "Feria"

            if kind == "state":
                if tid not in self.sim.states:
                    return dict(error="Державу не знайдено")
                self._push_undo(f"редагування держави {self.sim.sname(tid)}")
                st = self.sim.states[tid]
                cleaned = {}
                for k in ("uk", "ruler", "coins", "gov", "lore"):
                    if k in fields and fields[k] is not None:
                        val = str(fields[k]).strip()[:MAX_TEXT_FIELD]
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
            elif kind == "province":
                if tid not in self.sim.provinces:
                    return dict(error="Провінцію не знайдено")
                pr = self.sim.provinces[tid]
                self._push_undo(f"редагування провінції {pr['uk']}")
                cleaned = {}
                for k in ("uk", "governor", "loyalty", "lore", "specialty"):
                    if k in fields and fields[k] is not None:
                        if k == "loyalty":
                            if str(fields[k]).strip() == "":
                                continue
                            val_f = E.clamp(_finite(fields[k]), 0.0, 100.0)
                            pr.setdefault("governor", {})["loyalty"] = round(val_f, 1)
                            cleaned["loyalty"] = round(val_f, 1)
                            continue
                        val = str(fields[k]).strip()[:MAX_TEXT_FIELD]
                        if k != "lore" and not val:
                            continue
                        cleaned[k] = val
                        if k == "uk":
                            pr["uk"] = val
                        elif k == "governor":
                            pr.setdefault("governor", {})["name"] = val
                        elif k == "lore":
                            pr["lore"] = val
                        elif k == "specialty":
                            pr["specialty"] = val
                log_name = pr["uk"]
            else:
                if tid not in self.sim.burgs:
                    return dict(error="Місто не знайдено")
                self._push_undo(f"перейменування міста {self.sim.bname(tid)}")
                b = self.sim.burgs[tid]
                cleaned = {}
                if fields.get("uk") is not None and str(fields["uk"]).strip():
                    val = str(fields["uk"]).strip()[:MAX_TEXT_FIELD]
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
            sec = {"state": "states", "burg": "burgs", "province": "provinces"}[kind]
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
            _write_json_atomic(self.overrides_file, data)

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

    # ---------------------------------------------------------------- нові системи
    def config_data(self):
        with self.lock:
            sim = self.sim
            values = {}
            fields = []
            for key, label, lo, hi, step in CONFIG_FIELDS:
                values[key] = _config_get(sim, key, lo)
                fields.append(dict(key=key, label=label, type="number",
                                   min=lo, max=hi, step=step, value=values[key]))
            for key, label in CONFIG_BOOL_FIELDS:
                values[key] = bool(_config_get(sim, key, True))
                fields.append(dict(key=key, label=label, type="bool", value=values[key]))
            weights = sim.cfg("event_weights", {}) or {}
            return dict(config=values, fields=fields,
                        event_weights=weights if isinstance(weights, dict) else {})

    def set_config(self, values=None, key=None, value=None):
        with self.lock:
            updates = {}
            if isinstance(values, dict):
                updates.update(values)
            if key is not None:
                updates[key] = value
            cleaned = {}
            for k, v in updates.items():
                ok, val = _coerce_config_value(str(k), v)
                if not ok:
                    return dict(error=f"Недозволене або некоректне значення config: {k}")
                cleaned[str(k)] = val
            if not cleaned:
                return dict(error="Немає змін конфігурації")
            self._push_undo("зміна налаштувань симуляції")
            cfg = self.sim.w.setdefault("config", {})
            for k, val in cleaned.items():
                if "." in k:
                    root, sub = k.split(".", 1)
                    block = cfg.setdefault(root, {})
                    if isinstance(block, dict):
                        block[sub] = val
                else:
                    cfg[k] = val
            keys = ", ".join(sorted(cleaned))
            self.sim.log("gm", f"Майстер гри змінив налаштування: {keys}.")
            self.save()
            return dict(ok=True, message=f"Оновлено: {keys}", config=self.config_data()["config"])

    def event_choices(self):
        with self.lock:
            sim = self.sim
            t = sim.tick_index()
            table = getattr(LD, "EVENT_CHOICES", {}) or {}
            out = []
            for i, e in enumerate(sim.w.get("active_events", [])):
                key = e.get("key")
                out.append(dict(
                    uid=e.get("uid", i + 1), key=key, title=e.get("title", LD.EVENT_TITLES.get(key, key)),
                    target=e.get("target", ""), sev=e.get("sev", 1),
                    months_left=max(0, int(e.get("until", t)) - t), text=e.get("text", ""),
                    choices=table.get(key, []) if isinstance(table, dict) else [],
                ))
            return dict(events=out)

    def apply_event_choice(self, uid, choice_id):
        with self.lock:
            sim = self.sim
            active = sim.w.get("active_events", [])
            ev = next((e for e in active if str(e.get("uid")) == str(uid)), None)
            if ev is None:
                try:
                    idx = int(uid) - 1
                except (TypeError, ValueError):
                    idx = -1
                if 0 <= idx < len(active):
                    ev = active[idx]
            if ev is None:
                return dict(error="Активну подію не знайдено")
            if ev.get("uid") is None:
                seq = int(sim.w.get("_event_seq", 0)) + 1
                sim.w["_event_seq"] = seq
                ev["uid"] = seq
            label = (getattr(LD, "EVENT_CHOICES", {}) or {}).get(ev.get("key"), [])
            label = next((c.get("label", choice_id) for c in label
                          if isinstance(c, dict) and str(c.get("id")) == str(choice_id)), choice_id)
            self._push_undo(f"вибір події: {label}")
            try:
                done = EV.apply_event_choice(sim, ev["uid"], choice_id)
            except Exception as ex:
                return dict(error=f"Не вдалося застосувати вибір: {ex}")
            if not done:
                return dict(error="Варіант вибору не знайдено")
            self.save()
            msg = sim.w["journal"][-1]["text"] if sim.w["journal"] else f"Вибір «{label}» застосовано"
            return dict(ok=True, message=msg, choice=done if isinstance(done, dict) else dict(label=label))

    def quest_board(self, state_id=None):
        with self.lock:
            w = self.sim.w
            board = w.setdefault("quests", {})
            for k in ("active", "completed", "expired"):
                if not isinstance(board.get(k), list):
                    board[k] = []
            sid = state_id if state_id not in (None, "", "all") else None
            try:
                hooks = DT.generate_quest_hooks(self.sim, state_id=sid)
            except Exception:
                hooks = []
            return dict(active=board["active"], completed=board["completed"],
                        expired=board["expired"], hooks=hooks)

    def quest_accept(self, quest_id, state_id=None):
        with self.lock:
            sid = state_id if state_id not in (None, "", "all") else None
            self._push_undo("прийняття квесту")
            quest = DT.accept_quest(self.sim, quest_id, state_id=sid)
            if not quest:
                return dict(error="Квест не знайдено на дошці оголошень")
            self.save()
            return dict(ok=True, message=f"Квест «{quest.get('title', quest_id)}» прийнято",
                        quest=quest, board=self.quest_board())

    def quest_complete(self, quest_id, success=True):
        with self.lock:
            self._push_undo("завершення квесту")
            quest = DT.complete_quest(self.sim, quest_id, success=bool(success))
            if not quest:
                return dict(error="Прийнятий квест не знайдено")
            self.save()
            return dict(ok=True, message=f"Квест «{quest.get('title', quest_id)}» закрито",
                        quest=quest, board=self.quest_board())

    def npc_board(self):
        with self.lock:
            npcs = self.sim.w.get("npcs") or []
            return dict(npcs=npcs if isinstance(npcs, list) else [])

    def generate_npc(self, state_id=None, role=None):
        with self.lock:
            sid = state_id if state_id not in (None, "", "all") else None
            self._push_undo("генерація NPC")
            try:
                npc = DT.generate_npc(self.sim, state_id=sid, role=role or None)
            except Exception as ex:
                return dict(error=f"Не вдалося створити NPC: {ex}")
            board = self.sim.w.setdefault("npcs", [])
            if not isinstance(board, list):
                board = []
                self.sim.w["npcs"] = board
            npc = dict(npc, created_tick=self.sim.tick_index())
            board.append(npc)
            self.save()
            return dict(ok=True, message=f"Створено: {npc['name']} — {npc['role']}",
                        npc=npc, npcs=board)

    def shop_buy(self, burg_id, item_id, qty=1):
        with self.lock:
            sim = self.sim
            try:
                bid = int(burg_id)
            except (TypeError, ValueError):
                return dict(error="Невірний ID міста")
            try:
                count = max(1, min(99, int(qty)))
            except (TypeError, ValueError):
                return dict(error="Невірна кількість")
            try:
                retail = DT.city_retail_prices(sim, bid)
            except Exception as ex:
                return dict(error=str(ex))
            item = next((x for x in retail.get("items", []) if str(x.get("id")) == str(item_id)), None)
            if item is None:
                return dict(error="Товар не знайдено у каталозі")
            if int(item.get("available", 0)) < count:
                return dict(error=f"На ринку є лише {item.get('available', 0)} шт.")
            self._push_undo(f"купівля {item['name']} ×{count}")
            res = DT.purchase_shop_item(sim, bid, item_id, count)
            if not res.get("ok"):
                return dict(error=res.get("reason", "Покупку скасовано"))
            self.save()
            return dict(ok=True, message=f"Куплено {item['name']} ×{count} за {res.get('coins', '')}",
                        receipt=res, retail=DT.city_retail_prices(sim, bid))

    def fork(self, name):
        with self.lock:
            label = ((name or "").strip() or f"Гілка {E.date_str(self.sim.w)}")[:200]
            slot_id = self._new_slot_id(label, fork=True)
            sdir = os.path.join(self.slots_dir, slot_id)
            self._push_undo(f"гілка «{label}»")
            self.save()
            os.makedirs(sdir, exist_ok=False)
            shutil.copy2(self.world_file, os.path.join(sdir, "world.json"))
            if os.path.exists(self.journal_file):
                shutil.copy2(self.journal_file, os.path.join(sdir, "journal.jsonl"))
            if os.path.exists(self.geo_file):
                shutil.copy2(self.geo_file, os.path.join(sdir, "map_geo.json"))
            meta = dict(
                id=slot_id, name=label, fork=True,
                parent_world=self.world_file,
                world_name=self.sim.w.get("meta", {}).get("world_name", "Ферія"),
                date=E.date_str(self.sim.w),
                pop=round(sum(st.get("pop", 0) for st in self.sim.states.values())),
                states=len(self.sim.states),
                saved_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            _write_json_atomic(os.path.join(sdir, "meta.json"), meta)
            return dict(ok=True, message=f"Гілка «{label}» створена; поточний світ не змінено",
                        slot=meta, slots=self.list_slots())

    def step(self, months, export_report=False):
        months = _finite(months)
        if months is None:
            return dict(error="Кількість місяців має бути скінченним числом")
        months = max(1, min(int(months), 24))
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
            self.sim._index_mods()
            if not hasattr(self.sim, "acc"):
                self.sim.acc = dict(pop={}, gdp={})
            tgt = int(target_id) if target_id not in (None, "", "auto") else None
            EV.fire(self.sim, self._rng(), key, target=tgt, sev=int(sev) if sev else None)
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
            PO.declare_war(self.sim, a, b, self._rng(), casus="воля майстра гри")
            self.save()
            return dict(ok=True, message=self.sim.w["journal"][-1]["text"])

    def end_war(self, war_id):
        with self.lock:
            war_id = int(war_id)
            wr = next((w for w in self.sim.w["wars"] if w["id"] == war_id), None)
            if not wr:
                return dict(error="Війну не знайдено")
            self._push_undo(f"мир ({wr['name']})")
            PO.end_war(self.sim, wr, self._rng())
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
            num = _finite(value)
            if num is None:
                return dict(error="Значення має бути скінченним числом")
            st = self.sim.states[sid]
            self._push_undo(f"зміна {field} ({st['uk']})")
            old = st[field]
            st[field] = num
            self.sim.log("gm", f"Майстер гри змінив {field} держави {st['uk']}: {old} → {num}.", state=sid)
            self.save()
            return dict(ok=True, message=f"{st['uk']}: {field} = {num}")

    def export_report(self):
        with self.lock:
            RP.write_all(self.sim, self.vault)
            return dict(ok=True, message="Нотатки Obsidian оновлено")

    def _init_from_map(self, map_path, year=None, era=None, seed=1):
        imp = IM.import_map(map_path)
        ov_path = self.overrides_file
        over = {}
        if os.path.exists(ov_path):
            try:
                with open(ov_path, encoding="utf-8") as f:
                    over = json.load(f)
            except Exception:
                over = {}
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
        self._push_undo(f"імпорт карти {os.path.basename(map_path)}")
        if os.path.exists(self.journal_file):
            os.remove(self.journal_file)
        self.sim = sim
        self.sim.journal_path = self.journal_file
        self.sim.w.setdefault("meta", {})["journal_file"] = self.journal_file
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
                b64 = str(content_b64 or "")
                if len(b64) > int(MAX_UPLOAD_BYTES * 4 / 3) + 8:
                    return dict(error="Файл карти занадто великий")
                raw = base64.b64decode(b64, validate=True)
                if not raw or len(raw) > MAX_UPLOAD_BYTES:
                    return dict(error="Файл карти занадто великий або порожній")
                name = os.path.basename(str(filename or "map.map"))
                name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")[:120]
                if not name or not SAFE_MAP_NAME.fullmatch(name):
                    return dict(error="Недозволене ім'я файлу карти")
                if os.path.splitext(name)[1].lower() not in (".map", ".json", ".gz"):
                    return dict(error="Підтримуються лише .map, .json та .map.gz")
                if name.lower().endswith(".gz"):
                    dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    try:
                        text = dec.decompress(raw, MAX_MAP_TEXT_BYTES + 1)
                        if not dec.eof or len(text) > MAX_MAP_TEXT_BYTES:
                            return dict(error="Розпакована карта занадто велика")
                        text += dec.flush(max(0, MAX_MAP_TEXT_BYTES + 1 - len(text)))
                    except zlib.error:
                        return dict(error="Пошкоджений gzip-архів карти")
                    if len(text) > MAX_MAP_TEXT_BYTES:
                        return dict(error="Розпакована карта занадто велика")
                os.makedirs(self.maps_dir, exist_ok=True)
                out_path = os.path.join(self.maps_dir, name)
                tmp = os.path.join(self.maps_dir, f".upload_{uuid.uuid4().hex}.tmp")
                try:
                    with open(tmp, "wb") as f:
                        f.write(raw)
                    os.replace(tmp, out_path)
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                return self._init_from_map(out_path, year=year, era=era, seed=seed)
            except Exception as ex:
                return dict(error=f"Помилка імпорту карти: {type(ex).__name__}")

    def switch_map(self, map_path, year=None, era=None, seed=1):
        with self.lock:
            try:
                allowed = {os.path.realpath(m["path"]) for m in self._list_saved_maps()}
                target = os.path.realpath(str(map_path or ""))
                if target not in allowed or not os.path.isfile(target) or os.path.islink(target):
                    return dict(error="Карту не знайдено у списку дозволених")
                return self._init_from_map(target, year=year, era=era, seed=seed)
            except Exception as ex:
                return dict(error=f"Помилка завантаження карти: {type(ex).__name__}")


def make_handler(app: AppState, expected_hosts=None):
    class Handler(BaseHTTPRequestHandler):
        timeout = 15
        server_version = "FeriaSim/1.0"

        def log_message(self, fmt, *args):
            pass

        def _json(self, data, code=200):
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def _security_ok(self):
            addr = self.server.server_address
            allowed = _expected_hosts(str(addr[0]), addr[1]) if expected_hosts is None \
                else {str(h).lower() for h in expected_hosts}
            host = self.headers.get("Host", "").strip().lower()
            if host not in allowed:
                self._json({"error": "Forbidden host"}, 403)
                return False
            if self.command == "POST":
                origin = self.headers.get("Origin", "")
                if origin and urllib.parse.urlparse(origin).netloc.lower() not in allowed:
                    self._json({"error": "Forbidden origin"}, 403)
                    return False
                if self.headers.get("Sec-Fetch-Site", "") not in ("", "same-origin", "none"):
                    self._json({"error": "Forbidden fetch site"}, 403)
                    return False
            return True

        @staticmethod
        def _qi(qs, key, default=None, required=False):
            val = qs.get(key, [None])[0]
            if val is None or val == "":
                if required:
                    raise ValueError(f"Параметр {key} обов'язковий")
                return default
            try:
                return int(val)
            except (TypeError, ValueError):
                raise ValueError(f"Параметр {key} має бути цілим числом")

        def _body(self):
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Transfer-Encoding не підтримується")
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype != "application/json":
                raise ValueError("Потрібен Content-Type: application/json")
            try:
                ln = int(self.headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                raise ValueError("Невірний Content-Length")
            if ln <= 0 or ln > MAX_BODY_BYTES:
                raise ValueError("Недозволений розмір запиту")
            raw = self.rfile.read(ln)
            if len(raw) != ln:
                raise ValueError("Неповне тіло запиту")

            def reject_constant(value):
                raise ValueError(f"Недозволене числове значення: {value}")

            try:
                data = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ValueError("Тіло запиту має бути коректним JSON")
            if not isinstance(data, dict):
                raise ValueError("Тіло запиту має бути JSON-об'єктом")
            return data

        def do_GET(self):
            try:
                if not self._security_ok():
                    return
                u = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(u.query)
                if u.path == "/":
                    with open(UI_FILE, "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Security-Policy",
                                     "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                     "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
                    self.end_headers()
                    self.wfile.write(body)
                elif u.path == "/api/overview":
                    self._json(app.overview())
                elif u.path == "/api/state":
                    self._json(app.state_detail(self._qi(qs, "id", required=True)))
                elif u.path == "/api/province":
                    self._json(app.province_detail(self._qi(qs, "id", required=True)))
                elif u.path == "/api/market":
                    self._json(app.market_detail(self._qi(qs, "id", required=True)))
                elif u.path == "/api/goods":
                    self._json(app.goods_table())
                elif u.path == "/api/guilds":
                    self._json(app.guilds_data())
                elif u.path == "/api/journal":
                    self._json(app.journal_query(qs.get("kind", [""])[0], qs.get("q", [""])[0],
                                                 self._qi(qs, "limit", 150)))
                elif u.path == "/api/map_geo":
                    self._json(app.map_geo())
                elif u.path == "/api/config":
                    self._json(app.config_data())
                elif u.path == "/api/event_choices":
                    self._json(app.event_choices())
                elif u.path in ("/api/retail", "/api/shop"):
                    self._json(app.retail_prices(qs.get("burg", [0])[0]))
                elif u.path == "/api/route":
                    self._json(app.calc_route(qs.get("from", [0])[0], qs.get("to", [0])[0], qs.get("mode", ["foot"])[0]))
                elif u.path == "/api/quests":
                    self._json(app.quest_hooks(qs.get("state", [None])[0]))
                elif u.path == "/api/quest_board":
                    self._json(app.quest_board(qs.get("state", [None])[0]))
                elif u.path == "/api/npc":
                    self._json(app.npc_board())
                elif u.path == "/api/slots":
                    self._json(dict(slots=app.list_slots()))
                else:
                    self._json({"error": "Not found"}, 404)
            except ValueError as ex:
                self._json({"error": str(ex) or "Невірний запит"}, 400)
            except Exception:
                self.log_error("Unhandled request error")
                self._json({"error": "Внутрішня помилка сервера"}, 500)

        def do_POST(self):
            try:
                u = urllib.parse.urlparse(self.path)
                path = u.path
                post_paths = {
                    "/api/step", "/api/undo", "/api/fire", "/api/declare", "/api/peace",
                    "/api/set_state", "/api/override", "/api/set_config", "/api/event_choice",
                    "/api/quest_accept", "/api/quest_complete", "/api/shop_buy", "/api/npc",
                    "/api/fork", "/api/save_slot", "/api/load_slot", "/api/delete_slot",
                    "/api/report", "/api/upload_map", "/api/switch_map",
                }
                if path not in post_paths:
                    self._json({"error": "Not found"}, 404)
                    return
                if not self._security_ok():
                    return
                body = self._body()
                if path == "/api/step":
                    self._json(app.step(body.get("months", 1), body.get("report", False)))
                elif path == "/api/undo":
                    self._json(app.undo())
                elif path == "/api/fire":
                    self._json(app.fire_event(body.get("key"), body.get("target"), body.get("sev")))
                elif path == "/api/declare":
                    self._json(app.declare_war(body.get("a"), body.get("b")))
                elif path == "/api/peace":
                    self._json(app.end_war(body.get("war_id")))
                elif path == "/api/set_state":
                    self._json(app.set_state_field(body.get("id"), body.get("field"), body.get("value")))
                elif path == "/api/override":
                    self._json(app.apply_override(body.get("kind"), body.get("id"), body.get("fields", {})))
                elif path == "/api/set_config":
                    self._json(app.set_config(values=body.get("values"), key=body.get("key"), value=body.get("value")))
                elif path == "/api/event_choice":
                    self._json(app.apply_event_choice(body.get("uid"), body.get("choice_id")))
                elif path == "/api/quest_accept":
                    self._json(app.quest_accept(body.get("id") or body.get("quest_id"), body.get("state")))
                elif path == "/api/quest_complete":
                    self._json(app.quest_complete(body.get("id") or body.get("quest_id"), body.get("success", True)))
                elif path == "/api/shop_buy":
                    self._json(app.shop_buy(body.get("burg") or body.get("burg_id"), body.get("item") or body.get("item_id"), body.get("qty", 1)))
                elif path == "/api/npc":
                    self._json(app.generate_npc(body.get("state"), body.get("role")))
                elif path == "/api/fork":
                    self._json(app.fork(body.get("name", "")))
                elif path == "/api/save_slot":
                    self._json(app.save_slot(body.get("name", "")))
                elif path == "/api/load_slot":
                    self._json(app.load_slot(body.get("id", "")))
                elif path == "/api/delete_slot":
                    self._json(app.delete_slot(body.get("id", "")))
                elif path == "/api/report":
                    self._json(app.export_report())
                elif path == "/api/upload_map":
                    self._json(app.load_map_upload(body.get("filename"), body.get("content_b64", ""),
                                                   body.get("year"), body.get("era"), body.get("seed", 1)))
                elif path == "/api/switch_map":
                    self._json(app.switch_map(body.get("path", ""), body.get("year"), body.get("era"), body.get("seed", 1)))
                else:
                    self._json({"error": "Not found"}, 404)
            except ValueError as ex:
                self._json({"error": str(ex) or "Невірний запит"}, 400)
            except Exception:
                self.log_error("Unhandled request error")
                self._json({"error": "Внутрішня помилка сервера"}, 500)

    return Handler


def run_server(world_file, journal_file, host="127.0.0.1", port=8765, vault=None, open_browser=True):
    app = AppState(world_file, journal_file, vault=vault)
    bind_host = _host_key(host)
    ipv6 = ":" in bind_host
    hosts = _expected_hosts(bind_host, port)

    class _Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if ipv6 else socket.AF_INET
        daemon_threads = True

    srv = _Server((bind_host, port), make_handler(app, expected_hosts=hosts))
    display_host = f"[{bind_host}]" if ipv6 else (bind_host or "127.0.0.1")
    url = f"http://{display_host}:{port}/"
    if bind_host not in ("", "127.0.0.1", "localhost", "::1"):
        print("Увага: сервер доступний з інших хостів без авторизації — використовуйте лише довірену мережу.")
    print(f"Веб-панель Ферії запущено: {url} (Ctrl+C для зупинки)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер зупинено.")
