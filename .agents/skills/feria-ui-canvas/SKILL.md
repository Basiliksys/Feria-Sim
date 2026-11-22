---
name: feria-ui-canvas
description: >-
  Use when editing feria_sim/ui.html or /api/map_geo contracts to preserve XSS escaping,
  Canvas offscreen layer caching, province polygon hit-testing, and responsive map rendering.
---

# Feria UI & Canvas Workflow

Правила безпечної та продуктивної роботи з фронтендом `feria_sim/ui.html`.

## Обов'язкові правила

1. **XSS-безпека**: будь-які рядки світу (`uk`, `name`, `lore`, `governor`, `specialty`, назви подій/товарів) перед вставкою у шаблонний HTML пропускати через `escHtml(...)` (і уникати сирих рядків у `onclick="..."`).
2. **Контракт `/api/map_geo`**: зберігати ключі `has_svg`, `land`, `states`, `borders`, `prov_borders`, `prov_bodies`, `rivers`, `lakes`.
3. **Продуктивність Canvas**:
   - Не перебудовувати об'єкти `Path2D` у `drawMap()` — компілювати їх один раз у `loadGeo()`.
   - Статичний шар (`land`, `states`, `prov_bodies`, `lakes`, `rivers`, `borders`, `provBorders`) кешувати в offscreen-canvas при незмінному режимі/зумі/DATA, перемальовуючи лише оверлеї під час pan/hover.
4. **Перевірка**: прогнати `python -m unittest tests.test_feria_sim.TestFeriaSim.test_ui_templates_escape_dynamic_values tests.test_feria_sim.TestFeriaSim.test_web_http_endpoints -v`.
