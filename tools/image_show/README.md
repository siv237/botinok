# image — инструмент Ботинока

Плагин-папка: `tools/image_show/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Показать изображение В ЧАТЕ (не анализ, а отображение)
- **Пакет:** `tools.image_show` · **Вход:** `image` · **Алиасы:** нет
- **Платформа передаёт в вызов:** `session_path`
- **Схема:** ручная, из [tool.json](./tool.json) (7 параметров)
- **Always-on:** нет
- **Тесты:** `tests/test_image_catalog.py`, `tests/test_image_icc.py`, `tests/test_image_in_chat.py`, `tests/test_image_render.py`, `tests/test_image_scaling.py`, `tests/test_lazy_images.py`

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `action` | string | нет |
| `source` | string | нет |
| `path` | string | нет |
| `url` | string | нет |
| `alt` | string | нет |
| `id` | string | нет |
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
venv/bin/python -m pytest tests/test_image_catalog.py -q
venv/bin/python -u tests/test_plugin_folders.py   # контракт плагинов целиком
```
