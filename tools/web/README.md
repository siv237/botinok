# web — инструмент Ботинока

Плагин-папка: `tools/web/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Единый добыватель данных из сети
- **Пакет:** `tools.web` · **Вход:** `execute` · **Алиасы:** нет
- **Платформа передаёт в вызов:** `session_path`, `progress`
- **Схема:** ручная, из [tool.json](./tool.json) (26 параметров)
- **Опасность:** session_output — запись вывода/скачанного файла вне папки сессии требует dangerous mode
- **Always-on:** нет
- **Тесты:** `tests/test_web_jobs.py`, `tests/test_web_kit.py`, `tests/test_web_mirror.py`, `tests/test_web_mirror_page.py`, `tests/test_web_progress.py`

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `action` | string | нет |
| `url` | string | нет |
| `method` | string | нет |
| `json_body` | object | нет |
| `body` | string | нет |
| `query` | string | нет |
| `extract` | array | нет |
| `css` | array | нет |
| `jq` | string | нет |
| `output_path` | string | нет |
| `resume` | boolean | нет |
| `verify` | boolean | нет |
| `expected_sha256` | string | нет |
| `headers` | array | нет |
| `timeout_sec` | integer | нет |
| `max_bytes` | integer | нет |
| `follow_redirects` | boolean | нет |
| `max_items` | integer | нет |
| `proxy` | string | нет |
| `no_proxy` | string | нет |
| `scope` | string | нет |
| `command` | string | нет |
| `background` | boolean | нет |
| `name` | string | нет |
| `job_id` | string | нет |
| `wait` | boolean | нет |

## Контракт плагина

- Манифест — единственный источник правды о подключении: [tool.json](./tool.json).
- Общие правила, поля манифеста и тезисы «умных инструментов» —
  [../_template/README.md](../_template/README.md) и
  [wiki/concepts/tool_plugins.md](../../wiki/concepts/tool_plugins.md).
- Подключение/отключение — только файловой системой: положил папку в `tools/` —
  инструмент появился (каталог, `tools(action=enable)`, payload), удалил папку —
  исчез (без правок в `core/`).

## Проверка

```bash
venv/bin/python -m pytest tests/test_web_jobs.py -q
venv/bin/python -u tests/test_plugin_folders.py   # контракт плагинов целиком
```
