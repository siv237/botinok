# shell_exec — инструмент Ботинока

Плагин-папка: `tools/shell_exec/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Выполнение shell команд в отдельной PTY-сессии (dangerous mode)
- **Пакет:** `tools.shell_exec` · **Вход:** `shell_exec` · **Алиасы:** нет
- **Платформа передаёт в вызов:** `session_path`
- **Схема:** ручная, из [tool.json](./tool.json) (13 параметров)
- **Опасность:** shell — опасные действия (`run`/`send`/…): всегда требуют dangerous mode
- **Always-on:** нет
- **Тесты:** `tests/test_shell_exec_tool.py`

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `command` | string | нет |
| `cwd` | string | нет |
| `timeout_sec` | integer | нет |
| `action` | string | нет |
| `session_id` | string | нет |
| `input` | string | нет |
| `key` | string | нет |
| `pattern` | string | нет |
| `regex` | boolean | нет |
| `context` | integer | нет |
| `tail_lines` | integer | нет |
| `wait_timeout` | number | нет |
| `interactive` | boolean | нет |

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
venv/bin/python -m pytest tests/test_shell_exec_tool.py -q
venv/bin/python -u tests/test_plugin_folders.py   # контракт плагинов целиком
```
