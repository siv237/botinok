# session_memory — инструмент Ботинока

Плагин-папка: `tools/session_memory/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Протокольный доступ к истории сессии: точные timestamps, строгий порядок ходов (turn_id 1..N), полный текст сообщений и указатели на артефакты/инструменты
- **Пакет:** `tools.session_memory` · **Вход:** `session_memory_tool` · **Алиасы:** нет
- **Платформа передаёт в вызов:** `session_path`
- **Схема:** ручная, из [tool.json](./tool.json) (14 параметров)
- **Always-on:** да (ядро харнесса)
- **Тесты:** — (отдельного теста нет)

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `action` | string | да |
| `session_path` | string | нет |
| `turn_id` | integer | нет |
| `query` | string | нет |
| `blocks` | string | нет |
| `note` | string | нет |
| `since` | string | нет |
| `until` | string | нет |
| `role` | string | нет |
| `has_tool_calls` | boolean | нет |
| `limit` | integer | нет |
| `offset` | integer | нет |
| `include_content` | boolean | нет |
| `include_thinking` | boolean | нет |

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
