---
type: concept
tags: [llm, session, audio]
updated: 2026-08-24
sources: 1
status: stable
---

# Мультимодальность (Audio)

Возможность анализировать аудио. Инструмент `audio` передаёт звук в omni-модель (Qwen3-Omni, Qwen3.5-Omni/27B и др.) в base64. → `entities/tools/audio.md`

## Особенность транспорта
Правильный нативный способ передать аудио в Ollama `/api/chat` — сообщение с полем **`audios`** (множественное): `"audios": ["<base64-wav>"]`, принимается **только WAV** (детект по magic-байтам). Поле появляется в сборках Ollama с нерелизнутой поддержкой аудио (PR [ollama/ollama#15243](https://github.com/ollama/ollama/pull/15243), закрывает issue #11798). Модели с аудио-модальностью (напр. gemma4 — недокументированный тег `audio`; qwen-omni) получают звук именно так. В botinok аудио-сообщение несёт `audios=[b64]` + маркеры `media_kind="audio"` и `mime_type`.

## Обе ветки бэкендов
- **Ollama native `/api/chat`** → сообщение с `audios=[b64wav]` (по PR #15243). В live-тестах на Ollama 0.32.14 эти поля до модели НЕ доходят.
- **OpenAI-совместимый `/v1/chat/completions`** → content-part `{"type":"input_audio","input_audio":{"data":<b64>,"format":"wav"}}`. **Это рабочий путь** (проверено на gemma4:12b: речь транскрибируется). В `core/openai_compat.to_openai_messages` маркер `media_kind=audio` выбирает `input_audio` вместо `image_url`.

> Практический вывод: аудио в botinok работает только с `backend=openai` и аудио-моделью (напр. `gemma4:12b`); при `backend=ollama` звук не доставляется.

## Транскодирование
Оба бэкенда ждут **WAV 16кГц моно PCM**, поэтому `tools/audio.py` всегда приводит вход (mp3/ogg/flac/m4a/webm/aiff/wav) в этот формат через ffmpeg (`_transcode_to_wav16k`). Это устраняет ошибку декодирования MP3/OGG на стороне сервера.

## Валидация
Формат распознаётся по magic-байтам с фолбэком на расширение; веб-источники проверяются на Content-Type и HTML-заглушки; есть лимит размера `AUDIO_MAX_BYTES` и стриминг-кап при скачивании.

## Предостережение
Аудио доходит только до сервера, у которого включена аудио-поддержка (PR #15243 ещё не релизнут). Без неё: `images[]`/`input_audio` → 400; `audios` молча игнорируется (модель отвечает «аудио не приложено»). Для моделей БЕЗ аудио-модальности слать звук нельзя — возможен «галлюцинативный» транскрипт (см. github.com/artokun/comfyui-mcp#1972). Надёжно работает только с genuinely omni-моделями на подходящем сервере.

## Связи
Инструмент — `entities/tools/audio.md`. Выбор модели — `entities/ollama_backend.md`. Смежная концепция для изображений — `concepts/vision_multimodal.md`.
