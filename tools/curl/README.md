# curl — инструмент Ботинока

Плагин-папка: `tools/curl/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Legacy-алиас web (HTTP-запросы, JSON, файлы)
- **Пакет:** `tools.curl` · **Вход:** `curl` · **Алиасы:** нет
- **Платформа передаёт в вызов:** `session_path`, `progress`
- **Схема:** ручная, из [tool.json](./tool.json) (12 параметров)
- **Опасность:** session_output — запись вывода в файл вне папки сессии требует dangerous mode
- **Always-on:** нет
- **Тесты:** — (отдельного теста нет)

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `url` | string | да |
| `method` | string | нет |
| `body` | string | нет |
| `json_body` | object | нет |
| `headers` | array | нет |
| `timeout_sec` | integer | нет |
| `max_bytes` | integer | нет |
| `follow_redirects` | boolean | нет |
| `jq_filter` | string | нет |
| `output_path` | string | нет |
| `resume` | boolean | нет |
| `expected_sha256` | string | нет |

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
venv/bin/python -m pytest tests -q -q
venv/bin/python -u tests/test_plugin_folders.py   # контракт плагинов целиком
```
