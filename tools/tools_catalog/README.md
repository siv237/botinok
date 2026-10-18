# tools — инструмент Ботинока

Плагин-папка: `tools/tools_catalog/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Менеджер инструментов: краткий каталог всех инструментов (action=list) и ступенчатое раскрытие схем
- **Пакет:** `tools.tools_catalog` · **Вход:** `tools_catalog_tool` · **Алиасы:** нет
- **Платформа передаёт в вызов:** `session_path`
- **Схема:** ручная, из [tool.json](./tool.json) (2 параметров)
- **Always-on:** да (ядро харнесса)
- **Тесты:** `tests/test_tools_catalog.py`

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `action` | string | да |
| `name` | string | нет |

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
venv/bin/python -m pytest tests/test_tools_catalog.py -q
venv/bin/python -u tests/test_plugin_folders.py   # контракт плагинов целиком
```
