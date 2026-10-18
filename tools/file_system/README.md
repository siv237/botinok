# file_system — инструмент Ботинока

Плагин-папка: `tools/file_system/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Файлы и система
- **Пакет:** `tools.file_system` · **Вход:** `file_system_tool` · **Алиасы:** нет
- **Платформа передаёт в вызов:** `session_path`, `dangerous_mode`
- **Схема:** ручная, из [tool.json](./tool.json) (13 параметров)
- **Опасность:** session_write — мутации (delete/move/copy/mkdir/chmod/symlink/touch) вне папки сессии требуют dangerous mode
- **Always-on:** нет
- **Тесты:** `tests/test_file_system_grep.py`

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `action` | string | да |
| `path` | string | нет |
| `dest` | string | нет |
| `mode` | string | нет |
| `command` | string | нет |
| `algo` | string | нет |
| `pattern` | string | нет |
| `recursive` | boolean | нет |
| `content_query` | string | нет |
| `max_results` | integer | нет |
| `max_bytes` | integer | нет |
| `offset` | integer | нет |
| `limit` | integer | нет |

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
venv/bin/python -m pytest tests/test_file_system_grep.py -q
venv/bin/python -u tests/test_plugin_folders.py   # контракт плагинов целиком
```
