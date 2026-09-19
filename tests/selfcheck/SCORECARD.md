# Scorecard — оценка прохождения самотестов

Заполняется человеком (или агентом-наблюдателем) по результатам отчётов модели.
Один прогон = один прогон набора; для надёжности полезно 3–5 прогонов.

## Шкала

- **PASS (2)** — все критерии выполнены, есть доказательства из инструментов.
- **PARTIAL (1)** — итог достигнут, но с лишними инструментами/обходами или без
  доказательств.
- **FAIL (0)** — критерий не выполнен или заявлен без подтверждения.

## Таблица прогона

| # | Задача | PASS/PARTIAL/FAIL | Вызовов инструментов | Ошибок инструментов | Лишние полные чтения | Комментарий |
|---|--------|-------------------|----------------------|---------------------|----------------------|-------------|
| 01 | read pagination | | | | | |
| 02 | grep file regex | | | | | |
| 03 | grep dir recursive | | | | | |
| 04 | replace exact | | | | | |
| 05 | apply multi | | | | | |
| 06 | fuzzy replace | | | | | |
| 07 | undo / no-op | | | | | |
| 08 | find & fix bug | | | | | |
| 09 | cross-file rename | | | | | |
| 10 | module from spec | | | | | |
| 11 | log diagnostics | | | | | |
| 12 | ambiguous recovery | | | | | |
| 13 | TDD roman | | | | | |
| 14 | fix failing test | | | | | |
| 15 | final miniproject | | | | | |

## Производные метрики

- **Score** = сумма баллов / 30.
- **Pass@1** — доля задач с PASS с первого прогона.
- **Pass^k** — доля задач, пройденных PASS во всех `k` прогонах (надёжность).
- **Tool precision** — доля вызовов, соответствующих назначению задачи.
- **Избыточность** — число вызовов на задачу против эталона (см. заметки ниже).

## Таксономия ошибок (по τ-bench-подходу)

- `wrong_tool` — вызван не тот инструмент (например `shell_exec` для чтения).
- `wrong_args` — неверные аргументы (путаница `pattern`/`content_query`,
  отсутствие `offset`).
- `unintended_action` — правка не того места / лишняя мутация.
- `goal_partial` — задача выполнена частично.

## Эталонные ориентиры (ожидаемый минимум вызовов)

| # | Задача | Ожидаемо вызовов | Ключевые инструменты |
|---|--------|------------------|----------------------|
| 01 | read pagination | 2–3 | code_editor read |
| 02 | grep file regex | 2–3 | file_system grep |
| 03 | grep dir recursive | 2–4 | file_system grep recursive |
| 04 | replace exact | 2–3 | code_editor replace |
| 05 | apply multi | 1–2 | code_editor apply |
| 06 | fuzzy replace | 2–3 | code_editor replace (fuzzy) |
| 07 | undo / no-op | 3–5 | code_editor replace/undo/read |
| 08 | find & fix bug | 4–6 | grep + read + replace |
| 09 | cross-file rename | 5–8 | grep + apply/replace |
| 10 | module from spec | 4–7 | code_editor write |
| 11 | log diagnostics | 3–5 | grep regex |
| 12 | ambiguous recovery | 4–7 | replace (ambiguous) + контекст |
| 13 | TDD roman | 8–12 | code_editor + shell_exec |
| 14 | fix failing test | 8–14 | shell_exec + read + replace |
| 15 | final miniproject | 20–35 | все инструменты |
