---
type: entity
tags: [tool, network, integration, llm]
updated: 2026-10-10
sources: 1
status: stable
---

# Фоновые веб-задачи (web_jobs)

`tools/web_jobs.py` — реестр параллельных фоновых задач для инструмента `web`.
Опция: **обычные вызовы `web` остались синхронными**, фон включается только по
явной просьбе агента (`background=true`). → `entities/tools/web.md`,
`concepts/web_kit.md`

## Механика
- `WebJobRegistry` — синглтон (по образцу `ShellSessionRegistry`), тредобезопасен,
  живёт в процессе. `WebJob` — одна задача: `job_id` (`wNNN-xxxxxx`), имя, статус
  `running/done/error`, прогресс, результат, флаги `notified`/`cancelled`.
- `web action=<сетевое> background=true name=метка` → `_submit_background`
  заводит daemon-тред, выполняющий `web.execute(...)` с progress-колбэком в
  job; агенту сразу возвращается `job_id` (harnest-ответ «⏳ задача запущена»).
- Опрос: `web action=jobs` — таблица всех задач (что готово ✅, что идёт ⏳ с
  прогрессом/процентами); `web action=job job_id=…` — статус или **полный
  результат**; `wait=true` — подождать до `timeout_sec`; `command=kill` —
  пометить убитой (best-effort: тред завершится сам, результат отбрасывается).

## Уведомления (инкрементальные)
`format_notifications()` отдаёт харнесу цикла агента:
- события завершившихся/сбоивших задач, **ещё не доставленных** (флаг
  `notified`) — каждое ровно один раз;
- напоминание о висящих задачах (имена, id, прогресс, сколько идут) — модель
  помнит, что ждёт, и не считает их готовыми.

Харнес вызывает его на границах: начало хода и конец каждого тул-раунда
(`core/textual_integration.py::_web_jobs_notice`, `botinok.py`), вставляя
сообщение `role:user` в `messages` и `context.json`.

## UI
`textual_app::_sync_web_jobs` (в `_tick_stats`) держит карточки задач в панели
инструментов: имя+id, статус, живой прогресс, превью результата. Карточки
помечены `job: True` и **исключены** из `turn_in_progress`/`_task_active`/
детектора зависаний — фон не имитирует активность хода и не ловит Esc-диалог.

## Уборка
Реестр держит до 40 завершённых задач и чистит старше 1 часа
(`cleanup_old`, вызывается из `action=jobs`).

## Связи
Инструмент: `entities/tools/web.md`. Концепция: `concepts/web_kit.md`.
Параллельный прототип (PTY-сессии): `entities/shell_session.md`.
Модель исполнения tool_calls: `concepts/function_calling.md`.
