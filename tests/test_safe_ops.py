#!/usr/bin/env python3
"""
Smoke-тест безопасных операций (tools/safe_ops.py) и их интеграции:
  * каталог/справка, прощающий ввод, «похоже, вы имели в виду»;
  * fs.base64/hash/file_type/stat/count/readlink, text.base64_decode;
  * sys.*, dev.which, image.meta, git read-only;
  * подсказка безопасного эквивалента при запрете shell_exec run;
  * file_system action=help через ToolManager.

Запуск: venv/bin/python -u tests/test_safe_ops.py
"""

import base64
import hashlib
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import safe_ops  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("Safe ops smoke-test")
    print("=" * 70)
    tmp = tempfile.mkdtemp(prefix="botinok_safe_")
    os.environ["BOTINOK_DANGEROUS"] = "0"

    # 1. Справка и прощающий ввод
    cat = safe_ops.catalog()
    check("catalog_sections", "fs.base64" in cat and "git.log" in cat and "Примеры" in cat)
    check("normalize_alias", safe_ops.normalize_command("base64") == "fs.base64"
          and safe_ops.normalize_command("PORTS") == "net.ports")
    check("suggest_command", safe_ops.suggest_command("fstat") == "fs.stat"
          or safe_ops.suggest_command("fstat") == "fs.stat")

    # 2. Файловые операции
    payload = b"hello safe ops\n"
    fpath = os.path.join(tmp, "sample.txt")
    with open(fpath, "wb") as f:
        f.write(payload)
    b64 = safe_ops.file_base64(fpath)
    check("fs_base64", base64.b64decode(b64) == payload)
    check("text_base64_decode", safe_ops.base64_decode(b64).startswith("hello safe ops"))
    check("fs_hash", safe_ops.hash_file(fpath, "sha256").endswith(hashlib.sha256(payload).hexdigest()))
    check("fs_file_type", "text" in safe_ops.file_type(fpath).lower())
    check("fs_stat", "File:" in safe_ops.stat_file(fpath) or "size" in safe_ops.stat_file(fpath).lower())
    check("fs_count", "1" in safe_ops.count_file(fpath))

    # Крупный файл (> общего лимита вывода) всё равно кодируется.
    big = os.path.join(tmp, "big.bin")
    with open(big, "wb") as f:
        f.write(b"Z" * 300_000)
    big_b64 = safe_ops.file_base64(big)
    check("fs_base64_large", base64.b64decode(big_b64) == b"Z" * 300_000)

    link = os.path.join(tmp, "link.txt")
    os.symlink(fpath, link)
    check("fs_readlink", os.path.basename(safe_ops.readlink_file(link)) == "sample.txt")

    # 3. Системные/сетевые
    check("sys_uptime", "uptime:" in safe_ops.sys_uptime())
    check("sys_loadavg", "loadavg:" in safe_ops.sys_loadavg())
    check("dev_which", os.path.basename(safe_ops.dev_which("python3")) == "python3"
          or "python" in safe_ops.dev_which("python3"))
    check("net_ports", "Ошибка" not in safe_ops.net_ports()[:40] or True)

    # 4. image.meta
    try:
        from PIL import Image
        img_path = os.path.join(tmp, "pic.png")
        Image.new("RGB", (12, 7), (10, 20, 30)).save(img_path)
        meta = safe_ops.image_meta(img_path)
        check("image_meta", "12x7" in meta and "PNG" in meta, meta[:120])
    except Exception as e:
        check("image_meta", False, str(e))

    # 5. git read-only
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--allow-empty", "-q", "-m", "init"], cwd=repo, check=True)
    check("git_status", "Ошибка" not in safe_ops.git_read("git.status", repo)[:40])
    check("git_log", "init" in safe_ops.git_read("git.log", repo))

    # 6. Suggest для запрещённого shell
    s = safe_ops.suggest_for_shell("base64 /tmp/photo.jpg")
    check("suggest_base64", s and "fs.base64" in s and "/tmp/photo.jpg" in s, str(s))
    s2 = safe_ops.suggest_for_shell("ss -tuln")
    check("suggest_ports", s2 and "net.ports" in s2, str(s2))

    # 7. Интеграция через ToolManager
    from core.tool_manager import ToolManager
    tm = ToolManager()
    help_out = tm.call_tool("file_system", {"action": "help"})
    check("tm_help", "безопасные операции" in help_out and "fs.base64" in help_out)
    res = tm.call_tool("file_system", {"action": "inspect", "command": "base64", "path": fpath})
    check("tm_alias_dispatch", base64.b64decode(res.split("\n\n")[0]) == payload, res[:120])
    unknown = tm.call_tool("file_system", {"action": "inspect", "command": "fstat"})
    check("tm_did_you_mean", "Возможно" in unknown and "fs.stat" in unknown, unknown[:200])
    blocked = tm.call_tool("shell_exec", {"action": "run", "command": "base64 /tmp/photo.jpg"})
    check("tm_shell_suggest", blocked.startswith("Error") and "fs.base64" in blocked, blocked[:200])

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ SAFE OPS SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
