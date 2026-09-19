# 07. Чекпоинт, undo и распознавание no-op

- Уровень: **L2**
- Время: ~5 мин
- Инструменты: `code_editor` (write, replace, undo, read)
- Dangerous mode: не нужен

## Подготовка

Создай файл `project/state.txt`:

```
version = 1
mode = "safe"
```

## Задание

1. Замени `version = 1` на `version = 2`. В ответе найди путь `checkpoint`.
2. Откати правку через `action=undo` и подтверди, что файл вернулся к `version = 1`.
3. Сделай **правку без изменений**: `replace` `version = 1` на `version = 1`.
   Убедись, что инструмент честно сообщает отсутствие изменений.

## Критерии приёмки (проверь сам)

- [ ] После шага 1: `version = 2`, в ответе есть непустой `checkpoint`.
- [ ] После шага 2: файл снова `version = 1`, ответ `undo` содержит `"ok": true`.
- [ ] После шага 3: `"changed": false` (no-op распознан).
- [ ] Файл `state.txt` не содержит посторонних изменений.

## Формат отчёта

```
## Отчёт по задаче 07
- PASS/FAIL:
- Критерии:
  - [ ] replace → changed=true, checkpoint=...
  - [ ] undo → ok=true, read → version = 1
  - [ ] no-op replace → changed=false
- Использованные инструменты:
- Ошибки/тупики:
```
