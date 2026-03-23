"""
github — Инструмент для работы с GitHub API

Умеет:
- search_repos: искать репозитории
- get_repo: получить информацию о репозитории
- get_readme: получить README файлы
- get_file: получить содержимое файла
- get_tags: получить теги/версии
"""

import os
import json
import base64
import urllib.request
import urllib.parse

GITHUB_API = "https://api.github.com"

def _github_request(url: str) -> dict:
    """Сделать запрос к GitHub API"""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Botinok-AI/1.0"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "message": e.read().decode() if e.fp else str(e)}
    except Exception as e:
        return {"error": str(e)}

def github(
    action: str,
    query: str = "",
    repo: str = "",
    path: str = "",
    branch: str = "main",
    per_page: int = 5,
) -> str:
    """
    Работа с GitHub API.
    
    Actions:
    - search_repos: искать репозитории по запросу
    - get_repo: получить информацию о репозитории (owner/repo)
    - get_readme: получить README репозитория
    - get_file: получить содержимое файла
    - get_tags: получить теги/версии репозитория
    - get_branches: получить ветки репозитория
    
    Args:
        action: действие
        query: поисковый запрос (для search_repos)
        repo: полное имя репозитория owner/repo (для get_repo, get_readme, etc.)
        path: путь к файлу (для get_file)
        branch: ветка (по умолчанию main)
        per_page: количество результатов (для search)
    """
    
    if action == "search_repos":
        # Искать репозитории
        q = urllib.parse.quote(query)
        url = f"{GITHUB_API}/search/repositories?q={q}&sort=stars&per_page={per_page}"
        data = _github_request(url)
        
        if "error" in data:
            return f"❌ Ошибка: {data['error']}"
        
        items = data.get("items", [])
        if not items:
            return "🔍 Ничего не найдено"
        
        result = [f"🔍 Найдено {data.get('total_count', 0)} репозиториев:\n"]
        for r in items:
            result.append(
                f"  ⭐ {r['stargazers_count']:,} | {r['full_name']}\n"
                f"     {r.get('description', 'Без описания')[:80]}\n"
                f"     🏷️ {r.get('language', 'N/A')} | 🍴 {r['forks_count']}\n"
            )
        return "\n".join(result)
    
    elif action == "get_repo":
        # Информация о репозитории
        if not repo:
            return "❌ Укажи repo (owner/repo)"
        
        url = f"{GITHUB_API}/repos/{repo}"
        data = _github_request(url)
        
        if "error" in data:
            return f"❌ Ошибка: {data['error']}"
        if "message" in data and "error" in data.get("message", "").lower():
            return f"❌ {data.get('message', 'Репозиторий не найден')}"
        
        return (
            f"📦 {data['full_name']}\n"
            f"{'='*50}\n"
            f"⭐ {data['stargazers_count']:,} | 🍴 {data['forks_count']} | 👁️ {data['watchers_count']}\n"
            f"📝 {data.get('description', 'Нет описания')}\n"
            f"🏷️ Язык: {data.get('language', 'N/A')} | ⬇️ {data.get('downloads', 'N/A')}\n"
            f"🔗 {data['html_url']}\n"
            f"📅 Created: {data['created_at'][:10]} | Updated: {data['updated_at'][:10]}\n"
            f"🌿 Branch: {data.get('default_branch', 'main')}\n"
            f"📊 Open Issues: {data.get('open_issues_count', 0)}"
        )
    
    elif action == "get_readme":
        # Получить README
        if not repo:
            return "❌ Укажи repo (owner/repo)"
        
        url = f"{GITHUB_API}/repos/{repo}/readme"
        data = _github_request(url)
        
        if "error" in data:
            return f"❌ Ошибка: {data['error']}"
        
        # README может быть закодирован в base64
        if data.get("content"):
            content = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
            # Ограничиваем размер
            if len(content) > 5000:
                content = content[:5000] + "\n\n... [TRUNCATED]"
            return f"📝 README: {repo}\n{'='*50}\n{content}"
        
        return "❌ README не найден"
    
    elif action == "get_file":
        # Получить содержимое файла
        if not repo or not path:
            return "❌ Укажи repo и path"
        
        # URL encode путь
        encoded_path = urllib.parse.quote(path, safe='/')
        url = f"{GITHUB_API}/repos/{repo}/contents/{encoded_path}?ref={branch}"
        data = _github_request(url)
        
        if "error" in data:
            return f"❌ Ошибка: {data['error']}"
        
        if data.get("content"):
            content = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
            if len(content) > 5000:
                content = content[:5000] + "\n\n... [TRUNCATED]"
            return f"📄 {repo}/{path}\n{'='*50}\n{content}"
        
        if data.get("message"):
            return f"❌ {data['message']}"
        
        return "❌ Файл не найден"
    
    elif action == "get_tags":
        # Получить теги
        if not repo:
            return "❌ Укажи repo (owner/repo)"
        
        url = f"{GITHUB_API}/repos/{repo}/tags?per_page={per_page}"
        data = _github_request(url)
        
        if "error" in data:
            return f"❌ Ошибка: {data['error']}"
        
        if not data:
            return "📦 Нет тегов"
        
        result = [f"🏷️ Теги репозитория {repo}:\n"]
        for tag in data:
            result.append(f"  • {tag['name']} ({tag['commit']['sha'][:7]})")
        
        return "\n".join(result)
    
    elif action == "get_branches":
        # Получить ветки
        if not repo:
            return "❌ Укажи repo (owner/repo)"
        
        url = f"{GITHUB_API}/repos/{repo}/branches?per_page={per_page}"
        data = _github_request(url)
        
        if "error" in data:
            return f"❌ Ошибка: {data['error']}"
        
        if not data:
            return "🌿 Нет веток"
        
        result = [f"🌿 Ветки репозитория {repo}:\n"]
        for branch in data:
            protected = "🔒" if branch.get("protected") else "  "
            result.append(f"  {protected} {branch['name']}")
        
        return "\n".join(result)
    
    else:
        return (
            f"❌ Неизвестное действие: {action}\n"
            f"Доступные: search_repos, get_repo, get_readme, get_file, get_tags, get_branches"
        )
