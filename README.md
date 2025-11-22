# Scientific Spaces Big-Data PDF builder

将科学空间（[spaces.ac.cn](https://spaces.ac.cn)）“信息时代”（Big-Data 分类）下的文章抓取并合成一本带书签和页码的 PDF，方便在 iPad 等设备上离线阅读。

> ⚠️ **版权说明**：科学空间的文章采用 CC BY-NC-SA 协议（署名-非商业性使用-相同方式共享）。本项目只抓取公开网页并本地生成 PDF，仅供个人学习与收藏使用，请勿用于任何商业用途，转发时请注明原作者与原站链接。

---

## 目录结构

```text
kexue_book/
  __init__.py   # 包入口，导出 Post 类型
  types.py      # Post 元数据结构（标题 / URL / 日期）
  crawl.py      # 爬取 Big-Data 分类页，收集文章元信息
  render.py     # Playwright 渲染单篇 HTML -> 单篇 PDF
  merge.py      # 合并章节 PDF，添加封面、书签、页码
  cli.py        # 命令行入口（python -m kexue_book.cli）
output/          # 运行后生成的输出目录
  chapters/      # 渲染出的单篇 PDF
  *.pdf          # 最终合并后的“选集”PDF
requirements.txt
README.md
```

---

## 环境准备

建议使用 Python 3.11（其他 3.10+ 一般也可以）。

```bash
conda create -n kexue-book python=3.11 -y
conda activate kexue-book

pip install -r requirements.txt
python -m playwright install chromium
```

如果后续 `requirements.txt` 有更新，只需在已有环境中重新执行一次：

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

> Playwright 会自动下载 Chromium，可视为一次性的“浏览器安装”。

---

## 快速开始

下面命令会把 2015–2025 年的“信息时代”文章打包成一本 PDF，并加上封面和页码：

```bash
python -m kexue_book.cli \
  --start 2015-01-01 \
  --end   2025-12-31 \
  --out-dir output \
  --name "Kexue-BigData" \
  --cover
```

生成结果示例：

* 单篇 PDF：`output/chapters/001-XXXX.pdf`, `002-YYYY.pdf`, ...
* 合并书籍：`output/Kexue-BigData-2015-01-01-2025-12-31.pdf`

---

## 默认行为与功能

* 文章按日期从旧到新排列（等价于 `--order asc`），想从新到旧则使用 `--order desc`。
* 每篇文章会生成 **可点击的 PDF 书签目录**：在阅读器的“目录/书签”面板中可以直接跳转到对应文章。
* 页脚会印出 **真实页码**，从整本书的第一页（封面）开始连续编号；可用 `--no-page-numbers` 关闭。
* 可选封面 `--cover`，标题为 **“苏剑林选集”**，副标题为 “Scientific Spaces · Big-Data”。
* 会自动隐藏站点的侧边栏、评论区等元素，正文和公式（MathJax 渲染）都会保留。

---

## 命令行参数

核心参数：

* `--start YYYY-MM-DD`：起始日期（含），必选。
* `--end YYYY-MM-DD`：结束日期（含），必选。
* `--out-dir PATH`：输出目录（默认：`output`）。
* `--name NAME`：生成的 PDF 文件名前缀（默认：`BigData`）。

排版 / 排序相关：

* `--order asc|desc`  
  按日期排序方式：
  * `asc`：从旧到新（默认，适合作为“时间线教科书”）。
  * `desc`：从新到旧（最近的文章在前，适合追新）。

* `--cover`  
  在最前面加一页封面，标题写“苏剑林选集”。

* `--no-page-numbers`  
  关闭每页底部的页码（默认是 **有** 页码的）。

渲染控制：

* `--delay-ms N`  
  每篇文章在打印 PDF 前额外等待的毫秒数，用于确保 MathJax 等脚本完成渲染（默认：4000）。

调试用参数：

* `--limit N`  
  只抓取并渲染前 N 篇文章，适合调试样式/字体时使用，不想一次扫全站。

---

## 整体流程

运行 `python -m kexue_book.cli ...` 时会执行三步：

1. **抓取元信息（crawl）**  
   从 `https://spaces.ac.cn/category/Big-Data` 起始，按分页依次抓取：  
   * 每篇文章的标题、URL 和发布日期；  
   * 按 `--start` / `--end` 过滤在时间区间内的文章；  
   * 按 `--order` 指定的顺序排序。

2. **单篇渲染（render）**  
   对每一篇文章：  
   * 使用 Playwright + Chromium 打开文章页面；  
   * 等待网络稳定，再额外等待 `--delay-ms` 毫秒以保证 MathJax 完全渲染；  
   * 注入一段打印专用 CSS：隐藏头部导航、侧边栏、评论等非正文；控制版芯宽度、字体和行距；  
   * 调用 `page.pdf()` 导出为 A4 纸大小的单篇 PDF，存到 `output/chapters/`。

3. **合并与排版（merge）**  
   使用 `pypdf` 和 `reportlab`：  
   * 按顺序合并所有单篇 PDF；  
   * 如果开启 `--cover`，在最前面添加一页封面；  
   * 为每篇文章创建一个 PDF 书签（outline item），相当于一个可点击的目录；  
   * 如果没有 `--no-page-numbers`，为合并后的每一页生成底部居中的页码（1, 2, 3, ...），包括封面在内。

最终得到一本文档级别的 “苏剑林选集 · 信息时代” PDF。

---

## 注意事项与小贴士

* 第一次运行时 Playwright 会下载 Chromium，时间可能略长。
* 如果科学空间将来更换主题或改版 HTML 结构，`crawl.py` 里的 CSS 选择器（例如 `div.Post`, `span.submitted`）可能需要微调。
* 封面目前使用 ReportLab 的内置 Helvetica 字体直接绘制 **“苏剑林选集”**，在某些环境下可能出现方框。想要更漂亮/稳健的中文封面，可以：
  * 自己下载中文字体（如 Noto Serif SC / 思源宋体），
  * 在 `merge.py` 的 `_make_cover_pdf` 中注册对应 TTF 并替换 `setFont("Helvetica-Bold", 32)`。
* 渲染逻辑默认假设原文中的公式由 MathJax 渲染，且在 `--delay-ms` 指定时间内能完成；如果发现部分页面公式缺失，可以适当调大该参数。
* 生成的 PDF 仅用于 **个人学习和收藏**，请尊重原站点的 CC BY-NC-SA 协议，转载或分发时务必注明原作者“苏剑林”和科学空间链接。

---

生成好 PDF 之后，把最终的 `*.pdf` 丢进 iCloud / AirDrop 给 iPad，用任意 PDF 阅读器打开，就可以当一本“官方未发行的《苏剑林·信息时代选集》”慢慢啃了。
