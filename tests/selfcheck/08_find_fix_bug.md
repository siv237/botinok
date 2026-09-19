# 08. Найти и починить баг в наборе файлов

- Уровень: **L2**
- Время: ~6 мин
- Инструменты: `file_system` (grep, read), `code_editor` (replace)
- Dangerous mode: не нужен

## Подготовка

Создай файлы:

`project/util.py`
```python
def average(nums):
    if not nums:
        return 0
    return sum(nums) / len(nums) + 1


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
```

`project/SPEC.md`
```
# Спецификация util

- average(nums) — среднее арифметическое. Для пустого списка вернуть 0.
- clamp(value, low, high) — ограничить значение диапазоном [low, high].
```

`project/CHANGELOG.md`
```
# Changelog
- добавлен clamp
- добавлен average
```

## Задание

1. Сверь `util.py` со `SPEC.md` и найди расхождение.
2. Почини **только** баг, ничего больше не меняя.
3. Объясни, в чём была ошибка и как проверил исправление.

## Критерии приёмки (проверь сам)

- [ ] Баг найден: `average` прибавляет `+ 1` к среднему.
- [ ] Правка внесена через `code_editor replace` (или `apply`), `changed: true`.
- [ ] `clamp` не изменён; `SPEC.md`, `CHANGELOG.md` не изменены.
- [ ] Контрольное чтение `util.py` подтверждает `return sum(nums) / len(nums)`.
- [ ] В отчёте есть строчное доказательство (файл:строка) до и после.

## Формат отчёта

```
## Отчёт по задаче 08
- PASS/FAIL:
- Найденный баг: ... (строка N)
- Критерии:
  - [ ] replace, changed=true, read → исправлено
- Использованные инструменты:
- Ошибки/тупики:
```
