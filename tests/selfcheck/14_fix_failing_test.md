# 14. Починить падающий тест по трассировке

- Уровень: **L4** (нужен dangerous mode)
- Время: ~12 мин
- Инструменты: `shell_exec` (run), `code_editor` (read/replace), `file_system` (grep)
- Dangerous mode: **да**

## Подготовка

Создай файлы:

`project/stats.py`
```python
def mean(values):
    return sum(values) / len(values)


def median(values):
    values = sorted(values)
    n = len(values)
    mid = n // 2
    if n % 2 == 0:
        return (values[mid - 1] + values[mid]) / 2
    return values[mid]


def mode(values):
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.get)
```

`project/test_stats.py`
```python
from stats import mean, median, mode

assert mean([1, 2, 3]) == 2
assert mean([2, 4]) == 3
assert median([1, 2, 3]) == 2
assert median([1, 2, 3, 4]) == 2.5
assert median([5]) == 5
assert mode([1, 1, 2]) == 1
assert mode([3, 3, 3]) == 3

print("OK")
```

## Задание

1. Запусти `project/test_stats.py` через `shell_exec`.
2. Найди падающее утверждение, по трассировке определи причину.
3. Почини **минимально** (не переписывая модуль целиком), перезапусти до зелёного.
4. Объясни корневую причину и что именно изменил.

## Критерии приёмки (проверь сам)

- [ ] Первый запуск показал падение с трассировкой (зафиксируй текст).
- [ ] Причина определена верно (например `median` для чётного/нечётного списка
      или `mode` при нескольких кандидатах).
- [ ] Правка внесена через `code_editor`, тест перезапущен и зелёный (`OK`, rc=0).
- [ ] Другие функции не сломаны: повторный полный прогон зелёный.
- [ ] В отчёте: трассировка до, причина, правка, вывод после.

## Формат отчёта

```
## Отчёт по задаче 14
- PASS/FAIL:
- Трассировка до: ...
- Корневая причина: ...
- Правка: replace ... → ...
- Вывод после: OK (rc=0)
- Использованные инструменты:
- Ошибки/тупики:
```
