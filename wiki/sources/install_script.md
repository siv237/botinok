---
type: source
tags: [config, integration]
updated: 2026-08-23
sources: 1
status: stable
---

# install.sh

Установщик Ботинка в стиле Ollama. Source: `<repo>/install.sh`.

## Что делает
- Ставит системные зависимости: `python3-venv`, `lynx`, `git` (+ `ca-certificates`).
- Разворачивает проект в **`/opt/botinok`**.
- Создаёт алиас/симлинк `botinok` (в `/usr/local/bin` или `/usr/bin` для RHEL — там нет `/usr/local/bin` в PATH root'a).
- Поддержка **macOS** (BIN_DIR `/usr/local/bin`; API логов — `log show`).
- Создаёт runtime-директории: `~/.botinok/sessions`, `~/.botinok/skills`, `~/.botinok/experience`.
- Определяет версию из git (`0.2 | дата | хеш`).

## Установка
```bash
curl -sSL https://raw.githubusercontent.com/siv237/botinok/main/install.sh | sudo bash
```

## Производные страницы
`entities/botinok_cli.md` · `concepts/self_update.md` · `sources/readme.md`
