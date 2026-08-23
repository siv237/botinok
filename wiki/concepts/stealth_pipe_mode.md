---
type: concept
tags: [tui]
updated: 2026-08-23
sources: 2
status: stable
---

# Stealth и Pipe режимы

Режимы для автоматизации и скриптов. → `entities/botinok_cli.md`

## Stealth
`botinok --stealth "..."` — выводит **только финальный ответ** модели, без ASCII-арта, панелей и статистики. Идеален для автоматизации (`ask_ollama_stealth`).

## Pipe (конвейер)
`botinok` автоматически определяет данные в **stdin**. Примеры:
- `tail -n 100 /var/log/syslog | botinok "Найди критические ошибки"`
- `cat script.py | botinok "Объясни что делает этот код"`

Если не интерактивный терминал (и есть stdin) — бот автоматически переходит в **stealth** (только ответ).

## Связи
CLI/флаги — `entities/botinok_cli.md`. Поток без интерфейса — `ask_ollama_stealth`.
