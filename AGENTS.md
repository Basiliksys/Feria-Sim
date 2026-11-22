# AGENTS.md — Інструкції та швидкий контекст для ШІ-агентів (Feria-Sim)

Цей файл — головна точка входу для будь-якого ШІ-агента, що працює з **Feria-Sim**.
Детальні схеми даних, формули балансу, повний перелік API та CLI див. у [docs/AI_CONTEXT.md](docs/AI_CONTEXT.md).

---

## 1. Суть проєкту та обмеження

- **Що це**: економіко-геополітичний симулятор світу (Ферія або довільна карта Azgaar FMG `.map` / `.map.gz` / `.json`) + інструментарій Майстра гри D&D (роздрібні ціни, маршрути, квести, NPC, крамниця) + веб-панель (`ui.html`) + експорт до Obsidian.
- **Стек**: **Python 3.12+ лише стандартна бібліотека (базовий режим)** + опціональні прискорювачі через `pyproject.toml` (`[fast]`: `orjson`, `numpy`; `[geo]`: `lxml`, `shapely`; `[web]`: `pydantic`; `[dev]`: `pytest`, `ruff`). Усе має 100% stdlib-фолбек.
- **Мова**: весь UI, звіти Obsidian, CLI-вивід, події журналу та відповіді користувачу — **українською мовою**.

---

## 2. Основні команди (перевірка та запуск)

Виконувати з кореня репозиторію `Feria-Sim/`:

```powershell
# Повний набір автотестів (обов'язково після будь-яких правок; сумісно з unittest і pytest)
python -m unittest discover -s tests -v
pytest -v

# Лінтинг й перевірка синхронності контексту
ruff check --select E9,F,B feria_sim tests
python .agents/skills/feria-context-sync/scripts/check_context.py

# Переініціалізація світу з .map (генерує save/world.json і save/map_geo.json)
python -m feria_sim init

# Прогін симуляції й оновлення Obsidian-нотаток
python -m feria_sim run --months 3 --report

# Веб-панель (локально 127.0.0.1:8765)
python -m feria_sim serve --no-browser
```

---

## 3. Карта файлів проєкту

| Файл | Відповідальність | Деталі |
|---|---|---|
| `feria_sim/_accel.py` | Опціональний шар прискорення й валідації (`orjson`, `numpy`, `lxml`, `shapely`, `pydantic`) із суворим stdlib-фолбеком та `assert_finite()` | Єдина точка опціональних імпортів |
| `feria_sim/engine.py` | Клас `Sim`, тик (`tick()`), виробництво, попарна торгівля, каравани, споживання, ціни, населення, історія, `_intkeys`, `save_world` / `load_world` | Ядро економіки та міграції старих сейвів |
| `feria_sim/importer.py` | Парсер Azgaar `.map`, `.map.gz`, FMG JSON, синтез економіки для ванільних карт, екстрактор SVG/hull у `map_geo.json` (включно з `prov_borders`) | Вхід із карт |
| `feria_sim/geography.py` | Похідна географія (`world["geography"]`): кліматичні пояси (`polar/cold/temperate/tropical`), біом ринку, узбережжя/річки, регіональні сигнатури | Працює без збереження масиву клітинок |
| `feria_sim/routes.py` | Граф ринкових шляхів (`market_graph`, `shortest_path`), генератор магістралей (`generate_highways`, `world["trade_routes"]`) | Спільні дороги для караванів і D&D-маршрутів |
| `feria_sim/worldgen.py` | `build_world()`, застосування `data/content_pack.json`, `data/special_goods.json` (101..112), `data/overrides.json`, лор провінцій і намісники, `calibrate()` | Генерація й ідемпотентне калібрування |
| `feria_sim/politics.py` | Податки, фінанси, лояльність намісників і зради, дипломатія, AI-війни, облоги/окупація/анексія провінцій, найманці, правителі, Хрестовий похід | `step_finance`, `step_politics`, `end_war`, `annex_province` |
| `feria_sim/events.py` | 36 типів подій (`step_events`, `fire`), епідемії (`step_epidemics` + `market_immunity`), сецесія (`secede`), інтерактивні вибори ГМ (`apply_event_choice`) | Події та наслідки |
| `feria_sim/lore_data.py` | Назви товарів (`GOODS_UK`, `GOOD_IDS`), культурні склади імен, відомі держави Ферії, форми провінцій/титули намісників, `GOVERNOR_TRAITS`, `blazon_coa`, `EVENT_CHOICES` | Словники й лор |
| `feria_sim/dnd_tools.py` | Роздрібні ціни (`1 зм = 10 ср = 100 мм`), купівля зі складу (`purchase_shop_item`), калькулятор маршрутів (`travel_route`), квести (генерація + життєвий цикл), генератор NPC | D&D-шар для ГМ |
| `feria_sim/web.py` | Потокобезпечний `AppState`, Undo-стек (`save/undo/`), слоти/fork (`save/slots/`), локальний HTTP-сервер, валідація/CSP/Origin-захист | Усі `GET /api/*` і `POST /api/*` |
| `feria_sim/ui.html` | Однофайловий фронтенд (Canvas-карта з векторними контурами й шарами, таблиці, графіки, D&D-стіл, модалка провінції, редактор конфігу й overrides) | Без зовнішніх JS/CSS бібліотек |
| `feria_sim/report.py` | Атомарний експорт нотаток у Obsidian (`DnD1\D&D1\Симуляція`): дашборд, держави, провінції, ринки, квести, маршрути, NPC, правила | Не видаляє чужі `.md`-файли |
| `feria_sim/cli.py` | CLI-інтерфейс `python -m feria_sim ...` (ініціалізація, кроки, інспекція, `province`, `config`, `choice`, `npc`, `shop`, `fork`, `undo`) | Мутуючі команди пишуть в Undo через `AppState` |
| `data/content_pack.json` | Дефолтний пак конфігу (`world.config`), перевизначення товарів і ваг 36 подій | Змінюється без правки Python-коду |
| `data/special_goods.json` | Каталог 12 регіональних спецтоварів (`id` 101..112) із прив'язкою до поясів/біомів/портів/річок | Підключається при `worldgen` |
| `pyproject.toml` | Метадані пакета `feria-sim`, групи опціональних залежностей (`[fast]`, `[geo]`, `[web]`, `[dev]`, `[all]`), налаштування `pytest` і `ruff` | Працює і з `pip install -e .[all]`, і без нього |
| `.agents/skills/` | Локальні скіли для ШІ-агентів: `feria-context-sync`, `feria-perf-balance`, `feria-ui-canvas` (зі скриптами звірки й бенчмарку) | Автоматично підхоплюються агентами |
| `tests/test_feria_sim.py` | Регресійні та інтеграційні тести (`TestFeriaSim`: 31 тест) | Орієнтир усіх контрактів (`unittest` / `pytest`) |

Некомічені робочі директорії (у `.gitignore`): `save/` (`world.json`, `map_geo.json`, `journal.jsonl`, `maps/`, `slots/`, `undo/`).

---

## 4. Жорсткі інваріанти (не ламати при змінах!)

1. **JSON-ключі та числа**:
   - Після `json.load()` цілочисельні ID стають рядками — завжди пропускайте світ через `engine._intkeys(...)` (`load_world()` робить це автоматично).
   - Серіалізація тільки з `allow_nan=False` — не допускайте `NaN`/`Inf` у стані світу; використовуйте `_finite()`.
   - Усі записи у `save/`, `data/overrides.json`, Obsidian і `save/slots/` — атомарні (`.tmp` + `os.replace()`).
2. **Порядок `Sim.tick()`** ([engine.py](feria_sim/engine.py)):
   `events -> produce -> trade (_step_caravans -> _dispatch_caravans -> попарна торгівля) -> consume -> update_prices -> finance -> update_population -> politics -> record_history -> date`.
   - `e["flow"]` оновлюється **один раз** після проходу обох напрямків (`a→b` і `b→a`), щоб не було асиметрії за ID.
   - `trade_multiplier` і `capital_constraint` не можуть зробити `stock[g] < 0` або `capital < 0`; `imported_this_tick` забороняє миттєвий перепродаж у той самий місяць.
3. **Власність і провінції**:
   - При зміні `p["state"]` або `b["state"]` обов'язково викликайте `sim.refresh_ownership()`, `_ensure_valid_capitals(sim)` та `refresh_neighbors(sim)`.
   - Жодне місто не має залишатися без валідної провінції (`b["province"] in sim.provinces`).
4. **D&D і Web/UI контракти**:
   - `travel_route()` завжди повертає **рівно 3** елементи в `encounters`.
   - Роздрібні ціни D&D використовують курс `1 зм = 100 мм` (`fmt_mm`).
   - `/api/map_geo` зберігає очікуваний фронтендом і тестами контракт (`has_svg`, `land`, `states`, `borders`, `prov_borders`, `prov_bodies`, `rivers`, `lakes`).
   - У `ui.html` усі динамічні рядки перед вставкою в HTML/атрибути обов'язково екрануються (`escHtml()` / безпечні обробники), а на бекенді зберігається перевірка `Host`, `Origin`, `Sec-Fetch-Site`, `CSP` та containment шляхів (`_vault_target`, `SAFE_SLOT_ID`).
5. **Ідемпотентність калібрування та міграція старих сейвів**:
   - `worldgen.calibrate(sim)` працює на глибокій копії, не змінюючи дату/журнал/історію/капітали.
   - Старі збереження без `provinces`, `geography`, `trade_routes`, `caravans` або нових ключів `config` повинні відновлюватися в `Sim.build_runtime()` без винятків.

---

## 5. Протокол оновлення контексту для ШІ-агентів

Кожен агент, який змінює архітектуру, дані, API або механіки, **зобов'язаний оновити контекстні файли перед фінальною відповіддю/комітом**:

| Що змінено в коді | Що оновити в документації |
|---|---|
| Новий файл / модуль / `data/*.json` | Таблицю «Карта файлів» у `AGENTS.md` та відповідний розділ у `docs/AI_CONTEXT.md` |
| Ключ у `world["config"]` або `CONFIG_FIELDS` | Розділ конфігурації в `docs/AI_CONTEXT.md` і (якщо публічний) [README.md](README.md) |
| Нове поле у `world` / `state` / `province` / `burg` / `market` | Схему `world.json` у `docs/AI_CONTEXT.md` |
| Зміна логіки `tick()`, балансу, війн, подій | Розділ «Пайплайн тику та формули» у `docs/AI_CONTEXT.md` |
| Новий HTTP-маршрут у `web.py` або CLI-команда в `cli.py` | Таблиці API / CLI у `docs/AI_CONTEXT.md` (і `README.md`) |
| Зміна кількості або змісту тестів у `tests/` | Розділ перевірок у `AGENTS.md` / `docs/AI_CONTEXT.md` |

### Швидка перевірка актуальності контексту (для наступного агента)

Перед стартом роботи над новою фічею достатньо:
1. Прочитати `AGENTS.md` (цей файл) і потрібний розділ у `docs/AI_CONTEXT.md`.
2. Виконати `git log -n 5 --oneline` та `git status -s`, щоб звірити чи не з'явилися нові коміти після оновлення документації.
3. Прогнати `python -m unittest discover -s tests -v`.
