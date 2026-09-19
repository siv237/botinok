---
type: entity
tags: [tool, safety, dev]
updated: 2026-09-19
sources: 4
status: stable
---

# Инструмент code_editor (edit-кит)

`tools/code_editor.py` → функция `code_editor(...)`. Единый редактор файлов,
приведённый к «помогающей» парадигме (как `web` и `session_memory`).
Концепция — `concepts/edit_kit.md`.

## Действия
- `read` — чтение с пагинацией (`offset`/`limit`, `line_numbers`); в шапке
  `sha256`, `encoding`, `eol`, диапазон строк.
- `write` — полная запись (`content`); атомарно, сохраняет кодировку/EOL/BOM
  существующего файла.
- `replace` — одна замена `old_text → new_text` (`replace_all`); пустой
  `new_text` = удаление.
- `apply` — несколько замен за вызов: `edits=[{old_text,new_text,replace_all}]`,
  **атомарно** (всё или ничего).
- `undo` — откат последней правки из чекпоинта (`checkpoint` либо последний).
- `help` — справка.
- Прощающий ввод: алиасы (`edit→replace`, `patch→apply`, `revert/restore→undo`,
  `cat→read`), строковые числа, неизвестные аргументы игнорируются с пометкой
  `ignored_args`.

## Матчинг
- Точное вхождение — если ровно одно.
- Fuzzy-матчинг **построчный** (устойчив к сдвигу отступов, не страдает от
  auto-junk на частых символах), с нормализацией переводов строк и жёсткими
  лимитами (строк/длины фрагмента/числа сравнений) — процесс не подвисает.
- Не найдено — возвращает код `old_text_not_found`; если есть близкий кандидат
  (ratio ≥ 0.3) — блок `nearest` (строка, ratio, сниппет). Слишком большой
  фрагмент/файл помечается `fuzzy_skipped` вместо многоминутного скана.
- Более одного точного вхождения без `replace_all` — код `ambiguous` со списком
  кандидатов (`file:line`).

## Надёжность
- **Атомарная запись** `tmp` + `os.replace` (+ `fsync`).
- **Кодировки/EOL** сохраняются: utf-8/utf-8-sig/cp1251; LF, CRLF и CR.
  Смешанные переводы нормализуются к преобладающему с явной пометкой
  `eol_normalized=true` (не молча).
- **Чтение полное** (до `max_bytes`, по умолчанию 20 МБ), пагинация по строкам
  работает на всём файле; вывод обрезается отдельно с корректным `offset`.
- **Бинарные файлы** (NUL-байт) отклоняются с подсказкой про `file_system
  action=inspect`.
- **Стейл-контроль**: серверный стейт-хэш; файл, изменённый вне сессии,
  отклоняется (код `stale`) с советом перечитать. `expected_sha256` — усиленный
  контроль.
- **Чекпоинт** перед каждой мутацией в `<root>/.edit_backups/` (+ sidecar с
  ожидаемым `after_sha256`). `undo` тоже проверяет стейл; принудительно —
  `force=true`.
- **Алиасы действий** нормализуются в гейтах безопасности
  (`editor_action_of` в `core/tool_manager.py`), поэтому `save/edit/patch/...`
  не обходят подтверждение dangerous mode.

## Обратная связь
- JSON-ответ с `changed`, `before/after_sha256`, `bytes_before/after` и
  **unified `diff`** (обрезается по объёму).
- Каркас: `_meta`, `_provenance`, `_confidence` (EXACT/DERIVED/HINT),
  `_advice`, `_next_actions`. Совместим с `_compact_tool_message` (поля
  `path`/`changed`); крупные аргументы (`content`/`edits`) в UI скрываются.

## Безопасность
- `read` — всегда; мутации (`write`/`replace`/`apply`/`undo`) внутри
  `session_path` — без dangerous mode; **вне сессии** — требуется dangerous mode.
  → `concepts/dangerous_mode.md`
- Путь резолвится `_safe_path` (`realpath`, ограничение корнем); относительный
  путь приводится к `<session>/project/` через `core.path_utils.resolve_session_path`
  (ведущий `project/` не дублируется). При `dangerous_mode=True` ограничение
  снимается. Политика «внутри/вне» — `allowed_in_session`
  (`core/tool_manager.py`).

## Тесты
`tests/test_code_editor.py` — write/read, exact/fuzzy/ambiguous, apply-атомарность,
BOM/CRLF, stale, undo, binary, help, интеграция с `ToolManager`.

## Связи
`concepts/edit_kit.md`, `entities/tool_manager.md`, `concepts/dangerous_mode.md`,
`entities/botinok_cli.md`.
