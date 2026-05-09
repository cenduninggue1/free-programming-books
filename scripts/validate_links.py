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
    "reddit.com",    # personal addition: reddit rate-limits bots aggressively
    "medium.com",    # added: medium returns 200 for paywalled content anyway
    "researchgate.net",  # also blocks bots; returns 403 almost always
    "academia.edu",  # added: consistently returns 403 for automated requests
    "quora.com",     # added: quora redirects bots to login page, not useful to check
    "stackoverflow.com",  # added: rate-limits heavily during bulk checks
    "geeksforgeeks.org",  # added: frequently returns 403 for headless requests
    "docs.oracle.com",   # added: oracle docs intermittently 403 on automated requests
    "dev.to",            # added: dev.to started returning 429 for rapid automated checks
    "freecodecamp.org",  # added: returns 403 for automated requests in my testing
    "substack.com",      # added: substack consistently blocks bots with 403
}

DEFAULT_TIMEOUT = 20  # bumped from 15s — my connection is slower, avoids false positives
DEFAULT_CONCURRENCY = 10  # reduced from 20 — be a bit more polite to servers


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
         
