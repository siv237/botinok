---
type: entity
tags: [network, config, integration]
updated: 2026-09-21
sources: 1
status: stable
---

# net_config — единая сетевая настройка (прокси)

`core/net_config.py` — единственный источник прокси для веб-под-инструментов.
Задача: агент пишет адрес «как удобно», инструмент нормализует и раздаёт его
каждому движку в нужной форме.

## Модель и приоритет
`{scheme, host, port, user, password, no_proxy}`. Приоритет источника:
параметр вызова > файл сессии (`<session>/project/.botinok/net.json`) >
глобальный `config.cfg [Tools] Proxy/NoProxy` > env (`HTTP(S)_PROXY`,
`ALL_PROXY`, `NO_PROXY`). **Пустые env-значения игнорируются** — иначе httpx
молча обходит прокси (проверено: `https_proxy=""` отключал рабочий `HTTPS_PROXY`).

## Нормализация (прощающий ввод)
`normalize_proxy`: `17277` → `http://127.0.0.1:17277`; `host:port`;
`host:port user pass`; `scheme://user:pass@host:port`; `none`/`clear` → снять.
Схемы: http/https/socks5/socks5h/socks4/all. `mask_proxy` скрывает пароль.

## Раздача движкам
- `httpx_proxy` — для всех httpx-клиентов (web/image/vision/audio);
- `requests_proxies` — для requests;
- `aria2c_args` — `--all-proxy=`/`--no-proxy=` (aria2c **не читает env**);
- `subprocess_env` — env для lynx/git (с зачисткой пустых переменных).

## Управление (`web action=proxy`)
`show` (эффективный + источник, маска), `set` (`scope=session|global`),
`clear`, `test` (TCP + реальный запрос по httpx и aria2c отдельно, с
подтверждением агенту). Прокси **не навязывается**: без настройки сеть работает
напрямую; при сбое инструмент лишь советует задать и проверить прокси.

## Границы
Прокси — настройка веб-кита (внешние сайты). Соединения к LLM-бэкенду
(`botinok.py`, `openai_compat`, `session_manager`, `config_wizard`) по умолчанию
прокси не получают.

## Связи
Потребители: `entities/tools/web.md`, `entities/tools/image.md`,
`entities/tools/vision.md`, `entities/tools/audio.md`.
Тест: `tests/test_net_config.py`.
