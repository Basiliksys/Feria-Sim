---
name: feria-perf-balance
description: >-
  Use when optimizing Feria-Sim speed, I/O, caching, or economic/political balance
  to benchmark tick latency, save/load time, and long-horizon stability invariants.
---

# Feria Performance & Balance Profiler

Вимірює реальний час завантаження, збереження, кроків симуляції та перевіряє довгостроковий баланс світу.

## Кроки

1. Запустити бенчмарк (за наявності `save/world.json`):
   ```powershell
   python .agents/skills/feria-perf-balance/scripts/bench_tick.py
   ```
2. Запустити тести інваріантів балансу та прискорення:
   ```powershell
   python -m unittest discover -s tests -v
   ```
3. Якщо змінювався `importer.py` чи геометрія — перевірити `python -m feria_sim init` і переконатися, що всі міста мають валідні провінції (`orphans == 0`), а ціни й населення залишаються скінченними (`allow_nan=False`).
