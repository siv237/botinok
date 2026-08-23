---
type: concept
tags: [tui, session]
updated: 2026-08-23
sources: 1
status: draft
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
- Новый класс `core/scrollback_buffer.py` (интеграция в `BotVisualizer` через `self.scrollback`), фоновый поток `readchar` для чтения клавиш без блокировки UI.

## ⚠️ Противоречие
Файл `core/scrollback_buffer.py` **не найден** в git. Не подтверждено, что фича реализована в коде (возможная альтернатива — Textual `textual_history_viewer.py`). Статус — `draft` до проверки по коду; при подтверждении в `textual_history_viewer.py` обновить страницу и `sources/scrollback_feature.md`.

## Связи
Интерфейс — `entities/textual_ui.md`; структура истории — `entities/session_directory.md`; `readchar` как зависимость — `sources/requirements.md`.
