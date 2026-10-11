# -*- coding: utf-8 -*-
"""Самообучающийся пересчёт байтов/символов в токены (фаза 1 — тихий сбор).

Идея: инструмент не знает заранее ни одной модели. На каждом запросе к серверу
модели пишется пара (объём текста, точные токены из usage финального ответа).
Накопленные замеры агрегируются в метки плотности (токенов на символ) по ключу
`(деплой, направление, тип вызова)` с каскадным фолбэком вверх:

    (деплой, направление, тип)  n >= MIN_LEAF_N
    (деплой, направление)       n >= MIN_PARENT_N   (агрегат по всем типам)
    глобальный prior по направлению

Агрегация — робастная: скользящее окно, МЕДИАНА + MAD (не среднее), выбросы
за пределом 0.02–20 ток/символ отбрасываются. Детектор дрейфа: медиана
свежих DRIFT_WINDOW замеров ушла от сохранённой больше чем на DRIFT_REL —
метка помечается спорной (панель вправе вернуть байты).

Ничего не меняет в UI: фаза 1 только копит данные. Панель переключится на
токены, когда `ready()` скажет true (см. wiki/concepts/token_calibration.md).

Формат хранилища — версионируемый JSON (атомарная запись), переносимый.
"""
import json
import os
import statistics
import threading
import time

VERSION = 1

WINDOW = 200            # размер скользящего окна замеров на ключ
MIN_LEAF_N = 30         # минимум замеров для точного ключа
MIN_PARENT_N = 20       # минимум замеров для агрегата (деплой, направление)
DRIFT_WINDOW = 30       # сколько свежих замеров смотреть на дрейф
DRIFT_REL = 0.25        # относительный порог срабатывания детектора
RATIO_MIN, RATIO_MAX = 0.02, 20.0   # физический допуск ток/символ
SAVE_THROTTLE_SEC = 5.0
SAVE_EVERY_N = 10

# Стартовые плотности (токенов на символ) для чистой установки — чтобы
# панель говорила токенами с первого же хода до накопления своих замеров.
# Получены на полигоне реальных сессий (агентский RU-трафик, Qwen-семейство);
# собственная медиана перекрывает их после накопления окна.
PRIORS = {"prompt": 0.48, "completion": 0.48, "reasoning": 0.27, "answer": 0.50}

_lock = threading.RLock()
_state = None
_state_path = None
_records_since_save = 0
_last_save = 0.0


def deploy_fingerprint(model: str, server: str) -> str:
    """Устойчивый отпечаток деплоя: модель + сервер (сменился бэкенд — новая метка)."""
    return f"{str(model or '?')}@{str(server or '?')}"


def default_store_path(sessions_dir: str = None) -> str:
    """Хранилище рядом с базой сессий (~/.botinok/token_calib.json по умолчанию)."""
    base = os.path.expanduser(sessions_dir or os.path.join(
        os.path.expanduser('~'), '.botinok', 'sessions'))
    return os.path.join(os.path.dirname(os.path.abspath(base)), 'token_calib.json')


def init(path: str) -> None:
    """Загрузить (или создать) состояние хранилища по указанному пути."""
    global _state, _state_path
    with _lock:
        _state_path = path
        _state = None
    _ensure_loaded()


def _ensure_loaded():
    global _state
    with _lock:
        if _state is not None:
            return _state
        data = {}
        if _state_path and os.path.exists(_state_path):
            try:
                with open(_state_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and loaded.get('version') == VERSION:
                    data = loaded
            except Exception:
                data = {}
        _state = {'version': VERSION, 'keys': data.get('keys') or {}}
        return _state


def _recompute(entry: dict) -> None:
    """Пересчитать медиану/MAD/n по окну; выставить флаг дрейфа.

    Дрейф — сравнение двух непересекающихся окон: «старое» (всё, кроме
    последних DRIFT_WINDOW) против «свежего». Никаких засеянных базовых
    медиан: ранняя естественная вариативность не должна выглядеть дрейфом.
    """
    samples = entry.get('samples') or []
    ratios = [s[1] for s in samples]
    if not ratios:
        entry['median'] = None
        entry['mad'] = None
        entry['n'] = 0
        entry['drift'] = False
        return
    med = statistics.median(ratios)
    mad = statistics.median([abs(r - med) for r in ratios])
    entry['median'] = round(med, 6)
    entry['mad'] = round(mad, 6)
    entry['n'] = len(samples)
    if len(samples) >= 2 * DRIFT_WINDOW:
        old = statistics.median([s[1] for s in samples[:-DRIFT_WINDOW]])
        fresh = statistics.median([s[1] for s in samples[-DRIFT_WINDOW:]])
        entry['drift'] = bool(old > 0 and abs(fresh - old) / old > DRIFT_REL)
    else:
        entry['drift'] = False


def _add_sample(key: str, ratio: float, ts: float) -> None:
    st = _ensure_loaded()
    # Замер пишется и в точный ключ, и в родительский агрегат (деплой,направление),
    # чтобы каскад имел данные до накопления MIN_LEAF_N на листе.
    parent = key.rsplit('|', 1)[0] + '|*'
    for k in (key, parent):
        entry = st['keys'].setdefault(k, {'samples': [], 'n': 0, 'median': None,
                                          'mad': None, 'drift': False,
                                          'stable_median': None})
        samples = entry['samples']
        samples.append([round(ts, 2), round(ratio, 6)])
        if len(samples) > WINDOW:
            del samples[:len(samples) - WINDOW]
        _recompute(entry)


def record_api_call(deploy: str, kind: str, roles: dict, prompt_tokens: int,
                    response_chars: int = 0, thinking_chars: int = 0,
                    tool_chars: int = 0, completion_tokens: int = 0,
                    reasoning_tokens: int = 0, path: str = None) -> dict:
    """Записать один точный срез с завершённого запроса к модели.

    roles: {роль сообщения: число символов} отправленного payload.
    Возвращает dict с записанными ключами (для тестов/отладки).
    """
    global _records_since_save
    if path:
        init(path)
    ts = time.time()
    written = {}
    with _lock:
        total_chars = sum(int(v or 0) for v in (roles or {}).values())
        if prompt_tokens and total_chars > 0:
            r = prompt_tokens / total_chars
            if RATIO_MIN <= r <= RATIO_MAX:
                key = f"{deploy}|prompt|{kind}"
                _add_sample(key, r, ts)
                written['prompt'] = key
        out_chars = int(response_chars or 0) + int(thinking_chars or 0) + int(tool_chars or 0)
        if completion_tokens and out_chars > 0:
            r = completion_tokens / out_chars
            if RATIO_MIN <= r <= RATIO_MAX:
                key = f"{deploy}|completion|{kind}"
                _add_sample(key, r, ts)
                written['completion'] = key
        # Чистый ответ без размышлений: отдельное направление — у ответа и
        # reasoning разная плотность, смешивать их в одной метке нельзя.
        answer_tokens = int(completion_tokens or 0) - int(reasoning_tokens or 0)
        if answer_tokens > 0 and int(response_chars or 0) > 0:
            r = answer_tokens / int(response_chars)
            if RATIO_MIN <= r <= RATIO_MAX:
                key = f"{deploy}|answer|{kind}"
                _add_sample(key, r, ts)
                written['answer'] = key
        if reasoning_tokens and thinking_chars and int(thinking_chars) > 0:
            r = reasoning_tokens / int(thinking_chars)
            if RATIO_MIN <= r <= RATIO_MAX:
                key = f"{deploy}|reasoning|{kind}"
                _add_sample(key, r, ts)
                written['reasoning'] = key
        _records_since_save += 1
        if _records_since_save >= SAVE_EVERY_N or ts - _last_save >= SAVE_THROTTLE_SEC:
            _save_locked()
    return written


def _save_locked() -> None:
    global _records_since_save, _last_save
    if not _state_path or _state is None:
        return
    tmp = _state_path + '.tmp'
    try:
        os.makedirs(os.path.dirname(_state_path), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False)
        os.replace(tmp, _state_path)
        _records_since_save = 0
        _last_save = time.time()
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def flush() -> None:
    """Принудительно сохранить (для тестов и корректного завершения)."""
    with _lock:
        _save_locked()


def _entry_ratio(key: str, min_n: int):
    st = _ensure_loaded()
    entry = st['keys'].get(key)
    if not entry or int(entry.get('n') or 0) < min_n:
        return None
    med = entry.get('median')
    if not med:
        return None
    return med, entry


def estimate(deploy: str, direction: str, kind: str, chars) -> tuple:
    """(токены, статус, n): статус calibrated|drift|prior по каскаду ключей."""
    chars = max(0, int(chars or 0))
    med_entry = _entry_ratio(f"{deploy}|{direction}|{kind}", MIN_LEAF_N)
    if med_entry is None:
        med_entry = _entry_ratio(f"{deploy}|{direction}|*", MIN_PARENT_N)
    if med_entry is not None:
        med, entry = med_entry
        status = 'drift' if entry.get('drift') else 'calibrated'
        return int(round(chars * med)), status, int(entry.get('n') or 0)
    prior = PRIORS.get(direction, 0.30)
    return int(round(chars * prior)), 'prior', 0


def density(deploy: str, direction: str, kind: str = '*') -> tuple:
    """Плотность (токенов на символ) по каскаду ключей: (ratio, status)."""
    med_entry = _entry_ratio(f"{deploy}|{direction}|{kind}", MIN_LEAF_N)
    if med_entry is None:
        med_entry = _entry_ratio(f"{deploy}|{direction}|*", MIN_PARENT_N)
    if med_entry is not None:
        med, entry = med_entry
        return med, ('drift' if entry.get('drift') else 'calibrated')
    return PRIORS.get(direction, 0.30), 'prior'


def ready(deploy: str, direction: str, kind: str = '*') -> bool:
    """Готов ли ключ показывать токены вместо байтов (при дрейфе — не готов)."""
    _, status, _ = estimate(deploy, direction, kind, 1)
    return status == 'calibrated'


def get_stats() -> dict:
    """Сводка по всем ключам (для отладки/будущей панели)."""
    st = _ensure_loaded()
    return {k: {'n': v.get('n'), 'median': v.get('median'), 'mad': v.get('mad'),
                'drift': bool(v.get('drift'))}
            for k, v in st['keys'].items()}


def reset_for_tests() -> None:
    """Полный сброс состояния (только тесты)."""
    global _state, _state_path, _records_since_save, _last_save
    with _lock:
        _state = None
        _state_path = None
        _records_since_save = 0
        _last_save = 0.0
