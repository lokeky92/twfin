"""
把前端 (frontend/index.html + assets/app.css + assets/js/*.js，依 index.html 內 <script> 順序串接)
與 SQLite 最新資料快照打包成單一檔案 docs/index.html，
供 GitHub Pages / Cloudflare Worker 使用，也可直接雙擊離線開啟。

- 不會修改 frontend/ 下的任何原始檔。
- 快照以 <script id="twfin-snapshot" type="application/json"> 嵌入，前端 readEmbeddedSnapshot() 讀取。
- 前端腳本是傳統 <script> (非 ES module)，彼此共用全域範圍，所以 HTML 內的 inline onclick 可直接呼叫；
  依序串接後行為與單一大檔完全一致。新增腳本時，只要在 index.html 依序加上 <script> 標籤即可。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import get_dashboard_payload

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
FRONTEND_HTML = os.path.join(FRONTEND_DIR, "index.html")
CSS_PATH = os.path.join(FRONTEND_DIR, "assets", "app.css")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
DOCS_INDEX_HTML = os.path.join(DOCS_DIR, "index.html")

CSS_TAG = '<link rel="stylesheet" href="assets/app.css" />'
# index.html 內連續的 <script src="assets/js/NN-xxx.js"></script> 區段
JS_BLOCK_RE = re.compile(r'(?:[ \t]*<script src="assets/js/[^"]+\.js"></script>\r?\n?)+')
JS_SRC_RE = re.compile(r'<script src="(assets/js/[^"]+\.js)"></script>')


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _replace_once(html, old, new):
    if html.count(old) != 1:
        raise RuntimeError(f"frontend/index.html 中找不到唯一的 {old!r}，無法打包")
    return html.replace(old, new)


def read_frontend_scripts(html):
    """依 index.html 的順序回傳 [(相對路徑, 內容)]。"""
    return [(rel, _read(os.path.join(FRONTEND_DIR, *rel.split("/")))) for rel in JS_SRC_RE.findall(html)]


def build_bundle(payload):
    html = _read(FRONTEND_HTML)
    css = _read(CSS_PATH)
    scripts = read_frontend_scripts(html)
    if not scripts:
        raise RuntimeError("frontend/index.html 中找不到 assets/js/*.js 的 <script> 標籤")
    if len(JS_BLOCK_RE.findall(html)) != 1:
        raise RuntimeError("frontend/index.html 的 assets/js 腳本標籤必須是連續的一整段")
    js = "\n".join(code for _, code in scripts)
    if "</script" in js.lower():
        raise RuntimeError("前端腳本內含 '</script'，內嵌後會提前結束 <script> 標籤")

    # JSON 內的 "</" 需跳脫，避免資料中出現 </script> 時破壞頁面
    snapshot = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = _replace_once(html, CSS_TAG, f"<style>\n{css}</style>")
    block = (
        f'<script id="twfin-snapshot" type="application/json">{snapshot}</script>\n'
        f"  <script>\n{js}</script>\n"
    )
    return JS_BLOCK_RE.sub(lambda _m: block, html, count=1)


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
