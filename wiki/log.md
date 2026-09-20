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

## [2026-09-18] ingest | мгновенная остановка по Esc: killpg дерева процессов
Симптом: Esc во время работы инструмента не прерывал действие — «Stop requested»
копился (4 раза на скриншоте), а процесс (aria2c/jq/lynx) продолжал работать,
потому что `subprocess.run` блокирует поток и не реагирует на флаг.
- **`core/process_control.py`**: единый реестр процессов + `run()` с
  `start_new_session=True`, `communicate` в потоке и опросом `stop_event`;
  `request_stop()` убивает группу (`SIGTERM`→grace→`SIGKILL`) — процесс и всех
  порождённых, ничего не остаётся.
- `App.request_stop()` → `process_control.request_stop()` +
  `ShellSessionRegistry.close_all()`; Esc логирует «Остановлено» один раз
  (`_stop_logged`); `start_assistant_turn` сбрасывает флаг.
- Прерванный инструмент фиксируется в сессии как `aborted`
  («ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ…»), ход не продолжается.
- `web` (aria2c/jq/lynx/httpx-циклы), `safe_ops`, `file_system._run_safe_command`
  переведены на прерываемый `run`.
- Тесты: `tests/test_process_control.py` (быстрое прерывание + отсутствие
  оставшихся «внуков»). Страницы: `entities/process_control.md`,
  `entities/textual_ui.md`, `index.md`.

## [2026-09-18] fix | остановка самой модели по Esc (обрыв стрима)
Дополнение к остановке процессов: Esc не останавливал **генерацию LLM**.
`response.close()` не прерывает блокирующий `response.iter_lines()` в потоке-
читателе → Ollama продолжал генерировать, а UI просто вставал.
- `_abort_stream(response)`: `shutdown(SHUT_RDWR)` сокета (`response.raw._fp.fp.raw._sock`;
  для OpenAI-обёртки — `._resp`), затем `raw.close()/release_conn()` и
  `response.close()`. Разблокирует read и рвёт соединение → сервер прекращает
  генерацию.
- Применяется на всех путях остановки и при детекте повторов; после
  `stopped_by_user` частичный ответ сохраняется и ход завершается.
- Тест `tests/test_abort_stream.py`: локальный медленный NDJSON-сервер видит
  разрыв (BrokenPipe), поток-читатель останавливается < 3 с.
- Страницы: `concepts/streaming_tui.md`, `entities/process_control.md`.

## [2026-09-18] fix | Esc: не терять флаг остановки между итерациями
Симптом: после «Остановлено» модель всё равно делала новые tool-call'ы и
размышления. Причина: `start_assistant_turn` вызывается на **каждой** итерации
цикла инструментов и сбрасывал `_stop_requested`/`process_control.clear_stop()`,
гася Esc.
- Сброс флага остановки перенесён в `reset_turn_state` (один раз на запрос
  пользователя); `start_assistant_turn` больше его не трогает.
- Явные проверки стопа: в начале итерации (перед новым запросом к модели),
  после каждого инструмента и **перед стартом** инструмента — при остановке
  оставшиеся `tool_calls` не выполняются, а закрываются aborted-результатами
  (в истории нет «висячих» вызовов).
- UI возвращается в покой (`_finalize_turn`), частично надуманное сохраняется.
- Страницы: `concepts/streaming_tui.md`, `entities/process_control.md`.

## [2026-09-18] fix | сохранность сессии: атомарная запись и восстановление
Симптом: «Ошибка загрузки истории: Expecting ',' delimiter…»; огромная сессия
выглядела пустой. Причина: Esc не останавливал модель (см. выше) → приложение
закрыли во время записи крупного `context.json`; `update_context` писал
`json.dump` прямо в файл (не атомарно) → файл обрублен; ошибка чтения глушилась,
история переставала обновляться.
- `_atomic_write_json` (tmp+fsync+`os.replace`, бэкап `.bak`) в `update_context`,
  создании сессии и proofreader.
- `_read_json_with_backup` + `load_history_entries` (context → `.bak` →
  `messages.json`); `update_context` засевает историю из снапшота и откладывает
  битый файл в `context.json.corrupt-<ts>`.
- `load_history` использует надёжный загрузчик (не падает на битом JSON).
- Реально восстановлена сессия `20260918_212628` (64 записи из `messages.json`).
- Тест `tests/test_session_recovery.py` (атомарность, `.bak`, fallback, засев).
- Страницы: `entities/session_manager.md`.

## [2026-09-18] fix | Esc: прервать и ЖДАТЬ, а не убивать сессию
Симптом: Esc «не завершал» ход: модель/авто-продолжение шли дальше, а при
остановке сессия получала обрубленный `context.json` и умирала.
- `process_control.signal_stop()` — мягкая остановка (только флаг); запущенный
  `run()` сам гасит свою группу. `request_stop()` оставлен как жёсткий kill_all.
- `App.request_stop()` больше НЕ зовёт `kill_all()`/`ShellSessionRegistry.close_all()`:
  убийство из обработчика клавиши гонялось с записью `context.json`.
- `flush_tool_buffer` при остановке не отправляет накопленную очередь, а
  возвращает её в поле ввода и пишет «Жду следующее сообщение…».
- Контракт: Esc → стоп хода → ожидание следующего сообщения (без авто-продолжений).
- Предыдущая правка (сброс флага только в `reset_turn_state`) остаётся.
- Тест `tests/test_process_control.py`: `signal_stop` прерывает `run()`, но
  посторонний процесс не убивает.
- Страницы: `entities/process_control.md`.

## [2026-09-18] repair | восстановление сессии 20260918_212628_visual_run
Причина потери: `context.json` был записан обрубленным (неатомарная запись),
затем восстановление засеяло историю из `messages.json` — а это скользящее окно
последних 20 сообщений → потеряна история 21:26–23:36.
- Жёсткий сброс убран: `update_context` больше не перезаписывает историю
  снапшотом и не переносит файл; `_salvage_history` вычитывает максимум из
  обрезанного JSON, `_merge_history` склеивает источники без потерь.
- `_read_history_soft`: context.json → salvage → .bak → messages.json; на нём
  переведены `load_history_entries`, `build_resume_brief`, `restore_session`,
  `audit_context`. Приложение и просмотрщик истории читают через него.
- Сессия восстановлена: 311 записей — `.corrupt-1789738545` (130) + context/bak
  + снапшот + достройка ассистентских ответов из `session_raw.log` и tool-шагов
  из `steps/` (21:xx–23:xx непрерывно). Оригиналы и полный бэкап папки сохранены.
- Тест `tests/test_session_recovery.py` (атомарность, `.bak`, salvage, fallback).
- Страницы: `entities/session_manager.md`.

## [2026-09-18] fix | тесты больше не сорят в рабочие сессии
Симптом: приложение открывало пустую «сессию» с «привет/ответ/ещё» вместо
настоящей (полдня диалога) — тесты создавали сессии в `~/.botinok/sessions`, и
самая свежая (`*_recovery-test`) перебивала реальную.
- `SessionManager` понимает переопределение `BOTINOK_SESSIONS_DIR` (env).
- `tests/test_session_recovery.py` пишет в `tempfile.mkdtemp` (изоляция).
- Мусорные `*_recovery-test`/`*_recovery-snapshot` и бэкап убраны из
  `~/.botinok/sessions`; настоящая сессия снова самая свежая.
- Страницы: `entities/session_manager.md`.

## [2026-09-19] fix | защита от пустого («молчаливого») завершения модели
Причина обрыва ответа в сессии 20260919_090557 (11:58:10): бэкенд сгенерировал
`eval_count=52`, но клиент не получил ни `content`, ни `thinking`, ни `tool_calls`;
ветка `if not tool_calls:` сохраняла пустого ассистента, финализировала ход и
гасила сессию без лога/ошибки.
- `_is_empty_completion(full_response, full_thinking, tool_calls)` — классификатор.
- Обработка в `core/textual_integration.py`: видимая пометка в UI + system-заметка
  в сессию, повтор запроса (`auto_continue_final`) до `MAX_EMPTY_RETRIES_PER_TURN=3`,
  при исчерпании — явное сообщение и ожидание следующего ввода. Счётчик
  сбрасывается на нормальном ответе.
- Обрыв генерации по повторам (`_detect_repetition` → `_abort_stream`) теперь
  логируется.
- Тест `tests/test_empty_completion.py`.
- Страницы: `concepts/streaming_tui.md`.

## [2026-09-19] feat | edit-кит: code_editor по парадигме web/session_memory
Повод: живая сессия `20260919_090557_visual_run` — 32 `replace` подряд по
49 КБ-файлу почти без перечитываний, 2× «old_text не найден», потеря заголовка
из-за правки без diff, `TypeError` на лишнем аргументе `limit`.
- `tools/code_editor.py` переписан: каркас `_meta/_provenance/_confidence/
  _advice/_next_actions/help`; fuzzy-матчинг + `nearest`; `apply` = несколько
  замен атомарно (`edits`); `undo` из чекпоинтов (`.edit_backups/`); unified
  `diff`; атомарная запись; сохранение BOM/CRLF/кодировки; отказ на бинарь;
  стейл-контроль (серверный хэш + `expected_sha256`); пагинированное чтение;
  прощающий ввод (алиасы, игнор неизвестных аргументов).
- `DANGEROUS_EDITOR_ACTIONS` += `undo`; схема и описание инструмента обновлены.
- `_compact_tool_message` (botinok.py, textual_integration.py) скрывает `edits`.
- `prompts/tool_reminder.txt` — apply/undo/diff.
- Тест `tests/test_code_editor.py` (все проверки пройдены); `tests/test_dangerous_mode.py` — без регрессий.
- Страницы: `entities/tools/code-editor.md`, `concepts/edit_kit.md`, `index.md`.

## [2026-09-19] fix | edit-кит: правки после ревью
- **Fuzzy переписан на построчное сравнение**: не страдает от auto-junk на
  частых символах, дешёвый; лимиты на строки/длину фрагмента/число сравнений +
  ранний выход при неоднозначности. Раньше полный char-level `ratio()` на 100
  строк мог идти минутами.
- **Чтение**: файл читается целиком (до `max_bytes`), пагинация `offset/limit`
  работает на всём файле (раньше — только первые 200 КБ); корректный подсчёт
  строк (без фантомной строки от trailing `\n`), нет инвертированного диапазона
  в конце файла; UTF-8 на границе больше не декодируется как cp1251.
- **EOL**: поддерживаются LF/CRLF/CR; смешанные нормализуются с пометкой
  `eol_normalized` (не молча).
- **`undo`**: проверяет `after_sha256` чекпоинта (sidecar), при внешнем
  изменении — `stale`; принудительно — `force=true`.
- **Алиасы действий** нормализуются в гейтах (`editor_action_of`), закрыт обход
  подтверждения dangerous mode через `save/edit/patch/revert/restore`.
- Вынесен общий `_commit` (убрано дублирование write/replace); удалён мёртвый
  `has_bom`.
- Тест `tests/test_code_editor.py` расширен (пагинация, EOL, границы fuzzy,
  undo-stale/force, alias-gate); регрессии зелёные.
- Страницы: `entities/tools/code-editor.md`.

## [2026-09-19] fix | file_system: grep по файлу и regex
Повод: живая сессия `20260919_090557_visual_run` — grep систематически возвращал
«Совпадений не найдено», из-за чего модель уходила в полные чтения файлов.
- **Причина 1:** `_grep_files` строил glob `path/*`; при `path` = файл файлов не
  находилось → всегда «не найдено». Теперь `path` может быть файлом.
- **Причина 2:** `content_query` искался как литеральная подстрока, а модель
  передавала regex (`^## `, `3\.8`, `a|b`). Теперь grep — regex
  (регистронезависимо) с fallback на текст при некорректном regex;
  `inspect grep.contains` остаётся литеральным, `grep.regex` — regex.
- **Причина 3:** модель передавала запрос в `pattern` → «content_query
  обязателен». Прощающий ввод: если `content_query` пуст, запросом становится
  `pattern`; `search` с `content_query` теперь ищет по содержимому.
- Схема/докстринг обновлены; вывод grep — с числом совпадений и подсказкой.
- Тест `tests/test_file_system_grep.py` (16 проверок), регрессии зелёные.
- Страницы: `entities/tools/file-system.md`.

## [2026-09-19] fix | резолв путей сессии: устранена ловушка project/project
Повод: самотест 01 в сессии `20260919_145122` — модель передала относительный
`project/notes.txt`, TUI приклеил `<session>/project/` и получился
`project/project/notes.txt` (3 потерянных вызова, удаление вложенного каталога).
- Введён `core/path_utils.resolve_session_path`: относительный путь →
  `<session>/project/`, ведущий `project/` не дублируется; абсолютный — realpath.
- Применён в TUI (`core/textual_integration.py`), в `code_editor` и `file_system`.
- Гейт `allowed_in_session` резолвит `path`/`dest`/`output_path` тем же
  резолвером (относительные in-session мутации больше не блокируются).
- Тест `tests/test_path_resolution.py` (20 проверок); регрессии зелёные.
- Страницы: `entities/tools/code-editor.md`, `entities/tools/file-system.md`,
  `tests/selfcheck/README.md`.

## [2026-09-19] feat | code_editor: проверка синтаксиса + реестр типов файлов
Мотив: в safe-режиме модель не может запускать код и не получала обратной связи
о корректности созданного кода (задачи 10/13 самотестов).
- `core/file_kinds.py` — каскад определения типа: shebang/magic (EXACT) →
  расширение (`mimetypes`+Pygments, DERIVED) → сниффер по содержимому (HINT);
  возвращает ранжированных кандидатов (при неоднозначности — выбор `kind=`).
- `core/syntax_check.py` — проверка без запуска кода: python/json/toml/yaml/xml
  через stdlib, bash/js/ts/html через tree-sitter (`tree-sitter-language-pack`).
- `code_editor`: action=check (read-only) + **автопроверка после
  write/replace/apply**; результат в поле `syntax` и в `_advice`
  (✅ OK / ⚠️ строка N) — информационно, без требования исправлять.
- Зависимость `tree-sitter-language-pack>=1.20` в requirements.txt (install.sh и
  апдейтер botinok.py подхватят при обновлении).
- Тест `tests/test_syntax_check.py`; регрессии зелёные.
- Страницы: `entities/tools/code-editor.md`, `index.md`.

## [2026-09-19] feat | панель «Производительность»: живые русские метрики, профили сервера, трафик, детектор зависаний
Повод: панель показывала часть цифр замороженными (счётчики Thinking/Response/
Tool/TTFT/TPS писались только по завершении потока), англо-аббревиатуры и
ложное «No models loaded» при работе через OpenAI-совместимый бэкенд.
- **Живое ядро**: размер «Размышляет»/«Написал ответ» считается по уже
  пришедшему тексту, «Скорость» (Б/с), «Первый ответ», «Этап», «Модель
  молчит»; `_tick_stats` форсирует перерисовку 10/с, пока задача активна.
- **Русские подписи** и перевод всех статусов (`_ru_status`); заголовок панели —
  «Производительность».
- **Профили сервера** (`stats_data["server"]`): Ollama (расширенный) — строка
  «Видеопамять», «Готовит команду», точные метрики; OpenAI-совместимый — эти
  строки скрыты (сервер их не сообщает).
- **Трафик модели**: новый `core/net_meter.py` — перехват `HTTPAdapter.send`,
  «АПИ отдано / АПИ принято» за запрос и за сессию, скорость приёма, число
  обращений. Инструменты считаются автоматически (летят внутри чат-запроса).
- **Детектор зависаний**: молчание 10/30 с и инструмент 1/5 мин → жёлтый/красный,
  растущие счётчики и подсказка про Esc; прокинут `retries` (попытки связи).
- Тест `tests/test_perf_panel.py`; регрессии (abort_stream, shell_*, confirm,
  dangerous, syntax, code_editor, file_system) зелёные.
- Страницы: `entities/net_meter.md` (новая), `entities/textual_ui.md`,
  `concepts/streaming_tui.md`, `overview.md`, `index.md`, `raw/README.md`.

## [2026-09-19] fix | ошибки API называют реальный сервер, а не «Ollama»
Повод: при работе через OpenAI-совместимый бэкенд падал 503, а в лог писалось
«Ollama Error 503: Unknown Error» — подпись всегда врала бэкендом.
- `_server_label(sm)` — имя реального сервера («Ollama (url)» / «OpenAI-совместимый
  сервер (url)»); применено к сообщениям об ошибке связи, HTTP-ошибке и обрыве потока.
- `_extract_api_error(data)` — достаёт текст ошибки из любого формата
  (`{"error": "..."}`, `{"error": {"message": ...}}`, `{"detail": ...}`), вместо
  постоянного «Unknown Error».
- Артефакт `ollama_http_error_*` → `api_http_error_*`.
- Таймауты не менялись (`RequestTimeout=300`); автопродолжение не затрагивалось
  (503 был из-за недоступного сервиса).

## [2026-09-19] feat | сессия держится при сбоях API (удержание до суток)
Повод: при 502/503 от OpenAI-совместимого сервера ход завершался после 2 попыток
(фикс. пауза 2–3 с), и сессия выглядела «оборванной».
- `_try_hold(reason)`: временные сбои (сеть, `429/500/502/503/504`) пережидаются
  с экспоненциальной паузой до `MaxRetryBackoffSec` (60 с) в пределах
  `RetryBudgetSec` (по умолчанию 86400 с — сутки). Прерывание — `Esc`.
- Ошибка печатается **один раз**, рядом растёт счётчик: в панели строка
  «Ждём сервер: N с (попыток: K)» (`retry_wait`, `retries`).
- Счётчики сбрасываются на успешном стриме; тот же запрос переотправляется
  (бэкенд stateless), ход не теряется.
- Постоянные `4xx` — без пережидания (сохраняется прерванный ход).
- Защита от «тихой смерти» модели (`_is_empty_completion` + `auto_continue_final`)
  не тронута и подтверждена тестом.
- config.cfg: `retrybudgetsec`, `maxretrybackoffsec`.
- Тесты: `tests/test_api_resilience.py`; `test_empty_completion`, `test_abort_stream`,
  `test_perf_panel` — зелёные.
- Страницы: `concepts/streaming_tui.md`, `sources/config_cfg.md`.

## [2026-09-19] feat | очередь «мыслей»: сказать модели, не прерывая
Повод: во время длинной генерации ввод копился и доходил до модели только в конце
хода; хотелось передать мысль на ближайшей границе, без обрыва.
- Внизу над полем ввода — панель `#thought_queue`: каждая мысль чипом «💭 …» с
  крестиком отмены до отправки (`_render_thought_queue`, `_remove_queued`,
  `on_button_pressed`).
- `take_queued_thoughts()` — атомарно забирает ВСЕ мысли одним блоком и очищает
  очередь (одна мысль не уйдёт дважды).
- Доставка: в цикле хода после раунда инструментов, до следующего запроса
  (`textual_integration`); текст с лёгкой пометкой `(во время работы)`, без
  указаний «прерви/продолжай» — модель решает сама.
- Esc: очередь мыслей возвращается в строку ввода одним блоком; мысли живут
  только в памяти (не персистятся).
- Тест `tests/test_thought_queue.py`; набор smoke-тестов (15) зелёный.
- Страницы: `concepts/thought_queue.md` (новая), `entities/textual_ui.md`,
  `concepts/streaming_tui.md`, `index.md`.

## [2026-09-19] fix | старт клиента: экранирование markup в заголовках/панелях
Повод: сессия с tool-call, где в аргументах код-редактора есть JSON-массив
(`edits:[{...}]`) и `\"\"`, роняла TUI при загрузке истории:
`MarkupError: Expected markup value` в `Collapsible(title=...)` (заголовок
парсится как Rich-markup).
- `_spoiler_title`: экранирует label и превью (`_rich_escape`) — заголовок
  спойлера больше не ломается на `[`.
- `_diag_card_title` и `_update_diag`: экранируют текст вопроса; содержимое
  диаг-карточки — `Static(..., markup=False)`.
- `_tool_details`: экранирует запрос/результат инструмента (панель инструментов).
- Тест `tests/test_startup_client.py` — **главная проверка «клиент загрузился»**:
  строит сессию с «ядовитой» историей (скобки/`\"\"` в промпте, аргументах,
  результате, diag и панели инструментов) и требует, чтобы приложение
  стартовало. Без фикса тест падает (`client_started` FAIL).
- Набор smoke-тестов: 16 зелёных.

## [2026-09-19] feat | доставленная мысль видна в чате и отмечена в промтах
- `deliver_thought_block()`: ушедшая в поток мысль показывается в чате как
  сообщение пользователя («💭 Моя мысль (во время работы): …») и регистрируется
  в верхней панели промтов как `kind="thought"` — облачко + метка времени
  отправки, отличимый цвет (`_diag_card_title`, `_update_diag`).
- Мид-турн доставка в `textual_integration` вызывает `deliver_thought_block`
  (раньше — `append_user_message` без отметки в промтах); конец хода —
  `flush_tool_buffer`.
- Заодно убран шум: пустой `user` больше не пишется в контекст на границах
  раунда (в живой сессии виделись пустые `user:` между tool-результатами).
- Тест `tests/test_thought_queue.py` дополнен (видимость в чате, отметка в diag,
  метка времени, заголовок с 💭); набор smoke-тестов (16) зелёный.

### Наблюдение по живой сессии 20260919_163427
Мыслей с меткой в истории 0 — новая очередь в ней ещё не отрабатывала. Проверено
по `context.json` (`history`, 868 записей): блоков «(во время работы)» нет.

## [2026-09-19] fix | мысль не уходила в поток: двойной забор очереди
Корень: `_call_from_thread_result` вызывал `app.call_from_thread(...).result()`,
но Textual `call_from_thread` возвращает результат НАПРЯМУЮ (не Future). `.result()`
бросал AttributeError уже ПОСЛЕ выполнения колбэка; fallback повторно вызывал
`take_queued_thoughts()` в рабочем потоке на уже очищенной очереди и возвращал
пусто. Итог: чипы мыслей исчезали, а в поток ничего не уходило.
- Вынесено в `_call_ui_result(app, fn, ...)` (без `.result()`), nested-хелпер
  делегирует.
- Тест `tests/test_thought_queue.py::test_call_ui_result`: проверяет, что результат
  возвращается и функция вызывается ровно один раз (со старым `.result()` —
  `calls=2`, FAIL).
- ВАЖНО: запущенный процесс нужно перезапустить, чтобы подхватить фикс.
- Smoke-набор (16) зелёный.

## [2026-09-19] fix | ширина шапки промтов/мыслей: точный бюджет по ячейкам
Шапка «💭 Мысль:» переносилась: бюджет считался как `width - 10` без учёта
фактической ширины подписи. Теперь `_update_diag` и `_diag_card_title` считают
через `cell_width` (ячейки терминала): доступная ширина минус префикс и подпись
минус запас. Тест дополнен проверками `header_fits`/`card_fits` (при ширине 93).

## [2026-09-19] feat | панель запросов: «Запрос»/«Мысль», строки без сворачивания, свежие сверху
- Английское «Prompt» заменено на русское «Запрос»; добавлены лейблы:
  «📝 Запрос:» для обычных запросов и «💭 Мысль:» для доставленных мыслью.
- Свёрнутые карточки (Collapsible) заменены на простые строки подряд (`Static`),
  свежие — сверху; шапка окна показывает последнюю запись.
- Доставка мысли прокручивает список к началу (свежая строка сверху).
- Тесты: `test_thought_queue` дополнен (`prompt_label`, `diag_newest_first`,
  `thought_card_created`); набор 16 зелёный.

## [2026-09-19] feat | аккуратный перенос строк в панели запросов
- Добавлен `cell_wrap` (перенос по словам по ячейкам, принудительный разрыв
  длинных слов) в `core/text_width.py`.
- `_diag_row_text` переносит длинный текст с висячим отступом: продолжение
  выравнивается под текстом, первая строка — с временем и меткой; проверено
  визуально (ширина 93, строки ≤ 90).
- Тесты: `thought_wraps`, `thought_wrap_fits`, `card_fits` (по строкам); плюс
  проверки `cell_wrap` на пустом/длинном слове/эмодзи; набор 16 зелёный.

## [2026-09-19] fix | Esc не прерывал: терминал проглатывал клавишу
Корень (по живой сессии 20260919_163427): после нажатия Esc модель продолжала
стримить ~2 минуты. Причина — когда фокус на встроенном терминале,
`ShellScreen/ShellInline.on_key` видел `escape` в `KEY_SEQUENCES` (`b"\x1b"`),
отправлял байт в PTY и делал `event.stop()`; приложение Esc не получало.
Плюс проверка остановки была только по `is_streaming`.
- `maybe_stop_from_terminal(widget, event)`: при идущем ходе Esc останавливает
  агента и НЕ уходит в PTY; в покое — прокидывается как раньше.
- `turn_in_progress()`: «ход идёт» = стрим ИЛИ работающий инструмент; Esc
  прерывает и во время инструмента.
- Composer и `App.on_key` используют `turn_in_progress()`.
- Тест `tests/test_escape_stop.py` (юнит на терминал + UI: стрим, инструмент,
  фокус на кнопке мысли, очистка ввода в покое). Набор из 18 smoke-тестов зелёный.

## [2026-09-19] fix | Esc рвёт стрим на каждом чанке
В сессии 20260919_163427 после Esc модель продолжала стримить ~2 минуты, хотя
флаг остановки выставлялся (в UI писалось «прерывание»). Проверка остановки была
только между пачками дренажа: при плотном потоке внутренняя очередь не пустела,
и код не доходил до проверки.
- Внутри цикла разбора чанков теперь проверяется `app._stop_requested` НА КАЖДОМ
  чанке → `_abort_stream` и выход немедленно.
- Ранее в этой партии: `turn_in_progress()` (стрим ИЛИ работающий инструмент) и
  `maybe_stop_from_terminal()` (Esc из встроенного терминала не уходит в PTY).
- Тесты: `test_escape_stop.py`, `test_abort_stream.py` — зелёные.

## [2026-09-19] fix | ДОКАЗАННАЯ причина: Esc не прерывал из-за O(n²)-перерисовки
Воспроизведено интеграционным тестом `tests/test_escape_stream.py`: mock-модель
льёт крупный поток (проверены оба пути — Ollama NDJSON и OpenAI SSE). Без фикса
Esc не прерывает: `is_streaming` остаётся True, сервер не видит разрыв (тест
падает на 6-секундном таймауте). С фиксом — обрыв < 2 c.
- Корень: `append_assistant_chunk` на КАЖДОМ чанке пересобирал весь накопленный
  текст (escape + markup + `Static.update`) — O(n²). UI насыщался, воркер висел
  в `call_from_thread` и не доходил до проверки `_stop_requested`.
- Фикс 1: троттлинг обновления Static (~10/с) — текст копится полностью, в UI
  выводится не чаще 100 мс.
- Фикс 2: независимый сторож в `_stream_turn` — по флагу `_stop_requested`
  сразу рвёт соединение, не дожидаясь основного цикла.
- Фикс 3: проверка `_stop_requested` на каждом чанке (а не между пачками).
- Дополнительно: Esc из встроенного терминала не уходит в PTY; `turn_in_progress`
  (стрим ИЛИ инструмент).
- Тест доказывает: без фикса — FAIL, с фиксом — PASS. Набор 19 зелёный.

## [2026-09-19] fix | Esc возвращает управление при зависшем API (без заголовков)
Симптом (скрин): сервер atria вернул 504 и «завис»; Esc не возвращал управление,
пока запрос не отвалится по таймауту (до 300 с).
- `_post_stream_interruptible(app, do_request)`: HTTP-запрос стрима выполняется в
  отдельном потоке, воркер ждёт его с проверкой `_stop_requested` → Esc выходит
  немедленно; если ответ придёт позже, он закрывается.
- Панель: при переждании сервера (`retries`/`retry_wait`) строка «Ждём сервер:
  N — попытка K», а не «модель молчит / зависло» (убран ложный «зависло» и
  дублирующая строка).
- Тест `tests/test_escape_stream.py` дополнен кейсом «зависший сервер»: без
  фикса FAIL (`status='Generating...'`, 3 с), с фиксом PASS. Набор 19 зелёный.
- Страницы: `entities/process_control.md`, `concepts/streaming_tui.md`.

## [2026-09-19] perf/fix | CPU в простое и «перерисовка всего чата»
Повод: вентилятор в простое; ощущение, что метрики рендерятся с лишней работой.
- Профиль (headless, длинная сессия): `select.epoll.poll` — ожидание; реальный CPU
  уходил в полную пересборку Textual (`_render_chops`, `_styles_cache.render`,
  CSS-токенайзер) из-за `Static.update(..., layout=True)` каждые 0.1 с.
- Метрики: `stats_rows.update(..., layout=False)` и шапка `layout=False`; layout
  включается только при смене числа строк. Проверено: обновление метрик не
  вызывает `chat.refresh` (0 за 2 с). Скорость метрик сохранена — 10/с при ходе.
- Простой: ~25% → ~4% одного ядра; активный ход ~10% (метрики 10/с).
- Раскладка правой колонки: `#stats` (auto, не сжимается) → `#tools` (1fr,
  сжимается) → `#shells` (внизу). Терминалы растут вниз, больше не давят метрики.
- Страницы: `entities/textual_ui.md`, `concepts/streaming_tui.md`.

## [2026-09-19] perf | ленивая загрузка истории + свёрнутые спойлеры
Повод: на длинной сессии старт ~14.5с и «зависание» после загрузки; спойлеры в
старой истории открывались раскрытыми.
- Профиль: время уходит в CSS/стили Textual на каждый виджет (get_rule 4M вызовов)
  при синхронном монтировании всей истории.
- Ленивая загрузка: стартовый рендер только хвоста (`HISTORY_INITIAL_ENTRIES=200`),
  кнопка «⤒ Показать более раннее» и автодогрузка при прокрутке вверх
  (`HISTORY_BATCH_ENTRIES=200`), рендер в контейнер через `call_after_refresh`;
  индикатор «⏳ Загрузка сессии…». Полная отрисовка заменена на порционную.
- Спойлеры истории (`Thinking`, tool-call, Tool result) — всегда `collapsed=True`;
  Markdown истории монтируется через `_mount_widget` (учитывает цель батча).
- Замер (сессия 1007 записей): старт 14.5с → **2.5с**, виджетов 2505 → ~508,
  раскрытых спойлеров 0.
- Тест `tests/test_history_lazy.py`; набор 19 зелёный.
- Страницы: `entities/textual_ui.md`.

## [2026-09-20] ingest | показ изображений в чате: инструмент `image`, идентификаторы, ленивый рендер
Инструмент `image` (`tools/image_show.py`, реестр `image`): принимает картинку
файлом или по URL, кладёт в каталог проекта, возвращает `token` вида
`[[image:<id>]]` для вставки в текст ответа. В сессии хранятся только
идентификаторы (`core/image_catalog.py`, `core/image_refs.py`); id уникальны и
не повторяются (`seq` + `retired`, переиспользование по sha256).

Рендер: `core/image_render.py` (chafa → фолбэк, кэши ANSI/`rich.Text`, бюджет
памяти) + `core/image_block.py` — ленивый `ImageBlock` (фиксированная высота,
рисуется только видимый срез строк, видимость в виртуальных координатах
контейнера). В чате — прокрутка подтягивает картинки (`ChatScroll.watch_scroll_y`),
в стриминге маркер маскируется, пейджер F6 рендерит картинки chafa.

Диагностика фризов: `Text.from_ansi` на UI-потоке (1.2с при ширине 400) и
гигантский `Static` (~1.5с на maximize). Исправлено: парсинг в фоне + кэш;
баннер ограничен (`LOGO_MAX_WIDTH=168`, `LOGO_MAX_HEIGHT=48`); картинки чата —
видимый срез. Замер 4К (400×110, 60 шт. 200×800): старт 4/60 рендеров, срез
32/401 строк, провал UI 68 мс.

Тесты: `test_image_render.py`, `test_image_catalog.py`, `test_image_in_chat.py`,
`test_logo_rescale.py` (реальный maximize 4К), `test_lazy_images.py` (4К, высокие
картинки). Страницы: `entities/tools/image.md`, `concepts/image_rendering.md`,
`entities/textual_ui.md`.

## [2026-09-20] perf | нормализация изображений под терминал + полосовой рендер
Повод: огромные изображения (4000×2250 и выше) «люто тормозили» — декодировался
и рендерился весь файл, хотя терминал показывает лишь десятки строк.
- `core/image_render.prepare_scaled(source, width, rows)` — уменьшенная копия
  ровно под текущий размер окна (≈2 px/клетку), кэш на диске по (файл, mtime,
  ширина, высота); `Image.draft` для быстрого JPEG-декодирования; лимиты
  `BOTINOK_IMAGE_TERM_WIDTH_PX=1200`, `BOTINOK_IMAGE_TERM_PIXELS=2M`.
- `render_image_band(scaled, width, rows, y0, y1)` — chafa `--stretch` рисует
  только видимую полосу уменьшенной копии (кэш полос в памяти и на диске).
- `ImageBlock` переведён на два шага: подготовка копии под ширину окна, затем
  отрисовка видимого среза; полоса из 4000×3000 и из 400×300 стоит одинаково
  (16 мс vs 15 мс), подготовка 10 мс (кэш 0.04 мс).
- Тест `tests/test_image_scaling.py`; набор 37 зелёный.
- Страницы: `concepts/image_rendering.md`.
