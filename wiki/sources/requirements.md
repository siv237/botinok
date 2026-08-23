---
type: source
tags: [config, integration]
updated: 2026-08-23
sources: 1
status: stable
---

# requirements.txt

Файл зависимостей Python. Source: `<repo>/requirements.txt`.

## Зависимости (фактические)
`requests` · `rich` · `inquirer` · `configparser` (stdlib, требуется для проекта) · `Pillow` · `selectolax>=0.3.21` · `httpx>=0.27.0` · `readchar` · `textual`

## Куда используется
- **rich** — Rich Live / форматирование интерфейса. → `concepts/streaming_tui.md`, `comparisons/rich_vs_textual.md`
- **textual** — TUI. → `entities/textual_ui.md`
- **selectolax / httpx** — `web_extract` (быстрый C-парсер HTML). → `entities/tools/web-extract.md`
- **requests** — HTTP (Ollama, OpenAI-compat). → `entities/openai_compat.md`
- **Pillow** — обработка изображений (vision). → `entities/tools/vision.md`
- **readchar** — чтение клавиш без блокировки (прокрутка). → `concepts/scrollback.md`
- **inquirer** — выбор/мастер (`--wizard`, меню). → `concepts/config_priority.md`

## Обновление пакетов
`botinok --update-packages` / `-U` (или `--update`): `pip install --upgrade pip setuptools wheel -r requirements.txt`. → `concepts/self_update.md`

## Производные страницы
Зависимости разнесены по страницам инструментов/интерфейсов, перечисленных выше.
