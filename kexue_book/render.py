from __future__ import annotations

from pathlib import Path
from typing import Iterable, List
import re

from playwright.sync_api import Page, sync_playwright

from .types import Post

PRINT_CSS = """
header, nav, footer, #sideBar, .MobileSideBar, .post-footer, #comments, .comments, .post-meta {
    display: none !important;
}
body {
    width: 100% !important;
    margin: 0 auto;
    font-family: 'Noto Serif SC', 'Source Han Serif', serif;
    font-size: 14px;
    line-height: 1.6;
}
.PostContent {
    max-width: 960px;
    margin: 0 auto;
}
img {
    max-width: 100%;
    page-break-inside: avoid;
}
h1, h2, h3, h4, h5, h6 {
    page-break-after: avoid;
}
pre, code {
    font-family: 'JetBrains Mono', 'Menlo', monospace;
    white-space: pre-wrap;
}
"""

SAFE_NAME_PATTERN = re.compile(r"[^\w\u4e00-\u9fff-]+")


def _safe_filename(title: str) -> str:
    simplified = SAFE_NAME_PATTERN.sub("-", title).strip("-")
    return simplified or "article"


def _render_single(page: Page, post: Post, target: Path, delay_ms: int) -> None:
    page.goto(post.url, wait_until="load", timeout=60_000)
    page.wait_for_timeout(delay_ms)
    page.add_style_tag(content=PRINT_CSS)
    page.wait_for_timeout(200)
    target.parent.mkdir(parents=True, exist_ok=True)
    page.pdf(
        path=str(target),
        format="A4",
        margin={"top": "20mm", "bottom": "20mm", "left": "16mm", "right": "16mm"},
        print_background=True,
    )
    page.close()


def render_posts_to_pdfs(posts: Iterable[Post], output_dir: Path, delay_ms: int = 4000) -> List[Path]:
    rendered_paths: List[Path] = []
    posts_list = list(posts)
    output_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        for index, post in enumerate(posts_list, start=1):
            filename = f"{index:03d}-{_safe_filename(post.title)}.pdf"
            pdf_path = output_dir / filename
            page = context.new_page()
            try:
                print(f"[render] {index}/{len(posts_list)} {post.url}")
                _render_single(page, post, pdf_path, delay_ms)
                rendered_paths.append(pdf_path)
            except Exception as exc:
                print(f"[warn] 渲染失败，跳过: {post.url} ({exc})")
                try:
                    page.close()
                except Exception:
                    pass
        browser.close()
    return rendered_paths
