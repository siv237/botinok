---
type: entity
tags: [integration, llm]
updated: 2026-08-23
sources: 2
status: stable
---

# OpenAI-совместимый бэкенд (openai_compat)

`core/openai_compat.py` — адаптер, позволяющий Ботинку работать с любыми OpenAI-совместимыми API: llama-server, vLLM, OpenAI и др. Включается в `config.cfg`:

```ini
[Ollama]
backend = openai
baseurl = http://192.168.237.131:8080
```

При `backend = openai` все запросы идут на `{baseurl}/v1/chat/completions`, а SSE-стрим конвертируется в формат Ollama `/api/chat` на лету. Если в `[Ollama]` указан `ApiKey`, во все запросы добавляется заголовок `Authorization: Bearer <ключ>`. → `concepts/function_calling.md`, `entities/config_system.md`

Бэкенд выбирается мастером настроек (`--wizard`): шаг 0 — тип сервера, для OpenAI дополнительно прописывается `ApiKey` и забирается список моделей из `/v1/models`. → `config_system.md`

## Ключевые компоненты
- `is_openai_backend(sm)` — признак по конфигу (`openai`, `openai-compatible`).
- `to_openai_messages(messages)` — маппинг ролей, tool_calls, `thinking` (в историю API не передаётся).
- `_to_openai_payload(ollama_payload)` — `num_predict` → `max_tokens`, `stream_options.include_usage`.
- `OpenAIStreamResponse` — обёртка над SSE-стримом; имитирует `requests.Response.iter_lines()`, отдаёт NDJSON-чанки в формате Ollama, аккумулирует дельты tool_calls и usage. `reasoning_content`/`thinking` → поле `thinking`.
- `chat_stream_request(sm, payload)` / `chat_once(sm, payload)` — стриминговый и нестриминговый запросы.

## Связи
- Вызывается из `botinok.py` (`is_openai_backend`, `chat_stream_request`, `chat_once`). → `botinok_cli.md`
- Позволяет использовать удалённые/облачные модели без дополнительных ключей в агенте. → `ollama_backend.md`
