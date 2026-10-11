---
type: source
tags: [docs]
updated: 2026-10-11
sources: 1
status: stable
---

# README.md

Главный документ проекта (корень репо). Source: `<repo>/README.md` (raw, не изменяется). → `index.md`

## Содержание (резюме, состояние 0.4)
- **Что это**: «Проект Ботинок» — консольный агентный ИИ для Ollama и любых OpenAI-совместимых API (OpenAI, llama-server, vLLM); фокус на производительность, прозрачность и аудит сессий; самообучение (experience/skills/session_memory).
- **Возможности**: Textual TUI по умолчанию (стриминг, статистика TTFT/TPS/VRAM, встроенный терминал, темы), reasoning-режимы, скользящее окно памяти + SESSION_PROTOCOL, function calling (инструменты по запросу), dangerous mode, внешние промпты, полная прослеживаемость.
- **Быстрый старт**: 3 шага — `curl … | sudo bash` (install.sh) → `botinok --wizard` → `botinok`.
- **Философия умных инструментов**: контекст — самое дорогое; одна задача — один инструмент (`web` вместо четырёх); подсказка следующего шага; надёжность без модели (докачка, sha256, ретраи); аудируемость.
- **Инструменты**: группы сеть/система/разработка/память/мультимодальность; `web` с aria2c/торрентами/прокси/памятью загрузок.
- **Сессии**: структура `sessions/<ts>_<name>/`; одиночный запрос/stealth/pipe — временная сессия.
- **Режимы**: интерактивный, одиночный запрос, stealth, pipe; запуск одной строкой без конфига (`--backend/--base-url/--api-key/-m`, env `BOTINOK_*`); `--reasoning`; `--update`; `--view-history`; `--version`.
- **Настройка**: `--wizard`, приоритет конфигов (`~/.config/botinok/config.cfg` → локальный → системный).
- **Навыки**: `skills/` (personal/project), SKILL.md + Python.
- **Футер**: текущая версия со ссылкой на CHANGELOG и wiki.

## Производные страницы вики
- `entities/botinok_cli.md` · `entities/tool_manager.md` · `entities/ollama_backend.md` · `entities/openai_compat.md` · `entities/session_directory.md` · `concepts/dangerous_mode.md` · `concepts/stealth_pipe_mode.md` · `concepts/web_kit.md` · `sources/install_script.md`
