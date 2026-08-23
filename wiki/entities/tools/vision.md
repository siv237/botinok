---
type: entity
tags: [tool, llm, vision]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент vision

`tools/vision.py` → функция `execute(...)`. Анализ изображений мультимодальной моделью (llava, bakllava, Qwen3.5 и др.). Изображение конвертируется в base64 и передаётся в LLM. → `concepts/vision_multimodal.md`

## Параметры
- `image_path` — локальный файл (jpg, png, gif, webp, bmp).
- `url` — URL изображения (альтернатива).
- `prompt` — вопрос к модели (по умолчанию «Опиши что ты видишь»).
- `timeout_sec` — таймаут скачивания URL.

## Обработка изображений
- Автовалидация формата (`_validate_and_process_image`), проверка Content-Type для web (`_download_image`, `_looks_like_html`).
- Автоконвертация в RGB JPEG при необходимости (прозрачность/неподдерживаемые форматы).
- **Авторесайз** до лимитов модели (4096×4096 для Qwen3.5; уменьшает, но не увеличивает).

## Связи
Зарегистрирован как `vision`. Подробная концепция — `concepts/vision_multimodal.md`. ASCII-арт из изображений — `core/image_ascii.py`.
