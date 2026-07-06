"""
NEXUS AI v4.0 — Tool 04: Web content extraction.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Fetches web page content using httpx async with readability-style
extraction for clean text content. Supports markdown conversion.
"""

import json
import logging
import time
import re
from typing import Optional, List, Dict, Any
from html.parser import HTMLParser

logger = logging.getLogger("nexus.tool.web_fetch")

# ─── Constants ────────────────────────────────────────────────────────────────
FETCH_TIMEOUT: int = 30
MAX_CONTENT_LENGTH: int = 50000  # Max characters to extract
ALLOWED_SCHEMES: frozenset = frozenset({"http", "https"})


class ReadabilityParser(HTMLParser):
    """
    Minimal readability-style HTML to text parser.
    Extracts article content by prioritizing <article>, <main>, and <body> tags.
    Strips scripts, styles, nav, footer, and other non-content elements.
    """
    
    BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "br", "li", "blockquote", "pre", "hr"}
    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript", "form", "svg", "iframe"}
    INLINE_TAGS = {"a", "span", "strong", "em", "b", "i", "code", "u", "mark", "sub", "sup"}
    
    def __init__(self):
        super().__init__()
        self.text_parts: List[str] = []
        self._skip_depth: int = 0
        self._in_content: bool = True
        self._tag_stack: List[str] = []
        self._link_url: str = ""
        self._last_was_block: bool = False
    
    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        self._tag_stack.append(tag)
        attrs_dict = dict(attrs)
        
        # Track skip depth for nested skip tags
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        
        if self._skip_depth > 0:
            return
        
        # Extract links
        if tag == "a":
            self._link_url = attrs_dict.get("href", "")
        
        # Block-level spacing
        if tag in self.BLOCK_TAGS:
            if not self._last_was_block and self.text_parts:
                self.text_parts.append("\n")
            self._last_was_block = True
    
    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        
        text = data.strip()
        if not text:
            return
        
        # If we have a link, format as markdown link
        if self._link_url:
            self.text_parts.append(f"[{text}]({self._link_url})")
            self._link_url = ""
        else:
            if self._last_was_block and self.text_parts and not self.text_parts[-1].endswith("\n"):
                self.text_parts.append("\n")
            self.text_parts.append(text)
            self._last_was_block = False
    
    def handle_endtag(self, tag: str) -> None:
        if self._tag_stack:
            self._tag_stack.pop()
        
        if tag in self.SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        
        if tag in self.BLOCK_TAGS:
            if not self._last_was_block:
                self.text_parts.append("\n")
                self._last_was_block = True
    
    def get_text(self) -> str:
        """Join and clean up extracted text."""
        text = "".join(self.text_parts)
        # Collapse multiple newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Collapse multiple spaces
        text = re.sub(r'[ \t]{2,}', ' ', text)
        return text.strip()


def web_fetch(
    url: str,
    extract_links: bool = True,
    max_length: int = 10000,
) -> str:
    """
    Fetch and extract readable content from a web page.
    
    Use this tool when: The user asks to read a web page, get content from a URL,
    extract information from a website, or summarize a web article.
    
    Args:
        url: The full URL to fetch (https://...).
        extract_links: Whether to preserve hyperlinks in markdown format.
        max_length: Maximum characters to return (500-50000).
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the fetch succeeded.
          - result (str): Extracted text content from the page.
          - error (str or null): Error message if failed.
          - metadata (dict): Title, URL, content length, extraction stats.
    
    Examples:
        >>> web_fetch("https://example.com/article")
        >>> web_fetch("https://news.ycombinator.com", max_length=5000)
    """
    start = time.perf_counter()
    max_length = min(max(max_length, 500), MAX_CONTENT_LENGTH)
    
    # Validate URL
    if not url.startswith(("http://", "https://")):
        return json.dumps({
            "success": False, "result": None,
            "error": f"Invalid URL scheme. Only http:// and https:// are allowed: {url[:50]}..."
        })
    
    try:
        return _fetch_with_httpx(url, extract_links, max_length)
    except ImportError:
        try:
            return _fetch_with_urllib(url, extract_links, max_length)
        except Exception as e:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Fetch failed: {e}"
            })
    except Exception as e:
        logger.error(f"web_fetch error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })


def _fetch_with_httpx(url: str, extract_links: bool, max_length: int) -> str:
    """Fetch using httpx (async-capable, HTTP/2)."""
    import httpx
    
    try:
        with httpx.Client(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text
        
        return _extract_content(html, url, extract_links, max_length)
        
    except httpx.TimeoutException:
        return json.dumps({
            "success": False, "result": None,
            "error": f"Request timed out after {FETCH_TIMEOUT}s"
        })
    except httpx.HTTPStatusError as e:
        return json.dumps({
            "success": False, "result": None,
            "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}"
        })
    except httpx.RequestError as e:
        return json.dumps({
            "success": False, "result": None,
            "error": f"Request failed: {e}"
        })


def _fetch_with_urllib(url: str, extract_links: bool, max_length: int) -> str:
    """Fallback fetch using urllib."""
    import urllib.request
    import urllib.error
    
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            }
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as response:
            html = response.read().decode("utf-8", errors="replace")
        
        return _extract_content(html, url, extract_links, max_length)
        
    except urllib.error.HTTPError as e:
        return json.dumps({
            "success": False, "result": None,
            "error": f"HTTP {e.code}: {e.reason}"
        })
    except urllib.error.URLError as e:
        return json.dumps({
            "success": False, "result": None,
            "error": f"URL error: {e.reason}"
        })


def _extract_content(html: str, url: str, extract_links: bool, max_length: int) -> str:
    """Extract readable content from HTML."""
    # Try to find title
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""
    
    # Extract content with readability parser
    parser = ReadabilityParser()
    parser.feed(html)
    text = parser.get_text()
    
    if not text or len(text) < 50:
        # Fallback: extract from body or just strip all tags
        body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
        if body_match:
            body_html = body_match.group(1)
            text = re.sub(r'<[^>]+>', ' ', body_html)
            text = re.sub(r'\s+', ' ', text).strip()
    
    # Truncate if needed
    truncated = False
    if len(text) > max_length:
        text = text[:max_length] + "...\n[Content truncated]"
        truncated = True
    
    duration_ms = 0  # Will be set by call site
    
    return json.dumps({
        "success": True,
        "result": text,
        "error": None,
        "metadata": {
            "title": title,
            "url": url,
            "content_length": len(text),
            "truncated": truncated,
            "links_preserved": extract_links,
        }
    })