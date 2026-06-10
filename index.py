#!/usr/bin/env python3
"""Pure-stdlib static blog generator: posts/*.md -> output/."""

import html as html_lib
import os
import re
import shutil
from datetime import datetime

POSTS_DIR = "posts"
OUTPUT_DIR = "output"
STATIC_DIR = "static"
SITE_TITLE = "My Blog"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}} - {{SITE_TITLE}}</title>
<link rel="stylesheet" href="{{ROOT}}static/style.css">
</head>
<body>
<header>
<h1><a href="{{ROOT}}index.html">{{SITE_TITLE}}</a></h1>
</header>
<main>
{{CONTENT}}
</main>
<footer>
<p>&copy; {{YEAR}} {{SITE_TITLE}}</p>
</footer>
</body>
</html>
"""


def render_page(title, content_html, root):
    page = PAGE_TEMPLATE
    page = page.replace("{{TITLE}}", html_lib.escape(title, quote=False))
    page = page.replace("{{SITE_TITLE}}", SITE_TITLE)
    page = page.replace("{{ROOT}}", root)
    page = page.replace("{{CONTENT}}", content_html)
    page = page.replace("{{YEAR}}", str(datetime.now().year))
    return page


def render_inline(text):
    text = html_lib.escape(text, quote=False)

    code_spans = []

    def stash_code(m):
        code_spans.append(m.group(1))
        return f"\x00{len(code_spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash_code, text)

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", text)

    for i, code in enumerate(code_spans):
        text = text.replace(f"\x00{i}\x00", f"<code>{code}</code>")

    return text


def is_special_line(line):
    return bool(
        re.match(r"^#{1,6}\s+", line)
        or re.match(r"^[-*]\s+", line)
        or re.match(r"^\d+\.\s+", line)
        or line.startswith(">")
        or line.startswith("```")
        or re.match(r"^(-{3,}|\*{3,}|_{3,})$", line)
    )


def markdown_to_html(text):
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code = html_lib.escape("\n".join(code_lines), quote=False)
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{code}</code></pre>")
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{render_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            out.append("<hr>")
            i += 1
            continue

        if stripped.startswith(">"):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(re.sub(r"^>\s?", "", lines[i].strip()))
                i += 1
            out.append(f"<blockquote>{markdown_to_html(chr(10).join(quote_lines))}</blockquote>")
            continue

        if re.match(r"^[-*]\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                item_text = re.sub(r"^[-*]\s+", "", lines[i].strip())
                items.append(f"<li>{render_inline(item_text)}</li>")
                i += 1
            out.append("<ul>\n" + "\n".join(items) + "\n</ul>")
            continue

        if re.match(r"^\d+\.\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                item_text = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                items.append(f"<li>{render_inline(item_text)}</li>")
                i += 1
            out.append("<ol>\n" + "\n".join(items) + "\n</ol>")
            continue

        para_lines = []
        while i < len(lines) and lines[i].strip() and not is_special_line(lines[i].strip()):
            para_lines.append(lines[i].strip())
            i += 1
        out.append("<p>" + render_inline(" ".join(para_lines)) + "</p>")

    return "\n".join(out)


def parse_post(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()

    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end].strip()
            body = text[end + 4:].lstrip("\n")
            for line in front.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip().lower()] = value.strip()

    return meta, body


def build():
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(os.path.join(OUTPUT_DIR, "posts"))

    if os.path.isdir(STATIC_DIR):
        shutil.copytree(STATIC_DIR, os.path.join(OUTPUT_DIR, "static"))

    posts = []
    for filename in sorted(os.listdir(POSTS_DIR)):
        if not filename.endswith(".md"):
            continue

        meta, body = parse_post(os.path.join(POSTS_DIR, filename))
        slug = filename[:-len(".md")]
        title = meta.get("title", slug)
        date = meta.get("date", "")

        content_html = (
            f"<article>\n<h2>{html_lib.escape(title, quote=False)}</h2>\n"
            f'<p class="date">{html_lib.escape(date, quote=False)}</p>\n'
            f"{markdown_to_html(body)}\n</article>"
        )
        page = render_page(title, content_html, root="../")

        with open(os.path.join(OUTPUT_DIR, "posts", f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(page)

        posts.append({"title": title, "date": date, "slug": slug})

    posts.sort(key=lambda p: p["date"], reverse=True)

    items = "\n".join(
        f'<li><span class="date">{html_lib.escape(p["date"], quote=False)}</span> '
        f'<a href="posts/{p["slug"]}.html">{html_lib.escape(p["title"], quote=False)}</a></li>'
        for p in posts
    )
    index_content = f'<ul class="post-list">\n{items}\n</ul>'
    index_page = render_page("Home", index_content, root="")

    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page)

    print(f"Built {len(posts)} post(s) into {OUTPUT_DIR}/")


if __name__ == "__main__":
    build()
