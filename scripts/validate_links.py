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
}

DEFAULT_TIMEOUT = 10  # seconds
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
    filepath: Path,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict]:
    """Validate all links in a markdown file and return a list of issues."""
    links = extract_links(filepath)
    issues = []

    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(concurrency)

        async def bounded_check(lineno, text, url):
            if should_skip(url):
                return
            async with sem:
                _, status, error = await check_url(session, url, timeout)
            if error:
                issues.append({"file": str(filepath), "line": lineno, "url": url, "status": None, "error": error})
            elif status not in VALID_STATUS_CODES:
                issues.append({"file": str(filepath), "line": lineno, "url": url, "status": status, "error": None})

        await asyncio.gather(*(bounded_check(ln, t, u) for ln, t, u in links))

    return issues


def main():
    parser = argparse.ArgumentParser(description="Validate links in markdown files.")
    parser.add_argument("files", nargs="+", type=Path, help="Markdown files to check")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Max concurrent requests")
    args = parser.parse_args()

    all_issues = []
    for filepath in args.files:
        if not filepath.exists():
            print(f"WARNING: {filepath} does not exist, skipping.", file=sys.stderr)
            continue
        issues = asyncio.run(validate_file(filepath, args.concurrency, args.timeout))
        all_issues.extend(issues)

    if all_issues:
        print(f"\nFound {len(all_issues)} broken link(s):\n")
        for issue in all_issues:
            status_info = f"HTTP {issue['status']}" if issue["status"] else issue["error"]
            print(f"  {issue['file']}:{issue['line']} [{status_info}] {issue['url']}")
        sys.exit(1)
    else:
        print("All links are valid.")
        sys.exit(0)


if __name__ == "__main__":
    main()
