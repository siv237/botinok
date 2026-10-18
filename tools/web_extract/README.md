# web_extract — инструмент Ботинока

Плагин-папка: `tools/web_extract/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Извлечь структурированные ресурсы со страницы: ссылки, картинки, заголовки, мета-теги, таблицы
- **Пакет:** `tools.web_extract` · **Вход:** `web_extract` · **Алиасы:** `web_extractor`
- **Платформа передаёт в вызов:** `session_path`, `progress`
- **Схема:** ручная, из [tool.json](./tool.json) (5 параметров)
- **Always-on:** нет
- **Тесты:** — (отдельного теста нет)

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `url` | string | да |
| `extract` | array | нет |
| `max_items` | integer | нет |
| `timeout_sec` | integer | нет |
| `headers` | array | нет |

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
