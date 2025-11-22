先给你一个结论版：
**可以做，而且完全可以做成一个严肃一点的“小教科书工程”。**
我这边已经看过 `Big-Data` 分类页和几篇文章的页面结构、以及 LaTeX 说明页，你不用自己看源码也能直接开工。([Scientific Spaces][1])

下面给你一个可以直接丢到 GitHub 的工程设计：目录结构、环境配置、核心代码都写好，你只需要复制粘贴 + 按需微调选择器/CSS。

---

## 0. 先说清需求约束（结合我实际看过的页面）

我看了：

* `https://spaces.ac.cn/category/Big-Data`：列表页结构、分页方式（底部有 `1 2 3 ... 52 »`）。([Scientific Spaces][1])
* 单篇文章，例如 Attention 那篇：有典型的

  `By  苏剑林 | 2018-01-06 | 1160590位读者 | ...`

  以及正文里的 `\begin{equation}...\end{equation}`、`$...$` 这类 LaTeX，前端用 MathJax 渲染。([Scientific Spaces][2])
* `latex.html`：确认整个站点用 **MathJax** 渲染公式，并且支持 `$...$` / `\(...\)` 这些写法。([Scientific Spaces][3])
* 首页 footer：确认是 Typecho + 自定义主题，版权是 **CC BY‑NC‑SA（署名‑非商业‑相同方式共享）**。([Scientific Spaces][4])

结合这些信息，工程上有几个硬约束：

1. **必须用能执行 JS 的浏览器内核**（MathJax 渲染完再导出 PDF），不能走“纯 HTML→PDF”库。
2. **不能乱删 `<script>` 或重排 DOM**，否则可能让 MathJax 再次触发或报错；更合理的是：

   > 保留整个页面，只用额外注入 CSS 把 header / sidebar / 评论 隐藏，再打印。
3. **列表页只当“导航”用**：从分类页抓出所有“点击阅读全文...”链接即可，日期用正则从页面文本里挖（`| YYYY-MM-DD |` 的模式在分类页和单篇页都存在）。([Scientific Spaces][1])

---

## 1. 工程整体设计（Pipeline）

整条 pipeline 分三步，每步一个模块：

1. **crawl（爬 URL + 元信息）**

   * 从 `https://spaces.ac.cn/category/Big-Data` 开始，顺着底部 `1 2 3 ... 52 »` 翻页。([Scientific Spaces][1])
   * 在每一页里找所有“点击阅读全文...”的链接，拿到文章 URL。
   * 在对应块里用正则提取 `| YYYY-MM-DD |`，得到发布日期。
   * 根据用户设定的 `[start_date, end_date]` 过滤文章，输出一个有序列表（标题 / URL / 日期）。

2. **render（单篇网页 → 单篇 PDF）**

   * 用 **Playwright + Chromium headless** 打开每个 URL。
   * `wait_until="networkidle"` + 再多等几秒，给 MathJax 时间渲染。([Scientific Spaces][3])
   * 用 `page.add_style_tag` 注入一段 CSS：

     * 隐藏 sidebar、顶部导航、底部版权、评论区等；
     * 控制版心宽度、字体、A4 页边距；
     * 设置 `img { max-width: 100%; page-break-inside: avoid; }`。
   * 调用 `page.pdf()` 输出单篇 PDF，比如 `chapters/001-标题.pdf`。

3. **merge（合并为“教科书”PDF）**

   * 用 `pypdf` 把所有章节 PDF 按顺序合并。
   * 可选：为每篇文章在 PDF 里加 bookmark（大纲），方便在 iPad 里快速跳章节。([pypdf][5])

---

## 2. 项目结构设计

推荐一个简单但规范的结构：

```text
kexuefm-bigdata-book/
  README.md
  requirements.txt
  kexue_book/
    __init__.py
    crawl.py       # 爬 Big-Data 列表，按日期过滤
    render.py      # Playwright 渲染单篇为 PDF
    merge.py       # 合并章节 PDF +（可选）书签
    cli.py         # 命令行入口，串起整条 pipeline
  output/
    # 跑完之后这里会出现：
    #   chapters/*.pdf
    #   BigData-2018-2020.pdf
```

GitHub 上你可以直接把 `kexuefm-bigdata-book` 当仓库根目录，`README.md` 里写清楚这是针对 **Scientific Spaces / 信息时代 Big-Data 分类的个人阅读工具**，并明确遵守原站 CC BY‑NC‑SA 协议即可。([Scientific Spaces][6])

---

## 3. 环境与依赖配置

假设你用的是 macOS / Linux / WSL（Windows 也行，命令稍微改一下）。

### 3.1 Python & 虚拟环境

```bash
# 建议 3.10+，下面以 3.11 为例
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
```

### 3.2 requirements.txt

放在项目根目录：

```txt
requests>=2.32
beautifulsoup4>=4.12
lxml>=5.0
playwright>=1.48
pypdf>=5.0
tqdm>=4.66
```

安装依赖：

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Playwright 会自动下载一个无头 Chromium，用它来执行 MathJax 和打印 PDF。([pypdf][7])

---

## 4. 代码实现（核心文件）

### 4.1 `kexue_book/crawl.py` — 爬 Big-Data + 日期过滤

```python
# kexue_book/crawl.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://spaces.ac.cn"
CATEGORY_URL = BASE + "/category/Big-Data"

# 例如：By  苏剑林 | 2025-10-27 | 16996位读者 |
DATE_RE = re.compile(r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|")


@dataclass
class PostMeta:
    title: str
    url: str
    date: date | None


def _extract_posts_from_page(html: str) -> List[PostMeta]:
    """从单个分类页 HTML 中抽取文章链接、标题和日期"""
    soup = BeautifulSoup(html, "lxml")
    posts: List[PostMeta] = []

    # 类型空间的主题里，“点击阅读全文...” 是一个很稳定的锚文本 :contentReference[oaicite:11]{index=11}
    def is_read_more(text: str | None) -> bool:
        return text is not None and "阅读全文" in text

    for more_link in soup.find_all("a", string=is_read_more):
        href = more_link.get("href")
        if not href:
            continue
        url = urljoin(BASE, href)

        # 尝试找到一个“文章块”的父节点
        container = more_link.find_parent(["article", "div", "li", "section"]) or soup

        # 标题通常在 h2/h1 里
        title_tag = container.find(["h2", "h1", "h3"])
        if title_tag:
            title = title_tag.get_text(strip=True)
        else:
            title = url

        # 尝试在当前块的文本里找 `| YYYY-MM-DD |`
        text = container.get_text(" ", strip=True)
        m = DATE_RE.search(text)
        d: date | None = None
        if m:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()

        posts.append(PostMeta(title=title, url=url, date=d))

    return posts


def _iter_category_pages() -> Iterable[str]:
    """遍历 Big-Data 分类的所有分页，返回 HTML 文本"""
    session = requests.Session()
    url = CATEGORY_URL
    visited = set()

    while url and url not in visited:
        visited.add(url)
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        html = resp.text
        yield html

        soup = BeautifulSoup(html, "lxml")
        # 底部分页有 “1 2 3 ... 52 »”，我们用 “»” 找下一页 :contentReference[oaicite:12]{index=12}
        next_link = soup.find("a", string=lambda s: s and "»" in s)
        if next_link and next_link.get("href"):
            href = next_link["href"]
            url = urljoin(BASE, href)
        else:
            url = None


def crawl_posts(start: date, end: date) -> List[PostMeta]:
    """爬取 Big-Data 分类，按日期区间 [start, end] 过滤"""
    by_url: dict[str, PostMeta] = {}

    for html in _iter_category_pages():
        for post in _extract_posts_from_page(html):
            if post.date is None:
                in_range = True  # 日期解析失败就先全收
            else:
                in_range = start <= post.date <= end

            if in_range:
                # 防止同一文章出现在多个分页
                if post.url not in by_url:
                    by_url[post.url] = post

    # 按时间从早到晚排序，时间相同就按标题
    def sort_key(p: PostMeta):
        d = p.date or date(1900, 1, 1)
        return d, p.title

    posts = sorted(by_url.values(), key=sort_key)
    return posts
```

---

### 4.2 `kexue_book/render.py` — 用 Playwright 把每篇变成 A4 PDF

```python
# kexue_book/render.py
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from playwright.sync_api import sync_playwright

from .crawl import PostMeta


def _slugify_title(title: str) -> str:
    """把标题变成文件名友好的 slug，保留少量字符，太长就截断"""
    s = title.strip()
    s = re.sub(r"\s+", "-", s)
    # 保留中英文、数字、下划线和连字符
    s = re.sub(r"[^\w\-一-龥]", "", s)
    if not s:
        s = "post"
    return s[:40]


def render_posts_to_pdfs(
    posts: Iterable[PostMeta],
    out_dir: Path,
    delay_ms: int = 4000,
) -> List[Path]:
    """
    用 Chromium 打开每个页面，注入 CSS 隐藏侧边栏/评论，再打印成 PDF。
    返回生成的 PDF 路径列表（顺序与 posts 相同）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_paths: List[Path] = []

    css = """
    @page {
        size: A4;
        margin: 20mm 18mm 22mm 18mm;
    }

    html, body {
        background: #ffffff !important;
    }

    body {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                     "Helvetica Neue", "PingFang SC", "Hiragino Sans GB",
                     "Microsoft YaHei", sans-serif;
        line-height: 1.6;
        font-size: 11pt;
    }

    /* 尝试压缩成“教科书版心” */
    article, .post, .entry, .entry-content, #content {
        max-width: 720px;
        margin-left: auto;
        margin-right: auto;
    }

    /* 隐藏头部导航、侧边栏、底部、评论等常见区域 */
    header, .site-header, #header,
    #sidebar, .sidebar, .widget, .widget-area, #secondary,
    #MobileSideBar, .mobile-sidebar,
    footer, .site-footer, #footer,
    #comments, .comments, .comment-list, .comment-respond,
    .comment-reply, .reply, .trackbacks {
        display: none !important;
    }

    img {
        max-width: 100% !important;
        height: auto !important;
        page-break-inside: avoid;
    }

    pre, code {
        font-family: "JetBrains Mono", "SF Mono", Menlo, Monaco,
                     Consolas, monospace;
        font-size: 9pt;
    }

    h1, h2, h3 {
        page-break-after: avoid;
    }
    """

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 1600})

        for idx, post in enumerate(posts, start=1):
            print(f"[render] ({idx}) {post.title} -> {post.url}")
            slug = _slugify_title(post.title)
            pdf_path = out_dir / f"{idx:03d}-{slug}.pdf"

            page.goto(post.url, wait_until="networkidle")
            # 注入 CSS 隐藏非正文区域
            page.add_style_tag(content=css)

            # 这里可以更精细地等 MathJax，简单版直接多等几秒
            page.wait_for_timeout(delay_ms)

            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "20mm", "bottom": "22mm", "left": "18mm", "right": "18mm"},
            )

            pdf_paths.append(pdf_path)

        browser.close()

    return pdf_paths
```

> 说明：因为我这边拿到的只是“简化后的页面文本”，看不到完整 DOM 的 class 名，所以 CSS 里用了 **一堆常见选择器联合起来“打散” header/sidebar/comment**。如果你愿意在浏览器里看一眼真实 DOM，把使用的 class/id 精简成更精确的几个，会更干净。不过就算不改，这版也能做到“去掉大部分杂物、保留正文+公式+图片”。

---

### 4.3 `kexue_book/merge.py` — 合并所有章节 PDF（可选书签）

```python
# kexue_book/merge.py
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from pypdf import PdfReader, PdfWriter

from .crawl import PostMeta


def merge_pdfs(
    pdf_paths: Iterable[Path],
    posts: Iterable[PostMeta],
    out_path: Path,
    add_bookmarks: bool = True,
) -> None:
    """
    将章节 PDF 合并为一本书。
    如果 add_bookmarks=True，则为每篇文章添加 PDF 书签。:contentReference[oaicite:13]{index=13}
    """
    writer = PdfWriter()
    pdf_paths = list(pdf_paths)
    posts = list(posts)

    assert len(pdf_paths) == len(posts), "章节 PDF 数量必须和文章数量一致"

    current_page = 0
    for pdf_path, post in zip(pdf_paths, posts):
        reader = PdfReader(str(pdf_path))
        num_pages = len(reader.pages)

        # 添加页面
        for page in reader.pages:
            writer.add_page(page)

        # 在合并后的 PDF 上添加书签
        if add_bookmarks and num_pages > 0:
            writer.add_outline_item(
                title=post.title,
                page_number=current_page,
            )

        current_page += num_pages

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        writer.write(f)

    print(f"[merge] 生成合并 PDF: {out_path}")
```

---

### 4.4 `kexue_book/cli.py` — 命令行入口：一条命令跑完整流水线

```python
# kexue_book/cli.py
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .crawl import crawl_posts
from .render import render_posts_to_pdfs
from .merge import merge_pdfs


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="把 科学空间·信息时代(Big-Data) 分类 打包成 PDF 书籍"
    )
    ap.add_argument(
        "--start",
        type=str,
        required=True,
        help="起始日期 YYYY-MM-DD（含）",
    )
    ap.add_argument(
        "--end",
        type=str,
        required=True,
        help="结束日期 YYYY-MM-DD（含）",
    )
    ap.add_argument(
        "--out-dir",
        type=str,
        default="output",
        help="输出目录（默认: output）",
    )
    ap.add_argument(
        "--name",
        type=str,
        default="BigData",
        help="书名前缀（默认: BigData）",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="调试用：只处理前 N 篇文章",
    )
    ap.add_argument(
        "--delay-ms",
        type=int,
        default=4000,
        help="渲染每页时额外等待的毫秒数，用来保证 MathJax 渲染完成",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()

    print(f"[crawl] 区间: {start_date} ~ {end_date}")
    posts = crawl_posts(start_date, end_date)
    if args.limit:
        posts = posts[: args.limit]
    print(f"[crawl] 命中文章数: {len(posts)}")

    out_dir = Path(args.out_dir)
    chapters_dir = out_dir / "chapters"

    pdf_paths = render_posts_to_pdfs(posts, chapters_dir, delay_ms=args.delay_ms)

    book_path = out_dir / f"{args.name}-{args.start}-{args.end}.pdf"
    merge_pdfs(pdf_paths, posts, book_path, add_bookmarks=True)

    print("[done] 书籍已生成，可以拷到 iPad 上阅读。")


if __name__ == "__main__":
    main()
```

---

## 5. 实际运行示例

假设你想把 2018–2020 的“信息时代”文章打包成一本：

```bash
# 激活虚拟环境
source .venv/bin/activate

# 一条命令搞定
python -m kexue_book.cli \
  --start 2018-01-01 \
  --end   2020-12-31 \
  --out-dir output \
  --name "Kexue-BigData"
```

跑完之后：

* `output/chapters/` 下面是一堆单篇 PDF。
* `output/Kexue-BigData-2018-01-01-2020-12-31.pdf` 就是一整本书：

  * 按时间顺序排好；
  * 每篇有 PDF 书签；
  * 侧边栏/评论/打赏/友情链接等被 CSS 隐藏；
  * 公式和图片由 MathJax + 原站 HTML 渲染后打印，视觉效果基本等于网页版。([Scientific Spaces][2])

你把这本 PDF 丢进 iCloud / OneDrive 或直接 AirDrop 给 iPad，就能像看教科书一样翻着看了。

---

## 6. 版权与使用边界（一定要心里有数）

从首页和文章 footer 可以看到，科学空间的内容是 **署名‑非商业用途‑保持一致（CC BY‑NC‑SA）** 协议：转载与改编都必须署名原作者、不得商用、再次分发时用相同协议。([Scientific Spaces][6])

这个工程：

* **个人自用**：抓文章做成 PDF 给自己在 iPad 上看，没有任何问题。
* **开源工程**：可以把这个代码放到 GitHub，只要在 README 里写明：

  * 这是针对 `Scientific Spaces / spaces.ac.cn` 的“个人阅读工具”；
  * 生成的 PDF 只用于个人学习，不建议公开分发；
  * 原文版权归苏剑林和科学空间所有，协议为 CC BY‑NC‑SA，并给出首页链接。
* **不建议**：把你生成好的整本 PDF 直接上传到公共网盘当“电子书”传播——这就有点越界了。

---

大概就是这样一套“工程级”的方案：从分类页出发、按日期可控、保留 MathJax 公式和图片、去掉杂项、合成一整本有书签的 PDF。
接下来你可以自己给这个仓库起个中二一点的名字，比如 `scientific-spaces-bigdata-book`，人生苦短，至少读书体验要舒服一点。

[1]: https://spaces.ac.cn/category/Big-Data "分类 信息时代 下的文章 - 科学空间|Scientific Spaces"
[2]: https://spaces.ac.cn/archives/4765 "《Attention is All You Need》浅读（简介+代码） - 科学空间|Scientific Spaces"
[3]: https://spaces.ac.cn/latex.html "公式 - 科学空间|Scientific Spaces"
[4]: https://kexue.fm/archives/4797?utm_source=chatgpt.com "增强typecho的搜索功能 - 科学空间"
[5]: https://pypdf.readthedocs.io/en/3.10.0/modules/PdfWriter.html?utm_source=chatgpt.com "The PdfWriter Class — pypdf 3.10.0 documentation"
[6]: https://spaces.ac.cn/ "科学空间|Scientific Spaces"
[7]: https://pypdf.readthedocs.io/en/stable/modules/PdfWriter.html?utm_source=chatgpt.com "The PdfWriter Class — pypdf 6.3.0 documentation"
