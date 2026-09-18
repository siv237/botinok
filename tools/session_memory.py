"""
Session Memory Tool — Объектная модель памяти сессий

Предоставляет структурированный доступ к истории сессий через типизированные объекты:
- Turn: обмен сообщениями user ↔ assistant
- ToolCall: вызов инструмента с аргументами и результатом
- Timeline: хронология событий
"""

import json
import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    """Вызов инструмента внутри сообщения assistant"""
    id: str
    tool: str
    arguments: Dict[str, Any]
    timestamp: Optional[str] = None
    result_preview: Optional[str] = None
    result: Optional[str] = None          # полный результат (если доступен)
    artifact: Optional[str] = None        # указатель на полный артефакт
    status: str = "unknown"  # running | completed | failed

    @classmethod
    def from_tool_log_entry(cls, entry: Dict) -> "ToolCall":
        """Создаёт ToolCall из записи tools.log"""
        full = str(entry.get("full_result", "")) if entry.get("full_result") else ""
        return cls(
            id=entry.get("call_id") or f"tool_{entry.get('tool')}_{hash(str(entry))}",
            tool=entry.get("tool", "unknown"),
            arguments=entry.get("arguments", {}),
            timestamp=entry.get("timestamp"),
            result_preview=full[:200] if full else None,
            result=full or None,
            status=entry.get("status", "unknown")
        )

    def to_dict(self, include_args: bool = True) -> Dict:
        result = {
            "id": self.id,
            "tool": self.tool,
            "timestamp": self.timestamp,
            "status": self.status,
        }
        if include_args:
            result["arguments"] = self.arguments
        if self.artifact:
            result["artifact"] = self.artifact
        if self.result_preview:
            result["result_preview"] = self.result_preview
        if include_args and self.result:
            result["result"] = self.result
        return result


@dataclass
class MessagePart:
    """Часть сообщения (user или assistant)"""
    role: str
    content: Optional[str] = None
    content_preview: Optional[str] = None
    content_length: int = 0
    thinking: Optional[str] = None
    thinking_preview: Optional[str] = None
    thinking_length: int = 0
    timestamp: Optional[str] = None
    model: Optional[str] = None
    tokens: Optional[Dict[str, int]] = None

    @classmethod
    def from_context_entry(cls, entry: Dict, max_preview: int = 200) -> "MessagePart":
        """Создаёт MessagePart из записи context.json"""
        content = entry.get("content", "")
        thinking = entry.get("thinking")
        
        content_str = str(content) if content else ""
        thinking_str = str(thinking) if thinking else ""

        # Важно: полный контент храним всегда. Раньше длинные тексты (>400)
        # отбрасывались в None, и get_turn(include_content=True) возвращал
        # только 200-символьное превью — из-за этого агент «не мог прочитать»
        # отчёт из session_memory и лез в файлы.
        return cls(
            role=entry.get("role", "unknown"),
            content=content_str,
            content_preview=content_str[:max_preview] if len(content_str) > max_preview else None,
            content_length=len(content_str),
            thinking=thinking_str,
            thinking_preview=thinking_str[:max_preview] if thinking_str and len(thinking_str) > max_preview else None,
            thinking_length=len(thinking_str),
            timestamp=entry.get("timestamp"),
            model=entry.get("model"),
            tokens=entry.get("tokens")
        )

    def to_dict(self, include_full: bool = True) -> Dict:
        result = {
            "role": self.role,
            "content_length": self.content_length,
            "thinking_length": self.thinking_length,
        }
        if self.timestamp:
            result["timestamp"] = self.timestamp
        if self.model:
            result["model"] = self.model
        if self.tokens:
            result["tokens"] = self.tokens
            
        if include_full:
            if self.content:
                result["content"] = self.content
            if self.thinking:
                result["thinking"] = self.thinking
        
        if self.content_preview:
            result["content_preview"] = self.content_preview
        if self.thinking_preview:
            result["thinking_preview"] = self.thinking_preview
            
        return result


@dataclass
class Turn:
    """Один обмен сообщениями: user → assistant (+ tool_calls)"""
    turn_id: int
    timestamp_start: Optional[str] = None
    timestamp_end: Optional[str] = None
    duration_sec: Optional[float] = None
    user: Optional[MessagePart] = None
    assistant: Optional[MessagePart] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    artifacts_created: List[str] = field(default_factory=list)

    def to_dict(self, include_content: bool = True, include_thinking: bool = True) -> Dict:
        """Сериализация с контролем объёма данных"""
        result = {
            "turn_id": self.turn_id,
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
            "duration_sec": self.duration_sec,
        }
        
        if self.user:
            result["user"] = self.user.to_dict(include_full=include_content)
        if self.assistant:
            result["assistant"] = self.assistant.to_dict(include_full=include_content)
        if self.tool_calls:
            result["tool_calls"] = [tc.to_dict(include_args=include_content) for tc in self.tool_calls]
            result["tool_calls_count"] = len(self.tool_calls)
        if self.artifacts_created:
            result["artifacts_created"] = self.artifacts_created
            
        return result


class SessionParser:
    """Парсит файлы сессии в объектную модель"""
    
    def __init__(self, session_path: str):
        self.session_path = session_path
        self.context_data: Optional[Dict] = None
        self.tools_log: List[Dict] = []
        self._load_data()
    
    def _load_data(self):
        """Загружает context.json и tools.log (мягко, без потери истории)."""
        try:
            from core.session_manager import SessionManager
            history = SessionManager().load_history_entries(self.session_path) or []
        except Exception:
            history = []
        self.context_data = {"history": history}
        
        tools_log_path = os.path.join(self.session_path, "tools.log")
        if os.path.exists(tools_log_path):
            try:
                with open(tools_log_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                self.tools_log.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
            except Exception:
                pass
    
    def parse_turns(self) -> List[Turn]:
        """Парсит историю в список Turn объектов.

        Ход НЕ закрывается на каждом assistant: агент часто отвечает
        несколькими раундами (assistant с tool_calls → tool → снова assistant),
        а авто-продолжения добавляют пустые user-записи. Раньше из-за этого
        реальный финальный ответ попадал в «пустой» ход, и get_turn возвращал
        Assistant (0 chars). Теперь ход закрывается только на новом непустом
        user (или в конце), а внутри накапливаются assistant-текст и tool-calls.
        """
        history = self.context_data.get("history", [])
        turns: List[Turn] = []
        current_turn: Optional[Turn] = None
        current_assistant_has_tc = False
        turn_counter = 0
        last_user_text: Optional[str] = None
        current_user: Optional[MessagePart] = None

        def _start(entry: Optional[Dict], user: Optional[MessagePart] = None):
            nonlocal turn_counter, current_assistant_has_tc
            turn_counter += 1
            current_assistant_has_tc = False
            return Turn(
                turn_id=turn_counter,
                timestamp_start=(entry or {}).get("timestamp"),
                user=user if user is not None else current_user,
            )

        def _close():
            nonlocal current_turn
            if current_turn is None:
                return
            if current_turn.timestamp_start and current_turn.timestamp_end:
                try:
                    t1 = datetime.fromisoformat(current_turn.timestamp_start.replace("Z", "+00:00"))
                    t2 = datetime.fromisoformat(current_turn.timestamp_end.replace("Z", "+00:00"))
                    current_turn.duration_sec = round((t2 - t1).total_seconds(), 2)
                except Exception:
                    pass
            turns.append(current_turn)
            current_turn = None

        for entry in history:
            role = entry.get("role")
            content = str(entry.get("content") or "")

            if role == "user":
                text = content.strip()
                if not text:
                    # пустой auto-continue user — часть текущего хода
                    continue
                if current_turn is not None and text == last_user_text:
                    # дубль подряд (старый формат) — не создаём фантомный ход
                    continue
                _close()
                current_user = MessagePart.from_context_entry(entry)
                current_turn = _start(entry, current_user)
                last_user_text = text

            elif role == "assistant":
                if current_turn is None:
                    current_turn = _start(entry)  # продолжение без нового user
                part = MessagePart.from_context_entry(entry)
                has_tc = bool(entry.get("tool_calls"))
                # Финальный ответ (без tool_calls) закрывает обмен; промежуточные
                # tool-раунды копятся в том же ходе.
                if part.content_length > 0:
                    if current_turn.assistant is None:
                        current_turn.assistant = part
                        current_assistant_has_tc = has_tc
                    elif not has_tc:
                        current_turn.assistant = part
                        current_assistant_has_tc = False
                    elif current_assistant_has_tc:
                        current_turn.assistant = part
                current_turn.timestamp_end = entry.get("timestamp") or current_turn.timestamp_end
                for tc in (entry.get("tool_calls") or []):
                    tc_id = tc.get("id", f"tc_{len(current_turn.tool_calls)}")
                    tc_func = tc.get("function", {}) or {}
                    args = tc_func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args) if args else {}
                        except json.JSONDecodeError:
                            args = {"raw": args}
                    current_turn.tool_calls.append(ToolCall(
                        id=tc_id,
                        tool=tc_func.get("name", "unknown"),
                        arguments=args if args else {},
                        timestamp=entry.get("timestamp"),
                    ))
                # Финальный ответ завершает обмен (ход). Следующие записи без
                # нового user (авто-продолжение) начнут новый ход, унаследовав
                # текущий user-промпт.
                if not has_tc and part.content_length > 0:
                    _close()

            elif role == "tool":
                if current_turn is None:
                    continue
                full = content
                tid = entry.get("tool_call_id")
                target = None
                if tid:
                    target = next((t for t in current_turn.tool_calls if t.id == tid), None)
                if target is None:
                    target = next((t for t in current_turn.tool_calls
                                   if not t.result and not t.result_preview), None)
                if target is None:
                    target = next((t for t in reversed(current_turn.tool_calls)
                                   if t.tool == entry.get("name")), None)
                if target is not None:
                    target.result = full
                    target.result_preview = full[:200]
                    m = re.search(r"artifact_path:\s*(\S+)", full)
                    if m:
                        target.artifact = m.group(1)
                    if target.status in ("unknown", ""):
                        target.status = "completed"
                current_turn.timestamp_end = entry.get("timestamp") or current_turn.timestamp_end

        _close()
        # Дополняем результаты из tools.log (полные, включая старый формат)
        self._enrich_with_tools_log(turns)
        return turns
    
    def _enrich_with_tools_log(self, turns: List[Turn]):
        """Дополняет turns данными из tools.log.

        Быстрый путь — по call_id (новый формат). Старый формат без call_id
        матчим по имени инструмента внутри временного окна хода.
        """
        if not turns or not self.tools_log:
            return

        # Индекс turn по call_id: O(tool_calls).
        turn_by_id: Dict[str, Turn] = {}
        for turn in turns:
            for tc in turn.tool_calls:
                if tc.id:
                    turn_by_id.setdefault(tc.id, turn)

        # Предвычисленные окна ходов для матчинга старого формата.
        windows = []
        for turn in turns:
            if not turn.timestamp_start:
                continue
            try:
                t0 = datetime.fromisoformat(turn.timestamp_start.replace("Z", "+00:00"))
                t1 = (datetime.fromisoformat(turn.timestamp_end.replace("Z", "+00:00"))
                      if turn.timestamp_end else t0)
            except Exception:
                continue
            windows.append((t0, t1, turn))

        for log_entry in self.tools_log:
            cid = log_entry.get("call_id")
            if cid and cid in turn_by_id:
                self._update_tool_call(turn_by_id[cid], log_entry)
                continue
            timestamp = log_entry.get("timestamp")
            if not timestamp:
                continue
            try:
                t_log = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            except Exception:
                continue
            # ближайший ход, в окно которого попадает tool (или ±60с)
            best = None
            best_delta = None
            for t0, t1, turn in windows:
                if t0 <= t_log <= t1:
                    best, best_delta = turn, 0
                    break
                delta = min(abs((t_log - t0).total_seconds()),
                            abs((t_log - t1).total_seconds()))
                if best_delta is None or delta < best_delta:
                    best, best_delta = turn, delta
            if best is not None and (best_delta == 0 or best_delta < 60):
                self._update_tool_call(best, log_entry)
    
    def _update_tool_call(self, turn: Turn, log_entry: Dict):
        """Обновляет существующий или добавляет новый ToolCall (полный результат)."""
        tool_name = log_entry.get("tool")
        call_id = log_entry.get("call_id")
        status = log_entry.get("status", "unknown")
        full = str(log_entry.get("full_result", "")) if log_entry.get("full_result") else ""

        tc = None
        if call_id:
            tc = next((t for t in turn.tool_calls if t.id == call_id), None)
        if tc is None and status != "running":
            tc = next((t for t in turn.tool_calls
                       if t.tool == tool_name and not t.result), None)
        if tc is None:
            tc = next((t for t in reversed(turn.tool_calls) if t.tool == tool_name), None)

        if tc is None:
            turn.tool_calls.append(ToolCall.from_tool_log_entry(log_entry))
            return

        if status and status != "running":
            tc.status = status
        # "STARTED" — не результат, не затираем им уже полученное.
        if full and full != "STARTED":
            tc.result = full
            tc.result_preview = full[:200]
        tc.timestamp = log_entry.get("timestamp", tc.timestamp)


class SessionIndex:
    """Индекс для быстрого поиска по сессии"""
    
    def __init__(self, session_path: str):
        self.session_path = session_path
        self.index_path = os.path.join(session_path, ".index", "session_memory.idx")
        self.turns: List[Turn] = []
        self.word_index: Dict[str, List[int]] = {}  # word -> turn_ids
        self._loaded = False
    
    def build(self) -> List[Turn]:
        """Строит индекс и возвращает turns"""
        parser = SessionParser(self.session_path)
        self.turns = parser.parse_turns()
        self._build_word_index()
        # Сохраняем индекс только для реальных сессий: создание .index в
        # пустой/чужой сессии искажало mtime каталога и ломало сортировку
        # list_sessions() (см. SessionManager._session_marker_mtime).
        if self.turns:
            self._save_index()
        self._loaded = True
        return self.turns
    
    def get_turns(self) -> List[Turn]:
        """Возвращает turns (строит индекс при необходимости)"""
        if not self._loaded:
            if os.path.exists(self.index_path):
                self._load_index()
            else:
                self.build()
        return self.turns
    
    def _build_word_index(self):
        """Строит инвертированный индекс слов"""
        for turn in self.turns:
            words = set()
            
            # Индексируем user content
            if turn.user and turn.user.content:
                words.update(self._extract_words(turn.user.content))
            
            # Индексируем assistant content и thinking
            if turn.assistant:
                if turn.assistant.content:
                    words.update(self._extract_words(turn.assistant.content))
                if turn.assistant.thinking:
                    words.update(self._extract_words(turn.assistant.thinking))
            
            # Индексируем tool_calls
            for tc in turn.tool_calls:
                words.add(tc.tool.lower())
                for arg_val in tc.arguments.values():
                    words.update(self._extract_words(str(arg_val)))
            
            # Добавляем в индекс
            for word in words:
                if word not in self.word_index:
                    self.word_index[word] = []
                self.word_index[word].append(turn.turn_id)
    
    def _extract_words(self, text: str) -> set:
        """Извлекает слова из текста"""
        words = set()
        for match in re.finditer(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', text.lower()):
            words.add(match.group())
        return words
    
    def _save_index(self):
        """Сохраняет индекс на диск"""
        try:
            os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
            data = {
                "turns_count": len(self.turns),
                "word_index": self.word_index,
                "turns_meta": [
                    {
                        "turn_id": t.turn_id,
                        "timestamp_start": t.timestamp_start,
                        "timestamp_end": t.timestamp_end,
                        "tool_calls_count": len(t.tool_calls)
                    }
                    for t in self.turns
                ]
            }
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass  # Индекс необязателен
    
    def _load_index(self):
        """Загружает индекс с диска"""
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.word_index = data.get("word_index", {})
            # Перезагружаем turns из parser (индекс только мета-информация)
            parser = SessionParser(self.session_path)
            self.turns = parser.parse_turns()
            self._loaded = True
        except Exception:
            self.build()


def session_memory_tool(
    action: str = "summary",
    session_path: Optional[str] = None,
    turn_id: Optional[int] = None,
    query: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    role: Optional[str] = None,
    has_tool_calls: Optional[bool] = None,
    limit: int = 20,
    offset: int = 0,
    format: str = "structured",
    include_content: bool = False,
    include_thinking: bool = False,
    max_preview_chars: int = 200,
    **kwargs
) -> str:
    """
    Session Memory Tool — объектный доступ к истории сессии
    
    Actions:
    - resume_brief: быстрый сбор сессии для продолжения после паузы/прерывания
    - summary: общая сводка по сессии
    - turns: список обменов с метаданными
    - get_turn: полный объект Turn по ID
    - search: поиск по content/thinking/tool_calls
    - timeline: хронология событий
    - stats: статистика сессии
    
    Args:
        action: тип операции
        session_path: путь к сессии (default: автоопределение)
        turn_id: ID turn для get_turn
        query: строка поиска для search
        since/until: фильтр по времени (ISO format)
        role: фильтр по роли (user/assistant/system)
        has_tool_calls: фильтр по наличию tool_calls
        limit/offset: пагинация
        format: structured | json | markdown
        include_content: включать полный content
        include_thinking: включать полный thinking
        max_preview_chars: длина превью
    """

    # --- Прощающее приведение аргументов: тупая модель не должна ошибаться ---
    # Синонимы action и терпимость к типам/пропущенным аргументам.
    _ALIASES = {
        "brief": "resume_brief", "resume": "resume_brief",
        "resume_brief": "resume_brief", "continue": "resume_brief",
        "sum": "summary", "info": "summary", "summary": "summary",
        "turn": "get_turn", "get": "get_turn", "get_turn": "get_turn",
        "list": "turns", "turns": "turns",
        "find": "search", "grep": "search", "search": "search",
        "filter": "filter", "timeline": "timeline", "stats": "stats", "chain": "chain",
        "help": "help", "?": "help", "actions": "help", "man": "help", "capabilities": "help",
        "restore": "restore", "rebuild": "restore", "exact": "restore",
        "load": "restore", "resume_exact": "restore", "snapshot": "restore",
    }
    _VALID = set(_ALIASES.values())
    raw_action = str(action if isinstance(action, str) else "").strip().lower()
    if not raw_action:
        # Пустой action — помогаем, а не ошибаемся.
        action = "resume_brief"
    elif raw_action in _ALIASES:
        action = _ALIASES[raw_action]
    else:
        # Строгая неоднозначность: НЕ подменяем смысл действия молча.
        return json.dumps({
            "ambiguous": True,
            "requested": raw_action,
            "candidates": sorted(_VALID),
            "hint": "Не понял action. Точное восстановление — action=\"restore\"; "
                    "обзор — resume_brief; поиск — search; справка — help.",
            "_next_actions": ["action=\"restore\"", "action=\"help\"", "action=\"resume_brief\""],
        }, ensure_ascii=False, indent=2)

    def _to_int(v, default=None):
        try:
            if v is None or v == "":
                return default
            return int(v)
        except Exception:
            return default

    turn_id = _to_int(turn_id)
    limit = _to_int(limit, 20) or 20
    offset = _to_int(offset, 0) or 0
    if not query:
        query = kwargs.get("q") or kwargs.get("text") or kwargs.get("query")
    if turn_id is None:
        turn_id = _to_int(kwargs.get("turn") or kwargs.get("id") or kwargs.get("turn_id"))
    if not include_content:
        include_content = bool(kwargs.get("full") or kwargs.get("include_full"))

    # Определяем путь к сессии (прощающе: плохой путь → берём последнюю сессию)
    requested_path = session_path
    if session_path and not os.path.exists(session_path):
        session_path = None
    if not session_path:
        session_path = os.environ.get("BOTINOK_SESSION_PATH") or None
    if not session_path or not os.path.exists(session_path):
        try:
            from core.session_manager import SessionManager
            latest = SessionManager().get_latest_session()
            if latest:
                session_path = latest.get("path")
        except Exception:
            session_path = None

    if not session_path or not os.path.exists(session_path):
        return json.dumps({
            "error": "Session path not found",
            "hint": "Укажи session_path=... (папка сессии) или открой сессию; "
                    "без него берётся последняя.",
            "available_actions": sorted(_VALID),
            "_next_actions": ["action=\"turns\"", "action=\"help\""],
        }, ensure_ascii=False, indent=2)

    _path_note = None
    if requested_path and session_path != requested_path:
        _path_note = f"Путь {requested_path} не найден — взята последняя сессия."
    
    # Получаем или строим индекс
    index = SessionIndex(session_path)
    turns = index.get_turns()
    
    # Выполняем action
    result = {}

    if action == "help":
        return _help_text(session_path)

    if action == "restore":
        result = _action_restore(session_path, include_content=True)

    elif action == "resume_brief":
        result = _action_resume_brief(session_path, turns, limit)

    elif action == "summary":
        result = _action_summary(turns, session_path)
    
    elif action == "turns":
        result = _action_turns(turns, limit, offset, include_content, include_thinking)
    
    elif action == "get_turn":
        result = _action_get_turn(turns, turn_id, include_content, include_thinking)
    
    elif action == "search":
        result = _action_search(turns, index, query, limit, include_content, include_thinking,
                                mode=str(kwargs.get("mode", "auto")).lower(),
                                session_path=session_path)
    
    elif action == "filter":
        result = _action_filter(turns, since, until, role, has_tool_calls, limit, offset, include_content, include_thinking)
    
    elif action == "timeline":
        result = _action_timeline(turns, limit)
    
    elif action == "stats":
        result = _action_stats(turns)
    
    elif action == "chain":
        from_turn = kwargs.get("from_turn", 0)
        to_turn = kwargs.get("to_turn", len(turns))
        result = _action_chain(turns, from_turn, to_turn, include_content, include_thinking)
    
    else:
        result = {"error": f"Unknown action: {action}", "available_actions": [
            "resume_brief", "summary", "turns", "get_turn", "search", "filter", "timeline", "stats", "chain"
        ]}
    
    # Архивариус не молчит: контекст, совет и следующие шаги — всегда.
    if isinstance(result, dict):
        result["_meta"] = {
            "session": os.path.basename(os.path.normpath(session_path)),
            "turns_total": len(turns),
            "turn_range": [turns[0].turn_id, turns[-1].turn_id] if turns else [],
            "last_timestamp": ((turns[-1].timestamp_end or turns[-1].timestamp_start)
                               if turns else None),
        }
        if _path_note:
            result["_meta"]["note"] = _path_note
        prov = _provenance_for(action, result)
        result["_provenance"] = prov
        result["_confidence"] = _CONF[prov]
        result.setdefault("_advice", _advise(action, result))
        result.setdefault("_next_actions", _next_actions(action, result))

    # Форматируем вывод
    if format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2)
    elif format == "markdown":
        return _format_as_markdown(result, action)
    else:  # structured
        if isinstance(result, dict) and "error" in result:
            return json.dumps(result, ensure_ascii=False)
        return _format_structured(result, action)


def _help_text(session_path: str) -> str:
    return (
        "🧭 Session Memory — архивариус и советник по этой сессии.\n"
        "\n"
        "Что я знаю: точные timestamps, строгий порядок ходов (turn_id 1..N),\n"
        "полные тексты user/assistant/thinking, аргументы и результаты инструментов,\n"
        "указатели на артефакты. Зачем: продолжать сессию и искать в ней БЕЗ чтения\n"
        "context.json/response.md напрямую — здесь быстрее и с подсказками.\n"
        "\n"
        "Простой синтаксис (всё прощается, регистр/пробелы не важны):\n"
        "  • action=resume_brief                      — что было и где остановились\n"
        "  • action=get_turn turn_id=123 include_content=true — полный ход\n"
        "  • action=search query=кулер                — гибкий поиск (части слов, RU)\n"
        "  • action=turns limit=20 offset=0           — список ходов\n"
        "  • action=timeline limit=30                 — хронология\n"
        "  • action=help                              — эта справка\n"
        "\n"
        "Можно звать усечённо: action=turn/123, action=list, action=find query=...\n"
        "Если аргумент пропущен — я не ошибуюсь, а подскажу следующий шаг.\n"
        f"Сессия: {session_path}\n"
    )


def _advise(action: str, data: Dict) -> str:
    """Короткий совет архивариуса — что делать дальше."""
    try:
        if action == "resume_brief":
            return ("Продолжай с последнего хода; детали любого хода — "
                    "get_turn(turn_id=…, include_content=true).")
        if action == "search":
            n = data.get("total_matches", 0)
            if n == 0:
                return ("Совпадений нет — попробуй mode=any, одно слово или "
                        "часть слова (поиск кириллицы учитывает окончания).")
            return (f"Нашлось {n}. Смотри блок «Где именно» (файл:строка, время); "
                    "детали — get_turn по turn_id из списка.")
        if action == "get_turn":
            return "Соседние ходы и полные результаты инструментов — в подсказках ниже."
        if action == "turns":
            return "Для содержания хода — get_turn; для страницы — offset."
        if action == "restore":
            if data.get("exact"):
                extra = (" Снапшот старше context.json (есть прерванный хвост) — "
                         "хвост смотри через get_turn/turns." if data.get("stale") else "")
                return ("Точный контекст из messages.json — можно доверять "
                        f"(EXACT); подавай как есть для продолжения.{extra}")
            return ("Снапшота нет: это реконструкция из context.json (DERIVED) — "
                    "ключевые места перепроверь.")
        if action == "timeline":
            return "Точка во времени с ошибкой/инструментом — get_turn рядом."
        return "Могу: restore, resume_brief, get_turn, search, turns, timeline, help."
    except Exception:
        return ""


def _next_actions(action: str, data: Dict) -> List[str]:
    """Конкретные следующие вызовы session_memory (интуитивные подсказки)."""
    def sm(a, **kw):
        parts = [f'action="{a}"']
        for k, v in kw.items():
            parts.append(f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}")
        return "session_memory " + " ".join(parts)

    def _kw(text, n=60):
        s = " ".join(str(text or "").split())
        return s[:n] if s else ""

    nxt = []
    if action == "resume_brief":
        rt = data.get("recent_turns") or []
        if rt:
            nxt.append(sm("get_turn", turn_id=rt[-1]["turn_id"], include_content=True))
        nxt.append(sm("turns", limit=20))
        if data.get("LAST_USER_PROMPT"):
            nxt.append(sm("search", query=_kw(data["LAST_USER_PROMPT"])))
    elif action == "get_turn":
        tid = data.get("turn_id")
        if isinstance(tid, int):
            nxt.append(sm("get_turn", turn_id=max(1, tid - 1), include_content=True))
            nxt.append(sm("get_turn", turn_id=tid + 1, include_content=True))
        nxt.append(sm("timeline", limit=30))
    elif action == "turns":
        for t in (data.get("turns") or [])[:3]:
            if t.get("turn_id"):
                nxt.append(sm("get_turn", turn_id=t["turn_id"], include_content=True))
        total = data.get("total", 0)
        off = data.get("offset", 0)
        lim = data.get("limit", 20)
        if total > off + lim:
            nxt.append(sm("turns", limit=lim, offset=off + lim))
    elif action == "search":
        for t in (data.get("turns") or [])[:3]:
            if t.get("turn_id"):
                nxt.append(sm("get_turn", turn_id=t["turn_id"], include_content=True))
        nxt.append(sm("turns", limit=20))
    elif action == "restore":
        nxt.append(sm("turns", limit=20))
        nxt.append(sm("resume_brief"))
    elif action == "timeline":
        for e in (data.get("events") or [])[:3]:
            if e.get("turn_id"):
                nxt.append(sm("get_turn", turn_id=e["turn_id"], include_content=True))
    else:
        nxt.append(sm("resume_brief"))
        nxt.append(sm("timeline", limit=30))
        nxt.append(sm("turns", limit=20))

    seen = set()
    out = []
    for x in nxt:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:6]


_CONF = {"exact": "EXACT", "derived": "DERIVED", "heuristic": "HINT"}


def _provenance_for(action: str, result: Dict) -> str:
    if action == "restore":
        return "exact" if result.get("exact") else "derived"
    if action == "search":
        return "heuristic"
    return "derived"


def _action_restore(session_path: str, include_content: bool = True) -> Dict:
    """Точное восстановление контекста из канонического снапшота.

    exact=True  — прочитан messages.json (источник истины, можно доверять);
    exact=False — снапшота нет, реконструкция из context.json (derived).
    """
    from core.session_manager import SessionManager
    data = SessionManager().restore_session(session_path)
    msgs = data.get("messages") or []
    from collections import Counter
    roles = Counter(m.get("role") for m in msgs)
    if include_content:
        payload_msgs = msgs
    else:
        payload_msgs = [
            {"role": m.get("role"),
             "content_length": len(str(m.get("content") or "")),
             "tool_call_id": m.get("tool_call_id"),
             "has_tool_calls": bool(m.get("tool_calls"))}
            for m in msgs
        ]
    return {
        "source": data.get("source"),
        "exact": bool(data.get("exact")),
        "model": data.get("model"),
        "context_limit": data.get("context_limit"),
        "saved_at": data.get("saved_at"),
        "stale": bool(data.get("stale")),
        "last_context_timestamp": data.get("last_context_timestamp"),
        "messages_count": len(msgs),
        "roles": dict(roles),
        "tool_messages": sum(1 for m in msgs if m.get("role") == "tool"),
        "messages_full": include_content,
        "messages": payload_msgs,
    }


def _action_resume_brief(session_path: str, turns: List[Turn], limit: int) -> Dict:
    """Быстрый сбор сессии для продолжения после прерывания/паузы."""
    from core.session_manager import SessionManager
    brief = SessionManager().build_resume_brief(session_path)
    recent = []
    for t in turns[-max(1, limit):]:
        recent.append({
            "turn_id": t.turn_id,
            "timestamp_start": t.timestamp_start,
            "timestamp_end": t.timestamp_end,
            "user_preview": ((t.user.content or t.user.content_preview or "")[:200]
                             if t.user else ""),
            "assistant_preview": ((t.assistant.content or t.assistant.content_preview or "")[:200]
                                  if t.assistant else ""),
            "tools": [tc.tool for tc in t.tool_calls],
        })
    brief = dict(brief)
    brief["recent_turns"] = recent
    return brief


def _action_summary(turns: List[Turn], session_path: str) -> Dict:
    """Общая сводка по сессии"""
    total_tokens_in = 0
    total_tokens_out = 0
    tools_used: Dict[str, int] = {}
    
    for turn in turns:
        if turn.assistant and turn.assistant.tokens:
            total_tokens_in += turn.assistant.tokens.get("prompt", 0)
            total_tokens_out += turn.assistant.tokens.get("completion", 0)
        
        for tc in turn.tool_calls:
            tools_used[tc.tool] = tools_used.get(tc.tool, 0) + 1
    
    return {
        "session_path": session_path,
        "total_turns": len(turns),
        "total_messages": len(turns) * 2 if turns else 0,
        "total_tool_calls": sum(len(t.tool_calls) for t in turns),
        "tokens": {
            "input": total_tokens_in,
            "output": total_tokens_out,
            "total": total_tokens_in + total_tokens_out
        },
        "tools_used": tools_used,
        "time_range": {
            "first": turns[0].timestamp_start if turns else None,
            "last": turns[-1].timestamp_end if turns else None
        }
    }


def _action_turns(turns: List[Turn], limit: int, offset: int, include_content: bool, include_thinking: bool) -> Dict:
    """Список turns с пагинацией"""
    total = len(turns)
    sliced = turns[offset:offset + limit]
    
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "turns": [t.to_dict(include_content, include_thinking) for t in sliced]
    }


def _action_get_turn(turns: List[Turn], turn_id: Optional[int], include_content: bool, include_thinking: bool) -> Dict:
    """Получить конкретный turn по ID.

    Прощающее поведение: без turn_id берём последний ход, а при промахе —
    ближайший существующий (с пометкой), чтобы агент не упирался в ошибку.
    """
    if not turns:
        return {"error": "История пуста", "turns": 0}

    if turn_id is None:
        turn = turns[-1]
        result = turn.to_dict(include_content, include_thinking)
        result["_note"] = "turn_id не указан — показан последний ход."
        result["confidence"] = "DERIVED"
        return result

    for turn in turns:
        if turn.turn_id == turn_id:
            result = turn.to_dict(include_content, include_thinking)
            result["confidence"] = "DERIVED"
            return result

    # Ближайший по номеру.
    nearest = min(turns, key=lambda t: abs(t.turn_id - turn_id))
    result = nearest.to_dict(include_content, include_thinking)
    result["confidence"] = "DERIVED"
    result["_note"] = (f"Turn {turn_id} не найден — показан ближайший "
                       f"Turn {nearest.turn_id}. Диапазон: {turns[0].turn_id}…{turns[-1].turn_id}.")
    return result


def _norm_text(s) -> str:
    """Нормализация для поиска: регистр, пробелы, пунктуация."""
    s = str(s or "").lower().replace("ё", "е")
    s = re.sub(r"[\u2018\u2019\u201c\u201d«»\"'`]", " ", s)
    s = re.sub(r"[\x00-\x1f]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


_RU_ENDINGS = (
    # длинные окончания — раньше, чтобы срезать максимум
    "ями", "ами", "иями", "ыми", "ими", "ого", "его", "ому", "ему",
    "ах", "ях", "ов", "ев", "ий", "ый", "ой", "ей", "ом", "ем", "ью", "ию",
    "а", "я", "о", "е", "у", "ю", "ы", "и", "ь",
)


def _stem(token: str) -> str:
    """Грубый стеммер (RU/EN): «кулеры»→«кулер», «нагрузкой»→«нагрузк».

    Поиск по сессии чаще кириллический, поэтому срезаем частые русские
    окончания. Это не полноценная морфология, но резко повышает гибкость.
    """
    t = token
    if len(t) > 5:
        for end in _RU_ENDINGS:
            if t.endswith(end) and len(t) - len(end) >= 4:
                t = t[: -len(end)]
                break
    if len(t) > 4 and t.endswith("s"):
        t = t[:-1]
    return t


def _query_tokens(query) -> List[str]:
    return [t for t in re.split(r"\s+", _norm_text(query)) if t]


def _turn_haystack(turn: Turn):
    """Все тексты хода для поиска: (текст, метка, вес)."""
    parts = []
    if turn.user:
        if turn.user.content:
            parts.append((_norm_text(turn.user.content), "user_content", 4))
        if turn.user.thinking:
            parts.append((_norm_text(turn.user.thinking), "user_thinking", 1))
    if turn.assistant:
        if turn.assistant.content:
            parts.append((_norm_text(turn.assistant.content), "assistant_content", 4))
        if turn.assistant.thinking:
            parts.append((_norm_text(turn.assistant.thinking), "assistant_thinking", 2))
    for tc in turn.tool_calls:
        parts.append((_norm_text(tc.tool), f"tool:{tc.tool}", 2))
        if tc.arguments:
            try:
                parts.append((_norm_text(json.dumps(tc.arguments, ensure_ascii=False)),
                              "tool_arguments", 2))
            except Exception:
                parts.append((_norm_text(str(tc.arguments)), "tool_arguments", 1))
        body = tc.result or tc.result_preview or ""
        if body:
            parts.append((_norm_text(body), "tool_result", 1))
        if tc.artifact:
            parts.append((_norm_text(tc.artifact), "artifact", 1))
    return parts


_SEARCH_FILES = ("response.md", "thinking.md", "tools.log", "session_raw.log",
                 "context.json", "messages.json")


def _search_files(session_path: str, tokens: List[str],
                  limit_per_file: int = 5) -> List[Dict]:
    """Ищет токены построчно в файлах сессии; возвращает файл:строка + время."""
    if not session_path or not os.path.isdir(session_path) or not tokens:
        return []
    found: List[Dict] = []
    for fname in _SEARCH_FILES:
        path = os.path.join(session_path, fname)
        if not os.path.isfile(path):
            continue
        try:
            file_mtime = datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
        except Exception:
            file_mtime = None
        hits = 0
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    nl = _norm_text(line)
                    if not any(tok in nl or (len(tok) > 4 and _stem(tok) in nl)
                               for tok in tokens):
                        continue
                    m = re.search(r'"timestamp"\s*:\s*"([^"]+)"', line)
                    found.append({
                        "file": fname,
                        "line": lineno,
                        "timestamp": m.group(1) if m else file_mtime,
                        "file_mtime": file_mtime,
                        "snippet": " ".join(line.split())[:220],
                    })
                    hits += 1
                    if hits >= limit_per_file:
                        break
        except Exception:
            continue
    return found


def _action_search(turns: List[Turn], index: SessionIndex, query: str, limit: int,
                   include_content: bool, include_thinking: bool,
                   mode: str = "auto", session_path: str = "") -> Dict:
    """Очень гибкий поиск по сессии.

    - регистр не важен;
    - пробелы/пунктуация нормализуются;
    - ищутся части слов (подстроки) и отдельные токены;
    - при отсутствии полного совпадения возвращаются частичные.
    mode: auto | all (все токены) | any (любой токен) | regex
    """
    raw = str(query or "").strip()
    if not raw:
        # Без запроса не ошибка — отдаём последние ходы.
        recent = turns[-limit:]
        out = [t.to_dict(include_content, include_thinking) for t in recent]
        return {
            "query": "",
            "tokens": [],
            "note": "Запрос пуст — показаны последние ходы. Уточни query=…",
            "total_matches": len(turns),
            "turns": out,
        }

    matched_turns = []
    tokens = _query_tokens(raw)

    if mode == "regex":
        try:
            rx = re.compile(raw, re.IGNORECASE)
        except re.error:
            rx = None
        for turn in turns:
            hay = " \n ".join(p[0] for p in _turn_haystack(turn))
            if rx and rx.search(hay):
                d = turn.to_dict(include_content, include_thinking)
                d["matched_in"] = ["regex"]
                d["search_score"] = 10
                d["confidence"] = "HINT"
                matched_turns.append(d)
    else:
        for turn in turns:
            parts = _turn_haystack(turn)
            blob = " \n ".join(p[0] for p in parts)
            # Совпадение: сам токен или его стем (учёт кириллических окончаний).
            hit = [tok for tok in tokens
                   if tok in blob or (len(tok) > 4 and _stem(tok) in blob)]
            if not hit:
                continue
            all_hit = len(hit) == len(tokens)
            if mode == "all" and not all_hit:
                continue
            hit_variants = set()
            for tok in hit:
                hit_variants.add(tok)
                if len(tok) > 4:
                    hit_variants.add(_stem(tok))
            matched_in = []
            for text, label, _w in parts:
                if any(v in text for v in hit_variants):
                    matched_in.append(label)
            score = len(hit) * 3
            if all_hit:
                score += 6
            # бонус за попадание в user/assistant текст
            if "user_content" in matched_in:
                score += 2
            if "assistant_content" in matched_in:
                score += 2
            d = turn.to_dict(include_content, include_thinking)
            d["matched_in"] = sorted(set(matched_in))
            d["matched_tokens"] = hit
            d["search_score"] = score
            d["partial"] = not all_hit
            d["confidence"] = "HINT"
            matched_turns.append(d)

    matched_turns.sort(key=lambda x: x.get("search_score", 0), reverse=True)

    return {
        "query": raw,
        "tokens": tokens,
        "mode": mode,
        "total_matches": len(matched_turns),
        "turns": matched_turns[:limit],
        "files": _search_files(session_path, tokens) if tokens else [],
    }


def _action_filter(turns: List[Turn], since: Optional[str], until: Optional[str], role: Optional[str], 
                   has_tool_calls: Optional[bool], limit: int, offset: int, include_content: bool, include_thinking: bool) -> Dict:
    """Фильтрация turns"""
    filtered = []
    
    for turn in turns:
        # Фильтр по времени
        if since and turn.timestamp_start:
            if turn.timestamp_start < since:
                continue
        if until and turn.timestamp_end:
            if turn.timestamp_end > until:
                continue
        
        # Фильтр по роли
        if role:
            if role == "user" and not turn.user:
                continue
            if role == "assistant" and not turn.assistant:
                continue
        
        # Фильтр по наличию tool_calls
        if has_tool_calls is not None:
            if has_tool_calls and not turn.tool_calls:
                continue
            if not has_tool_calls and turn.tool_calls:
                continue
        
        filtered.append(turn)
    
    total = len(filtered)
    sliced = filtered[offset:offset + limit]
    
    return {
        "filters": {"since": since, "until": until, "role": role, "has_tool_calls": has_tool_calls},
        "total": total,
        "offset": offset,
        "limit": limit,
        "turns": [t.to_dict(include_content, include_thinking) for t in sliced]
    }


def _action_timeline(turns: List[Turn], limit: int) -> Dict:
    """Хронология событий"""
    events = []
    
    for turn in turns:
        # User message
        if turn.user:
            events.append({
                "type": "user_message",
                "turn_id": turn.turn_id,
                "timestamp": turn.timestamp_start,
                "preview": turn.user.content_preview or turn.user.content[:100] if turn.user.content else "",
                "content_length": turn.user.content_length
            })
        
        # Tool calls
        for tc in turn.tool_calls:
            events.append({
                "type": "tool_call",
                "turn_id": turn.turn_id,
                "timestamp": tc.timestamp,
                "tool": tc.tool,
                "status": tc.status,
                "preview": str(tc.arguments)[:100]
            })
        
        # Assistant message
        if turn.assistant:
            events.append({
                "type": "assistant_message",
                "turn_id": turn.turn_id,
                "timestamp": turn.timestamp_end,
                "preview": turn.assistant.content_preview or turn.assistant.content[:100] if turn.assistant.content else "",
                "has_thinking": turn.assistant.thinking_length > 0,
                "content_length": turn.assistant.content_length,
                "model": turn.assistant.model
            })
    
    # Сортируем по timestamp
    events.sort(key=lambda x: x.get("timestamp") or "")
    
    return {
        "total_events": len(events),
        "events": events[:limit]
    }


def _action_stats(turns: List[Turn]) -> Dict:
    """Статистика сессии"""
    total_tool_calls = 0
    tools_distribution: Dict[str, int] = {}
    models_used: Dict[str, int] = {}
    content_lengths = []
    thinking_lengths = []
    durations = []
    
    for turn in turns:
        total_tool_calls += len(turn.tool_calls)
        
        for tc in turn.tool_calls:
            tools_distribution[tc.tool] = tools_distribution.get(tc.tool, 0) + 1
        
        if turn.assistant:
            if turn.assistant.model:
                models_used[turn.assistant.model] = models_used.get(turn.assistant.model, 0) + 1
            content_lengths.append(turn.assistant.content_length)
            thinking_lengths.append(turn.assistant.thinking_length)
        
        if turn.duration_sec:
            durations.append(turn.duration_sec)
    
    return {
        "turns_count": len(turns),
        "tool_calls_count": total_tool_calls,
        "tools_distribution": tools_distribution,
        "models_used": models_used,
        "content": {
            "total_chars": sum(content_lengths),
            "avg_per_turn": sum(content_lengths) / len(content_lengths) if content_lengths else 0,
            "max_turn": max(content_lengths) if content_lengths else 0
        },
        "thinking": {
            "total_chars": sum(thinking_lengths),
            "avg_per_turn": sum(thinking_lengths) / len(thinking_lengths) if thinking_lengths else 0,
            "max_turn": max(thinking_lengths) if thinking_lengths else 0
        },
        "response_time": {
            "avg_sec": sum(durations) / len(durations) if durations else 0,
            "min_sec": min(durations) if durations else 0,
            "max_sec": max(durations) if durations else 0,
            "total_sec": sum(durations) if durations else 0
        }
    }


def _action_chain(turns: List[Turn], from_turn: int, to_turn: int, include_content: bool, include_thinking: bool) -> Dict:
    """Цепочка рассуждений от from_turn до to_turn"""
    # Нормализуем индексы
    from_idx = max(0, from_turn - 1)  # turn_id начинается с 1
    to_idx = min(len(turns), to_turn)
    
    chain = turns[from_idx:to_idx]
    
    return {
        "from_turn": from_turn,
        "to_turn": to_turn,
        "chain_length": len(chain),
        "chain": [t.to_dict(include_content, include_thinking) for t in chain]
    }


def _format_structured(data: Dict, action: str) -> str:
    """Форматирует результат в структурированный текст"""
    lines = []

    meta = data.get("_meta") or {}
    if meta.get("session"):
        rng = meta.get("turn_range") or []
        rng_s = f"[{rng[0]}..{rng[1]}]" if rng else "[]"
        conf = data.get("_confidence") or ""
        lines.append(f"🧭 Архивариус: {meta['session']} · ходов {meta.get('turns_total')} "
                     f"{rng_s} · последний {meta.get('last_timestamp')}"
                     + (f" · [{conf}]" if conf else ""))
        if meta.get("note"):
            lines.append(f"   ℹ {meta['note']}")

    if action == "resume_brief":
        lines.append("🔁 Resume Brief")
        lines.append(f"   Session: {data.get('SESSION_NAME')}")
        lines.append(f"   Status: {data.get('RESUME_STATE')} | elapsed: {data.get('ELAPSED')}")
        lines.append(f"   Original task: {data.get('ORIGINAL_TASK', '')[:200]}")
        lines.append(f"   Last user prompt: {data.get('LAST_USER_PROMPT', '')[:200]}")
        lines.append(f"   Last assistant: {data.get('LAST_ASSISTANT_ANSWER', '')[:200]}")
        lines.append(f"   History: {data.get('HISTORY_LEN')} msgs, tool calls: {data.get('TOOL_CALLS')} (missing result: {data.get('TOOL_CALLS_MISSING')})")
        recent = data.get("recent_turns", [])
        if recent:
            lines.append("   Recent turns:")
            for t in recent:
                tools = f" [{', '.join(t.get('tools', []))}]" if t.get("tools") else ""
                lines.append(f"      Turn {t.get('turn_id')} ({t.get('timestamp_start')}){tools}")
                if t.get("user_preview"):
                    lines.append(f"         User: {t['user_preview'][:100]}")
                if t.get("assistant_preview"):
                    lines.append(f"         Assistant: {t['assistant_preview'][:100]}")

    elif action == "restore":
        lines.append(f"🧩 Точное восстановление: source={data.get('source')} "
                     f"exact={data.get('exact')} model={data.get('model')} "
                     f"ctx={data.get('context_limit')}")
        lines.append(f"   Сообщений: {data.get('messages_count')} · roles={data.get('roles')} "
                     f"· tool-сообщений: {data.get('tool_messages')}")
        if data.get("stale"):
            lines.append(f"   ⚠ Снапшот старше context.json: последний хвост "
                         f"{data.get('last_context_timestamp')} — смотри get_turn/turns.")
        for m in (data.get("messages") or [])[-6:]:
            role = m.get("role")
            if m.get("content_length") is not None:
                body = f"len={m.get('content_length')}"
            else:
                body = " ".join(str(m.get("content") or "").split())[:100]
            lines.append(f"   • {role}: {body}")
        if data.get("messages_full"):
            lines.append("   (полный массив `messages` — в format=json)")

    elif action == "summary":
        lines.append(f"📊 Session Summary")
        lines.append(f"   Path: {data.get('session_path')}")
        lines.append(f"   Turns: {data.get('total_turns')}, Messages: {data.get('total_messages')}, Tool calls: {data.get('total_tool_calls')}")
        lines.append(f"   Tokens: {data.get('tokens', {}).get('total', 0)} (in: {data.get('tokens', {}).get('input', 0)}, out: {data.get('tokens', {}).get('output', 0)})")
        
        tools = data.get('tools_used', {})
        if tools:
            lines.append(f"   Tools used:")
            for tool, count in sorted(tools.items(), key=lambda x: -x[1]):
                lines.append(f"      • {tool}: {count}")
    
    elif action == "turns":
        lines.append(f"🔄 Turns (showing {len(data.get('turns', []))} of {data.get('total', 0)}):")
        for turn in data.get("turns", []):
            turn_id = turn.get("turn_id")
            ts = turn.get("timestamp_start", "?")
            duration = turn.get("duration_sec")
            tc_count = turn.get("tool_calls_count", 0)
            
            user_preview = turn.get("user", {}).get("content_preview", "")[:50]
            
            dur_str = f" ({duration}s)" if duration else ""
            tc_str = f" [{tc_count} tools]" if tc_count else ""
            lines.append(f"   Turn {turn_id}: {ts}{dur_str}{tc_str}")
            if user_preview:
                lines.append(f"      User: {user_preview}...")
    
    elif action == "get_turn":
        lines.append(f"📋 Turn {data.get('turn_id')}  "
                     f"[{data.get('timestamp_start')} → {data.get('timestamp_end')}]")
        if data.get("user"):
            user = data["user"]
            lines.append(f"   User ({user.get('content_length')} chars) "
                         f"[{user.get('timestamp')}]:")
            body = user.get("content") or user.get("content_preview") or ""
            lines.append("      " + body[:8000])

        if data.get("assistant"):
            ass = data["assistant"]
            lines.append(f"   Assistant ({ass.get('content_length')} chars) "
                         f"[{ass.get('timestamp')}] model={ass.get('model')}:")
            body = ass.get("content") or ass.get("content_preview") or ""
            lines.append("      " + body[:8000])

            if ass.get("thinking"):
                lines.append(f"   Thinking ({ass.get('thinking_length')} chars):")
                lines.append("      " + (ass.get("thinking") or "")[:4000])

        for tc in data.get("tool_calls") or []:
            lines.append(f"   ⚙ {tc.get('tool')} [{tc.get('status')}] id={tc.get('id')}")
            args = tc.get("arguments")
            if args:
                try:
                    lines.append("      args: " + json.dumps(args, ensure_ascii=False)[:600])
                except Exception:
                    lines.append(f"      args: {str(args)[:600]}")
            if tc.get("artifact"):
                lines.append(f"      artifact: {tc.get('artifact')}")
            body = tc.get("result") or tc.get("result_preview") or ""
            if body:
                lines.append(f"      result: {str(body)[:2000]}")
    
    elif action == "search":
        lines.append(f"🔍 Search '{data.get('query')}': {data.get('total_matches')} turns"
                     + (f", tokens={data.get('tokens')}" if data.get("tokens") else ""))
        for turn in data.get("turns", []):
            turn_id = turn.get("turn_id")
            score = turn.get("search_score", 0)
            matched_in = ", ".join(turn.get("matched_in", []))
            partial = " (частично)" if turn.get("partial") else ""
            lines.append(f"   Turn {turn_id} [{turn.get('timestamp_start')}] "
                         f"(score: {score}, in: {matched_in}){partial}")
            user = turn.get("user") or {}
            user_text = user.get("content") or user.get("content_preview") or ""
            if user_text:
                lines.append(f"      User: {' '.join(user_text.split())[:100]}")
            ass = turn.get("assistant") or {}
            ass_text = ass.get("content") or ass.get("content_preview") or ""
            if ass_text:
                lines.append(f"      Assistant: {' '.join(ass_text.split())[:100]}")

        files = data.get("files") or []
        if files:
            lines.append("   📄 Где именно (файл:строка, время):")
            for f in files:
                lines.append(f"      {f.get('file')}:{f.get('line')} [{f.get('timestamp')}]")
                lines.append(f"         {f.get('snippet', '')[:160]}")
    
    elif action == "stats":
        lines.append(f"📈 Session Statistics")
        lines.append(f"   Turns: {data.get('turns_count')}, Tool calls: {data.get('tool_calls_count')}")
        
        content = data.get("content", {})
        lines.append(f"   Content: {content.get('total_chars', 0)} chars total, {content.get('avg_per_turn', 0):.0f} avg/turn")
        
        thinking = data.get("thinking", {})
        lines.append(f"   Thinking: {thinking.get('total_chars', 0)} chars total, {thinking.get('avg_per_turn', 0):.0f} avg/turn")
        
        rt = data.get("response_time", {})
        lines.append(f"   Response time: {rt.get('avg_sec', 0):.1f}s avg, {rt.get('total_sec', 0):.1f}s total")
        
        tools = data.get("tools_distribution", {})
        if tools:
            lines.append(f"   Top tools:")
            for tool, count in sorted(tools.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"      • {tool}: {count}")
    
    elif action == "timeline":
        lines.append(f"⏱️ Timeline ({len(data.get('events', []))} of {data.get('total_events', 0)} events):")
        for event in data.get("events", []):
            ts = event.get("timestamp", "?")[11:19] if event.get("timestamp") else "?"
            etype = event.get("type")
            turn_id = event.get("turn_id")
            
            if etype == "user_message":
                preview = event.get("preview", "")[:50]
                lines.append(f"   [{ts}] Turn {turn_id} | User: {preview}...")
            elif etype == "assistant_message":
                model = event.get("model", "?")
                has_th = "🤔" if event.get("has_thinking") else ""
                lines.append(f"   [{ts}] Turn {turn_id} | Assistant ({model}) {has_th}")
            elif etype == "tool_call":
                tool = event.get("tool")
                status = event.get("status")
                lines.append(f"   [{ts}] Turn {turn_id} | Tool: {tool} ({status})")
    
    elif action == "chain":
        lines.append(f"🔗 Chain from turn {data.get('from_turn')} to {data.get('to_turn')} ({data.get('chain_length')} turns):")
        for turn in data.get("chain", []):
            turn_id = turn.get("turn_id")
            lines.append(f"   --- Turn {turn_id} ---")
            if turn.get("user", {}).get("content_preview"):
                lines.append(f"   User: {turn['user']['content_preview'][:60]}...")
            if turn.get("assistant", {}).get("content_preview"):
                lines.append(f"   Assistant: {turn['assistant']['content_preview'][:60]}...")
    
    else:
        # Для остальных действий — JSON
        return json.dumps(data, ensure_ascii=False, indent=2)

    advice = data.get("_advice")
    if advice:
        lines.append("")
        lines.append(f"💡 Совет: {advice}")

    hints = data.get("_next_actions")
    if hints:
        lines.append("")
        lines.append("➡ Следующие шаги (session_memory):")
        for h in hints:
            lines.append(f"   • {h}")

    return "\n".join(lines)


def _format_as_markdown(data: Dict, action: str) -> str:
    """Форматирует результат в Markdown"""
    lines = []
    
    if action == "summary":
        lines.append(f"# Session Summary\n")
        lines.append(f"**Path:** `{data.get('session_path')}`\n")
        lines.append(f"**Turns:** {data.get('total_turns')} | **Messages:** {data.get('total_messages')} | **Tool calls:** {data.get('total_tool_calls')}\n")
        lines.append(f"**Tokens:** {data.get('tokens', {}).get('total', 0)} total\n")
        
        tools = data.get('tools_used', {})
        if tools:
            lines.append(f"\n## Tools Used\n")
            for tool, count in sorted(tools.items(), key=lambda x: -x[1]):
                lines.append(f"- `{tool}`: {count}\n")
    
    elif action == "turns":
        lines.append(f"# Turns ({data.get('total')} total)\n")
        for turn in data.get("turns", []):
            turn_id = turn.get("turn_id")
            ts = turn.get("timestamp_start", "?")
            lines.append(f"## Turn {turn_id} ({ts})\n")
            
            if turn.get("user"):
                lines.append(f"**User:** {turn['user'].get('content_preview', '')[:100]}\n")
            if turn.get("assistant"):
                lines.append(f"**Assistant:** {turn['assistant'].get('content_preview', '')[:100]}\n")
    
    else:
        # Fallback to JSON in code block
        lines.append(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n")

    hints = data.get("_next_actions")
    if hints:
        lines.append("\n**Следующие шаги (session_memory):**\n")
        for h in hints:
            lines.append(f"- `{h}`\n")

    return "".join(lines)
