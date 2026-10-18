# audio — инструмент Ботинока

Плагин-папка: `tools/audio/` (`tool.json` + `__init__.py` + этот README).
Удалишь папку — инструмент исчезнет из каталога, payload и вызовов.

- **Назначение:** Анализ аудио мультимодальной (omni) моделью
- **Пакет:** `tools.audio` · **Вход:** `execute` · **Алиасы:** нет
- **Платформа передаёт в вызов:** `session_path`
- **Схема:** ручная, из [tool.json](./tool.json) (4 параметров)
- **Always-on:** нет
- **Тесты:** `tests/test_audio_local.py`

## Параметры (по схеме)

| параметр | тип | обязателен |
|----------|-----|------------|
| `audio_path` | string | нет |
| `url` | string | нет |
| `prompt` | string | нет |
| `timeout_sec` | integer | нет |

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
venv/bin/python -m pytest tests/test_audio_local.py -q
venv/bin/python -u tests/test_plugin_folders.py   # контракт плагинов целиком
```
