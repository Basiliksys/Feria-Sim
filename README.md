# Feria-Sim

Симуляція економіки, геополітики та подій для настільно-рольових кампаній **D&D** із підтримкою карт **[Azgaar Fantasy Map Generator](https://azgaar.github.io/Fantasy-Map-Generator/)** (`.map`, `.map.gz`, `.json`), інтерактивною веб-панеллю, CLI та експортом нотаток до **Obsidian**.

Працює на **Python 3.12+** виключно на стандартній бібліотеці — без сторонніх залежностей.

---

## Основні можливості

- **Економічне ядро ([`feria_sim/engine.py`](feria_sim/engine.py), [`feria_sim/worldgen.py`](feria_sim/worldgen.py))**: 71 товар, динамічний вибір рецептів за цінами, видобуток за біомами й родовищами, міжринкова торгівля з обмеженим капіталом і захистом від перепродажу, пружний попит, сезонність, обмежена ємність середовища та калібрування економіки на будь-якій карті.
- **Налаштування й паки вмісту ([`data/content_pack.json`](data/content_pack.json))**: ключі `world.config` (`price_elasticity`, `carry_cap`, `tech_cap`, `tech_decay`, `max_events_per_month`, `event_scale_by_size`, `neighbor_drift`, `army_recovery_rate`, `trade_budget_factor`, `guild_invest_rate`, `demand_elasticity_enabled`, `dynamic_recipes`, `capital_constraint`), ваги подій і перевизначення товарів за ID.
- **Політика й події ([`feria_sim/politics.py`](feria_sim/politics.py), [`feria_sim/events.py`](feria_sim/events.py))**: бюджети, податки, армії, перемир'я, дипломатія, війни, облоги, анексії з асиміляцією, відокремлення провінцій, найманці, гільдійні позики, ордени, обмежений і занепадний технологічний прогрес, 36 типів подій із варіантами рішень для ГМ.
- **D&D-інструменти Майстра гри ([`feria_sim/dnd_tools.py`](feria_sim/dnd_tools.py))**:
  - роздрібні ціни з урахуванням податків, війни та «Чорної Іржі», із скінченним запасом і купівлею (`пм / зм / см / мм`);
  - калькулятор маршрутів (пішки, возом, верхи, кораблем), де небезпека впливає на час, вартість і добір зустрічей;
  - дошка квестів із прийняттям, виконанням і спливанням термінів, виплата нагороди з казни;
  - генератор NPC і фракцій на основі культури, подій і поточних чуток.
- **Веб-панель ([`feria_sim/web.py`](feria_sim/web.py), [`feria_sim/ui.html`](feria_sim/ui.html))**: векторна карта як головний екран, теплові шари (політика, провінції, їжа, стабільність, багатство, війна, задоволеність, лояльність, торгівля, дефіцит), часові графіки, редактор конфігурації, вибір подій, квестова дошка, крамниця, генератор NPC, слоти, fork і Undo.
- **Експорт до Obsidian ([`feria_sim/report.py`](feria_sim/report.py))**: `Дашборд.md`, `Наступна сесія.md`, паспорти держав/ринків/товарів, хроніка, а також нотатки «Квести», «Маршрути та небезпека», «Персонажі та фракції». Правила генеруються з поточного світу; чужі `.md`-файли не видаляються.

---

## Швидкий старт

```powershell
# 1. Ініціалізувати світ з карти Azgaar (.map / .json)
python -m feria_sim init --map "шлях\до\карти.map" --year 1250 --era Н.Е.

# 2. Запустити веб-панель у браузері (http://127.0.0.1:8765/)
python -m feria_sim serve
```

Шлях до карти за замовчуванням можна задати через `FERIA_MAP` або `FERIA_DEFAULT_MAP`; інакше використовується остання збережена карта в `save/maps/`, а застарілий шлях з `Downloads` — лише якщо файл існує.

### Корисні CLI-команди

```powershell
python -m feria_sim status                          # зведення світу та війн
python -m feria_sim run --months 3 --report         # прокрутити 3 місяці й оновити Obsidian
python -m feria_sim retail Несплоі                  # роздрібні D&D-ціни у місті
python -m feria_sim shop Несплоі longsword --qty 1  # купити товар із ринкового запасу
python -m feria_sim route Несплоі Буранвіле --mode horse
python -m feria_sim quests                          # квестові гачки
python -m feria_sim quests accept <ID>              # прийняти квест
python -m feria_sim quests complete <ID>            # закрити квест
python -m feria_sim npc --state "Королівство" --role купець
python -m feria_sim choice <UID> <CHOICE_ID>        # вибрати варіант події
python -m feria_sim config get event_rate           # переглянути ключ конфігурації
python -m feria_sim config set carry_cap 1.8        # змінити ключ конфігурації
python -m feria_sim declare 1 2                     # оголосити війну
python -m feria_sim peace 1 2                       # укласти мир
python -m feria_sim fork "Що якщо"                  # створити вітку світу
python -m feria_sim undo                            # відкотити останній крок
```

Мутуючі команди підтримують Undo так само, як веб-панель.

---

## Тести

```powershell
python -m unittest discover -s tests -v
```
