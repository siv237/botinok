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

PERSONAL_DIR = Path.home() / ".botinok" / "skills"
PROJECT_DIR = Path("skills")

def ensure_dirs():
    PERSONAL_DIR.mkdir(parents=True, exist_ok=True)

def find_skill(name):
    personal_path = PERSONAL_DIR / name
    project_path = PROJECT_DIR / name
    if (personal_path / "SKILL.md").exists():
        return personal_path, "personal"
    elif (project_path / "SKILL.md").exists():
        return project_path, "project"
    elif personal_path.exists():
        md_files = list(personal_path.glob("*.md"))
        if md_files:
            return personal_path, "personal"
        md_files = list(project_path.glob("*.md"))
        if md_files:
            return project_path, "project"
    return None, None

def get_skill_description(skill_dir):
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        md_files = list(skill_dir.glob("*.md"))
        if md_files:
            skill_file = md_files[0]
    if skill_file.exists():
        content = skill_file.read_text()
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1)
        return content[:100].strip()
    return ""

def get_raw_url(github_url):
    match = re.match(r'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)', github_url)
    if match:
        owner, repo, branch, path = match.groups()
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    return github_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")

def fetch_file(raw_url):
    try:
        result = subprocess.run(["curl", "-s", "-L", raw_url], capture_output=True, text=True, timeout=30)
        return result.stdout if result.returncode == 0 else None
    except:
        return None

# === CLAWHUB API ===
CLAWHUB_API = "https://clawhub.ai/api/v1"

def clawhub_search(query: str, limit: int = 10) -> list:
    import urllib.request
    url = f"{CLAWHUB_API}/search?q={urllib.parse.quote(query)}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("results", [])
    except Exception as e:
        return [{"error": str(e)}]

def clawhub_explore(limit: int = 10, sort: str = "newest") -> list:
    import urllib.request
    url = f"{CLAWHUB_API}/skills?limit={limit}&sort={sort}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("skills", data) if isinstance(data, dict) else data
    except Exception as e:
        return [{"error": str(e)}]

def clawhub_install(slug: str) -> bool:
    import urllib.request
    import zipfile
    
    # Get skill metadata
    url = f"{CLAWHUB_API}/skills/{slug}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Failed to fetch skill metadata: {e}")
        return False
    
    if isinstance(data, dict) and "error" in data:
        print(f"Skill not found: {slug}")
        return False
    
    ensure_dirs()
    skill_dir = PERSONAL_DIR / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    # Download zip from clawhub
    download_url = f"{CLAWHUB_API}/download?slug={slug}"
    zip_path = skill_dir / "temp_download.zip"
    
    try:
        with urllib.request.urlopen(download_url, timeout=30) as resp:
            zip_data = resp.read()
        zip_path.write_bytes(zip_data)
    except Exception as e:
        print(f"Failed to download skill: {e}")
        return False
    
    # Extract zip
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Clean old files
            for f in skill_dir.iterdir():
                if f.name != "temp_download.zip":
                    if f.is_file():
                        f.unlink()
                    elif f.is_dir():
                        import shutil
                        shutil.rmtree(f)
            
            zf.extractall(skill_dir)
            
            zf.extractall(skill_dir)
        
        # Remove temp zip
        zip_path.unlink()
        
        # If extracted content has single dir, move files up
        contents = list(skill_dir.iterdir())
        if len(contents) == 1 and contents[0].is_dir():
            inner_dir = contents[0]
            for f in inner_dir.iterdir():
                f.rename(skill_dir / f.name)
            inner_dir.rmdir()
        
        print(f"Installed: {slug}")
        return True
        
    except Exception as e:
        print(f"Failed to extract skill: {e}")
        if zip_path.exists():
            zip_path.unlink()
        return False

# === COMMANDS ===

def cmd_list():
    ensure_dirs()
    all_skills = {}
    if PERSONAL_DIR.exists():
        for item in sorted(PERSONAL_DIR.iterdir()):
            if item.is_dir():
                desc = get_skill_description(item)
                all_skills[item.name] = {"source": "personal", "desc": desc}
    if PROJECT_DIR.exists():
        for item in sorted(PROJECT_DIR.iterdir()):
            if item.is_dir() and item.name not in all_skills:
                desc = get_skill_description(item)
                all_skills[item.name] = {"source": "project", "desc": desc}
    if not all_skills:
        print("No skills found.")
        return []
    print("Local skills:\n")
    for name, info in all_skills.items():
        source_icon = "personal" if info["source"] == "personal" else "project"
        print(f"  {source_icon} {name}: {info['desc']}")
    return list(all_skills.keys())

def cmd_get(name):
    path, source = find_skill(name)
    if not path:
        print(f"Skill not found: {name}")
        return None
    skill_file = path / "SKILL.md"
    if not skill_file.exists():
        md_files = list(path.glob("*.md"))
        if md_files:
            skill_file = md_files[0]
    if skill_file.exists():
        content = skill_file.read_text()
        print(f"{name} ({source}):\n")
        print(content[:2000])
        if len(content) > 2000:
            print(f"\n... [{len(content) - 2000} more chars]")
        return content
    return None

def cmd_add(name: str, url: str = None, content: str = None) -> bool:
    ensure_dirs()
    skill_dir = PERSONAL_DIR / name
    if skill_dir.exists():
        print(f"Skill already exists: {name}")
        return False
    skill_dir.mkdir(parents=True, exist_ok=True)
    if url:
        raw_url = get_raw_url(url) if "github.com" in url else url
        file_content = fetch_file(raw_url)
        if file_content:
            (skill_dir / "SKILL.md").write_text(file_content)
            print(f"Added skill from URL: {name}")
            return True
        else:
            print(f"Failed to fetch: {url}")
            skill_dir.rmdir()
            return False
    if content:
        (skill_dir / "SKILL.md").write_text(content)
        print(f"Added skill from content: {name}")
        return True
    print("Need url or content")
    skill_dir.rmdir()
    return False

def cmd_remove(name: str) -> bool:
    path, source = find_skill(name)
    if not path:
        print(f"Skill not found: {name}")
        return False
    if source != "personal":
        print(f"Can only remove personal skills (not {source})")
        return False
    import shutil
    shutil.rmtree(path)
    print(f"Removed skill: {name}")
    return True

def cmd_run(name: str, task: str = "") -> str:
    path, source = find_skill(name)
    if not path:
        return f"Skill not found: {name}"
    skill_file = path / "SKILL.md"
    if not skill_file.exists():
        md_files = list(path.glob("*.md"))
        if md_files:
            skill_file = md_files[0]
    if not skill_file.exists():
        return f"No SKILL.md in: {name}"
    content = skill_file.read_text()
    if not task:
        return f"{name} content:\n\n{content}"
    return f"{name} (for task: {task}):\n\n{content}"

def cmd_clawhub_search(query: str, limit: int = 10) -> list:
    results = clawhub_search(query, limit)
    if not results:
        print("No results found.")
        return []
    if results and isinstance(results[0], dict) and "error" in results[0]:
        print(f"Error: {results[0]['error']}")
        return []
    print(f"ClawHub results for '{query}' (total: {len(results)}):\n")
    output = []
    for r in results:
        # ClawHub API returns: displayName, summary, slug, tags
        name = r.get("displayName") or r.get("name", "?")
        desc = r.get("summary") or r.get("description", "N/A")
        desc_short = desc[:80] + "..." if len(desc) > 80 else desc
        slug = r.get("slug", "")
        tags = r.get("tags", [])
        tags_str = ", ".join(tags[:3]) if tags else "none"
        output.append(f"{name}")
        output.append(f"   {desc_short}")
        output.append(f"   slug: {slug} | tags: {tags_str}")
        output.append("")
    return output

def cmd_clawhub_explore(limit: int = 10, sort: str = "newest") -> list:
    results = clawhub_explore(limit, sort)
    if not results:
        print("No results found.")
        return []
    if results and isinstance(results[0], dict) and "error" in results[0]:
        print(f"Error: {results[0]['error']}")
        return []
    print(f"Latest skills on ClawHub (sort: {sort}):\n")
    output = []
    for r in results:
        name = r.get("displayName") or r.get("name", "?")
        desc = r.get("summary") or r.get("description", "N/A")
        desc_short = desc[:80] + "..." if len(desc) > 80 else desc
        slug = r.get("slug", "")
        tags = r.get("tags", [])
        tags_str = ", ".join(tags[:3]) if tags else "none"
        output.append(f"{name}")
        output.append(f"   {desc_short}")
        output.append(f"   slug: {slug} | tags: {tags_str}")
        output.append("")
    return output

# === MAIN SKILLS FUNCTION ===

def skills(action=None, name=None, query=None, url=None, content=None, task=None, limit=None, sort=None) -> list:
    ensure_dirs()
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = None
        if action == "list":
            result = cmd_list()
        elif action == "get":
            if not name:
                print("Missing name")
                result = None
            else:
                result = cmd_get(name)
        elif action == "add":
            if not name:
                print("Missing name")
                result = False
            else:
                result = cmd_add(name, url, content)
        elif action == "remove":
            if not name:
                print("Missing name")
                result = False
            else:
                result = cmd_remove(name)
        elif action == "run":
            if not name:
                print("Missing name")
                result = None
            else:
                result = cmd_run(name, task)
        elif action == "clawhub" or action == "search":
            if query:
                result = cmd_clawhub_search(query, limit=limit or 10)
            elif name == "explore":
                result = cmd_clawhub_explore(limit=limit or 10, sort=sort or "newest")
            else:
                print("Use: action='clawhub', query='search term' or name='explore'")
                result = []
        elif action == "install-clawhub":
            if not name:
                print("Missing name (slug)")
                result = False
            else:
                result = clawhub_install(name)
        else:
            print(f"Unknown action: {action}")
            result = None
    output = buf.getvalue()
    result_text = ""
    if isinstance(result, list):
        result_text = "\n".join(str(x) for x in result if x is not None)
    elif result is not None:
        result_text = str(result)

    combined = (output or "") + (result_text if result_text else "")
    if combined.strip():
        return combined
    return None

if __name__ == "__main__":
    import sys
    kwargs = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kwargs[k] = v
    if "action" not in kwargs and kwargs:
        kwargs = {"action": list(kwargs.keys())[0], **kwargs}
    result = skills(**kwargs)
    if result:
        print(result)
