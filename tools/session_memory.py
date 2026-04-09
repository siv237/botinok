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
    status: str = "unknown"  # running | completed | failed

    @classmethod
    def from_tool_log_entry(cls, entry: Dict) -> "ToolCall":
        """Создаёт ToolCall из записи tools.log"""
        return cls(
            id=entry.get("call_id", f"tool_{entry.get('tool')}_{hash(str(entry))}"),
            tool=entry.get("tool", "unknown"),
            arguments=entry.get("arguments", {}),
            timestamp=entry.get("timestamp"),
            result_preview=str(entry.get("full_result", ""))[:200] if entry.get("full_result") else None,
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
        if self.result_preview:
            result["result_preview"] = self.result_preview
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
        
        return cls(
            role=entry.get("role", "unknown"),
            content=content_str if len(content_str) <= max_preview * 2 else None,
            content_preview=content_str[:max_preview] if len(content_str) > max_preview else None,
            content_length=len(content_str),
            thinking=thinking_str if thinking_str and len(thinking_str) <= max_preview * 2 else None,
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
        """Загружает context.json и tools.log"""
        context_path = os.path.join(self.session_path, "context.json")
        if os.path.exists(context_path):
            try:
                with open(context_path, "r", encoding="utf-8", errors="ignore") as f:
                    self.context_data = json.load(f)
            except Exception:
                self.context_data = {"history": []}
        else:
            self.context_data = {"history": []}
        
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
        """Парсит историю в список Turn объектов"""
        history = self.context_data.get("history", [])
        turns: List[Turn] = []
        current_turn: Optional[Turn] = None
        turn_counter = 0
        
        i = 0
        while i < len(history):
            entry = history[i]
            role = entry.get("role")
            
            if role == "user":
                # Новый turn начинается с user
                if current_turn is not None:
                    turns.append(current_turn)
                turn_counter += 1
                current_turn = Turn(
                    turn_id=turn_counter,
                    timestamp_start=entry.get("timestamp"),
                    user=MessagePart.from_context_entry(entry)
                )
                
            elif role == "assistant" and current_turn is not None:
                current_turn.assistant = MessagePart.from_context_entry(entry)
                current_turn.timestamp_end = entry.get("timestamp")
                
                # Считаем duration если есть оба timestamp
                if current_turn.timestamp_start and current_turn.timestamp_end:
                    try:
                        t1 = datetime.fromisoformat(current_turn.timestamp_start.replace("Z", "+00:00"))
                        t2 = datetime.fromisoformat(current_turn.timestamp_end.replace("Z", "+00:00"))
                        current_turn.duration_sec = round((t2 - t1).total_seconds(), 2)
                    except Exception:
                        pass
                
                # Ищем tool_calls в записи assistant
                tool_calls = entry.get("tool_calls", [])
                for tc in tool_calls:
                    tc_id = tc.get("id", f"tc_{len(current_turn.tool_calls)}")
                    tc_func = tc.get("function", {})
                    
                    # arguments может быть строкой или dict
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
                        timestamp=entry.get("timestamp")
                    ))
                
                turns.append(current_turn)
                current_turn = None
                
            i += 1
        
        # Добавляем незавершённый turn если есть
        if current_turn is not None:
            turns.append(current_turn)
        
        # Дополняем tool_calls из tools.log
        self._enrich_with_tools_log(turns)
        
        return turns
    
    def _enrich_with_tools_log(self, turns: List[Turn]):
        """Дополняет turns данными из tools.log"""
        for log_entry in self.tools_log:
            timestamp = log_entry.get("timestamp")
            tool_name = log_entry.get("tool")
            
            # Ищем ближайший turn по времени
            for turn in turns:
                if turn.timestamp_start and timestamp:
                    try:
                        t_turn = datetime.fromisoformat(turn.timestamp_start.replace("Z", "+00:00"))
                        t_log = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        
                        # Если tool_call в пределах turn (или сразу после)
                        if turn.timestamp_end:
                            t_end = datetime.fromisoformat(turn.timestamp_end.replace("Z", "+00:00"))
                            if t_log >= t_turn and t_log <= t_end:
                                # Обновляем или добавляем tool_call
                                self._update_tool_call(turn, log_entry)
                                break
                        elif abs((t_log - t_turn).total_seconds()) < 60:  # В пределах минуты
                            self._update_tool_call(turn, log_entry)
                            break
                    except Exception:
                        pass
    
    def _update_tool_call(self, turn: Turn, log_entry: Dict):
        """Обновляет существующий или добавляет новый ToolCall"""
        tool_name = log_entry.get("tool")
        arguments = log_entry.get("arguments", {})
        
        # Ищем существующий tool_call с таким же tool и аргументами
        for tc in turn.tool_calls:
            if tc.tool == tool_name:
                # Обновляем статус и результат
                tc.status = log_entry.get("status", tc.status)
                if log_entry.get("full_result"):
                    tc.result_preview = str(log_entry["full_result"])[:200]
                tc.timestamp = log_entry.get("timestamp", tc.timestamp)
                return
        
        # Добавляем новый если не нашли
        turn.tool_calls.append(ToolCall.from_tool_log_entry(log_entry))


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
    
    # Определяем путь к сессии
    if not session_path:
        # Ищем текущую сессию из переменных окружения или последнюю
        session_path = os.environ.get("BOTINOK_SESSION_PATH")
        if not session_path:
            # Ищем в стандартных местах
            from core.session_manager import SessionManager
            sm = SessionManager()
            latest = sm.get_latest_session()
            if latest:
                session_path = latest["path"]
    
    if not session_path or not os.path.exists(session_path):
        return json.dumps({"error": "Session path not found"}, ensure_ascii=False)
    
    # Получаем или строим индекс
    index = SessionIndex(session_path)
    turns = index.get_turns()
    
    # Выполняем action
    result = {}
    
    if action == "summary":
        result = _action_summary(turns, session_path)
    
    elif action == "turns":
        result = _action_turns(turns, limit, offset, include_content, include_thinking)
    
    elif action == "get_turn":
        result = _action_get_turn(turns, turn_id, include_content, include_thinking)
    
    elif action == "search":
        result = _action_search(turns, index, query, limit, include_content, include_thinking)
    
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
            "summary", "turns", "get_turn", "search", "filter", "timeline", "stats", "chain"
        ]}
    
    # Форматируем вывод
    if format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2)
    elif format == "markdown":
        return _format_as_markdown(result, action)
    else:  # structured
        if isinstance(result, dict) and "error" in result:
            return json.dumps(result, ensure_ascii=False)
        return _format_structured(result, action)


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
    """Получить конкретный turn по ID"""
    if turn_id is None:
        return {"error": "turn_id is required for get_turn action"}
    
    for turn in turns:
        if turn.turn_id == turn_id:
            return turn.to_dict(include_content, include_thinking)
    
    return {"error": f"Turn {turn_id} not found", "available_turns": [t.turn_id for t in turns]}


def _action_search(turns: List[Turn], index: SessionIndex, query: str, limit: int, include_content: bool, include_thinking: bool) -> Dict:
    """Поиск по turns"""
    if not query:
        return {"error": "query is required for search action"}
    
    query_lower = query.lower()
    matched_turns = []
    
    for turn in turns:
        matched_in = []
        score = 0
        
        # Поиск в user content
        if turn.user and turn.user.content and query_lower in turn.user.content.lower():
            matched_in.append("user_content")
            score += 3
        
        # Поиск в assistant content
        if turn.assistant:
            if turn.assistant.content and query_lower in turn.assistant.content.lower():
                matched_in.append("assistant_content")
                score += 3
            if turn.assistant.thinking and query_lower in turn.assistant.thinking.lower():
                matched_in.append("assistant_thinking")
                score += 2
        
        # Поиск в tool_calls
        for tc in turn.tool_calls:
            if query_lower in tc.tool.lower():
                matched_in.append(f"tool:{tc.tool}")
                score += 2
            for arg_val in tc.arguments.values():
                if query_lower in str(arg_val).lower():
                    matched_in.append("tool_arguments")
                    score += 1
        
        if matched_in:
            turn_dict = turn.to_dict(include_content, include_thinking)
            turn_dict["matched_in"] = matched_in
            turn_dict["search_score"] = score
            matched_turns.append(turn_dict)
    
    # Сортируем по score
    matched_turns.sort(key=lambda x: x.get("search_score", 0), reverse=True)
    
    return {
        "query": query,
        "total_matches": len(matched_turns),
        "turns": matched_turns[:limit]
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
    
    if action == "summary":
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
        lines.append(f"📋 Turn {data.get('turn_id')}:")
        if data.get("user"):
            user = data["user"]
            lines.append(f"   User ({user.get('content_length')} chars):")
            content = user.get("content", user.get("content_preview", ""))
            lines.append(f"      {content[:200]}...")
        
        if data.get("assistant"):
            ass = data["assistant"]
            lines.append(f"   Assistant ({ass.get('content_length')} chars, model: {ass.get('model')}):")
            content = ass.get("content", ass.get("content_preview", ""))
            lines.append(f"      {content[:200]}...")
            
            if ass.get("thinking"):
                lines.append(f"   Thinking ({ass.get('thinking_length')} chars):")
                lines.append(f"      {ass['thinking'][:200]}...")
        
        if data.get("tool_calls"):
            lines.append(f"   Tool calls ({len(data['tool_calls'])}):")
            for tc in data["tool_calls"]:
                lines.append(f"      • {tc.get('tool')}: {tc.get('status')}")
    
    elif action == "search":
        lines.append(f"🔍 Search results for '{data.get('query')}': {data.get('total_matches')} matches")
        for turn in data.get("turns", []):
            turn_id = turn.get("turn_id")
            score = turn.get("search_score", 0)
            matched_in = ", ".join(turn.get("matched_in", []))
            lines.append(f"   Turn {turn_id} (score: {score}, matched in: {matched_in})")
            
            user_preview = turn.get("user", {}).get("content_preview", "")
            if user_preview:
                lines.append(f"      User: {user_preview[:80]}...")
    
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
    
    return "".join(lines)
