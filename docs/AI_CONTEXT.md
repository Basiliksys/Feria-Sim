# AI Context & Architecture Reference — Feria-Sim

Детальний технічний довідник для ШІ-агентів, щоб швидко відновлювати повну картину проєкту без повторного читання всіх вихідних файлів.

> Останнє оновлення контексту: після оптимізації стеку та геометрії (`pyproject.toml`, `_accel.py`, `lxml` + `shapely`, `gzip`, Canvas-кеш, `.agents/skills/`).

---

## 1. Архітектура та потік даних

```
Azgaar (.map / .map.gz / .json)
   │
   ▼  importer.py (import_map, extract_map_geometry)
Raw Import Dict  +  save/map_geo.json (SVG контури, prov_borders, hull фолбек)
   │
   ├──► data/content_pack.json (config, event_weights, goods overrides)
   ├──► data/special_goods.json (12 регіональних спецтоварів ID 101..112)
   ├──► data/overrides.json (ручні перейменування/лор держав, міст, провінцій)
   │
   ▼  worldgen.py (build_world, calibrate)
save/world.json (детермінований JSON-стан світу)
   │
   ▼  engine.Sim(world) ── 1 tick = 1 місяць
   ├──► events.py (36 подій, епідемії, сецесія, вибори ГМ)
   ├──► routes.py + engine.py (магістралі, каравани, попарна торгівля)
   ├──► politics.py (податки, намісники, дипломатія, облоги, анексії, реваншизм)
   ├──► geography.py (пояси широти, біоми, порт/річка, регіональні сигнатури)
   ├──► dnd_tools.py (крамниці, маршрути, дошка квестів, генератор NPC)
   ├──► web.py + ui.html (AppState, Undo/Slots/Fork, HTTP JSON API, Canvas UI)
   ├──► report.py (експорт в Obsidian vault DnD1\D&D1\Симуляція)
   └──► cli.py (python -m feria_sim <subcommand>)
```

---

## 2. Схема стану світу (`save/world.json`)

Після завантаження через `engine.load_world()` усі числові рядкові ключі JSON конвертуються в `int` функцією `_intkeys()`. Несеріалізовані тимчасові ключі `war_pairs` та `_new_journal` очищаються або відкидаються в `save_world()`.

### Кореневі ключі `world`

- `meta`: `{world_name, source_file, width, height, lat_n, lat_s, map_year, sim_seed, start_year, era, is_feria, has_native_economy, dist_unit, dist_scale}`
- `date`: `{year, month}` (`month` у діапазоні `1..12`)
- `config`: параметри балансу й прапорці фіч (синхронізовані між `engine.CONFIG_DEFAULTS`, `data/content_pack.json` та `web.CONFIG_FIELDS` / `CONFIG_BOOL_FIELDS`)
- `goods`: `{gid: {id, name, value, tags, unit, cover, recipes, chance, biome_out, cult_mult, [base, specialty, value_mult, origin]}}`
  - `1..71` — базові товари з `goods_default.json` (або з `.map`), `101..112` — регіональні спецтовари з `data/special_goods.json`.
- `markets`: `{mid: {id, center, name, uk, burgs, edges, stock, price, want, want_now, capital, shop_reserved}}`
- `burgs`: `{bid: {id, name, uk, state, core_state, occupied_by, province, market, x, y, pop, pop0, rural, capital, port, walls, citadel, culture, feature, cell, sat, raw, craft}}`
- `states`: `{sid: {id, name, full_name, uk, form, gov_text, prefix_uk, continent, color, coins, lore, known, capital, culture, culture_name, religion, religion_name, landmass, neighbors, army, army0, army_cost, mercs, treasury, treasury_map, debt, rev0, tax_mult, poll_tax, sales_tax, prod_dev, readiness, stability, legitimacy, war_exhaustion, tech, food_sat, lux_sat, pop, pop_cache, gdp, truce, ruler: {name, age, traits, collective}, diplo_labels}}`
- `provinces`: `{pid: {id, name, full_name, uk, form, form_uk, state, core_state, occupied_by, siege, assimilation, burg, burgs, color, pole, coa, blazon, specialty, lore, governor: {name, age, traits, loyalty}}}`
- `edges`: `[{a, b, dist, cap, sea, kind, pts, flow}]` — планарні географічні ребра між ринками (`kind`: `road | trail | sea | prospective`; `pts` — спрощена полілінія маршруту з `pack.routes` або пряма).
- `geography`: `{biomes, features, market_geo: {mid: {biome, feature, feature_name, lat, band, coast, river, province, region, specialties}}, regions: {pid: {name, state, center, markets, band, biome, coast, river, signature, specialties}}, derived}`
- `trade_routes`: `[{id, name, markets, edges, dist, cap, sea}]` — магістралі (`routes.ensure_highways`).
- `caravans`: `[{id, route_id, good, qty, unit_price, margin, origin, origin_market, origin_state, dest, at_market, leg_index, next_edge, eta_days, created_tick}]`
- `relations`: `{sid_a: {sid_b: score}}` (`a < b`, `score` в `-100..+100`), `vassals`: `[[vassal_sid, suzerain_sid]]`.
- `wars`: `[{id, name, attackers, defenders, score, exhaustion, start_year, start_month, captured, occupied_provs, casualties, log}]`; `war_history`: архів завершених війн.
- `guilds`, `mercs`, `orders`, `crusade`: економічні/військові організації та сценарій Четвертого Походу на Кірос (активний лише для Ферії).
- `mods`, `active_events`, `epidemics`, `market_immunity` (`{ep_key: until_tick}`), `quests` (`{active, completed, expired, seq}`), `npcs`, `journal` (керований ліміт записів + повний лог у `save/journal.jsonl`), `history` (`states`: останні 240 тіків; `world`: останні 1200 тіків).

### Геометрія карти (`save/map_geo.json`)

Структура для фронтенда:
`{has_svg, width, height, land: [path...], lakes: [path...], rivers: [path...], borders: [path...], prov_borders: [path...], prov_bodies: {pid: path}, states: {sid: path}}`
SVG витягується через `lxml.etree` (з виправленим stdlib regex-фолбеком), а полігони провінцій `prov_bodies` будуються через `shapely` (`polygonize` меж провінцій у межах `statesBody` + `voronoi_polygons` для незамкнених швів). Якщо SVG відсутній (наприклад, у FMG JSON), `importer.py` будує фолбек через опуклі оболонки міст (`_hull_path_from_burgs`).

---

## 3. Пайплайн місячного тику (`Sim.tick`) та ключові механіки

Кожен виклик `Sim.tick(politics=True, events=True, advance=True, finance=True)` виконується строго у такому порядку:

1. **Ініціалізація тіку та RNG**: `rng = random.Random(f"{self.seed}-{self.tick_index()}")`, індексація модифікаторів (`_index_mods()`), обнулення акумулятора `self.acc`.
2. **Події (`events.step_events`)**:
   - Бюджет подій на місяць масштабується залежно від кількості держав (`event_scale_by_size`, `max_events_per_month`), вибір події враховує `event_weights`.
   - **Епідемії (`step_epidemics`)**: відстежують відвідані ринки (`visited`) і виставляють імунітет `market_immunity`, щоб хвороба вигорала без нескінченного повторного зараження; обмежена тривалість запобігає вимиранню населення.
   - **Вибори ГМ (`EVENT_CHOICES` / `apply_event_choice`)**: вибрані події записують `uid` і дозволяють одноразово застосувати одне з двох політико-економічних рішень.
3. **Виробництво (`Sim.produce`)**:
   - Для кожного міста обчислюється базовий множник: `labor * stab_f * prod_dev * prov_f * mods` (де `prov_f` враховує риси намісника, `0.55` при окупації та `0.75` при облозі).
   - Сільгосптовари (`agri_goods`) множаться на сезонність за широтою (`season(month, lat)`).
   - Ремесло (`dynamic_recipes`) може динамічно обирати прибутковіший рецепт за поточними цінами; видобута/вироблена продукція поповнює `market["stock"]`.
4. **Торгівля та каравани (`Sim.trade`)**:
   - Спочатку просуваються фізичні каравани (`_step_caravans`): рухаються по ребрах магістралей (`trade_routes`), платять мита й ризикують втратою частини вантажу від піратства/розбою (`_caravan_hazard`), розвантажуються при перекритті маршруту війною (`_dump_caravan`) або прибутті (`_deliver_caravan`).
   - Далі запускаються нові каравани (`_dispatch_caravans`, ліміт `caravan_max_active`) за позитивної маржі між вузлами магістралей.
   - Потім працює попарна торгівля «остання миля» по `edges` (послаблена на `1 - caravan_share` для ребер магістралей). Капітал ринку й `trade_budget_factor` обмежують імпорт (`capital_constraint`), діє захист від миттєвого перепродажу (`imported_this_tick`), а `e["flow"]` оновлюється симетричною EMA **один раз після обох напрямків** (`0.7 * old + 0.3 * moved_edge`).
5. **Споживання (`Sim.consume`)**:
   - Міста та армія виставляють попит (`want_now`) у категоріях `food`, `utilities`, `construction`, `luxury` (плюс ціновий сигнал військового попиту `mil_demand_units`).
   - За `demand_elasticity_enabled` ціни вище базової стискають попит (`price_elasticity`).
   - Оновлюються `b["sat"]` та експоненційне ковзне середнє попиту `m["want"]`.
6. **Ціни й запаси (`Sim.update_prices`)**:
   - Псування запасів (`spoil`: `4%` для швидкопсувної їжі, `0.4%` для інших).
   - **Стеля зберігання**: `ceiling = max(target * 8.0, 50.0)` запобігає безмежному накопиченню дешевої сировини й витісненню інших товарів.
   - Ціна зсувається з коефіцієнтом `0.35` до `base * clamp(ratio, PMIN=0.30, PMAX=6.0)`.
7. **Фінанси (`politics.step_finance`)**:
   - Подушні й торгові податки, тарифи, утримання армії/найманців, банкрутство/позики у гільдій (`guild_invest_rate`).
   - Податкові риси намісників змінюють збори; за лояльності `< 40%` — саботаж зборів (`×0.70`); в окупованих провінціях `40%` податків іде окупанту.
8. **Населення (`Sim.update_population`)**:
   - Компенсаційне відновлення після воєн і епідемій при `ratio <= 1.0` та добрій `food_sat`; вище `ratio > 1.0` ріст плавно гальмується до повної стелі `carry_cap * pop0` (`carry_cap = 1.65`).
9. **Політика й війни (`politics.step_politics`)**:
   - `step_alert`, `step_governors` (динаміка лояльності, асиміляція `assimilation`, ризик зради/бунту), `step_diplomacy` (ребалансований дрейф до сусідів і повернення до середнього), `step_stability` (м'яка цільова легітимність від стабільності замість жорсткого кроку вниз), `step_army_recovery`, `step_declarations` (AI-війни з урахуванням `war_rate` і реваншизму за втрачений `core_state`), `step_wars` -> `step_provincial_front` (облоги, здачі міст при лояльності `< 25%`, окупація), `end_war` (`annex_province`, статус-кво повернення, `_ensure_valid_capitals`, `refresh_neighbors`), `step_mercs`, `step_rulers`, `step_crusade`, а також затухання технологій (`tech_cap`, `tech_decay`).
10. **Історія та дата**: `record_history()` (округлює GDP до `>= 0` для відображення) та зсув `date.month / date.year`.

---

## 4. Конфігурація та контент-паки (`data/`)

- **`data/content_pack.json`**: завантажується у `worldgen._apply_content_pack()`.
  - `config` ключі: `price_elasticity`, `carry_cap`, `tech_cap`, `tech_decay`, `max_events_per_month`, `event_scale_by_size`, `neighbor_drift`, `army_recovery_rate`, `trade_budget_factor`, `guild_invest_rate`, `demand_elasticity_enabled`, `dynamic_recipes`, `capital_constraint`.
  - У `engine.CONFIG_DEFAULTS` і `web.CONFIG_FIELDS` також доступні: `mil_k`, `mil_goods_per_head`, `event_rate`, `war_rate`, `caravan_enabled`, `caravan_share`, `caravan_max_active`, `caravan_hub_count`, `geography_enabled`, `special_goods_enabled`, `specialty_rate`, `craft_scale`, `transport_rate`, `birth`, `death`, `poll_k`, `admin_share`, `per_capita.*`.
- **`data/special_goods.json`**: 12 регіональних спецтоварів (`id` `101..112`, прив'язані до `origin`: `bands`, `biomes`, `coast`, `river`). Під час `worldgen._apply_special_goods()` частина базової сировини (`divert`) конвертується у спецтовар з `value = base_value * value_mult` і `cover = base_cover * value_mult`.
- **`data/overrides.json`** (створюється/правиться з UI або API): ручні правки `states`, `burgs` та `provinces` (`uk`, `governor`, `loyalty`, `specialty`, `lore`). Має ключі рівня світу (`by_world`) і глобальні/ферійські.

---

## 5. Веб-API, фронтенд і безпека (`web.py`, `ui.html`)

### HTTP Endpoints (`127.0.0.1:8765` за замовчуванням)

- **GET**:
  - `/` (`ui.html`), `/api/overview`, `/api/map_geo`, `/api/goods`, `/api/guilds`, `/api/journal?kind=&q=&limit=`
  - `/api/state?id=`, `/api/province?id=`, `/api/market?id=`
  - `/api/config`, `/api/event_choices`, `/api/slots`, `/api/job?id=`
  - `/api/retail?burg=` (та `/api/shop?burg=`), `/api/route?from=&to=&mode=`, `/api/quests?state=`, `/api/quest_board?state=`, `/api/npc`
- **POST**:
  - Симуляція та час: `/api/step`, `/api/step_async`, `/api/undo`, `/api/build_road`
  - Політика й події: `/api/fire`, `/api/declare`, `/api/peace`, `/api/set_state`, `/api/event_choice`, `/api/set_config`
  - D&D-шар: `/api/quest_accept`, `/api/quest_complete`, `/api/shop_buy`, `/api/npc`
  - Редактор / збереження / карти: `/api/override`, `/api/fork`, `/api/save_slot`, `/api/load_slot`, `/api/delete_slot`, `/api/report`, `/api/upload_map`, `/api/switch_map`

### Фронтенд (`ui.html`)

- **Карта (Canvas + Path2D + offscreen-кеш)**: режими `political`, `provinces` (заливні полігони `GEO.provBodies` за лояльністю / окупацією / переходом територій, облоги `⚔`, клікабельність будь-якої точки провінції), `food`, `stability`, `wealth`, `war`, `trade` (географічні торгові потоки по полілініях доріг/стежок/морських ліній + підсвічені пунктиром перспективні тракти `prospective_roads` з побудовою в 1 клік), а також шари задоволеності, лояльності, дефіциту, географії та маршрутів/караванів.
- **Продуктивність**: HTTP-відповіді `>= 1024 Б` стискаються через `gzip` при `Accept-Encoding: gzip`, рендер зуму/перетягування батчиться через `requestAnimationFrame` (`scheduleDrawMap`), статичний векторний шар кешується в `_geoLayerCache`, а тривалі прогони (`months >= 6`) використовують `/api/step_async` + опитування `/api/job`.
- **Вкладки / модалки**: Огляд і Держави (із таблицею провінцій та `#prov-modal`), Ринки й Товари, 🎲 D&D Стіл (крамниця з купівлею, маршрути, дошка квестів, NPC-генератор), Війни/Похід/Гільдії, Журнал і Керування ГМ (`config`, `event_choices`, `overrides`, `slots`/`fork`, імпорт карти).

### Заходи безпеки (`web.py`, `report.py`, `ui.html`)

- Сервер приймає запити лише з дозволених `Host` (включаючи IPv6 `[::1]:port` і `::1:port`), перевіряє `Origin` та `Sec-Fetch-Site` для `POST`, виставляє `CSP` і `X-Content-Type-Options: nosniff`, відхиляє `NaN`/`Infinity` у JSON-вході (`parse_constant=reject_constant`), обмежує розміри тіла (`24 МБ`) та розпакованої карти (`64 МБ`).
- Валідація імен слотів (`SAFE_SLOT_ID`) та карт (`SAFE_MAP_NAME`), containment шляхів у Obsidian (`_vault_target`), повне екранування в JS (`escHtml`).

---

## 6. CLI та Obsidian (`cli.py`, `report.py`)

### Команди CLI (`python -m feria_sim ...`)

- Ініціалізація та крок: `init`, `run`, `undo`, `fork <name>`
- Інспекція: `status`, `state <name>`, `city <name>`, `province <name>`, `price <good>`, `events`, `wars`, `report`
- Керування: `fire <key>`, `declare <a> <b>`, `peace <a> <b>`, `set <state> <field> <value>`, `choice <uid> <choice_id>`, `config get|set [key] [val]`
- D&D: `retail <city>`, `shop <city> <item> [--qty N]`, `route <src> <dst> [--mode foot|wagon|horse|ship]`, `quests [accept|complete] [id]`, `npc [--state] [--role]`
- Веб: `serve [--host] [--port] [--vault] [--no-browser]`

### Obsidian (`DnD1\D&D1\Симуляція`)

`report.write_all()` генерує/оновлює (лише керовані `.md`-файли): `Дашборд.md`, `Наступна сесія.md`, `Правила симуляції.md`, `Війни.md`, `Гільдії та найманці.md`, `Похід на Кірос.md`, `Квести.md`, `Маршрути та небезпека.md`, `Персонажі та фракції.md`, `Держави/*.md` (архівує ліквідовані), `Ринки/*.md`, `Товари/*.md`, `Журнал/*.md`.

---

## 7. Набір тестів (`tests/test_feria_sim.py`)

Усі **31** тестів запускаються командою `python -m unittest discover -s tests -v` або `pytest -v`:
- Імпорт/формати й SVG (`test_import_formats`), калібрування (`test_calibration_and_simulation_invariants`)
- D&D: роздріб/маршрути (`test_dnd_tools_retail_and_routes`), вибори подій/квести/крамниця (`test_event_choices_quest_lifecycle_and_shop_stock`)
- Конфіг/пак (`test_config_contract_and_content_pack`), CLI+Undo (`test_cli_new_commands_and_undo`), звіти Obsidian (`test_report_outputs_are_dynamic_and_keep_unknown_notes`)
- Веб/Слоти/Безпека (`test_overrides_undo_and_slots`, `test_web_http_endpoints`, `test_web_security_hardening`, `test_ui_templates_escape_dynamic_values`, `test_web_exposes_geography_and_specialties`)
- Баланс і регресії (`test_epidemic_burnout_and_population_recovery`, `test_trade_flow_symmetry`, `test_trade_multiplier_cap_keeps_stock_non_negative`, `test_long_horizon_invariants`, `test_long_horizon_balance_no_spiral_or_stock_dominance`, `test_ai_war_declarations_are_reachable`)
- Аудити безпеки/цілісності (`test_audit_core_safety`, `test_audit_politics_and_events_safety`, `test_audit_dnd_report_and_cli_safety`)
- Провінції та війна (`test_provinces_governors_and_territorial_war`)
- Географія, спецтовари, каравани (`test_caravan_highways_and_delivery`, `test_caravan_config_and_legacy_save`, `test_geography_registry`, `test_geography_legacy_save`, `test_corrupted_geography_is_rebuilt`, `test_special_goods_catalog_and_conversion`, `test_special_goods_can_be_disabled`).
- Прискорення та геометрія (`test_acceleration_geo_polygons_and_web_gzip` — `orjson`/`numpy`/`lxml`/`shapely` паритет, фікс самозакривних `<g .../>`, `prov_bodies`, `gzip` API, `/api/step_async`).
- Географічні торгові потоки та будівництво доріг (`test_geographic_edges_and_prospective_road_build` — планарний граф Габріеля, трасування `pack.routes`, апгрейд застарілих хорд, `recommend_roads`, `POST /api/build_road` + Undo).

---

## 8. Шпаргалка: як швидко оновити контекст

Коли завершуєте задачу в репозиторії:
1. Перевірте `git diff --stat`: якщо змінилися модулі, ключі `world.json`, `CONFIG_DEFAULTS`, HTTP-маршрути, CLI-команди чи кількість тестів — оновіть відповідний розділ у цьому файлі та рядок «Останнє оновлення контексту» вгорі.
2. Якщо додали новий незмінний інваріант (наприклад, правило серіалізації чи симетрії формули), додайте 1–2 рядки у розділ 4 файлу [AGENTS.md](../AGENTS.md).
3. Якщо додано нові налаштування в `data/` або CLI-команди для користувача — синхронізуйте також [README.md](../README.md).
4. Після правок проженіть `python -m unittest discover -s tests -v` та вкажіть у коміті оновлення документації разом із кодом.
