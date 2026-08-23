---
type: concept
tags: [config]
updated: 2026-08-23
sources: 2
status: stable
---

# Приоритет конфигов и Мастер настройки

Конфигурация выбирается и настраивается несколькими способами. → `entities/config_system.md`

## Приоритет источников (личный > локальный > системный)
1. **Личный**: `~/.config/botinok/config.cfg`
2. **Локальный**: `config.cfg` в текущей директории
3. **Системный**: `BOTINOK_CONFIG` env или `/opt/botinok/config.cfg`

Выбранный путь/источник доступны в `SessionManager` (`config_path`, `config_source`). → `entities/session_manager.md`

## Мастер настройки (--wizard)
`core/config_wizard.py` (класс `ConfigWizard`) — интерактивный мастер быстрой настройки базового URL Ollama, моделей и **контекста по умолчанию**.
- Работает даже когда Ollama за nginx (`basedir` через прокси).
- `--wizard` без обязательного rich-режима.
- Оптимизация работы по SSL с Ollama (`verify_ssl`).
- `--rich-mode` опционален (Textual по умолчанию). → `entities/textual_ui.md`

## Связи
Содержимое файла — `sources/config_cfg.md`; настройки Ollama — `entities/ollama_backend.md`.
