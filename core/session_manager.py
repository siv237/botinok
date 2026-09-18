import os
import json
import time
import base64
import copy
import hashlib
import configparser
from datetime import datetime
from typing import Optional
import requests
import re

class SessionManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        
        # Приоритет конфигов: персональный > локальный > системный
        personal_config = os.path.expanduser("~/.config/botinok/config.cfg")
        local_config = "config.cfg"
        system_config = os.getenv("BOTINOK_CONFIG", "/opt/botinok/config.cfg")
        
        self.config_path = None
        self.config_source = None
        
        if os.path.exists(personal_config):
            self.config_path = personal_config
            self.config_source = "personal"
        elif os.path.exists(local_config):
            self.config_path = local_config
            self.config_source = "local"
        else:
            self.config_path = system_config
            self.config_source = "system"
            
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding='utf-8')
        else:
            # Дефолтные значения, если конфиг не найден
            self.config['Ollama'] = {'BaseUrl': 'http://localhost:11434', 'DefaultModel': 'qwen3.5:9b', 'DefaultContext': '8192'}
            self.config['Storage'] = {'SessionsDir': '~/.botinok/sessions', 'StepsSubDir': 'steps'}
            
        self.base_path = self.config.get('Storage', 'SessionsDir', fallback='sessions')
        # Разворачиваем ~ и $HOME для текущего пользователя
        self.base_path = os.path.expanduser(self.base_path)
        self.base_path = os.path.expandvars(self.base_path)
        self.last_chunk_time = None
        if not os.path.exists(self.base_path):
            try:
                os.makedirs(self.base_path)
            except PermissionError as e:
                parent = os.path.dirname(self.base_path)
                raise PermissionError(
                    f"Cannot create sessions directory: {self.base_path}\n"
                    f"Parent directory exists: {os.path.exists(parent)}\n"
                    f"If {parent} was created by root earlier, run:\n"
                    f"  sudo chown $(id -u):$(id -g) {parent}\n"
                    f"Or remove it: sudo rm -rf {parent}"
                ) from e

    @staticmethod
    def _session_marker_mtime(session_path: str) -> float:
        """«Честное» время последней активности сессии.

        mtime САМОГО КАТАЛОГА использовать нельзя: оно меняется при создании
        любого файла внутри (например .index/session_memory.idx, который пишет
        инструмент session_memory — в т.ч. для ЧУЖИХ сессий), но НЕ меняется
        при дозаписи в уже существующие файлы (context.json, tools.log,
        session_raw.log). Из-за этого свежесозданная пустая сессия могла
        оказаться «новее» реально активной и перехватить «Продолжить последнюю».

        Поэтому берём mtime самого значимого файла: context.json обновляется
        на каждом сообщении (update_context). Фоллбэки — response.md, tools.log,
        session_raw.log, и только потом mtime каталога.
        """
        for fname in ("context.json", "response.md", "tools.log", "session_raw.log"):
            try:
                return os.path.getmtime(os.path.join(session_path, fname))
            except OSError:
                continue
        try:
            return os.path.getmtime(session_path)
        except OSError:
            return 0

    def list_sessions(self):
        """Возвращает список существующих сессий в base_path (новые сверху)."""
        try:
            if not os.path.exists(self.base_path):
                return []
            items = []
            for name in os.listdir(self.base_path):
                p = os.path.join(self.base_path, name)
                if os.path.isdir(p):
                    items.append({
                        "name": name,
                        "path": p,
                        "mtime": self._session_marker_mtime(p),
                    })
            items.sort(key=lambda x: x.get("mtime", 0), reverse=True)
            return items
        except Exception:
            return []

    def get_latest_session(self):
        sessions = self.list_sessions()
        return sessions[0] if sessions else None

    def ensure_session_structure(self, session_path: str):
        """Гарантирует наличие стандартных подпапок в уже существующей сессии."""
        try:
            steps_subdir = self.config.get('Storage', 'StepsSubDir', fallback='steps')
            os.makedirs(os.path.join(session_path, steps_subdir), exist_ok=True)
            os.makedirs(os.path.join(session_path, "artifacts"), exist_ok=True)
            os.makedirs(os.path.join(session_path, "project"), exist_ok=True)
            os.makedirs(os.path.join(session_path, "proofreader"), exist_ok=True)
        except Exception:
            pass

    @staticmethod
    def _clean_answer(text: str) -> str:
        """Убирает из текста сессии YAML-метаданные и разделители ходов."""
        if not text:
            return ""
        s = str(text)
        s = re.sub(r"```yaml\s*\ntype:\s*BOTINOK_SESSION_METADATA.*?```", "", s, flags=re.S)
        s = re.sub(r"#{3,}\s*\n#\s*NEW TURN:.*?\n#{3,}\s*\n", "", s, flags=re.S)
        s = re.sub(r"^[ \t]*---[ \t]*$", "", s, flags=re.M)
        return s.strip()

    @staticmethod
    def _last_final_assistant(history: list) -> str:
        """Последний *завершённый* ответ ассистента (без tool_calls)."""
        for e in reversed(history):
            if e.get("role") != "assistant" or e.get("tool_calls"):
                continue
            content = str(e.get("content") or "").strip()
            if content:
                return content
        # Фолбэк: любой непустой ответ (в т.ч. промежуточный).
        for e in reversed(history):
            if e.get("role") == "assistant":
                content = str(e.get("content") or "").strip()
                if content:
                    return content
        return ""

    def load_last_assistant_answer(self, session_path: str, max_chars: int = 6000) -> str:
        """Пытается достать последний завершённый ответ ассистента.

        Приоритет:
        1) context.json — последний assistant без tool_calls (реальный финал);
        2) конец response.md (очищенный от YAML-метаданных турнов).
        """
        context_path = os.path.join(session_path, "context.json")
        try:
            if os.path.exists(context_path):
                with open(context_path, "r", encoding="utf-8", errors="ignore") as f:
                    ctx = json.load(f)
                hist = ctx.get("history", []) if isinstance(ctx, dict) else []
                content = self._clean_answer(self._last_final_assistant(hist))
                if content:
                    if len(content) > max_chars:
                        content = content[-max_chars:]
                    return content
        except Exception:
            pass

        response_path = os.path.join(session_path, "response.md")
        try:
            if os.path.exists(response_path):
                with open(response_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = self._clean_answer(f.read())
                if data:
                    if len(data) > max_chars:
                        data = data[-max_chars:]
                    return data
        except Exception:
            pass

        return ""

    def load_first_user_prompt(self, session_path: str, max_chars: int = 120) -> str:
        context_path = os.path.join(session_path, "context.json")
        try:
            if os.path.exists(context_path):
                with open(context_path, "r", encoding="utf-8", errors="ignore") as f:
                    ctx = json.load(f)
                hist = ctx.get("history", []) if isinstance(ctx, dict) else []
                for entry in hist:
                    if isinstance(entry, dict) and entry.get("role") == "user":
                        content = str(entry.get("content") or "").strip()
                        if content:
                            content = re.sub(r"\s+", " ", content)
                            if len(content) > max_chars:
                                content = content[:max_chars] + "..."
                            return content
        except Exception:
            pass

        response_path = os.path.join(session_path, "response.md")
        try:
            if os.path.exists(response_path):
                with open(response_path, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(60_000)
                m = re.search(r"^\s*prompt:\s*\|\s*\n(?P<body>(?:\s{2}.*\n)+)", head, re.MULTILINE)
                if m:
                    body = m.group("body")
                    lines = []
                    for ln in body.splitlines():
                        lines.append(ln[2:] if ln.startswith("  ") else ln)
                    content = "\n".join(lines).strip()
                    content = re.sub(r"\s+", " ", content)
                    if content:
                        if len(content) > max_chars:
                            content = content[:max_chars] + "..."
                        return content
        except Exception:
            pass

        return ""

    def ensure_session_subdir(self, session_path: str, subdir_name: str) -> str:
        subdir_path = os.path.join(session_path, subdir_name)
        if not os.path.exists(subdir_path):
            os.makedirs(subdir_path, exist_ok=True)
        return subdir_path

    def save_artifact(self, session_path: str, file_name: str, content: str) -> str:
        artifacts_dir = self.ensure_session_subdir(session_path, "artifacts")
        artifact_path = os.path.join(artifacts_dir, file_name)
        with open(artifact_path, "w", encoding="utf-8", errors="ignore") as f:
            f.write(str(content))
        return artifact_path
            
    def save_config(self):
        """Сохраняет текущую конфигурацию в файл."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def create_session(self, name=""):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{timestamp}_{name}" if name else timestamp
        session_path = os.path.join(self.base_path, session_name)
        
        steps_subdir = self.config.get('Storage', 'StepsSubDir', fallback='steps')
        os.makedirs(session_path)
        os.makedirs(os.path.join(session_path, steps_subdir))
        os.makedirs(os.path.join(session_path, "artifacts"))
        os.makedirs(os.path.join(session_path, "project"))
        os.makedirs(os.path.join(session_path, "proofreader"))
        
        # Копируем системные промпты в сессию
        self._copy_prompts_to_session(session_path)
        
        # Начальный контекст
        context = {
            "session_id": session_name,
            "created_at": timestamp,
            "history": []
        }
        
        with open(os.path.join(session_path, "context.json"), "w") as f:
            json.dump(context, f, indent=4)
            
        return session_path

    def _copy_prompts_to_session(self, session_path: str):
        """Копирует системные промпты из глобальной папки в сессию."""
        import shutil
        # Определяем путь к глобальным промптам
        if os.path.exists("prompts"):
            global_prompts = "prompts"
        else:
            # Ищем рядом с конфигом
            global_prompts = os.path.join(os.path.dirname(self.config_path), "prompts")
        
        session_prompts = os.path.join(session_path, "prompts")
        os.makedirs(session_prompts, exist_ok=True)
        
        if os.path.exists(global_prompts):
            for filename in os.listdir(global_prompts):
                if filename.endswith('.txt'):
                    src = os.path.join(global_prompts, filename)
                    dst = os.path.join(session_prompts, filename)
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass

    def load_prompt(self, session_path: str, prompt_name: str, **variables) -> str:
        """Загружает промпт из папки сессии и подставляет переменные."""
        prompt_file = os.path.join(session_path, "prompts", f"{prompt_name}.txt")
        
        # Fallback на глобальные промпты
        if not os.path.exists(prompt_file):
            if os.path.exists(f"prompts/{prompt_name}.txt"):
                prompt_file = f"prompts/{prompt_name}.txt"
            else:
                global_file = os.path.join(os.path.dirname(self.config_path), "prompts", f"{prompt_name}.txt")
                if os.path.exists(global_file):
                    prompt_file = global_file
                else:
                    return ""
        
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Подставляем переменные {{VAR_NAME}}
            for var_name, var_value in variables.items():
                content = content.replace(f"{{{{{var_name}}}}}", str(var_value))
            
            return content
        except Exception:
            return ""

    def get_ollama_status(self, base_url=None):
        if base_url is None:
            base_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        # Для OpenAI-совместимого бэкенда статус Ollama недоступен
        try:
            if self.config.get('Ollama', 'Backend', fallback='ollama').strip().lower() == 'openai':
                return None
        except Exception:
            pass
        verify_ssl = self.config.getboolean('Ollama', 'VerifySSL', fallback=True)
        try:
            response = requests.get(f"{base_url}/api/ps", timeout=5, verify=verify_ssl)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            pass
        return None

    def unload_models(self, base_url=None):
        """Выгружает все модели из памяти Ollama"""
        if base_url is None:
            base_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        verify_ssl = self.config.getboolean('Ollama', 'VerifySSL', fallback=True)
        status = self.get_ollama_status(base_url)
        if status and "models" in status:
            for m in status["models"]:
                try:
                    requests.post(f"{base_url}/api/generate", json={
                        "model": m["name"],
                        "keep_alive": 0
                    }, timeout=5, verify=verify_ssl)
                except Exception:
                    pass

    def log_chunk(self, session_path, chunk_type, content, metrics=None):
        """Логирует каждый отдельный чанк ответа в реальном времени с замером дельты."""
        log_file = os.path.join(session_path, "session_raw.log")
        now = datetime.now()
        
        delta = 0
        if self.last_chunk_time:
            delta = (now - self.last_chunk_time).total_seconds()
        self.last_chunk_time = now

        entry = {
            "timestamp": now.isoformat(),
            "delta_sec": round(delta, 4),
            "type": chunk_type,
            "content": content
        }
        if metrics:
            entry["metrics"] = metrics
            
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Инкрементальная запись в файлы thinking.md и response.md
        if chunk_type == "thinking":
            with open(os.path.join(session_path, "thinking.md"), "a", encoding="utf-8") as f:
                f.write(content)
        elif chunk_type == "response":
            with open(os.path.join(session_path, "response.md"), "a", encoding="utf-8") as f:
                f.write(content)

    def write_file_header(self, session_path, file_name, model, num_ctx, prompt):
        """Записывает технический заголовок в файл в формате Markdown. Если файл существует, добавляет разделитель."""
        file_path = os.path.join(session_path, file_name)
        exists = os.path.exists(file_path)
        
        mode = "a" if exists else "w"
        header = ""
        
        if exists:
            header += "\n\n" + "#" * 40 + "\n"
            header += f"# NEW TURN: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            header += "#" * 40 + "\n\n"

        header += (
            f"```yaml\n"
            f"type: BOTINOK_SESSION_METADATA\n"
            f"status: START\n"
            f"timestamp: {datetime.now().isoformat()}\n"
            f"model: {model}\n"
            f"context_limit: {num_ctx}\n"
            f"prompt: |\n"
            f"  {prompt}\n"
            f"```\n\n"
            f"---\n\n"
        )
        with open(file_path, mode, encoding="utf-8") as f:
            f.write(header)

    def write_file_footer(self, session_path, file_name, stats):
        """Записывает технический футер в файл в формате Markdown."""
        file_path = os.path.join(session_path, file_name)
        footer = (
            f"\n\n---\n\n"
            f"```yaml\n"
            f"type: BOTINOK_SESSION_METADATA\n"
            f"status: END\n"
            f"metrics:\n"
            f"  total_tokens: {stats.get('total_tokens')}\n"
            f"  thinking_tokens: {stats.get('thinking_tokens')}\n"
            f"  response_tokens: {stats.get('response_tokens')}\n"
            f"  average_tps: {stats.get('tps'):.2f}\n"
            f"  ttft: {stats.get('ttft'):.2f}s\n"
            f"  total_duration: {stats.get('duration'):.2f}s\n"
            f"files:\n"
            f"  thinking: \"./thinking.log\"\n"
            f"  response: \"./response.md\"\n"
            f"  raw_log: \"./session_raw.log\"\n"
            f"```\n"
        )
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(footer)

    def log_tool_call(self, session_path, tool_name, arguments, result, status="success", call_id=None):
        """Записывает подробный лог вызова инструмента в отдельный файл."""
        tool_log_file = os.path.join(session_path, "tools.log")
        
        # Вычисляем размер результата в КБ
        result_size_kb = len(str(result).encode('utf-8')) / 1024
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "arguments": arguments,
            "status": status,
            "size_kb": round(result_size_kb, 2),
            "full_result": str(result)
        }
        if call_id:
            entry["call_id"] = call_id
        with open(tool_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def update_context(self, session_path, role, content, thinking="", tool_calls=None,
                       tool_call_id=None, name=None, extra=None):
        context_path = os.path.join(session_path, "context.json")
        try:
            with open(context_path, "r") as f:
                context = json.load(f)

            entry = {
                "timestamp": datetime.now().isoformat(),
                "role": role,
                "content": content
            }
            if thinking:
                entry["thinking"] = thinking
            if tool_calls:
                entry["tool_calls"] = tool_calls
            if tool_call_id:
                entry["tool_call_id"] = tool_call_id
            if name:
                entry["name"] = name
            if extra:
                for k, v in extra.items():
                    if v is not None:
                        entry[k] = v

            history = context.setdefault("history", [])

            # Дедупликация подряд идущих одинаковых записей (напр. повторный
            # логинг одного и того же user-запроса при auto-continue/resume).
            # Не трогаем assistant-записи с tool_calls — они значимы сами по себе.
            if history and not tool_calls:
                last = history[-1]
                if (last.get("role") == role
                        and last.get("content") == content
                        and last.get("tool_call_id") == tool_call_id
                        and not last.get("tool_calls")):
                    return

            history.append(entry)

            with open(context_path, "w") as f:
                json.dump(context, f, indent=4, ensure_ascii=False)
        except Exception as e:
            pass

    def log_step(self, session_path, step_name, request_data, response_data, metrics):
        steps_subdir = self.config.get('Storage', 'StepsSubDir', fallback='steps')
        steps_dir = os.path.join(session_path, steps_subdir)
        os.makedirs(steps_dir, exist_ok=True)

        # Коллизии: несколько вызовов одного инструмента в пределах одной секунды
        # раньше писались в один и тот же файл (int(time.time())) и затирали друг
        # друга. Даём уникальное имя, не удаляя предыдущие шаги.
        step_file = os.path.join(steps_dir, f"{step_name}.json")
        if os.path.exists(step_file):
            i = 1
            while os.path.exists(os.path.join(steps_dir, f"{step_name}_{i}.json")):
                i += 1
            step_file = os.path.join(steps_dir, f"{step_name}_{i}.json")

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "request": request_data,
            "response": response_data,
            "metrics": metrics
        }
        
        with open(step_file, "w") as f:
            json.dump(log_entry, f, indent=4, ensure_ascii=False)
            
        # Обновляем общий лог производительности
        perf_file = os.path.join(session_path, "performance.log")
        with open(perf_file, "a", encoding="utf-8") as f:
            # Компактный JSON в одну строку для удобства tail -f
            perf_entry = {
                "step": step_name,
                "time": datetime.now().isoformat(),
                "tps": response_data.get("tps") if isinstance(response_data, dict) else None,
                "vram": response_data.get("vram_gb") if isinstance(response_data, dict) else None,
                "ctx": metrics.get("context_used") if isinstance(metrics, dict) else None
            }
            f.write(json.dumps(perf_entry, ensure_ascii=False) + "\n")

    def load_proofreader_history(self, session_path: str) -> list:
        """Загружает историю сообщений корректора."""
        path = os.path.join(session_path, "proofreader", "context.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("history", [])
            except Exception:
                return []
        return []

    def save_proofreader_history(self, session_path: str, history: list):
        """Сохраняет историю сообщений корректора."""
        path = os.path.join(session_path, "proofreader", "context.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"history": history}, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Канонический снапшот сообщений (100% восстановление сессии)
    # ------------------------------------------------------------------
    _MEDIA_EXT = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/ogg": "ogg",
        "audio/webm": "webm",
    }

    @staticmethod
    def _decode_media_blob(data):
        """Возвращает (bytes, mime|None) для data-url / base64 / bytes."""
        mime = None
        if isinstance(data, (bytes, bytearray)):
            return bytes(data), None
        if isinstance(data, str):
            s = data.strip()
            if s.startswith("data:"):
                head, _, payload = s.partition(",")
                mime = head[5:].split(";")[0] or None
                try:
                    return base64.b64decode(payload), mime
                except Exception:
                    return s.encode("utf-8", errors="ignore"), mime
            try:
                return base64.b64decode(s, validate=False), None
            except Exception:
                return s.encode("utf-8", errors="ignore"), None
        return None, None

    def save_media(self, session_path: str, data, mime: str = "", kind: str = "media") -> str:
        """Сохраняет медиа-блоб в artifacts и возвращает путь (или '' при неудаче)."""
        blob, detected = self._decode_media_blob(data)
        if not blob:
            return ""
        mime = mime or detected or ""
        ext = self._MEDIA_EXT.get(mime, "bin")
        # Имя по хэшу содержимого: повторное сохранение того же блоба не плодит
        # дубликаты (снапшот пишется каждый turn, медиа в нём то же самое).
        digest = hashlib.sha256(blob).hexdigest()[:16]
        name = f"media_{kind}_{digest}.{ext}"
        try:
            path = self.save_artifact(session_path, name, blob if isinstance(blob, str) else "")
            if not isinstance(blob, str):
                # save_artifact пишет текст; для бинарных данных пишем сами.
                artifacts_dir = self.ensure_session_subdir(session_path, "artifacts")
                path = os.path.join(artifacts_dir, name)
                with open(path, "wb") as f:
                    f.write(blob)
            return path
        except Exception:
            return ""

    def _externalize_media(self, session_path: str, messages: list) -> list:
        """Копия messages, где images/audios заменены на ссылки на файлы."""
        out = copy.deepcopy(messages)
        for msg in out:
            if not isinstance(msg, dict):
                continue
            for key, kind in (("images", "image"), ("audios", "audio")):
                items = msg.get(key)
                if not items or not isinstance(items, list):
                    continue
                refs = []
                for item in items:
                    if isinstance(item, dict) and item.get("media_ref"):
                        refs.append(item)
                        continue
                    mime = msg.get("mime_type", "") if key == "audios" else ""
                    path = self.save_media(session_path, item, mime=mime, kind=kind)
                    refs.append({"media_ref": path} if path else {"media_dropped": True})
                msg[key] = refs
        return out

    @staticmethod
    def _load_media_ref(ref: dict):
        path = ref.get("media_ref") or ""
        if not path or not os.path.isfile(path):
            return ref
        try:
            with open(path, "rb") as f:
                blob = f.read()
            ext = os.path.splitext(path)[1].lstrip(".").lower()
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "webp": "image/webp", "gif": "image/gif", "wav": "audio/wav",
                    "mp3": "audio/mpeg", "ogg": "audio/ogg", "webm": "audio/webm"}.get(ext, "application/octet-stream")
            return f"data:{mime};base64," + base64.b64encode(blob).decode("ascii")
        except Exception:
            return ref

    def save_messages_snapshot(self, session_path: str, messages: list, model: str = "", num_ctx=None) -> str:
        """Пишет канонический снапшот входного массива сообщений (messages.json).

        Медиа выносится в artifacts, чтобы снапшот оставался компактным, но
        полностью восстанавливаемым. Возвращает путь к файлу ('' при ошибке).
        """
        try:
            serializable = self._externalize_media(session_path, messages)
            payload = {
                "version": 1,
                "saved_at": datetime.now().isoformat(),
                "model": model,
                "context_limit": num_ctx,
                "messages": serializable,
            }
            path = os.path.join(session_path, "messages.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, path)
            return path
        except Exception:
            return ""

    def load_messages_snapshot(self, session_path: str):
        """Читает messages.json и восстанавливает медиа-ссылки. None если нет."""
        path = os.path.join(session_path, "messages.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return None
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            for key in ("images", "audios"):
                items = msg.get(key)
                if isinstance(items, list):
                    msg[key] = [self._load_media_ref(it) if isinstance(it, dict) else it for it in items]
        return messages

    def load_context_messages(self, session_path: str):
        """Восстанавливает LLM-сообщения из сессии.

        Приоритет: messages.json (канонический снапшот) → context.json.
        Для старых сессий (без tool_call_id и без messages.json) пары
        «tool_call ↔ tool_result» восстанавливаются по порядку, а недостающие
        результаты добираются из tools.log. Возвращает валидный список
        сообщений, пригодный для продолжения диалога.
        """
        snapshot = self.load_messages_snapshot(session_path)
        if snapshot is not None:
            return snapshot

        context_path = os.path.join(session_path, "context.json")
        try:
            with open(context_path, "r", encoding="utf-8") as f:
                context = json.load(f)
        except Exception:
            return []
        history = context.get("history", []) if isinstance(context, dict) else []
        tools_log = self.load_tools_log(session_path)
        messages = self.reconstruct_messages(history, tools_log=tools_log)
        # Рехидратация медиа-ссылок в data-url/base64 для API.
        for msg in messages:
            for key in ("images", "audios"):
                items = msg.get(key)
                if isinstance(items, list):
                    msg[key] = [self._load_media_ref(it) if isinstance(it, dict) else it
                                for it in items]
        return messages

    @staticmethod
    def _jc(v):
        """Канонический ключ сравнения аргументов (для матчинга tools.log)."""
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                return str(v).strip()
        try:
            return json.dumps(v, sort_keys=True, ensure_ascii=False)
        except Exception:
            return str(v)

    def load_tools_log(self, session_path: str) -> list:
        """Читает tools.log (list[dict]); [] если файла/строк нет."""
        path = os.path.join(session_path, "tools.log")
        entries = []
        if not os.path.exists(path):
            return entries
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass
        return entries

    @staticmethod
    def reconstruct_messages(history: list, tools_log: list = None):
        """Собирает валидные messages из записей context.json.

        Совместимо со старым форматом: если у tool-записи нет `tool_call_id`,
        он берётся из ближайшего assistant.tool_calls (по порядку и имени).
        Недостающие результаты добираются из tools.log; если и там пусто —
        подставляется явная заглушка, чтобы последовательность tool_calls →
        tool-результат осталась корректной.
        """
        messages = []
        pending = []  # [(call_id, name, args_json)] из последнего assistant.tool_calls
        # остатки tools.log, ещё не использованные: очередь по (name, args)
        log_index = {}
        if tools_log:
            for e in tools_log:
                if not isinstance(e, dict):
                    continue
                key = (str(e.get("tool", "")), SessionManager._jc(e.get("arguments")))
                log_index.setdefault(key, []).append(e)

        def _take_log_result(call_id, name, args_json):
            q = log_index.get((name, args_json))
            if q:
                e = q.pop(0)
                return str(e.get("full_result", ""))
            return ""

        def _flush_pending():
            # assistant.tool_calls остались без tool-записей — добавляем
            # синтетические tool-сообщения, чтобы диалог был валиден.
            nonlocal pending
            for (pid, pname, pargs) in pending:
                content = _take_log_result(pid, pname, pargs) or "[результат не сохранён]"
                messages.append({
                    "role": "tool",
                    "tool_call_id": pid,
                    "name": pname,
                    "content": content,
                })
            pending = []

        for entry in history:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            if role not in ("system", "user", "assistant", "tool"):
                continue

            if role != "tool" and pending:
                _flush_pending()

            msg = {"role": role, "content": entry.get("content", "")}

            if role == "assistant" and entry.get("tool_calls"):
                msg["tool_calls"] = entry["tool_calls"]
                pending = []
                for tc in entry["tool_calls"]:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function") or {}
                    pending.append((tc.get("id"), fn.get("name", ""),
                                    SessionManager._jc(fn.get("arguments"))))

            if role == "tool":
                tid = entry.get("tool_call_id")
                name = entry.get("name", "")
                if not tid and pending:
                    # старый формат: связываем по имени, иначе — по порядку
                    idx = next((i for i, (_, pn, _) in enumerate(pending) if name and pn == name), 0)
                    tid, pname, pargs = pending.pop(idx)
                    name = name or pname
                elif tid and pending:
                    idx = next((i for i, (p, _, _) in enumerate(pending) if p == tid), None)
                    if idx is not None:
                        pending.pop(idx)
                if tid:
                    msg["tool_call_id"] = tid
                if name:
                    msg["name"] = name

            if entry.get("media_kind"):
                msg["media_kind"] = entry["media_kind"]
            for key in ("images", "audios"):
                if entry.get(key):
                    msg[key] = entry[key]
            messages.append(msg)

        if pending:
            _flush_pending()
        return messages

    @staticmethod
    def strip_skills_mandate(text: str) -> str:
        """Убирает из промпта обязательную проверку skills/experience.

        Используется при возобновлении сессии: на восстановлении инструкции про
        проверку навыков модели не отправляются (а не «отменяются» другой
        инструкцией).
        """
        if not text:
            return text
        markers = (
            "skills action=list",
            "experience action=list",
            "проверяю наличие навыков",
            "обязан сначала проверить",
            "запрещено использовать",
            "обязательно: начни с",
        )
        kept = [ln for ln in text.splitlines()
                if not any(m in ln.lower() for m in markers)]
        result = "\n".join(kept)
        return re.sub(r"\n{3,}", "\n\n", result)

    @staticmethod
    def _human_duration(seconds) -> str:
        if seconds is None:
            return "неизвестно"
        seconds = int(max(0, seconds))
        d, rem = divmod(seconds, 86400)
        h, rem = divmod(rem, 3600)
        m, s = divmod(rem, 60)
        if d:
            return f"{d}д {h}ч {m}м"
        if h:
            return f"{h}ч {m}м"
        if m:
            return f"{m}м {s}с"
        return f"{s}с"

    def build_resume_brief(self, session_path: str, now: Optional[datetime] = None) -> dict:
        """Собирает компактную сводку для промпта восстановления сессии."""
        context_path = os.path.join(session_path, "context.json")
        history = []
        try:
            with open(context_path, "r", encoding="utf-8") as f:
                history = json.load(f).get("history", [])
        except Exception:
            history = []

        def _parse(ts):
            try:
                return datetime.fromisoformat(str(ts))
            except Exception:
                return None

        last_dt = None
        for e in history:
            t = _parse(e.get("timestamp"))
            if t and (last_dt is None or t > last_dt):
                last_dt = t
        if last_dt is None:
            for fname in ("context.json", "response.md", "tools.log", "session_raw.log"):
                p = os.path.join(session_path, fname)
                if os.path.exists(p):
                    t = datetime.fromtimestamp(os.path.getmtime(p))
                    if last_dt is None or t > last_dt:
                        last_dt = t

        now = now or datetime.now()
        elapsed = (now - last_dt).total_seconds() if last_dt else None

        # Ход считается завершённым только если последняя запись — финальный
        # ответ ассистента без tool_calls. Иначе сессия прервана (в т.ч. если
        # последняя запись — assistant с tool_calls, tool или user).
        last_entry = history[-1] if history else {}
        last_is_final = (last_entry.get("role") == "assistant"
                         and not last_entry.get("tool_calls")
                         and str(last_entry.get("content", "")).strip())
        state = ("завершена (последний ход закрыт)"
                 if last_is_final else "прервана на середине хода")

        first_user = next((str(e.get("content", "")) for e in history
                           if e.get("role") == "user" and str(e.get("content", "")).strip()), "")
        last_user = next((str(e.get("content", "")) for e in reversed(history)
                          if e.get("role") == "user" and str(e.get("content", "")).strip()), "")
        last_assistant = self._last_final_assistant(history)

        call_ids = [tc.get("id") for e in history if e.get("role") == "assistant"
                    for tc in (e.get("tool_calls") or []) if isinstance(tc, dict)]
        call_ids = [c for c in call_ids if c]
        tool_entries = sum(1 for e in history if e.get("role") == "tool")
        # Старые сессии не хранят tool_call_id, поэтому "пропажу" считаем по
        # числу tool-записей, а не по id (id-пары восстанавливаются на чтении).
        missing = max(0, len(call_ids) - tool_entries)

        def _clip(s, n=600):
            s = (s or "").strip().replace("\r", "")
            return s if len(s) <= n else s[:n] + "…"

        return {
            "SESSION_NAME": os.path.basename(os.path.normpath(session_path)),
            "SESSION_PATH": session_path,
            "RESUME_STATE": state,
            "LAST_ACTIVITY": last_dt.isoformat() if last_dt else "неизвестно",
            "NOW": now.isoformat(),
            "ELAPSED": self._human_duration(elapsed),
            "ORIGINAL_TASK": _clip(first_user),
            "LAST_USER_PROMPT": _clip(last_user),
            # Последний финальный ответ даём целиком (до 4000), иначе агент
            # начинает перечитывать свой отчёт из файлов вместо продолжения.
            "LAST_ASSISTANT_ANSWER": _clip(last_assistant, 4000),
            "HISTORY_LEN": len(history),
            "TOOL_CALLS": len([c for c in call_ids if c]),
            "TOOL_CALLS_MISSING": missing,
        }

    def restore_session(self, session_path: str) -> dict:
        """Формализованное точное восстановление контекста сессии.

        Источник истины — канонический снапшот `messages.json` (exact=True).
        Если его нет (старая сессия) — реконструкция из `context.json`
        (exact=False, derived). Возвращает сам массив сообщений, поэтому
        вызывающий может отличить точный результат от наметки.
        """
        snap_path = os.path.join(session_path, "messages.json")
        payload = None
        if os.path.exists(snap_path):
            try:
                with open(snap_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                payload = None
        if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
            messages = self.load_messages_snapshot(session_path) or []
            saved_at = payload.get("saved_at") or ""
            # Снапшот пишется в конце хода: прерванный ход в него не попадает.
            # Помечаем, что context.json ушёл вперёд, чтобы не считать снапшот
            # полным на момент прерывания.
            last_ctx_ts = ""
            try:
                with open(os.path.join(session_path, "context.json"), "r",
                          encoding="utf-8") as f:
                    hist = json.load(f).get("history", [])
                if hist:
                    last_ctx_ts = str(hist[-1].get("timestamp") or "")
            except Exception:
                pass
            return {
                "source": "messages.json",
                "exact": True,
                "model": payload.get("model"),
                "context_limit": payload.get("context_limit"),
                "saved_at": payload.get("saved_at"),
                "stale": bool(saved_at and last_ctx_ts and last_ctx_ts > saved_at),
                "last_context_timestamp": last_ctx_ts or None,
                "messages": messages,
            }
        messages = self.load_context_messages(session_path)
        return {
            "source": "context.json",
            "exact": False,
            "model": None,
            "context_limit": None,
            "saved_at": None,
            "messages": messages,
        }

    def audit_context(self, session_path: str) -> dict:
        """Проверка восстановимости: сколько tool-вызовов без пары/результата."""
        context_path = os.path.join(session_path, "context.json")
        try:
            with open(context_path, "r", encoding="utf-8") as f:
                history = json.load(f).get("history", [])
        except Exception:
            history = []
        call_ids = []
        for e in history:
            if e.get("role") == "assistant":
                for tc in (e.get("tool_calls") or []):
                    if isinstance(tc, dict):
                        call_ids.append(tc.get("id"))
        result_ids = [e.get("tool_call_id") for e in history
                      if e.get("role") == "tool" and e.get("tool_call_id")]
        missing_ids = [c for c in call_ids if c and c not in result_ids]
        return {
            "tool_calls": len(call_ids),
            "tool_results_with_id": len(result_ids),
            "tool_calls_without_result": len(missing_ids),
            "missing_ids": missing_ids,
        }
