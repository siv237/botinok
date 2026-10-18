"""
experience — Инструмент для накопления опыта работы ассистента

Автоматически записывает:
- POSITIVE: успешные решения после долгих поисков
- NEGATIVE: грабли и ошибки которых стоит избегать

Опыт хранится в ~/.botinok/experience/
"""

import os
import json
from datetime import datetime
from typing import Optional, List

def _experience_dir() -> str:
    """Папка с опытом — глобальная, над сессиями"""
    home = os.path.expanduser("~")
    exp_dir = os.path.join(home, ".botinok", "experience")
    os.makedirs(exp_dir, exist_ok=True)
    return exp_dir

def _ensure_structure():
    """Создать структуру папок если их нет"""
    exp_dir = _experience_dir()
    for subdir in ["positive", "negative", "tools", "patterns"]:
        os.makedirs(os.path.join(exp_dir, subdir), exist_ok=True)

def _format_timestamp(ts: str) -> str:
    """Форматирование timestamp в читаемый вид"""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts)
        return f"📅 {dt.strftime('%Y-%m-%d %H:%M')}"
    except:
        return f"📅 {ts}"

def _format_entry(entry: dict) -> str:
    """Форматирование записи опыта для отображения"""
    ts_str = _format_timestamp(entry.get('timestamp', ''))
    
    lines = [
        f"**{entry.get('title', 'Без названия')}**",
        f"🏷️ {', '.join(entry.get('tags', []))}",
    ]
    
    if ts_str:
        lines.append(ts_str)
    
    if entry.get('solution'):
        lines.append(f"\n💡 **Решение:**\n{entry.get('solution')}")
    
    if entry.get('error_context'):
        lines.append(f"\n❌ **Ошибка:**\n{entry.get('error_context')}")
    
    return "\n".join(lines)

def _update_index(exp_dir: str):
    """Обновление индекса опыта"""
    index_path = os.path.join(exp_dir, "index.json")
    index = {"positive": [], "negative": [], "updated": datetime.now().isoformat()}
    
    for subdir in ["positive", "negative"]:
        subpath = os.path.join(exp_dir, subdir)
        if not os.path.exists(subpath):
            continue
        for filename in os.listdir(subpath):
            if filename.endswith(".json"):
                filepath = os.path.join(subpath, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        entry = json.load(f)
                    index[subdir].append({
                        "filename": filename,
                        "title": entry.get("title", ""),
                        "tags": entry.get("tags", []),
                        "timestamp": entry.get("timestamp", ""),
                    })
                except:
                    pass
    
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

def experience(
    action: str,
    title: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
    solution: str = "",
    error_context: str = "",
) -> str:
    """
    Работа с базой опыта.
    
    Actions:
    - add_positive: записать успешный опыт (задача долго решалась, но получилось)
    - add_negative: записать ошибку/грабли
    - search: найти опыт по тегам или тексту
    - list: показать весь опыт
    - check: проверить есть ли опыт по теме (для использования в логике)
    
    Args:
        action: add_positive | add_negative | search | list | check
        title: краткое название (например "Битый MP3 определяется как валидный")
        description: что произошло
        tags: список тегов [audio, mp3, wget, file]
        solution: как решили проблему
        error_context: что пошло не так (для negative)
    """
    
    _ensure_structure()
    exp_dir = _experience_dir()
    
    if action == "add_positive":
        # Записываем успешный опыт
        entry = {
            "type": "positive",
            "title": title,
            "description": description,
            "tags": tags or [],
            "solution": solution,
            "timestamp": datetime.now().isoformat(),
        }
        
        # Имя файла = timestamp + первые слова title
        safe_title = "".join(c if c.isalnum() else "_" for c in title[:30])
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_title}.json"
        filepath = os.path.join(exp_dir, "positive", filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        
        # Обновляем индекс
        _update_index(exp_dir)
        
        return f"✅ Позитивный опыт записан:\n📁 {filepath}\n🏷️ Теги: {', '.join(tags or [])}\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    elif action == "add_negative":
        # Записываем ошибку
        entry = {
            "type": "negative",
            "title": title,
            "description": description,
            "tags": tags or [],
            "error_context": error_context,
            "timestamp": datetime.now().isoformat(),
        }
        
        safe_title = "".join(c if c.isalnum() else "_" for c in title[:30])
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_title}.json"
        filepath = os.path.join(exp_dir, "negative", filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        
        _update_index(exp_dir)
        
        return f"❌ Негативный опыт записан:\n📁 {filepath}\n🏷️ Теги: {', '.join(tags or [])}\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    elif action == "search":
        # Ищем опыт по тегам или тексту
        query = title  # используем title как поисковый запрос
        results = {"positive": [], "negative": []}
        
        for subdir in ["positive", "negative"]:
            subpath = os.path.join(exp_dir, subdir)
            if not os.path.exists(subpath):
                continue
            
            for filename in os.listdir(subpath):
                if not filename.endswith(".json"):
                    continue
                
                filepath = os.path.join(subpath, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        entry = json.load(f)
                    
                    # Ищем в тегах, названии, описании
                    search_text = " ".join([
                        entry.get("title", ""),
                        entry.get("description", ""),
                        " ".join(entry.get("tags", [])),
                        entry.get("solution", ""),
                        entry.get("error_context", ""),
                    ]).lower()
                    
                    if query.lower() in search_text:
                        results[subdir].append({
                            "filename": filename,
                            "title": entry.get("title"),
                            "tags": entry.get("tags", []),
                            "timestamp": entry.get("timestamp"),
                        })
                except Exception:
                    pass
        
        # Формируем ответ
        output = [f"🔍 Результаты поиска по: '{query}'\n"]
        
        if results["positive"]:
            output.append("✅ Позитивный опыт:")
            for r in results["positive"]:
                ts = _format_timestamp(r.get('timestamp', ''))
                output.append(f"  • {r['title']} {ts} — теги: {', '.join(r['tags'])}")
        
        if results["negative"]:
            output.append("\n❌ Негативный опыт:")
            for r in results["negative"]:
                ts = _format_timestamp(r.get('timestamp', ''))
                output.append(f"  • {r['title']} {ts} — теги: {', '.join(r['tags'])}")
        
        if not results["positive"] and not results["negative"]:
            output.append("Ничего не найдено.")
        
        return "\n".join(output)
    
    elif action == "list":
        # Показать весь опыт
        output = ["📚 База опыта:\n"]
        
        for subdir in ["positive", "negative"]:
            subpath = os.path.join(exp_dir, subdir)
            if not os.path.exists(subpath):
                continue
            
            entries = []
            for filename in os.listdir(subpath):
                if not filename.endswith(".json"):
                    continue
                filepath = os.path.join(subdir, filename)
                try:
                    with open(os.path.join(exp_dir, filepath), "r", encoding="utf-8") as f:
                        entry = json.load(f)
                    entries.append(entry)
                except:
                    pass
            
            # Сортируем по timestamp (новые сверху)
            entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            
            prefix = "✅" if subdir == "positive" else "❌"
            output.append(f"\n{prefix} {subdir.capitalize()}:")
            
            for entry in entries:
                ts = _format_timestamp(entry.get('timestamp', ''))
                output.append(f"  • {entry.get('title', 'Без названия')} {ts}")
                output.append(f"    🏷️ {', '.join(entry.get('tags', []))}")
        
        return "\n".join(output)
    
    elif action == "check":
        # Проверяем есть ли опыт по теме (для использования в логике)
        query = title  # используем title как поисковый запрос
        found = {"positive": [], "negative": []}
        
        for subdir in ["positive", "negative"]:
            subpath = os.path.join(exp_dir, subdir)
            if not os.path.exists(subpath):
                continue
            
            for filename in os.listdir(subpath):
                if not filename.endswith(".json"):
                    continue
                
                filepath = os.path.join(subpath, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        entry = json.load(f)
                    
                    search_text = " ".join([
                        entry.get("title", ""),
                        entry.get("description", ""),
                        " ".join(entry.get("tags", [])),
                        entry.get("solution", ""),
                        entry.get("error_context", ""),
                    ]).lower()
                    
                    if query.lower() in search_text:
                        found[subdir].append({
                            "title": entry.get("title"),
                            "tags": entry.get("tags", []),
                            "solution": entry.get("solution"),
                            "error_context": entry.get("error_context"),
                            "timestamp": entry.get("timestamp"),
                        })
                except Exception:
                    pass
        
        # Возвращаем в формате для JSON парсинга
        return json.dumps(found, ensure_ascii=False)
    
    else:
        return f"❓ Неизвестное действие: {action}"
