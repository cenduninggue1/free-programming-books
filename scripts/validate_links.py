#!/usr/bin/env python3
"""
Link validation script for free-programming-books.

Checks URLs in markdown files for accessibility, proper formatting,
and compliance with contribution guidelines.
"""

import re
import sys
import asyncio
import argparse
from pathlib import Path
from typing import Optional

import aiohttp

# Regex pattern to extract markdown links
MARKDOWN_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^)]+)\)')

# HTTP status codes considered valid
VALID_STATUS_CODES = {200, 206, 301, 302, 303, 307, 308}

# Domains known to block automated requests (treat as warnings, not errors)
SKIP_DOMAINS = {
    "web.archive.org",
    "linkedin.com",
    "facebook.com",
    "twitter.com",   # also blocks bots consistently
    "x.com",         # same as above, new domain
}

DEFAULT_TIMEOUT = 15  # increased from 10s — some mirrors are slow to respond
DEFAULT_CONCURRENCY = 20


def extract_links(filepath: Path) -> list[tuple[int, str, str]]:
    """
    Extract all markdown links from a file.

    Returns a list of (line_number, link_text, url) tuples.
    """
    links = []
    with filepath.open(encoding="utf-8", errors="ignore") as f:
        for lineno, line in enumerate(f, start=1):
            for match in MARKDOWN_LINK_RE.finditer(line):
                text, url = match.group(1), match.group(2)
                links.append((lineno, text, url))
    return links


def should_skip(url: str) -> bool:
    """Return True if the URL belongs to a domain we skip."""
    for domain in SKIP_DOMAINS:
        if domain in url:
            return True
    return False


async def check_url(
    session: aiohttp.ClientSession,
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[str, Optional[int], Optional[str]]:
    """
    Perform an async HEAD (fallback GET) request for the given URL.

    Returns (url, status_code, error_message).
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; free-programming-books-bot/1.0; "
            "+https://github.com/EbookFoundation/free-programming-books)"
        )
    }
    try:
        async with session.head(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
            ssl=False,
        ) as resp:
            if resp.status == 405:  # Method Not Allowed — retry with GET
                raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=405)
            return url, resp.status, None
    except aiohttp.ClientResponseError as exc:
        if exc.status == 405:
            try:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    allow_redirects=True,
                    ssl=False,
                ) as resp:
                    return url, resp.status, None
            except Exception as inner_exc:
                return url, None, str(inner_exc)
        return url, exc.status, str(exc)
    except Exception as exc:
        return url, None, str(exc)


async def validate_file(
 