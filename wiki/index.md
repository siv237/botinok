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
- [entities/net_meter.md](entities/net_meter.md) — `core/net_meter.py`: сырой учёт трафика модели («АПИ отдано/принято»)
- [entities/shell_session.md](entities/shell_session.md) — `core/shell_session.py`: PTY-сессия команды и реестры
- [entities/shell_screen.md](entities/shell_screen.md) — `core/shell_screen.py`: встроенный терминал в TUI (свернуть/закрыть)
- [entities/session_directory.md](entities/session_directory.md) — структура директории сессии
- [entities/config_system.md](entities/config_system.md) — система конфигов (config.cfg, BOTINOK_CONFIG)

### Инструменты ([entities/tools/](entities/tools/))
| Инструмент | Страница | Краткое описание |
|-----------|----------|------------------|
| web | [entities/tools/web.md](entities/tools/web.md) | Единый добыватель данных: search/open/extract/json/download; харнес подсказок |
| download_manager | [entities/download_manager.md](entities/download_manager.md) | Глобальная память загрузок web: что/куда/целое, докачка, хеши |
| safe_ops | [entities/safe_ops.md](entities/safe_ops.md) | Каталог безопасных read-only операций + подсказки эквивалента |
| process_control | [entities/process_control.md](entities/process_control.md) | Реестр процессов и мгновенная остановка по Esc (killpg дерева) |
| file_system | [entities/tools/file-system.md](entities/tools/file-system.md) | FS: навигация, поиск, grep, инспекция; мутации — dangerous |
| code_editor | [entities/tools/code-editor.md](entities/tools/code-editor.md) | Edit-кит: read/write/replace/apply/undo/check, fuzzy, diff, синтаксис-проверка, чекпоинты; запись вне сессии — dangerous |
| shell_exec | [entities/tools/shell-exec.md](entities/tools/shell-exec.md) | PTY-сессия команд (run/read/search/send/wait/kill), dangerous, встроенный терминал |
| web_search | [entities/tools/web-search.md](entities/tools/web-search.md) | legacy-обёртка web (поиск) |
| open_url | [entities/tools/open-url.md](entities/tools/open-url.md) | legacy-обёртка web (текст страницы) |
| web_extract | [entities/tools/web-extract.md](entities/tools/web-extract.md) | legacy-обёртка web (структура) |
| curl | [entities/tools/curl.md](entities/tools/curl.md) | legacy-обёртка web (JSON/файлы); jq_filter восстановлен |
| journal | [entities/tools/journal.md](entities/tools/journal.md) | Read-only анализ systemd journal (journalctl) |
| github | [entities/tools/github.md](entities/tools/github.md) | Работа с GitHub API |
| experience | [entities/tools/experience.md](entities/tools/experience.md) | База «позитивного/негативного» опыта |
| vision | [entities/tools/vision.md](entities/tools/vision.md) | Анализ изображений мультимодальной моделью |
| image | [entities/tools/image.md](entities/tools/image.md) | Показать изображение в чате: файл/URL → каталог проекта → id → рендер по скроллу |
| audio | [entities/tools/audio.md](entities/tools/audio.md) | Анализ аудио мультимодальной (omni) моделью |
| skills | [entities/tools/skills.md](entities/tools/skills.md) | Менеджер AI-навыков (личные/проектные, ClawHub) |
| session_memory | [entities/tools/session-memory.md](entities/tools/session-memory.md) | Архивариус: restore (EXACT) / resume_brief / get_turn / гибкий поиск |

## Концепции (concepts)
Абстрактные механизмы и подходы.
- [concepts/session_lifecycle.md](concepts/session_lifecycle.md) — жизненный цикл сессии, создание, продолжение, возобновление
- [concepts/session_resume.md](concepts/session_resume.md) — возобновление и точное восстановление контекста (EXACT/DERIVED/HINT), устойчивость к обрывам API
- [concepts/scrollback.md](concepts/scrollback.md) — бесконечная прокрутка истории сессии (TUI); draft
- [concepts/context_management.md](concepts/context_management.md) — обрезка, переполнение, SESSION_PROTOCOL, детекция зацикливания
- [concepts/function_calling.md](concepts/function_calling.md) — механика tool-calls в потоке агента
- [concepts/dangerous_mode.md](concepts/dangerous_mode.md) — безопасность: dangerous mode и подтверждения
- [concepts/web_kit.md](concepts/web_kit.md) — единый веб-кит: один добыватель, харнес подсказок, контекстная дисциплина
- [concepts/edit_kit.md](concepts/edit_kit.md) — edit-кит: редактор с каркасом-советником, fuzzy, атомарность, чекпоинты
- [concepts/streaming_tui.md](concepts/streaming_tui.md) — стриминг, панель «Производительность» (живые метрики, профили сервера, зависания, трафик), плавность UI
- [concepts/thought_queue.md](concepts/thought_queue.md) — очередь «мыслей»: сказать модели, не прерывая; доставка блоком на границе раунда, крестик отмены
- [concepts/terminal_unicode_width.md](concepts/terminal_unicode_width.md) — ширина Unicode в терминале: почему «плывут» панели и как лечим
- [concepts/embedded_terminal.md](concepts/embedded_terminal.md) — встроенный терминал: PTY-сессии, свернуть/вернуть, общий доступ человека и агента
- [concepts/image_rendering.md](concepts/image_rendering.md) — изображения в чате: идентификаторы в сессии, каталог, ленивый рендер по скроллу, производительность на 4К
- [concepts/skills_system.md](concepts/skills_system.md) — система навыков (personal/project, ClawHub)
- [concepts/experience_learning.md](concepts/experience_learning.md) — обучение на опыте (positive/negative)
- [concepts/vision_multimodal.md](concepts/vision_multimodal.md) — мультимодальность: конвертация/ресaйз изображений
- [concepts/audio_multimodal.md](concepts/audio_multimodal.md) — мультимодальность: аудио через images[]/input_audio (требует omni-модель)
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
