---
type: entity
tags: [tool, network, integration]
updated: 2026-09-21
sources: 6
status: stable
---

# Инструмент web (единый добыватель данных)

`tools/web.py` → функция `execute(...)`. Один инструмент вместо четырёх:
`web_search`, `open_url`, `web_extract`, `curl` остаются **legacy-обёртками**
поверх этого ядра. → `concepts/web_kit.md`

## Действия (`action`)
| action | Назначение |
|--------|-----------|
| `auto` | получить URL и выбрать стратегию по content-type (по умолчанию) |
| `open` | читаемый основной текст страницы в markdown (`_html_to_markdown`) |
| `extract` | структура: `links` / `images` / `headings` / `meta` / `tables` + `css`-селекторы |
| `images` | найти прямые картинки (со страницы `url` или из выдачи `query`); каждая ссылка проверяется на живую картинку |
| `json` | JSON: jq-фильтр (`jq`) или сводка по структуре |
| `download` | скачать/докачать файл, ISO или торрент (aria2c), проверить тип/хеш |
| `downloads` | память загрузок: что/куда/целое (глобальная, вне сессий) |
| `search` | поиск (DuckDuckGo HTML через httpx, fallback — lynx) |
| `proxy` | прокси: `command=show/set/clear/test` (нормализация, проверка, подтверждение) |
| `help` | справка |

## Помощник-навигатор после любого fetch
Любой успешный `open`/`auto`/`extract` добавляет в харнес строку
`📦 На странице: 🖼 images=N · links=N · headings=N · tables=N · meta=N`
(`_page_inventory`) и **готовые вызовы** под фактическое содержимое
(`_inventory_actions`): `extract images`, `image(source=…)`, `extract links/tables`,
а для JS-страниц без прямых `<img>` — подсказку `action=images`.
Так модель видит, что есть на странице и как это достать, без угадывания.

## Поиск изображений (`action=images`)
Провайдер не зашит в код: инструмент берёт **любую** страницу (`url`) или
выдачу поиска (`query`), собирает прямые картинки generic-парсером
(`_collect_image_urls`: `img`, ленивые атрибуты, `srcset`, `og:image`/`twitter:image`)
и **проверяет каждую ссылку** (`_verify_image`: HTTP-код + `content-type` +
magic-байты). Возвращаются только живые; ранжирование — по размеру (фото обычно
крупнее иконок), затем по «фотографичности» URL. Готовые `image(source=…)` — в
«Следующих шагах».

## Загрузки: aria2c, память, докачка, хеши
- Действие `download` идёт через **`aria2c`** (`tools/download_manager.py`): докачка
  (`--continue`), несколько соединений, большие файлы (ISO) и **торренты**
  (`magnet:?…` или `https://…​.torrent`, `--seed-time=0`).
- Скачанное **не обрезается**; при превышении лимита — явная ошибка (старый curl
  ошибочно отказывал, новый web раньше молча резал файл по `max_bytes`).
- **HTML-заглушки** (ошибка/капча/редирект вместо файла) распознаются и не
  сохраняются.
- **Проверка хеша**: `expected_sha256` — при несовпадении файл удаляется.
- **Память загрузок глобальна** (`~/.botinok/downloads/history.json`,
  `action=downloads`): что скачано, куда, целое ли (наличие, размер, sha256, тип
  через `file`). Новая сессия может не качать заново — инструмент вернёт файл из
  памяти, если он цел; недокачанные помечаются и предлагаются к `resume=true`.
- `curl` (legacy) делегирует сюда же, поэтому получает aria2c/память/докачку.

## Движки загрузки: aria2c vs HTTP-клиент
- **aria2c** — большие файлы, докачка, торренты/magnet, проверка `sha256`.
- **HTTP-клиент (httpx)** — сложные HTTP-запросы: методы, тело, JSON, заголовки,
  API (и загрузки, где aria2c не проходит).
- Если aria2c **упал**, загрузка **автоматически повторяется через httpx**
  (`_download_file` → `_httpx_download`); ошибка aria2c переводится в
  человекочитаемый вид (`_aria2c_error_text`). Основание — сессия
  `20260824_164041_visual_run`: у движков разная маршрутизация (то, что не
  проходит у aria2c, проходит у httpx, и наоборот).

## Прокси (настраивает агент; без хардкодов)
`core/net_config.py` — единый источник прокси. Приоритет: параметр вызова >
файл сессии (`project/.botinok/net.json`) > глобальный `config.cfg [Tools] Proxy`
> env. **Пустые env-переменные игнорируются** (иначе httpx молча обходит прокси).
- Ввод прощающий: `17277`, `host:port`, `host:port user pass`,
  `scheme://user:pass@host:port`, `none` → нормализуется в `scheme://…` (`normalize_proxy`).
- Раздаётся в нужной движку форме: `httpx_proxy`, `requests_proxies`,
  `aria2c_args` (`--all-proxy`/`--no-proxy`; aria2c не читает env), `subprocess_env`.
- Наследуют: `web`, `image`, `vision`, `audio`, `curl` и обёртки. Соединения к
  LLM-бэкенду прокси **не** получают (отдельная настройка).
- Действия: `show` (эффективный + источник, пароль маскируется), `set`
  (`scope=session|global`), `clear`, `test` (TCP + реальный запрос по httpx и
  aria2c отдельно — подтверждает работоспособность агенту).

## Параметры
`url`, `query`, `extract`, `css`, `jq` (алиас `jq_filter`), `output_path`,
`headers`, `timeout_sec`, `max_bytes`, `follow_redirects`, `max_items`,
`session_path`, `resume`, `expected_sha256`, `method`, `json_body`/`body`,
`proxy` (разовый прокси), `no_proxy`, `scope`, `command` (для `action=proxy`).

### Локальные файлы в теле запроса
Чтобы отправить файл в API без ручного base64, в `json_body` пишется маркер
`{"$file_base64": "/путь/к/файлу"}` — `web` сам читает и кодирует его
(`_resolve_file_markers`). Так байты **не проходят через модель**.
Пример (Ollama): `messages:[{"role":"user","content":"…","images":[{"$file_base64":"/…/photo.jpg"}]}]`.
→ `entities/safe_ops.md`

## Работа с веб-API (в т.ч. в простом режиме)
`web` поддерживает HTTP-методы `GET`/`POST`/`PUT`/`PATCH`/`DELETE` и тело
запроса: `method=POST`, `json_body={…}` (объект) или `body` (строка). Это
позволяет обращаться к API, которые не работают по GET (например Ollama
`/api/generate`, `/api/chat`, `/api/show`) — **без dangerous mode**: сеть/API
не относятся к опасным локальным операциям. GET-запросы без тела по-прежнему
идут через aria2c (докачка/файлы), запросы с телом — обычным HTTP-путём.

## Умное поведение (харнес)
Каждый ответ заканчивается блоком:
- мета: `action`, `kind`, `type`, `size`, `elapsed`, `final`, `saved`, `items`, `truncated`;
- `provenance`: `readable | extracted | projected | raw | saved | error`;
- «💡 Совет» — что делать дальше;
- «➡ Следующие шаги (web)» — готовые вызовы.

Поиск возвращает структурированные результаты (`title`/`url`/`snippet`) и
сразу предлагает `action=open` для верхнего результата. Небезопасные
jq-фильтры (`@file`, `tee`, перенаправления) блокируются.

## Умные ошибки (методика, без доменной конкретики)
Никакие значения конкретных API в коде не зашиты. Работает общая методика:
- тело ответа сервера пробрасывается модели (`Ответ сервера: <reason>`);
- из текста ошибки извлекается имя параметра, упомянутого сервером
  (`_params_named_in_reason`), и в «Следующих шагах» предлагается вызов без
  этого параметра (`_strip_params`); допустимое значение модель выбирает сама;
- беззнаковая правка кодирования: безопасные процент-экранирования
  (`%2F`, `%3A`, `%2C`, `%40`) декодируются с одним повтором (`_decode_safe_escapes`),
  пометка `fixed=…` в мете. Структурные `&`, `=`, `#`, `?` не трогаются.
- Основание: диагностика сессии `20260918_203213` — без тела ошибки модель
  сделала 4 неудачных запроса и угадывала параметры.

## Контекстная дисциплина
Большие тела (HTML/JSON) сохраняются в папку сессии, в ответ идёт превью,
путь и подсказка, как прочитать срез.

## Безопасность
Только `http`/`https`. Запись (`output_path`) вне папки сессии требует
dangerous mode — гейт в `ToolManager.call_tool` (`allowed_in_session`).
→ `concepts/dangerous_mode.md`

## Legacy-обёртки
- `curl` → `action=json` при `jq_filter`, иначе `download` (при `output_path`) или `auto`.
- `web_extract` → `action=extract`.
- `open_url` → `action=open` (добавляет `https://`, если схема опущена).
- `web_search` → `action=search`.

## Связи
Реестр: `entities/tool_manager.md`. Механика: `concepts/web_kit.md`,
`concepts/function_calling.md`. Тест: `tests/test_web_kit.py`.
