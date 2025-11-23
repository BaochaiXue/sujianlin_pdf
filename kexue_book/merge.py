from __future__ import annotations

from pathlib import Path
from typing import Iterable
import io

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from .types import Post

# 注册内置中文字体，避免封面中文字符变成方块
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def _make_cover_pdf(title: str) -> io.BytesIO:
    """Return a single-page cover PDF in memory."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    c.setTitle(title)
    c.setFont("STSong-Light", 32)
    c.drawCentredString(width / 2.0, height * 0.55, title)

    c.setFont("STSong-Light", 14)
    c.drawCentredString(width / 2.0, height * 0.48, "Scientific Spaces Big-Data")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def _make_page_number_overlay(num_pages: int) -> io.BytesIO:
    """Return an in-memory PDF with centered footer page numbers 1..N."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, _ = A4

    for i in range(1, num_pages + 1):
        c.setFont("Helvetica", 9)
        c.drawCentredString(width / 2.0, 12 * mm, str(i))
        c.showPage()

    c.save()
    buf.seek(0)
    return buf


def merge_pdfs(
    pdf_paths: Iterable[Path],
    posts: Iterable[Post],
    output_path: Path,
    add_bookmarks: bool = True,
    add_cover: bool = False,
    add_page_numbers: bool = False,
    cover_title: str = "苏剑林选集",
) -> Path:
    """
    Merge single-article PDFs into one book with optional cover, bookmarks, and page numbers.
    """
    posts = list(posts)
    pdf_paths = list(pdf_paths)

    if len(posts) != len(pdf_paths):
        raise ValueError("pdf_paths 和 posts 数量必须一致")

    writer = PdfWriter()

    # Optional cover first
    if add_cover:
        cover_buf = _make_cover_pdf(cover_title)
        cover_reader = PdfReader(cover_buf)
        for page in cover_reader.pages:
            writer.add_page(page)
    cover_page_count = len(writer.pages)

    # Merge article PDFs and add bookmarks with proper offset
    current_page = cover_page_count
    for pdf_path, post in zip(pdf_paths, posts):
        reader = PdfReader(str(pdf_path))
        num_pages = len(reader.pages)

        for page in reader.pages:
            writer.add_page(page)

        if add_bookmarks and num_pages > 0:
            writer.add_outline_item(post.title, current_page)

        current_page += num_pages

    # Optional page numbers overlay
    if add_page_numbers:
        total_pages = len(writer.pages)
        overlay_buf = _make_page_number_overlay(total_pages)
        overlay_reader = PdfReader(overlay_buf)

        for i in range(total_pages):
            base_page = writer.pages[i]
            overlay_page = overlay_reader.pages[i]
            base_page.merge_page(overlay_page)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        writer.write(f)

    return output_path
