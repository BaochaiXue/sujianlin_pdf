from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

from .crawl import crawl_posts
from .merge import merge_pdfs
from .render import render_posts_to_pdfs


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
        default=10_000,
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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()

    print(f"[crawl] 区间: {start_date} ~ {end_date}")
    posts = crawl_posts(start_date, end_date)
    if args.limit:
        posts = posts[: args.limit]
    print(f"[crawl] 命中文章数: {len(posts)}")

    if args.order == "desc":
        posts = list(reversed(posts))

    out_dir = Path(args.out_dir)
    chapters_dir = out_dir / "chapters"

    pdf_paths, rendered_posts = render_posts_to_pdfs(
        posts, chapters_dir, delay_ms=args.delay_ms, workers=args.workers
    )

    if not rendered_posts:
        raise SystemExit("[error] 没有成功渲染任何文章，已退出。")
    if len(pdf_paths) != len(rendered_posts):
        raise SystemExit("[error] 渲染结果数量不一致，请重试。")

    book_path = out_dir / f"{args.name}-{args.start}-{args.end}.pdf"
    merge_pdfs(
        pdf_paths,
        rendered_posts,
        book_path,
        add_bookmarks=True,
        add_cover=args.cover,
        add_page_numbers=args.page_numbers,
        cover_title="苏剑林选集",
    )

    print(f"[done] 书籍已生成，可以拷到 iPad 上阅读： {book_path}")


if __name__ == "__main__":
    main()
