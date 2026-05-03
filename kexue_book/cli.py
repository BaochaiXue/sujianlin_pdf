from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

from .crawl import crawl_posts
from .merge import merge_pdfs
from .render import render_posts_to_pdfs
from .types import Post


def _split_keywords(values: list[str] | None) -> list[str]:
    if not values:
        return []

    keywords: list[str] = []
    for value in values:
        keywords.extend(
            keyword.strip() for keyword in value.split(",") if keyword.strip()
        )
    return keywords


def _title_contains(title: str, keyword: str, case_sensitive: bool) -> bool:
    if case_sensitive:
        return keyword in title
    return keyword.casefold() in title.casefold()


def _filter_posts_by_title(
    posts: list[Post],
    include_keywords: list[str],
    exclude_keywords: list[str],
    include_match: str,
    case_sensitive: bool,
) -> list[Post]:
    filtered: list[Post] = []

    for post in posts:
        if include_keywords:
            matches = [
                _title_contains(post.title, keyword, case_sensitive)
                for keyword in include_keywords
            ]
            if include_match == "all":
                include_ok = all(matches)
            else:
                include_ok = any(matches)
        else:
            include_ok = True

        exclude_hit = any(
            _title_contains(post.title, keyword, case_sensitive)
            for keyword in exclude_keywords
        )

        if include_ok and not exclude_hit:
            filtered.append(post)

    return filtered


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Build a PDF book from Scientific Spaces Big-Data posts."
    )
    parser.add_argument(
        "--start", type=str, required=True, help="Start date YYYY-MM-DD (inclusive)"
    )
    parser.add_argument(
        "--end", type=str, required=True, help="End date YYYY-MM-DD (inclusive)"
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="output",
        help="Output directory (default: output)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="BigData",
        help="Book name prefix (default: BigData)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Debug: only process first N posts"
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=4000,
        help="Extra wait time for MathJax rendering in milliseconds (default: 4000)",
    )

    parser.add_argument(
        "--order",
        choices=("asc", "desc"),
        default="asc",
        help="Sort posts by date: asc or desc (default: asc)",
    )
    parser.add_argument(
        "--cover",
        action="store_true",
        help="Add a cover page titled '苏剑林选集' at the beginning",
    )
    parser.add_argument(
        "--no-page-numbers",
        dest="page_numbers",
        action="store_false",
        help="Disable printing page numbers on each page",
    )
    parser.set_defaults(page_numbers=True)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel render workers (default: 1)",
    )
    parser.add_argument(
        "--title-keyword",
        action="append",
        default=None,
        metavar="TEXT",
        help="Only keep posts whose title contains this keyword; repeat or comma-separate for multiple keywords",
    )
    parser.add_argument(
        "--title-match",
        choices=("any", "all"),
        default="any",
        help="How --title-keyword values are matched: any or all (default: any)",
    )
    parser.add_argument(
        "--exclude-title-keyword",
        action="append",
        default=None,
        metavar="TEXT",
        help="Exclude posts whose title contains this keyword; repeat or comma-separate for multiple keywords",
    )
    parser.add_argument(
        "--title-case-sensitive",
        action="store_true",
        help="Make title keyword matching case-sensitive",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing valid chapter PDFs and render only missing/invalid ones",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry only posts marked as failed in the previous manifest.json",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()

    print(f"[crawl] 区间: {start_date} ~ {end_date}")
    posts = crawl_posts(start_date, end_date)
    print(f"[crawl] 命中文章数: {len(posts)}")

    if args.order == "desc":
        posts = list(reversed(posts))

    include_keywords = _split_keywords(args.title_keyword)
    exclude_keywords = _split_keywords(args.exclude_title_keyword)
    if include_keywords or exclude_keywords:
        before_filter = len(posts)
        posts = _filter_posts_by_title(
            posts,
            include_keywords=include_keywords,
            exclude_keywords=exclude_keywords,
            include_match=args.title_match,
            case_sensitive=args.title_case_sensitive,
        )
        print(
            f"[filter] 标题关键词过滤: {before_filter} -> {len(posts)} 篇"
        )
        if include_keywords:
            print(f"[filter] 包含关键词({args.title_match}): {', '.join(include_keywords)}")
        if exclude_keywords:
            print(f"[filter] 排除关键词: {', '.join(exclude_keywords)}")

    if args.limit:
        before_limit = len(posts)
        posts = posts[: args.limit]
        print(f"[filter] limit: {before_limit} -> {len(posts)} 篇")

    if not posts:
        raise SystemExit("[error] 指定区间没有命中文章，已退出。")

    out_dir = Path(args.out_dir)
    chapters_dir = out_dir / "chapters"
    manifest_path = out_dir / "manifest.json"

    if args.retry_failed and not manifest_path.exists():
        raise SystemExit(f"[error] --retry-failed 找不到 manifest: {manifest_path}")

    render_output = render_posts_to_pdfs(
        posts,
        chapters_dir,
        delay_ms=args.delay_ms,
        workers=args.workers,
        manifest_path=manifest_path,
        resume=args.resume,
        retry_failed=args.retry_failed,
    )

    success_records = [
        record for record in render_output.records if record.status == "success"
    ]
    failed_records = [
        record for record in render_output.records if record.status != "success"
    ]
    print(
        f"[check] 渲染完整性: 成功 {len(success_records)} 篇，"
        f"失败 {len(failed_records)} 篇；manifest: {manifest_path}"
    )
    if failed_records:
        print("[check] 缺失 URL:")
        for record in failed_records:
            reason = record.failure_reason or "unknown"
            print(f"  - #{record.index:03d} {record.post.url} ({reason})")
        print("[check] 将只合并成功生成且可读取的章节 PDF。")

    if not render_output.rendered_posts:
        raise SystemExit("[error] 没有成功渲染任何文章，已退出。")
    if len(render_output.pdf_paths) != len(render_output.rendered_posts):
        raise SystemExit("[error] 渲染结果数量不一致，请重试。")

    book_path = out_dir / f"{args.name}-{args.start}-{args.end}.pdf"
    merge_pdfs(
        render_output.pdf_paths,
        render_output.rendered_posts,
        book_path,
        add_bookmarks=True,
        add_cover=args.cover,
        add_page_numbers=args.page_numbers,
        cover_title="苏剑林选集",
    )

    print(f"[done] 书籍已生成，可以拷到 iPad 上阅读： {book_path}")


if __name__ == "__main__":
    main()
