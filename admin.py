#!/usr/bin/env python3
"""Local admin UI: create/edit/delete posts with a live preview, then rebuild the site."""

import html as html_lib
import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import index as blog

PORT = 8001

FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.md$")

ADMIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>
(function () {
  var stored = localStorage.getItem("theme");
  var theme = stored || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", theme);
})();
</script>
<title>{{TITLE}} - Blog Admin</title>
<link rel="stylesheet" href="/blog-assets/static/style.css">
<link rel="stylesheet" href="/static/admin.css">
</head>
<body>
<div class="terminal admin-terminal">
<div class="terminal-title">Blog Admin</div>
<main>
{{BODY}}
</main>
<footer>
<a href="/">Dashboard</a>
<a href="/site/" target="_blank">View site &#8599;</a>
<button id="theme-toggle" aria-label="Toggle dark mode">Dark mode</button>
</footer>
</div>
<script src="/blog-assets/static/theme.js" defer></script>
<script src="/static/admin.js" defer></script>
</body>
</html>
"""

ADMIN_CSS = """
.admin-terminal {
  max-width: 1100px;
}

.editor {
  display: flex;
  gap: 1.5rem;
  align-items: flex-start;
  flex-wrap: wrap;
}

.editor-form {
  flex: 1 1 380px;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.editor-preview {
  flex: 1 1 420px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.field label {
  font-size: 0.85rem;
  color: var(--muted);
}

input, textarea, button {
  font: inherit;
  font-size: 0.9rem;
  background: var(--code-bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.5rem;
}

input:focus, textarea:focus {
  outline: none;
  border-color: var(--accent);
}

textarea#body {
  min-height: 420px;
  resize: vertical;
  font-family: inherit;
}

button[type="submit"], .button {
  align-self: flex-start;
  background: var(--accent);
  color: var(--bg);
  border: none;
  font-weight: bold;
  cursor: pointer;
  text-decoration: none;
}

button[type="submit"]:hover, .button:hover {
  opacity: 0.85;
}

#preview {
  width: 100%;
  height: 600px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
}

.admin-post-list li {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.inline-form {
  display: inline;
  margin: 0;
}

button.link-button {
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  padding: 0;
  font-size: 0.85rem;
  text-decoration: underline;
}

button.link-button:hover {
  color: var(--accent);
}

.flash {
  color: var(--accent);
  font-weight: bold;
}

footer a {
  color: var(--link);
  margin-right: 1rem;
}
"""

ADMIN_JS = """
(function () {
  function debounce(fn, wait) {
    var t;
    return function () {
      clearTimeout(t);
      var args = arguments;
      t = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  function updatePreview() {
    var titleEl = document.getElementById("title");
    var dateEl = document.getElementById("date");
    var bodyEl = document.getElementById("body");
    var iframe = document.getElementById("preview");
    if (!iframe || !titleEl || !bodyEl) return;

    fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: titleEl.value,
        date: dateEl.value,
        body: bodyEl.value
      })
    })
      .then(function (res) { return res.json(); })
      .then(function (data) { iframe.srcdoc = data.html; });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var debounced = debounce(updatePreview, 300);
    ["title", "date", "body"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("input", debounced);
    });
    updatePreview();
  });
})();
"""


def list_posts():
    posts = []
    for filename in sorted(os.listdir(blog.POSTS_DIR)):
        if not filename.endswith(".md"):
            continue
        meta, _ = blog.parse_post(os.path.join(blog.POSTS_DIR, filename))
        posts.append({
            "filename": filename,
            "title": meta.get("title", filename),
            "date": meta.get("date", ""),
        })
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def render_admin_page(title, body):
    return ADMIN_PAGE.replace("{{TITLE}}", html_lib.escape(title, quote=False)).replace("{{BODY}}", body)


def dashboard_page():
    posts = list_posts()
    if posts:
        rows = "\n".join(
            f'<li><span class="date">{html_lib.escape(p["date"], quote=False)}</span> '
            f'<a href="/edit/{html_lib.escape(p["filename"])}">{html_lib.escape(p["title"], quote=False)}</a> '
            f'<form class="inline-form" method="post" action="/delete">'
            f'<input type="hidden" name="filename" value="{html_lib.escape(p["filename"])}">'
            f'<button type="submit" class="link-button" '
            f'onclick="return confirm(\'Delete this post?\')">Delete</button>'
            f'</form></li>'
            for p in posts
        )
    else:
        rows = "<li>No posts yet.</li>"

    body = f"""<h2>Posts</h2>
<ul class="post-list admin-post-list">
{rows}
</ul>
<p><a class="button" href="/new">+ New post</a></p>"""
    return render_admin_page("Dashboard", body)


def edit_page(filename, saved=False):
    if filename:
        meta, post_body = blog.parse_post(os.path.join(blog.POSTS_DIR, filename))
        title = meta.get("title", "")
        date = meta.get("date", "")
    else:
        filename = ""
        title = ""
        date = ""
        post_body = ""

    flash = '<p class="flash">Saved.</p>' if saved else ""
    filename_attr = ' readonly' if filename else ""

    form = f"""{flash}
<form id="edit-form" method="post" action="/save">
<input type="hidden" name="original_filename" value="{html_lib.escape(filename)}">
<div class="field">
<label for="filename">Filename</label>
<input id="filename" name="filename" value="{html_lib.escape(filename)}" placeholder="2026-06-15-my-post.md"{filename_attr} required>
</div>
<div class="field">
<label for="title">Title</label>
<input id="title" name="title" value="{html_lib.escape(title)}" required>
</div>
<div class="field">
<label for="date">Date</label>
<input id="date" name="date" value="{html_lib.escape(date)}" placeholder="YYYY-MM-DD">
</div>
<div class="field">
<label for="body">Content (Markdown)</label>
<textarea id="body" name="body" rows="20">{html_lib.escape(post_body)}</textarea>
</div>
<button type="submit">Save</button>
</form>"""

    layout = (
        '<div class="editor">'
        f'<div class="editor-form">{form}</div>'
        '<div class="editor-preview"><iframe id="preview" title="Preview"></iframe></div>'
        '</div>'
    )
    return render_admin_page("Edit post" if filename else "New post", layout)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_html(self, html_text, status=200):
        payload = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_text(self, text, content_type):
        payload = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_file(self, base_dir, rel_path):
        rel_path = unquote(rel_path) or "index.html"
        full = os.path.normpath(os.path.join(base_dir, rel_path))
        base_abs = os.path.abspath(base_dir)
        if not os.path.abspath(full).startswith(base_abs) or not os.path.isfile(full):
            self.send_error(404)
            return
        ctype, _ = mimetypes.guess_type(full)
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            self.send_html(dashboard_page())
        elif path == "/new":
            self.send_html(edit_page(None))
        elif path.startswith("/edit/"):
            filename = unquote(path[len("/edit/"):])
            if not FILENAME_RE.match(filename) or not os.path.isfile(os.path.join(blog.POSTS_DIR, filename)):
                self.send_error(404)
                return
            self.send_html(edit_page(filename, saved=query.get("saved") == ["1"]))
        elif path == "/static/admin.css":
            self.send_text(ADMIN_CSS, "text/css")
        elif path == "/static/admin.js":
            self.send_text(ADMIN_JS, "application/javascript")
        elif path.startswith("/blog-assets/static/"):
            self.serve_file(blog.STATIC_DIR, path[len("/blog-assets/static/"):])
        elif path == "/site" or path == "/site/":
            self.serve_file(blog.OUTPUT_DIR, "index.html")
        elif path.startswith("/site/"):
            self.serve_file(blog.OUTPUT_DIR, path[len("/site/"):])
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/save":
            self.handle_save()
        elif self.path == "/delete":
            self.handle_delete()
        elif self.path == "/api/preview":
            self.handle_preview()
        else:
            self.send_error(404)

    def handle_save(self):
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode("utf-8"))
        filename = data.get("filename", [""])[0].strip()
        original = data.get("original_filename", [""])[0].strip()
        title = data.get("title", [""])[0]
        date = data.get("date", [""])[0]
        body = data.get("body", [""])[0]

        if not FILENAME_RE.match(filename):
            self.send_error(400, "Invalid filename (must be letters, digits, ., _, - and end with .md)")
            return

        content = f"---\ntitle: {title}\ndate: {date}\n---\n\n{body}\n"
        with open(os.path.join(blog.POSTS_DIR, filename), "w", encoding="utf-8") as f:
            f.write(content)

        if original and original != filename and FILENAME_RE.match(original):
            old_path = os.path.join(blog.POSTS_DIR, original)
            if os.path.isfile(old_path):
                os.remove(old_path)

        blog.build()

        self.send_response(303)
        self.send_header("Location", f"/edit/{filename}?saved=1")
        self.end_headers()

    def handle_delete(self):
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode("utf-8"))
        filename = data.get("filename", [""])[0].strip()

        if FILENAME_RE.match(filename):
            path = os.path.join(blog.POSTS_DIR, filename)
            if os.path.isfile(path):
                os.remove(path)
            blog.build()

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def handle_preview(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        title = data.get("title", "")
        date = data.get("date", "")
        body = data.get("body", "")

        content_html = blog.post_content_html(title, date, body)
        page = blog.render_page(title or "Preview", content_html, root="/blog-assets/")

        payload = json.dumps({"html": page}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    blog.build()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Admin UI at http://127.0.0.1:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
