from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable, List
from concurrent.futures import ProcessPoolExecutor, as_completed

from playwright.sync_api import Error as PlaywrightError, Page, sync_playwright
from pypdf import PdfReader

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
    padding: 0 8px;
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

/* MathJax: leave space for right-side equation numbers and avoid clipping. */
mjx-container[jax="CHTML"][display="true"],
mjx-container[jax="SVG"][display="true"] {
    padding-right: 3.5em !important;
    overflow: visible !important;
}

mjx-container[jax="CHTML"][display="true"] mjx-tag,
mjx-container[jax="SVG"][display="true"] mjx-tag {
    padding-left: .3em !important;
}

/* Hide MathJax status box (e.g., "Loading ...") so it won't appear in PDFs. */
.MathJax_Message,
#MathJax_Message {
    display: none !important;
}
"""

SAFE_NAME_PATTERN = re.compile(r"[^\w\u4e00-\u9fff-]+")

# Viewport settings that align MathJax layout with the printable A4 area. The
# Scientific Spaces site scales MathJax output according to the window width at
# render time; matching the viewport to the A4 content area avoids right-edge
# clipping of equation numbers and long underbrace expressions when exporting to
# PDF.
CSS_PX_PER_MM = 96 / 25.4
A4_WIDTH_MM = 210
LEFT_MARGIN_MM = 16
RIGHT_MARGIN_MM = 16
WIDTH_FUDGE = 0.95
CONTENT_WIDTH_PX = int(
    (A4_WIDTH_MM - LEFT_MARGIN_MM - RIGHT_MARGIN_MM) * CSS_PX_PER_MM * WIDTH_FUDGE
)
VIEWPORT = {"width": CONTENT_WIDTH_PX, "height": 1200}
PDF_MARGINS = {
    "top": "20mm",
    "bottom": "20mm",
    "left": f"{LEFT_MARGIN_MM}mm",
    "right": f"{RIGHT_MARGIN_MM}mm",
}
PDF_SCALE = 0.9
MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RenderTask:
    index: int
    post: Post
    pdf_path: Path


@dataclass(frozen=True)
class RenderRecord:
    index: int
    post: Post
    pdf_path: Path
    status: str
    failure_reason: str | None
    page_count: int | None
    rendered: bool


@dataclass(frozen=True)
class RenderOutput:
    pdf_paths: List[Path]
    rendered_posts: List[Post]
    records: List[RenderRecord]
    manifest_path: Path | None

    def __iter__(self):
        yield self.pdf_paths
        yield self.rendered_posts


def _safe_filename(title: str) -> str:
    simplified = SAFE_NAME_PATTERN.sub("-", title).strip("-")
    return simplified or "article"


def _make_task(index: int, post: Post, output_dir: Path) -> RenderTask:
    filename = f"{index:03d}-{_safe_filename(post.title)}.pdf"
    return RenderTask(index=index, post=post, pdf_path=output_dir / filename)


def _format_failure(exc: BaseException) -> str:
    message = str(exc).strip().splitlines()
    return (message[0] if message else exc.__class__.__name__)[:1000]


def _pdf_page_count(path: Path) -> int | None:
    if not path.exists() or not path.is_file():
        return None

    try:
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
    except Exception:
        return None

    return page_count if page_count > 0 else None


def _resolve_manifest_pdf_path(entry: dict[str, Any], manifest_dir: Path) -> Path | None:
    pdf_path = entry.get("pdf_path")
    if not isinstance(pdf_path, str) or not pdf_path:
        return None

    path = Path(pdf_path)
    return path if path.is_absolute() else manifest_dir / path


def _display_pdf_path(path: Path, manifest_dir: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(manifest_dir.resolve()))
    except ValueError:
        return str(path)


def _record_to_manifest_entry(
    record: RenderRecord, manifest_dir: Path
) -> dict[str, Any]:
    return {
        "index": record.index,
        "title": record.post.title,
        "url": record.post.url,
        "date": record.post.date.isoformat(),
        "pdf_path": _display_pdf_path(record.pdf_path, manifest_dir),
        "status": record.status,
        "failure_reason": record.failure_reason,
        "page_count": record.page_count,
        "rendered": record.rendered,
    }


def _load_manifest_entries(manifest_path: Path) -> list[dict[str, Any]]:
    with manifest_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"manifest 缺少 entries 列表: {manifest_path}")

    return [entry for entry in entries if isinstance(entry, dict)]


def _write_manifest(manifest_path: Path, records: list[RenderRecord]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_dir = manifest_path.parent
    sorted_records = sorted(records, key=lambda record: record.index)
    data = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": [
            _record_to_manifest_entry(record, manifest_dir)
            for record in sorted_records
        ],
    }

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


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
    page.emulate_media(media="screen")
    page.wait_for_timeout(delay_ms)
    page.add_style_tag(content=PRINT_CSS)
    page.wait_for_timeout(200)
    target.parent.mkdir(parents=True, exist_ok=True)
    page.pdf(
        path=str(target),
        format="A4",
        margin=PDF_MARGINS,
        print_background=True,
        scale=PDF_SCALE,
    )


def _render_task(
    context,
    task: RenderTask,
    delay_ms: int,
    position: int,
    total: int,
    prefix: str,
) -> RenderRecord:
    page = context.new_page()
    try:
        print(f"{prefix} {position}/{total} #{task.index:03d}: {task.post.url}")
        _render_single(page, task.post, task.pdf_path, delay_ms)
        page_count = _pdf_page_count(task.pdf_path)
        if page_count is None:
            return RenderRecord(
                index=task.index,
                post=task.post,
                pdf_path=task.pdf_path,
                status="failed",
                failure_reason="Rendered PDF is missing, unreadable, or empty",
                page_count=None,
                rendered=True,
            )

        return RenderRecord(
            index=task.index,
            post=task.post,
            pdf_path=task.pdf_path,
            status="success",
            failure_reason=None,
            page_count=page_count,
            rendered=True,
        )
    except Exception as exc:
        print(f"{prefix} warn #{task.index:03d} 渲染失败，跳过: {task.post.url} ({exc})")
        return RenderRecord(
            index=task.index,
            post=task.post,
            pdf_path=task.pdf_path,
            status="failed",
            failure_reason=_format_failure(exc),
            page_count=None,
            rendered=True,
        )
    finally:
        try:
            page.close()
        except Exception:
            pass


def _render_batch(
    tasks: List[RenderTask],
    delay_ms: int,
) -> List[RenderRecord]:
    """
    子进程中渲染一批 task，返回每篇文章的渲染记录。
    """
    records: List[RenderRecord] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, ignore_https_errors=True)
        total = len(tasks)

        for position, task in enumerate(tasks, start=1):
            records.append(
                _render_task(
                    context,
                    task,
                    delay_ms,
                    position,
                    total,
                    prefix=f"[worker pid={os.getpid()}]",
                )
            )

        browser.close()

    return records


def _reuse_record(task: RenderTask, page_count: int, pdf_path: Path) -> RenderRecord:
    return RenderRecord(
        index=task.index,
        post=task.post,
        pdf_path=pdf_path,
        status="success",
        failure_reason=None,
        page_count=page_count,
        rendered=False,
    )


def _reuse_valid_record(
    task: RenderTask, candidates: list[Path | None]
) -> RenderRecord | None:
    seen_paths: set[Path] = set()
    for candidate in candidates:
        if candidate is None or candidate in seen_paths:
            continue
        seen_paths.add(candidate)
        page_count = _pdf_page_count(candidate)
        if page_count is not None:
            return _reuse_record(task, page_count, candidate)
    return None


def _failed_without_render(task: RenderTask, reason: str) -> RenderRecord:
    return RenderRecord(
        index=task.index,
        post=task.post,
        pdf_path=task.pdf_path,
        status="failed",
        failure_reason=reason,
        page_count=None,
        rendered=False,
    )


def _select_tasks(
    tasks: list[RenderTask],
    manifest_path: Path | None,
    resume: bool,
    retry_failed: bool,
) -> tuple[list[RenderTask], list[RenderRecord]]:
    tasks_to_render: list[RenderTask] = []
    prefilled_records: list[RenderRecord] = []

    previous_by_url: dict[str, dict[str, Any]] = {}
    manifest_dir: Path | None = None
    should_load_manifest = bool(manifest_path and manifest_path.exists())
    if retry_failed and not should_load_manifest:
        raise FileNotFoundError(f"--retry-failed 找不到 manifest: {manifest_path}")
    if should_load_manifest and (resume or retry_failed):
        if manifest_path is None:
            raise ValueError("--retry-failed 需要 manifest_path")
        manifest_dir = manifest_path.parent
        previous_by_url = {
            entry["url"]: entry
            for entry in _load_manifest_entries(manifest_path)
            if isinstance(entry.get("url"), str)
        }

    for task in tasks:
        previous = previous_by_url.get(task.post.url)
        previous_path = (
            _resolve_manifest_pdf_path(previous, manifest_dir)
            if previous is not None and manifest_dir is not None
            else None
        )

        if retry_failed:
            if previous is None:
                prefilled_records.append(
                    _failed_without_render(
                        task, "Not found in previous manifest; skipped by --retry-failed"
                    )
                )
                continue

            if previous.get("status") == "success":
                reused_record = _reuse_valid_record(task, [task.pdf_path, previous_path])
                if reused_record is not None:
                    prefilled_records.append(reused_record)
                else:
                    prefilled_records.append(
                        _failed_without_render(
                            task,
                            "Previous success PDF is missing or invalid; run without --retry-failed to rebuild it",
                        )
                    )
                continue

            if resume:
                reused_record = _reuse_valid_record(task, [task.pdf_path, previous_path])
                if reused_record is not None:
                    prefilled_records.append(reused_record)
                    continue

            tasks_to_render.append(task)
            continue

        if resume:
            reused_record = _reuse_valid_record(task, [task.pdf_path, previous_path])
            if reused_record is not None:
                prefilled_records.append(reused_record)
                continue

        tasks_to_render.append(task)

    return tasks_to_render, prefilled_records


def render_posts_to_pdfs(
    posts: Iterable[Post],
    output_dir: Path,
    delay_ms: int = 4000,
    workers: int = 1,
    manifest_path: Path | None = None,
    resume: bool = False,
    retry_failed: bool = False,
) -> RenderOutput:
    posts_list = list(posts)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not posts_list:
        if manifest_path is not None:
            _write_manifest(manifest_path, [])
        return RenderOutput([], [], [], manifest_path)

    tasks = [
        _make_task(index, post, output_dir)
        for index, post in enumerate(posts_list, start=1)
    ]
    tasks_to_render, records = _select_tasks(
        tasks, manifest_path, resume=resume, retry_failed=retry_failed
    )

    if resume:
        reused = len([record for record in records if record.status == "success"])
        print(f"[render] resume: 复用已有有效 PDF {reused} 篇")
    if retry_failed:
        print(f"[render] retry-failed: 本次需要重试 {len(tasks_to_render)} 篇")

    # 单进程模式
    if tasks_to_render and (workers <= 1 or len(tasks_to_render) <= 1):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport=VIEWPORT, ignore_https_errors=True)
            total = len(tasks_to_render)
            for position, task in enumerate(tasks_to_render, start=1):
                records.append(
                    _render_task(
                        context,
                        task,
                        delay_ms,
                        position,
                        total,
                        prefix="[render]",
                    )
                )
            browser.close()
    elif tasks_to_render:
        # 并行模式
        workers = min(workers, len(tasks_to_render))
        chunk_size = math.ceil(len(tasks_to_render) / workers)
        chunks: List[List[RenderTask]] = [
            tasks_to_render[i : i + chunk_size]
            for i in range(0, len(tasks_to_render), chunk_size)
        ]

        print(
            f"[render] 并行渲染 workers={len(chunks)}, total_posts={len(tasks_to_render)}"
        )

        with ProcessPoolExecutor(max_workers=len(chunks)) as executor:
            futures = {
                executor.submit(_render_batch, chunk, delay_ms): chunk
                for chunk in chunks
            }
            for fut in as_completed(futures):
                try:
                    records.extend(fut.result())
                except Exception as exc:
                    print(f"[worker error] 子进程异常: {exc}")
                    records.extend(
                        _failed_without_render(task, _format_failure(exc))
                        for task in futures[fut]
                    )

    records.sort(key=lambda record: record.index)
    if manifest_path is not None:
        _write_manifest(manifest_path, records)

    successful_records = [record for record in records if record.status == "success"]
    return RenderOutput(
        pdf_paths=[record.pdf_path for record in successful_records],
        rendered_posts=[record.post for record in successful_records],
        records=records,
        manifest_path=manifest_path,
    )
