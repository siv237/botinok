---
type: concept
tags: [tui, llm]
updated: 2026-08-23
sources: 2
status: stable
---

# Стриминг и производительность в TUI

Проект сильно оптимизирован под низкую VRAM и слабые терминалы. Метрики: **TTFT** (Time To First Token), **TPS** (Tokens Per Second), **VRAM**. Визуализация — класс `BotVisualizer` (Rich) и Textual UI. → `entities/textual_ui.md`

## Ключевые улучшения (из git-истории)
- Замена Rich Live на **Textual TUI** для плавности (FPS 10/30). → `comparisons/rich_vs_textual.md`
- **Единая точка вывода** `stream_static`: весь поток рендерится там; «спойлеры» открываются/закрываются по очереди → **нет мигания** в терминале.
- Живое markdown-форматирование стрима ассистента.
- Исправления мерцания в SSH-терминалах с низкой скоростью (Rich-эпоха).
- Компактный прогрессбар контекста.

## Отображаемые метрики
- TTFT, TPS, использованный/лимит контекста, VRAM на всех этапах.
- Метрики сохраняются в YAML-футер сессии (`BOTINOK_SESSION_METADATA`). → `entities/session_directory.md`, `entities/session_manager.md`

## Связи
Интерфейсы — `entities/textual_ui.md`, `entities/botinok_cli.md`. Управление контекстом — `concepts/context_management.md`.
