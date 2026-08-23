---
type: source
tags: [tui]
updated: 2026-08-23
sources: 1
status: draft
---

# SCROLLBACK_FEATURE.md

Описание фичи «бесконечная прокрутка» (scrollback buffer) в интерфейсе истории сессии. Source: `<repo>/SCROLLBACK_FEATURE.md`. → `concepts/scrollback.md`, `entities/textual_ui.md`

## Резюме (содержание документа)
- **Что**: бесконечная прокрутка истории сессии без разрывов между диалогами; все сообщения в общей последовательности.
- **Управление**: `↑`/`↓` на 3 строки, `PgUp`/`PgDown` на страницу, `Home`/`End` — к началу/концу.
- **Интерфейс**: заголовок панели `History (start-end/total) %`; полоса прокрутки (ползунок `█`, фон `│`); индикатор `Scroll: ... | AUTO/MANUAL` (AUTO — следует за текстом, зелёный; MANUAL — ручное управление, жёлтый).
- **Логика**: история из `context.json`; auto-scroll по умолчанию; ручная прокрутка вверх отключает auto; `End` возвращает auto.

## Технические детали (по документу)
- Новый класс: `core/scrollback_buffer.py`; интеграция в `BotVisualizer` через `self.scrollback`; фоновый поток `readchar`; сохранение позиции при вызове инструментов.

## ⚠️ Расхождение документ/код (противоречие)
`core/scrollback_buffer.py` **отсутствует** в git-истории (проверено `git ls-files`). Наличие фичи в работающем коде не подтверждено — вероятно, класс либо не был закоммичен, либо реализован иначе (например, в Textual `textual_history_viewer.py`). Статус страницы — `draft` до верификации в коде.

## Производные страницы
`concepts/scrollback.md` · `entities/textual_ui.md`
