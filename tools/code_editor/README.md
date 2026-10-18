# code_editor — инструмент Ботинока

Плагин-папка: `tools/code_editor/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Единый редактор файлов
- **Пакет:** `tools.code_editor` · **Вход:** `code_editor` · **Алиасы:** нет
- **Платформа передаёт в вызов:** `session_path`, `dangerous_mode`
- **Схема:** ручная, из [tool.json](./tool.json) (15 параметров)
- **Опасность:** session_write — запись/замена вне папки сессии требует dangerous mode
- **Always-on:** нет
- **Тесты:** `tests/test_code_editor.py`

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `action` | string | да |
| `path` | string | да |
| `content` | string | нет |
| `old_text` | string | нет |
| `new_text` | string | нет |
| `edits` | array | нет |
| `replace_all` | boolean | нет |
| `create` | boolean | нет |
| `expected_sha256` | string | нет |
| `offset` | integer | нет |
| `limit` | integer | нет |
| `line_numbers` | boolean | нет |
| `checkpoint` | string | нет |
| `force` | boolean | нет |
| `kind` | string | нет |

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
venv/bin/python -m pytest tests/test_code_editor.py -q
venv/bin/python -u tests/test_plugin_folders.py   # контракт плагинов целиком
```
