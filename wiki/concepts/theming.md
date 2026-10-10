---
type: concept
tags: [tui, config]
updated: 2026-10-10
sources: 4
status: stable
---

# Темы оформления TUI (ночь / день / вечер)

Три темы с переключателем-иконкой в шапке TUI. Реализовано 2026-10-10 (`core/themes.py`, тест `tests/test_themes.py`).

## Реализация

- **Темы** (`core/themes.py`): `night` — **по умолчанию, клон textual-dark, внешний вид не менялся**; `day` — белая (dark=False, #ffffff); `evening` — голубая (фон #0d2b45, акцент #7ec8ff). Каждая — `textual.theme.Theme` со стандартными токенами + кастомными `variables` (`hdr-bg`, `hl`, `shell-bg`, `cmd-bg/-fg/-border`, `flag-*`, `danger-bg`, `warn-bg`, `ok/warn/err`, `pager-fg`, `accent-fg`) — в них вынесены цвета, ранее захардкоженные в CSS; в ночи значения равны прежним литералам 1-в-1.
- **CSS** `BotinokTextualApp` токенизирован: все литералы заменены на `$токены`; правила, уже использовавшие `$surface/$primary/$text-muted` и т.п., не тронуты — night не изменилась.
- **Переключатель**: одна иконка `#theme_btn` в левом верхнем углу шапки (`header_row`, перед `#header`). Показывает **следующую** тему цикла ночь→день→вечер; клик — применить её (тот же паттерн `on_click`+`event.stop()`, что у `#auto_flag`). Глифы текстовые, width=1: `☾` / `☀︎` (с VS15) / `◓`.
- **Персист (глобально, для всех)**: `[UI] theme = night|day|evening` в `~/.config/botinok/config.cfg`; запись — построчная правка (`save_theme_name`), комментарии конфига сохраняются, каталог создаётся. Чтение: глобальный > fallback (config сессии) > night.
- **Покрытие всех Textual-приложений**: `ThemedAppMixin` (`core/themes.py`) — регистрация палитр, применение глобального выбора, `make_theme_btn()` (иконка в левом верхнем углу, `dock: top`) и `on_click`-цикл с персистом. Подключено к: `BotinokTextualApp`, `_SelectApp`/`_TextApp` (`textual_prompts` — через них работает и `config_wizard`), `SessionPickerApp` (иконка на `_MenuScreen` и `_ListScreen`), `HistoryViewerApp`. Важно: Textual вызывает обработчики `on_*` по всей MRO — класс не должен дублировать обработку темы, иначе двойной цикл.
- **Рамки меню/пикеров** (`cyan`) тоже переведены на `$hl` — темятся.
- **Не темизуются** (осознанно, follow-up): inline-акценты `[cyan]/[yellow]/…` (~300 мест — семантические предупреждения/ошибки), ANSI-вывод терминала, pygments-подсветка в пейджере, chafa-баннер, CSS `HistoryViewerApp`/`ShellScreen`.

Ниже — исходное исследование (сохранено).

## Текущее состояние (где живут цвета)

- `BotinokTextualApp.CSS` (`core/textual_app.py:625-740`) — ~40 правил; цвета частично захардкожены (`#0055aa` шапка, `#0f0f0f`/`#0c0c0c` терминал, `#cc8800` флаг, `#5f87af` рамки, `cyan`/`yellow`/`green`/`red` рамки панелей), частично уже через дизайн-токены Textual (`$surface`, `$primary`, `$panel`, `$text`, `$text-muted`, `$success`, `$error`).
- Inline-Rich-разметка в коде: ~300 вхождений `[cyan]`/`[yellow]`/`[dim]`… (textual_app.py ~160, textual_integration.py ~92, остальные — history viewer, shell_screen, session_picker). Это главный объём миграции.
- Подсветка кода в Markdown: pygments `code_theme` (тёмный по умолчанию).
- Баннер-логотип: chafa-рендер (`core/image_render.py`) — зависит от предполагаемого цвета фона терминала.
- Конфиг: `config.cfg` секция `[UI]` (`entities/config_system.md`); цепочка приоритетов personal → local → system.

## Что даёт Textual 8.2.3 (уже установлено)

- `textual.theme.Theme(name, primary, background, surface, panel, text, text_muted, …, dark=bool, variables={...})` — стандартные токены + **произвольные кастомные переменные**, доступные в CSS как `$my-token`.
- `App.register_theme(theme)` + реактивное `App.theme = "night"` — мгновенный рестайл всего UI без рестарта.
- Textual markup поддерживает подстановку переменных: `[$accent]` в строках разметки резолвится в цвет активной темы → inline-разметку можно мигрировать постепенно.
- Команда палитры «Switch theme» — бонусом из коробки.

## Предлагаемая архитектура

1. **`core/themes.py`** — три встроенных палитры (day/evening/night) как словари токенов + резолвер: `[UI] theme = day|evening|night`, переопределение любого цвета секцией `[theme:<имя>]` в config.cfg (configparser). Встроенные дефолты — чтобы config.cfg не раздувался; пользователь правит только то, что хочет.
2. **Токенизация CSS**: все литералы в `CSS` заменяются на токены; кастомные нужды (цвет шапки, фон логов терминала, рамки) — через `Theme.variables`.
3. **Миграция inline-разметки**: `[cyan]` → `[$accent]` и т.п. инкрементально (немигрированные места просто останутся фиксированного цвета — не ломается).
4. **Переключатель в шапке**: три кликабельных `Static` `☀ 🌆 🌙` рядом с `#auto_flag` (тот же паттерн: `on_click` + `event.stop()`, `textual_app.py:3034`); активный подсвечен CSS-классом. Клик → `self.theme = name` + запись `[UI] theme` в config.cfg + строка в лог. Клавиатурный цикл — опционально (напр. Ctrl+T).
5. **Прочее по теме**: pygments `code_theme` светлый для day; chafa-баннеру передавать фон темы; проверить `strip_ansi_backgrounds`/ANSI-прострелы терминала (свой цвет не темизируем — осознанно).

## Риски

- ANSI-цвета стороннего вывода (shell-логи, `xterm-256color`) тему не уважают — приемлемо.
- Светлая тема + терминал с белым фоном: задавать явные hex везде (уже планируется), `dark=False` у Theme.
- Полный рестайл при переключении — разовый, не горячий путь; метрики чата не затронет.

## Связи
- `entities/textual_ui.md` — где вешать переключатель (header_row, паттерн auto_flag).
- `entities/config_system.md` — формат и приоритеты конфига.
- `concepts/terminal_unicode_width.md` — пиктограммы ☀🌆🌙 должны быть одноширинными (риск «плыущей» шапки).
