---
type: concept
tags: [tui, session]
updated: 2026-09-17
sources: 1
status: superseded
---

# Бесконечная прокрутка (Scrollback)

Возможность просматривать историю сессии без разрывов через клавиатурную прокрутку. Описана в `SCROLLBACK_FEATURE.md`; связана с просмотром истории сессии в TUI. → `sources/scrollback_feature.md`, `entities/textual_ui.md`

## Как работает
- История сессии загружается из `context.json` при старте; новые сообщения добавляются в конец. → `entities/session_directory.md`
- **Auto-scroll** включён по умолчанию — виден конец диалога.
- Ручная прокрутка вверх (отличная от конца) отключает auto-scroll; прокрутка в `End` включает его обратно.
- Индикатор `Scroll: AUTO/MANUAL` и позиция `History (start-end/total) %` в панели статистики.

## Управление
| Клавиша | Действие |
|---------|----------|
| `↑`/`↓` | на 3 строки |
| `PgUp`/`PgDown` | на страницу |
| `Home`/`End` | начало / конец сессии |

## Технические детали
- (Историческая запись) предполагался новый класс `core/scrollback_buffer.py` с интеграцией в `BotVisualizer` через `self.scrollback` и фоновым потоком `readchar`. `BotVisualizer` и Rich-движок удалены в 0.4, поэтому запись окончательно устарела.

## ⚠️ Противоречие
Файл `core/scrollback_buffer.py` **не найден** в git, фича не реализована. Актуальная прокрутка истории обеспечивается Textual (`textual_history_viewer.py`). Запись чисто историческая (Rich-эпоха).

## Связи
Интерфейс — `entities/textual_ui.md`; структура истории — `entities/session_directory.md`.
