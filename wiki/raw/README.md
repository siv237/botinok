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
| `core/openai_compat.py` | Адаптер OpenAI-совместимых бэкендов | `entities/openai_compat.md` |
| `core/config_wizard.py` | Интерактивный мастер настройки (--wizard) | `concepts/config_priority.md` |
| `core/image_ascii.py` | ASCII-генерация изображений для консоли | `concepts/vision_multimodal.md` |
| `tools/*.py` | 13 инструментов (+ алиас `web_extractor`) (см. `entities/tools/`) | `entities/tools/*` |
| `prompts/*.txt` | Системные промпты (копируются в сессию) | `sources/prompts_readme.md` |
| `prompts/README.md` | Документация по системе промптов | `sources/prompts_readme.md` |
| `config.cfg` | Конфигурация по умолчанию (Ollama, Storage, Tools, UI) | `sources/config_cfg.md`, `entities/config_system.md` |
| `install.sh` | Установщик (системные зависимости, /opt/botinok, алиас) | `sources/install_script.md` |
| `README.md` | Главное описание проекта | `sources/readme.md` |
| `CHANGELOG.md` | Журнал версий (0.1, 0.2) | `sources/changelog.md` |
| `requirements.txt` | Зависимости Python (pip install -r) | `sources/requirements.md` |
| `SCROLLBACK_FEATURE.md` | Описание фичи «бесконечная прокрутка» TUI | `sources/scrollback_feature.md`, `concepts/scrollback.md` |
| `.git` (история) | Хронология коммитов | `sources/git_history.md` |
| `skills/excel/SKILL.md` | Пример навыка (excel) | `concepts/skills_system.md` |
| `assets/logo.png` | Логотип проекта | — |

## Производные артефакты (не raw, не включать в ингвест)
`sessions/`, `venv/`, `.browser_profile/`, `__pycache__/`, `*.log` — генерируются в рантайме, в `.gitignore`, не являются источниками знаний.

## Новая функция → новый источник
Когда в коде появляется новая фича или инструмент, это трактуется как **новый источник**: создай резюме-страницу в `wiki/sources/` (если оправдано) и обнови затронутые страницы сущностей/концепций. Запись о работе — в `log.md`.
