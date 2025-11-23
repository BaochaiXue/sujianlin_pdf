from __future__ import annotations

from pathlib import Path
from typing import Iterable, List
import re
import math
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

from playwright.sync_api import Error as PlaywrightError, Page, sync_playwright

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


def _navigate_with_retries(page: Page, url: str) -> None:
    """
    Try loading the page up to three times with progressively looser conditions/timeouts:
    1) goto with load (75s)
    2) reload with domcontentloaded (90s)
    3) fresh goto with domcontentloaded (120s)
    """
    attempts = [
        ("goto-load", lambda: page.goto(url, wait_until="load", timeout=75_000)),
        (
            "reload-domcontent",
            lambda: page.reload(wait_until="domcontentloaded", timeout=90_000),
        ),
        (
            "goto-domcontent",
            lambda: page.goto(url, wait_until="domcontentloaded", timeout=120_000),
        ),
    ]

    last_exc: PlaywrightError | None = None
    for _, attempt in attempts:
        try:
            attempt()
            return
        except PlaywrightError as exc:
            last_exc = exc
    if last_exc:
        raise last_exc


def _render_single(page: Page, post: Post, target: Path, delay_ms: int) -> None:
    _navigate_with_retries(page, post.url)
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


def _render_batch(
    indexed_posts: List[tuple[int, Post]],
    output_dir_str: str,
    delay_ms: int,
) -> List[tuple[str, Post]]:
    """
    子进程中渲染一批 (index, post)，返回成功生成的 PDF 路径与对应 Post。
    """
    output_dir = Path(output_dir_str)
    rendered: List[tuple[str, Post]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        total = len(indexed_posts)

        for index, post in indexed_posts:
            filename = f"{index:03d}-{_safe_filename(post.title)}.pdf"
            pdf_path = output_dir / filename
            page = context.new_page()
            try:
                print(f"[worker pid={os.getpid()}] {index}/{total}: {post.url}")
                _render_single(page, post, pdf_path, delay_ms)
                rendered.append((str(pdf_path), post))
            except PlaywrightError as exc:
                print(
                    f"[worker warn pid={os.getpid()}] 渲染失败，跳过: {post.url} ({exc})"
                )
                try:
                    page.close()
                except PlaywrightError:
                    pass

        browser.close()

    return rendered


def render_posts_to_pdfs(
    posts: Iterable[Post],
    output_dir: Path,
    delay_ms: int = 4000,
    workers: int = 1,
) -> tuple[List[Path], List[Post]]:
    rendered_paths: List[Path] = []
    rendered_posts: List[Post] = []
    posts_list = list(posts)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not posts_list:
        return [], []

    # 单进程模式：保持原有行为
    if workers <= 1:
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
                    rendered_posts.append(post)
                except PlaywrightError as exc:
                    print(f"[warn] 渲染失败，跳过: {post.url} ({exc})")
                    try:
                        page.close()
                    except PlaywrightError:
                        pass
            browser.close()
        return rendered_paths, rendered_posts

    # 并行模式
    workers = min(workers, len(posts_list))
    indexed: List[tuple[int, Post]] = list(enumerate(posts_list, start=1))
    chunk_size = math.ceil(len(indexed) / workers)
    chunks: List[List[tuple[int, Post]]] = [
        indexed[i : i + chunk_size] for i in range(0, len(indexed), chunk_size)
    ]

    print(f"[render] 并行渲染 workers={len(chunks)}, total_posts={len(posts_list)}")

    with ProcessPoolExecutor(max_workers=len(chunks)) as executor:
        futures = [
            executor.submit(_render_batch, chunk, str(output_dir), delay_ms)
            for chunk in chunks
        ]
        combined: List[tuple[str, Post]] = []
        for fut in as_completed(futures):
            try:
                combined.extend(fut.result())
            except PlaywrightError as exc:
                print(f"[worker error] 子进程异常: {exc}")

    # 按文件名排序，保证顺序与 posts_list 对齐
    combined.sort(key=lambda item: Path(item[0]).name)
    for path_str, post in combined:
        rendered_paths.append(Path(path_str))
        rendered_posts.append(post)

    return rendered_paths, rendered_posts
