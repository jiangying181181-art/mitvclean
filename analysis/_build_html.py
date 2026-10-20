"""
把 analysis/*.md 转成自包含 HTML 报告（零外链，套用 deep-project-analysis 模板的组件样式）。

用法: python analysis/_build_html.py
"""
import html
import re
from pathlib import Path

TPL = Path(r"C:/Users/jiang/.workbuddy/plugins/cache/experts/opensource-x/1.1.0/skills/deep-project-analysis/assets/report-template.html")
ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent

FOOTER_LINKS = [
    ("架构实现分析", "mitvclean架构实现分析.html"),
    ("演化分析", "mitvclean基础层与领域模型演化分析.html"),
    ("第一性原理与巧思", "mitvclean第一性原理与设计巧思分析.html"),
    ("代码质量评估", "mitvclean代码质量评估.html"),
    ("技术栈拆解", "mitvclean技术栈拆解.html"),
]

KICKER = {
    "mitvclean架构实现分析": ("架构实现", "代码是怎么组织的、为什么这么组织、数据怎么流"),
    "mitvclean基础层与领域模型演化分析": ("架构演化", "这套架构是怎么演化来的"),
    "mitvclean第一性原理与设计巧思分析": ("第一性原理 · 设计巧思", "为谁解决什么不可回避的问题，哪些设计是必然的"),
    "mitvclean代码质量评估": ("代码质量", "这代码能改吗、从哪改——把印象换成可复现的指标"),
    "mitvclean技术栈拆解": ("技术栈", "这套栈还健康吗，基于它做二开的成本在哪"),
}


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def inline(s: str) -> str:
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    return s


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out = []
    i = 0
    n = len(lines)
    sec_no = 0

    def flush_para(buf):
        if buf:
            out.append("<p>" + inline(" ".join(buf)) + "</p>")
            buf.clear()

    para: list[str] = []

    while i < n:
        ln = lines[i]

        # 代码块
        if ln.startswith("```"):
            lang = ln[3:].strip() or "text"
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(
                '<div class="codebox"><div class="bar"><span class="dot"></span><span class="dot"></span>'
                '<span class="dot"></span><span class="fname">' + esc(lang) + "</span></div><pre><code data-lang=\""
                + esc(lang if lang in ("python", "yaml", "json", "bash", "text") else "text")
                + '">'
                + esc("\n".join(buf))
                + "</code></pre></div>"
            )
            continue

        # 表格
        if ln.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
            flush_para(para)
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = ["<table><thead><tr>"]
            t += ["<th>" + inline(h) + "</th>" for h in head]
            t.append("</tr></thead><tbody>")
            for r in rows:
                t.append("<tr>")
                t += ["<td>" + inline(c) + "</td>" for c in r]
                t.append("</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            flush_para(para)
            lvl = len(m.group(1))
            txt = m.group(2).strip()
            if lvl == 2:
                sec_no += 1
                out.append(f'<section id="s{sec_no}"><h2><span class="sec-no">{sec_no}</span>{inline(txt)}</h2>')
            elif lvl == 3:
                out.append(f"<h3>{inline(txt)}</h3>")
            elif lvl == 4:
                out.append(f"<h4>{inline(txt)}</h4>")
            else:
                out.append(f"<h3>{inline(txt)}</h3>")
            i += 1
            continue

        # 分隔线
        if re.match(r"^-{3,}$", ln.strip()):
            flush_para(para)
            out.append('<div class="callout info"><span class="t">—</span></div>')
            i += 1
            continue

        # 引用
        if ln.startswith("> "):
            flush_para(para)
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> ").rstrip())
                i += 1
            out.append('<div class="callout info">' + inline("<br>".join(buf)) + "</div>")
            continue

        # 列表
        if re.match(r"^\s*[-*]\s+", ln) or re.match(r"^\s*\d+\.\s+", ln):
            flush_para(para)
            items = []
            ordered = bool(re.match(r"^\s*\d+\.\s+", ln))
            while i < n and (re.match(r"^\s*[-*]\s+", lines[i]) or re.match(r"^\s*\d+\.\s+", lines[i])):
                t = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", lines[i])
                items.append("<li>" + inline(t) + "</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f'<{tag} class="check">' + "".join(items) + f"</{tag}>")
            continue

        if not ln.strip():
            flush_para(para)
            i += 1
            continue

        para.append(ln.strip())
        i += 1

    flush_para(para)
    return "\n".join(out)


def build(md_path: Path) -> str:
    md = md_path.read_text(encoding="utf-8")
    stem = md_path.stem
    key = stem
    kicker, sub = KICKER.get(key, ("分析", ""))
    body = md_to_html(md)

    # 去掉 md 里的一级标题（HTML 已有 hero 标题）
    body = re.sub(r"<h3>[^<]*分析对象.*?</h3>", "", body, flags=re.S)

    tpl = TPL.read_text(encoding="utf-8")
    # 提取 style 与 script 块
    style = re.search(r"<style>.*?</style>", tpl, re.S).group(0)
    bodies = []
    for m in re.finditer(r"<script>(.*?)</script>", tpl, re.S):
        js = m.group(1)
        if "tocNav" in js or "cv-h" in js or "colorize" in js:
            bodies.append(js)
    script = "\n".join(bodies)

    nav = "".join(f'<a href="{h}">{t}</a>' for t, h in FOOTER_LINKS)
    foot = " · ".join(f'<a href="{h}">{t}</a>' for t, h in FOOTER_LINKS)

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mitvclean · {kicker}</title>
{style}
</head>
<body>
<div class="layout">
  <aside class="toc">
    <div class="brand">
      <div class="brand-mark">mitv</div>
      <div><strong>{kicker}</strong><span>mitvclean 深度解构</span></div>
    </div>
    <nav id="tocNav"></nav>
  </aside>
  <main>
    <header class="hero">
      <div class="wrap">
        <div class="kicker">OpenSource-X · {kicker}</div>
        <h1>mitvclean · {kicker}</h1>
        <p>{esc(sub)}</p>
        <div class="meta">
          <span class="chip">分析对象 <b>mitvclean</b></span>
          <span class="chip">版本 <b>b277c37</b></span>
          <span class="chip">数据来源 <b>本地仓库直读</b></span>
          <span class="chip">日期 <b>2026-10-21</b></span>
        </div>
        <div class="conclusion"><b>结论先行：</b>见正文第一节「结论」，每条结论均可回溯到具体文件路径与行号。</div>
      </div>
    </header>
    <div class="content">
{body}
      <footer style="margin-top:70px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px">
        <span>mitvclean · {esc(kicker)} · 生成于 analysis/{esc(stem)}.md</span>
        <span>{foot}</span>
      </footer>
    </div>
  </main>
</div>
<script>
{script}
</script>
</body>
</html>
"""
    return page


def main():
    for md in sorted(ROOT.glob("mitvclean*.md")):
        if "思维导图" in md.stem:
            continue
        out = md.with_suffix(".html")
        out.write_text(build(md), encoding="utf-8")
        print("written:", out.name)


if __name__ == "__main__":
    main()
