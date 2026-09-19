# 09. Кросс-файловое переименование

- Уровень: **L3**
- Время: ~7 мин
- Инструменты: `file_system` (grep), `code_editor` (apply/replace, read)
- Dangerous mode: не нужен

## Подготовка

Создай файлы:

`project/service.py`
```python
def fetch_data(url):
    return {"url": url, "status": "ok"}


def fetch_data_cached(url):
    return fetch_data(url)
```

`project/main.py`
```python
from service import fetch_data


def run():
    result = fetch_data("https://example.com")
    return result
```

`project/README.md`
```
Модуль service предоставляет fetch_data.
```

## Задание

Переименуй функцию `fetch_data` в `load_data` во **всех** файлах, где она
упоминается как отдельное имя (определение, вызов, импорт). Не трогай
`fetch_data_cached` и текст в README, если там не идёт речь именно о функции.

## Критерии приёмки (проверь сам)

- [ ] `grep` по `project/` для `fetch_data` **до** правки показал все вхождения.
- [ ] После правки: `grep` по `fetch_data` не находит **ничего**
      (`fetch_data_cached` при этом сохранён).
- [ ] В `service.py` определены `load_data` и `fetch_data_cached` (последняя
      вызывает `load_data`).
- [ ] В `main.py` импорт и вызов обновлены на `load_data`.
- [ ] Правки сделаны через `code_editor` (по возможности — `apply`), не через shell.

## Формат отчёта

```
## Отчёт по задаче 09
- PASS/FAIL:
- Критерии:
  - [ ] grep fetch_data до: ... ; после: "Совпадений не найдено"
  - [ ] read service.py/main.py → load_data
- Использованные инструменты:
- Ошибки/тупики:
```
