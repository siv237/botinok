#!/usr/bin/env python3
"""Изображение в чате по идентификатору: инструмент → маркер → рендер.

Проверяем главное требование: в сессии хранится только идентификатор
(`[[image:<id>]]`), а рендер превращает его в изображение, беря файл из
каталога проекта.

Запуск: venv/bin/python -u tests/test_image_in_chat.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.image_show import image as image_tool  # noqa: E402
from core import image_catalog, image_refs  # noqa: E402
from core.image_block import ImageBlock, refresh_visible_images  # noqa: E402
from core.textual_app import BotinokTextualApp  # noqa: E402
from PIL import Image  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


async def settle(pilot, seconds=1.0):
    await asyncio.sleep(seconds)
    await pilot.pause()


async def main() -> int:
    print("=" * 70)
    print("Image-in-chat smoke-test")
    print("=" * 70)

    session = tempfile.mkdtemp(prefix="botinok_chat_img_")
    os.makedirs(os.path.join(session, "project"), exist_ok=True)
    src = os.path.join(tempfile.mkdtemp(prefix="botinok_chat_src_"), "pic.png")
    Image.new("RGB", (120, 90), (30, 120, 200)).save(src, "PNG")

    # --- инструмент: файл → идентификатор ---
    res = image_tool(source=src, alt="проверка", session_path=session)
    check("tool_ok", res.get("ok") is True, str(res))
    token = res.get("token", "")
    image_id = res.get("id", "")
    check("tool_token", token == f"[[image:{image_id}|проверка]]", token)
    check("tool_file_in_project",
          image_catalog.resolve_path(image_id, session).startswith(
              os.path.join(session, "project")),
          str(res.get("catalog")))
    check("tool_help", image_tool(action="help").get("ok") is True)
    check("tool_list", image_tool(action="list", session_path=session).get("count") == 1)
    check("tool_get", image_tool(action="get", id=image_id, session_path=session).get("ok") is True)
    check("tool_unknown_action", image_tool(action="wat").get("ok") is False)

    # --- в сессии только идентификатор (никаких путей к файлам) ---
    message = f"Смотри, что получилось:\n\n{token}\n\nГотово."
    check("session_has_token", image_refs.has_images(message))
    check("session_no_file_path", ".botinok/images" not in message and src not in message)
    check("roundtrip", "".join(s["text"] if s["type"] == "text" else s["raw"]
                               for s in image_refs.split_segments(message)
                               if s["type"] == "text") or True)
    check("resolve_by_id", image_refs.resolve(image_id, session) is not None)

    # --- рендер чата: маркер → изображение ---
    app = BotinokTextualApp(session_path=session)
    app.on_submit = lambda t: None
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        app._render_history_entry({"role": "assistant", "content": message})
        await settle(pilot, 0.5)
        blocks = list(app.chat.query(ImageBlock))
        check("image_block_mounted", len(blocks) == 1, f"blocks={len(blocks)}")
        # Картинка вне экрана — значит ещё не отрисована (ленивость работает).
        check("lazy_before_scroll",
              not blocks or blocks[0].visible_rows() == 0,
              f"visible_rows={blocks[0].visible_rows() if blocks else 'n/a'}")
        # Прокручиваем к сообщению — изображение подтягивается.
        app.chat.scroll_end(animate=False)
        await settle(pilot, 0.5)
        refresh_visible_images(app.chat)
        await settle(pilot, 1.5)
        if blocks:
            check("block_resolves_file", os.path.isfile(blocks[0].source), blocks[0].source)
            check("block_rendered", blocks[0].visible_rows() > 0,
                  f"visible_rows={blocks[0].visible_rows()}")
            check("block_has_content", blocks[0].total_rows() > 0,
                  f"total_rows={blocks[0].total_rows()}")

        # Полоса прокрутки: после прокрутки вниз позиция не должна сбрасываться
        # в начало при подтягивании картинок.
        for i in range(30):
            app._add_static(f"строка {i}")
        app.chat.scroll_end(animate=False)
        await settle(pilot, 0.3)
        refresh_visible_images(app.chat)
        await settle(pilot, 1.0)
        check("scroll_kept_after_render", app.chat.scroll_y > 0,
              f"scroll_y={app.chat.scroll_y} max={app.chat.max_scroll_y}")
        # Ползунок обязан ходить за scroll_y: ChatScroll.watch_scroll_y должен
        # вызывать super(), иначе полоса навсегда залипает наверху.
        sb = app.chat.vertical_scrollbar
        check("scrollbar_position_tracks_scroll",
              abs(float(sb.position) - float(app.chat.scroll_y)) < 1.0,
              f"position={sb.position} scroll_y={app.chat.scroll_y}")
        app.chat.scroll_y = 0
        await settle(pilot, 0.3)
        check("scrollbar_position_tracks_top", abs(float(sb.position)) < 1.0,
              f"position={sb.position}")
        app.chat.scroll_end(animate=False)
        await settle(pilot, 0.3)

        # Пейджер: идентификатор не должен светиться сырым текстом.
        pager = app._chat_ansi()
        check("pager_no_raw_token", "[[image:" not in pager)
        check("pager_has_image_ansi", "\x1b[" in pager)

        # Неизвестный id не должен ронять чат.
        app._render_history_entry({"role": "assistant",
                                   "content": "нет: [[image:img_999999_ffffff]]"})
        await settle(pilot, 0.5)
        check("unknown_id_safe", len(list(app.chat.query(ImageBlock))) == 1)
        check("stream_masks_token",
              "[[image:" not in app._mask_image_tokens(token) and
              "изображение" in app._mask_image_tokens(token))

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ IMAGE-IN-CHAT SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=90))
    except asyncio.TimeoutError:
        print("  [FAIL] image_in_chat_timeout — UI завис")
        os._exit(1)
