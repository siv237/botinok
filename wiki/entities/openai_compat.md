---
type: entity
tags: [integration, llm]
updated: 2026-10-18
sources: 3
status: stable
---

# OpenAI-совместимый бэкенд (openai_compat)

`core/openai_compat.py` — адаптер, позволяющий Ботинку работать с любыми OpenAI-совместимыми API: llama-server, vLLM, OpenAI и др. Включается в `config.cfg`:

```ini
[Ollama]
backend = openai
baseurl = http://localhost:8080
```

При `backend = openai` все запросы идут на `{baseurl}/v1/chat/completions`, а SSE-стрим конвертируется в формат Ollama `/api/chat` на лету. Если в `[Ollama]` указан `ApiKey`, во все запросы добавляется заголовок `Authorization: Bearer <ключ>`. → `concepts/function_calling.md`, `entities/config_system.md`

Бэкенд выбирается мастером настроек (`--wizard`): шаг 0 — тип сервера, для OpenAI дополнительно прописывается `ApiKey` и забирается список моделей из `/v1/models`. Мастер извлекает максимальный контекст модели из полей провайдера (`context_length`, `context_window`, `max_model_len`, вложено в `meta`/`meta.llama`); если провайдер контекст не отдаёт, пробуется эндпоинт llama.cpp `/props`. В шаге выбора модели контекст отображается, а в шаге контекста предлагается рекомендуемый (максимальный) или меньше. → `config_system.md`, `config_priority.md`

Все пути смены ключа сходятся на `core/api_key_gate.py`: `.save_api_key(sm, key)` пишет в персональный `~/.config/botinok/config.cfg` (с мержом эффективного конфига) и обновляет живой `sm.config`; запрос ключа — модальное `ApiKeyScreen` (`core/textual_app.py`) либо getpass в консоли. Три триггера: 401/403 в ходе (`is_auth_error` → проверка → повтор хода), первый запуск без ключа (`require_api_key`) и команда TUI **`/key`** — добровольная смена: проверка `ConfigWizard(sm).check_openai` (метод визарда: канонический `/v1/models` с Bearer) в фоне, сохранение только при успехе + запись в `server_history` / синхронизация env `BOTINOK_API_KEY`. → `entities/textual_ui.md`, `concepts/config_priority.md`

## Ключевые компоненты
- `is_openai_backend(sm)` — признак по конфигу (`openai`, `openai-compatible`).
- `to_openai_messages(messages)` — маппинг ролей, tool_calls, `thinking` (в историю API не передаётся).
- `_to_openai_payload(ollama_payload)` — `num_predict` → `max_tokens`, `stream_options.include_usage`.
- `OpenAIStreamResponse` — обёртка над SSE-стримом; имитирует `requests.Response.iter_lines()`, отдаёт NDJSON-чанки в формате Ollama, аккумулирует дельты tool_calls и usage. `reasoning_content`/`thinking` → поле `thinking`. Финальный чанк несёт и `reasoning_tokens` (из `completion_tokens_details`) — для калибратора токенов. → `concepts/token_calibration.md`
- `chat_stream_request(sm, payload)` / `chat_once(sm, payload)` — стриминговый и нестриминговый запросы.

## Связи
- Вызывается из `botinok.py` (`is_openai_backend`, `chat_stream_request`, `chat_once`). → `botinok_cli.md`
- Позволяет использовать удалённые/облачные модели без дополнительных ключей в агенте. → `ollama_backend.md`
