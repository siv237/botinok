---
type: concept
tags: [tui]
updated: 2026-09-17
sources: 3
status: stable
---

# Ширина Unicode-символов в терминале (сдвиги панелей)

Почему в TUI «плывут» границы панелей на строках с эмодзи/необычными символами и
как это лечится.

## Причина
Терминал и библиотека (Rich/Textual) считают ширину символа по-разному. Для
эмодзи с variation selector (VS16, U+FE0F), например `❤️`/`👁️`/`🖼️`/`✍️`:

- Rich/Textual (`rich.cells.cell_len`) считают такой кластер **2 ячейки**;
- часть терминалов на Linux через glibc `wcwidth`/`wcswidth` считает **1**
  (баг glibc locale/32322); Ghostty, наоборот, даёт 2.

Если модель и терминал расходятся, строка рендерится на N ячеек короче/длиннее:
курсор «уезжает», и всё, что правее (в т.ч. границы соседних панелей), визуально
смещается, оставляя чёрные «дыры». Классический репорт —
Textual [#5980](https://github.com/Textualize/textual/issues/5980), разбор —
Ghostty
[#8027](https://github.com/ghostty-org/ghostty/discussions/8027), плюс
[grapheme clusters in terminals](https://mitchellh.com/writing/grapheme-clusters-in-terminals).

## Почему «просто починить» нельзя
У приложения нет портируемого способа узнать ширину символа в конкретном
терминале. Есть протоколы (mode 2027 / kitty text-sizing), но они не universally
supported и Textual их не использует. Поэтому терминальные аппы выбирают
стратегию: либо мириться, либо не использовать неоднозначные последовательности.

## Что делаем мы
- **Нормализация ширины** (`core/text_width.py`): снимаем VS15/VS16 (U+FE0E/FE0F),
  ZWJ (U+200D) и прочие zero-width, раскрываем табы; это официальный воркэраунд
  из issue — base-символ без селектора даёт однозначную ширину 1.
- Точка применения — **`BotinokTextualApp._add_static`** (единая вставка в чат) и
  `_rich_escape`, плюс панели (`_update_header/_update_footer`) и обрезка query по
  ширине ячейки.
- **Обрезка по ячейкам, а не по `len()`** (`cell_truncate`) — для таблиц/панелей.
- Альтернатива на стороне терминала (если хочется сохранить цветные эмодзи):
  `grapheme-width-method = legacy` в Ghostty или glibc с фиксом width для VS16.

## Связи
Интерфейс — `entities/textual_ui.md`; встроенный терминал — `entities/shell_screen.md`.
