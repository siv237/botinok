---
type: concept
tags: [llm, config, integration]
updated: 2026-10-11
sources: 3
status: stable
---

# Режимы рассуждения (reasoning)

Уровни рассуждения модели (low/medium/high и т.п.) определяются **самим API**, а не списком в коде: сервер диктует допустимые значения.

## Автоопределение уровней

- `core/openai_compat.py::probe_reasoning` шлёт тестовый запрос с пробным `reasoning_effort`; если сервер не принимает значение, в ответе 400 перечисляет допустимые — `parse_reasoning_error` вытаскивает список и дефолт из текста ошибки.
- Результат (уровни + default) кэшируется в `reasoning_cache.json` рядом с конфигом; ключ — `(backend, url, model)` (`reasoning_cache_key`). `probe_reasoning_cached` — быстрый путь для мастера и меню TUI, `force=True` переопрашивает.

## Где задаётся

- **Мастер** (`core/config_wizard.py::_configure_reasoning`): после выбора модели опрашивает API (или берёт кэш) и предлагает выбрать уровень.
- **TUI**: чип `🧠 <eff>` в шапке (`core/textual_app.py::show_reasoning_modal`) — горячая смена без перезапуска; выбор применяется на лету (`_apply_reasoning`).
- **Конфиг**: `[Ollama] ReasoningEffort` (общий ключ для обоих бэкендов). **Env**: `BOTINOK_REASONING` (переопределяет на запуск; `auto` снимает настройку).
- По умолчанию — **auto**: параметр вообще не отправляется, поведение модели прежнее.

## Отправка и устойчивость

- `get_reasoning_effort(sm)` читает настройку; для openai-бэкенда значение кладётся в `payload['reasoning_effort']` (`core/openai_compat.py`).
- Если сервер отклонил настройку (400), она молча снимается до `auto` — сессия не ломается.
- `reasoning_tokens` из `completion_tokens_details` прокидывается в финальный чанк — питает калибратор токенов. → `concepts/token_calibration.md`

## Связи
- `entities/openai_compat.md` — адаптер и проброс параметра
- `entities/textual_ui.md` — чип в шапке и модалка
- `concepts/config_priority.md` — приоритет env/флагов над конфигом
