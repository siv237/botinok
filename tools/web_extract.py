#!/usr/bin/env python3
"""
Веб-экстрактор ресурсов. Извлекает структурированные данные со страниц
используя httpx + selectolax (быстрый парсер на C).

Usage:
  web_extract(url="https://example.com", extract=["links", "images"])
  web_extract(url="...", extract=["all"], max_items=50)
  web_extract(url="...", extract=["tables"], timeout_sec=15)

Returns:
  Структурированный markdown с извлеченными ресурсами
"""

import os
import sys
from typing import List, Optional
from urllib.parse import urljoin, urlparse

try:
    import httpx
except ImportError:
    httpx = None

try:
    from selectolax.parser import HTMLParser
except ImportError:
    HTMLParser = None


def _debug(msg: str):
    """Выводит отладочное сообщение если включен BOTINOK_DEBUG."""
    if os.environ.get("BOTINOK_DEBUG"):
        print(f"DEBUG: {msg}", file=sys.stderr)


def execute(
    url: str,
    extract: List[str] = None,
    max_items: int = 100,
    timeout_sec: int = 15,
    headers: List[str] = None,
    session_path: str = None,
) -> str:
    """
    Извлекает ресурсы с веб-страницы.
    
    Args:
        url: URL страницы (http/https)
        extract: Что извлекать - "links", "images", "headings", "meta", "tables", "all"
        max_items: Максимальное количество элементов на категорию
        timeout_sec: Таймаут запроса в секундах
        headers: HTTP заголовки (опционально, формат "Key: Value")
        session_path: Путь сессии для сохранения дампа (опционально)
    """
    if httpx is None:
        return "❌ Error: httpx not installed. Run: pip install httpx"
    if HTMLParser is None:
        return "❌ Error: selectolax not installed. Run: pip install selectolax"
    
    if not url.startswith(('http://', 'https://')):
        return "❌ Error: URL must start with http:// or https://"
    
    if extract is None:
        extract = ["all"]
    
    # Нормализуем extract
    extract_all = "all" in extract
    want_links = extract_all or "links" in extract
    want_images = extract_all or "images" in extract
    want_headings = extract_all or "headings" in extract
    want_meta = extract_all or "meta" in extract
    want_tables = extract_all or "tables" in extract
    
    # Парсим заголовки
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    if headers:
        for h in headers:
            if ':' in h:
                key, value = h.split(':', 1)
                request_headers[key.strip()] = value.strip()
    
    try:
        _debug(f"Fetching URL: {url}")
        
        with httpx.Client(follow_redirects=True, timeout=timeout_sec) as client:
            resp = client.get(url, headers=request_headers)
            resp.raise_for_status()
        
        content_type = resp.headers.get('content-type', '').lower()
        if 'text/html' not in content_type and 'application/xhtml' not in content_type:
            # Пробуем парсить всё равно если похоже на HTML
            if not resp.text.strip().startswith('<!') and not resp.text.strip().startswith('<'):
                return f"⚠️ Warning: Content-Type is {content_type}, not HTML. Skipping."
        
        # Парсим HTML
        tree = HTMLParser(resp.text)
        base_url = str(resp.url)  # Финальный URL после редиректов
        
        results = []
        results.append(f"# 🌐 Resource Extract: {url}")
        if base_url != url:
            results.append(f"**Final URL:** {base_url}")
        results.append("")
        
        total_extracted = 0
        
        # 1. Meta теги
        if want_meta:
            _debug("Extracting meta tags...")
            meta_items = []
            
            # Стандартные meta
            for node in tree.css('meta[name], meta[property]'):
                name = (node.attributes.get('name') or node.attributes.get('property') or '').strip()
                content = (node.attributes.get('content') or '').strip()
                if name and content:
                    meta_items.append((name, content))
            
            # Title
            title_node = tree.css_first('title')
            if title_node:
                title_text = title_node.text(strip=True)
                if title_text:
                    meta_items.insert(0, ('title', title_text))
            
            # Description
            desc_node = tree.css_first('meta[name="description"]')
            if desc_node:
                meta_items.insert(1, ('description', desc_node.attributes.get('content', '')))
            
            if meta_items:
                results.append("## 📋 Meta Information")
                results.append("")
                for name, content in meta_items[:max_items]:
                    # Транкейтим длинный контент
                    display_content = content[:300] + "..." if len(content) > 300 else content
                    display_content = display_content.replace('\n', ' ').replace('\r', '')
                    results.append(f"- **{name}:** {display_content}")
                results.append("")
                total_extracted += len(meta_items[:max_items])
        
        # 2. Заголовки h1-h6
        if want_headings:
            _debug("Extracting headings...")
            headings = []
            for level in range(1, 7):
                for node in tree.css(f'h{level}'):
                    text = node.text(strip=True) or ""
                    if text:
                        headings.append((level, text))
            
            if headings:
                results.append("## 📑 Headings")
                results.append("")
                for level, text in headings[:max_items]:
                    indent = "  " * (level - 1)
                    # Транкейтим длинные заголовки
                    display_text = text[:200] + "..." if len(text) > 200 else text
                    display_text = display_text.replace('\n', ' ')
                    results.append(f"{indent}- **H{level}:** {display_text}")
                results.append("")
                total_extracted += len(headings[:max_items])
        
        # 3. Ссылки
        if want_links:
            _debug("Extracting links...")
            links = []
            for node in tree.css('a[href]'):
                href = node.attributes.get('href', '').strip()
                text = node.text(strip=True) or ""
                
                if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                    continue
                
                # Абсолютный URL
                full_url = urljoin(base_url, href)
                
                # Пропускаем внешние ссылки если их много (оставляем домен)
                parsed_base = urlparse(base_url)
                parsed_link = urlparse(full_url)
                
                # Транкейтим длинный текст
                display_text = text[:80] + "..." if len(text) > 80 else text
                if not display_text:
                    display_text = "[no text]"
                
                links.append((display_text, full_url))
            
            if links:
                # Убираем дубликаты по URL
                seen_urls = set()
                unique_links = []
                for text, link_url in links:
                    if link_url not in seen_urls:
                        seen_urls.add(link_url)
                        unique_links.append((text, link_url))
                
                results.append("## 🔗 Links")
                results.append("")
                for text, link_url in unique_links[:max_items]:
                    results.append(f"- [{text}]({link_url})")
                results.append("")
                total_extracted += len(unique_links[:max_items])
        
        # 4. Картинки
        if want_images:
            _debug("Extracting images...")
            images = []
            for node in tree.css('img[src]'):
                src = (node.attributes.get('src') or '').strip()
                alt = (node.attributes.get('alt') or '').strip()
                title = (node.attributes.get('title') or '').strip()
                
                if not src:
                    continue
                
                full_url = urljoin(base_url, src)
                caption = alt or title or "[no caption]"
                caption = caption[:100] + "..." if len(caption) > 100 else caption
                
                images.append((caption, full_url))
            
            if images:
                # Убираем дубликаты
                seen_urls = set()
                unique_images = []
                for caption, img_url in images:
                    if img_url not in seen_urls:
                        seen_urls.add(img_url)
                        unique_images.append((caption, img_url))
                
                results.append("## 🖼️ Images")
                results.append("")
                for caption, img_url in unique_images[:max_items]:
                    results.append(f"- {caption}: `{img_url}`")
                results.append("")
                total_extracted += len(unique_images[:max_items])
        
        # 5. Таблицы
        if want_tables:
            _debug("Extracting tables...")
            tables = []
            for table in tree.css('table'):
                rows_data = []
                # Ищем заголовки
                headers = []
                thead = table.css_first('thead')
                if thead:
                    for th in thead.css('th'):
                        th_text = th.text(strip=True)
                        if th_text:
                            headers.append(th_text)
                
                # Если нет thead, берем первую строку
                if not headers:
                    first_row = table.css_first('tr')
                    if first_row:
                        for cell in first_row.css('th, td'):
                            cell_text = cell.text(strip=True)
                            if cell_text:
                                headers.append(cell_text)
                
                # Данные
                rows = []
                tbody = table.css_first('tbody') or table
                start_idx = 0 if thead else 1
                for i, row in enumerate(tbody.css('tr')):
                    if i < start_idx:
                        continue
                    cells = []
                    for cell in row.css('td, th'):
                        text = cell.text(strip=True) or ""
                        text = text.replace('\n', ' ').replace('\r', '')
                        cells.append(text[:100])  # Транкейт ячеек
                    if cells:
                        rows.append(cells)
                
                if rows or headers:
                    tables.append((headers, rows))
            
            if tables:
                results.append("## 📊 Tables")
                results.append("")
                
                for idx, (headers, rows) in enumerate(tables[:max_items], 1):
                    results.append(f"### Table {idx}")
                    results.append("")
                    
                    # Заголовки
                    if headers:
                        header_line = " | ".join(headers)
                        results.append(f"| {header_line} |")
                        separator = " | ".join(["---"] * len(headers))
                        results.append(f"| {separator} |")
                    
                    # Данные (максимум 20 строк на таблицу для компактности)
                    for row in rows[:20]:
                        # Выравниваем количество колонок
                        if headers and len(row) < len(headers):
                            row.extend([""] * (len(headers) - len(row)))
                        row_line = " | ".join(row)
                        results.append(f"| {row_line} |")
                    
                    if len(rows) > 20:
                        results.append(f"*... and {len(rows) - 20} more rows*")
                    
                    results.append("")
                
                total_extracted += len(tables[:max_items])
        
        # Сводка
        results.insert(1, f"**Extracted:** {total_extracted} items")
        results.insert(2, "")
        
        # Сохраняем дамп если нужно
        if session_path:
            try:
                import time
                timestamp = int(time.time())
                safe_url = "".join([c if c.isalnum() else "_" for c in url])[:50]
                dump_file = os.path.join(session_path, f"web_extract_{timestamp}_{safe_url}.md")
                with open(dump_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(results))
                results.append(f"*💾 Dump saved to: {dump_file}*")
            except Exception as e:
                _debug(f"Failed to save dump: {e}")
        
        return "\n".join(results)
        
    except httpx.TimeoutException:
        return f"❌ Timeout ({timeout_sec}s) fetching {url}"
    except httpx.HTTPStatusError as e:
        return f"❌ HTTP {e.response.status_code} error: {url}"
    except httpx.RequestError as e:
        return f"❌ Request error: {str(e)}"
    except Exception as e:
        return f"❌ Error extracting resources: {type(e).__name__}: {str(e)}"


# Alias для совместимости
web_extract = execute


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        url = sys.argv[1]
        extract = sys.argv[2:] if len(sys.argv) > 2 else ["all"]
        print(execute(url=url, extract=extract))
    else:
        print("Usage: python3 web_extract.py <url> [extract_types...]")
        print("Examples:")
        print("  python3 web_extract.py https://example.com")
        print("  python3 web_extract.py https://example.com links images")
