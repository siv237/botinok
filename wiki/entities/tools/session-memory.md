---
type: entity
tags: [tool, session, llm]
updated: 2026-09-18
sources: 3
status: stable
---

# Инструмент session_memory (архивариус-советник)

`tools/session_memory.py` → `session_memory_tool(...)`. **Протокольный доступ к истории сессии**: точные timestamps, строгий порядок ходов (`turn_id` 1..N), полные тексты, указатели на артефакты. Основной инструмент продолжения и поиска — вместо прямого чтения `context.json`/`response.md` через `file_system`. → `concepts/session_resume.md`, `entities/session_directory.md`

## Достоверность (`_confidence`)
Каждый ответ помечает природу данных, чтобы агент отличал точный результат от наметки:
- **EXACT** — `action=restore` из канонического снапшота `messages.json` (можно доверять как есть).
- **DERIVED** — реконструкция/группировка (`resume_brief`, `get_turn`, `turns`, `timeline`) из `context.json`.
- **HINT** — эвристика (`search`): регистр/стемминг/подстроки, требует перепроверки.

## Действия
- `restore` — **точное восстановление** контекста (`SessionManager.restore_session`): `messages.json` → EXACT, иначе `context.json` → DERIVED; флаг `stale`, если снапшот старше context.json (прерванный хвост).
- `resume_brief` — обзор для продолжения: статус (прервана/завершена), elapsed, исходная задача, последний **финальный** ответ целиком, последние ходы.
- `get_turn turn_id=… include_content=true` — полный ход (user/assistant/thinking, tool args/result/artifact).
- `search query=…` — гибкий поиск (см. ниже), плюс блок «где именно».
- `turns` / `timeline` / `summary` / `stats` / `filter` / `chain` — обзор и аналитика.
- `help` — справка «кто я и как со мной говорить».

## Прощающий синтаксис
- Синонимы: `brief|resume|continue → resume_brief`; `turn|get → get_turn`; `list → turns`; `find|grep → search`; `restore|rebuild|exact|load|snapshot → restore`; `help|?|actions → help`.
- Приведение типов (`turn_id="3"`), алиасы (`q`, `id`, `full`), пустой `action` → `resume_brief`.
- `get_turn` без id → последний ход; промах → ближайший с диапазоном; плохой `session_path` → последняя сессия (с пометкой).
- **Строгая неоднозначность**: неизвестный action не подменяется — возвращается `ambiguous=true` со списком кандидатов.
- Всегда добавляются `_meta` (сессия, диапазон ходов, последняя метка), `_advice` (совет) и `_next_actions` (готовые вызовы) — инструмент не «молчит».

## Поиск (гибкий, кириллица в приоритете)
- Нормализация: регистр, `ё→е`, пробелы, пунктуация.
- Части слов (подстроки) и грубый русский стеммер окончаний (`нагрузкой → нагрузк`).
- Мульти-токены; режимы `auto|all|any|regex`; при отсутствии полного совпадения — частичные с флагом `partial`.
- **Где именно**: построчный поиск по `response.md`, `thinking.md`, `tools.log`, `session_raw.log`, `context.json`, `messages.json` → `файл:строка [время]` + сниппет.

## Внутренняя модель
`ToolCall` (args, status, `result`, `artifact`) · `MessagePart` (полный content/thinking) · `Turn` (обмен: tool-раунды копятся, финальный ответ закрывает ход) · `SessionParser` (разбор `context.json`) · `SessionIndex` (word-index). Вывод: structured / markdown / json.

## Связи
Точное восстановление и resume — `concepts/session_resume.md`; сохранение данных — `entities/session_manager.md`; жизненный цикл — `concepts/session_lifecycle.md`.
