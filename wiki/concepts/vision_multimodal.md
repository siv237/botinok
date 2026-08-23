---
type: concept
tags: [llm, session]
updated: 2026-08-23
sources: 2
status: stable
---

# Мультимодальность (Vision)

Возможность анализировать изображения. Инструмент `vision` передаёт картинку в мультимодальную модель (llava, bakllava, Qwen3.5 и др.) в base64. → `entities/tools/vision.md`

## Обработка изображений (автоматически)
- **Валидация**: формат, preflight-проверка перед отправкой; проверка Content-Type для веб-изображений; детекция HTML-заглушек.
- **Конвертация**: неподдерживаемые/прозрачные → RGB JPEG.
- **Авторесайз** до лимитов модели (4096×4096 для Qwen3.5; уменьшает, но не увеличивает).

## Источники
- Локальный файл (`image_path`) или URL (`url`) — скачивается с таймаутом.

## Связанные возможности
- ASCII-арт из изображений для консоли — `core/image_ascii.py` (`image_to_halftones`, `image_to_quarters`, `image_to_fullcolor`).

## Связи
Инструмент — `entities/tools/vision.md`. Выбор модели с поддержкой vision — `entities/ollama_backend.md`.
