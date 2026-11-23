"""
把前端 (frontend/index.html + assets/app.css + assets/app.js) 與 SQLite 最新資料快照
打包成單一檔案 docs/index.html，供 GitHub Pages / Cloudflare Worker 使用，也可直接雙擊離線開啟。

- 不會修改 frontend/ 下的任何原始檔。
- 快照以 <script id="twfin-snapshot" type="application/json"> 嵌入，前端 readEmbeddedSnapshot() 讀取。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import get_dashboard_payload

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
FRONTEND_HTML = os.path.join(FRONTEND_DIR, "index.html")
CSS_PATH = os.path.join(FRONTEND_DIR, "assets", "app.css")
JS_PATH = os.path.join(FRONTEND_DIR, "assets", "app.js")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
DOCS_INDEX_HTML = os.path.join(DOCS_DIR, "index.html")

CSS_TAG = '<link rel="stylesheet" href="assets/app.css" />'
JS_TAG = '<script src="assets/app.js"></script>'


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _replace_once(html, old, new):
    if html.count(old) != 1:
        raise RuntimeError(f"frontend/index.html 中找不到唯一的 {old!r}，無法打包")
    return html.replace(old, new)


def build_bundle(payload):
    html = _read(FRONTEND_HTML)
    css = _read(CSS_PATH)
    js = _read(JS_PATH)
    if "</script" in js.lower():
        raise RuntimeError("app.js 內含 '</script'，內嵌後會提前結束 <script> 標籤")

    # JSON 內的 "</" 需跳脫，避免資料中出現 </script> 時破壞頁面
    snapshot = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = _replace_once(html, CSS_TAG, f"<style>\n{css}</style>")
    html = _replace_once(
        html,
        JS_TAG,
        f'<script id="twfin-snapshot" type="application/json">{snapshot}</script>\n'
        f"  <script>\n{js}</script>",
    )
    return html


def export_standalone():
    payload = get_dashboard_payload(use_cache=False)
    bundle = build_bundle(payload)

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(DOCS_INDEX_HTML, "w", encoding="utf-8", newline="\n") as f:
        f.write(bundle)
    with open(os.path.join(DOCS_DIR, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")

    print(f"Exported single-file dashboard ({len(bundle.encode('utf-8')) / 1024:.0f} KB) to: {DOCS_INDEX_HTML}")


if __name__ == "__main__":
    export_standalone()
