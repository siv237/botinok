---
type: entity
tags: [tool, llm, audio]
updated: 2026-08-24
sources: 1
status: stable
---

# Инструмент audio

`tools/audio.py` → функция `execute(...)`. Анализ аудио мультимодальной (omni) моделью (Qwen3-Omni, Qwen3.5-Omni/27B и др.). Аудиофайл конвертируется в base64 и передаётся в LLM. → `concepts/audio_multimodal.md`

## Параметры
- `audio_path` — локальный файл (wav, mp3, ogg, flac, m4a, webm, aiff).
- `url` — URL аудио (альтернатива).
- `prompt` — вопрос к модели (по умолчанию «Опиши, что ты слышишь в этом аудио»).
- `timeout_sec` — таймаут скачивания URL.

## Обработка аудио
- Детект формата по magic-байтам (`_detect_mime`): RIFF/WAVE, MP3 (ID3/frame-sync), OGG, FLAC, WebM/MKV, MP4/M4A, AIFF; фолбэк по расширению.
- Проверка Content-Type для web (`_download_audio`, `_looks_like_html`), валидация RIFF-контейнера (`_validate_audio`).
- Лимит размера `AUDIO_MAX_BYTES` (по умолчанию 50 МБ). Без пережатия/транскодирования — аудио уходит как есть.

## Транспорт в LLM
- **Ollama `/api/chat`**: правильное поле — **`audios`** (множественное, base64 **WAV**), а не `images[]`/`audio`. Доступно в Ollama-сборках с нерелизнутой поддержкой аудио (PR ollama/ollama#15243). Аудио всегда транскодируется в **WAV 16кГц моно PCM** (`_transcode_to_wav16k` через ffmpeg), т.к. Ollama принимает только WAV (детект по magic-байтам). → `concepts/audio_multimodal.md`
- **OpenAI-dialect**: переводится в content-part `{"type":"input_audio","input_audio":{"data":...,"format":"wav"}}` (`core/openai_compat.to_openai_messages`, маркер `media_kind=audio`).

## Связи
Зарегистрирован как `audio`. Требует omni-модель с поддержкой аудио. Подробная концепция — `concepts/audio_multimodal.md`.
