# Индекс вики (index)

Каталог всех страниц вики по категориям. Обновляется при каждом ingest. При ответе на запрос сначала читается этот файл.

## Корневые страницы
- [overview.md](overview.md) — синтез: что такое Ботинок, архитектура, карта механизмов
- [../AGENTS.md](../AGENTS.md) — схема вики (правила ведения, воркфлоу; в корне репо)
- [raw/README.md](raw/README.md) — манифест неизменяемых исходников
- [log.md](log.md) — хронологический журнал операций

## Сущности (entities)
Компоненты и инструменты проекта.
- [entities/ollama_backend.md](entities/ollama_backend.md) — бэкенд Ollama (локальный/сетевой/облачный)
- [entities/openai_compat.md](entities/openai_compat.md) — адаптер OpenAI-совместимых API (llama-server, vLLM)
- [entities/session_manager.md](entities/session_manager.md) — `core/session_manager.py`
- [entities/tool_manager.md](entities/tool_manager.md) — `core/tool_manager.py`, реестр и загрузка инструментов
- [entities/botinok_cli.md](entities/botinok_cli.md) — `botinok.py` / `botinok`, CLI, флаги, режимы
- [entities/textual_ui.md](entities/textual_ui.md) — Textual TUI (`textual_app.py`, `textual_integration.py`, `textual_history_viewer.py`)
- [entities/session_directory.md](entities/session_directory.md) — структура директории сессии
- [entities/config_system.md](entities/config_system.md) — система конфигов (config.cfg, BOTINOK_CONFIG)

### Инструменты ([entities/tools/](entities/tools/))
| Инструмент | Страница | Краткое описание |
|-----------|----------|------------------|
| file_system | [entities/tools/file-system.md](entities/tools/file-system.md) | FS: навигация, поиск, grep, инспекция; мутации — dangerous |
| code_editor | [entities/tools/code-editor.md](entities/tools/code-editor.md) | Редактирование файлов (read/write/replace/apply), dangerous |
| shell_exec | [entities/tools/shell-exec.md](entities/tools/shell-exec.md) | Выполнение shell-команд, dangerous, подтверждение |
| web_search | [entities/tools/web-search.md](entities/tools/web-search.md) | Поиск DuckDuckGo через lynx |
| open_url | [entities/tools/open-url.md](entities/tools/open-url.md) | Извлечение текста страницы через lynx -dump |
| web_extract | [entities/tools/web-extract.md](entities/tools/web-extract.md) | Структурированное извлечение (links, images, tables) через httpx+selectolax |
| curl | [entities/tools/curl.md](entities/tools/curl.md) | HTTP GET, скачивание, jq-фильтры; запись только в сессию |
| journal | [entities/tools/journal.md](entities/tools/journal.md) | Read-only анализ systemd journal (journalctl) |
| github | [entities/tools/github.md](entities/tools/github.md) | Работа с GitHub API |
| experience | [entities/tools/experience.md](entities/tools/experience.md) | База «позитивного/негативного» опыта |
| vision | [entities/tools/vision.md](entities/tools/vision.md) | Анализ изображений мультимодальной моделью |
| skills | [entities/tools/skills.md](entities/tools/skills.md) | Менеджер AI-навыков (личные/проектные, ClawHub) |
| session_memory | [entities/tools/session-memory.md](entities/tools/session-memory.md) | Объектный доступ к истории сессии |

## Концепции (concepts)
Абстрактные механизмы и подходы.
- [concepts/session_lifecycle.md](concepts/session_lifecycle.md) — жизненный цикл сессии, создание, продолжение, возобновление
- [concepts/scrollback.md](concepts/scrollback.md) — бесконечная прокрутка истории сессии (TUI); draft
- [concepts/context_management.md](concepts/context_management.md) — обрезка, переполнение, SESSION_PROTOCOL, детекция зацикливания
- [concepts/function_calling.md](concepts/function_calling.md) — механика tool-calls в потоке агента
- [concepts/dangerous_mode.md](concepts/dangerous_mode.md) — безопасность: dangerous mode и подтверждения
- [concepts/streaming_tui.md](concepts/streaming_tui.md) — стриминг, TTFT/TPS, VRAM, плавность UI
- [concepts/skills_system.md](concepts/skills_system.md) — система навыков (personal/project, ClawHub)
- [concepts/experience_learning.md](concepts/experience_learning.md) — обучение на опыте (positive/negative)
- [concepts/vision_multimodal.md](concepts/vision_multimodal.md) — мультимодальность: конвертация/ресaйз изображений
- [concepts/stealth_pipe_mode.md](concepts/stealth_pipe_mode.md) — тихий режим и работа из конвейера (stdin)
- [concepts/proofreader.md](concepts/proofreader.md) — режим корректора (Исполнитель → Корректор)
- [concepts/config_priority.md](concepts/config_priority.md) — приоритет конфигов и wizard
- [concepts/self_update.md](concepts/self_update.md) — автообновление из git (--update)

## Сравнения (comparisons)
- [comparisons/rich_vs_textual.md](comparisons/rich_vs_textual.md) — Rich Live против Textual TUI

## Источники (sources)
Резюме исходных документов.
- [sources/readme.md](sources/readme.md) — README.md (главное описание)
- [sources/changelog.md](sources/changelog.md) — CHANGELOG.md (0.1, 0.2)
- [sources/config_cfg.md](sources/config_cfg.md) — config.cfg (ключи и значения)
- [sources/prompts_readme.md](sources/prompts_readme.md) — система системных промптов
- [sources/install_script.md](sources/install_script.md) — install.sh (установщик)
- [sources/requirements.md](sources/requirements.md) — requirements.txt (зависимости Python)
- [sources/scrollback_feature.md](sources/scrollback_feature.md) — SCROLLBACK_FEATURE.md (фича прокрутки TUI)
- [sources/git_history.md](sources/git_history.md) — хронология коммитов и основные вехи
