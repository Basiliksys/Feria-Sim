# -*- coding: utf-8 -*-
"""Генератор подій: природа, хвороби, економіка, політика, магія."""
import copy
import math

from . import lore_data as LD
from .engine import clamp
from . import politics as PO

SEV_WORD = {1: "помірна", 2: "серйозна", 3: "катастрофічна"}

# Резервні ідентифікатори товарів (якщо LD.GOOD_IDS ще не додано іншою гілкою).
GOOD_WOOD = PO.good_id("Wood", 1)
GOOD_FISH = PO.good_id("Fish", 11)
GOOD_WHALES = PO.good_id("Whales", 37)
GOOD_SHIPS = PO.good_id("Ships", 53)
GOOD_CATTLE = PO.good_id("Cattle", 10)
GOOD_SHEEP = PO.good_id("Sheep", 30)
GOOD_HORSES = PO.good_id("Horses", 18)
GOOD_GOLD = PO.good_id("Gold", 8)
GOOD_IRON = PO.good_id("Iron", 4)
GOOD_COPPER = PO.good_id("Copper", 5)
GOOD_TIN = PO.good_id("Tin", 6)
GOOD_SILVER = PO.good_id("Silver", 7)
GOOD_MARBLE = PO.good_id("Marble", 3)
GOOD_OIL = PO.good_id("Oil", 35)
GOOD_TOOLS = PO.good_id("Tools", 58)
GOOD_ARMS = PO.good_id("Arms", 59)
GOOD_ARTILLERY = PO.good_id("Artillery", 61)
STORM_GOODS = [GOOD_FISH, GOOD_WHALES, GOOD_SHIPS]
MURRAIN_GOODS = [GOOD_CATTLE, GOOD_SHEEP, GOOD_HORSES]
MINE_GOODS = [GOOD_IRON, GOOD_COPPER, GOOD_TIN, GOOD_SILVER, GOOD_GOLD, GOOD_MARBLE, GOOD_OIL]
RUST_GOODS = [GOOD_IRON, GOOD_TOOLS, GOOD_ARMS, GOOD_ARTILLERY]


def _cfg(sim, key, default):
    return PO.get_cfg(sim, key, default)


def _num(value, default=0.0):
    """Скінченне число або fallback (захист від NaN/inf зі збережень і конфігу)."""
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return f if math.isfinite(f) else default


def _int(value, default=0, lo=None, hi=None):
    iv = int(_num(value, default))
    if lo is not None:
        iv = max(lo, iv)
    if hi is not None:
        iv = min(hi, iv)
    return iv


# Поля держави, які дозволено змінювати negative/positive дельтою з вибору події.
_STATE_EFFECT_KEYS = {
    "treasury", "debt", "stability", "legitimacy", "tech", "food_sat", "lux_sat",
    "alert", "readiness", "war_exhaustion", "prod_dev", "tax_mult",
}
_FLAT_ADD_KEYS = ("stability", "legitimacy", "treasury", "food_sat", "lux_sat", "mort")
_FLAT_MULT_KEYS = ("prod_agri", "prod_all", "rebuild", "trade")
# Дозволені ключі модифікаторів за областю застосування.
_MOD_KEYS = {
    "state": {"prod_all", "prod_agri", "prod_g", "rebuild", "mort", "stab", "util_need",
              "tax", "war_power", "pop_growth", "trade", "tariff", "food_need"},
    "market": {"trade", "mort", "prod_all", "price_g"},
    "burg": {"prod_all", "prod_agri", "prod_g", "rebuild", "mort", "pop_growth", "food_need"},
    "edge": {"trade", "piracy"},
    "pair": {"rel", "embargo"},
}


def _mod_key_ok(sim, scope, key):
    allowed = _MOD_KEYS.get(scope)
    if not allowed or not isinstance(key, str) or not key:
        return False
    if key in allowed:
        return True
    for prefix in ("prod_g", "price_g"):
        if prefix in allowed and key.startswith(prefix):
            suffix = key[len(prefix):]
            if suffix.isdigit():
                return _int(suffix, -1) in sim.goods
    return False


def _canon_id(registry, value):
    """Повертає канонічний ключ реєстру (підтримує рядки зі збережень)."""
    if isinstance(value, bool):
        return None
    try:
        if value in registry:
            return value
    except (TypeError, ValueError):
        return None
    if isinstance(value, str):
        try:
            iv = int(value)
        except ValueError:
            return None
        try:
            return iv if iv in registry else None
        except (TypeError, ValueError):
            return None
    return None


def _mod_target(sim, scope, value):
    if scope == "pair":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        a, b = (_canon_id(sim.states, value[0]), _canon_id(sim.states, value[1]))
        if a is None or b is None:
            return None
        return (min(a, b), max(a, b))
    if scope == "marker":
        markers = sim.w.get("markers", []) or []
        if isinstance(value, dict):
            return value if any(value is m or value == m for m in markers) else None
        idx = _canon_id(range(len(markers)), value)
        return markers[idx] if idx is not None else None
    registry = {"state": sim.states, "market": sim.markets, "burg": sim.burgs,
                "edge": range(len(sim.edges))}.get(scope)
    return _canon_id(registry, value) if registry is not None else None


def _target_for_scope(sim, scope, target):
    """Перевіряє ціль події проти реєстру відповідної області."""
    if scope == "state":
        sid = _canon_id(sim.states, target)
        return sid if sid is not None and not sim.states[sid].get("extinct") else None
    if scope == "pair":
        return _mod_target(sim, "pair", target)
    if scope in ("market", "burg", "edge", "marker"):
        return _mod_target(sim, scope, target)
    return None


def _event_budget(sim, reserve=True):
    """Лічильник подій поточного місяця; None = обмеження не встановлено."""
    budget = sim.w.get("_event_budget")
    if not isinstance(budget, dict) or budget.get("tick") != sim.tick_index():
        return None
    left = _int(budget.get("left", 0), 0, 0, 1000)
    if reserve:
        budget["left"] = left - 1
    return left


def _bump_tech(sim, sid, factor):
    st = sim.states.get(sid)
    if not st:
        return
    f = _num(factor, 1.0)
    if f <= 0:
        f = 1.0
    st["tech"] = round(PO.clamp_tech(sim, _num(st.get("tech", 1.0), 1.0) * f), 4)


def _wchoice(rng, items, weights):
    if not items:
        return None
    clean = []
    for it, wt in zip(items, weights):
        v = _num(wt, 0.0)
        if math.isfinite(v) and v > 0:
            clean.append((it, v))
    if not clean:
        return rng.choice(list(items))
    tot = sum(v for _, v in clean)
    r = rng.random() * tot
    for it, wt in clean:
        r -= wt
        if r <= 0:
            return it
    return clean[-1][0]


def _reconcile_event_seq(w, active):
    """Підтягує лічильник UID до наявних подій (у тому числі після завантаження)."""
    max_uid = _int(w.get("_event_seq", 0), 0, 0, 10 ** 9)
    for ev in active:
        if not isinstance(ev, dict):
            continue
        max_uid = max(max_uid, _int(ev.get("uid", 0), 0, 0, 10 ** 9))
    w["_event_seq"] = max_uid


def step_events(sim, rng):
    w = sim.w
    t = sim.tick_index()
    active = []
    for e in w.get("active_events", []) or []:
        if not isinstance(e, dict):
            continue
        until = _num(e.get("until"), -1.0)
        if math.isfinite(until) and until > t:
            active.append(e)
    w["active_events"] = active
    _reconcile_event_seq(w, active)
    # похідні риси правителя мають бути готові до торгівлі в цьому ж місяці
    PO.sync_ruler_fields(sim)
    step_epidemics(sim, rng)
    event_rate = clamp(_num(_cfg(sim, "event_rate", 1.0), 1.0), 0.0, 100.0)
    if not math.isfinite(event_rate):
        event_rate = 1.0
    scale = 1.0
    if _cfg(sim, "event_scale_by_size", True):
        n = max(1, len(sim.states))
        scale = clamp(math.sqrt(n / 50.0), 0.6, 2.0)
    cap = _int(_cfg(sim, "max_events_per_month", 4), 4, 0, 64)
    w["_event_budget"] = dict(tick=t, left=cap)
    weights_cfg = _cfg(sim, "event_weights", {}) or {}
    event_weights = weights_cfg if isinstance(weights_cfg, dict) else {}
    base_p = clamp(0.10 * event_rate * scale, 0.0, 1.0)
    candidates = []
    for key, spec in LD.EVENT_TABLE.items():
        if not isinstance(spec, dict):
            continue
        mul = _num(event_weights.get(key, 1.0), 1.0)
        if not math.isfinite(mul) or mul < 0:
            mul = 1.0
        base_weight = _num(spec.get("weight", 1.0), 1.0)
        if not math.isfinite(base_weight) or base_weight < 0:
            base_weight = 1.0
        weight = base_weight * mul
        if weight > 0 and math.isfinite(weight):
            candidates.append((key, weight))
    fired = 0
    while candidates and fired < cap:
        key = _wchoice(rng, [k for k, _ in candidates], [wt for _, wt in candidates])
        candidates = [(k, wt) for k, wt in candidates if k != key]
        if key is None or rng.random() >= base_p:
            continue
        # Якщо подія не знайшла ціль — вага перерозподіляється на інші події.
        if fire(sim, rng, key) is True:
            fired += 1


def _spec_range(raw, default, lo, hi):
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        a, b = _int(raw[0], default[0], lo, hi), _int(raw[1], default[1], lo, hi)
        return (min(a, b), max(a, b))
    return default


def fire(sim, rng, key, target=None, sev=None, _nested=False):
    """Сумісний вхід: True = подія відбулася, False = цілі/обробника немає.

    `_nested` позначає події, викликані іншими подіями (напр., переворот): вони
    підлягають тому самому місячному бюджету, що й звичайні події.
    """
    spec = LD.EVENT_TABLE.get(key)
    if not isinstance(spec, dict):
        return False
    fn = HANDLERS.get(key)
    if not fn:
        return False
    scope = spec.get("scope")
    if scope not in ("state", "market", "burg", "marker", "pair", "edge"):
        return False
    budget = _event_budget(sim, reserve=False)
    if budget is not None and budget <= 0:
        return False
    sev_range = _spec_range(spec.get("sev"), (1, 3), 1, 3)
    if sev is None:
        severity = _int(rng.randint(*sev_range), sev_range[0], sev_range[0], sev_range[1])
    else:
        severity = _int(sev, sev_range[0], sev_range[0], sev_range[1])
    dur_range = _spec_range(spec.get("dur"), (0, 0), 0, 120)
    dur = _int(rng.randint(*dur_range), 0, 0, 120) if dur_range[1] else 0
    if target is None:
        target = pick_target(sim, rng, key, scope)
    tgt = _target_for_scope(sim, scope, target)
    if tgt is None:
        return False
    res = fn(sim, rng, tgt, severity, dur)
    if res is False:
        return False
    if budget is not None:
        _event_budget(sim, reserve=True)
    return True


def pick_target(sim, rng, key, scope):
    states = [s for s in sim.states if not sim.states[s].get("extinct")]
    if scope in ("state", "pair") and not states:
        return None
    if scope == "state":
        wts = []
        for s in states:
            st = sim.states[s]
            pop = _num(sim.acc.get("pop", {}).get(s, st.get("pop_cache", 1)), 1.0)
            wt = math.sqrt(max(pop, 1.0))
            if key in ("undead_incursion", "monster_horde", "black_rust") and st.get("continent") == "Кірос":
                wt *= 3.5
            if key == "black_rust" and st.get("name") == "Galg":
                wt *= 4.0
            if key in ("peasant_revolt", "coup", "noble_conspiracy", "succession_crisis"):
                stability = clamp(_num(st.get("stability", 50.0), 50.0), 0.0, 100.0)
                wt *= (1.6 - stability / 100.0) ** 2
            wts.append(wt)
        return _wchoice(rng, states, wts)
    if scope == "market":
        ids = list(sim.markets)
        if not ids:
            return None
        if key in ("sea_storm", "piracy_surge"):
            ports = [m for m in ids
                     if sim.burgs.get(sim.markets[m].get("center"), {}).get("port")]
            ids = ports or ids
        return rng.choice(ids)
    if scope == "burg":
        ids = list(sim.burgs)
        if not ids:
            return None
        wts = [math.sqrt(max(_num(sim.burgs[b].get("pop", 0.0), 0.0), 0.0))
               * (1.3 if key in ("dungeon_breach", "dragon_attack") else 1) for b in ids]
        return _wchoice(rng, ids, wts)
    if scope == "marker":
        vol = [m for m in (sim.w.get("markers", []) or [])
               if isinstance(m, dict) and "volcan" in str(m.get("type", "")).lower()]
        return rng.choice(vol) if vol else None
    if scope == "pair":
        a = _wchoice(rng, states, [1.0] * len(states))
        if a is None:
            return None
        nb = [n for n in sim.states[a].get("neighbors", []) if n in sim.states and not sim.states[n].get("extinct")]
        if not nb:
            return None
        return (a, rng.choice(nb))
    if scope == "edge":
        if not sim.edges:
            return None
        return rng.randrange(len(sim.edges))
    return None


def _record(sim, key, scope, target_name, sev, dur, text, states=None, **kw):
    t = sim.tick_index()
    states = list(states or [])
    w = sim.w
    active = w.setdefault("active_events", [])
    _reconcile_event_seq(w, active)
    if dur:
        uid = _int(w.get("_event_seq", 0), 0, 0, 10 ** 9) + 1
        used = {_int(e.get("uid", 0), 0) for e in active if isinstance(e, dict)}
        while uid in used:
            uid += 1
        w["_event_seq"] = uid
        rec = dict(uid=uid, key=key, title=LD.EVENT_TITLES[key], target=target_name, sev=sev,
                   until=t + dur, text=text, states=states, scope=scope)
        rec.update(kw)
        active.append(rec)
    sim.log("event", text, event=key, sev=sev, states=states, **kw)


def _clamp_state_effect(sim, key, value):
    if key in ("stability", "legitimacy", "war_exhaustion"):
        return clamp(value, 0.0, 100.0)
    if key == "tech":
        return PO.clamp_tech(sim, value)
    if key in ("food_sat", "lux_sat"):
        return clamp(value, 0.0, 2.0)
    if key in ("treasury", "debt"):
        return max(0.0, value)
    if key == "readiness":
        return clamp(value, 0.35, 1.15)
    if key == "prod_dev":
        return clamp(value, 0.5, 1.25)
    if key == "tax_mult":
        return clamp(value, 0.6, 1.6)
    if key == "alert":
        return clamp(value, 0.4, 3.0)
    return clamp(value, -1e9, 1e9)


def _prepare_choice_state(sim, st, *effect_dicts):
    """Готує безпечні дельти; повертає None, якщо будь-яке поле хибне."""
    changes, debt_delta = {}, 0.0

    def current(key):
        if key not in st:
            return 0.0
        value = st[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = float(value)
        return value if math.isfinite(value) else None

    for effects in effect_dicts:
        for key, delta in effects.items():
            if key not in _STATE_EFFECT_KEYS:
                return None
            if isinstance(delta, bool) or not isinstance(delta, (int, float)):
                return None
            delta = float(delta)
            if not math.isfinite(delta):
                return None
            cur = current(key)
            if cur is None:
                return None
            new = cur + delta
            if key == "treasury" and new < 0:
                # Як і у звичайному фінансовому шляху: дефіцит іде в борг.
                debt_delta += -new
                new = 0.0
            changes[key] = round(_clamp_state_effect(sim, key, new), 4)
    if debt_delta:
        base = changes.get("debt")
        if base is None:
            base = current("debt")
            if base is None:
                return None
        changes["debt"] = round(max(0.0, base + debt_delta), 4)
    return changes


def apply_event_choice(sim, uid, choice_id):
    """Застосовує вибір GM до активної події. Повертає False нічого не змінивши."""
    w = sim.w
    active = w.get("active_events", [])
    ev = next((e for e in active if isinstance(e, dict) and str(e.get("uid")) == str(uid)), None)
    if ev is None or ev.get("resolved"):
        return False
    table = getattr(LD, "EVENT_CHOICES", {})
    if not isinstance(table, dict):
        return False
    options = table.get(ev.get("key")) or []
    choice = None
    for opt in options:
        if isinstance(opt, dict) and str(opt.get("id")) == str(choice_id):
            choice = opt
            break
    if choice is None:
        return False
    effects = choice.get("effects") or {}
    if not isinstance(effects, dict):
        return False
    st_eff = effects.get("state")
    mod_eff = effects.get("mod")
    pair_eff = effects.get("pair")
    journal = effects.get("journal")
    if st_eff is not None and not isinstance(st_eff, dict):
        return False
    if mod_eff is not None and not isinstance(mod_eff, (dict, list, tuple)):
        return False
    if pair_eff is not None and not isinstance(pair_eff, dict):
        return False
    if journal is not None and not isinstance(journal, str):
        return False
    mods = [mod_eff] if isinstance(mod_eff, dict) else list(mod_eff or [])
    if any(not isinstance(m, dict) or not m.get("key") for m in mods):
        return False
    # Плоска схема з LD.EVENT_CHOICES: адитивні дельти та мультиплікатори.
    flat = {k: v for k, v in effects.items() if k in _FLAT_ADD_KEYS or k in _FLAT_MULT_KEYS}
    if set(st_eff or {}) & set(flat):
        return False  # подвійне застосування того самого поля
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v))
           for v in flat.values()):
        return False
    states = list(ev.get("states") or [])
    sid = states[0] if states else None
    st = sim.states.get(sid)
    if (st_eff or flat) and st is None:
        return False

    add_eff = {k: v for k, v in flat.items() if k in _FLAT_ADD_KEYS and k != "mort"}
    changes = {} if st is None else _prepare_choice_state(sim, st, st_eff or {}, add_eff)
    if changes is None:
        return False
    ready_mods = []
    for key in _FLAT_MULT_KEYS:
        if key not in flat:
            continue
        val = _num(flat[key], 0.0)
        if val <= 0 or not math.isfinite(val):
            return False
        ready_mods.append(("state", sid, key, clamp(val, 0.01, 100.0), 6, "mult"))
    if "mort" in flat:
        val = _num(flat["mort"], 0.0)
        if val < 0 or not math.isfinite(val):
            return False
        ready_mods.append(("state", sid, "mort", clamp(val, 0.0, 0.05), 6, "add"))

    src = f"choice:{ev.get('key')}:{choice_id}"
    for m in mods:
        scope = m.get("scope", "state")
        key = m.get("key")
        if scope not in _MOD_KEYS or not _mod_key_ok(sim, scope, key):
            continue
        mid = _mod_target(sim, scope, m.get("id", sid))
        if mid is None:
            continue
        raw = m.get("val", 1.0)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        val = float(raw)
        months_raw = m.get("months", 1)
        if isinstance(months_raw, bool) or not isinstance(months_raw, (int, float)):
            continue
        if not math.isfinite(val) or not math.isfinite(float(months_raw)):
            continue
        kind = m.get("kind", "mult")
        if kind not in ("mult", "add"):
            continue
        months = _int(months_raw, 1, 1, 120)
        ready_mods.append((scope, mid, key, clamp(val, -1e6, 1e6), months, kind))

    rel_delta = 0.0
    if pair_eff:
        pair = pair_eff.get("states") or states[:2]
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            a, b = _canon_id(sim.states, pair[0]), _canon_id(sim.states, pair[1])
            if a is not None and b is not None:
                raw = pair_eff.get("rel", 0.0)
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    return False
                raw = float(raw)
                if not math.isfinite(raw):
                    return False
                rel_delta = clamp(raw, -100.0, 100.0)

    # Усе перевірено — застосовуємо.
    for key, value in changes.items():
        st[key] = value
    for scope, mid, key, val, months, kind in ready_mods:
        sim.add_mod(scope, mid, key, val, months, src=src, kind=kind)
    if rel_delta:
        pair = pair_eff.get("states") or states[:2]
        a, b = _canon_id(sim.states, pair[0]), _canon_id(sim.states, pair[1])
        PO.rel_add(sim, a, b, rel_delta)

    text = journal or f"{choice.get('label', choice_id)}: наслідки події «{ev.get('title', ev.get('key'))}» застосовано."
    sev = _int(ev.get("sev", 1), 1, 1, 3)
    sim.log("event_choice", text, event=ev.get("key"), choice=choice_id, uid=uid, states=states, sev=sev)
    ev["resolved"] = True
    ev["resolved_choice"] = choice_id
    active.remove(ev)
    return True


# ---------------------------------------------------------------- хендлери
def h_drought(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_agri", 1 - 0.12 * sev, dur, "drought")
    text = f"{SEV_WORD[sev].capitalize()} посуха в державі {sim.sname(s)}: врожаї впадуть на {int(12*sev)} % ({dur} міс.)."
    _record(sim, "drought", "state", sim.sname(s), sev, dur, text, [s])


def h_flood(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_agri", 1 - 0.09 * sev, dur, "flood")
    sim.add_mod("state", s, "rebuild", 1 + 0.5 * sev, dur + 3, "flood")
    sim.add_mod("state", s, "mort", 0.0006 * sev, dur, "flood", kind="add")
    _record(sim, "flood", "state", sim.sname(s), sev, dur,
            f"Повінь у державі {sim.sname(s)} ({SEV_WORD[sev]}): знищені поля й мости, зростає попит на будматеріали.", [s])


def h_bumper(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_agri", 1 + 0.12 * sev, dur, "bumper")
    _record(sim, "bumper_harvest", "state", sim.sname(s), sev, dur,
            f"Рясний врожай у державі {sim.sname(s)}: ціни на їжу підуть донизу.", [s])


def h_locusts(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_agri", 1 - 0.17 * sev, dur, "locusts")
    sim.add_mod("state", s, "stab", -1.5 * sev, dur, "locusts", kind="add")
    _record(sim, "locusts", "state", sim.sname(s), sev, dur, f"Нашестя сарани в державі {sim.sname(s)}: поля спустошені.", [s])


def h_winter(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "util_need", 1 + 0.3 * sev, dur, "winter")
    sim.add_mod("state", s, "mort", 0.0008 * sev, dur, "winter", kind="add")
    sim.add_mod("state", s, "prod_agri", 1 - 0.05 * sev, dur, "winter")
    _record(sim, "harsh_winter", "state", sim.sname(s), sev, dur,
            f"Люта зима в державі {sim.sname(s)}: різко зростає попит на паливо й одяг.", [s])


def h_storm(sim, rng, mid, sev, dur):
    sim.add_mod("market", mid, "trade", 1 - 0.25 * sev, dur, "storm")
    m = sim.markets[mid]
    for g in STORM_GOODS:
        m["stock"][g] = m["stock"].get(g, 0.0) * (1 - 0.06 * sev)
    sid = sim.market_state[mid]
    _record(sim, "sea_storm", "market", m["uk"], sev, dur,
            f"Морська буря біля порту {m['uk']} ({sim.sname(sid)}): судна затримані, торгівля сповільнюється.", [sid])


def h_quake(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    b["pop"] *= 1 - 0.02 * sev
    sim.add_mod("burg", bid, "prod_all", 1 - 0.12 * sev, dur, "quake")
    sim.add_mod("burg", bid, "rebuild", 1 + 1.2 * sev, dur + 4, "quake")
    sim.add_mod("burg", bid, "mort", 0.002 * sev, 3, "quake", kind="add")
    _record(sim, "earthquake", "burg", sim.bname(bid), sev, dur,
            f"Землетрус у місті {sim.bname(bid)} ({sim.sname(b['state'])}): {SEV_WORD[sev]} руйнування.", [b["state"]], burg=bid)


def h_volcano(sim, rng, mk, sev, dur):
    near = [bid for bid, b in sim.burgs.items() if (b["x"] - mk["x"]) ** 2 + (b["y"] - mk["y"]) ** 2 < 60 ** 2]
    for bid in near:
        sim.add_mod("burg", bid, "prod_all", 1 - 0.18 * sev, dur, "volcano")
        sim.add_mod("burg", bid, "mort", 0.001 * sev, dur, "volcano", kind="add")
    sid = mk["state"]
    sim.add_mod("state", sid, "prod_agri", 1 - 0.07 * sev, dur, "ash")
    _record(sim, "volcano", "marker", mk["name"], sev, dur,
            f"Виверження вулкана {mk['name']}: попіл накрив {len(near)} міст держави {sim.sname(sid)}.", [sid])


def h_wildfire(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    m = sim.markets[b["market"]]
    m["stock"][GOOD_WOOD] = m["stock"].get(GOOD_WOOD, 0.0) * (1 - 0.25 * sev)
    sim.add_mod("burg", bid, "prod_all", 1 - 0.1 * sev, dur, "fire")
    sim.add_mod("burg", bid, "rebuild", 1 + 0.8 * sev, dur + 3, "fire")
    _record(sim, "wildfire", "burg", sim.bname(bid), sev, dur,
            f"Велика пожежа у {sim.bname(bid)} ({sim.sname(b['state'])}): згоріли склади деревини.", [b["state"]], burg=bid)


def h_plague(sim, rng, mid, sev, dur):
    t = sim.tick_index()
    eps = sim.w.setdefault("epidemics", [])
    if len(eps) >= 2:
        return False
    imm = sim.w.setdefault("market_immunity", {})
    if imm.get(mid, -1) > t or any(mid in ep.get("markets", {}) for ep in eps):
        cand = [m for m in sim.markets if imm.get(m, -1) <= t and all(m not in ep.get("markets", {}) for ep in eps)]
        if not cand:
            return False
        mid = rng.choice(cand)
    max_mk = 3 + sev * 3
    ep = dict(
        id=int(sim.w.get("_ep_seq", 0)) + 1,
        sev=sev,
        markets={mid: 0.85},
        visited=[mid],
        max_markets=max_mk,
        name=rng.choice(["Сіра пошесть", "Червоний кашель", "Чорна лихоманка", "Жовта волога", "Пошесть Трьох Місяців"]),
        start=t,
        end=t + dur + 2,
    )
    sim.w["_ep_seq"] = ep["id"]
    eps.append(ep)
    imm[mid] = t + dur + 24
    m = sim.markets[mid]
    sid = sim.market_state[mid]
    _record(sim, "plague", "market", m["uk"], sev, dur,
            f"У {m['uk']} ({sim.sname(sid)}) спалахнула епідемія «{ep['name']}» ({SEV_WORD[sev]}).", [sid], market=mid)


def step_epidemics(sim, rng):
    w = sim.w
    t = sim.tick_index()
    imm = w.setdefault("market_immunity", {})
    for k in [k for k, until in imm.items() if until <= t]:
        del imm[k]
    eps = w.get("epidemics", [])
    for ep in list(eps):
        if t > ep.get("end", t) + 4:
            eps.remove(ep)
            sim.log("disease", f"Епідемія «{ep['name']}» згасла.", sev=1)
            continue
        visited = set(ep.get("visited") or ep["markets"].keys())
        max_mk = int(ep.get("max_markets", 3 + ep.get("sev", 2) * 3))
        new = {}
        for mid, inten in list(ep["markets"].items()):
            if mid not in sim.markets:
                continue
            m = sim.markets[mid]
            sim.add_mod("market", mid, "mort", 0.0012 * ep["sev"] * inten, 1, "plague", kind="add")
            sim.add_mod("market", mid, "trade", 1 - 0.20 * inten, 1, "quarantine")
            if t < ep["end"] and inten >= 0.30 and (len(visited) + len(new)) < max_mk:
                for ei in m["edges"]:
                    if (len(visited) + len(new)) >= max_mk:
                        break
                    e = sim.edges[ei]
                    other = e["b"] if e["a"] == mid else e["a"]
                    if other in ep["markets"] or other in new or other in visited or imm.get(other, -1) > t:
                        continue
                    if sim.at_war(sim.market_state[mid], sim.market_state[other]):
                        continue
                    flow_f = clamp(math.log1p(max(e.get("flow", 0.0), 0.0)) / 10.0, 0.15, 0.85)
                    sea_f = 0.45 if e.get("sea") else 1.0
                    if rng.random() < 0.055 * inten * flow_f * sea_f:
                        new[other] = round(inten * 0.65, 3)
                        visited.add(other)
                        imm[other] = t + 24
                        sim.log("disease", f"Епідемія «{ep['name']}» дісталася {sim.markets[other]['uk']}.", market=other,
                                states=[sim.market_state[other]], sev=2)
            ep["markets"][mid] = inten * (0.72 if t < ep["end"] else 0.45)
        ep["markets"].update(new)
        ep["visited"] = list(visited)
        ep["markets"] = {k: v for k, v in ep["markets"].items() if v > 0.10}
        if not ep["markets"]:
            eps.remove(ep)
            sim.log("disease", f"Епідемія «{ep['name']}» згасла.", sev=1)


def h_murrain(sim, rng, s, sev, dur):
    for g in MURRAIN_GOODS:
        sim.add_mod("state", s, f"prod_g{g}", 1 - 0.2 * sev, dur, "murrain")
    _record(sim, "cattle_murrain", "state", sim.sname(s), sev, dur,
            f"Мор худоби в державі {sim.sname(s)}: дорожчають м'ясо, шкіра, коні.", [s])


def h_goldrush(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    if GOOD_GOLD not in b["raw"]:
        b["raw"][GOOD_GOLD] = 0.4
    sim.add_mod("burg", bid, f"prod_g{GOOD_GOLD}", 1 + 0.7 * sev, dur, "goldrush")
    sim.add_mod("burg", bid, "pop_growth", 1.5, dur, "goldrush")
    _record(sim, "gold_rush", "burg", sim.bname(bid), sev, dur,
            f"Золота лихоманка біля {sim.bname(bid)} ({sim.sname(b['state'])}): старателі стікаються до нових розсипів.",
            [b["state"]], burg=bid)


def h_mine(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    for g in MINE_GOODS:
        sim.add_mod("burg", bid, f"prod_g{g}", 1 - 0.3 * sev, dur, "mine")
    sim.add_mod("burg", bid, "mort", 0.001 * sev, 2, "mine", kind="add")
    _record(sim, "mine_collapse", "burg", sim.bname(bid), sev, dur,
            f"Обвал у копальнях {sim.bname(bid)} ({sim.sname(b['state'])}): видобуток руди зупинено.", [b["state"]], burg=bid)


def h_piracy(sim, rng, mid, sev, dur):
    m = sim.markets[mid]
    cnt = 0
    for ei in m["edges"]:
        if sim.edges[ei]["sea"]:
            sim.add_mod("edge", ei, "piracy", 1 - 0.28 * sev, dur, "piracy")
            cnt += 1
    sid = sim.market_state[mid]
    _record(sim, "piracy_surge", "market", m["uk"], sev, dur,
            f"Сплеск піратства біля {m['uk']} ({sim.sname(sid)}): під ударом {cnt} морських маршрутів.", [sid], market=mid)


def h_bandits(sim, rng, s, sev, dur):
    for mid in [m for m, st in sim.market_state.items() if st == s]:
        sim.add_mod("market", mid, "trade", 1 - 0.14 * sev, dur, "bandits")
    _record(sim, "bandit_roads", "state", sim.sname(s), sev, dur,
            f"Розбійники на шляхах держави {sim.sname(s)}: купці вимагають ескорту, торгівля сповільнюється.", [s])


def h_panic(sim, rng, mid, sev, dur):
    goods = list(sim.goods)
    if len(goods) < 3:
        return False
    m = sim.markets[mid]
    gs = rng.sample(goods, 3)
    for g in gs:
        sim.add_mod("market", mid, f"price_g{g}", 1 + 0.4 * sev, dur, "panic")
    sid = sim.market_state[mid]
    _record(sim, "market_panic", "market", m["uk"], sev, dur,
            f"Паніка на ринку {m['uk']}: скупка ({', '.join(LD.good_uk(g, sim.goods) for g in gs)}) розганяє ціни.", [sid], market=mid)


def h_strike(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    sim.add_mod("burg", bid, "prod_all", 1 - 0.3 * sev, dur, "strike")
    _record(sim, "guild_strike", "burg", sim.bname(bid), sev, dur,
            f"Ремісники {sim.bname(bid)} ({sim.sname(b['state'])}) оголосили страйк.", [b["state"]], burg=bid)


def h_boom(sim, rng, mid, sev, dur):
    m = sim.markets[mid]
    sim.add_mod("market", mid, "trade", 1 + 0.3 * sev, dur, "boom")
    sid = sim.market_state[mid]
    sim.states[sid]["income_once"] = sim.states[sid].get("income_once", 0.0) + sim.states[sid]["rev0"] * 0.05 * sev
    _record(sim, "trade_boom", "market", m["uk"], sev, dur, f"Торговий бум на ринку {m['uk']} ({sim.sname(sid)}).", [sid], market=mid)


def h_tech(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_all", 1 + 0.03 * sev, dur, "tech")
    _bump_tech(sim, s, 1 + 0.02 * sev)
    _record(sim, "tech_advance", "state", sim.sname(s), sev, dur,
            f"Майстри держави {sim.sname(s)} зробили відкриття: зростає продуктивність ремесел.", [s])


def h_caravan(sim, rng, ei, sev, dur):
    e = sim.edges[ei]
    sim.add_mod("edge", ei, "trade", 0.4, dur, "caravan")
    a, b = sim.markets[e["a"]], sim.markets[e["b"]]
    _record(sim, "caravan_lost", "edge", f"{a['uk']}–{b['uk']}", sev, dur,
            f"Пограбовано великий караван між {a['uk']} та {b['uk']}.", [sim.market_state[e["a"]], sim.market_state[e["b"]]])


def h_succession(sim, rng, s, sev, dur):
    st = sim.states[s]
    sim.add_mod("state", s, "stab", -3 * sev, dur, "succession", kind="add")
    st["legitimacy"] = clamp(st["legitimacy"] - 6 * sev, 10, 100)
    _record(sim, "succession_crisis", "state", st["uk"], sev, dur, f"Криза престолонаслідування в державі {st['uk']}.", [s])


def h_conspiracy(sim, rng, s, sev, dur):
    st = sim.states[s]
    sim.add_mod("state", s, "stab", -2 * sev, dur, "conspiracy", kind="add")
    _record(sim, "noble_conspiracy", "state", st["uk"], sev, dur, f"Змова знаті в державі {st['uk']} загрожує двору.", [s])
    if sev == 3 and rng.random() < 0.3:
        fire(sim, rng, "coup", target=s, sev=2, _nested=True)


def h_revolt(sim, rng, s, sev, dur):
    st = sim.states[s]
    bl = sim.state_burgs.get(s, [])
    if not bl:
        return False
    for bid in rng.sample(bl, min(len(bl), 2 + sev)):
        sim.add_mod("burg", bid, "prod_all", 1 - 0.1 * sev, dur, "revolt")
    sim.add_mod("state", s, "stab", -2 * sev, dur, "revolt", kind="add")
    for u in st["army"]:
        st["army"][u] = int(st["army"][u] * (1 - 0.02 * sev))
    _record(sim, "peasant_revolt", "state", st["uk"], sev, dur, f"Селянський заколот у державі {st['uk']} ({SEV_WORD[sev]}).", [s])
    if sev == 3 and st["stability"] < 35 and len(bl) > 4 and rng.random() < 0.4:
        cands = [b for b in bl if not sim.burgs[b]["capital"]]
        if cands:
            secede(sim, rng, rng.choice(cands))


def secede(sim, rng, bid):
    """Відокремлення міста разом із провінцією, а не лише одного burg."""
    w = sim.w
    b = sim.burgs.get(bid)
    if not b or b["state"] not in sim.states:
        return None
    old = b["state"]
    so = sim.states[old]
    nid = max(sim.states) + 1 if sim.states else 1
    while nid in sim.states:
        nid += 1
    name = f"Вільне місто {b['uk']}"

    pr = sim.provinces.get(b.get("province"))
    transferred = list(pr.get("burgs", [])) if pr else []
    if bid not in transferred:
        transferred.append(bid)
    transfer_set = set(transferred)
    # Спочатку переносимо столицю старої держави, інакше вона "їде" разом із провінцією.
    old_cap = so.get("capital")
    if old_cap in transfer_set:
        remaining = [x for x in sim.state_burgs.get(old, []) if x not in transfer_set and x in sim.burgs]
        if remaining:
            new_cap_id = max(remaining, key=lambda x: (
                int(bool(sim.burgs[x].get("walls"))), int(bool(sim.burgs[x].get("citadel"))),
                _num(sim.burgs[x].get("pop", 0.0), 0.0)))
            cap_old = sim.burgs.get(old_cap)
            if cap_old:
                cap_old["capital"] = False
            sim.burgs[new_cap_id]["capital"] = True
            so["capital"] = new_cap_id
        else:
            cap_old = sim.burgs.get(old_cap)
            if cap_old:
                cap_old["capital"] = False
            so["capital"] = None

    rev0 = max(_num(so.get("rev0", 1.0), 1.0) * 0.02, 1.0)
    scale = clamp(rev0 / max(_num(so.get("rev0", 1.0), 1.0), 1.0), 0.005, 0.25)
    army = {u: max(1, int(n * scale)) for u, n in so.get("army", {}).items() if n > 0}
    if not army:
        army = {"infantry": max(20, int(200 * scale))}
    army0 = dict(army)
    raw_up = sum(n * PO.UNIT_POWER.get(u, 1.0) for u, n in army.items())
    army_cost = (rev0 * 0.35 / raw_up) if raw_up > 0 else _num(so.get("army_cost", 0.0), 0.0)
    ns = copy.deepcopy(so)  # вкладені словники/списки не повинні бути спільними зі старою державою
    ns.update(id=nid, name=f"Free {b['name']}", full_name=f"Free City of {b['name']}", uk=name,
              prefix_uk="Вільне місто", capital=bid, neighbors=[old], army=army, army0=army0,
              army_cost=army_cost, rev0=rev0, treasury=rev0 * 6.0, debt=0.0,
              stability=55.0, legitimacy=60.0, war_exhaustion=0.0, truce={}, mercs=[],
              diplo_labels={}, known=False, form="Republic", extinct=False,
              ruler=dict(name="Міська рада", age=None, traits=["mercantile", "cautious"], collective=True),
              campaigns=[], income_once=0.0, alert=max(1.0, _num(so.get("alert", 1.0), 1.0)),
              prod_dev=_num(so.get("prod_dev", 1.0), 1.0), tech=_num(so.get("tech", 1.0), 1.0))
    ns["pop_cache"] = _num(b.get("pop", 0.0), 0.0) + _num(b.get("rural", 0.0), 0.0)
    w.setdefault("states", {})[nid] = ns
    sim.states = w["states"]

    # Провінція повністю переходить до нової держави разом із ядром.
    if pr:
        pr.update(state=nid, core_state=nid, occupied_by=None, siege=0.0, assimilation=0)
        gov = pr.get("governor")
        if isinstance(gov, dict):
            gov["loyalty"] = clamp(_num(gov.get("loyalty", 70.0), 70.0) + 10.0, 0.0, 100.0)
    for tb in transferred:
        tb_obj = sim.burgs.get(tb)
        if not tb_obj:
            continue
        tb_obj["state"] = nid
        tb_obj["core_state"] = nid
        tb_obj["occupied_by"] = None
        tb_obj["capital"] = (tb == bid)

    if nid not in so.get("neighbors", []):
        so["neighbors"] = list(so.get("neighbors", [])) + [nid]
    for s2 in sim.states:
        if s2 == nid:
            continue
        rel = -60 if s2 == old else rng.uniform(-10, 20)
        lo, hi = min(s2, nid), max(s2, nid)
        w.setdefault("relations", {}).setdefault(lo, {})[hi] = rel
    # Оновлюємо всі кеші володінь, щоб нова держава одразу мала провінцію/міста.
    sim.refresh_ownership()
    PO._ensure_valid_capitals(sim)
    PO.war_pairs(sim)
    PO.refresh_neighbors(sim)
    sim.log("politics", f"{b['uk']} та його провінція відокремились від {so['uk']} і проголосили Вільне місто!",
            states=[old, nid], sev=3)
    return nid


def h_wedding(sim, rng, pair, sev, dur):
    a, b = pair
    PO.rel_add(sim, a, b, 22)
    sim.add_mod("pair", (min(a, b), max(a, b)), "rel", 4.0, 12, "royal_wedding")
    sim.log("politics", f"Династичний шлюб між домами {sim.sname(a)} і {sim.sname(b)} зміцнює їхні відносини.", states=[a, b], sev=1, event="royal_wedding")


def h_incident(sim, rng, pair, sev, dur):
    a, b = pair
    PO.rel_add(sim, a, b, -7 * sev)
    sim.add_mod("pair", (min(a, b), max(a, b)), "rel", -3.0 * sev, 12, "border_incident")
    sim.log("politics", f"Прикордонний інцидент між {sim.sname(a)} і {sim.sname(b)} загострює напруженість.", states=[a, b], sev=sev, event="border_incident")


def h_embargo(sim, rng, pair, sev, dur):
    a, b = pair
    key = (min(a, b), max(a, b))
    sim.add_mod("pair", key, "embargo", 0.1, dur, "embargo")
    PO.rel_add(sim, a, b, -10)
    _record(sim, "trade_embargo", "pair", f"{sim.sname(a)}–{sim.sname(b)}", sev, dur,
            f"{sim.sname(a)} запроваджує торгове ембарго проти {sim.sname(b)} на {dur} міс.", [a, b])


def h_taxreform(sim, rng, s, sev, dur):
    st = sim.states[s]
    up = rng.random() < 0.5
    if up:
        st["tax_mult"] = clamp(st["tax_mult"] * 1.12, 0.6, 1.6)
        sim.add_mod("state", s, "stab", -2.0, 6, "taxreform", kind="add")
        txt = f"{st['uk']} підвищує податки (+12 %): казна зросте, невдоволення також."
    else:
        st["tax_mult"] = clamp(st["tax_mult"] * 0.9, 0.6, 1.6)
        sim.add_mod("state", s, "stab", 2.0, 6, "taxreform", kind="add")
        txt = f"{st['uk']} знижує податки (−10 %): населення полегшено зітхає."
    sim.log("politics", txt, state=s, states=[s], sev=1, event="tax_reform")


def h_coup(sim, rng, s, sev, dur):
    st = sim.states[s]
    r = st["ruler"]
    if not r["collective"]:
        from .worldgen import _make_name
        title = r["name"].split(" ")[0]
        r["name"] = f"{title} {_make_name(rng, st['culture_name'])}"
        r["age"] = rng.randint(24, 55)
    r["traits"] = rng.sample(LD.RANDOM_TRAIT_POOL, 2)
    st["legitimacy"] = clamp(st["legitimacy"] - 15, 5, 100)
    sim.add_mod("state", s, "stab", -5, dur, "coup", kind="add")
    _record(sim, "coup", "state", st["uk"], sev, dur, f"Державний переворот у {st['uk']}! До влади прийшов {r['name']}.", [s])


def _army_hit(sim, s, f):
    for u in sim.states[s]["army"]:
        sim.states[s]["army"][u] = int(sim.states[s]["army"][u] * (1 - f))


def h_horde(sim, rng, s, sev, dur):
    bl = sim.state_burgs.get(s, [])
    for bid in rng.sample(bl, min(len(bl), 1 + sev)) if bl else []:
        sim.add_mod("burg", bid, "prod_all", 1 - 0.12 * sev, dur, "horde")
        sim.add_mod("burg", bid, "mort", 0.0012 * sev, dur, "horde", kind="add")
    _army_hit(sim, s, 0.015 * sev)
    _record(sim, "monster_horde", "state", sim.sname(s), sev, dur,
            f"Орда монстрів вийшла з пустищ у державі {sim.sname(s)}; авантюристів кличуть на допомогу.", [s])


def h_breach(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    sim.add_mod("burg", bid, "prod_all", 1 - 0.1 * sev, dur, "breach")
    sim.add_mod("burg", bid, "mort", 0.001 * sev, dur, "breach", kind="add")
    loot = rng.random() < 0.3
    if loot:
        sim.states[b["state"]]["income_once"] = sim.states[b["state"]].get("income_once", 0.0) + sim.states[b["state"]]["rev0"] * 0.04 * sev
    _record(sim, "dungeon_breach", "burg", sim.bname(bid), sev, dur,
            f"Прорив підземелля поблизу {sim.bname(bid)} ({sim.sname(b['state'])})" + ("; здобичі вистачить, щоб поповнити казну." if loot else "."),
            [b["state"]], burg=bid)


def h_dragon(sim, rng, bid, sev, dur):
    b = sim.burgs[bid]
    b["pop"] *= 1 - 0.03 * sev
    sim.add_mod("burg", bid, "prod_all", 0.5, dur, "dragon")
    sim.add_mod("state", b["state"], "stab", -1.5 * sev, dur, "dragon", kind="add")
    colour = rng.choice(["червоний", "синій", "зелений", "чорний", "білий"])
    _record(sim, "dragon_attack", "burg", sim.bname(bid), sev, dur,
            f"{colour.capitalize()} дракон напав на {sim.bname(bid)} ({sim.sname(b['state'])}): виробництво паралізоване.",
            [b["state"]], burg=bid)


def h_mana(sim, rng, s, sev, dur):
    good = rng.random() < 0.6
    if good:
        sim.add_mod("state", s, "prod_all", 1 + 0.04 * sev, dur, "mana")
        txt = f"Сплеск мани над державою {sim.sname(s)}: магічні ремесла процвітають."
    else:
        sim.add_mod("state", s, "prod_all", 1 - 0.05 * sev, dur, "mana")
        sim.add_mod("state", s, "stab", -1.0 * sev, dur, "mana", kind="add")
        txt = f"Нестабільний сплеск мани в державі {sim.sname(s)}: аномалії зривають роботу майстерень."
    _record(sim, "mana_surge", "state", sim.sname(s), sev, dur, txt, [s])


def h_artifact(sim, rng, s, sev, dur):
    st = sim.states[s]
    st["income_once"] = st.get("income_once", 0.0) + st["rev0"] * 0.5
    st["legitimacy"] = clamp(st["legitimacy"] + 6, 0, 100)
    sim.add_mod("state", s, "war_power", 1.08, 12, "artifact_found")
    sim.log("magic", f"У державі {st['uk']} знайдено стародавній артефакт; двір отримав престиж і скарб.", states=[s], sev=2, event="artifact_found")


def h_undead(sim, rng, s, sev, dur):
    bl = sim.state_burgs.get(s, [])
    for bid in rng.sample(bl, min(len(bl), 1 + sev)) if bl else []:
        sim.add_mod("burg", bid, "prod_all", 1 - 0.1 * sev, dur, "undead")
        sim.add_mod("burg", bid, "mort", 0.0015 * sev, dur, "undead", kind="add")
    _army_hit(sim, s, 0.02 * sev)
    _record(sim, "undead_incursion", "state", sim.sname(s), sev, dur,
            f"Вторгнення нежиті в державі {sim.sname(s)}; Іконоборці й гарнізони тримають оборону.", [s])


def h_tower(sim, rng, s, sev, dur):
    sim.add_mod("state", s, "prod_all", 1 + 0.03 * sev, dur, "tower")
    _bump_tech(sim, s, 1 + 0.03 * sev)
    _record(sim, "tower_breakthrough", "state", sim.sname(s), sev, dur,
            f"Магічна башта держави {sim.sname(s)} зробила прорив: зростають продуктивність і військова міць.", [s])


def h_black_rust(sim, rng, s, sev, dur):
    for g in RUST_GOODS:
        sim.add_mod("state", s, f"prod_g{g}", 1 - 0.18 * sev, dur, "black_rust")
    sim.add_mod("state", s, "prod_all", 1 - 0.06 * sev, dur, "black_rust")
    _record(sim, "black_rust", "state", sim.sname(s), sev, dur,
            f"Спалах прокляття «Чорної Іржі» в державі {sim.sname(s)}: залізо, зброя та інструменти швидко псуються.", [s])


HANDLERS = {
    "drought": h_drought, "flood": h_flood, "bumper_harvest": h_bumper, "locusts": h_locusts, "harsh_winter": h_winter,
    "sea_storm": h_storm, "earthquake": h_quake, "volcano": h_volcano, "wildfire": h_wildfire, "plague": h_plague,
    "cattle_murrain": h_murrain, "gold_rush": h_goldrush, "mine_collapse": h_mine, "piracy_surge": h_piracy,
    "bandit_roads": h_bandits, "market_panic": h_panic, "guild_strike": h_strike, "trade_boom": h_boom,
    "tech_advance": h_tech, "caravan_lost": h_caravan, "succession_crisis": h_succession, "noble_conspiracy": h_conspiracy,
    "peasant_revolt": h_revolt, "royal_wedding": h_wedding, "border_incident": h_incident, "trade_embargo": h_embargo,
    "tax_reform": h_taxreform, "coup": h_coup, "monster_horde": h_horde, "dungeon_breach": h_breach,
    "dragon_attack": h_dragon, "mana_surge": h_mana, "artifact_found": h_artifact, "undead_incursion": h_undead,
    "tower_breakthrough": h_tower, "black_rust": h_black_rust,
}
