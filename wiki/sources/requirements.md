---
type: source
tags: [config, integration]
updated: 2026-09-17
sources: 2
status: stable
---

# requirements.txt

Файл зависимостей Python. Source: `<repo>/requirements.txt`.

## Зависимости (фактические)
`requests` · `configparser` (stdlib, требуется для проекта) · `Pillow` · `selectolax>=0.3.21` · `httpx>=0.27.0` · `textual`

## Куда используется
- **textual** — единственный UI (TUI + диалоги выбора/мастера); Rich идёт транзитивной зависимостью Textual и используется только как средство рендеринга внутри Textual. → `entities/textual_ui.md`, `comparisons/rich_vs_textual.md`
- **selectolax / httpx** — `web_extract` (быстрый C-парсер HTML). → `entities/tools/web-extract.md`
- **requests** — HTTP (Ollama, OpenAI-compat). → `entities/openai_compat.md`
- **Pillow** — обработка изображений (vision, ASCII-баннер). → `entities/tools/vision.md`

## Удалено в 0.4
`rich` (прямая зависимость), `inquirer` и `readchar` — заменены Textual
(`core/textual_prompts.py`, `core/session_picker.py`).

## Обновление пакетов
`botinok --update-packages` / `-U` (или `--update`): `pip install --upgrade pip setuptools wheel -r requirements.txt`. → `concepts/self_update.md`

## Производные страницы
Зависимости разнесены по страницам инструментов/интерфейсов, перечисленных выше.
