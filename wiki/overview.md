# Вики проекта «Ботинок» — обзор (synthesis)

> Точка входа в вики. Индекс всех страниц — в `index.md`. Хронология операций — в `log.md`. Правила ведения — в `AGENTS.md`.

## Что это

**«Ботинок»** (`botinok`) — консольный агентный ИИ (LLM-агент), работающий с локальным **Ollama** и любыми **OpenAI-совместимыми API** (OpenAI, llama-server, vLLM). Акцент на производительность, прозрачность работы модели и детальный аудит сессий. Интерфейс полностью консольный: полноэкранный Textual TUI по умолчанию, одиночный запрос / stealth / pipe — для скриптов. Полностью русскоязычный интерфейс.

Репозиторий: `github.com/siv237/botinok` · Версия: **0.4** · Язык: Python 3.

## Как устроен проект (архитектура)

```
botinok.py                        # CLI / главный цикл агента: TUI, одиночный запрос, stealth, pipe, --update
├── core/
│   ├── session_manager.py        # сессии, конфиги, промпты, логирование
│   ├── session_digest.py / session_picker.py  # скользящее окно/дайджесты, выбор сессии
│   ├── tool_manager.py           # реестр и lazy-загрузка инструментов
│   ├── openai_compat.py          # адаптер OpenAI-совместимых API (reasoning-уровни, usage)
│   ├── config_wizard.py / server_history.py   # мастер настройки, история серверов, SSL-проверка
│   ├── api_key_gate.py           # окно ввода API-ключа при 401/403
│   ├── textual_app.py / textual_integration.py / textual_history_viewer.py  # Textual TUI
│   ├── shell_session.py / shell_screen.py / process_control.py  # PTY-сессии, встроенный терминал, остановка по Esc
│   ├── net_meter.py / net_config.py  # учёт трафика модели, единый прокси
│   ├── themes.py                 # темы ночь/день/вечер
│   ├── token_calibrator.py       # калибратор «байты→токены» по фактическому usage
│   ├── image_render.py / image_block.py / image_catalog.py / image_refs.py  # картинки в чате
│   └── image_ascii.py / syntax_check.py / file_kinds.py / text_width.py / terminal_keys.py / clipboard.py / path_utils.py / cli_io.py
├── tools/*.py                    # инструменты: web (+legacy-алиасы), file_system, code_editor, shell_exec,
│                                 # session_memory, sign_step, experience, skills, github, journal,
│                                 # vision, audio, image_show, web_jobs, download_manager, safe_ops, tools_catalog
├── prompts/*.txt                 # системные промпты (копируются в сессию)
├── config.cfg                    # конфигурация по умолчанию
├── install.sh / update.sh        # установщик и самообновление
└── skills/{excel,llm-wiki}/      # навыки; llm-wiki — ведение этой вики агентом
```

## Ключевые механизмы (карта мышления)

- **Сессии** — каждый интерактивный запуск создаёт `sessions/<timestamp>_<name>/` с полным трейсом: `context.json`, `messages.json`, `thinking.md`, `response.md`, `tools.log`, `artifacts/`, `steps/`. Одиночный/stealth/pipe — временная сессия, удаляется после ответа. → `entities/session_directory.md`, `concepts/session_lifecycle.md`, `concepts/session_resume.md`, `concepts/stealth_pipe_mode.md`
- **Скользящее окно памяти** — старые ходы плавно вытесняются вместо сброса разом; агент держит каталог «забытого» и поднимает любой фрагмент (`session_memory` get_turn/поиск). Осознанная компакция: `session_memory action=context_map/compact` — агент видит цену блоков в токенах и сам освобождает отработанное. `sign_step` — чекпоинты прогресса, живущие через сбросы. → `concepts/context_management.md`, `concepts/context_memory_research.md`, `entities/tools/session-memory.md`
- **Калибратор токенов** — плотность «байты→токены» измеряется по фактическому usage сервера; панель и бюджеты тримма считают токены, а не байты. → `concepts/token_calibration.md`
- **Инструменты (function calling)** — включаются по запросу и не занимают контекст заранее; единый `web` вместо четырёх; фоновые веб-задачи. → `entities/tool_manager.md`, `concepts/function_calling.md`, `concepts/web_kit.md`, `entities/tools/web-jobs.md`
- **Dangerous mode** — мутирующие действия вне песочницы сессии требуют `--dangerous` или подтверждения по ходу; внутри `project/` агент свободен. → `concepts/dangerous_mode.md`
- **Два бэкенда** — нативный Ollama `/api/chat` и OpenAI-совместимые API через адаптер; режимы рассуждения (reasoning) определяются самим API, переключаются чипом 🧠 в шапке. → `entities/ollama_backend.md`, `entities/openai_compat.md`, `concepts/reasoning_modes.md`
- **UI** — Textual TUI: плавный стриминг, спойлеры мыслей, очередь «мыслей», панель «Производительность» (метрики в токенах, таймер молчания, трафик), темы ночь/день/вечер, картинки прямо в чате. → `entities/textual_ui.md`, `concepts/streaming_tui.md`, `concepts/theming.md`, `concepts/image_rendering.md`, `concepts/thought_queue.md`, `entities/net_meter.md`
- **Встроенный терминал** — `shell_exec` в фоновой PTY-сессии, окно терминала над чатом, мгновенная остановка процессов по Esc. → `concepts/embedded_terminal.md`, `entities/shell_session.md`, `entities/shell_screen.md`, `entities/process_control.md`
- **Промпты** — вынесены в `prompts/`, копируются в сессию, редактируемы под задачу. → `sources/prompts_readme.md`
- **Опыт, навыки и вики** — база опыта, skills (personal/project, ClawHub), скилл llm-wiki (WIKI_MODE); живучесть подключённых скиллов через сбросы. → `concepts/experience_learning.md`, `concepts/skills_system.md`
- **Мультимодальность** — `vision` (авто-конвертация/ресайз), `audio` (omni-модели), `image` (показ в чате, truecolor по ssh). → `concepts/vision_multimodal.md`, `concepts/audio_multimodal.md`, `concepts/image_rendering.md`

## Инструменты

| Группа | Инструменты |
|--------|-------------|
| Сеть и поиск | `web` (единый добыватель; `web_search`/`open_url`/`web_extract`/`curl` — legacy-алиасы), `web_jobs`, `download_manager` |
| Система | `file_system`, `shell_exec`, `journal`, `safe_ops`, `process_control` |
| Разработка | `code_editor` (edit-кит, синтаксис-проверка), `github`, `skills` |
| Память/опыт | `session_memory`, `sign_step`, `experience` |
| Мультимодальность | `image`, `vision`, `audio` |

Подробно: каталог `entities/tools/` и `index.md`.

## Состояние
Активная разработка; вехи: релиз 0.1 (03-2026), 0.2 (03-2026), переход на Textual (04-2026), OpenAI-compat бэкенды и релиз 0.3 (08-2026), релиз 0.4 — скользящее окно памяти, единый web, картинки в чате, темы, reasoning-режимы (10-2026). Полная хронология — `log.md` и `sources/git_history.md`.
