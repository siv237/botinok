# Вики проекта «Ботинок» — обзор (synthesis)

> Точка входа в вики. Индекс всех страниц — в `index.md`. Хронология операций — в `log.md`. Правила ведения — в `AGENTS.md`.

## Что это

**«Ботинок»** (`botinok`) — консольный агентный ИИ (LLM-агент), глубоко оптимизированный для работы с локальным **Ollama** (и OpenAI-совместимыми бэкендами) в системах с малым объёмом VRAM. Акцент на производительность, прозрачность работы модели и детальный аудит сессий. Интерфейс полностью консольный с богатым форматированием (Rich + Textual TUI).

Репозиторий: `github.com/siv237/botinok` · Версия: **0.2** · Язык: Python 3.

## Как устроен проект (архитектура)

```
botinok.py                        # CLI / главный цикл агента, вызов модели, TUI, корректор
├── core/
│   ├── session_manager.py        # сессии, конфиги, промпты, логирование
│   ├── tool_manager.py           # реестр/загрузка инструментов
│   ├── openai_compat.py          # адаптер OpenAI-совместимых API
│   ├── config_wizard.py          # мастер настройки
│   ├── textual_app.py / textual_integration.py / textual_history_viewer.py  # Textual TUI
│   └── image_ascii.py            # ASCII-арт из картинок
├── tools/*.py                    # 14 инструментов (+ алиас, function calling)
├── prompts/*.txt                 # системные промпты (копируются в сессию)
├── config.cfg                    # конфигурация по умолчанию
├── install.sh                    # установщик
└── skills/excel/SKILL.md         # пример навыка
```

## Ключевые механизмы (карта мышления)

- **Сессии** — каждый запуск создаёт `sessions/<timestamp>_<name>/` с полным трейсом: `context.json`, `thinking.md`, `response.md`, `tools.log`, `artifacts/`, `steps/`. → `entities/session_directory.md`, `concepts/session_lifecycle.md`
- **Управление контекстом** — автообрезка и протокол `SESSION_PROTOCOL` при переполнении, суммаризация, детекция зацикливания. → `concepts/context_management.md`
- **Инструменты (function calling)** — 14 инструментов, lazy-загрузка через `ToolManager`, безопасные/опасные действия. → `entities/tool_manager.md`, `concepts/function_calling.md`
- **Dangerous mode** — `code_editor`/`shell_exec` и мутирующие действия FS включаются только явно (`--dangerous`). → `concepts/dangerous_mode.md`
- **Два бэкенда** — нативный Ollama `/api/chat` и OpenAI-совместимые API через адаптер. → `entities/ollama_backend.md`, `entities/openai_compat.md`
- **UI** — переход с Rich Live на Textual TUI (плавный стриминг, спойлеры, FPS). → `entities/textual_ui.md`, `comparisons/rich_vs_textual.md`
- **Промпты** — вынесены в `prompts/`, копируются в сессию, редактируемы под задачу. → `sources/prompts_readme.md`
- **Опыт и навыки** — база «позитивного/негативного» опыта и система skills. → `concepts/experience_learning.md`, `concepts/skills_system.md`
- **Мультимодальность** — инструмент `vision` (изображения, авто-конвертация/ресaйз) и `audio` (аудио, требует omni-модель). → `concepts/vision_multimodal.md`, `concepts/audio_multimodal.md`

## Инструменты (14)

| Шаблон | Инструменты |
|--------|-------------|
| Сеть и поиск | `web_search`, `open_url`, `web_extract`, `curl` |
| Система | `file_system`, `shell_exec`, `journal` |
| Разработка | `code_editor`, `github`, `skills` |
| Память/опыт | `experience`, `session_memory` |
| Мультимодальность | `vision`, `audio` |

Подробно: каталог `entities/tools/` и `index.md`.

## Состояние
Активная разработка; вехи: релиз 0.1 (03-2026), 0.2 (03-2026), переход на Textual (04-2026), OpenAI-compat бэкенды (08-2026). Полная хронология — `log.md` и `sources/git_history.md`.
