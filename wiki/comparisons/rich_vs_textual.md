---
type: comparison
tags: [tui]
updated: 2026-09-17
sources: 3
status: superseded
---

# Сравнение: Rich Live против Textual TUI

> **Статус: superseded (2026-09-17).** Rich Live движок удалён из проекта (0.4).
> Страница сохранена как исторический контекст миграции. Актуальный интерфейс —
> только Textual TUI. → `entities/textual_ui.md`

Проект перешёл с интерфейса на базе **Rich Live** на **Textual TUI**. После
завершения миграции старый движок (`BotVisualizer`, `create_layout`,
`ask_ollama_stream`, флаг `--rich-mode`) удалён — в кодовой базе остался только
Textual; Rich используется как библиотека рендеринга внутри Textual и для
headless-вывода stealth-режима.

## Textual TUI (актуальный, единственный интерактивный)
- **Плавный стриминг**: FPS 10/30, ускорение UI.
- **Нет мигания**: единая точка вывода `stream_static`; спойлеры открываются/закрываются по очереди.
- **Collapsible-спойлеры** в общем потоке вместо RichLog (thinking/артефакты).
- **Живое markdown-рендеринг** стрима ассистента.
- **Независимый ввод** сообщений, очередь, остановка по **ESC**.
- **Встроенный терминал**: окна PTY-сессий `shell_exec` со сворачиванием/возвратом. → `concepts/embedded_terminal.md`
- Корректное отображение VRAM на всех этапах.

## Rich Live (удалено в 0.4)
- Библиотека Rich: `Layout`, `Panel`, `Table`, `Live`, `Progress`, `Markdown`.
- Класс `BotVisualizer` отображал статистику VRAM/TPS/TTFT.
- Были исправления мерцания в SSH-терминалах с низкой скоростью; компактный прогрессбар контекста.

## Вывод
Textual даёт более плавный и современный поток без мерцания. Поддержка двух
движков больше не нужна: интерактив — Textual, автоматизация/pipe — headless
`ask_ollama_stealth`.

## Связи
Поток — `concepts/streaming_tui.md`. Интерфейсы — `entities/textual_ui.md`, `entities/botinok_cli.md`.
