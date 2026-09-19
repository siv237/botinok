#!/usr/bin/env python3
"""
code_editor — единый инструмент редактирования файлов (edit-кит).

Действия (action):
  read     — чтение с пагинацией, нумерацией строк и меткой достоверности
  write    — полная запись содержимого (атомарно)
  replace  — замена одного фрагмента (old_text → new_text)
  apply    — одна или несколько замен за вызов, атомарно (edits=[{old_text,new_text}])
  undo     — откат последней правки из чекпоинта
  help     — справка

Принципы (в русле web / session_memory):
  * ответ — не только результат, но и совет: _meta, _provenance, _confidence,
    _advice, _next_actions;
  * правка прощает дрейф отступов и переводов строк (fuzzy, жёстко ограничен,
    чтобы не подвесить процесс), сообщает «ближайшее совпадение»;
  * запись атомарная (tmp + os.replace), с сохранением кодировки/EOL;
  * устаревший файл отклоняется (серверный стейт-хэш);
  * перед мутацией — чекпоинт с ожидаемым состоянием, доступен undo;
  * крупные результаты уходят в артефакт, в контекст — нужная часть.
"""

import difflib
import hashlib
import json
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

MAX_BYTES_DEFAULT = 20_000_000
READ_MAX_BYTES = 200_000
DIFF_MAX_CHARS = 20_000
FUZZY_THRESHOLD = 0.80
FUZZY_AMBIGUITY_GAP = 0.02
FUZZY_MAX_LINES = 20000
FUZZY_MAX_NEEDLE_LINES = 80
FUZZY_MAX_NEEDLE_CHARS = 4000
FUZZY_MAX_SCAN_CHARS = 3_000_000
FUZZY_MAX_RATIO_CALLS = 1500
FUZZY_MIN_NEEDLE_CHARS = 12
BACKUP_DIRNAME = ".edit_backups"

EDITOR_ACTION_ALIASES = {
    "open": "read", "cat": "read",
    "save": "write",
    "patch": "apply",
    "edit": "replace", "str_replace": "replace",
    "revert": "undo", "restore": "undo",
    "?": "help", "actions": "help",
}
EDITOR_ACTIONS = ("read", "write", "replace", "apply", "undo", "help")

_KNOWN_STATE: Dict[str, str] = {}
_LAST_CHECKPOINT: Dict[str, str] = {}

_CONF = {"exact": "EXACT", "derived": "DERIVED", "heuristic": "HINT"}

_SKIP_REASON = {
    "needle_too_short": "фрагмент слишком короткий для нечёткого поиска",
    "needle_too_large": "фрагмент слишком большой для нечёткого поиска",
    "file_too_large": "файл слишком большой для нечёткого поиска",
}


def normalize_action(action: Any) -> str:
    text = str(action or "").strip().lower()
    return EDITOR_ACTION_ALIASES.get(text, text)


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _safe_path(path: str, root: str) -> str:
    root = os.path.realpath(root)
    rp = os.path.realpath(path)
    if not (rp == root or rp.startswith(root + os.sep)):
        raise ValueError(f"Path outside allowed root is not allowed: {path}")
    return rp


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "да")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _atomic_write(path: str, data: bytes) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp_edit_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_bytes(path: str, max_bytes: int) -> bytes:
    with open(path, "rb") as f:
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"File too large (>{max_bytes} bytes)")
    return data


def _decode_text(data: bytes) -> Tuple[str, str, str, bool]:
    """Возвращает (text, encoding, eol, mixed).

    eol — преобладающий перевод строки ("\\r\\n" | "\\n" | "\\r"),
    mixed — в файле смешаны разные переводы (при записи нормализуются).
    """
    if b"\x00" in data:
        raise ValueError("похоже на бинарный файл (найден NUL-байт) — текстовый редактор не применяется")
    has_bom = data.startswith(b"\xef\xbb\xbf")
    encoding = "utf-8-sig" if has_bom else "utf-8"
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1251")
            encoding = "cp1251"
        except UnicodeDecodeError:
            raise ValueError("не удалось декодировать файл как текст (utf-8/cp1251)")
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    counts = {"\r\n": crlf, "\n": lf, "\r": cr}
    present = [k for k, v in counts.items() if v > 0]
    if not present:
        eol, mixed = "\n", False
    else:
        eol = max(counts, key=counts.get)
        mixed = len(present) > 1
    return text, encoding, eol, mixed


def _canonical(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _encode_text(text: str, encoding: str, eol: str) -> bytes:
    out = _canonical(text)
    if eol == "\r\n":
        out = out.replace("\n", "\r\n")
    elif eol == "\r":
        out = out.replace("\n", "\r")
    return out.encode(encoding, errors="surrogateescape")


def _eol_label(eol: str, mixed: bool) -> str:
    base = {"\r\n": "CRLF", "\r": "CR", "\n": "LF"}.get(eol, "LF")
    return base + "+mixed" if mixed else base


def _normalize(text: str) -> str:
    lines = [ln.rstrip() for ln in _canonical(text).split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _line_spans(text: str) -> Tuple[List[str], List[Tuple[int, int]]]:
    lines = text.split("\n")
    spans: List[Tuple[int, int]] = []
    pos = 0
    for ln in lines:
        spans.append((pos, pos + len(ln)))
        pos += len(ln) + 1
    return lines, spans


def _unified_diff(before: str, after: str, path: str) -> str:
    if before == after:
        return ""
    diff = difflib.unified_diff(
        before.split("\n"), after.split("\n"),
        fromfile="a/" + os.path.basename(path),
        tofile="b/" + os.path.basename(path),
        lineterm="", n=2,
    )
    text = "\n".join(diff)
    if len(text) > DIFF_MAX_CHARS:
        text = text[:DIFF_MAX_CHARS] + "\n...[DIFF TRUNCATED]"
    return text


def _snippet(text: str, start: int, end: int, limit: int = 160) -> str:
    frag = " ".join(text[start:end].split())
    return frag[:limit] + ("…" if len(frag) > limit else "")


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _fuzzy_scan(text: str, needle: str) -> Dict[str, Any]:
    """Нечёткий поиск с нормализацией отступов и переводов строк.

    Сравнение построчное (список строк), а не посимвольное: это устойчиво к
    сдвигу отступов, не страдает от auto-junk на частых символах и дешёво.
    Жёстко ограничен по объёму, чтобы не подвесить процесс.
    """
    needle_norm = _normalize(needle)
    if not needle_norm:
        return {"found": False, "ratio": 0.0}
    if len(needle_norm) < FUZZY_MIN_NEEDLE_CHARS:
        return {"found": False, "ratio": 0.0, "skipped": "needle_too_short"}
    if len(needle_norm) > FUZZY_MAX_NEEDLE_CHARS:
        return {"found": False, "ratio": 0.0, "skipped": "needle_too_large"}
    needle_lines = needle_norm.split("\n")
    width = len(needle_lines)
    if width > FUZZY_MAX_NEEDLE_LINES:
        return {"found": False, "ratio": 0.0, "skipped": "needle_too_large"}

    lines, spans = _line_spans(text)
    if len(lines) > FUZZY_MAX_LINES:
        return {"found": False, "ratio": 0.0, "skipped": "file_too_large"}
    if sum(len(ln) for ln in lines) > FUZZY_MAX_SCAN_CHARS:
        return {"found": False, "ratio": 0.0, "skipped": "file_too_large"}

    needle_cmp = [ln.strip() for ln in needle_lines]
    norm_lines = [ln.strip() for ln in lines]

    best = (0.0, -1)
    runner_up = (0.0, -1)
    best_any = (0.0, -1)
    ratio_calls = 0

    if width == 1:
        matcher = difflib.SequenceMatcher(autojunk=False)
        matcher.set_seq1(needle_cmp[0])
        upper = len(norm_lines)
        for i in range(upper):
            blk = norm_lines[i]
            if not blk:
                continue
            matcher.set_seq2(blk)
            quick = matcher.quick_ratio()
            if quick >= best_any[0]:
                best_any = (quick, i)
            if quick < FUZZY_THRESHOLD or ratio_calls >= FUZZY_MAX_RATIO_CALLS:
                continue
            ratio_calls += 1
            ratio = matcher.ratio()
            if ratio > best[0]:
                runner_up = best
                best = (ratio, i)
            elif ratio > runner_up[0]:
                runner_up = ratio, i
            if (best[0] >= FUZZY_THRESHOLD and runner_up[1] >= 0
                    and (best[0] - runner_up[0]) < FUZZY_AMBIGUITY_GAP):
                break
    else:
        matcher = difflib.SequenceMatcher(autojunk=False)
        matcher.set_seq1(needle_cmp)
        upper = max(0, len(norm_lines) - width + 1)
        for i in range(upper):
            block = norm_lines[i:i + width]
            if not any(block):
                continue
            matcher.set_seq2(block)
            quick = matcher.quick_ratio()
            if quick >= best_any[0]:
                best_any = (quick, i)
            if quick < FUZZY_THRESHOLD or ratio_calls >= FUZZY_MAX_RATIO_CALLS:
                continue
            ratio_calls += 1
            ratio = matcher.ratio()
            if ratio > best[0]:
                runner_up = best
                best = (ratio, i)
            elif ratio > runner_up[0]:
                runner_up = ratio, i
            if (best[0] >= FUZZY_THRESHOLD and runner_up[1] >= 0
                    and (best[0] - runner_up[0]) < FUZZY_AMBIGUITY_GAP):
                break

    if best[1] < 0:
        i = best_any[1]
        if i < 0:
            return {"found": False, "ratio": 0.0}
        if width == 1:
            matcher.set_seq2(norm_lines[i])
        else:
            matcher.set_seq2(norm_lines[i:i + width])
        ratio = matcher.ratio()
        if ratio < 0.3:
            return {"found": False, "ratio": round(ratio, 3)}
        start = spans[i][0]
        end = spans[i + width - 1][1]
        return {"found": False, "ratio": round(ratio, 3), "start": start, "end": end,
                "snippet": _snippet(text, start, end), "line": i + 1}

    ratio, idx = best
    start = spans[idx][0]
    end = spans[idx + width - 1][1]
    return {
        "found": ratio >= FUZZY_THRESHOLD,
        "ratio": round(ratio, 3),
        "start": start,
        "end": end,
        "snippet": _snippet(text, start, end),
        "line": idx + 1,
        "ambiguous": (ratio - runner_up[0]) < FUZZY_AMBIGUITY_GAP and ratio >= FUZZY_THRESHOLD,
        "candidate_line": runner_up[1] + 1 if runner_up[1] >= 0 else None,
    }


def _locate(text: str, needle: str, replace_all: bool) -> Dict[str, Any]:
    if not needle:
        return {"kind": "empty", "found": False}
    exact = text.count(needle)
    if exact == 1:
        start = text.index(needle)
        return {"kind": "exact", "found": True, "start": start, "end": start + len(needle),
                "count": 1, "line": _line_of(text, start)}
    if exact > 1:
        if replace_all:
            return {"kind": "exact_all", "found": True, "count": exact,
                    "line": _line_of(text, text.index(needle))}
        positions = []
        pos = -1
        for _ in range(min(exact, 5)):
            pos = text.index(needle, pos + 1)
            positions.append({"line": _line_of(text, pos), "snippet": _snippet(text, pos, pos + len(needle))})
        return {"kind": "ambiguous_exact", "found": False, "count": exact, "candidates": positions}

    fuzzy = _fuzzy_scan(text, needle)
    if fuzzy.get("found") and not fuzzy.get("ambiguous"):
        return {"kind": "fuzzy", "found": True, "start": fuzzy["start"], "end": fuzzy["end"],
                "ratio": fuzzy["ratio"], "line": fuzzy["line"]}
    if fuzzy.get("found") and fuzzy.get("ambiguous"):
        return {"kind": "ambiguous_fuzzy", "found": False, "ratio": fuzzy["ratio"],
                "line": fuzzy["line"], "candidate_line": fuzzy.get("candidate_line"),
                "snippet": fuzzy.get("snippet")}
    return {"kind": "not_found", "found": False, "ratio": fuzzy.get("ratio", 0.0),
            "line": fuzzy.get("line"), "snippet": fuzzy.get("snippet"),
            "skipped": fuzzy.get("skipped")}


def _apply_one(text: str, old_text: str, new_text: str, replace_all: bool) -> Tuple[Optional[str], Optional[Dict], Optional[Dict]]:
    where = _locate(text, old_text, replace_all)
    if where.get("found"):
        if where["kind"] == "exact_all":
            updated = text.replace(old_text, new_text)
        else:
            updated = text[:where["start"]] + new_text + text[where["end"]:]
        applied = {"old_text": _snippet(old_text, 0, len(old_text), 80),
                   "matched": "exact" if where["kind"].startswith("exact") else "fuzzy",
                   "replace_all": where["kind"] == "exact_all",
                   "count": where.get("count", 1),
                   "line": where.get("line")}
        return updated, applied, None

    kind = where.get("kind")
    if kind == "empty":
        error = {"code": "empty_old_text", "message": "old_text пуст"}
    elif kind == "ambiguous_exact":
        error = {"code": "ambiguous", "count": where.get("count"),
                 "message": f"old_text встречается {where.get('count')} раз — уточни контекст или replace_all=true",
                 "candidates": where.get("candidates", [])}
    elif kind == "ambiguous_fuzzy":
        error = {"code": "ambiguous_fuzzy", "message": "несколько похожих фрагментов — уточни контекст",
                 "line": where.get("line"), "candidate_line": where.get("candidate_line")}
    else:
        skipped = where.get("skipped")
        reason = _SKIP_REASON.get(skipped)
        message = "old_text не найден в файле" + (f" ({reason})" if reason else "")
        error = {"code": "old_text_not_found", "message": message}
        if skipped:
            error["fuzzy_skipped"] = skipped
        if where.get("snippet"):
            error["nearest"] = {"line": where.get("line"), "ratio": where.get("ratio"),
                                "snippet": where["snippet"]}
    return None, None, error


def _checkpoint(root: str, path: str, data: bytes, after_sha: str) -> Optional[str]:
    try:
        bdir = os.path.join(root, BACKUP_DIRNAME)
        os.makedirs(bdir, exist_ok=True)
        key = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
        cp = os.path.join(bdir, f"{key}_{os.path.basename(path) or 'file'}")
        _atomic_write(cp, data)
        meta = json.dumps({"after_sha256": after_sha,
                           "at": datetime.now().isoformat(timespec="seconds")}).encode("utf-8")
        _atomic_write(cp + ".meta", meta)
        _LAST_CHECKPOINT[path] = cp
        return cp
    except Exception:
        return None


def _checkpoint_expected_sha(cp: str) -> Optional[str]:
    try:
        with open(cp + ".meta", "r", encoding="utf-8") as f:
            return json.load(f).get("after_sha256")
    except Exception:
        return None


def _commit(root: str, safe_path: str, action: str, before: bytes, before_sha: Optional[str],
            before_text: str, after_text: str, data: bytes, mixed: bool,
            extra: Dict[str, Any]) -> Dict[str, Any]:
    new_sha = _sha256_bytes(data)
    checkpoint_path = None
    if before and before_sha != new_sha:
        checkpoint_path = _checkpoint(root, safe_path, before, new_sha)
    _atomic_write(safe_path, data)
    _KNOWN_STATE[safe_path] = new_sha
    data_out: Dict[str, Any] = {
        "ok": True, "action": action, "path": safe_path,
        "before_sha256": before_sha, "after_sha256": new_sha,
        "changed": before_sha != new_sha,
        "bytes_before": len(before), "bytes_after": len(data),
        "diff": _unified_diff(before_text, after_text, safe_path),
        "checkpoint": checkpoint_path,
        "eol_normalized": bool(mixed),
    }
    data_out.update(extra)
    return data_out


def _render_read(path: str, body: str, total_lines: int, start_line: int, end_line: int,
                 sha: str, encoding: str, eol_label: str, truncated: bool, cont_offset: int) -> str:
    header = (f"--- {path}\n"
              f"--- lines {start_line}-{end_line} of {total_lines} | "
              f"sha256={sha} | encoding={encoding} | eol={eol_label} ---")
    if truncated:
        body += f"\n...[TRUNCATED_BY_MAX_BYTES — продолжай с offset={cont_offset}]"
    footer = ("────────────────────────────\n"
              "🧭 code_editor · action=read | provenance=exact | _confidence=EXACT\n"
              "💡 Совет: правь через replace/apply — устаревание и отступы инструмент отслеживает сам.\n"
              "➡ Следующие шаги: code_editor action=replace path=\"%s\" old_text=\"…\" new_text=\"…\"" % path)
    return f"{header}\n{body}\n\n{footer}"


def _next_actions(action: str, path: str, data: Dict) -> List[str]:
    p = json.dumps(path, ensure_ascii=False)
    if action == "read":
        return [f'code_editor action=replace path={p} old_text="…" new_text="…"',
                f'code_editor action=apply path={p} edits=[{{"old_text":"…","new_text":"…"}}]',
                f'code_editor action=help']
    if action in ("write", "replace", "apply", "undo"):
        out = [f'code_editor action=read path={p}']
        if data.get("checkpoint"):
            out.append(f'code_editor action=undo path={p}')
        return out
    return ['code_editor action=help']


def _advise(action: str, data: Dict) -> str:
    if action == "read":
        if data.get("truncated"):
            return "Файл прочитан не полностью — продолжай с offset, затем правь replace/apply."
        return "Для правки используй replace (один фрагмент) или apply (несколько за раз, атомарно)."
    if action in ("write", "replace", "apply"):
        if data.get("changed"):
            extra = " Перевод строк был смешан и нормализован." if data.get("eol_normalized") else ""
            return "Готово. Проверь diff; при необходимости откати через undo или продолжи replace/apply." + extra
        return "Изменений нет: содержимое совпало с текущим."
    if action == "undo":
        return "Чекпоинт восстановлен. Перечитай файл, если продолжишь правки."
    return "Действия: read, write, replace, apply, undo, help."


def _result(action: str, path: str, data: Dict, provenance: str, advice: str,
            next_actions: List[str]) -> str:
    data["_meta"] = {
        "path": path,
        "action": action,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    data["_provenance"] = provenance
    data["_confidence"] = _CONF.get(provenance, "DERIVED")
    data["_advice"] = advice
    data["_next_actions"] = next_actions
    return json.dumps(data, ensure_ascii=False, indent=2)


def _error(action: str, path: str, code: str, message: str, advice: str,
           extra: Optional[Dict] = None) -> str:
    data: Dict[str, Any] = {"ok": False, "action": action, "path": path,
                            "error": {"code": code, "message": message}}
    if extra:
        data["error"].update(extra)
    return _result(action, path, data, "heuristic", advice, _next_actions(action, path, data))


def _help_text() -> str:
    return (
        "🧭 code_editor — единый редактор файлов (edit-кит).\n"
        "\n"
        "Действия:\n"
        "  code_editor action=read path=… [offset=0] [limit=400] [line_numbers=true]\n"
        "      — чтение с пагинацией; sha256, encoding и eol в шапке.\n"
        "  code_editor action=write path=… content=\"…\" [create=true]\n"
        "      — полная запись; сохраняет кодировку и перевод строк существующего файла.\n"
        "  code_editor action=replace path=… old_text=\"…\" new_text=\"…\" [replace_all=false]\n"
        "      — одна замена; прощает отступы/EOL, сообщает ближайшее совпадение.\n"
        "  code_editor action=apply path=… edits=[{\"old_text\":\"…\",\"new_text\":\"…\"}, …]\n"
        "      — несколько замен за вызов, атомарно (всё или ничего).\n"
        "  code_editor action=undo path=… [checkpoint=…] [force=true]\n"
        "      — откат последней правки из чекпоинта.\n"
        "  code_editor action=help — эта справка.\n"
        "\n"
        "Особенности:\n"
        "  • diff изменений возвращается в ответе — проверяй, что изменил именно то;\n"
        "  • устаревший файл (изменён вне сессии) отклоняется с подсказкой перечитать;\n"
        "  • перед каждой мутацией создаётся чекпоинт (path в ответе, откат — undo);\n"
        "  • крупные файлы читай пагинированно (offset/limit).\n"
    )


def code_editor(
    action: str = "",
    path: str = "",
    content: Optional[str] = None,
    old_text: Optional[str] = None,
    new_text: Optional[str] = None,
    edits: Optional[List[Dict[str, Any]]] = None,
    replace_all: bool = False,
    create: bool = False,
    expected_sha256: Optional[str] = None,
    max_bytes: int = MAX_BYTES_DEFAULT,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    line_numbers: bool = False,
    checkpoint: Optional[str] = None,
    force: bool = False,
    session_path: Optional[str] = None,
    dangerous_mode: bool = False,
    **kwargs: Any,
) -> str:
    action = normalize_action(action)

    if action not in EDITOR_ACTIONS:
        return _error(action or "?", path, "unknown_action",
                      f"неизвестный action '{action}'",
                      f"Доступные действия: {', '.join(EDITOR_ACTIONS)}.")

    if action == "help":
        return _help_text()

    if not path:
        return _error(action, "", "no_path", "не указан path",
                      "Укажи path (в сессии относительный путь резолвится в session_path/project/).")

    try:
        root = os.path.abspath(session_path) if session_path else _project_root()
        if dangerous_mode:
            safe_path = os.path.realpath(path) if os.path.isabs(path) \
                else os.path.realpath(os.path.join(root, path))
        else:
            safe_path = _safe_path(path, root=root)
    except Exception as e:
        return _error(action, path, "path_denied", str(e),
                      "Запись/чтение вне папки сессии требует dangerous mode.")

    ignored = sorted(kwargs.keys())
    max_bytes = max(1024, _as_int(max_bytes, MAX_BYTES_DEFAULT))
    offset = max(0, _as_int(offset, 0))
    line_numbers = _as_bool(line_numbers)
    replace_all = _as_bool(replace_all)
    create = _as_bool(create)
    force = _as_bool(force)

    try:
        if action == "read":
            return _do_read(safe_path, path, offset, limit, line_numbers, max_bytes, ignored)

        if action == "undo":
            return _do_undo(safe_path, path, root, checkpoint, force, ignored)

        exists = os.path.exists(safe_path)
        if not exists and not create and action != "write":
            return _error(action, path, "not_found",
                          f"файл не существует (create=false): {path}",
                          "Укажи create=true, чтобы создать файл.")
        if exists and not os.path.isfile(safe_path):
            return _error(action, path, "not_file", f"не обычный файл: {path}",
                          "Редактор работает только с обычными файлами.")

        before = b""
        before_sha = None
        encoding, eol, mixed = "utf-8", "\n", False
        before_text = ""
        if exists:
            before = _read_bytes(safe_path, max_bytes=max(max_bytes, MAX_BYTES_DEFAULT))
            before_sha = _sha256_bytes(before)
            raw_text, encoding, eol, mixed = _decode_text(before)
            before_text = _canonical(raw_text)

        if expected_sha256 and before_sha and expected_sha256 != before_sha:
            return _error(action, path, "sha_mismatch",
                          "expected_sha256 не совпадает с текущим файлом",
                          "Файл изменился — перечитай его через read и повтори правку.",
                          {"current_sha256": before_sha, "expected_sha256": expected_sha256})

        known = _KNOWN_STATE.get(safe_path)
        if before_sha and known and known != before_sha and expected_sha256 is None:
            return _error(action, path, "stale",
                          "файл изменился с момента последнего чтения/правки в этой сессии",
                          "Перечитай файл через read и повтори правку (или передай expected_sha256 осознанно).",
                          {"known_sha256": known, "current_sha256": before_sha})

        if action == "write":
            if content is None:
                return _error(action, path, "no_content", "для write нужен content",
                              "Передай content строкой.")
            new_text_full = _canonical(str(content))
            data = _encode_text(new_text_full, encoding, eol)
            if len(data) > max_bytes:
                return _error(action, path, "too_large",
                              f"content слишком большой (>{max_bytes} bytes)",
                              "Разбей запись на части через apply/replace.")
            data_out = _commit(root, safe_path, action, before, before_sha,
                               before_text, new_text_full, data, mixed,
                               {"ignored_args": ignored})
            return _result(action, safe_path, data_out, "exact",
                           _advise(action, data_out), _next_actions(action, safe_path, data_out))

        if action in ("replace", "apply"):
            items: List[Dict[str, Any]] = []
            if action == "apply" and edits:
                if isinstance(edits, str):
                    try:
                        edits = json.loads(edits)
                    except Exception:
                        return _error(action, path, "bad_edits", "edits не парсится как JSON",
                                      'Формат: edits=[{"old_text":"…","new_text":"…"}]')
                if isinstance(edits, dict):
                    edits = [edits]
                for it in edits:
                    if not isinstance(it, dict):
                        return _error(action, path, "bad_edits", "edits должен быть списком объектов",
                                      'Формат: edits=[{"old_text":"…","new_text":"…"}]')
                    items.append({"old_text": it.get("old_text", it.get("old")),
                                  "new_text": it.get("new_text", it.get("new")),
                                  "replace_all": _as_bool(it.get("replace_all"), replace_all)})
            else:
                items.append({"old_text": old_text, "new_text": new_text, "replace_all": replace_all})

            if not items:
                return _error(action, path, "no_edits", "нет правок для применения",
                              "Для replace нужны old_text и new_text; для apply — edits=[…].")
            for it in items:
                if it["old_text"] is None:
                    return _error(action, path, "no_old_text", "не указан old_text",
                                  "Передай old_text (и new_text).")
                it["old_text"] = str(it["old_text"])
                if it["new_text"] is None:
                    it["new_text"] = ""
                it["new_text"] = str(it["new_text"])

            working = before_text
            applied: List[Dict[str, Any]] = []
            for it in items:
                updated, info, err = _apply_one(working, it["old_text"], it["new_text"], it["replace_all"])
                if err:
                    extra = {"edit_index": len(applied), "applied_before_error": applied}
                    hint = ("Ни одна правка не применена (атомарно). " +
                            ("Ближайшее совпадение: строка %s." % err.get("nearest", {}).get("line")
                             if isinstance(err.get("nearest"), dict) else
                             "Перечитай файл и уточни old_text."))
                    merged = dict(err)
                    merged.update(extra)
                    return _error(action, safe_path, err.get("code", "edit_failed"),
                                  err.get("message", "не удалось применить правку"), hint, merged)
                applied.append(info)
                working = updated

            data = _encode_text(working, encoding, eol)
            if len(data) > max_bytes:
                return _error(action, safe_path, "too_large",
                              f"результат слишком большой (>{max_bytes} bytes)",
                              "Разбей правку на части.")
            data_out = _commit(root, safe_path, action, before, before_sha,
                               before_text, working, data, mixed,
                               {"applied": applied, "ignored_args": ignored})
            return _result(action, safe_path, data_out, "exact",
                           _advise(action, data_out), _next_actions(action, safe_path, data_out))

    except Exception as e:
        return _error(action, path, "exception", str(e),
                      "Проверь путь и аргументы; при необходимости перечитай файл.")

    return _error(action, path, "unhandled", "не удалось выполнить действие",
                  "Используй action=help.")


def _do_read(safe_path: str, path: str, offset: int, limit: Any,
             line_numbers: bool, max_bytes: int, ignored: List[str]) -> str:
    if not os.path.isfile(safe_path):
        return _error("read", path, "not_found", f"файл не найден: {path}",
                      "Проверь путь или список файлов через file_system action=list.")
    try:
        raw = _read_bytes(safe_path, max_bytes=max(max_bytes, MAX_BYTES_DEFAULT))
    except ValueError as e:
        return _error("read", path, "too_large", str(e),
                      "Файл больше лимита — читай его через file_system action=read с пагинацией.")
    sha = _sha256_bytes(raw)
    _KNOWN_STATE[safe_path] = sha
    try:
        text, encoding, eol, mixed = _decode_text(raw)
    except ValueError as e:
        return _error("read", path, "binary", str(e),
                      "Для бинарных файлов используй file_system action=inspect.",
                      {"sha256": sha})

    canonical = _canonical(text)
    lines = canonical.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    total = len(lines)
    label = _eol_label(eol, mixed)
    cap = min(max_bytes, READ_MAX_BYTES)

    if total == 0 or offset >= total:
        return _render_read(safe_path, "(конец файла)", total, total, total, sha,
                            encoding, label, False, offset)

    lim = _as_int(limit, 0)
    if lim <= 0:
        lim = total
    start = offset
    end = min(start + lim, total)
    chunk = "\n".join(lines[start:end])
    data = chunk.encode("utf-8", errors="replace")
    truncated = False
    cont_offset = end
    if len(data) > cap:
        chunk = data[:cap].decode("utf-8", errors="ignore")
        shown_lines = chunk.count("\n") + 1
        cont_offset = start + shown_lines
        truncated = True
    if line_numbers:
        chunk = "\n".join(f"{i:>6}\t{ln}" for i, ln in enumerate(chunk.split("\n"), start=start + 1))
    result = _render_read(safe_path, chunk, total, start + 1, end, sha, encoding,
                          label, truncated, cont_offset)
    if ignored:
        result += f"\n(проигнорированы неизвестные аргументы: {', '.join(ignored)})"
    return result


def _do_undo(safe_path: str, path: str, root: str, checkpoint: Optional[str],
             force: bool, ignored: List[str]) -> str:
    bdir = os.path.realpath(os.path.join(root, BACKUP_DIRNAME))
    cp = checkpoint or _LAST_CHECKPOINT.get(safe_path)
    if cp:
        cpr = os.path.realpath(cp)
        if not (cpr == bdir or cpr.startswith(bdir + os.sep)):
            return _error("undo", path, "bad_checkpoint",
                          "checkpoint вне каталога чекпоинтов сессии",
                          "Чекпоинт можно взять только из ответа прошлой правки.",
                          {"checkpoint_dir": bdir})
    if not cp:
        key = hashlib.sha256(safe_path.encode("utf-8")).hexdigest()[:12]
        candidate = os.path.join(bdir, f"{key}_{os.path.basename(safe_path) or 'file'}")
        cp = candidate if os.path.isfile(candidate) else None
    if not cp or not os.path.isfile(cp):
        return _error("undo", path, "no_checkpoint", "чекпоинт для отката не найден",
                      "Чекпоинт создаётся перед каждой правкой; откатывать нечего.",
                      {"checkpoint_dir": bdir})

    exists = os.path.isfile(safe_path)
    before = _read_bytes(safe_path, max_bytes=MAX_BYTES_DEFAULT) if exists else b""
    cur_sha = _sha256_bytes(before) if before else None
    expected = _checkpoint_expected_sha(cp)
    if not force and expected and cur_sha and cur_sha != expected:
        return _error("undo", path, "stale",
                      "файл изменился после правки, которую откатываем",
                      "Перечитай файл; если откат всё же нужен — повтори undo с force=true.",
                      {"current_sha256": cur_sha, "expected_sha256": expected})

    backup = _read_bytes(cp, max_bytes=MAX_BYTES_DEFAULT)
    _atomic_write(safe_path, backup)
    after_sha = _sha256_bytes(backup)
    _KNOWN_STATE[safe_path] = after_sha
    data_out = {
        "ok": True, "action": "undo", "path": safe_path,
        "before_sha256": cur_sha, "after_sha256": after_sha,
        "changed": before != backup,
        "bytes_before": len(before), "bytes_after": len(backup),
        "restored_from": cp,
        "ignored_args": ignored,
    }
    return _result("undo", safe_path, data_out, "exact", _advise("undo", data_out),
                   _next_actions("undo", safe_path, data_out))
