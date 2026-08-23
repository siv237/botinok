---
type: entity
tags: [config, integration]
updated: 2026-08-23
sources: 2
status: stable
---

# Ollama Backend

Основной бэкенд Ботинка — локальный/сетевой/облачный инстанс [Ollama](https://ollama.com). Проект спроектирован под работу с Ollama; нативный поток идёт через `/api/chat`.

## Настройки (config.cfg → `[Ollama]`)
- `baseurl` (по умолчанию `http://localhost:11434`) — адрес инстанса.
- `defaultmodel` (по умолчанию `qwen3.5:9b`), `defaultcontext` (по умолчанию 16384).
- `requesttimeout`, `temperature`, `top_p`, `top_k`, `repeat_penalty`, `num_predict`.
- `verify_ssl` — для `https`-доступа.

## Модели и Function Calling
Для работы инструментов нужны модели с поддержкой **function calling**: `qwen2.5`, `llama3.1`, `mistral-nemo`, `qwen3.5`. В противном случае используется режим только-чат. → `concepts/function_calling.md`

## Удалённые/облачные модели
Оllама может проксировать удалённые модели (`minimax-m2.7:cloud`); для Ботинка это выглядит как обычная модель — достаточно указать имя. Альтернатива — прямой OpenAI-совместимый доступ через адаптер. → `entities/openai_compat.md`

## Статус/управление
- `SessionManager.get_ollama_status()` — `GET /api/ps` (список загруженных моделей); при бэкенде `openai` возвращает `None`.
- `SessionManager.unload_models()` — выгрузка `keep_alive=0` через `/api/generate`. → `entities/session_manager.md`

## Примечание
Побочные сущности: `chat_only` режим для моделей без tools (`chat_only.txt`), обработка ошибок без tools (`_ollama_error_indicates_no_tools`). → `sources/prompts_readme.md`
