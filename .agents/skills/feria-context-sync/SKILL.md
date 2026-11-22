---
name: feria-context-sync
description: >-
  Use after any code or config change in Feria-Sim to verify and update AGENTS.md,
  docs/AI_CONTEXT.md, and README.md so AI agent context stays synchronized with the codebase.
---

# Feria Context Sync

Підтримує синхронність документації проєкту (`AGENTS.md`, `docs/AI_CONTEXT.md`, `README.md`) із фактичним кодом, тестами, маршрутами API та CLI-командами.

## Кроки перевірки й оновлення

1. Запустити скрипт звірки з кореня репозиторію `Feria-Sim`:
   ```powershell
   python .agents/skills/feria-context-sync/scripts/check_context.py
   ```
2. Порівняти вивід скрипта (кількість тестів, `CONFIG_DEFAULTS`, HTTP-ендпоїнти в `web.py`, CLI-команди в `cli.py`, поточний git-коміт) із розділами у `AGENTS.md` та `docs/AI_CONTEXT.md`.
3. Оновити таблиці модулів/API/CLI/конфігів та рядок `Останнє оновлення контексту` у `docs/AI_CONTEXT.md`, якщо є розбіжності.
4. Переконатися, що тести проходять (`python -m unittest discover -s tests -v`).
