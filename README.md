# Scientific Spaces Big-Data PDF builder

将科学空间（spaces.ac.cn）“信息时代”分类下的文章抓取并合成一本带书签的 PDF，方便 iPad 等设备离线阅读。项目遵循原站点的 CC BY-NC-SA 协议，仅供个人学习使用。

## 目录结构

```
kexue_book/
  crawl.py   # 爬取分类页，收集文章元信息
  render.py  # Playwright 渲染单篇 PDF
  merge.py   # 合并章节并写入书签
  cli.py     # 命令行入口
output/
  chapters/  # 渲染出的单篇 PDF（运行后生成）
```

## 环境准备

```bash
conda create -n kexue-book python=3.11 -y
conda activate kexue-book
pip install -r requirements.txt
python -m playwright install chromium
```

已有环境更新依赖（当 requirements.txt 变化时）：

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## 快速开始

```bash
python -m kexue_book.cli \
  --start 2015-01-01 \
  --end   2025-12-31 \
  --out-dir output \
  --name "Kexue-BigData" \
  --cover 
```

默认行为与功能：

- 文章按日期从旧到新排列（`--order asc`），需要从新到旧用 `--order desc`。
- 每篇文章会生成可点击的 PDF 书签目录。
- 页脚会印出真实页码，从封面起连续编号；可用 `--no-page-numbers` 关闭。
- 可选封面 `--cover`，标题为“苏剑林选集”。

常用开关：

- `--cover`：在最前面加一页封面（标题“苏剑林选集”）
- `--order desc`：按日期从新到旧排列文章（默认从旧到新）
- `--no-page-numbers`：关闭页脚页码（默认开启）

命令会：

1. 从 `https://spaces.ac.cn/category/Big-Data` 起始，按分页收集所有文章标题、URL 和日期，并按日期过滤。
2. 用 Playwright + Chromium 打开每篇文章，等待 MathJax 渲染后注入打印样式，再导出单篇 PDF 到 `output/chapters/`。
3. 使用 `pypdf` 合并章节，生成 `output/Kexue-BigData-YYYY-MM-DD-YYYY-MM-DD.pdf`，并为每篇文章创建书签。

## 注意事项

- Playwright 会自动下载浏览器，首次运行时间较长。
- 渲染时会隐藏站点的侧边栏、评论区等元素，正文和公式将保留。
- 合并时默认为每页打印页码，如不需要可用 `--no-page-numbers` 关闭。
- 生成的 PDF 仅用于个人学习与收藏，请遵守科学空间的 CC BY-NC-SA 协议。
