import re
import json
import subprocess
from typing import Optional, List, Dict


def _run_journalctl(argv: List[str], max_bytes: int = 256_000) -> str:
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        out = (cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")
        data = out.encode("utf-8", errors="ignore")
        if len(data) > max_bytes:
            out = data[:max_bytes].decode("utf-8", errors="ignore") + "\n...[TRUNCATED_BY_MAX_BYTES]"
        return out.strip() if out.strip() else "(no output)"
    except FileNotFoundError:
        return f"Ошибка: journalctl не найден"
    except subprocess.TimeoutExpired:
        return "Ошибка: journalctl timeout"
    except Exception as e:
        return f"Ошибка: {str(e)}"


def _build_base_args(
    unit: Optional[str],
    since: Optional[str],
    until: Optional[str],
    boot: Optional[int],
    priority: Optional[str],
    output: str,
    no_pager: bool,
) -> List[str]:
    argv: List[str] = ["journalctl"]

    if no_pager:
        argv.append("--no-pager")

    if output:
        argv.extend(["-o", output])

    if boot is not None:
        argv.extend(["-b", str(boot)])

    if unit:
        argv.extend(["-u", unit])

    if since:
        argv.extend(["--since", since])

    if until:
        argv.extend(["--until", until])

    if priority:
        argv.extend(["-p", priority])

    return argv


def _filter_lines(text: str, grep: Optional[str], regex: Optional[str], max_lines: int) -> str:
    lines = text.splitlines()

    if grep:
        g = grep.lower()
        lines = [ln for ln in lines if g in ln.lower()]

    if regex:
        try:
            rx = re.compile(regex, re.IGNORECASE)
            lines = [ln for ln in lines if rx.search(ln)]
        except Exception as e:
            return f"Ошибка regex: {str(e)}"

    if max_lines > 0 and len(lines) > max_lines:
        head = lines[:max_lines]
        head.append(f"...[TRUNCATED_BY_MAX_LINES total={len(lines)} shown={max_lines}]")
        lines = head

    return "\n".join(lines) if lines else "(no matches)"


def _stats_levels(text: str) -> Dict[str, int]:
    # Очень грубая эвристика для short-iso: ищем ' info ' / ' warning ' / ' err '
    levels = {"emerg": 0, "alert": 0, "crit": 0, "err": 0, "warning": 0, "notice": 0, "info": 0, "debug": 0, "unknown": 0}
    for ln in text.splitlines():
        low = ln.lower()
        matched = False
        for lvl in ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]:
            if f"[{lvl}]" in low or f" {lvl} " in low:
                levels[lvl] += 1
                matched = True
                break
        if not matched:
            levels["unknown"] += 1
    return levels


def journal_tool(
    action: str,
    unit: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    lines: int = 200,
    grep: Optional[str] = None,
    regex: Optional[str] = None,
    priority: Optional[str] = None,
    boot: Optional[int] = None,
    output: str = "short-iso",
    max_bytes: int = 256_000,
    max_lines: int = 500,
) -> str:
    """Read-only systemd journal analysis tool.

    Actions:
    - tail: last N lines
    - unit_tail: last N lines for a unit
    - since: lines since a time (optionally until)
    - query: like since/tail but with grep/regex filters
    - stats: compute simple level counts over retrieved window
    """

    if lines <= 0:
        lines = 200
    lines = min(lines, 5000)

    if max_bytes <= 0:
        max_bytes = 1

    if max_lines <= 0:
        max_lines = 1

    act = (action or "").strip().lower()

    if act == "tail":
        argv = _build_base_args(unit=None, since=None, until=None, boot=boot, priority=priority, output=output, no_pager=True)
        argv.extend(["-n", str(lines)])
        raw = _run_journalctl(argv, max_bytes=max_bytes)
        return _filter_lines(raw, grep=grep, regex=regex, max_lines=max_lines)

    if act == "unit_tail":
        if not unit:
            return "Ошибка: unit обязателен для action='unit_tail'"
        argv = _build_base_args(unit=unit, since=None, until=None, boot=boot, priority=priority, output=output, no_pager=True)
        argv.extend(["-n", str(lines)])
        raw = _run_journalctl(argv, max_bytes=max_bytes)
        return _filter_lines(raw, grep=grep, regex=regex, max_lines=max_lines)

    if act == "since":
        if not since:
            return "Ошибка: since обязателен для action='since'"
        argv = _build_base_args(unit=unit, since=since, until=until, boot=boot, priority=priority, output=output, no_pager=True)
        argv.extend(["-n", str(lines)])
        raw = _run_journalctl(argv, max_bytes=max_bytes)
        return _filter_lines(raw, grep=grep, regex=regex, max_lines=max_lines)

    if act == "query":
        # query = since (если задан) иначе tail
        if since:
            argv = _build_base_args(unit=unit, since=since, until=until, boot=boot, priority=priority, output=output, no_pager=True)
        else:
            argv = _build_base_args(unit=unit, since=None, until=None, boot=boot, priority=priority, output=output, no_pager=True)
        argv.extend(["-n", str(lines)])
        raw = _run_journalctl(argv, max_bytes=max_bytes)
        return _filter_lines(raw, grep=grep, regex=regex, max_lines=max_lines)

    if act == "stats":
        # берём окно как в query и считаем грубую статистику
        if since:
            argv = _build_base_args(unit=unit, since=since, until=until, boot=boot, priority=priority, output=output, no_pager=True)
        else:
            argv = _build_base_args(unit=unit, since=None, until=None, boot=boot, priority=priority, output=output, no_pager=True)
        argv.extend(["-n", str(lines)])
        raw = _run_journalctl(argv, max_bytes=max_bytes)
        filtered = _filter_lines(raw, grep=grep, regex=regex, max_lines=max_lines)
        if filtered.startswith("Ошибка"):
            return filtered
        levels = _stats_levels(filtered)
        return json.dumps({"action": "stats", "unit": unit, "since": since, "until": until, "lines": lines, "levels": levels}, ensure_ascii=False, indent=2)

    return f"Ошибка: неизвестное действие '{action}'"
