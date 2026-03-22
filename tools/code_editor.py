import os
import json
import hashlib
from typing import Optional


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _safe_path(path: str) -> str:
    root = _project_root()
    rp = os.path.realpath(path)
    if not (rp == root or rp.startswith(root + os.sep)):
        raise ValueError(f"Path outside project root is not allowed: {path}")
    return rp


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _read_bytes(path: str, max_bytes: int) -> bytes:
    with open(path, "rb") as f:
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"File too large (>{max_bytes} bytes)")
    return data


def code_editor(
    action: str,
    path: str,
    content: Optional[str] = None,
    old_text: Optional[str] = None,
    new_text: Optional[str] = None,
    create: bool = False,
    expected_sha256: Optional[str] = None,
    max_bytes: int = 2_000_000,
) -> str:
    if action not in ("read", "write", "replace", "apply"):
        return f"Ошибка: неизвестный action '{action}'"

    try:
        safe_path = _safe_path(path)

        if action == "read":
            if not os.path.isfile(safe_path):
                return f"Файл не найден: {path}"
            data = _read_bytes(safe_path, max_bytes=max_bytes)
            try:
                txt = data.decode("utf-8")
            except Exception:
                txt = data.decode("utf-8", errors="ignore")
            return txt

        exists = os.path.exists(safe_path)
        if not exists and not create:
            return f"Ошибка: файл не существует (create=false): {path}"

        before = b""
        before_sha = None
        if exists and os.path.isfile(safe_path):
            before = _read_bytes(safe_path, max_bytes=max_bytes)
            before_sha = _sha256_bytes(before)

        if expected_sha256 and before_sha and expected_sha256 != before_sha:
            return (
                "Ошибка: expected_sha256 не совпадает с текущим sha256 файла. "
                f"current={before_sha}, expected={expected_sha256}"
            )

        if action == "write":
            if content is None:
                return "Ошибка: для write нужен content"
            data = content.encode("utf-8")
            if len(data) > max_bytes:
                return f"Ошибка: content слишком большой (>{max_bytes} bytes)"
            os.makedirs(os.path.dirname(safe_path) or ".", exist_ok=True)
            with open(safe_path, "wb") as f:
                f.write(data)

        elif action in ("replace", "apply"):
            if old_text is None or new_text is None:
                return "Ошибка: для replace/apply нужны old_text и new_text"
            base_text = before.decode("utf-8", errors="ignore")
            occurrences = base_text.count(old_text)
            if occurrences == 0:
                return "Ошибка: old_text не найден в файле"
            if occurrences > 1:
                return f"Ошибка: old_text найден более одного раза ({occurrences})"
            updated = base_text.replace(old_text, new_text)
            data = updated.encode("utf-8")
            if len(data) > max_bytes:
                return f"Ошибка: результат слишком большой (>{max_bytes} bytes)"
            os.makedirs(os.path.dirname(safe_path) or ".", exist_ok=True)
            with open(safe_path, "wb") as f:
                f.write(data)

        after = b""
        after_sha = None
        if os.path.isfile(safe_path):
            after = _read_bytes(safe_path, max_bytes=max_bytes)
            after_sha = _sha256_bytes(after)

        result = {
            "action": action,
            "path": os.path.relpath(safe_path, _project_root()),
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "changed": before_sha != after_sha,
            "bytes_before": len(before),
            "bytes_after": len(after),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"Ошибка code_editor: {str(e)}"
