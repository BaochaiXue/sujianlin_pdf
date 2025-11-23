from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, List
from urllib.parse import urljoin
import re

import requests
from bs4 import BeautifulSoup

from .types import Post

BASE_CATEGORY_URL = "https://spaces.ac.cn/category/Big-Data"
DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
ARCHIVE_ID_PATTERN = re.compile(r"/(\\d+)$")


def _parse_post(post_element: BeautifulSoup) -> Post:
    title_el = post_element.select_one("h2 a")
    if not title_el or not title_el.get("href"):
        raise ValueError("Post node is missing title link")

    title = title_el.get_text(strip=True)
    url = urljoin(BASE_CATEGORY_URL, title_el["href"])

    meta_text = post_element.select_one("span.submitted")
    if not meta_text:
        raise ValueError(f"Missing metadata for post: {title}")

    match = DATE_PATTERN.search(meta_text.get_text(" "))
    if not match:
        raise ValueError(f"Missing date for post: {title}")

    publish_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()

    return Post(title=title, url=url, date=publish_date)


def _find_next_page(soup: BeautifulSoup, current_url: str) -> str | None:
    next_link = soup.find("a", string="»")
    if not next_link or not next_link.get("href"):
        return None
    return urljoin(current_url, next_link["href"])


def crawl_posts(start: date, end: date) -> List[Post]:
    """Crawl the Big-Data category and return posts within [start, end]."""

    posts: List[Post] = []
    seen_pages: set[str] = set()

    page_url: str | None = BASE_CATEGORY_URL
    while page_url and page_url not in seen_pages:
        response = requests.get(page_url, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        seen_pages.add(page_url)

        for post_element in soup.select("div.Post"):
            try:
                post = _parse_post(post_element)
            except ValueError:
                continue

            if start <= post.date <= end:
                posts.append(post)

        page_url = _find_next_page(soup, page_url)

    def _sort_key(p: Post) -> tuple[date, int]:
        # Use archive id as tie-breaker so posts on the same date follow publish order.
        match = ARCHIVE_ID_PATTERN.search(p.url)
        archive_id = int(match.group(1)) if match else 0
        return (p.date, archive_id)

    posts.sort(key=_sort_key)
    return posts


def iter_posts(start: date, end: date) -> Iterable[Post]:
    """Yield posts within the given date range in chronological order."""

    for post in crawl_posts(start, end):
        yield post
