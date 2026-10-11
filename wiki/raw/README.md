# Raw Sources — манифест исходников

Этот слой — **неизменяемый источник истины**. Данные файлы живут в корне репозитория и не редактируются вики. Агент только читает их. Манифест ниже каталогизирует их и связывает с соответствующими резюме-страницами в `wiki/sources/`.

> Принцип: `raw/` не копирует содержимое (код уже в git). Здесь — указатели на реальные файлы репозитория, их назначение и ссылка на резюме в вики.

## Каталог исходников

| Файл (в корне проекта) | Назначение | Резюме в вики |
|------------------------|------------|----------------|
| `botinok.py` | Главный CLI/агент: аргументы, поток вызова Ollama, TUI, корректор | `sources/readme.md`, `entities/botinok_cli.md` |
| `core/session_manager.py` | Управление сессиями, конфигами, логирование, промпты сессии | `entities/session_manager.md` |
| `core/tool_manager.py` | Реестр и lazy-загрузка инструментов | `entities/tool_manager.md` |
| `core/textual_app.py` | Textual TUI-приложение | `entities/textual_ui.md` |
| `core/textual_integration.py` | Поток вызова модели через Textual UI | `entities/textual_ui.md` |
| `core/textual_history_viewer.py` | Просмотр истории сессии в TUI | `entities/textual_ui.md` |
| `core/shell_session.py` | PTY-сессия команды (не держит агента), реестры сессий и Textual-приложения | `entities/shell_session.md` |
| `core/shell_screen.py` | Встроенный терминал в TUI (окно, кнопки «Свернуть/Закрыть») | `entities/shell_screen.md` |
| `core/net_meter.py` | Сырой учёт трафика модели: «АПИ отдано / АПИ принято» | `entities/net_meter.md` |
| `core/textual_prompts.py` | Textual-диалоги для CLI (select/prompt/confirm) | `entities/textual_ui.md` |
| `core/session_picker.py` | Textual-экран выбора/возобновления сессии | `entities/botinok_cli.md` |
| `core/cli_io.py` | Plain-вывод CLI без Rich (`out`, `term_width`) | `sources/requirements.md` |
| `core/text_width.py` | Нормализация ширины Unicode/эмодзи и обрезка по ячейкам | `concepts/terminal_unicode_width.md` |
| `core/openai_compat.py` | Адаптер OpenAI-совместимых бэкендов, reasoning-уровни, usage | `entities/openai_compat.md`, `concepts/reasoning_modes.md` |
| `core/config_wizard.py` | Интерактивный мастер настройки (--wizard) | `concepts/config_priority.md` |
| `core/server_history.py` | История серверов мастера (адрес/ключ) | `concepts/config_priority.md` |
| `core/api_key_gate.py` | Окно ввода API-ключа при 401/403 | `entities/openai_compat.md` |
| `core/token_calibrator.py` | Калибратор «байты→токены» по фактическому usage | `concepts/token_calibration.md` |
| `core/session_digest.py` | Скользящее окно памяти, FORGOTTEN_INDEX, подписи sign_step | `concepts/context_management.md` |
| `core/process_control.py` | Реестр процессов, остановка дерева по Esc | `entities/process_control.md` |
| `core/net_config.py` | Единый прокси для веб-инструментов | `entities/net_config.md` |
| `core/themes.py` | Темы ночь/день/вечер | `concepts/theming.md` |
| `core/image_render.py` / `image_block.py` / `image_catalog.py` / `image_refs.py` | Рендер и каталог картинок в чате | `concepts/image_rendering.md` |
| `core/syntax_check.py` / `file_kinds.py` | Синтаксис-проверка code_editor, реестр типов | `concepts/edit_kit.md` |
| `core/image_ascii.py` | ASCII-генерация изображений для консоли | `concepts/vision_multimodal.md` |
| `tools/*.py` | Инструменты: единый `web` (+legacy-алиасы `web_search`/`open_url`/`web_extract`/`curl`), `web_jobs`, `download_manager`, `safe_ops`, `file_system`, `code_editor`, `shell_exec`, `session_memory`, `sign_step`, `experience`, `skills`, `github`, `journal`, `vision`, `audio`, `image_show`, служебный `tools_catalog` (см. `entities/tools/`) | `entities/tools/*` |
| `prompts/*.txt` | Системные промпты (копируются в сессию) | `sources/prompts_readme.md` |
| `prompts/README.md` | Документация по системе промптов | `sources/prompts_readme.md` |
| `config.cfg` | Конфигурация по умолчанию (Ollama, Storage, Tools, UI) | `sources/config_cfg.md`, `entities/config_system.md` |
| `install.sh` | Установщик (системные зависимости, /opt/botinok, алиас) | `sources/install_script.md` |
| `update.sh` | Обновление из git | `concepts/self_update.md` |
| `README.md` | Главное описание проекта | `sources/readme.md` |
| `CHANGELOG.md` | Журнал версий (0.1–0.4) | `sources/changelog.md` |
| `requirements.txt` | Зависимости Python (pip install -r) | `sources/requirements.md` |
| `requirements-dev.txt` | Тестовые зависимости (pytest, pytest-asyncio) | `sources/requirements.md` |
| `SCROLLBACK_FEATURE.md` | ~~Описание фичи «бесконечная прокрутка»~~ — удалён из репо; фича живёт в TUI | `sources/scrollback_feature.md`, `concepts/scrollback.md` |
| `.git` (история) | Хронология коммитов | `sources/git_history.md` |
| `skills/excel/SKILL.md` | Пример навыка (excel) | `concepts/skills_system.md` |
| `skills/llm-wiki/SKILL.md` | Скилл ведения этой вики (WIKI_MODE) | `concepts/skills_system.md` |
| `assets/logo.png` | Логотип проекта | — |

## Производные артефакты (не raw, не включать в ингвест)
`sessions/`, `venv/`, `.browser_profile/`, `__pycache__/`, `*.log` — генерируются в рантайме, в `.gitignore`, не являются источниками знаний.

## Новая функция → новый источник
Когда в коде появляется новая фича или инструмент, это трактуется как **новый источник**: создай резюме-страницу в `wiki/sources/` (если оправдано) и обнови затронутые страницы сущностей/концепций. Запись о работе — в `log.md`.
