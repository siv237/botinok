# Журнал вики (log)

Хронологический журнал. Восстановлен по **реальным изменениям в git** (состав и даты файлов из `git log --diff-filter=A`, а не тексты сообщений). Формат с единым префиксом парсится утилитами: `grep "^## \[" log.md | tail -5`.

## [2026-03-21] e801859 | Ядро агента и базовая система
Первый коммит: `botinok.py` (CLI/главный цикл), `core/session_manager.py` (сессии), `core/tool_manager.py` (реестр/загрузка инструментов), `tools/web_search.py`, `tools/open_url.py`. Затого — стартовый набор: поиск DuckDuckGo и чтение страниц через lynx.

## [2026-03-21] 6abe59e–b788407 | Установщик и баннер
`install.sh` + README (инструкции), зависимость `ca-certificates`, user_agent открытия URL, ASCII-баннер при старте.

## [2026-03-21] 0e7128c–64e9a44 | Форматирование, контекст, диагностика
Форматирование вывода диалога в консоли (0e7128c, 03b8eca), счётчик контекста в инструментах (551332a), уменьшение фризов панели диагностики (64e9a44).

## [2026-03-21] 9ae5ce2–2acd8d2 | Мастер, stealth/pipe
`core/config_wizard.py` (мастер настройки), тихий режим и работа через пайп/stdin (e8f390f), форматирование тихого вывода (2acd8d2).

## [2026-03-21] 97e8ef7, e4f7481 | Инструменты файловой системы и журналов
`tools/file_system.py` (навигация/чтение), затем `tools/journal.py` (анализ systemd/log show). Фикс зацикленности первого ответа (8e6bedb).

## [2026-03-21/22] 73ab1ff | Режим выполнения и редактирования
Появление `tools/code_editor.py` и `tools/shell_exec.py` (выполнение и правка). Убрано зависание UI при вызове инструментов (6fc5412).

## [2026-03-23] 05e4772, 52c49ff | GitHub и база опыта
`tools/github.py` + `tools/experience.py`; позже — timestamp и сортировка записей опыта (52c49ff). Подписи к сессиям (1bc08a8).

## [2026-03-24] 60807d8–6c5c7df | Система навыков
`tools/skills.py` + пример `skills/excel/SKILL.md` (личные/проектные навыки), поиск и установка из ClawHub (6c5c7df).

## [2026-03-25] fa8fba2, 7b2ea49 | Корректор и стриминг инструментов
Режим корректора (Исполнитель → Корректор); стриминг вызовов инструментов в рассуждении.

## [2026-03-27] 8a357af–fab9810 | Портируемость, конфиги, промпты
RHEL-поддержка install.sh (8a357af), поддержка macOS (f8dff64), wizard при Ollama за nginx (2a3428b), SSL-оптимизация (48eebc5), режим «только чат» (1920378), уменьшение мерцания в SSH (26095f1), пользовательский конфиг (ee73fb5), debug-режим (fab9810).

## [2026-03-27] 619c8b3, a98f241 | Внешние промпты и обновление
Промпты вынесены в `prompts/` и копируются внутрь сессии (619c8b3); инструмент `--update` (a98f241); при возврате в сессию — последний ответ (f3380f1); компактный прогрессбар (d298662).

## [2026-03-28/29] 153a79d–c18ef39 | ASCII, автообновление пакетов, изображения
ASCII-генератор изображений (`core/image_ascii.py`), логотип в README, автообновление Python-зависимостей при `--update`, коррекция промптов.

## [2026-03-29] c79ad2f–4446e50 | curl, web_extract, промпты переполнения
`tools/curl.py` (скачивание, jq), `tools/web_extract.py` (структурированное извлечение HTML), рефактор curl с выносом промптов переполнения контекста (307dcf8).

## [2026-03-29] b1de3f1–7ce95a9 | Vision (мультимодальность)
`tools/vision.py` + доводка обработки изображений: валидация и автоконвертация в JPEG (9c46f42), обработка неизвестных форматов (56537a7), Content-Type для web (dcb96b7), preflight перед отправкой (7ce95a9).

## [2026-03-30] 56f1768–05b71ef | Безопасность, конфиги, фиксы (0.2)
Dangerous mode для `file_system` (56f1768), фикс переменной `ans` (4294fe5), поддержка персональных конфигов и обработка ошибок сохранения (05b71ef). **Релиз 0.2** (52018af).

## [2026-03-30] 1839087–3285995 | Post-0.2 стабильность
Fix UnicodeDecodeError в стриме (1839087), интерактивная таблица выбора сессии с фильтром и относительным временем (2b7a6bc), многострочный ввод с нумерацией строк.

## [2026-04-09] 8ed1898–adf965b | Корректор и объектный доступ к истории
Запрос перед запуском корректора + пошаговый алгоритм (8ed1898), фикс UnboundLocalError (5da5ceb), `tools/session_memory.py` — объектный доступ к истории сессий.

## [2026-04-13] 1136095 | Переход на Textual
Появление `core/textual_app.py`, `core/textual_integration.py`, `core/textual_history_viewer.py`; добавлен `SCROLLBACK_FEATURE.md`. **Важно:** описанный в нём `core/scrollback_buffer.py` в git так и не создан (см. `concepts/scrollback.md`, status: draft).

## [2026-06-01…06-04] e00aae7–4e29278 | Доводка Textual TUI
Живой markdown-рендер стрима (696fe77), приведение к виду старого Rich Live (95c64e5, b68a98e, a336440), корректный VRAM на всех этапах (bf41b5e), плавный стриминг и UI до 10/30 FPS (e441a22), Collapsible-спойлеры вместо RichLog (aab7f82), независимый ввод и остановка по ESC (a1fef6c). **Textual по умолчанию, Rich через `--rich-mode`** (69f958a).

## [2026-06-10] 0d71a70–cd57c89 | Wizard и бесшовный стриминг
Wizard: контекст по умолчанию, `--wizard` без `--rich-mode` (0d71a70); единая точка вывода `stream_static` (a54666c); конвертация на месте и закрытие спойлеров по очереди — нет мигания (cd57c89).

## [2026-08-23] fb084e8 | OpenAI-совместимые бэкенды
Появление `core/openai_compat.py` — адаптер API (llama-server, vLLM и др.), конвертация SSE ⇄ Ollama на лету.

---

## Операции вики (LLM, руководимые человеком)
Префикс ведения вики-операций — как в `AGENTS.md`; ниже журнал работы над самой вики.

## [2026-08-23] ingest | Первичный ингвест репозитория
Создана базовая вики по методике LLM Wiki: схема `AGENTS.md` (корень), `index.md`, `log.md`, `overview.md`, манифест `raw/README.md`, страницы сущностей/концепций/сравнений/источников.

## [2026-08-23] lint | Аудит покрытия и счётчик инструментов
Полное свечение кода/доков с вики. Исправлено завышенное «14 инструментов» → 13 + алиас `web_extractor` (tool_manager, raw, overview).

## [2026-08-23] ingest | requirements.txt, SCROLLBACK_FEATURE.md
Закрыты пробелы: `sources/requirements.md`, `sources/scrollback_feature.md`, `concepts/scrollback.md` (draft). Зафиксировано отсутствие `core/scrollback_buffer.py` в git.

## [2026-08-23] ingest | Лог по реальным коммитам
Журнал восстановлен по фактам git (`--diff-filter=A`, даты, состав файлов), а не по текстам сообщений. Найдено фактическое наличие/отсутствие всех компонентов.

## [2026-08-23] ingest | Wizard: поддержка OpenAI-совместимых бэкендов
`core/openai_compat.py` добавлен помощник `_api_headers(sm)` — заголовок `Authorization: Bearer <ApiKey>` для стриминговых и нестриминговых запросов. `core/config_wizard.py` переработан: шаг 0 — выбор бэкенда (Ollama / OpenAI-совместимый); для OpenAI проверка связи через `/v1/models`, запрос списка моделей, настройка `ApiKey`; выбор модели по имени для обоих бэкендов; `Backend` пишется в `[Ollama]`.
Обновлены `entities/config_system.md`, `entities/openai_compat.md`.

## [2026-08-23] ingest | Textual: хронологический порядок и схлопывание рассуждения
`core/textual_app.py`: спойлер thinking при финализации хода монтируется свёрнутым (`collapsed=True`) на своём месте через `mount(before=stream_static)` — рассуждение остаётся над ответом; `_spoiler_title` режет превью по ширине чата (`chat.size.width`), чтобы заголовок был одной строкой; `_mount_spoiler` получил параметры `collapsed` и `before`; порядок в `_render_history_entry` приведён к хронологическому (thinking перед ответом). Обновлён `entities/textual_ui.md`.

## [2026-08-23] ingest | Textual: скролл без прилипания
`core/textual_app.py`: `on_mouse_scroll_up` над чатом (`_event_inside_chat`) сразу ставит `_user_scrolled_away=True`; `_tick_stats` не вызывает `scroll_end` при установленном флаге и сбрасывает его только когда пользователь сам вернулся в нижнюю зону (`SCROLL_THRESHOLD=30`). Ранее тик каждые 0.1 c принудительно возвращал вниз, из-за чего нельзя было прокрутить вверх мышью во время стрима. Обновлён `entities/textual_ui.md`.

## [2026-08-23] ingest | Textual: прилипание больше не мешает скроллу мышью
`core/textual_app.py`: прежняя «зона внизу» была слишком широкой — `SCROLL_THRESHOLD=30` px заставлял `_is_at_bottom()` возвращать True даже после прокрутки вверх (а для слегка переполненного содержимого — вообще всегда), так что тик и `_auto_scroll_chat` возвращали к выводу. Заменено на `SCROLL_BOTTOM_EPS=1` (буквальный низ); `_tick_stats` при сброшенном флаге просто держит `scroll_end` (не теряет следование за стримом), а при установленном — не трогает; `_auto_scroll_chat` (зовётся при каждом монтировании спойлера) теперь уважает `_user_scrolled_away`, а хендлеры колеса схлопнуты в `on_mouse_scroll`. Сброс флага — только когда пользователь сам докрутил до низа. Обновлён `entities/textual_ui.md`.

## [2026-08-23] ingest | Textual: нет сырого мышления в потоке (диагноз по сессии)
Диагноз по завершённой сессии `~/.botinok/sessions/20260823_231959_visual_run`: большая часть ходов — «только мышление» (`content=""`, `thinking>0`, `tool_calls=1`), все токены льются как `thinking` (см. `session_raw.log`). В `finalize_assistant_turn` блок финализации `stream_static` был под условием `if final_content`, поэтому для таких ходов raw-текст мышления, стримившийся в `stream_static`, НЕ очищался и оставался кучой мусора в общем потоке ПОД свёрнутыми спойлерами. Исправлено: `stream_static` теперь финализируется всегда — есть ответ → Markdown, нет → `update("")`; спойлер `Thinking` монтируется свернутым и уносит текст из потока. Также убраны лишний заголовок `Assistant:` (`start_assistant_turn`) и хвостовая пустая строка после ответа. Обновлён `entities/textual_ui.md`.

## [2026-08-23] ingest | Textual: детекция скролла вверх по позиции и сброс No chunks
`core/textual_app.py`: дефолтный хендлер колеса на чате делает `event.stop()`, поэтому App-хендлер не срабатывал — прилипание не отключалось. Добавлен опрос в `_tick_stats`: `_last_scroll_y` сравнивается с `scroll_y`, уменьшение позиции помечает `_user_scrolled_away=True` (работает от любого источника: колесо, клавиши, тачпад). Плюс сброс `_last_chunk_time=0.0` в `start_assistant_turn` и `flush_tool_buffer` — счётчик No chunks больше не растёт бесконечно между ходами. Обновлён `entities/textual_ui.md`.

## [2026-08-24] ingest | TUI: экранирование markup при рендере истории
При старте рендер старой сессии падал `MarkupError: Expected markup value` — вывод `shell_exec` с `xterm-256color` из `context.json` попадал внутрь `[dim]...[/dim]` без экранирования. Исправлено в `core/textual_app.py`: `_render_history_entry`, `append_user_message`, `on_input_submitted` и спойлеры thinking прогоняют вставляемый контент через `_rich_escape` (уже используется в стриме). Обновлён `entities/textual_ui.md`.

## [2026-08-24] ingest | Аудио: авто-маршрутизация на /v1
Live-тестами на `dgk00srv930r` выяснено: аудио доставляется модели ТОЛЬКО через OpenAI-совместимый путь `/v1/chat/completions` + `input_audio` (wav) — нативные поля `/api/chat` (`images[]`, `audios`) сервер игнорирует/отвергает. Чтобы не переключать глобальный `backend=ollama`, добавлена авто-маршрутизация: если в `messages` есть аудио (`media_kind=audio` с `audios`), конкретный ход идёт на `/v1` (`chat_stream_request`), остальное — как прежде. Хелпер `_has_audio_message` в `botinok.py` (stream+stealth) и `core/textual_integration.py`; удалены прежние внецикловые `use_openai_backend`. Модель для аудио — `gemma4:12b`.

## [2026-08-24] ingest | Аудио-модуль (omni-модели)
`tools/audio.py` — инструмент `audio`, аналог `vision`: загрузка файла/URL, детект формата по magic-байтам, транскод в **WAV 16кГц моно PCM** (ffmpeg), base64. Интеграция в `botinok.py` (2 места) и `core/textual_integration.py` (сообщение с полем **`audios`** + маркер `media_kind=audio`, `mime_type`); OpenAI-бэкенд → `input_audio` `format=wav` в `core/openai_compat.py`, vision→`image_url`. Зарегистрирован в `core/tool_manager.py`. Итог live-тестов на сервере `dgk00srv930r` (Ollama 0.32.14): у `qwen3.8:27b` аудио-капа нет (400 на любом способе); `gemma4:12b` аудио-модальность имеет (`/api/show` capabilities=`audio`). Доставка: нативные поля `/api/chat` (`images[]`, `audios`) до модели НЕ доходят (модель отвечает «пришлите аудиофайл»); рабочий путь — **OpenAI `/v1/chat/completions` + `input_audio` (format=wav)** на gemma4:12b (речь транскрибируется корректно). Значит для аудио конфиг должен быть `backend=openai` + `defaultmodel=gemma4:12b`. Созданы `entities/tools/audio.md`, `concepts/audio_multimodal.md`; обновлены index/overview/raw.

## [2026-08-23] ingest | Мастер OpenAI: получение провайдерского контекста моделей
`core/config_wizard.py`: `check_openai` теперь возвращает `list[dict] {'id','context'}` — максимальный контекст извлекается из полей провайдера (`context_length`, `context_window`, `max_model_len`, вложено в `meta`/`meta.llama`), для llama.cpp пробуется `/props`. Добавлены `_model_context`, `_context_ladder`, `_server_context`. В шаге выбора модели контекст отображается в списке; в шаге контекста для OpenAI предлагается рекомендуемый (максимальный) контекст провайдера или меньше, вместо фиксированной лесенки. Обновлены `entities/openai_compat.md`, `concepts/config_priority.md`.

## [2026-09-16] ingest | Встроенный терминал: PTY-сессии, свернуть/вернуть
`tools/shell_exec.py` переписан на «shell как отдельная сессия»: действия
`run/status/read/search/send/send_key/wait/kill/list`, вывод читается порциями,
сессия не держит агент. Новые модули: `core/shell_session.py` (`ShellSession`,
`ShellSessionRegistry`, `TextualAppRegistry`) и `core/shell_screen.py`
(`ShellScreen` — модальное окно терминала с кнопками «Свернуть»/«Закрыть»,
Ctrl+Q — свернуть, Ctrl+C — SIGINT). Свёрнутые сессии показываются в панели
`#shells` основного TUI (`BotinokTextualApp.open_shell_session`,
`minimize_shell_session`, кнопки `shell_restore_<id>`); одновременно открыто не
более одного окна. По ходу закрыты дефекты из ревью: эскалация SIGINT→SIGKILL в
`kill()`, возврат дефолтного `timeout_sec=120`, обработка сбоя `Popen` без утечки
PTY-дескрипторов, ограничение буферов вывода (`_clean_str` deque, raw 4 МиБ),
уборка мёртвых сессий + `atexit`, ограничение `search` по совпадениям/контексту,
устранение busy-wait в `_drain`. Защита от `RecursionError`: непрозрачный фон
`ShellScreen` и отказ от накопления модальных окон. Тесты:
`tests/test_shell_session.py` (12), `tests/test_shell_exec_tool.py` (10),
`tests/test_shell_screen.py`, новый `tests/test_shell_minimize.py`.
Созданы `entities/shell_session.md`, `entities/shell_screen.md`,
`concepts/embedded_terminal.md`; обновлены `entities/tools/shell-exec.md`,
`entities/textual_ui.md`, index/overview/raw.

## [2026-09-17] ingest | Удалён старый Rich Live движок (0.4)
Завершена миграция на Textual: из `botinok.py` удалены `BotVisualizer`,
`create_layout`, `ask_ollama_stream` (~1240 строк), флаг `--rich-mode` и старый
readchar-ввод (однострочный и многострочный `---`). Вместе с ними убраны мёртвые
хелперы/константы (`_trim_tail`, `_tool_stream_has_payload`,
`_estimate_messages_tokens`, `_session_project_dir`, `_resolve_code_editor_target_path`,
`_is_within`, `_code_editor_args_for_display`, `_ollama_summarize_and_reset_context`,
`_detect_repetition`, `REPEAT_LINE_*`, `HARD_CTX_PCT`, `MAX_TOOL_ROUNDS_PER_TURN`,
`MAX_AUTO_RECOVERIES_PER_TURN`, `MISSING_FINAL_AUTO_CONTINUE_MAX`) и лишние импорты.
Интерактив — только `ask_ollama_textual`; stealth/pipe и корректор — headless
`ask_ollama_stealth` (`run_proofreader_turn` без `vis`). Тесты зелёные
(session 12, exec 10, screen, minimize). Обновлены `entities/botinok_cli.md`,
`entities/textual_ui.md`, `comparisons/rich_vs_textual.md` (superseded),
`concepts/proofreader.md`, `concepts/config_priority.md`, `concepts/streaming_tui.md`,
`concepts/scrollback.md` и `sources/scrollback_feature.md` (superseded),
CHANGELOG (0.4), README, `prompts/README.md`; удалён устаревший план миграции.
Логотип/баннер версии перенесён в Textual: `BotinokTextualApp._mount_banner`
показывает ASCII-арт `assets/logo.png` (автоскейл под ширину `#chat`) и строку
версии в начале новой сессии (пустая история); версия прокидывается через
`ask_ollama_textual(version=_BOTINOK_VERSION)`. Обновлён `entities/textual_ui.md`.
Версия поднята до 0.4. Перенесены забытые возможности CLI: стартовый промпт
(`-p/--prompt`, позиционный) автоотправляется в Textual (`initial_prompt` →
`_submit_initial_prompt`), `--debug` выставляет `BOTINOK_DEBUG` и в Textual-ветке,
`--proofread` работает в TUI через `proofreader_fn=run_proofreader_turn`
(до `MAX_PROOFREAD_ROUNDS=3`, замечания в чате). Обновлены CHANGELOG,
`entities/botinok_cli.md`, `concepts/proofreader.md`.
Завершено выпиливание Rich/inquirer/readchar (0.4): выбор сессии — Textual
`core/session_picker.py`, мастер — `core/textual_prompts.py`, CLI/wizard-вывод —
plain `core/cli_io.py`. Из `botinok.py`/`config_wizard.py` убраны прямые импорты
Rich (`Console`/`Markdown`/`Confirm`/`Panel`), из `requirements.txt` — `rich`,
`inquirer`, `readchar` (Rich — транзитивно через Textual, используется только как
renderable внутри Textual-модулей). Удалён `SCROLLBACK_FEATURE.md` (нереализованная
фича Rich-эпохи). Обновлены `sources/requirements.md`, `entities/botinok_cli.md`,
`entities/textual_ui.md`, `concepts/config_priority.md`, raw-манифест.
Проверка: `core/textual_prompts`/`session_picker` (select/text/filter) — OK;
`botinok`/`config_wizard` без Rich-импортов; прежние тесты зелёные.
Правка UX выбора сессии: восстановлено двухшаговое меню (3 пункта → список
сессий с фильтром только в «Выбрать другую»), стрелки переключают фокус
фильтр↔список; проверены результаты latest/new/path/cancel.
Панели переведены на нативные виджеты Textual (0.4): `Performance` = `Static` +
`ProgressBar`, `Tools Activity` = `DataTable`, шапка/подвал = `Static` с
`border-title`, финальный ответ/история = виджет `Markdown`; Rich-renderables
(`Panel`/`Table`/`Progress`/`Group`/`Markdown`) из кода убраны, `rich.text`
оставлен только для ANSI (баннер, лог терминала), сам `rich` — транзитивная
зависимость Textual. Разобран и исправлен «сдвиг панелей» на необычных символах:
расхождение ширины эмодзи с VS16 (Textual #5980, Ghostty #8027, glibc
locale/32322), решение — `core/text_width.py` (нормализация в `_add_static`/
`_rich_escape`, обрезка по ячейкам). Создана
`concepts/terminal_unicode_width.md`; обновлены `entities/textual_ui.md`,
CHANGELOG, index, raw-манифест.
Панель `Tools Activity` переделана по UX: убрана таблица/`DataTable`, теперь список
карточек-`Collapsible` «время + инструмент + статус», по клику раскрываются детали
(запрос/результат/размер). Обновление инкрементальное (карточка обновляется, а не
пересоздаётся), состояние раскрытия сохраняется; `append_tool_result` кладёт превью
результата в карточку. Шапка сжата до 1 строки.
Фикс: карточки инструментов «летели развёрнутыми» — причина в том, что
`CollapsibleTitle` является подклассом `Static`, и апдейт `query_one(Static)`
перезаписывал заголовок телом; тело теперь обновляется строго через
`Collapsible.Contents`; все новые карточки гарантированно свёрнуты.
Косметика: `Diagnostic Log` перенесён наверх в левую колонку как кликабельный
`Collapsible` (одна строка в свёрнутом виде, полный prompt с прокруткой через
`VerticalScroll`), строка `Response (Lines: …)` и нижняя панель удалены; блок
`Performance` не затронут. Заголовок свёрнутого блока — `Prompt: <промпт>` с
обрезкой по ширине (пересчёт при resize), по клику полный текст.
Раскрытый Diagnostic Log — список вопросов сессии: карточки-`Collapsible` с
`дата · сколько назад` + обрезанный вопрос, по клику полный текст; вопросы
подгружаются из `context.json` и добавляются при отправке, время обновляется раз
в 30 с; список прокручивается (`VerticalScroll`).
Многострочный ввод: `Input` заменён на `Composer` (`TextArea`) — Enter отправляет,
Shift+Enter/Ctrl+J новая строка, Esc очистка, Alt+↑/↓ история, авто-рост 1→8 строк;
bracketed paste вставляет текст целиком без отправки, плюс окно защиты от Enter-ов
при вставке для терминалов без bracketed paste. Исправлена потеря `Input`-ом всего
после первой строки при вставке.

## [2026-09-18] ingest | Встроенный терминал по умолчанию (inline) + разворот/возврат
`shell_exec` теперь по умолчанию открывает **встроенную** панель `ShellInline`
(новый класс в `core/shell_screen.py`), а не модалку: `#inline_shell`
в `BotinokTextualApp` занимает верх колонки `#content` (50%), чат со стримом
модели остаётся снизу. Кнопки панели: «Развернуть» (`expand_shell_session` →
модальный `ShellScreen`), «Свернуть» (в панель свёрнутых), «Закрыть». В модалке
появилась кнопка «В окно» (`_to_inline`), возвращающая панель. Панель
переиспользуется (`set_session`) при запуске новой сессии, старая уходит в
панель свёрнутых. `_keep_focus` не отбирает фокус у панели. Панель свёрнутых
переведена на инкрементальное обновление (`_shell_widgets`) — убран race
`remove_children`+`mount` (DuplicateIds). `_ui_push_screen` при вызове из
UI-потока планирует показ через `call_after_refresh` (mount/remove — только из
pump). `_detach` разделён на `_detach_view`/`_pop_screen` с отложенным
`_defer_after_pop`. Тесты: `tests/test_shell_minimize.py` переписан под inline /
expand / return / minimize / restore / close. Обновлены
`entities/shell_screen.md`, `entities/textual_ui.md`,
`concepts/embedded_terminal.md`, CHANGELOG.

## [2026-09-18] ingest | Панель терминалов: активная строка, ✕, время и прокрутка
Панель `#shells` переработана: `VerticalScroll` (прокрутка, `max-height: 50%`);
сверху всегда активная строка `#shells_active` (`● активный <имя> · HH:MM:SS ·
Ns`) с тикающим счётчиком секунд от старта встроенной сессии; свёрнутые
терминалы — однострочные `Horizontal`-строки с кнопкой восстановления
(`shell_restore_<sid>`, время старта и длительность) и кнопкой `✕`
(`shell_kill_<sid>`) для завершения. Обновление осталось инкрементальным
(`_shell_widgets` теперь хранит строки), сигнатура `_shells_sig` включает
`int(elapsed)` для тика счётчика. Тест `tests/test_shell_minimize.py` дополнен
проверками активной строки, ✕-завершения и однострочности.

## [2026-09-18] fix | Терминал: статус/анимация, подвисание UI и переоткрытие
Заголовок терминала (`ShellScreen` и `ShellInline`) через общий `_terminal_title`
показывает анимацию и счётчик: `⠋ имя · идёт Ns` → `✔ имя · завершён за Ns
(rc=…)`; тик 0.15 с, значения экранируются. Исправлено подвисание UI при
«Развернуть» → «Свернуть» из модалки (и при «Закрыть»): `_minimize`/`_terminate`
обновляют DOM основного экрана только после фактического снятия модалки
(`_pop_screen(cb)` + `_defer_after_pop`), иначе модалка не домонтируется и UI
встаёт. Исправлено переоткрытие: `_ui_push_screen` при вызове из UI-потока
планирует показ через `call_next` (`call_after_refresh` не срабатывал на простое),
а inline-виджет больше не удаляется `remove()`, а скрывается и переиспользуется
(`_hide_inline_shell`, флаг `inline_shell_active`) — асинхронный prune оставлял
«застрявшего» потомка. Добавлен `tests/test_shell_reopen.py`; обновлён
`tests/test_shell_minimize.py` (модальные «Свернуть»/«Закрыть», ✕, активная
строка).

## [2026-09-18] fix | Терминал: затенение MessagePump._closed (перестал сворачиваться)
Корень «сломалось сворачивание/разворачивание»: `ShellInline` хранил свой флаг
в `self._closed`, а у Textual `MessagePump._closed` — внутренний атрибут
(останавливает message loop). При сворачивании/разворачивании виджет
выставлял `_closed=True`, Textual считал виджет закрытым и вычищал его из DOM —
после этого ни свернуть, ни развернуть было нельзя. Флаг переименован в
`_view_closed` (в `ShellScreen` и `ShellInline`). Прямой вызов обработчиков в
тестах это не ловил — добавлен `tests/test_shell_pump_clicks.py` с настоящими
кликами через `pilot`. Плюс: скрытый терминал больше не удерживает фокус
(`blur()` + `_keep_focus` с учётом `inline_shell_active`).

## [2026-09-18] ingest | Терминал: явный маркер завершения команды
В лог терминала (`ShellScreen`/`ShellInline`) по завершении процесса один раз
дописывается строка `─── завершено за Ns (rc=…) ───` (или `─── остановлено ·
Ns ───`), флаг `_done_written` (сбрасывается в `set_session`). Заголовок
переформулирован в «завершено за Ns». Тест `tests/test_shell_reopen.py`
проверяет и маркер в логе.

## [2026-09-18] ingest | Встроенное подтверждение опасного действия
`show_confirmation_prompt` больше не открывает модалку поверх правых панелей:
подтверждение показывается встроенно в окне вывода — `#inline_confirm`
(`ConfirmInline`, тот же набор: Да / Нет / Отменить с причиной, `y/д`, `n/esc`,
↑↓+Enter, режим причины с мини-инпутом). `ConfirmationScreen` оставлен запасным
путём. Добавлен `tests/test_confirm_inline.py`; обновлён
`concepts/dangerous_mode.md`.

## [2026-09-18] fix | Встроенное подтверждение: убраны артефакты вложенной рамки
У `#inline_confirm_options` (`OptionList` в `ConfirmInline`) оставалась
собственная рамка `tall` — вложенная в рамку `#inline_confirm` она давала
артефакты линий. Убрана (`border: none`, фон прозрачный); то же для запасного
`#confirm_options`. Тест `tests/test_confirm_inline.py` проверяет отсутствие
рамки (`options_no_border`).

## [2026-09-18] ingest | Разворот shell-команд через shfmt + подтверждение и история
Добавлен `format_shell_command` (shfmt / `shfmt-py`): однострочники
разворачиваются, `for …; do` сохраняется, тело/`done` выравниваются; при
недоступном shfmt — исходная строка (кэш `lru_cache`). Применение: клик по
заголовку терминала (`#inline_shell_cmd`/`#shell_cmd`); подтверждение опасного
действия показывает команду развёрнутой сразу (`#inline_confirm_cmd` в
прокрутке, прочие аргументы — pretty-JSON); в истории сессии тело раскрытого
вызова `shell_exec` показывает развёрнутую команду (`_format_tool_call`).
`requirements.txt` += `shfmt-py` (beautysh не подошёл — он только выравнивает
отступы и не разбирает однострочники). Тесты: `tests/test_shell_command_format.py`,
обновлён `tests/test_confirm_inline.py`.

## [2026-09-18] ingest | session_memory: restore/EXACT, прощающий синтаксис, гибкий поиск
`tools/session_memory.py` переработан в «архивариуса-советника».
- Новое действие `restore` — точное восстановление из канонического
  `messages.json` (EXACT), иначе реконструкция из `context.json` (DERIVED,
  `SessionManager.restore_session`, флаг `stale`).
- Достоверность в каждом ответе: `_confidence` = EXACT | DERIVED | HINT
  (`search` — HINT).
- Полные тексты: `MessagePart` больше не отбрасывает content >400;
  `get_turn include_content=true` отдаёт полный ход (раньше — превью 200,
  из-за чего агент шёл читать файлы).
- Ходы группируются по завершённым обменам; tool-раунды и авто-продолжения
  не создают пустых ходов; финальный ответ закрывает ход.
- Прощающий синтаксис: синонимы action, строковые числа, алиасы, пустой
  action → `resume_brief`, промах `turn_id` → ближайший, плохой путь →
  последняя сессия. Неизвестное действие → `ambiguous=true` (не подменяется).
- Гибкий поиск (RU): регистр/ё/пробелы/пунктуация, части слов, стеммер
  окончаний, режимы auto/all/any/regex; блок «где именно» — `файл:строка`
  с временем по `response.md`, `thinking.md`, `tools.log`, `session_raw.log`,
  `context.json`, `messages.json`.
- Советник: `_meta` (сессия/диапазон/последняя метка), `_advice`,
  `_next_actions`, action `help`.
- Resume: `build_resume_brief` (статус прервана/завершена, полный последний
  ответ), `_clean_answer`/`_last_final_assistant`; на resume инструкции про
  `skills`/`experience` не отправляются (`strip_skills_mandate`).
- Устойчивость к обрывам API: `_stream_turn` повторяет запрос при
  `stream_error`, сохраняет прерванный ход/пометку (`_persist_connection_failure`).
- Тесты: `tests/test_session_snapshot.py` (restore/provenance/ambiguity,
  resume-brief, round-trip). Страницы: `entities/tools/session-memory.md`,
  `concepts/session_resume.md`, обновлены `entities/session_manager.md`,
  `concepts/session_lifecycle.md`, `index.md`.

## [2026-09-18] ingest | dangerous mode: политика внутри/вне сессии, автосогласие, запрос переключения
Переработан механизм подтверждений и гейт опасных действий.
- **Гейт `ToolManager.call_tool`** (простой режим): `shell_exec` запрещён;
  `code_editor` (write/replace/apply), мутации `file_system` и `curl output_path`
  разрешены только внутри `session_path`; хелперы `_path_within`/`_allowed_in_session`.
  Раньше блокировался только `file_system`, а `code_editor`/`shell_exec`
  выполнялись без подтверждения при выключенном dangerous mode.
- **`file_system._dangerous_action`**: разрешает мутации внутри сессии без
  dangerous mode (вне — ошибка).
- **`code_editor`**: новый параметр `dangerous_mode`; при включении снимается
  ограничение корня `_safe_path` (запись вне сессии после переключения).
- **TUI (`textual_integration.py`)**: опасное действие вне сессии в простом
  режиме → окно `kind="switch"` (да/нет); согласие включает dangerous mode и
  выполняет действие; отказ → `dangerous_switch_denied` (повторно не спрашивать)
  и явный результат агенту («ищи безопасную альтернативу»).
- **Подтверждение** `kind="confirm"` + галочка **автосогласия на сессию**
  (`dangerous_auto_confirm`), флаг в шапке `#auto_flag` с отключением по клику.
- **Фикс прерывания по Esc**: `Composer._on_key` перехватывал `Esc` всегда
  (гасил событие) и не давал всплыть до `App.on_key` → остановка стрима не
  срабатывала. Теперь при `is_streaming` `Esc` вызывает `request_stop()`.
- **Фикс рендера логов**: `append_log` не экранирует markup, поэтому
  `[yellow]…[/yellow]` больше не отображаются как текст.
- **Ревью-фиксы**: единый источник политики вынесен в
  `ToolManager.path_within` / `allowed_in_session` (их импортирует
  `textual_integration` вместо локальной копии); относительные `path`/
  `output_path` трактуются относительно `session_path`, а не CWD.
- **Тесты**: `tests/test_dangerous_mode.py` (гейт + UI switch/автосогласие/клик).
- Страницы: `concepts/dangerous_mode.md`, `entities/tool_manager.md`,
  `entities/textual_ui.md`, `entities/botinok_cli.md`,
  `entities/tools/{file-system,code-editor,shell-exec,curl}.md`.

## [2026-09-18] ingest | web-кит: один добыватель вместо четырёх инструментов
Консолидация `web_search` + `open_url` + `web_extract` + `curl` в единый
инструмент `web` (`tools/web.py`) с каркасом «помогающего» инструмента.
- **Действия**: `auto` (роутинг по content-type), `open` (читаемый markdown),
  `extract` (links/images/headings/meta/tables + `css`), `json` (jq или сводка),
  `download`, `search` (DDG HTML через httpx, fallback lynx), `help`.
- **Харнес** (по образцу `session_memory`): мета (`kind/type/size/elapsed/final/
  saved/items/truncated`), `provenance` (`readable/extracted/projected/raw/saved`),
  «💡 Совет», «➡ Следующие шаги (web)».
- **Контекстная дисциплина**: большие HTML/JSON сохраняются в папку сессии,
  в контекст идёт превью + путь.
- **Фикс регрессии curl**: `jq_filter` был вырезан реализацией в `307dcf8`
  (29.03.2026), но остался в схеме → `TypeError`. Восстановлен через
  `web action=json`; `curl`/`web_extract`/`open_url`/`web_search` стали
  тонкими обёртками.
- **Схема/гейт**: в `_tool_registry` добавлен `web`; `allowed_in_session` и
  `is_dangerous_tool` учитывают запись `web` вне сессии (→ dangerous mode).
- **Промпты**: `tool_policy.txt` и `tool_reminder.txt` рекомендуют `web`.
- **Тесты**: `tests/test_web_kit.py` (локальный HTTP-сервер: все действия,
  харнес, jq-safety, регрессия `jq_filter`, гейт записи).
- Страницы: `entities/tools/web.md`, `concepts/web_kit.md`; обновлены
  `entities/tools/{curl,web-extract,open-url,web-search}.md`, `entities/tool_manager.md`,
  `index.md`.

## [2026-09-18] lint/fix | web: тело ответа сервера на ошибке + общая методика
Диагностика сессии `20260918_203213`: новый `web action=json` на HTTP 400
**выбрасывал тело ответа сервера**, поэтому модель не видела присланную
причину и перебирала параметры (несколько неудачных запросов, обращение к
legacy `curl`, потеря времени). Ошибка универсальная и не зависит от темы
запроса: если сервер объясняет причину в теле, инструмент обязан её показать.
- `_http_error` теперь включает `Ответ сервера: <reason>` (общий разбор JSON
  `reason/error/message/detail`).
- **Методика вместо доменной конкретики**: из текста ошибки извлекается имя
  упомянутого сервером query-параметра и в «Следующих шагах» предлагается
  вызов без него; автоматически делается только беззнаковая правка —
  декодирование безопасных процент-экранирований (`%2F/%3A/%2C/%40`),
  структурные `& = # ?` не трогаются. Конкретные значения API в коде не
  зашиваются.
- Тесты: `tests/test_web_kit.py` — `http_error_body`, `encoded_slash_autofix`,
  `param_named_in_error`, `param_strip_next_action`; страница
  `entities/tools/web.md` дополнена разделом «Умные ошибки (методика)».

## [2026-09-18] ingest | web: надёжные загрузки (aria2c, память, докачка, хеши, торренты)
Диагностика сессии `20260918_212628` (погода + фото): на фото-этапе
`khv_amur_panorama.jpg` на диске оказался ровно **256000 байт** из 4608×3072 —
новый `web` **молча обрезал** загрузку по `max_bytes` (старый curl не обрезал, а
отказывал). Плюс Wikimedia на 429 отдавала HTML, который мог сохраниться как
картинка, а извлечение фото было хрупким (только `img[src]`).
- **`tools/download_manager.py`** — глобальная память загрузок
  (`~/.botinok/downloads/history.json`, вне сессий): статус, размер, sha256, тип,
  движок; `verify`/`pending`. Новая сессия не качает заново — `web` вернёт целый
  файл из памяти; недокачанное предлагается к `resume=true`.
- **`web` download**: через `aria2c` (докачка, большие файлы/ISO, торренты
  `magnet:`/`.torrent`, `--seed-time=0`), без обрезки; HTML-заглушки
  распознаются и не сохраняются; `expected_sha256` — при несовпадении файл
  удаляется; `action=downloads` — память/проверка.
- **Извлечение фото**: `srcset`, `data-src`/`data-original`/`data-lazy-src`,
  `source[srcset]`, `og:image`/`twitter:image`; ранжирование фото выше иконок.
- **Фикс `_human_size`** (двойное деление).
- Тесты `tests/test_web_kit.py`: `download_not_truncated`, `html_stub_rejected`,
  `download_sha_ok`/`download_sha_mismatch`, `downloads_memory`/`downloads_pending`,
  `images_lazy_and_og`, `torrent_detect`, `magnet_destination`.
- Live: тот же файл теперь качается целиком (3.6 МБ) через aria2c.
- Страницы: `entities/tools/web.md`, `entities/download_manager.md`, `index.md`.

## [2026-09-18] ingest | web: HTTP-методы и тело запроса (работа с веб-API в простом режиме)
Диагностика сессии `20260918_212628`: модель работала с **Ollama API** и получила
`HTTP 405 method not allowed` на `http://localhost:11434/api/generate` — `web`/`curl`
умели только GET, а API требует POST с JSON-телом. Плюс `Error calling tool 'curl':
TypeError: execute() got an unexpected keyword argument 'resume'`.
- `web`: параметры `method` (GET/POST/PUT/PATCH/DELETE), `json_body`/`body`/`data`;
  запросы с телом идут обычным HTTP-путём, GET без тела — через aria2c.
- `curl` (legacy): принимает `method`, `json_body`/`body`/`data`, `resume`,
  `expected_sha256` — устранён TypeError.
- Сеть/API разрешены **в простом режиме** (dangerous mode — про локальный
  код/файлы/шелл, не про веб).
- Тесты: `api_get_405`, `api_post_json`, `curl_post_json`, `curl_resume_accepted`.
- Live: POST к реальному Ollama `/api/show` вернул данные (без dangerous mode).
- Страницы: `entities/tools/web.md`.

## [2026-09-18] ingest | safe_ops: каталог безопасных операций, help и подсказки эквивалента
Задача: агент в простом режиме должен делать «исследование системы и базовые
вещи», а при попытке запустить запрещённую shell-команду получать безопасную
альтернативу. Историческая причина: гейт `shell_exec`/`code_editor` был снят в
`56f1768` и возвращён в `48a5a5c`, из-за чего `base64`/базовые команды стали
недоступны.
- **`tools/safe_ops.py`** — единый реестр read-only операций: `fs.base64`,
  `fs.file_type`, `fs.stat/count/hash/listing/readlink`, `text.base64_decode`,
  `sys.uptime/loadavg/cpu/mounts`, `proc.top`, `svc.list`, `net.interfaces/ports/dns`,
  `dev.which`, `image.meta`, `git.*` (read-only). argv без shell, `LC_ALL=C`,
  лимиты/таймаут, только обычные файлы.
- **«Умный» харнес:** `file_system action=help` (сгруппированный каталог с
  примерами), прощающий ввод (алиасы), «похоже, вы имели в виду»,
  совет/следующий шаг, `suggest_for_shell` для запрещённого shell.
- **`ToolManager`**: при блокировке `shell_exec run` возвращает безопасный
  эквивалент (напр. `base64` → `file_system action=inspect command=fs.base64`).
- **`web`**: маркер `{"$file_base64":"/путь"}` в теле — файл кодируется самим
  `web` (`_resolve_file_markers`), base64 не проходит через модель. Live: фото →
  Ollama `/api/chat` принято (`prompt_eval_count` вырос, модель обрабатывает).
- **Промпты**: `tool_policy.txt`/`tool_reminder.txt` — в безопасном режиме смотреть
  `file_system action=help`, не пытаться выполнять shell-команды.
- Двухуровневая модель: безопасный каталог везде; файловые мутации внутри сессии;
  выполнение кода — всегда dangerous.
- Тесты: `tests/test_safe_ops.py`, `file_base64_marker` в `test_web_kit.py`.
- Страницы: `entities/safe_ops.md`, `concepts/dangerous_mode.md`,
  `entities/tools/web.md`, `index.md`.
