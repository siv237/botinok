"""
Интеграция Textual App с стримингом Ollama.

Полная замена Rich Live на Textual App с:
- Tool-calls loop
- VRAM background prep
- Context overflow handling
- Proper UI callbacks (add_tool_activity, append_assistant_chunk, etc.)
- Repetition detection and recovery
- auto_continue_final for missing final response
- Logging (log_chunk, log_tool_call, log_step, file headers/footers)
- Vision tool handling
- HTTP retry logic
"""

import os
import queue
import threading
import time
import json
import re
import uuid
import requests
from typing import Optional, List, Dict, Callable

from core.session_manager import SessionManager
from core.tool_manager import (
    ToolManager,
    allowed_in_session,
    editor_action_of,
    DANGEROUS_FILESYSTEM_ACTIONS as DANGEROUS_FS_ACTIONS,
    DANGEROUS_EDITOR_ACTIONS,
    DANGEROUS_SHELL_ACTIONS,
)
from core.path_utils import resolve_session_path
from core.openai_compat import (is_openai_backend, chat_stream_request, chat_once,
                                apply_native_think, load_cache_entry)
from core.api_key_gate import is_auth_error, key_entry_url, save_api_key
from core.textual_app import BotinokTextualApp
from core import themes as botinok_themes
from core.terminal_keys import install as install_terminal_keys
from core import token_calibrator
from core import net_meter

MODELS_NO_TOOLS = set()

TOOL_OUTPUT_MAX_CHARS = 100000
STREAM_TOOL_TEXT_MAX_CHARS = 12000  # не используется, оставлено для совместимости
HARD_CTX_PCT = 0.90
# Осознанная компакция (запрос модели): подсказка context_cost в tool-результате
# при цене блока ≥5% num_ctx; не сжимать блоки дешевле 2% (трясня ради крох);
# максимум блоков в одном запросе компакции.
COMPACT_HINT_PCT = 0.05
MIN_COMPACT_PCT = 0.02
MAX_COMPACT_BLOCKS = 12
# Дедуп identical-вызовов внутри одного хода (только детерминированные
# читалки: повтор такого же вызова — ошибка фокуса, а не осмысленный рефреш).
DEDUP_TOOLS = ("file_system", "journal")
# Напоминалка о чекпоинтах sign_step: чем больше сожжено контекста, тем важнее
# отметить прогресс (сброс сотрёт непрописанное). Срабатывает при заполнении
# контекста ≥40% и отсутствии подписи в ходе — один раз за ход.
SIGN_CHECKPOINT_REMINDER_PCT = 0.40
MAX_TOOL_ROUNDS_PER_TURN = 80
MAX_AUTO_RECOVERIES_PER_TURN = 2
# Сколько раз подряд молча переспрашивать модель, если она вернула полностью
# пустое завершение (нет content, thinking и tool_calls). Модели глючат и рвутся
# — это штатная ситуация, из которой нужно выходить, а не молча гасить сессию.
MAX_EMPTY_RETRIES_PER_TURN = 3
MAX_PROOFREAD_ROUNDS = 3
MISSING_FINAL_AUTO_CONTINUE_MAX = 2
REPEAT_LINE_WINDOW = 40
REPEAT_LINE_MIN_OCCURRENCES = 6


_TOOL_STREAM_TAG_RE = re.compile(
    r"(?:<\|[^\n\r]*?\|>|</?[^>\n\r]+?>)",
    re.IGNORECASE,
)


def _has_audio_message(messages) -> bool:
    """Есть ли в истории аудио-сообщение (media, которое надо слать как input_audio).

    Аудио в Ollama доставляется только через OpenAI/pv1 (input_audio), поэтому ход
    с аудио перенаправляется на /v1 даже при backend=ollama."""
    return any(
        isinstance(m, dict) and m.get("media_kind") == "audio" and m.get("audios")
        for m in messages
    )


def _tool_stream_has_payload(text: str) -> bool:
    if not text:
        return False
    s = str(text)
    s = _TOOL_STREAM_TAG_RE.sub("", s)
    s = s.replace("{", "").replace("}", "").replace("[", "").replace("]", "")
    s = s.replace("\"", "").replace("'", "").replace(":", "").replace(",", "")
    s = "".join(ch for ch in s if not ch.isspace())
    return any(ch.isalnum() for ch in s)


# Калибровка оценщика токенов (этап 4): len//4 — грубая прикидка; после каждого
# ответа сравниваем её с фактическим prompt_eval_count и ведём EMA-поправку k
# per-model. HARD_CTX_PCT и бюджет тримма начинают означать реальные токены.
_TOKEN_K_EMA_ALPHA = 0.3
_token_k_state = {"by_model": {}, "current": 1.0}

# Текущий деплой для калибратора токенов (ставится на каждом ходе). Плотность
# token_calibrator — основной оценщик, когда по деплою накоплены замеры;
# EMA-коэффициент len//4 остаётся запасным путём (например, после resume).
_calib_deploy = ""


def _set_calib_deploy(model: str, server: str) -> None:
    global _calib_deploy
    try:
        _calib_deploy = token_calibrator.deploy_fingerprint(model, server)
    except Exception:
        _calib_deploy = ""


def _prompt_density():
    """Откалиброванная плотность промпта (токенов на символ) или None."""
    try:
        if _calib_deploy:
            dens, status = token_calibrator.density(_calib_deploy, "prompt", "*")
            if status == "calibrated":
                return dens
    except Exception:
        pass
    return None

# Накопительный учёт «умных вытеснений» (для панели): сколько токенов контекста
# сжато сегментным триммом и big-bang-ресетом за процесс.
_compression_stats = {"tokens": 0, "trims": 0, "resets": 0, "manual": 0, "last_reason": ""}


def get_compression_stats() -> dict:
    return dict(_compression_stats)


# Разовая метка на весь сеанс: скилл llm-wiki активирован. В messages нота
# переживает тримм, но НЕ big-bang-ресет (messages.clear()) — для этого есть
# SKILLS_ACTIVE-памятка, восстанавливаемая из enabled_skills.json каждый раунд.
# В context.json нота пишется ровно один раз на сессию (_wiki_note_persisted).
WIKI_MODE_NOTE = (
    "WIKI_MODE: в этой сессии задействован скилл llm-wiki (паттерн LLM Wiki). "
    "Работай по схеме вики проекта: сначала wiki/index.md → страницы → ответ; "
    "новый источник — ingest (затронутые страницы + index.md + запись в log.md); "
    "вопрос — query со ссылками на страницы; ценный ответ оформляй новой страницей; "
    "raw-источники неизменяемы."
)


def _wiki_mode_activation(tool_args, res_str: str) -> bool:
    """Активация скилла llm-wiki: skills get/run по нему (не повторный list)."""
    try:
        args = tool_args if isinstance(tool_args, dict) else json.loads(str(tool_args or "{}"))
    except Exception:
        args = {}
    if not isinstance(args, dict):
        args = {}
    name = str(args.get("name", "")).lower().replace("_", "-")
    res = str(res_str or "")
    if "llm-wiki" not in name and not ("llm-wiki" in res and "папка скилла" in res):
        return False
    action = str(args.get("action", "")).lower()
    return action in ("get", "run") or "папка скилла" in res


_SKILLS_STATE_FILE = "enabled_skills.json"
SKILLS_ACTIVE_PREFIX = "SKILLS_ACTIVE:"
# Сессии, по которым уже выполнен разовый бэкфилл состояния (tools.log/context.json).
_skills_state_scanned = set()
# Сессии, где WIKI_MODE_NOTE уже лежит в context.json — повторная запись не нужна.
_wiki_note_persisted = set()


def _skill_activation_name(tool_args, res_str: str) -> str:
    """Имя подключённого скилла по вызову и результату; '' — не активация."""
    try:
        args = tool_args if isinstance(tool_args, dict) else json.loads(str(tool_args or "{}"))
    except Exception:
        return ""
    if not isinstance(args, dict):
        return ""
    action = str(args.get("action", "")).lower()
    name = str(args.get("name", "")).strip().lower().replace("_", "-")
    res = str(res_str or "")
    if action not in ("get", "run") or not name:
        return ""
    if res.lower().startswith(("error", "не найден", "unknown")) or "не найден" in res[:80].lower():
        return ""
    return name


def _record_skill_name(session_path: str, name: str, stamp: str = None) -> None:
    path = os.path.join(session_path, _SKILLS_STATE_FILE)
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if name in data:
        return
    data[name] = stamp or time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def record_skill_activation(session_path: str, tool_name: str, tool_args, res_str: str) -> None:
    """Учёт подключённого скилла: skills get/run прошли успешно → имя в файл сессии.

    Файл переживает overflow-reset и выход из сессии — по нему восстанавливается
    памятка SKILLS_ACTIVE (какие скиллы были подключены и как их перечитать).
    """
    if tool_name != "skills":
        return
    name = _skill_activation_name(tool_args, res_str)
    if not name:
        return
    _record_skill_name(session_path, name)


def _backfill_session_state(session_path: str) -> None:
    """Разовый на сессию бэкфилл по неизменяемым архивам (resume/старый код).

    Активации, случившиеся до появления enabled_skills.json (скилл подключён в
    прошлых запусках процесса), терялись: SKILLS_ACTIVE не генерировался, и
    модель после resume не видела ни вики, ни скиллов. Сканируем tools.log
    (завершённые skills get/run) и context.json (уже вшитый WIKI_MODE).
    """
    if session_path in _skills_state_scanned:
        return
    _skills_state_scanned.add(session_path)
    if not os.path.exists(os.path.join(session_path, _SKILLS_STATE_FILE)):
        found = {}
        try:
            with open(os.path.join(session_path, "tools.log"), "r",
                      encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"skills"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if rec.get("tool") != "skills" or rec.get("status") != "completed":
                        continue
                    name = _skill_activation_name(rec.get("arguments"),
                                                  rec.get("full_result"))
                    if name and name not in found:
                        found[name] = str(rec.get("timestamp") or "backfill")[:19]
        except OSError:
            found = {}
        for name, stamp in found.items():
            _record_skill_name(session_path, name, stamp)
    if session_path in _wiki_note_persisted:
        return
    try:
        with open(os.path.join(session_path, "context.json"), "r",
                  encoding="utf-8", errors="ignore") as f:
            if "WIKI_MODE:" in f.read():
                _wiki_note_persisted.add(session_path)
    except OSError:
        pass


def refresh_skills_active_note(messages: list, session_path: str) -> None:
    """Живая system-памятка о подключённых скиллах: одна, всегда актуальная.

    Перезаписывается на каждый раунд (старая с тем же префиксом удаляется),
    поэтому переживает overflow-reset (messages.clear()) и возвращается при
    resume — файл сессии неизменяем. Модель знает, какие скиллы были подключены,
    и что их инструкции могли быть вытеснены — перечитывает, а не догадывается.
    """
    _backfill_session_state(session_path)
    try:
        with open(os.path.join(session_path, _SKILLS_STATE_FILE), "r",
                  encoding="utf-8") as f:
            data = json.load(f)
        names = sorted(str(k) for k in (data or {}) if str(k).strip())
    except (OSError, json.JSONDecodeError):
        names = []
    for m in list(messages):
        if m.get("role") == "system" and str(m.get("content", "")).startswith(SKILLS_ACTIVE_PREFIX):
            messages.remove(m)
    if not names:
        return
    note = (f"{SKILLS_ACTIVE_PREFIX} в этой сессии подключались скиллы: "
            + ", ".join(names)
            + ". Их инструкции — ранние tool-результаты; они могли быть вытеснены "
            "или сняты сбросом контекста. Не догадывайся о их содержимом — "
            "перечитай: skills action=get name=<имя>.")
    messages.append({"role": "system", "content": note})


def _compress_reason_ru(reason: str) -> str:
    """Краткая человеческая причина сжатия для уведомления в ленте."""
    r = str(reason or "")
    if r.startswith("hard_ctx_threshold_reached"):
        return "заполнилась больше чем на 90%"
    if r.startswith("repetition_detected"):
        return "заклинил на повторах"
    if "loop" in r.lower():
        return "ходил по кругу"
    if "recoveries_exhausted" in r:
        return "не вышло продолжить мягко"
    return r or "неизвестная причина"


def _append_system_once(messages: list, content: str) -> bool:
    """Добавляет system-реплику, только такой же ещё нет в истории.

    Без дедупа служебные памятки, добавляемые на каждый tool-раунд,
    накапливались сотнями копий и раздували запрос за пределы контекста
    (регресс 2026-10-10: 325 копий TOOL_USAGE_REMINDER ≈ 236k токенов).
    """
    if not content or not content.strip():
        return False
    for m in messages:
        if m.get("role") == "system" and str(m.get("content", "")) == content:
            return False
    messages.append({"role": "system", "content": content})
    return True


def _estimate_tokens_uncalibrated(text: str) -> int:
    if not text:
        return 0
    return max(1, len(str(text)) // 4)


def _estimate_tokens(text: str) -> int:
    base = _estimate_tokens_uncalibrated(text)
    k = _token_k_state.get("current", 1.0)
    if k == 1.0:
        return base
    return max(1, int(base * k))


def _estimate_message_tokens(msg: dict) -> int:
    content = msg.get("content", "")
    dens = _prompt_density()
    if dens is not None:
        # Плотность измерена как prompt_tokens / символы контента и уже
        # поглощает служебный оверхед шаблона — отдельные +8 не нужны.
        chars = len(content) if isinstance(content, str) else 0
        if "tool_calls" in msg and msg["tool_calls"]:
            try:
                chars += len(json.dumps(msg["tool_calls"], ensure_ascii=False))
            except Exception:
                chars += len(str(msg["tool_calls"]))
        return max(1, int(chars * dens))
    base = 8
    t = base + _estimate_tokens(content)
    if "tool_calls" in msg and msg["tool_calls"]:
        try:
            t += _estimate_tokens(json.dumps(msg["tool_calls"], ensure_ascii=False))
        except Exception:
            t += _estimate_tokens(str(msg["tool_calls"]))
    return t


def _estimate_messages_tokens(msgs: list) -> int:
    if not msgs:
        return 0
    return sum(_estimate_message_tokens(m) for m in msgs)


def _estimate_messages_tokens_raw(msgs: list) -> int:
    """Оценка без калибровочного коэффициента — знаменатель для замера k."""
    if not msgs:
        return 0
    total = 0
    for m in msgs:
        total += 8 + _estimate_tokens_uncalibrated(m.get("content", ""))
        if m.get("tool_calls"):
            try:
                s = json.dumps(m["tool_calls"], ensure_ascii=False)
            except Exception:
                s = str(m["tool_calls"])
            total += _estimate_tokens_uncalibrated(s)
    return total


def calibrate_token_estimator(model, prompt_eval_count, prepared_messages, persist_path=None):
    """EMA-поправка оценщика: k ← (1−α)·k + α·(prompt_eval_count / raw_estimate).

    Возвращает новый k или None, если замер неприменим (нет метрик/оценка нулевая,
    выброс за пределами 0.2–5.0). Деление на ноль защищено.
    """
    try:
        raw_est = _estimate_messages_tokens_raw(prepared_messages or [])
        if not model or not prompt_eval_count or raw_est <= 0:
            return None
        k_obs = float(prompt_eval_count) / float(raw_est)
        if not (0.2 <= k_obs <= 5.0):
            return None
        prev = float(_token_k_state["by_model"].get(model, 1.0))
        k = (1.0 - _TOKEN_K_EMA_ALPHA) * prev + _TOKEN_K_EMA_ALPHA * k_obs
        _token_k_state["by_model"][model] = k
        _token_k_state["current"] = k
        if persist_path:
            try:
                with open(persist_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "type": "token_calibration",
                        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "model": model,
                        "k": round(k, 4),
                        "prompt_eval_count": int(prompt_eval_count),
                        "est_raw": int(raw_est),
                    }, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return k
    except Exception:
        return None


def restore_token_calibration(persist_path, model):
    """Восстанавливает k модели из последней записи token_calibration в performance.log."""
    try:
        last = None
        with open(persist_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "token_calibration" and ev.get("model") == model:
                    last = ev
        if last:
            k = float(last.get("k") or 1.0)
            if 0.2 <= k <= 5.0:
                _token_k_state["by_model"][model] = k
                _token_k_state["current"] = k
                return k
    except Exception:
        pass
    return None


def _segment_indices(msgs: list) -> list:
    """Сегменты истории: блоки от user-сообщения до следующего user-сообщения.

    Всё, что до первого user, — отдельный сегмент. Границы вытеснения проходят
    только по границам сегментов, поэтому пары assistant.tool_calls ↔ tool
    никогда не разрываются.
    """
    segs = []
    cur = []
    for i, m in enumerate(msgs):
        if m.get("role") == "user" and cur:
            segs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        segs.append(cur)
    return segs


def _unit_indices(msgs: list, seg: list) -> list:
    """Неделимые единицы внутри сегмента: assistant с tool_calls + его tool-ответы."""
    units = []
    j = 0
    while j < len(seg):
        i = seg[j]
        m = msgs[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            unit = [i]
            k = j + 1
            while k < len(seg) and msgs[seg[k]].get("role") == "tool":
                unit.append(seg[k])
                k += 1
            units.append(unit)
            j = k
        else:
            units.append([i])
            j += 1
    return units


FORGOTTEN_BLOCK_BUDGET = 600
# Начало текста протокола overflow-ресета (prompts/context_overflow_protocol.txt
# и fallback в _ollama_summarize_and_reset_context). Старые протоколы вытесняются
# новым при очередном ресете — иначе их копии накапливаются между ресетами.
OVERFLOW_PROTOCOL_MARKERS = ("Контекст был очищен", "Context cleared.")
FORGOTTEN_BLOCK_HEADER = (
    "FORGOTTEN_INDEX — каталог автоматически вытеснённых из контекста ходов "
    "(механический индекс, не пересказ). Это указатели, а не история: "
    "строка = время, облако терминов вызова модели, указатель turn_id, "
    "подписи инструментов, размер контекста. Детали старого хода — "
    "session_memory get_turn turn_id=… или search; полное содержимое — "
    "артефакты в папке сессии. Не догадывайся, что было забыто, — смотри по указателю."
)


def _build_forgotten_block(session_path, first_kept_ts):
    """Одна system-реплика «скользящее окно о забытом» (регенерируется целиком).

    Строки — окна вызовов модели (core.session_digest), вытесненные из контекста;
    древние строки иерархически сворачиваются в одну. Бюджет — FORGOTTEN_BLOCK_BUDGET
    токенов. Пустая строка — Digest недоступен или вытеснять нечего.
    """
    try:
        from core import session_digest
    except Exception:
        return ""
    try:
        windows = session_digest.build_windows(session_path)
    except Exception:
        return ""
    forgotten = [
        w for w in windows
        if w.ts_end and (not first_kept_ts or w.ts_end <= first_kept_ts)
    ]
    if not forgotten:
        return ""
    lines = session_digest.build_digest_lines(forgotten)
    entries = [lines[i] + "\n" + lines[i + 1] for i in range(0, len(lines) - 1, 2)]
    if len(lines) % 2:
        entries.append(lines[-1])
    budget = max(100, FORGOTTEN_BLOCK_BUDGET - _estimate_tokens(FORGOTTEN_BLOCK_HEADER))
    kept = []
    used = 0
    merged_src = []
    for entry in reversed(entries):
        t = _estimate_tokens(entry)
        if kept and used + t > budget:
            merged_src.append(entry)
            continue
        kept.insert(0, entry)
        used += t
    def _assemble():
        parts = [FORGOTTEN_BLOCK_HEADER]
        if merged_src:
            try:
                parts.append(session_digest.merge_old_lines(list(reversed(merged_src))))
            except Exception:
                pass
        parts.extend(kept)
        return "\n".join(parts)

    result = _assemble()
    # округление оценки по частям может дать перебор — подгоняем по собранному блоку
    while len(kept) > 1 and _estimate_tokens(result) > FORGOTTEN_BLOCK_BUDGET:
        merged_src.append(kept.pop(0))
        result = _assemble()
    return result


def _prepare_messages_for_ollama(sm, session_path, messages, num_ctx, reserve_tokens=1200):
    if num_ctx <= 0:
        return messages
    # Бюджет тримма обязан лежать НИЖЕ хард-триггера (HARD_CTX_PCT·num_ctx),
    # иначе big-bang-ресет всегда успевает первым и сегментный тримм — мёртвый
    # код (регресс 2026-10-10: 13 ресетов каскадом, 0 trim-артефактов).
    budget = max(256, min(num_ctx, int(num_ctx * HARD_CTX_PCT)) - max(0, reserve_tokens))
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]
    used = sum(_estimate_message_tokens(m) for m in system_msgs)
    keep = [False] * len(other_msgs)
    segs = _segment_indices(other_msgs)
    # держим целые сегменты от самых свежих к старым
    i = len(segs) - 1
    while i >= 0:
        seg_cost = sum(_estimate_message_tokens(other_msgs[x]) for x in segs[i])
        if used + seg_cost > budget:
            break
        for x in segs[i]:
            keep[x] = True
        used += seg_cost
        i -= 1
    # ни один сегмент не влезает — держим хотя бы последние неделимые единицы
    # самого свежего сегмента (инвариант пар tool_calls ↔ tool сохраняется)
    if not any(keep) and segs:
        for unit in reversed(_unit_indices(other_msgs, segs[-1])):
            unit_cost = sum(_estimate_message_tokens(other_msgs[x]) for x in unit)
            if any(keep) and used + unit_cost > budget:
                break
            for x in unit:
                keep[x] = True
            used += unit_cost
    # Гарантии: в prepared обязан остаться хотя бы один непустой user —
    # OpenAI-совместимые шлюзы (LiteLLM) отвечают 400 "No user query found in
    # messages", если тримм выжил все user-реплики. Держим самую свежую.
    if other_msgs and not any(
            keep[i] and other_msgs[i].get("role") == "user"
            and str(other_msgs[i].get("content") or "").strip()
            for i in range(len(other_msgs))):
        for i in range(len(other_msgs) - 1, -1, -1):
            m = other_msgs[i]
            if m.get("role") == "user" and str(m.get("content") or "").strip():
                keep[i] = True
                break
    kept = [m for idx, m in enumerate(other_msgs) if keep[idx]]
    dropped = [m for idx, m in enumerate(other_msgs) if not keep[idx]]
    trimmed = system_msgs + kept
    artifact_path = ""
    if dropped:
        _compression_stats["tokens"] += _estimate_messages_tokens(dropped)
        _compression_stats["trims"] += 1
        artifact_name = f"context_trim_{int(time.time())}.json"
        try:
            artifact_path = sm.save_artifact(session_path, artifact_name, json.dumps(list(reversed(dropped)), ensure_ascii=False, indent=2))
        except Exception:
            artifact_path = f"./artifacts/{artifact_name}"
    # блок «забытого» вместо старой notice: собирается по границам вытеснения,
    # регенерируется на каждый запрос целиком (в историю не пишется)
    first_kept_ts = ""
    for m in kept:
        ts = str(m.get("timestamp") or "")
        if ts:
            first_kept_ts = ts
            break
    if kept and not first_kept_ts:
        dts = [str(m.get("timestamp") or "") for m in dropped if m.get("timestamp")]
        first_kept_ts = max(dts) if dts else ""
    block = _build_forgotten_block(session_path, first_kept_ts)
    if block:
        trimmed = system_msgs + [{"role": "system", "content": block}] + kept
    elif dropped:
        notice = {
            "role": "system",
            "content": (
                "Контекст был автоматически сокращён, чтобы избежать переполнения. "
                f"Старые сообщения сохранены в артефакт: {artifact_path}"
            )
        }
        trimmed = system_msgs + [notice] + kept
    return trimmed


def _is_empty_completion(full_response, full_thinking, tool_calls) -> bool:
    """Полностью пустое завершение модели: нет текста, reasoning и tool_calls.

    Штатный сбой (модель сглючила/оборвалась) — его нельзя молча принимать за
    финальный ответ. → защита по `MAX_EMPTY_RETRIES_PER_TURN`.
    """
    return (not tool_calls) and (not (full_response or "").strip()) \
        and (not (full_thinking or "").strip())


def _detect_repetition(full_response: str) -> bool:
    if not full_response:
        return False
    lines = [l.strip() for l in full_response.splitlines() if l.strip()]
    if len(lines) < 10:
        return False
    tail = lines[-REPEAT_LINE_WINDOW:]
    last = tail[-1]
    if not last:
        return False
    return sum(1 for l in tail if l == last) >= REPEAT_LINE_MIN_OCCURRENCES


def _stitch_response(parts: list) -> str:
    """Склейка частей ответа, прерванных по finish_reason=length.

    На стыке убирается дословное перекрытие (модель часто повторяет последние
    слова обрывка) и дублирующая первая строка — шов проверяется как повтор.
    """
    out = ""
    for part in parts:
        part = str(part or "")
        if not part:
            continue
        if not out:
            out = part
            continue
        max_ov = min(len(out), len(part), 200)
        ov = 0
        for k in range(max_ov, 0, -1):
            if out[-k:] == part[:k]:
                ov = k
                break
        nxt = part[ov:]
        out_lines = out.splitlines(keepends=True)
        nxt_lines = nxt.splitlines(keepends=True)
        if out_lines and nxt_lines and out_lines[-1].strip() and \
                out_lines[-1].strip() == nxt_lines[0].strip():
            nxt = "".join(nxt_lines[1:])
        out += nxt
    return out


def _ollama_error_indicates_no_tools(error_msg: str) -> bool:
    if not error_msg:
        return False
    msg = str(error_msg).lower()
    return "does not support tools" in msg or "doesn't support tools" in msg or "not support tools" in msg


def _server_label(sm) -> str:
    """Человекочитаемое имя РЕАЛЬНОГО сервера модели (а не всегда «Ollama»)."""
    try:
        base = sm.config.get('Ollama', 'BaseUrl', fallback='').strip().rstrip('/')
    except Exception:
        base = ""
    try:
        if is_openai_backend(sm):
            return base or "OpenAI-совместимый сервер"
    except Exception:
        pass
    return f"Ollama ({base})" if base else "Ollama"


def _extract_api_error(data) -> str:
    """Достаёт осмысленный текст ошибки из ответа любого из бэкендов."""
    if not isinstance(data, dict):
        return str(data)
    err = data.get("error")
    if isinstance(err, dict):
        for k in ("message", "type", "code"):
            if err.get(k):
                return str(err[k])
        return json.dumps(err, ensure_ascii=False)
    if err:
        return str(err)
    detail = data.get("detail")
    if detail:
        return str(detail)
    return "Неизвестная ошибка сервера"


def _format_api_error(status, error_msg, error_text="", server_label="") -> str:
    """Разборчивый блок ошибки API для чата и истории (без спама)."""
    head = f"⚠ Ошибка API: HTTP {status}"
    if server_label:
        head += f" ({server_label})"
    lines = [head, str(error_msg or "Неизвестная ошибка сервера")]
    body = (error_text or "").strip()
    if body and body != str(error_msg).strip():
        lines.append("")
        lines.append(body[:2000])
    return "\n".join(lines)


# HTTP-коды, при которых имеет смысл держать сессию и ждать сервер
# (перегрузка, загрузка модели, временная недоступность), а не сдаваться.
TRANSIENT_HTTP_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _is_transient_http(code: int) -> bool:
    return int(code) in TRANSIENT_HTTP_CODES


# Коды, которые тоже пережидаем: проблемы ключа/лимита (401/403) и прочая
# нестабильность — ход не прерываем, а держим сессию с паузой: ключи и
# лимиты пополняются, агент должен дождаться и продолжить.
RETRYABLE_EXTRA_HTTP_CODES = frozenset({401, 403})


def _is_retryable_http(code: int) -> bool:
    """Коды, которые лечатся ожиданием и повтором."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return False
    return code in TRANSIENT_HTTP_CODES or code in RETRYABLE_EXTRA_HTTP_CODES


def _call_ui_result(app, fn, *args, **kwargs):
    """Вызвать fn в UI-потоке и вернуть результат.

    Textual `call_from_thread` возвращает результат НАПРЯМУЮ (не Future),
    поэтому `.result()` здесь недопустим: он бросает AttributeError уже ПОСЛЕ
    выполнения колбэка, а fallback повторно выполняет fn на уже изменённом
    состоянии (так терялась очередь мыслей: забор очищал очередь, а повторный
    вызов возвращал пусто).
    """
    try:
        return app.call_from_thread(fn, *args, **kwargs)
    except Exception:
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None




def _ensure_chat_only_system_message(messages: list) -> None:
    if not messages:
        return
    marker = "CHAT_ONLY_MODE"
    for m in messages:
        if m.get("role") == "system" and marker in str(m.get("content", "")):
            return
    messages.append({
        "role": "system",
        "content": (
            f"{marker}\n"
            "В этом режиме инструменты недоступны (tool-calling отключён). "
            "Не предлагай и не описывай использование инструментов, файловых операций или команд. "
            "Отвечай только текстом и, если нужно, проси пользователя выполнить действия вручную."
        ),
    })


# Мемо каталогов: skills/experience action=list тянут ~12KB; после overflow-reset
# модель по директиве tool_policy берёт их заново каждый раз и снова выбивает
# бюджет. Харнес один раз за сессию кэширует дамп в артефакт, повтор отдаёт
# короткой памяткой с указателем — каталог не «перечитывается» бесконечно.
_catalog_memo: Dict[str, Dict] = {}


def _catalog_memo_key(tool_name, tool_args):
    if tool_name not in ("skills", "experience"):
        return None
    if not isinstance(tool_args, dict) or str(tool_args.get("action", "")).lower() != "list":
        return None
    try:
        return (tool_name, json.dumps(tool_args, sort_keys=True, ensure_ascii=False))
    except (TypeError, ValueError):
        return None


def _catalog_memo_check(session_path, tool_name, tool_args):
    prev = _catalog_memo.get(str(session_path), {}).get(_catalog_memo_key(tool_name, tool_args)) if tool_name else None
    if not prev:
        return None
    ts, artifact = prev
    return (f"CATALOG_CACHED: каталог {tool_name} уже брался в этой сессии в {ts}. "
            f"Полный список: {artifact}. Повторно list не запрашивай — работай по нему.")


def _catalog_memo_store(session_path, tool_name, tool_args, result, sm):
    key = _catalog_memo_key(tool_name, tool_args)
    if not key or not result:
        return
    try:
        artifact = sm.save_artifact(session_path, f"catalog_{tool_name}_{int(time.time())}.txt", str(result))
    except Exception:
        artifact = "(артефакт не сохранён)"
    _catalog_memo.setdefault(str(session_path), {})[key] = (time.strftime("%H:%M:%S"), artifact)


# Pressure-инжект (этап 5): при пересечении вверх 70%/85% заполненности контекста
# один раз дописывается строка в конец TOOL_RESULT_SUMMARY. Без отдельных
# сообщений; не повторяется, пока уровень не сброшен (финальный ответ хода / reset).
PRESSURE_LEVELS = (
    (0.85, "критично, завершай ход: не начинай новых разведок, фиксируй результат"),
    (0.70, "сворачивай рассуждения: не пересказывай известное, думай короче"),
    (0.50, "планируй остаток: оцени задачу через session_memory action=context_stats, "
           "разбивай на части, жми compact по отработанным блокам"),
)
_pressure_state = {"ratio": 0.0, "notified": 0, "used": 0, "max": 0}


def set_context_pressure(ratio, used=0, max_ctx=0) -> None:
    try:
        _pressure_state["ratio"] = max(0.0, min(1.5, float(ratio or 0.0)))
    except (TypeError, ValueError):
        pass
    try:
        _pressure_state["used"] = int(used or 0)
        _pressure_state["max"] = int(max_ctx or 0)
    except (TypeError, ValueError):
        pass


def reset_context_pressure() -> None:
    _pressure_state["ratio"] = 0.0
    _pressure_state["notified"] = 0
    _pressure_state["used"] = 0
    _pressure_state["max"] = 0


def _pressure_note() -> str:
    """Строка уровня с гистерезисом: каждый уровень объявляется один раз до сброса."""
    ratio = _pressure_state["ratio"]
    used, mx = _pressure_state.get("used", 0), _pressure_state.get("max", 0)
    abs_part = f" ({used}/{mx} ток.)" if mx else ""
    for idx, (thr, text) in enumerate(PRESSURE_LEVELS):
        if ratio >= thr:
            level = len(PRESSURE_LEVELS) - idx
            if level <= _pressure_state["notified"]:
                return ""
            _pressure_state["notified"] = level
            return f"CONTEXT_PRESSURE: контекст ~{int(thr * 100)}%{abs_part} — {text}."
    return ""


def _context_blocks(messages: list) -> list:
    """Блоки живого контекста: user-корневые сегменты не-system-сообщений.

    Нумерация 1..N совпадает с аргументом blocks у session_memory compact.
    Для каждого блока — оценка токенов, время, превью user-реплики, имена
    инструментов: агент видит, кто именно съел контекст.
    """
    other = [m for m in messages if isinstance(m, dict) and m.get("role") != "system"]
    blocks = []
    for si, seg in enumerate(_segment_indices(other), start=1):
        toks = sum(_estimate_message_tokens(other[x]) for x in seg)
        user_prev, tools, ts = "", [], ""
        for x in seg:
            m = other[x]
            if not ts and m.get("timestamp"):
                ts = str(m["timestamp"])
            if m.get("role") == "user" and not user_prev:
                user_prev = " ".join(str(m.get("content") or "").split())[:80]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    n = str(((tc or {}).get("function") or {}).get("name") or "")
                    if n and n not in tools:
                        tools.append(n)
        blocks.append({"id": si, "messages": len(seg), "tokens": toks, "ts": ts,
                       "user_preview": user_prev, "tools": tools})
    return blocks


def write_context_map(session_path: str, messages: list, num_ctx: int) -> None:
    """Снимок карты контекста на каждый запрос: харнес пишет, session_memory читает."""
    try:
        blocks = _context_blocks(messages)
        total = sum(b["tokens"] for b in blocks)
        payload = {
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "num_ctx": int(num_ctx or 0),
            "used_est": total,
            "used_pct": int(total / num_ctx * 100) if num_ctx else 0,
            "compression_stats": dict(_compression_stats),
            "blocks": blocks,
        }
        with open(os.path.join(session_path, "context_map.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError:
        pass


def apply_pending_compacts(sm, session_path: str, messages: list, num_ctx: int) -> str:
    """Исполняет запрос агента на компакцию (compact_request.json) на границе раунда.

    Сегменты уходят из messages в артефакт; на их место — одна system-заглушка
    (механическая: блоки, освобождённые токены, артефакт, пометка агента).
    Рельсы: текущий (последний) блок не сжимается, блоки дешевле MIN_COMPACT_PCT
    пропускаются, кап MAX_COMPACT_BLOCKS. context.json не трогаем — история цела,
    поднятое — session_memory search/get_turn. Пустая строка — запроса не было.
    """
    req_path = os.path.join(session_path, "compact_request.json")
    try:
        with open(req_path, "r", encoding="utf-8") as f:
            req = json.load(f)
        os.remove(req_path)
    except (OSError, json.JSONDecodeError):
        return "", ""
    try:
        from tools.session_memory import parse_block_ids
        ids = parse_block_ids(req.get("blocks"))
    except Exception:
        return "", ""
    note = str(req.get("note") or "")[:200]
    if not ids:
        return "", ""

    other_pos = [i for i, m in enumerate(messages)
                 if isinstance(m, dict) and m.get("role") != "system"]
    segs = _segment_indices([messages[i] for i in other_pos])
    n_segs = len(segs)
    used_before = sum(_estimate_message_tokens(m) for m in messages)

    skipped_current, unknown, small, chosen = [], [], [], []
    for bid in ids[:MAX_COMPACT_BLOCKS]:
        if bid < 1 or bid > n_segs:
            unknown.append(bid)
        elif bid == n_segs:
            skipped_current.append(bid)
        else:
            gidx = [other_pos[p] for p in segs[bid - 1]]
            toks = sum(_estimate_message_tokens(messages[i]) for i in gidx)
            if num_ctx and toks < MIN_COMPACT_PCT * num_ctx:
                small.append(bid)
            else:
                chosen.append((bid, gidx, toks))

    if not chosen:
        parts = []
        if skipped_current:
            parts.append(f"текущий ход не сжимается (блоки {','.join(map(str, skipped_current))})")
        if small:
            parts.append(f"мелкие блоки пропущены (<{int(MIN_COMPACT_PCT * 100)}% num_ctx): "
                         f"{','.join(map(str, small))}")
        if unknown:
            parts.append(f"нет таких блоков: {','.join(map(str, unknown))}")
        s = "COMPACT: ничего не сжато — " + "; ".join(parts) if parts else ""
        return s, s

    drop_idx, freed = set(), 0
    tool_names = []
    for bid, gidx, toks in chosen:
        drop_idx.update(gidx)
        freed += toks
        for i in gidx:
            m = messages[i]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    n = str(((tc or {}).get("function") or {}).get("name") or "")
                    if n and n not in tool_names:
                        tool_names.append(n)
    dropped = [messages[i] for i in sorted(drop_idx)]
    artifact_name = f"context_compact_{int(time.time())}.json"
    try:
        artifact_path = sm.save_artifact(session_path, artifact_name,
                                         json.dumps(dropped, ensure_ascii=False, indent=2))
    except Exception:
        artifact_path = f"./artifacts/{artifact_name}"
    insert_at = min(drop_idx)
    for i in sorted(drop_idx, reverse=True):
        del messages[i]

    used_after = used_before - freed
    pct_b = int(used_before / num_ctx * 100) if num_ctx else 0
    pct_a = int(used_after / num_ctx * 100) if num_ctx else 0
    done_ids = [bid for bid, _, _ in chosen]
    extra = []
    if skipped_current:
        extra.append(f"текущий ход не тронут ({','.join(map(str, skipped_current))})")
    if small:
        extra.append(f"мелкие пропущены (<{int(MIN_COMPACT_PCT * 100)}% num_ctx): "
                     f"{','.join(map(str, small))}")
    if unknown:
        extra.append(f"нет блоков {','.join(map(str, unknown))}")
    ids_str = ",".join(map(str, done_ids))
    # Структурированная заглушка: первая строка — маркер и суть, дальше по полям.
    # Читается и человеком, и моделью; маркер COMPACTED_BLOCKS — на первой строке.
    lines = [
        f"COMPACTED_BLOCKS: блоки {ids_str} сжаты по запросу агента",
        f"• освобождено ≈{freed} токенов ({pct_b}%→{pct_a}% от num_ctx)",
        f"• инструменты: {', '.join(tool_names) if tool_names else '—'}",
        f"• артефакт: {artifact_path} — поднять: session_memory search/get_turn",
    ]
    if note:
        lines.append(f"• пометка агента: {note}")
    if extra:
        lines.append("• пропущено: " + "; ".join(extra))
    stub = "\n".join(lines)
    brief = f"блоки {ids_str} → −{freed} ток. ({pct_b}%→{pct_a}%)"
    messages.insert(insert_at, {"role": "system", "content": stub})

    _compression_stats["tokens"] += freed
    _compression_stats["manual"] = _compression_stats.get("manual", 0) + 1
    _compression_stats["last_reason"] = "agent_requested"
    return stub, brief


def _web_jobs_notice() -> str:
    """Инкрементная сводка фоновых веб-задач для модели ('' — нечего сказать)."""
    try:
        from tools import web_jobs as _wj
        return _wj.format_notifications()
    except Exception:
        return ""


def _compact_tool_message(tool_name, tool_args, result, artifact_path):
    res_str = "" if result is None else str(result)
    size_kb = len(res_str.encode('utf-8', errors='ignore')) / 1024
    shown = res_str[:TOOL_OUTPUT_MAX_CHARS]
    truncated = len(res_str) > TOOL_OUTPUT_MAX_CHARS
    args_preview = tool_args
    try:
        safe_args = tool_args
        if tool_name == "code_editor" and isinstance(tool_args, dict):
            safe_args = dict(tool_args)
            for k in ("content", "old_text", "new_text", "edits"):
                if k in safe_args and safe_args[k] is not None:
                    try:
                        safe_args[k] = f"<omitted:{len(str(safe_args[k]))} chars>"
                    except Exception:
                        safe_args[k] = "<omitted>"
        args_preview = json.dumps(safe_args, ensure_ascii=False)
    except Exception:
        args_preview = str(tool_args)

    extra_lines = ""
    if tool_name == "code_editor":
        try:
            parsed = json.loads(res_str)
            if isinstance(parsed, dict):
                p = parsed.get("path")
                changed = parsed.get("changed")
                if p is not None:
                    extra_lines += f"\nfile_path: {p}"
                if changed is not None:
                    extra_lines += f"\nchanged: {str(bool(changed)).lower()}"
        except Exception:
            pass

    msg = (
        f"TOOL_RESULT_SUMMARY\n"
        f"tool: {tool_name}\n"
        f"args: {args_preview}\n"
        f"artifact_path: {artifact_path}\n"
        f"size_kb: {size_kb:.2f}\n"
        f"truncated_in_context: {str(truncated).lower()}\n"
        f"content_preview:\n{shown}"
        f"{extra_lines}"
    )
    if truncated:
        msg += f"\n...[TRUNCATED {len(res_str) - TOOL_OUTPUT_MAX_CHARS} chars]"
    note = _pressure_note()
    if note:
        msg += f"\n{note}"
    return msg


def _ollama_summarize_and_reset_context(
    sm, model, session_path, messages, num_ctx,
    reason, reserve_tokens=1600,
):
    system_msgs = [m for m in messages if m.get("role") == "system"
                   and not str(m.get("content", "")).lstrip().startswith(OVERFLOW_PROTOCOL_MARKERS)]

    last_user_prompt = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if not content.startswith("Auto-continue:") and not content.startswith("Сформулируй финальный ответ"):
                last_user_prompt = content
                break

    artifact_name = f"context_overflow_full_{int(time.time())}.json"
    try:
        artifact_path = sm.save_artifact(
            session_path,
            artifact_name,
            json.dumps(messages, ensure_ascii=False, indent=2),
        )
    except Exception:
        artifact_path = f"./artifacts/{artifact_name}"

    summary_system_content = sm.load_prompt(
        session_path,
        "context_overflow_summary",
        REASON=reason,
        ORIGINAL_TASK=last_user_prompt[:300]
    )

    summary_system = {
        "role": "system",
        "content": summary_system_content or "Create session protocol",
    }
    summary_user_content = sm.load_prompt(
        session_path,
        "context_overflow_user",
        REASON=reason,
        ORIGINAL_TASK=last_user_prompt[:500],
        ARTIFACT_PATH=artifact_path
    )

    summary_user = {
        "role": "user",
        "content": summary_user_content or f"Create session protocol. Reason: {reason}",
    }

    summary_messages = system_msgs + [summary_system, summary_user]
    summary_messages = _prepare_messages_for_ollama(
        sm,
        session_path,
        summary_messages,
        num_ctx=num_ctx,
        reserve_tokens=reserve_tokens,
    )

    ollama_base_url = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
    verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)
    chat_url = f"{ollama_base_url}/api/chat"

    summary_text = (
        "SESSION_PROTOCOL\n"
        f"reason: {reason}\n"
        f"artifact: {artifact_path}\n"
        f"original_task: {last_user_prompt[:200]}...\n"
        "key_facts:\n"
        "- (summary generation failed)\n"
        "next_steps:\n"
        "- Продолжить с очищенным контекстом\n"
    )
    try:
        payload = {
            "model": model,
            "messages": summary_messages,
            "stream": False,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": 450,
            },
        }
        apply_native_think(sm, payload)
        data = {}
        if is_openai_backend(sm):
            data = chat_once(
                sm,
                payload,
                timeout=sm.config.getint('Ollama', 'RequestTimeout', fallback=300),
                verify_ssl=verify_ssl,
            )
            summary_text = data.get("message", {}).get("content") or summary_text
        else:
            res = requests.post(
                chat_url,
                json=payload,
                timeout=sm.config.getint('Ollama', 'RequestTimeout', fallback=300),
                verify=verify_ssl,
            )
            if res.status_code == 200:
                data = res.json()
                summary_text = data.get("message", {}).get("content") or summary_text
        # Срез калибратора и для нестримингового резюмирования.
        try:
            _pc = int(data.get("prompt_eval_count") or 0)
            _ec = int(data.get("eval_count") or 0)
            if _pc or _ec:
                token_calibrator.record_api_call(
                    deploy=token_calibrator.deploy_fingerprint(
                        model, _server_label(sm)),
                    kind="summary",
                    roles={"summary": sum(len(str(m.get("content") or ""))
                                          for m in summary_messages)},
                    prompt_tokens=_pc,
                    response_chars=len(summary_text or ""),
                    completion_tokens=_ec,
                    reasoning_tokens=int(data.get("reasoning_tokens") or 0),
                )
                net_meter.add_usage(_pc, _ec)
        except Exception:
            pass
    except Exception:
        pass

    protocol_content = sm.load_prompt(
        session_path,
        "context_overflow_protocol",
        ARTIFACT_PATH=artifact_path,
        SESSION_PROTOCOL=summary_text,
        ORIGINAL_TASK=last_user_prompt[:300]
    )

    protocol_msg = {
        "role": "system",
        "content": protocol_content or f"Context cleared. Continue task: {last_user_prompt[:100]}",
    }

    _compression_stats["tokens"] += _estimate_messages_tokens(
        [m for m in messages if m.get("role") != "system"])
    _compression_stats["resets"] += 1
    _compression_stats["last_reason"] = str(reason or "")
    messages.clear()
    messages.extend(system_msgs + [protocol_msg])
    reset_context_pressure()

    return protocol_msg["content"], artifact_path


def _abort_stream(response) -> None:
    """Принудительно оборвать стрим модели.

    `response.close()` не прерывает блокирующий read в потоке-читателе, поэтому
    Ollama продолжает генерировать. Здесь мы делаем `shutdown()` сокета — это
    разблокирует read и закрывает соединение, по которому сервер понимает, что
    генерацию надо остановить.
    """
    # Развернуть обёртку OpenAI-совместимого бэкенда до requests.Response.
    resp = getattr(response, "_resp", response)

    # 1) socket.shutdown — единственный надёжный способ разбудить blocked recv.
    try:
        import socket as _socket
        raw = getattr(resp, "raw", None)
        fp = getattr(getattr(raw, "_fp", None), "fp", None)
        sock = getattr(getattr(fp, "raw", None), "_sock", None)
        if sock is not None:
            try:
                sock.shutdown(_socket.SHUT_RDWR)
            except Exception:
                pass
    except Exception:
        pass

    # 2) Освободить соединение urllib3.
    try:
        raw = getattr(resp, "raw", None)
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass
            try:
                raw.release_conn()
            except Exception:
                pass
    except Exception:
        pass

    # 3) Закрыть объект ответа (requests/обёртка).
    try:
        response.close()
    except Exception:
        pass


def _post_stream_interruptible(app, do_request, poll: float = 0.2):
    """Выполнить HTTP-запрос стрима в отдельном потоке, прерываемо по Esc.

    Блокирующий `requests.post(stream=True)` ждёт заголовки ответа и не
    реагирует на флаг остановки: если сервер «завис», Esc не возвращал
    управление, пока запрос не отвалится по таймауту. Здесь запрос идёт в
    отдельном потоке, а воркер ждёт его с проверкой `_stop_requested`.

    Возвращает (response, None) при успехе, (None, "stopped") при Esc.
    Исключения пробрасываются.
    """
    box = {}
    done = threading.Event()

    def _run():
        try:
            box["resp"] = do_request()
        except Exception as e:
            box["err"] = e
        finally:
            done.set()
            # Если нас остановили, а ответ всё же пришёл — закрываем, чтобы не
            # оставлять висящее соединение.
            if getattr(app, "_stop_requested", False) and box.get("resp") is not None:
                try:
                    box["resp"].close()
                except Exception:
                    pass

    threading.Thread(target=_run, daemon=True).start()
    while not done.wait(poll):
        if getattr(app, "_stop_requested", False):
            return None, "stopped"
    if "err" in box:
        raise box["err"]
    return box.get("resp"), None


def ask_ollama_textual(
    model: str,
    messages: List[Dict],
    session_path: str,
    num_ctx: int = 8192,
    dangerous_mode: bool = False,
    version: str = "",
    initial_prompt: str = "",
    proofread: bool = False,
    proofreader_fn=None,
    resume_session: bool = False,
) -> List[Dict]:
    sm = SessionManager()
    tm = ToolManager()

    ollama_base_url = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
    ollama_chat_url = f"{ollama_base_url}/api/chat"
    verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)
    request_timeout = sm.config.getint('Ollama', 'RequestTimeout', fallback=300)

    # Калибратор «байты→токены»: тихий сбор пар (payload ↔ usage) рядом с базой
    # сессий. Фаза 1 ничего не меняет в панели — только копит замеры.
    try:
        token_calibrator.init(token_calibrator.default_store_path(
            getattr(sm, 'base_path', None)))
    except Exception:
        pass

    if messages and not any(m.get("role") == "system" and "BOTINOK" in str(m.get("content", "")) for m in messages):
        identity_content = sm.load_prompt(session_path, "identity")
        if identity_content:
            messages.insert(0, {"role": "system", "content": identity_content})

    # Ступенчатое раскрытие инструментов: в payload всегда только tools/sign_step
    # и включённые; остальные — кратким каталогом здесь, схемы по tools(enable).
    if messages and not any(m.get("role") == "system" and "TOOLS_CATALOG" in str(m.get("content", "")) for m in messages):
        try:
            from tools.tools_catalog import catalog_text
            _cat = catalog_text(tm)
            if _cat:
                messages.insert(1, {"role": "system", "content": "TOOLS_CATALOG\n" + _cat})
        except Exception:
            pass

    app = BotinokTextualApp(session_path=session_path, version=version,
                            initial_prompt=initial_prompt,
                            theme=botinok_themes.load_theme_name(sm.config),
                            config_path=getattr(sm, "config_path", None))
    # Живой SessionManager нужен TUI для чтения/записи ReasoningEffort
    # (клик по чипу рассуждения в шапке). Всё остальное (списки моделей,
    # рассуждение) — лениво по клику в шапке и на дисковом кэше:
    # при старте ни одного лишнего запроса к серверу.
    app.sm = sm
    app.set_model_info(model, dangerous=dangerous_mode,
                       server=_server_label(sm), ctx=num_ctx)
    # Первый запуск с openai-бэкендом без ключа — окошко ключа сразу при старте.
    try:
        app.require_api_key = (
            is_openai_backend(sm)
            and not (sm.config.get('Ollama', 'ApiKey', fallback='') or '').strip())
        app.key_url_hint = key_entry_url(sm)
    except Exception:
        pass

    # Регистрируем приложение глобально: инструменты (shell_exec) вызываются из
    # рабочего потока, где ContextVar active_app не наследуется. Без этой
    # регистрации встроенный экран терминала никогда бы не открылся.
    try:
        from core.shell_session import TextualAppRegistry
        TextualAppRegistry.set_app(app)
    except Exception:
        pass

    stream_active = threading.Event()
    stream_active.clear()

    def _call_from_thread(fn, *args, **kwargs):
        try:
            app.call_from_thread(fn, *args, **kwargs)
        except Exception:
            try:
                fn(*args, **kwargs)
            except Exception:
                pass

    def _call_from_thread_result(fn, *args, **kwargs):
        return _call_ui_result(app, fn, *args, **kwargs)

    def _update_stats(**kwargs):
        s = dict(app.stats_data)
        s.update(kwargs)
        _call_from_thread(app.update_stats, **s)

    def _add_tool(name, query, status="running", size_kb=0):
        _call_from_thread(app.add_tool_activity, name, query, status, size_kb)

    def _update_tool(name, status="completed", size_kb=0, query="", detail=None):
        _call_from_thread(app.update_tool_activity, name, status, size_kb, query, detail)

    def _tool_progress(tn, min_interval=0.2):
        """Живой прогресс инструмента: строка или (bytes, total) → detail."""
        last = [0.0]

        def cb(*args, **kwargs):
            text = ""
            if kwargs.get("detail"):
                text = str(kwargs["detail"])
            elif len(args) == 1 and isinstance(args[0], str):
                text = args[0]
            elif len(args) >= 2 and isinstance(args[0], (int, float)):
                done, total = args[0], args[1] or 0
                text = f"⬇ {done/1024:.1f} KB"
                if total:
                    text += f" / {total/1024:.1f} KB ({done/total*100:.0f}%)"
            if not text:
                return
            now = time.time()
            force = bool(kwargs.get("force"))
            if not force and now - last[0] < min_interval:
                return
            last[0] = now
            _call_from_thread(app.update_tool_detail, tn, text[:120])
        return cb

    def _append_user(text):
        _call_from_thread(app.append_user_message, text)

    def _append_chunk(content="", thinking="", tool_stream_json=""):
        _call_from_thread(app.append_assistant_chunk, content, thinking, tool_stream_json)

    def _finalize_turn(content, thinking="", tool_calls=None):
        if not tool_calls:
            reset_context_pressure()
        if tool_calls:
            tool_calls = [tc for tc in tool_calls
                          if (tc.get("function") or {}).get("name") != "sign_step"] or None
        _call_from_thread(app.finalize_assistant_turn, content, thinking, tool_calls)

    def _persist_connection_failure(reason: str, user_prompt: str = "") -> None:
        """Сохраняет факт сетевого сбоя, чтобы контекст не выглядел как новый.

        Пользовательский запрос и system-пометка фиксируются в истории, поэтому
        после обрыва агент видит, на чём остановился, а не начинает заново.
        """
        if user_prompt:
            sm.update_context(session_path, "user", user_prompt)
        note = f"{reason} Сессия не завершена — продолжай с того же места."
        sm.update_context(session_path, "system", note)
        messages.append({"role": "system", "content": note})
        _finalize_turn("", "")

    def _append_tool_result(tool_name, result):
        _call_from_thread(app.append_tool_result, tool_name, result)

    def _write_log(text):
        _call_from_thread(app.append_log, text)

    _stream_buf = []
    _thinking_buf = []

    def _flush_thinking_buf():
        nonlocal _thinking_buf
        if _thinking_buf:
            text = "".join(_thinking_buf)
            _thinking_buf = []
            _call_from_thread(app.append_assistant_chunk, thinking=text)

    def _flush_stream_buf():
        nonlocal _stream_buf
        if _stream_buf:
            text = "".join(_stream_buf)
            _stream_buf = []
            _call_from_thread(app.append_assistant_chunk, content=text)

    def _stream_chunk(content: str):
        _call_from_thread(app.append_assistant_chunk, content=content)

    def _stream_thought(thought: str):
        _call_from_thread(app.append_assistant_chunk, thinking=thought)

    def _refresh_vram():
        try:
            status = sm.get_ollama_status()
            if status and "models" in status:
                vram_info_parts = []
                for m in status["models"]:
                    vram = m.get("size_vram", 0) / (1024**3)
                    vram_info_parts.append(f"{m['name']}: {vram:.2f}GB")
                vram_str = " | ".join(vram_info_parts) if vram_info_parts else "No models loaded"
                _update_stats(vram=vram_str)
            else:
                _update_stats(vram="No models loaded")
        except Exception:
            pass

    def _do_vram_prep():
        try:
            if "qwen3.5:9b" in _current_model:
                _update_stats(status="Forced VRAM Cleanup...")
                try:
                    sm.unload_models()
                except Exception:
                    pass
                time.sleep(1)

            _update_stats(status="Checking Memory...")
            status = None
            try:
                status = sm.get_ollama_status()
            except Exception:
                pass
            if status and "models" in status:
                for m in status["models"]:
                    vram = m.get("size_vram", 0) / (1024**3)
                    if vram > 7.0 or (m['name'] != _current_model and len(status['models']) > 0):
                        _update_stats(status="Unloading Models...")
                        try:
                            sm.unload_models()
                        except Exception:
                            pass
                        break
            _refresh_vram()
            _update_stats(status="Ready")
        except Exception:
            _update_stats(status="Ready")

    def _append_turn_guidance(resume_turn=False):
        """Перед ходом добавляет памятку по инструментам (одну, без дублей).

        Вызывается и на границах tool-раундов; повторная такая же памятка
        не добавляется (_append_system_once).

        При возобновлении сессии из памятки и политики инструментов вырезаются
        строки про обязательную проверку skills/experience — никакой «отменяющей»
        памятки не добавляется, эти инструкции просто не отправляются модели.
        """
        tool_reminder_msg = sm.load_prompt(session_path, "tool_reminder",
                                           PROMPTS_DIR=os.path.join(session_path, 'prompts'))
        if tool_reminder_msg:
            if resume_session:
                tool_reminder_msg = SessionManager.strip_skills_mandate(tool_reminder_msg)
            _append_system_once(messages, tool_reminder_msg)

    # база для уведомлений ленты о сжатии контекста (событие = дельта);
    # живёт всю сессию, чтобы сброс в конце хода не остался без события
    _comp_base = get_compression_stats()

    def _stream_turn(user_text, resume_turn=False):
        nonlocal _stream_buf
        stream_active.set()
        _refresh_vram()
        _update_stats(status="Connecting...")

        current_model = _current_model
        current_ctx = _current_ctx
        current_ollama_chat_url = _ollama_chat_url
        current_verify_ssl = _verify_ssl
        current_timeout = _request_timeout
        server_label = _server_label(sm)
        _set_calib_deploy(current_model, server_label)

        if current_model in MODELS_NO_TOOLS:
            _ensure_chat_only_system_message(messages)

        sm.write_file_header(session_path, "thinking.md", current_model, current_ctx, user_text)
        sm.write_file_header(session_path, "response.md", current_model, current_ctx, user_text)

        tool_rounds = 0
        auto_recoveries = 0
        empty_retries = 0
        proof_rounds = 0
        sign_nudges = 0
        sign_hidden = False
        _sign_reminded = False
        post_sign_silent = False
        length_stitches = 0
        stitched_parts = []
        # Дедуп identical-вызовов хода: (tool, args-json) → artifact_path первого вызова.
        _turn_calls = {}
        try:
            from tools import sign_step as _sign_step
            _sign_step.reset_turn(session_path)
        except Exception:
            _sign_step = None
        stopped_by_user = False
        turn_prompt = user_text
        http_retries = 0
        error_logged = False
        key_gate_retried = False
        retry_waited = 0.0
        # «Держим сессию зубами»: при сбоях API не сдаёмся после пары попыток,
        # а ждём сервер с растущей паузой в пределах бюджета времени.
        retry_budget = sm.config.getint('Ollama', 'RetryBudgetSec', fallback=86400)
        max_backoff = sm.config.getint('Ollama', 'MaxRetryBackoffSec', fallback=60)
        retry_deadline = time.time() + max(30, retry_budget)

        def _try_hold(reason: str) -> bool:
            """Попытка удержания сессии при сбое API.

            Ошибка печатается один раз, а дальше рядом с ней растёт счётчик
            попыток и времени ожидания (в панели), без спама в лог.
            True — повторить запрос; False — бюджет исчерпан или Esc.
            """
            nonlocal http_retries, error_logged, retry_waited
            if getattr(app, "_stop_requested", False):
                return False
            if time.time() >= retry_deadline:
                return False
            http_retries += 1
            if not error_logged:
                _write_log(f"[red]{reason}[/red]")
                error_logged = True
            # Адаптивная пауза: первая попытка — сразу, дальше 2, 4, 8 … с
            # потолком max_backoff (не спамим сервер, но и не ждём зря).
            delay = 0 if http_retries <= 1 else \
                min(max_backoff, 2 ** min(http_retries - 1, 6))
            # Сообщаем UI, что ждём повтор: человек может ускорить (клик/Ctrl+R).
            app._force_retry = False
            app._retry_pending = True
            app._retry_deadline = time.time() + delay
            try:
                _update_stats(retries=http_retries, retry_wait=retry_waited,
                              status="Connecting...")
                end = time.time() + delay
                while time.time() < end:
                    if getattr(app, "_stop_requested", False):
                        return False
                    if getattr(app, "_force_retry", False):
                        app._force_retry = False
                        return True
                    time.sleep(0.2)
                    retry_waited += 0.2
                    _update_stats(retry_wait=retry_waited)
                return True
            finally:
                app._retry_pending = False

        changed_project_files = []
        start_time = time.time()
        elapsed = 0.0
        ttft_val = 0.0
        tps_val = 0.0
        full_response = ""
        full_thinking = ""
        metrics = {}
        thinking_tokens = 0
        response_tokens = 0
        streaming_tool_tokens = 0
        tool_tokens = 0

        # Новый запрос пользователя: отказ от dangerous mode из прошлого запроса
        # не переносим — иначе окно переключения больше никогда не появится.
        try:
            _call_from_thread(app.reset_turn_state)
        except Exception:
            app.dangerous_switch_denied = False

        # Фоновые веб-задачи: доставить завершившиеся в отсутствие модели и
        # напоминание о висящих — агент помнит, что он ждёт, и не считает их готовыми.
        _wj_note = _web_jobs_notice()
        if _wj_note:
            messages.append({"role": "user", "content": _wj_note})
            sm.update_context(session_path, "user", _wj_note)

        while True:
            # Esc между итерациями: не отправляем новый запрос, сразу выходим и
            # возвращаем UI в покой (ждём следующий вопрос).
            if getattr(app, "_stop_requested", False):
                stopped_by_user = True
                _finalize_turn("", "")
                break
            tool_rounds += 1
            # Раунд не виден в чате: пинк sign_step (sign_hidden) или раунд сразу
            # после подписи, когда ответ был отдан вместе со sign_step — тогда
            # текст раунда это лишь «эхо подписи», а не новый ответ.
            round_silent = sign_hidden or post_sign_silent
            post_sign_silent = False
            if tool_rounds > MAX_TOOL_ROUNDS_PER_TURN:
                if auto_recoveries >= MAX_AUTO_RECOVERIES_PER_TURN:
                    summary, _ = _ollama_summarize_and_reset_context(
                        sm, current_model, session_path, messages, current_ctx,
                        reason=f"max_tool_rounds_exceeded({MAX_TOOL_ROUNDS_PER_TURN})_recoveries_exhausted({MAX_AUTO_RECOVERIES_PER_TURN})",
                    )
                    sm.update_context(session_path, "assistant", summary)
                    messages.append({"role": "assistant", "content": summary})
                    break

                summary, artifact_path = _ollama_summarize_and_reset_context(
                    sm, current_model, session_path, messages, current_ctx,
                    reason=f"max_tool_rounds_exceeded({MAX_TOOL_ROUNDS_PER_TURN})",
                )
                auto_recoveries += 1
                tool_rounds = 0
                cont_user_content = sm.load_prompt(
                    session_path, "auto_continue",
                    LAST_USER_PROMPT=turn_prompt,
                    SESSION_PATH=session_path,
                    ARTIFACT_PATH=artifact_path,
                )
                cont_user = {"role": "user", "content": cont_user_content or f"Continue task: {turn_prompt[:100]}"}
                messages.append(cont_user)
                sm.update_context(session_path, "assistant", summary)
                sm.update_context(session_path, "user", cont_user["content"])
                continue

            if current_model and current_model not in _token_k_state["by_model"]:
                restore_token_calibration(os.path.join(session_path, "performance.log"), current_model)
            # Осознанная компакция: исполнить запрос агента ДО подготовки запроса —
            # карта пишется уже после неё, чтобы агент видел актуальную картину.
            _compact_summary, _compact_brief = apply_pending_compacts(
                sm, session_path, messages, current_ctx)
            if _compact_summary:
                if _compact_summary.startswith("COMPACT: ничего"):
                    _write_log(f"[dim]🗜 {_compact_summary}[/dim]")
                else:
                    _write_log(f"[dim]🗜 Память: сжато по запросу агента — {_compact_brief}. "
                               "Старое в артефакте, подниму по запросу.[/dim]")
                sm.update_context(session_path, "system", _compact_summary)
            write_context_map(session_path, messages, current_ctx)
            # Памятка о подключённых скиллах — живая, перезаписывается каждый раунд:
            # переживает overflow-reset (messages.clear()) и возвращается при resume.
            refresh_skills_active_note(messages, session_path)
            prepared = _prepare_messages_for_ollama(sm, session_path, messages, num_ctx=current_ctx)
            session_ctx_est = _estimate_messages_tokens(prepared)
            _cs = get_compression_stats()
            _d_tokens = _cs["tokens"] - _comp_base["tokens"]
            _d_trims = _cs["trims"] - _comp_base["trims"]
            _d_resets = _cs["resets"] - _comp_base["resets"]
            if _d_resets:
                _write_log(f"[dim]♻️ Память очищена целиком: −{_d_tokens} токенов "
                           f"({_compress_reason_ru(_cs.get('last_reason', ''))}); дневник сессии цел.[/dim]")
            elif _d_trims:
                _pct = int(session_ctx_est / current_ctx * 100) if current_ctx else 0
                _write_log(f"[dim]🧹 Память подожата: −{_d_tokens} токенов "
                           f"(было занято {_pct}%); старое в оглавлении, подниму по запросу.[/dim]")
            if _d_trims or _d_resets:
                _comp_base.update(_cs)
            _update_stats(session_ctx=session_ctx_est, session_ctx_max=current_ctx,
                          compressed_tokens=_cs["tokens"], compress_trims=_cs["trims"],
                          compress_resets=_cs["resets"],
                          compress_manual=_cs.get("manual", 0))

            tools = tm.get_tool_definitions()
            try:
                from tools.tools_catalog import enabled_tools
                _allowed = enabled_tools(session_path)
            except Exception:
                _allowed = None
            if _allowed is not None:
                tools_list = [
                    t for t in (tools.values() if isinstance(tools, dict) else (tools or []))
                    if ((t or {}).get("function") or {}).get("name") in _allowed
                ]
            else:
                tools_list = list(tools.values()) if isinstance(tools, dict) else (tools or [])

            payload = {
                "model": current_model,
                "messages": prepared,
                "stream": True,
                "logprobs": True,
                "options": {"num_ctx": current_ctx},
            }

            if current_model not in MODELS_NO_TOOLS:
                payload["tools"] = tools_list
            elif payload.get("tools") is not None:
                payload.pop("tools", None)
            apply_native_think(sm, payload)

            _update_stats(status="Generating...")

            try:
                # Аудио доставляется только через /v1 (input_audio) — перенаправляем ход
                # с аудио на openai-путь даже при backend=ollama.
                if is_openai_backend(sm) or _has_audio_message(prepared):
                    _do_request = lambda: chat_stream_request(  # noqa: E731
                        sm, payload, timeout=current_timeout,
                        verify_ssl=current_verify_ssl)
                else:
                    _do_request = lambda: requests.post(  # noqa: E731
                        current_ollama_chat_url, json=payload, stream=True,
                        timeout=current_timeout, verify=current_verify_ssl)
                # Запрос идёт в отдельном потоке: даже если сервер завис и не
                # отдал заголовки, Esc возвращает управление сразу.
                response, _req_status = _post_stream_interruptible(app, _do_request)
            except Exception as e:
                reason = (f"⚠ Ошибка связи с {server_label}: "
                          f"{type(e).__name__}: {e}")
                if _try_hold(reason):
                    continue
                try:
                    _call_from_thread(app.append_log, f"[red]{reason}[/red]")
                except Exception:
                    pass
                _persist_connection_failure(reason, user_text)
                break

            if _req_status == "stopped":
                # Esc во время ожидания ответа сервера — выходим немедленно.
                stopped_by_user = True
                _finalize_turn("", "")
                _update_stats(status="Ready")
                break

            if response.status_code != 200:
                error_msg = "Неизвестная ошибка сервера"
                error_text = ""
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        error_msg = _extract_api_error(data)
                        error_text = json.dumps(data, ensure_ascii=False, indent=2)
                    else:
                        error_text = str(data)
                except Exception:
                    try:
                        error_text = response.text[:500] if response.text else ""
                    except Exception:
                        error_text = ""

                if (
                    response.status_code == 400
                    and _ollama_error_indicates_no_tools(error_msg)
                    and payload.get("tools")
                ):
                    MODELS_NO_TOOLS.add(current_model)
                    _ensure_chat_only_system_message(messages)
                    payload.pop("tools", None)
                    _update_stats(status="Chat-only mode (no tools)")
                    continue

                # Проблема с API-ключом: показываем окошко ввода (со ссылкой на
                # выдачу ключа), сохраняем в персональный конфиг и повторяем ход.
                if is_auth_error(response.status_code, f"{error_msg} {error_text}") \
                        and not key_gate_retried:
                    key_gate_retried = True
                    _call_from_thread(
                        app.show_api_key_prompt,
                        server_label,
                        key_entry_url(sm),
                        str(error_msg)[:200],
                    )
                    app._api_key_event.wait(timeout=1800)
                    new_key = app._api_key_result
                    if new_key:
                        try:
                            saved_path = save_api_key(sm, new_key)
                            _call_from_thread(
                                app.append_log,
                                f"[green]API-ключ сохранён: {saved_path}[/green]")
                            continue
                        except Exception as e:
                            _call_from_thread(
                                app.append_log,
                                f"[red]Не удалось сохранить API-ключ: {e}[/red]")

                # Нестабильная связь не должна прерывать работу: пережидаемые
                # коды держим с растущей паузой в пределах бюджета времени.
                if _is_retryable_http(response.status_code) and _try_hold(
                        f"{server_label} вернул {response.status_code}: {error_msg}"):
                    continue

                formatted = _format_api_error(
                    response.status_code, error_msg, error_text, server_label)
                if not error_logged:
                    _write_log(f"[red]{formatted}[/red]")
                    error_logged = True
                # Ошибка всегда уходит в чат (форматированно) и в историю —
                # чтобы разбирать сбои по контексту, а не только в артефакте.
                try:
                    _call_from_thread(app.append_log, f"[red]{formatted}[/red]")
                except Exception:
                    pass

                ts = int(time.time())
                try:
                    sm.save_artifact(
                        session_path,
                        f"api_http_error_{response.status_code}_{ts}.txt",
                        (error_text or "")[:200_000],
                    )
                except Exception:
                    pass

                _persist_connection_failure(formatted, user_text)
                break

            full_response = ""
            full_thinking = ""
            tool_calls = []
            metrics = {}
            done_reason = ""
            start_time = time.time()
            first_token_time = None
            thinking_ended = False
            thinking_tokens = 0
            response_tokens = 0
            streaming_tool_text = ""
            streaming_tool_tokens = 0
            tool_tokens = 0
            prompt_eval_count = 0
            eval_count = 0
            last_chunk_time = time.time()
            _stream_buf.clear()
            _thinking_buf.clear()
            if not round_silent:
                _call_from_thread(app.start_assistant_turn)

            if user_text:
                sm.update_context(session_path, "user", user_text)

            stream_queue = queue.Queue()

            def _stream_reader():
                try:
                    for line in response.iter_lines():
                        stream_queue.put(("line", line))
                    stream_queue.put(("eof", None))
                except Exception as e:
                    stream_queue.put(("error", str(e)))

            reader_thread = threading.Thread(target=_stream_reader, daemon=True)
            reader_thread.start()

            # Независимый сторож: увидел Esc — сразу рвёт соединение с сервером,
            # не дожидаясь дренажа очереди. Это гарантия, что остановка сработает
            # даже при непрерывном потоке чанков.
            stop_watchdog = threading.Event()
            aborting_by_stop = threading.Event()

            def _watch_stop():
                while not stop_watchdog.is_set():
                    if getattr(app, "_stop_requested", False):
                        aborting_by_stop.set()
                        _abort_stream(response)
                        return
                    time.sleep(0.1)

            threading.Thread(target=_watch_stop, daemon=True).start()

            stream_done = False
            stream_error = None
            waiting_status_set = False

            total_tokens_counter = 0

            while not stream_done:
                while True:
                    # Esc должен рвать стрим НЕМЕДЛЕННО, даже если чанки идут
                    # непрерывным потоком и внутренняя очередь не пустеет.
                    # Раньше проверка была только между пачками — при плотном
                    # потоке она могла не срабатывать (Esc «не прерывал»).
                    if getattr(app, "_stop_requested", False):
                        _abort_stream(response)
                        stream_done = True
                        stopped_by_user = True
                        break
                    try:
                        kind, item = stream_queue.get_nowait()
                    except queue.Empty:
                        break

                    if kind == "eof":
                        stream_done = True
                        break
                    if kind == "error":
                        stream_error = item
                        stream_done = True
                        break

                    line = item
                    if not line:
                        continue

                    last_chunk_time = time.time()
                    _call_from_thread(app.report_chunk)
                    waiting_status_set = False

                    try:
                        chunk = json.loads(line.decode('utf-8', errors='replace'))
                    except json.JSONDecodeError:
                        continue

                    msg = chunk.get("message", {})

                    if "prompt_eval_count" in chunk:
                        prompt_eval_count = chunk.get("prompt_eval_count", 0)
                    if "eval_count" in chunk:
                        eval_count = chunk.get("eval_count", 0)

                    logprobs = chunk.get("logprobs")
                    if logprobs and isinstance(logprobs, list):
                        for lp in logprobs:
                            token = lp.get("token", "")
                            if token is None:
                                token = ""
                            streaming_tool_tokens += 1
                            if not msg.get("content") and not msg.get("thinking"):
                                if token:
                                    streaming_tool_text += str(token)
                                    if _tool_stream_has_payload(streaming_tool_text) and not round_silent:
                                        _append_chunk(tool_stream_json=streaming_tool_text)
                                if not waiting_status_set:
                                    _update_stats(status="Streaming Tool JSON...")
                                    waiting_status_set = True

                    if not first_token_time:
                        first_token_time = time.time()

                    total_tokens_counter += 1
                    if total_tokens_counter % 50 == 0:
                        try:
                            ollama_status = sm.get_ollama_status()
                            if ollama_status and "models" in ollama_status:
                                vram_parts = []
                                for ms in ollama_status["models"]:
                                    v = ms.get("size_vram", 0) / (1024**3)
                                    vram_parts.append(f"{ms['name']}: {v:.2f}GB")
                                _update_stats(vram=" | ".join(vram_parts) if vram_parts else "No models loaded")
                        except Exception:
                            pass

                    thought = msg.get("thinking", "")
                    if thought:
                        full_thinking += thought
                        thinking_tokens += 1
                        if not round_silent:
                            _stream_thought(thought)
                        sm.log_chunk(session_path, "thinking", thought)

                    token = msg.get("content", "")
                    if token:
                        if streaming_tool_text:
                            streaming_tool_text = ""

                        if not thinking_ended:
                            thinking_ended = True
                            thinking_stats = {
                                "total_tokens": thinking_tokens,
                                "thinking_tokens": thinking_tokens,
                                "response_tokens": 0,
                                "tps": thinking_tokens / (time.time() - first_token_time) if first_token_time else 0,
                                "ttft": first_token_time - start_time if first_token_time else 0,
                                "duration": time.time() - start_time,
                            }
                            sm.write_file_footer(session_path, "thinking.md", thinking_stats)

                        full_response += token
                        response_tokens += 1
                        if not round_silent:
                            _stream_chunk(content=token)
                        sm.log_chunk(session_path, "response", token)

                        if len(full_response) % 800 == 0 and _detect_repetition(full_response):
                            _abort_stream(response)
                            _write_log("[yellow]⚠ Обнаружен повтор в ответе модели — "
                                       "прерываю генерацию и запускаю восстановление…[/yellow]")
                            stream_done = True
                            break

                    tc_list = msg.get("tool_calls")
                    if tc_list:
                        tool_calls.extend(tc_list)

                    if chunk.get("done"):
                        done_reason = str(chunk.get("done_reason") or "")
                        metrics = {
                            "total_duration_ms": chunk.get("total_duration", 0) / 1_000_000,
                            "load_duration_ms": chunk.get("load_duration", 0) / 1_000_000,
                            "prompt_eval_count": chunk.get("prompt_eval_count", 0),
                            "eval_count": chunk.get("eval_count", 0),
                            "reasoning_tokens": chunk.get("reasoning_tokens", 0),
                            "eval_duration_ms": chunk.get("eval_duration", 0) / 1_000_000,
                        }
                        sm.log_chunk(session_path, "metrics", "", metrics=metrics)
                        stream_done = True
                        break

                if stream_done:
                    break

                if app._stop_requested:
                    _abort_stream(response)  # рвём сокет — модель прекращает генерацию
                    stream_done = True
                    stopped_by_user = True
                    break

                no_chunks_for = time.time() - last_chunk_time if last_chunk_time else 0.0
                if no_chunks_for >= 1.0 and not waiting_status_set:
                    _update_stats(status="Waiting for tool call...")
                    waiting_status_set = True
                elif no_chunks_for < 1.0 and app.stats_data.get("status") == "Waiting for tool call...":
                    _update_stats(status="Generating...")

                time.sleep(0.1)

                if app._stop_requested:
                    _abort_stream(response)  # рвём сокет — модель прекращает генерацию
                    _write_log("[yellow]⏹ Stopped by user[/yellow]")
                    stream_done = True
                    stopped_by_user = True
                    break

            if stream_error:
                _abort_stream(response)
                # Обрыв соединения с API в середине ответа. Держим сессию:
                # ждём сервер с растущей паузой; ошибка печатается один раз.
                if _try_hold(f"Обрыв потока {server_label}: {stream_error}"):
                    continue
                if full_response.strip() or full_thinking.strip():
                    sm.update_context(session_path, "assistant", full_response,
                                      thinking=full_thinking)
                    messages.append({"role": "assistant", "content": full_response})
                    _finalize_turn(full_response, full_thinking)
                else:
                    note = ("Соединение с API оборвалось до получения ответа. "
                            "Сессия не завершена — продолжай с того же места.")
                    sm.update_context(session_path, "system", note)
                    messages.append({"role": "system", "content": note})
                    _finalize_turn("", "")
                break

            # Успешный стрим — сбрасываем счётчики сетевых сбоев хода.
            http_retries = 0
            error_logged = False
            retry_waited = 0.0
            retry_deadline = time.time() + max(30, retry_budget)
            _update_stats(retries=0, retry_wait=0.0)

            elapsed = time.time() - start_time
            ttft_val = first_token_time - start_time if first_token_time else elapsed
            tps_val = (thinking_tokens + response_tokens + streaming_tool_tokens) / (time.time() - first_token_time) if first_token_time and (time.time() - first_token_time) > 0 else 0
            last_req_ctx = prompt_eval_count + eval_count
            set_context_pressure(last_req_ctx / current_ctx if current_ctx else 0.0,
                                 used=last_req_ctx, max_ctx=current_ctx)
            if prompt_eval_count:
                calibrate_token_estimator(
                    current_model, prompt_eval_count, prepared,
                    persist_path=os.path.join(session_path, "performance.log"),
                )
            # Тихий срез для калибратора токенов: объёмы текста ↔ точные usage.
            try:
                _calib_roles = {}
                for _m in prepared or []:
                    _r = str(_m.get("role") or "?")
                    _c = _m.get("content")
                    _n = len(_c) if isinstance(_c, str) else 0
                    if _m.get("tool_calls"):
                        try:
                            _n += len(json.dumps(_m["tool_calls"], ensure_ascii=False))
                        except Exception:
                            pass
                    _calib_roles[_r] = _calib_roles.get(_r, 0) + _n
                token_calibrator.record_api_call(
                    deploy=token_calibrator.deploy_fingerprint(current_model, server_label),
                    kind="tool_round" if any(str(m.get("role")) == "tool"
                                             for m in (prepared or [])) else "plain",
                    roles=_calib_roles,
                    prompt_tokens=prompt_eval_count,
                    response_chars=len(full_response),
                    thinking_chars=len(full_thinking),
                    tool_chars=len(streaming_tool_text),
                    completion_tokens=eval_count,
                    reasoning_tokens=int(metrics.get("reasoning_tokens") or 0),
                )
                net_meter.add_usage(prompt_eval_count, eval_count)
            except Exception:
                pass

            _update_stats(
                status="Processing tool calls..." if tool_calls else "Done",
                elapsed=elapsed,
                ttft=f"{ttft_val:.2f}s",
                thinking_tokens=thinking_tokens,
                response_tokens=response_tokens,
                stream_tool_tokens=streaming_tool_tokens,
                final_tool_tokens=tool_tokens,
                tps=tps_val,
                session_ctx=session_ctx_est,
                last_req_ctx=last_req_ctx,
                last_req_ctx_max=current_ctx,
            )

            _flush_thinking_buf()
            _flush_stream_buf()

            if round_silent and not tool_calls:
                # Тихий раунд (пинк sign_step или эхо после подписи): текст
                # в чат не показываем, ход завершён.
                break

            if (not tool_calls) and (not full_response.strip()) and full_thinking.strip():
                if auto_recoveries >= MAX_AUTO_RECOVERIES_PER_TURN:
                    cont_user_content = sm.load_prompt(
                        session_path, "auto_continue_final",
                        LAST_USER_PROMPT=turn_prompt,
                        SESSION_PATH=session_path,
                    )
                    cont_user = {"role": "user", "content": cont_user_content or f"Formulate final answer for: {turn_prompt[:100]}"}
                    messages.append(cont_user)
                    sm.update_context(session_path, "user", cont_user["content"])
                    continue
                auto_recoveries += 1
                tool_rounds = 0
                cont_user_content = sm.load_prompt(
                    session_path, "auto_continue_final",
                    LAST_USER_PROMPT=turn_prompt,
                    SESSION_PATH=session_path,
                )
                cont_user = {"role": "user", "content": cont_user_content or f"Formulate final answer for: {turn_prompt[:100]}"}
                messages.append(cont_user)
                sm.update_context(session_path, "user", cont_user["content"])
                continue

            # Полностью пустое завершение: модель не выдала ни текста, ни
            # reasoning, ни tool_call (бэкенд сгенерировал токены, но до клиента
            # ничего не дошло). Раньше это молча сохранялось как финальный ответ
            # и гасило ход. Теперь — видимая пометка и повтор (ограниченно).
            if _is_empty_completion(full_response, full_thinking, tool_calls):
                if empty_retries >= MAX_EMPTY_RETRIES_PER_TURN:
                    note = (f"Модель {empty_retries + 1}-й раз подряд вернула пустой "
                            f"ответ (eval_tokens={metrics.get('eval_count', 0)}). "
                            "Останавливаюсь и жду следующее сообщение.")
                    _write_log(f"[red]⚠ {note}[/red]")
                    sm.update_context(session_path, "system", note)
                    messages.append({"role": "system", "content": note})
                    _finalize_turn("", "")
                    break
                empty_retries += 1
                tool_rounds = 0
                _write_log(f"[yellow]⚠ Пустой ответ от модели — повторяю запрос "
                           f"({empty_retries}/{MAX_EMPTY_RETRIES_PER_TURN})…[/yellow]")
                sm.update_context(
                    session_path, "system",
                    f"Пустое завершение модели (eval_tokens={metrics.get('eval_count', 0)}). "
                    f"Повтор {empty_retries}/{MAX_EMPTY_RETRIES_PER_TURN}.")
                cont_user_content = sm.load_prompt(
                    session_path, "auto_continue_final",
                    LAST_USER_PROMPT=turn_prompt,
                    SESSION_PATH=session_path,
                )
                cont_user = {"role": "user",
                             "content": cont_user_content or f"Formulate final answer for: {turn_prompt[:100]}"}
                messages.append(cont_user)
                sm.update_context(session_path, "user", cont_user["content"])
                continue
            else:
                # Нормальный ответ (в т.ч. tool-call-only) — счётчик сбрасываем.
                empty_retries = 0

            if _detect_repetition(full_response):
                sm.update_context(session_path, "system", "Repetition detected, auto-continuing")
                if auto_recoveries >= MAX_AUTO_RECOVERIES_PER_TURN:
                    summary, _ = _ollama_summarize_and_reset_context(
                        sm, current_model, session_path, messages, current_ctx,
                        reason=f"repetition_detected_recoveries_exhausted({MAX_AUTO_RECOVERIES_PER_TURN})",
                    )
                    sm.update_context(session_path, "assistant", summary)
                    messages.append({"role": "assistant", "content": summary})
                    break

                summary, artifact_path = _ollama_summarize_and_reset_context(
                    sm, current_model, session_path, messages, current_ctx,
                    reason="repetition_detected",
                )
                auto_recoveries += 1
                tool_rounds = 0
                cont_user_content = sm.load_prompt(
                    session_path, "auto_continue",
                    LAST_USER_PROMPT=turn_prompt,
                    SESSION_PATH=session_path,
                    ARTIFACT_PATH=artifact_path,
                )
                cont_user = {"role": "user", "content": cont_user_content or f"Continue task: {turn_prompt[:100]}"}
                messages.append(cont_user)
                sm.update_context(session_path, "assistant", summary)
                sm.update_context(session_path, "user", cont_user["content"])
                _finalize_turn(full_response, full_thinking)
                continue

            _flush_thinking_buf()
            _flush_stream_buf()

            ctx_used = metrics.get("prompt_eval_count", 0) + metrics.get("eval_count", 0)
            if current_ctx > 0 and ctx_used >= int(current_ctx * HARD_CTX_PCT):
                if auto_recoveries >= MAX_AUTO_RECOVERIES_PER_TURN:
                    summary, _ = _ollama_summarize_and_reset_context(
                        sm, current_model, session_path, messages, current_ctx,
                        reason=f"hard_ctx_threshold_reached({ctx_used}/{current_ctx})_recoveries_exhausted({MAX_AUTO_RECOVERIES_PER_TURN})",
                    )
                    sm.update_context(session_path, "assistant", summary)
                    messages.append({"role": "assistant", "content": summary})
                    break

                summary, artifact_path = _ollama_summarize_and_reset_context(
                    sm, current_model, session_path, messages, current_ctx,
                    reason=f"hard_ctx_threshold_reached({ctx_used}/{current_ctx})",
                )
                auto_recoveries += 1
                tool_rounds = 0
                cont_user_content = sm.load_prompt(
                    session_path, "auto_continue",
                    LAST_USER_PROMPT=turn_prompt,
                    SESSION_PATH=session_path,
                    ARTIFACT_PATH=artifact_path,
                )
                cont_user = {"role": "user", "content": cont_user_content or f"Continue task: {turn_prompt[:100]}"}
                messages.append(cont_user)
                sm.update_context(session_path, "assistant", summary)
                sm.update_context(session_path, "user", cont_user["content"])
                continue

            if current_model in MODELS_NO_TOOLS and tool_calls:
                tool_calls = []

            if stopped_by_user:
                sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)
                messages.append({"role": "assistant", "content": full_response})
                if not round_silent:
                    _finalize_turn(full_response, full_thinking)
                break

            if not tool_calls:
                # Добивка обрыва по finish_reason=length (этап 7): обрубок сохранён,
                # скрытый досыл «продолжи с места обрыва», хвост приклеится при финале
                if (done_reason == "length" and full_response.strip()
                        and length_stitches < 2 and not stopped_by_user):
                    length_stitches += 1
                    stitched_parts.append(full_response)
                    messages.append({"role": "assistant", "content": full_response})
                    cont = ("Продолжи строго с места обрыва: без повторов уже сказанного, "
                            "без нового начала, сразу с следующего слова/строки.")
                    messages.append({"role": "user", "content": cont})
                    # Обрубки и служебный досыл — только в messages (API-история);
                    # в context.json идёт единый сшитый ответ, не фрагменты.
                    full_response = ""
                    full_thinking = ""
                    continue
                if stitched_parts:
                    full_response = _stitch_response(stitched_parts + [full_response])
                    stitched_parts = []
                sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)
                messages.append({"role": "assistant", "content": full_response})
                _finalize_turn(full_response, full_thinking)

                # sign_step (этап 6): нет подписи за рабочий ход — один пинк,
                # дальше смириться (провал форсинга стоит нулю — механическая строка)
                if (_sign_step is not None and sign_nudges < 1 and tool_rounds > 0
                        and current_model not in MODELS_NO_TOOLS
                        and not _sign_step.has_signature(session_path)):
                    sign_nudges += 1
                    sign_hidden = True
                    nudge = ("Перед завершением хода вызови инструмент sign_step: "
                             "goal (что делал за ход, ≤15 слов), done (что сделано, ≤15 слов), "
                             "status (progress|blocked|decision|answered), "
                             "entities — только что реально встречалось в ходе (пути, URL, имена; ≤6). "
                             "В следующий раз отмечай сделанное по ходу (sign_step(done=…) после "
                             "каждого значимого шага) — так прогресс не теряется. "
                             "Ничего больше не вызывай и не повторяй ответ.")
                    messages.append({"role": "user", "content": nudge})
                    # Пинк — служебный: в messages он есть (модель его видит),
                    # в context.json его нет — иначе session_memory показывает
                    # фантомный «ход» с текстом пинка вместо реальных ходов.
                    full_response = ""
                    full_thinking = ""
                    continue

                # --- РЕЖИМ КОРРЕКТОРА (--proofread) ---
                if proofread and proofreader_fn and proof_rounds < MAX_PROOFREAD_ROUNDS:
                    proof_rounds += 1
                    _update_stats(status="Proofreader is thinking...")
                    _call_from_thread(app._add_static,
                                      "[bold magenta]>>> ПРОВЕРКА КОРРЕКТОРОМ...[/bold magenta]")
                    feedback, verdict_path = "", ""
                    try:
                        feedback, verdict_path = proofreader_fn(
                            current_model, session_path, current_ctx, messages)
                    except Exception as e:
                        feedback = f"Ошибка корректора: {e}"
                        verdict_path = ""
                    _call_from_thread(app._add_static,
                                      "[bold magenta]ЗАКЛЮЧЕНИЕ КОРРЕКТОРА:[/bold magenta]")
                    try:
                        _call_from_thread(app._add_static, app._rich_escape(feedback or ""))
                    except Exception:
                        pass
                    fb_low = (feedback or "").lower()
                    exit_keywords = ["замечаний нет", "все верно", "исправлено",
                                     "проверка завершена", "принято",
                                     "замечаний не обнаружено", "все в порядке"]
                    if any(kw in fb_low for kw in exit_keywords):
                        _call_from_thread(app._add_static,
                                          "[bold green]Корректор одобрил работу.[/bold green]")
                        break
                    turn_prompt = (
                        "КОРРЕКТОР ОБНАРУЖИЛ ОШИБКИ/НЕДОЧЕТЫ.\n"
                        + (f"Полный текст замечаний сохранен в файле: {verdict_path}\n\n"
                           if verdict_path else "")
                        + f"Краткое резюме:\n{(feedback or '')[:2000]}\n\n"
                        "Исправь свою работу в соответствии с этими замечаниями."
                        + (" Обязательно прочитай файл вердикта, если резюме обрезано."
                           if verdict_path else "")
                    )
                    messages.append({"role": "user", "content": turn_prompt})
                    sm.update_context(session_path, "user", turn_prompt)
                    full_response = ""
                    full_thinking = ""
                    continue

                break

            _update_stats(status="Tool-mode parsing...")
            streaming_tool_text = ""
            _update_stats(status="Calling Tools...")

            messages.append({"role": "assistant", "content": full_response, "tool_calls": tool_calls})
            sm.update_context(session_path, "assistant", full_response, thinking=full_thinking, tool_calls=tool_calls)

            if not round_silent:
                _finalize_turn(full_response, full_thinking, tool_calls)

            for tc in tool_calls:
                # Esc до старта инструмента: не выполняем его вовсе. Закрываем
                # оставшиеся tool_calls aborted-результатами, чтобы в истории не
                # осталось «висячих» вызовов без ответа.
                if getattr(app, "_stop_requested", False):
                    for skip_tc in tool_calls[tool_calls.index(tc):]:
                        skip_func = skip_tc.get("function", {})
                        skip_id = skip_tc.get("id", "")
                        skip_name = skip_func.get("name", "unknown")
                        skip_msg = "ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ. Инструмент не выполнен."
                        messages.append({"role": "tool", "tool_call_id": skip_id,
                                         "name": skip_name, "content": skip_msg})
                        sm.update_context(session_path, "tool", skip_msg,
                                          tool_call_id=skip_id, name=skip_name)
                        sm.log_tool_call(session_path, skip_name, {}, skip_msg,
                                         status="aborted", call_id=skip_id)
                    break
                func = tc.get("function", {})
                tool_name = func.get("name", "unknown")
                tc_id = tc.get("id", "")
                try:
                    tool_args = json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else func.get("arguments", {})
                except Exception:
                    tool_args = {}

                _add_tool(tool_name, json.dumps(tool_args, ensure_ascii=False)[:60], status="running")

                sm.log_tool_call(session_path, tool_name, tool_args, "STARTED", status="running", call_id=tc_id)

                if _sign_step is not None and tool_name != "sign_step":
                    try:
                        _sign_step.observe(session_path, [tool_name] + [str(v) for v in (tool_args or {}).values()])
                    except Exception:
                        pass

                progress_callback = None
                if tool_name in ("curl", "web", "web_search", "open_url", "web_extract"):
                    progress_callback = _tool_progress(tool_name)

                effective_session_path = session_path
                if tool_name == "code_editor" and isinstance(tool_args, dict):
                    raw_path = tool_args.get("path", "")
                    if raw_path:
                        tool_args["path"] = resolve_session_path(raw_path, session_path)

                action = tool_args.get("action") if isinstance(tool_args, dict) else None
                # Опасные действия: shell_exec (run/send/...), запись code_editor,
                # мутации file_system и запись curl в файл.
                is_dangerous_tool = (
                    (tool_name == "shell_exec" and (action or "run") in DANGEROUS_SHELL_ACTIONS)
                    or (tool_name == "code_editor" and editor_action_of(tool_args) in DANGEROUS_EDITOR_ACTIONS)
                    or (tool_name == "file_system" and action in DANGEROUS_FS_ACTIONS)
                    or (tool_name in ("curl", "web") and bool(tool_args.get("output_path")))
                    or (tool_name == "web" and action == "download")
                )
                if is_dangerous_tool:
                    # В простом режиме внутри сессии писать можно без dangerous mode;
                    # выход за пределы сессии требует переключения режима.
                    needs_prompt = tm.dangerous_mode or not allowed_in_session(
                        tool_name, tool_args, session_path)
                    kind = "confirm" if tm.dangerous_mode else "switch"
                    # Если пользователь уже отказался переключаться — не спрашиваем
                    # повторно (иначе агент будет «долбить» одним и тем же запросом).
                    switch_denied = (kind == "switch"
                                     and getattr(app, "dangerous_switch_denied", False))
                    confirmed = False
                    if needs_prompt and not switch_denied:
                        _call_from_thread(
                            app.show_confirmation_prompt,
                            tool_name,
                            json.dumps(tool_args, ensure_ascii=False),
                            "",
                            kind,
                        )
                        app._confirmation_event.wait(timeout=300)
                        confirmed = app._confirmation_result
                    if needs_prompt and not confirmed:
                        if kind == "switch":
                            result = (
                                "ОТКАЗАНО ПОЛЬЗОВАТЕЛЕМ. Пользователь запретил повышение прав "
                                "(dangerous mode) на эту сессию: выполнение кода и внешних "
                                "бинарников недоступно. Все навыки, требующие выполнения кода "
                                "(requires.bins / CLI), для этой задачи НЕРЕЛЕВАНТНЫ — их "
                                "инструкции, правила, флаги и примеры применять НЕЛЬЗЯ. "
                                "Не повторяй это действие и не запрашивай dangerous mode снова. "
                                "Работай только безопасными инструментами; если задача без "
                                "выполнения кода невыполнима — прямо сообщи об этом."
                            )
                        else:
                            reason = (getattr(app, "_confirmation_reason", "")
                                      or "пользователь отклонил выполнение.")
                            result = f"ОТКАЗАНО ПОЛЬЗОВАТЕЛЕМ. Причина: {reason}"
                        artifact_path = ""
                        compact_msg = _compact_tool_message(tool_name, tool_args, result, "")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": tool_name,
                            "content": compact_msg
                        })
                        sm.update_context(session_path, "tool", compact_msg,
                                          tool_call_id=tc_id, name=tool_name)
                        sm.log_tool_call(session_path, tool_name, tool_args, result,
                                         status="aborted", call_id=tc_id)
                        _update_tool(tool_name, status="aborted", size_kb=0)
                        _append_tool_result(tool_name, compact_msg[:500])
                        continue
                    if kind == "switch" and confirmed:
                        # Пользователь разрешил переключение — включаем dangerous mode
                        # и выполняем действие в этом же ходе.
                        tm.dangerous_mode = True
                        os.environ["BOTINOK_DANGEROUS"] = "1"
                        try:
                            _call_from_thread(app.set_model_info, _current_model, dangerous=True)
                        except Exception:
                            pass
                        _write_log("[yellow]⚠️ Dangerous mode: ON (по запросу инструмента)[/yellow]")

                _dk = None
                if tool_name in DEDUP_TOOLS:
                    try:
                        _dk = (tool_name, json.dumps(tool_args, sort_keys=True,
                                                     ensure_ascii=False))
                    except (TypeError, ValueError):
                        _dk = None
                memo = _catalog_memo_check(session_path, tool_name, tool_args)
                if memo:
                    tool_result = memo
                elif _dk and _dk in _turn_calls:
                    tool_result = (
                        f"DEDUP_SAME_CALL: точно такой же {tool_name} уже выполнялся "
                        f"в этом ходе (артефакт: {_turn_calls[_dk]}). Повтор тратит "
                        "контекст впустую — работай с полученным; нужны свежие данные "
                        "— измени аргументы."
                    )
                else:
                    tool_result = tm.call_tool(
                        tool_name,
                        tool_args,
                        session_path=effective_session_path,
                        progress_callback=progress_callback,
                    )
                    _catalog_memo_store(session_path, tool_name, tool_args, tool_result, sm)

                # Esc во время работы инструмента: процесс(ы) убиты, фиксируем
                # прерывание и прекращаем ход, ничего не «додумывая».
                if getattr(app, "_stop_requested", False):
                    result = ("ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ. Действие и все запущенные "
                              "им процессы прерваны.")
                    compact_msg = _compact_tool_message(tool_name, tool_args, result, "")
                    messages.append({"role": "tool", "tool_call_id": tc_id,
                                     "name": tool_name, "content": compact_msg})
                    sm.update_context(session_path, "tool", compact_msg,
                                      tool_call_id=tc_id, name=tool_name)
                    sm.log_tool_call(session_path, tool_name, tool_args, result,
                                     status="aborted", call_id=tc_id)
                    _update_tool(tool_name, status="aborted", size_kb=0)
                    _append_tool_result(tool_name, compact_msg[:500])
                    break

                if tool_name == "code_editor":
                    try:
                        parsed = json.loads(str(tool_result))
                        if isinstance(parsed, dict) and parsed.get("changed") and parsed.get("path"):
                            changed_project_files.append(str(parsed.get("path")))
                    except Exception:
                        pass

                res_str = "" if tool_result is None else str(tool_result)
                size_kb = len(res_str.encode('utf-8', errors='ignore')) / 1024

                artifact_name = f"tool_{tool_name}_{tc_id or int(time.time())}.txt"
                try:
                    artifact_path = sm.save_artifact(session_path, artifact_name, res_str[:200_000])
                except Exception:
                    artifact_path = f"./artifacts/{artifact_name}"
                if _dk:
                    _turn_calls.setdefault(_dk, artifact_path)

                compact_msg = _compact_tool_message(tool_name, tool_args, tool_result, artifact_path)
                # Подсказка о цене блока: дорогой результат — предложить агенту
                # осознанно освободить его, когда он отработан (кроме текущего хода).
                _blk_est = _estimate_tokens(compact_msg)
                if current_ctx and _blk_est >= COMPACT_HINT_PCT * current_ctx:
                    compact_msg += (
                        f"\ncontext_cost: этот результат ≈{_blk_est} токенов "
                        f"({int(_blk_est / current_ctx * 100)}% от num_ctx). Когда он "
                        "отработан — не держи его: session_memory action=context_map покажет, "
                        "кто съел контекст, action=compact blocks=\"…\" освободит старые блоки "
                        "(текущий ход с этого хода и доступен для сжатия в следующем)."
                    )
                # Чекпоинты sign_step: индикатор важности — заполненность контекста
                # (чем больше сожжено, тем больнее терять непрописанный прогресс).
                _ctx_ratio = _pressure_state.get("ratio", 0.0)
                if (_sign_step is not None and not _sign_reminded
                        and _ctx_ratio >= SIGN_CHECKPOINT_REMINDER_PCT
                        and current_model not in MODELS_NO_TOOLS
                        and not _sign_step.has_signature(session_path)):
                    _sign_reminded = True
                    compact_msg += (
                        f"\ncheckpoint_reminder: контекст заполнен на ~{int(_ctx_ratio * 100)}%, "
                        "а прогресс хода ещё не отмечен — при сбросе он потеряется. "
                        "Сделал значимое — sign_step(done=…) коротко зафиксируй "
                        "и продолжай без паузы."
                    )

                res_tokens = _estimate_tokens(compact_msg)
                tool_tokens += res_tokens

                sm.log_tool_call(session_path, tool_name, tool_args, tool_result, status="completed", call_id=tc_id)

                if tool_name == "skills":
                    record_skill_activation(session_path, tool_name, tool_args, res_str)
                if tool_name == "skills" and _wiki_mode_activation(tool_args, res_str):
                    if _append_system_once(messages, WIKI_MODE_NOTE):
                        # в архив — ровно один раз на сессию: после каждого
                        # сброса нота возвращалась в messages и дублировалась
                        # в context.json десятками копий
                        if session_path not in _wiki_note_persisted:
                            _wiki_note_persisted.add(session_path)
                            sm.update_context(session_path, "system", WIKI_MODE_NOTE)
                        _write_log("[dim]📚 Режим вики включён: скилл llm-wiki активен до конца сессии.[/dim]")

                media_extra = None
                if tool_name == "vision" and isinstance(tool_result, dict) and tool_result.get("image_data"):
                    vision_prompt = tool_result.get("prompt", "Опиши что ты видишь на этом изображении")
                    media_ref = sm.save_media(session_path, tool_result["image_data"], kind="image")
                    messages.append({
                        "role": "user",
                        "content": vision_prompt,
                        "images": [tool_result["image_data"]]
                    })
                    media_extra = {
                        "media_kind": "image",
                        "images": [{"media_ref": media_ref}] if media_ref else [{"media_dropped": True}],
                    }
                elif tool_name == "audio" and isinstance(tool_result, dict) and tool_result.get("audio_data"):
                    audio_prompt = tool_result.get("prompt", "Опиши, что ты слышишь в этом аудио")
                    mime = tool_result.get("mime_type", "audio/wav")
                    media_ref = sm.save_media(session_path, tool_result["audio_data"], mime=mime, kind="audio")
                    messages.append({
                        "role": "user",
                        "content": audio_prompt,
                        "audios": [tool_result["audio_data"]],
                        "media_kind": "audio",
                        "mime_type": mime,
                    })
                    media_extra = {
                        "media_kind": "audio",
                        "mime_type": mime,
                        "audios": [{"media_ref": media_ref}] if media_ref else [{"media_dropped": True}],
                    }
                else:
                    tool_message = {
                        "role": "tool",
                        "content": compact_msg,
                    }
                    if tc_id:
                        tool_message["tool_call_id"] = tc_id
                    if tool_name:
                        tool_message["name"] = tool_name
                    messages.append(tool_message)

                sm.update_context(session_path, "tool", compact_msg,
                                  tool_call_id=tc_id, name=tool_name)
                if media_extra:
                    prompt = (tool_result.get("prompt") or "").strip() if isinstance(tool_result, dict) else ""
                    sm.update_context(session_path, "user", prompt or f"[{tool_name} media]",
                                      extra=media_extra)

                sm.log_step(session_path, f"tool_{tool_name}_{tc_id or int(time.time())}",
                            tc, {"result": tool_result}, {})

                _update_tool(tool_name, status="completed", size_kb=size_kb)
                _append_tool_result(tool_name, compact_msg[:500])

            if sign_hidden and _sign_step is not None and _sign_step.has_signature(session_path):
                # Подпись получена — ход завершён, ответ уже показан выше.
                break

            if any((tc.get("function") or {}).get("name") == "sign_step" for tc in tool_calls) \
                    and full_response.strip():
                # Модель отдала ответ вместе со sign_step — следующий финальный
                # текст будет лишь эхом подписи, его не показываем.
                post_sign_silent = True

            # Если инструмент был прерван пользователем — не запускаем новый ход,
            # возвращаем UI в покой и ждём следующий вопрос.
            if getattr(app, "_stop_requested", False):
                _finalize_turn("", "")
                _update_stats(status="Ready")
                break

            # Мысли пользователя, накопленные во время работы: отдаём их модели
            # ОДНИМ блоком на границе раунда, не прерывая генерацию. Никаких
            # указаний «прерви/продолжай» — модель решает сама по контексту.
            try:
                _thoughts = _call_from_thread_result(app.take_queued_thoughts) or ""
            except Exception:
                _thoughts = ""
            if _thoughts:
                _wrapped = f"(во время работы)\n{_thoughts}"
                messages.append({"role": "user", "content": _wrapped})
                sm.update_context(session_path, "user", _wrapped)
                _call_from_thread(app.deliver_thought_block, _thoughts)
                _write_log("[dim]💭 Мысли переданы модели[/dim]")

            # Фоновые веб-задачи: инкрементные ✅/❌ о завершившихся за этот
            # раунд + напоминание о ещё идущих (модель их не «теряет»).
            _wj_note = _web_jobs_notice()
            if _wj_note:
                messages.append({"role": "user", "content": _wj_note})
                sm.update_context(session_path, "user", _wj_note)
                _write_log("[dim]🌐 Уведомление о веб-задачах передано модели[/dim]")

            _append_turn_guidance(resume_turn)

            _update_stats(status="Resuming generation...")

            user_text = ""
            continue

        session_ctx_est = _estimate_messages_tokens(messages)
        _refresh_vram()
        _update_stats(session_ctx=session_ctx_est, status="Ready")
        _flush_thinking_buf()
        _flush_stream_buf()

        final_stats = {
            "total_tokens": thinking_tokens + response_tokens + tool_tokens + streaming_tool_tokens,
            "thinking_tokens": thinking_tokens,
            "response_tokens": response_tokens,
            "tps": tps_val,
            "ttft": ttft_val,
            "duration": time.time() - start_time,
        }
        sm.log_step(session_path, f"step_textual_{int(time.time())}_{uuid.uuid4().hex[:6]}",
                    {}, {"response": full_response, "thinking": full_thinking}, metrics)

        # Канонический снапшот входного массива сообщений — источник для
        # точного восстановления сессии (см. SessionManager.load_messages_snapshot).
        sm.save_messages_snapshot(session_path, messages, model=model, num_ctx=num_ctx)

        stream_active.clear()
        _call_from_thread(app.flush_tool_buffer)

    _current_model = model
    _current_ctx = num_ctx
    _last_user_text = ""
    _ollama_chat_url = ollama_chat_url
    _verify_ssl = verify_ssl
    _request_timeout = request_timeout

    def _get_ollama_models():
        # OpenAI-совместимый бэкенд: список берём из /v1/models с Bearer-ключом.
        # Не-LLM (эмбеддинги и пр.) отсекаем по классификации из кэша шапки.
        if is_openai_backend(sm):
            try:
                from core.openai_compat import _api_url, _api_headers
                r = requests.get(_api_url(sm, '/v1/models'),
                                 headers=_api_headers(sm), timeout=5,
                                 verify=_verify_ssl)
                if r.status_code == 200:
                    data = r.json()
                    names = [m.get("id") or m.get("name")
                             for m in data.get("data", [])
                             if m.get("id") or m.get("name")]
                    try:
                        _b = 'openai'
                        _u = sm.config.get('Ollama', 'BaseUrl', fallback='')
                        ent = load_cache_entry(
                            sm, f"models|{_b}|{_u.rstrip('/')}", ttl=24 * 3600)
                        nonchat = {m.get('id') for m in (ent or {}).get('models') or []
                                   if m.get('chat') is False}
                        names = [n for n in names if n not in nonchat] or names
                    except Exception:
                        pass
                    return names
            except Exception:
                pass
            return []
        try:
            url = ollama_base_url.rstrip("/") + "/api/tags"
            r = requests.get(url, timeout=5, verify=_verify_ssl)
            if r.status_code == 200:
                data = r.json()
                return [m["name"] for m in data.get("models", [])
                        if not (m.get("capabilities") and
                                "completion" not in m.get("capabilities"))]
        except Exception:
            pass
        return []

    def _handle_slash_command(cmd: str):
        nonlocal _current_model, _current_ctx, _ollama_chat_url
        parts = cmd.strip().split()
        command = parts[0].lower()

        if command == "/help":
            _write_log("[bold cyan]📋 Доступные команды:[/bold cyan]")
            _write_log("  [green]/model <name>[/green]  — сменить модель (например /model qwen3.5:9b)")
            _write_log("  [green]/models[/green]         — список доступных моделей Ollama")
            _write_log("  [green]/ctx <n>[/green]         — сменить размер контекста (например /ctx 32768)")
            _write_log("  [green]/clear[/green]          — очистить экран")
            _write_log("  [green]/dangerous[/green]      — переключить опасный режим")
            _write_log("  [green]/retry[/green]          — повторить последний запрос")
            _write_log("  [green]/vram[/green]           — показать статус VRAM")
            _write_log("  [green]exit[/green]            — выход")
            _write_log("")

        elif command == "/models":
            _write_log("[bold cyan]🔍 Получаю список моделей...[/bold cyan]")
            models = _get_ollama_models()
            if models:
                _write_log("[bold cyan]📦 Доступные модели:[/bold cyan]")
                for m in models:
                    tag = "[green]●[/green]" if _current_model == m else "[dim]○[/dim]"
                    _write_log(f"  {tag} {m}")
            else:
                _write_log("[red]Не удалось получить список моделей[/red]")

        elif command == "/model":
            if len(parts) < 2:
                _write_log(f"[yellow]Текущая модель: {_current_model}[/yellow]")
                _write_log("[dim]Использование: /model <имя_модели>[/dim]")
            else:
                new_model = parts[1]
                _current_model = new_model
                sm.config.set('Ollama', 'DefaultModel', new_model)
                with open(sm.config_path, 'w') as cf:
                    sm.config.write(cf)
                _call_from_thread(app.set_model_info, new_model, dangerous=tm.dangerous_mode)
                _write_log(f"[green]✅ Модель сменена на: {new_model}[/green]")
                _write_log("[dim]Новая модель будет использована в следующем запросе.[/dim]")

        elif command == "/ctx":
            if len(parts) < 2:
                _write_log(f"[yellow]Текущий контекст: {_current_ctx}[/yellow]")
            else:
                try:
                    new_ctx = int(parts[1])
                    if new_ctx < 1024:
                        _write_log("[red]Минимальный контекст: 1024[/red]")
                    else:
                        _current_ctx = new_ctx
                        sm.config.set('Ollama', 'DefaultContext', str(new_ctx))
                        with open(sm.config_path, 'w') as cf:
                            sm.config.write(cf)
                        _update_stats(session_ctx_max=new_ctx)
                        _write_log(f"[green]✅ Контекст сменён на: {new_ctx}[/green]")
                except ValueError:
                    _write_log("[red]Неверное число[/red]")

        elif command == "/clear":
            app.clear_log()

        elif command == "/dangerous":
            current = os.environ.get("BOTINOK_DANGEROUS", "0") == "1"
            new_val = "0" if current else "1"
            os.environ["BOTINOK_DANGEROUS"] = new_val
            tm.dangerous_mode = not current
            status = "[green]ON[/green]" if not current else "[red]OFF[/red]"
            _call_from_thread(app.set_model_info, _current_model, dangerous=tm.dangerous_mode)
            _write_log(f"[yellow]⚠️ Dangerous mode: {status}[/yellow]")

        elif command == "/vram":
            _write_log("[bold cyan]🔍 Проверяю VRAM...[/bold cyan]")
            try:
                status = sm.get_ollama_status()
                if status and "models" in status:
                    for m in status["models"]:
                        vram = m.get("size_vram", 0) / (1024**3)
                        _write_log(f"  [cyan]{m['name']}[/cyan] — VRAM: [yellow]{vram:.2f}GB[/yellow]")
                else:
                    _write_log("[dim]Нет загруженных моделей[/dim]")
            except Exception as e:
                _write_log(f"[red]Ошибка: {e}[/red]")

        elif command == "/retry":
            if _last_user_text:
                on_user_input(_last_user_text)
            else:
                _write_log("[yellow]Нет предыдущего запроса для повтора[/yellow]")

        else:
            _write_log(f"[yellow]Неизвестная команда: {command}. Введите /help для списка команд.[/yellow]")

    def on_user_input(text: str):
        nonlocal _last_user_text, _ollama_chat_url, _verify_ssl
        if text.lower() in ("exit", "quit", "выход"):
            app.exit()
            return

        if stream_active.is_set():
            app._queued_inputs.append(text)
            q = len(app._queued_inputs)
            app._update_queue_placeholder()
            app._add_static(f"[dim]⏸ +{q}: {text}[/dim]")
            return

        _last_user_text = text
        ollama_base_url_updated = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        _ollama_chat_url = f"{ollama_base_url_updated}/api/chat"
        _verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)

        _append_turn_guidance()

        messages.append({"role": "user", "content": text})
        sm.update_context(session_path, "user", text)

        worker = threading.Thread(target=_stream_turn, args=(text,), daemon=True)
        worker.start()

    app.on_submit = on_user_input
    app.on_slash_command = _handle_slash_command
    app._vram_prep_fn = _do_vram_prep

    # Различение Alt+Enter (ESC+CR/LF) — до запуска TUI.
    install_terminal_keys()

    app.run()

    return messages
