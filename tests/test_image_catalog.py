#!/usr/bin/env python3
"""Каталог изображений: хранение в проекте и НЕПОВТОРЯЮЩИЕСЯ идентификаторы.

Запуск: venv/bin/python -u tests/test_image_catalog.py
"""

import functools
import http.server
import os
import re
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import image_catalog  # noqa: E402
from PIL import Image  # noqa: E402

ID_RE = re.compile(r"^img_\d{6}_[0-9a-f]{6}$")
FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def png(path: str, color=(10, 20, 30), size=(40, 30)) -> str:
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def serve(directory: str):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def main() -> int:
    print("=" * 70)
    print("Image catalog smoke-test")
    print("=" * 70)

    session = tempfile.mkdtemp(prefix="botinok_cat_sess_")
    os.makedirs(os.path.join(session, "project"), exist_ok=True)
    src_dir = tempfile.mkdtemp(prefix="botinok_cat_src_")
    a = png(os.path.join(src_dir, "a.png"), (10, 20, 30))
    b = png(os.path.join(src_dir, "b.png"), (200, 100, 50), (60, 20))

    # --- добавление файла ---
    e1 = image_catalog.add_image(a, session_path=session, alt="схема")
    check("id_format", bool(ID_RE.match(e1["id"])), f"id={e1['id']}")
    check("file_in_project", e1["path"].startswith(os.path.join(session, "project")),
          e1["path"])
    check("file_exists", os.path.isfile(e1["path"]))
    check("meta", e1["width"] == 40 and e1["height"] == 30 and e1["mime"] == "image/png",
          f"{e1['width']}x{e1['height']} {e1['mime']}")
    check("catalog_written", os.path.isfile(image_catalog.catalog_path(session)))

    # --- повтор того же файла → тот же id (не повтор, а переиспользование) ---
    e1b = image_catalog.add_image(a, session_path=session, alt="схема")
    check("reuse_same_id", e1b["id"] == e1["id"] and e1b.get("reused") is True)

    # --- другой файл → новый уникальный id ---
    e2 = image_catalog.add_image(b, session_path=session)
    check("distinct_ids", e2["id"] != e1["id"], f"{e1['id']} vs {e2['id']}")

    # --- resolve/get ---
    check("resolve_path", image_catalog.resolve_path(e1["id"], session) == e1["path"])
    check("get_unknown_none", image_catalog.get_entry("img_999999_ffffff", session) is None)

    # --- удаление: id уходит в retired и НЕ выдаётся повторно ---
    old_id = e2["id"]
    check("delete_ok", image_catalog.delete_entry(old_id, session, remove_file=True))
    check("deleted_file_gone", not os.path.isfile(e2["path"]))
    e2b = image_catalog.add_image(b, session_path=session)
    check("no_id_reuse_after_delete", e2b["id"] != old_id,
          f"reused retired id {old_id}")

    # --- много добавлений: все id уникальны ---
    ids = {e1["id"], e2b["id"]}
    for i in range(50):
        p = png(os.path.join(src_dir, f"m{i}.png"), (i, i, i))
        ids.add(image_catalog.add_image(p, session_path=session)["id"])
    check("all_unique", len(ids) == 52, f"unique={len(ids)}")

    # --- URL ---
    httpd, base = serve(src_dir)
    try:
        eu = image_catalog.add_image(f"{base}/a.png", session_path=session, alt="url")
        check("url_added", bool(ID_RE.match(eu["id"])) and os.path.isfile(eu["path"]))
        check("url_reuses_same_content", eu["id"] == e1["id"] and eu.get("reused") is True,
              f"{eu['id']} vs {e1['id']}")
    except Exception as ex:
        check("url_added", False, str(ex))

    # Битую ссылку инструмент должен вернуть ошибкой, а не падением.
    try:
        image_catalog.add_image(f"{base}/missing.png", session_path=session)
        check("missing_url_raises", False, "ожидалась ошибка")
    except Exception:
        check("missing_url_raises", True)

    # --- классификация сетевых/серверных ошибок (без доменной конкретики) ---
    import httpx as _httpx

    def _status(code):
        req = _httpx.Request("GET", "http://h/x")
        return _httpx.HTTPStatusError("e", request=req,
                                      response=_httpx.Response(code, request=req))

    c403 = image_catalog._classify_download_error(_status(403))
    check("classify_403", "403" in c403 and "web action=images" in c403, c403)
    c404 = image_catalog._classify_download_error(_status(404))
    check("classify_404", "404" in c404, c404)
    cto = image_catalog._classify_download_error(_httpx.ReadTimeout("t"))
    check("classify_timeout", "Таймаут" in cto and "proxy" in cto, cto)

    # --- негативная память хостов: повтор к упавшему хосту отбивается коротко ---
    fails = image_catalog.load_catalog(session).get("host_failures", {}) or {}
    check("host_failure_recorded", "127.0.0.1" in fails, str(fails))
    try:
        image_catalog.add_image(f"{base}/missing.png", session_path=session)
        check("host_failure_shortcircuit", False, "ожидался отказ из памяти")
    except Exception as e:
        check("host_failure_shortcircuit", "уже не отвечал" in str(e), str(e)[:200])

    # TTL=0 отключает память → тот же хост снова доступен, память очищается
    os.environ["BOTINOK_IMAGE_HOST_TTL"] = "0"
    try:
        again = image_catalog.add_image(f"{base}/a.png", session_path=session)
        check("host_failure_recovery", bool(ID_RE.match(again["id"])), str(again)[:120])
        check("host_failure_cleared_on_success",
              "127.0.0.1" not in (image_catalog.load_catalog(session).get("host_failures", {}) or {}))
    except Exception as ex:
        check("host_failure_recovery", False, str(ex))
    finally:
        os.environ.pop("BOTINOK_IMAGE_HOST_TTL", None)

    # --- фолбэк без session_path ---
    ef = image_catalog.add_image(a)
    check("fallback_dir", ef["path"].startswith(os.path.expanduser("~/.botinok")))

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ IMAGE CATALOG SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    main()
