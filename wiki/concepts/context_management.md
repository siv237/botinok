---
type: concept
tags: [session, llm]
updated: 2026-10-18
sources: 4
status: stable
---

# Управление контекстом

Работа с ограниченным контекстом LLM — ключевая тема проекта (малый VRAM). Реализовано в `core/textual_integration.py` (TI) + `core/session_digest.py` + промпты `prompts/context_overflow_*.txt`. Исследования и план — [[context_memory_research]].

## Оценка токенов и калибровка
- База: `len//4` (`_estimate_tokens`, TI:160); после каждого ответа сравнение с фактическим `prompt_eval_count` → EMA-поправка k per-model (`calibrate_token_estimator`, TI:208), персист в `performance.log`, восстановление при резюме (`restore_token_calibration`, TI:243). Эффект: пороги начинают означать реальные токены.

## Мягкий тримм (перед каждым запросом)
`_prepare_messages_for_ollama` (TI:378):
- бюджет = `min(num_ctx, HARD_CTX_PCT·num_ctx) − reserve(1200)` — заведомо НИЖЕ хард-триггера (регресс 2026-10-10: при бюджете выше триггера тримм был мёртвым кодом);
- вытеснение целыми сегментами (user→user, `_segment_indices`, TI:269), внутри — неделимые единицы `assistant.tool_calls ↔ tool` (TI:288); инвариант пар не рвётся;
- гарантия: в prepared остаётся ≥1 непустой user (LiteLLM иначе отвечает 400);
- выбрасываемое — в артефакт `context_trim_*.json`;
- вместо notice вставляется **FORGOTTEN_INDEX** (см. ниже).

## FORGOTTEN_INDEX — «скользящее окно о забытом»
Одна system-реплика, регенерируется на каждый запрос (в историю не пишется), бюджет 600 токенов (TI:309-375): строки окон вызова модели из `core/session_digest` (облако терминов + указатель `turn_id` + подписи инструментов + ctx), древние сворачиваются иерархически (`merge_old_lines`). Подписи ходов — из `sign_step` (tools/sign_step/). Модель инструктирована `tool_policy.txt`:15: не догадываться о забытом — смотреть по указателю через `session_memory get_turn/search/windows`.

## Prompt-cache сервера: префикс обязан быть стабильным (2026-10-18)
Ollama кеширует KV-кеш по **наибольшему общему префиксу отрендеренного промпта** (в логе сервера: `selected slot by LCP similarity`, `cached n_tokens`, `context checkpoint`). Поэтому ботинок обязан отправлять «стабильный префикс + хвост»: любой байт, вставленный в середину, заставляет сервер пересчитать всё после него. Видно по `prompt_eval_cached_count`; `prompt_eval_count` — это весь промпт, а не пересчитанная часть (обнулённый кеш по нему не отличить).

Что ломало кеш:
- **`tools` рендерятся в голову промпта** — смена набора инструментов обнуляет кеш целиком. Замер на `ollama.localnet` (bonsai-2:9b): те же `messages` и `tools` → `cached 852/856`; добавили один инструмент → `cached 0/903`. Ступенчатое раскрытие инструментов (`tools action=enable`) — плановая причина сброса, а не баг.
- **Hoist system-реплик в голову** в `_prepare_messages_for_ollama` (`trimmed = system_msgs + kept`): памятка, добавленная по ходу (журнал, notice, checkpoint), влезала в середину головы. Плюс `FORGOTTEN_INDEX` регенерировался на каждый запрос ровно в голове, а тримм сдвигал окно → расхождение сразу после системного блока.
- Живой симптом (сессия `20261018_225313_visual_run`): каждый tool-раунд полный переэвал 7912 → 8422 → 8920 → 13518 → … → 28655 токенов, 45–70 с на раунд, `cached ≈ 0`, similarity 0.191.

Исправлено: `_prepare_messages_for_ollama` (TI, копия в `botinok.py`) **сохраняет хронологический порядок** — system-реплики остаются на своих местах, `FORGOTTEN_INDEX`/notice дописываются в **хвост**. Ollama спокойно принимает system-реплики в середине диалога (рендерер `qwen3.5`, проверено). Симуляция на реальных функциях: общий префикс между раундами 7/8 → 8/8 и 8/11 → 11/11.

Наблюдаемость: `prompt_eval_cached_count` читается из чанка, пишется в `metrics` (session_raw.log) и в `performance.log` (`token_calibration`: `prompt_eval_cached_count`, `cached_pct`). Модель рассуждений в контекст **не** попадает: в payload assistant-реплики идут без `thinking` (TI), в `messages.json` полей `thinking` нет, а рендерер `qwen3.5` это поле игнорирует (проверено: `prompt_eval_count` не меняется при `thinking` в 1200 символов).

Остаточные сбросы кеша по дизайну: смена набора `tools` и сам тримм (окно сдвигается — префикс меняется неизбежно). Вывод для практики: тримм должен быть редким и крупным, включение инструментов — пачкой в начале хода.

## Big-bang reset (переполнение/зацикливание)
`_ollama_summarize_and_reset_context` (TI:733):
1. вся история → артефакт `context_overflow_full_*.json`;
2. один LLM-вызов (`num_predict=450`, промпты `context_overflow_summary/user.txt`) → проза `SESSION_PROTOCOL`;
3. история = system + один протокол (`context_overflow_protocol.txt`); старые протоколы вытесняются (`OVERFLOW_PROTOCOL_MARKERS`, TI:313) — иначе копились сотни (регресс 2026-10-10).

**Триггер ровно один** (2026-10-18): `hard_ctx_threshold` — `prompt_eval_count+eval_count ≥ 0.90·num_ctx`, то есть реальное исчерпание контекста. Бюджет мягких продолжений: `MAX_AUTO_RECOVERIES_PER_TURN=2`, дальше `auto_continue.txt` вешается поверх.

Раньше big-bang вызывался ещё двумя поводами, **не связанными с объёмом контекста**, и стирал память на 80-м вызове инструментов в ходе (`max_tool_rounds_exceeded`) или на повторе в ответе (`repetition_detected`) — при плавающем контексте это чистый ущерб (регрессия: сессия обнулялась при заполнении на проценты). Теперь:
* **предел раундов** (`MAX_TOOL_ROUNDS_PER_TURN=80`, настраивается `[Ollama] MaxToolRounds`, `0` — без предела) — ход завершается, история цела; в контекст добавляется system-пометка `prompts/tool_rounds_limit.txt`, модель просят подвести итог;
* **повтор ответа** (`_detect_repetition`, `REPEAT_LINE_WINDOW=40`/`REPEAT_LINE_MIN_OCCURRENCES=6`) — просим не повторяться (`prompts/repetition_notice.txt`) до `MAX_REPETITION_RECOVERIES_PER_TURN=2`, затем ход завершается; память не стирается.
`messages.clear()` остался ровно один — внутри `_ollama_summarize_and_reset_context`. Страж: `tests/test_turn_limits.py`.

## Pressure-инжект (модель видит надвигающееся)
После каждого ответа: `set_context_pressure((prompt_eval+eval)/num_ctx, used, max)` (TI). При пересечении вверх 50%/70%/85% — ОДИН раз дописывается строка `CONTEXT_PRESSURE: контекст ~N% (used/max ток.) …` в конец `TOOL_RESULT_SUMMARY` (`PRESSURE_LEVELS`, TI): 50% — «планируй остаток (context_stats, разбивай, compact)», 70% — «сворачивай рассуждения», 85% — «завершай ход». Гистерезис: уровень объявляется раз до сброса (финальный ответ хода / reset).

## Осознанная компакция (запрос модели, 2026-10-11)
Авто-механизмы решают, КОГДА; модель теперь решает, ЧТО забыть:
- **context_map**: харнес перед каждым запросом пишет `context_map.json` — user-корневые блоки живого контекста с ценой в токенах, `%` от num_ctx, превью и инструментами (`_context_blocks`/`write_context_map`, TI); читается через `session_memory action=context_map`.
- **context_stats**: `session_memory action=context_stats` — исторические цены по окнам `session_digest` (медиана tool-раунда по приросту prompt_eval, средние цены инструментов, peak/p95, запас `num_ctx − prompt_eval`, `rounds_left_est`) — чтобы агент понимал «задача не влезет — разбить на части» ДО начала.
- **compact**: `session_memory action=compact blocks="1,3-5" note="…"` пишет `compact_request.json`; харнес исполняет на границе раунда (`apply_pending_compacts`, TI): блоки → артефакт `context_compact_*.json`, на их место — system-заглушка `COMPACTED_BLOCKS` (освобождённые токены %, артефакт, пометка агента). Рельсы: текущий (последний) блок не сжимается, блоки <2% num_ctx пропускаются, кап 12 блоков; `context.json` не трогается — поднятие через get_turn/search. Статистика: `_compression_stats["manual"]`.
- **context_cost**: tool-результат дороже 5% num_ctx получает строку цены с указанием механизма — событийная подсказка поверх процентного pressure.
- **Дедуп хода**: identical-вызовы `file_system`/`journal` с теми же аргументами внутри хода не выполняются повторно — `DEDUP_SAME_CALL` с указателем на артефакт (анти-спам, фокус).
- **Живучесть скиллов**: успешные `skills get/run` пишутся в `enabled_skills.json` сессии (`record_skill_activation`); перед каждым запросом `refresh_skills_active_note` перезаписывает одну system-реплику `SKILLS_ACTIVE:` (какие скиллы подключались, `skills action=get name=…` для перечитывания). Реплика переживает overflow-reset (`messages.clear()`) и появляется при resume — инструкция скилла могла быть вытеснена, модель перечитывает, а не догадывается. Бэкфилл (`_backfill_session_state`, раз на сессию): если файла нет, активации восстанавливаются из `tools.log` (завершённые `skills get/run`) — иначе скиллы, подключённые до появления механизма/в прошлых запусках процесса, оставались невидимы (сессия 20261011_141653: llm-wiki подключён в 15:02, памятка так и не появилась). `WIKI_MODE_NOTE` пишется в `context.json` ровно один раз на сессию (`_wiki_note_persisted`; до фикса после каждого сброса дублировалась — 4+ копий).
- **Чекпоинты sign_step (2026-10-11)**: подпись перестала быть one-shot в конце хода. Модель зовёт `sign_step(done=…)` после каждого значимого шага; все подписи хранятся в `signatures.json` (несколько на окно, поле `seq`), `session_digest`
кладёт их в `Window.signs` (`sign` = последняя), `window_line` печатает goal/done последней + «(+N чекпоинтов)». Отказ от ошибок после двух левых entities не блокирует последующие валидные подписи. Индикатор важности отметки — заполненность контекста: при ratio ≥40% (`SIGN_CHECKPOINT_REMINDER_PCT`) и отсутствии подписи в ходе — одна строка `checkpoint_reminder` в tool-результате.
- Тесты: `tests/test_context_compact.py`, `tests/test_sign_step.py` (чекпоинты, seq, +N), обновлённый `test_pressure_inject.py`.

## Статистика сжатия
`_compression_stats` {tokens, trims, resets, last_reason} (TI:95), `get_compression_stats()` (TI:98). Питает **только UI**: панель (`compressed_tokens/compress_trims/compress_resets`, TI:1337) и ленту («🧹 Память подожата… / ♻️ Память очищена…», TI:1328-1334). **Модель эти счётчики не видит** — она видит лишь процентный уровень pressure и факт вытеснения (FORGOTTEN_INDEX/протокол).

## Компактизация tool-результатов
`_compact_tool_message` (TI:681): полный результат → артефакт, в контекст — `TOOL_RESULT_SUMMARY` (tool/args/artifact_path/size_kb/preview ≤ `TOOL_OUTPUT_MAX_CHARS=100k`). Дедуп system-реплик: `_append_system_once` (TI:144) — без него памятки размножались сотнями и ломали весь механизм.

## Что видит и может модель (срез 2026-10-11)
- Видит: уровни pressure с абсолютными токенами, FORGOTTEN_INDEX, протокол ресета, цену дорогих блоков (`context_cost`), полную карту живого контекста и исторические цены (`context_map`/`context_stats`), счётчики сжатия — в `compression_stats` карты.
- Может: запросить компакцию своих отработанных блоков (`compact`), спланировать задачу по запасу контекста, не плодить identical-вызовы (дедуп хода).
- Ограничения v1: компакция действует в рамках процесса (при resume блоки возвращаются из context.json, заглушка остаётся последней system-репликой); блоки — user-корневые сегменты, тоньше нельзя; сжатие середины не попадает в FORGOTTEN_INDEX (у него своя префиксная механика — для компакции служит заглушка COMPACTED_BLOCKS на месте блока).

## Связи
Хранение — `entities/session_directory.md`; окна/дайджесты — `entities/tools/session-memory.md`; исследования — [[context_memory_research]]; резюм — [[session_resume]].
