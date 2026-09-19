# 11. Диагностика по логам: regex и агрегация

- Уровень: **L3**
- Время: ~7 мин
- Инструменты: `file_system` (grep, read)
- Dangerous mode: не нужен

## Подготовка

Создай файл `project/logs/app.log`:

```
2026-09-19 10:00:01 INFO  start
2026-09-19 10:00:02 INFO  loaded config
2026-09-19 10:00:03 WARN  cache miss key=user:1
2026-09-19 10:00:04 ERROR timeout calling db
2026-09-19 10:00:05 ERROR timeout calling db
2026-09-19 10:00:06 INFO  retry 1
2026-09-19 10:00:07 ERROR connection refused
2026-09-19 10:00:08 WARN  cache miss key=user:2
2026-09-19 10:00:09 ERROR timeout calling db
2026-09-19 10:00:10 INFO  ok
2026-09-19 10:00:11 ERROR disk full
2026-09-19 10:00:12 WARN  slow query 2.5s
2026-09-19 10:00:13 ERROR timeout calling db
2026-09-19 10:00:14 INFO  ok
2026-09-19 10:00:15 ERROR connection refused
2026-09-19 10:00:16 INFO  done
```

## Задание

1. Найди все строки уровня `ERROR` и `WARN` одним regex-запросом.
2. Посчитай: всего ERROR, всего WARN.
3. Определи самый частый **тип** ошибки (нормализуй текст: `timeout calling db`,
   `connection refused`, `disk full`) и назови его частоту и строки.
4. Скажи, сколько уникальных типов ошибок встречается.

## Критерии приёмки (проверь сам)

- [ ] Для поиска использован `grep` с regex `ERROR|WARN` (одним запросом).
- [ ] ERROR = 7, WARN = 3 (итого 10 строк уровня ERROR/WARN).
- [ ] Самый частый тип: `timeout calling db` — 4 раза, строки 4, 5, 9, 13.
- [ ] Уникальных типов ошибок = 3 (`timeout calling db`, `connection refused`,
      `disk full`).
- [ ] Числа подтверждены выводом инструмента (список строк), а не «на глаз».

## Формат отчёта

```
## Отчёт по задаче 11
- PASS/FAIL:
- Критерии:
  - [ ] grep "ERROR|WARN" → 10 строк (доказательство)
  - [ ] ERROR=7 WARN=3; top=timeout calling db (4: строки 4,5,9,13)
- Использованные инструменты:
- Ошибки/тупики:
```
