# skills — инструмент Ботинока

Плагин-папка: `tools/skills/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Менеджер AI скиллов
- **Пакет:** `tools.skills` · **Вход:** `skills` · **Алиасы:** нет
- **Платформа передаёт в вызов:** ничего
- **Схема:** ручная, из [tool.json](./tool.json) (8 параметров)
- **Always-on:** нет
- **Тесты:** — (отдельного теста нет)

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `action` | string | да |
| `name` | string | нет |
| `query` | string | нет |
| `url` | string | нет |
| `content` | string | нет |
| `task` | string | нет |
| `limit` | integer | нет |
| `sort` | string | нет |

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
