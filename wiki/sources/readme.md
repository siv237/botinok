---
type: source
tags: [docs]
updated: 2026-08-23
sources: 1
status: stable
---

# README.md

Главный документ проекта (корень репо). Source: `<repo>/README.md` (raw, не изменяется). → `index.md`

## Содержание (резюме)
- **Что это**: «Проект Ботинок» — консольный агентный ИИ для Ollama; фокус на производительность, прозрачность и аудит сессий.
- **Концепция**: автономный агент для систем с малым объёмом VRAM.
- **Возможности**: продвинутый Rich-UI, умное управление контекстом (SESSION_PROTOCOL), function calling, dangerous mode, внешние промпты, полная прослеживаемость.
- **Архитектура инструментов**: `core/tool_manager.py`, группы (сеть/система/разработка/память/мультимодальность).
- **Сессии**: структура `sessions/<ts>_<name>/`.
- **Промпты**: вынесены в `prompts/`, копируются в сессию.
- **Безопасность**: `--dangerous`.
- **Техстек**: Ollama (модели с function calling: qwen2.5, llama3.1, mistral-nemo), удалённые/облачные модели.
- **Установка**: `curl ... | sudo bash` (install.sh) → `/opt/botinok`.
- **Использование**: интерактивный, одиночный запрос, stealth, pipe, выбор модели/контекста, update.
- **Настройка**: `--wizard`.
- **Навыки**: `skills/SKILL.md` + Python.
- **Быстрый старт**: 3 шага (Ollama + модель → установка → запуск).

## Производные страницы вики
- `entities/botinok_cli.md` · `entities/tool_manager.md` · `entities/ollama_backend.md` · `entities/session_directory.md` · `concepts/dangerous_mode.md` · `concepts/stealth_pipe_mode.md` · `sources/install_script.md`
