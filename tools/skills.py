#!/usr/bin/env python3
"""Skills manager - двухуровневая система скиллов (personal + project)"""

import os
import re
import json
import subprocess
import urllib.parse
from pathlib import Path
import io
from contextlib import redirect_stdout

# Директории
PERSONAL_DIR = Path.home() / ".botinok" / "skills"
PROJECT_DIR = Path("skills")  # относительно cwd

def ensure_dirs():
    PERSONAL_DIR.mkdir(parents=True, exist_ok=True)

# === UTILS ===

def find_skill(name):
    """Найти скилл: сначала personal, потом project"""
    personal_path = PERSONAL_DIR / name
    project_path = PROJECT_DIR / name
    
    if (personal_path / "SKILL.md").exists():
        return personal_path, "personal"
    elif (project_path / "SKILL.md").exists():
        return project_path, "project"
    elif personal_path.exists():
        # Есть папка но нет SKILL.md - ищем любой .md
        md_files = list(personal_path.glob("*.md"))
        if md_files:
            return personal_path, "personal"
        md_files = list(project_path.glob("*.md"))
        if md_files:
            return project_path, "project"
    
    return None, None

def get_skill_description(skill_dir):
    """Получить первое описание из SKILL.md"""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        md_files = list(skill_dir.glob("*.md"))
        if md_files:
            skill_file = md_files[0]
    
    if skill_file.exists():
        content = skill_file.read_text()
        # Берем первый # заголовок или первые 100 символов
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1)
        return content[:100].strip()
    return ""

def parse_search_results(html_content):
    """Parse DuckDuckGo HTML for GitHub SKILL.md links"""
    pattern = r'href="(https://github\.com/[^/]+/[^/]+/[^"]*SKILL\.md[^"]*)"'
    matches = re.findall(pattern, html_content, re.IGNORECASE)
    
    results = []
    seen = set()
    for url in matches:
        clean_url = url.split('&rut=')[0]
        if clean_url not in seen:
            seen.add(clean_url)
            # Extract owner/repo/path
            parts = clean_url.split('/')
            if len(parts) >= 6:
                owner = parts[3]
                repo = parts[4]
                path = '/'.join(parts[5:]).replace('blob/', '')
                results.append({
                    "url": clean_url,
                    "owner": owner,
                    "repo": repo,
                    "path": path,
                    "name": path.split('/')[-2] if '/' in path else repo
                })
    return results

def extract_github_info(url):
    """Extract owner/repo/branch/path from GitHub URL"""
    match = re.match(r'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)', url)
    if match:
        return match.groups()
    return None, None, None, None

def get_raw_url(github_url):
    """Convert github.com URL to raw.githubusercontent.com"""
    match = re.match(r'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)', github_url)
    if match:
        owner, repo, branch, path = match.groups()
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    return github_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")

def search_web(query):
    """Search for SKILL.md files using DuckDuckGo"""
    search_query = f'site:github.com "SKILL.md" {query}'
    encoded = urllib.parse.quote(search_query)
    url = f"https://duckduckgo.com/?q={encoded}&ia=web"
    
    try:
        result = subprocess.run(
            ["lynx", "-dump", "-nolist", url],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout
    except Exception as e:
        return f"Error: {e}"

def fetch_file(raw_url):
    """Download file content"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-L", raw_url],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout if result.returncode == 0 else None
    except:
        return None

# === COMMANDS ===

def cmd_list():
    """List all skills (personal overrides project)"""
    ensure_dirs()
    all_skills = {}
    
    # Сначала personal
    if PERSONAL_DIR.exists():
        for item in sorted(PERSONAL_DIR.iterdir()):
            if item.is_dir():
                desc = get_skill_description(item)
                all_skills[item.name] = {"source": "personal", "desc": desc}
    
    # Потом project (не перезаписываем personal)
    if PROJECT_DIR.exists():
        for item in sorted(PROJECT_DIR.iterdir()):
            if item.is_dir() and item.name not in all_skills:
                desc = get_skill_description(item)
                all_skills[item.name] = {"source": "project", "desc": desc}
    
    if not all_skills:
        print("📚 No skills found.")
        return []
    
    print("📚 Local skills:\n")
    for name, info in all_skills.items():
        source_icon = "👤" if info["source"] == "personal" else "📁"
        print(f"  {source_icon} [{info['source']}] {name}")
        if info["desc"]:
            print(f"      {info['desc'][:60]}...")
        print()
    
    return list(all_skills.keys())

def cmd_search(query):
    """Search GitHub for SKILL.md files"""
    print(f"🔍 Searching GitHub for: {query}")
    print()
    
    html = search_web(query)
    results = parse_search_results(html)
    
    if not results:
        print("❌ Nothing found. Try different keywords.")
        return []
    
    print(f"Found {len(results)} skills:\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['name']}")
        print(f"   {r['owner']}/{r['repo']}")
        print(f"   {r['path']}")
        print()
    
    return results

def cmd_get(name):
    """Show skill details"""
    skill_dir, source = find_skill(name)
    
    if not skill_dir:
        print(f"❌ Skill '{name}' not found.")
        return None
    
    # Найти главный .md файл
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        md_files = list(skill_dir.glob("*.md"))
        if md_files:
            skill_file = md_files[0]
    
    if skill_file.exists():
        content = skill_file.read_text()
        print(f"📄 [{source}] {name}\n")
        print(content)
        return str(skill_file)
    else:
        print(f"❌ No .md file in skill '{name}'")
    return None

def cmd_install(url, name=None):
    """Install a skill ONLY to personal directory"""
    owner, repo, branch, path = extract_github_info(url)
    
    if not owner:
        print(f"❌ Invalid GitHub URL: {url}")
        return False
    
    # Determine skill name
    if not name:
        parts = path.split('/')
        if len(parts) >= 2:
            name = parts[-2]
        else:
            name = repo
    
    skill_dir = PERSONAL_DIR / name
    ensure_dirs()
    
    print(f"📥 Installing to personal: {name}")
    
    # Fetch the SKILL.md
    raw_url = get_raw_url(url)
    content = fetch_file(raw_url)
    
    if not content:
        print(f"❌ Failed to download: {raw_url}")
        return False
    
    # Create skill directory
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    # Remove frontmatter if present
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    # Save SKILL.md
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    
    print(f"✅ Installed to {skill_file}")
    return True

def cmd_add(name, content):
    """Create/update a skill in personal directory"""
    ensure_dirs()
    skill_dir = PERSONAL_DIR / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    
    print(f"✅ Created/updated personal skill '{name}' at {skill_file}")
    return True

def cmd_remove(name):
    """Remove an installed personal skill"""
    skill_dir = PERSONAL_DIR / name
    
    if not skill_dir.exists():
        print(f"❌ Personal skill '{name}' not found.")
        return False
    
    import shutil
    shutil.rmtree(skill_dir)
    print(f"🗑️  Removed personal skill '{name}'")
    return True

def cmd_run(name, task):
    """Show skill content for execution"""
    skill_dir, source = find_skill(name)
    if not skill_dir:
        print(f"❌ Skill '{name}' not found.")
        return None
    
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        md_files = list(skill_dir.glob("*.md"))
        if md_files:
            skill_file = md_files[0]
    
    if skill_file.exists():
        print(f"🎯 Skill '{name}' [{source}]:")
        print(skill_file.read_text())
        return skill_file.read_text()
    return None


def skills(action, name=None, category=None, query=None, tags=None, description=None, tools=None, steps=None, url=None, task=None, content=None, **kwargs):
    buf = io.StringIO()
    with redirect_stdout(buf):
        ensure_dirs()

        if action == "list":
            result = cmd_list()
        elif action == "search":
            if not query:
                print("❌ Missing query")
                result = []
            else:
                result = cmd_search(query)
        elif action == "get":
            if not name:
                print("❌ Missing name")
                result = None
            else:
                result = cmd_get(name)
        elif action == "install":
            if not url:
                print("❌ Missing url")
                result = False
            else:
                result = cmd_install(url, name=name)
        elif action == "add":
            if not name:
                print("❌ Missing name")
                result = False
            else:
                if content is None:
                    lines = []
                    title = name
                    if category:
                        title = f"{category}/{name}"
                    lines.append(f"# {title}")
                    if description:
                        lines.append("")
                        lines.append(description)
                    if tools:
                        lines.append("")
                        lines.append("## Tools")
                        for t in tools:
                            lines.append(f"- {t}")
                    if steps:
                        lines.append("")
                        lines.append("## Steps")
                        for s in steps:
                            lines.append(f"- {s}")
                    content = "\n".join(lines).rstrip() + "\n"
                result = cmd_add(name, content)
        elif action == "remove":
            if not name:
                print("❌ Missing name")
                result = False
            else:
                result = cmd_remove(name)
        elif action == "run":
            if not name:
                print("❌ Missing name")
                result = None
            else:
                result = cmd_run(name, task or "")
        else:
            print(f"❌ Unknown action: {action}")
            result = None

    output = buf.getvalue()
    if output.strip():
        return output
    return result

# === MAIN ===

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: skills <command> [args]")
        print("Commands: list, search <query>, get <name>, install <url>, add <name> <content>, remove <name>, run <name>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    args = sys.argv[2:]
    
    ensure_dirs()
    
    if cmd == "list":
        cmd_list()
    elif cmd == "search" and args:
        cmd_search(" ".join(args))
    elif cmd == "get" and args:
        cmd_get(args[0])
    elif cmd == "install" and args:
        cmd_install(args[0], args[1] if len(args) > 1 else None)
    elif cmd == "add" and len(args) >= 2:
        cmd_add(args[0], " ".join(args[1:]))
    elif cmd == "remove" and args:
        cmd_remove(args[0])
    elif cmd == "run" and args:
        cmd_run(args[0], " ".join(args[1:]))
    else:
        print("Unknown command or missing arguments")
        sys.exit(1)
