"""
把前端 (frontend/index.html + assets/app.css + assets/js/*.js，依 index.html 內 <script> 順序串接)
與 SQLite 最新資料快照打包。輸出兩種形式：

1. 拆分部署 (預設，供 GitHub Pages / Cloudflare 使用)
   - docs/index.html：只有程式 (HTML + CSS + JS)，改版時才會變動，瀏覽器可長期快取
   - docs/data.json ：資料快照，每次排程更新；以縮排格式輸出，git diff 只會看到真正變動的數字
   頁面載入時會用 fetch('data.json') 取得資料 (見 frontend/assets/js/03-navigation.js)。

2. 單檔離線版 (--single 輸出路徑)
   - 資料快照以 <script id="twfin-snapshot" type="application/json"> 內嵌，可直接雙擊開啟 (file:// 無法 fetch 旁邊的檔案)。
   - CI 每次排程會把它上傳到 data-latest Release (twfin-standalone.html)；Cloudflare Worker 與 Render 也以此形式提供。

- 不會修改 frontend/ 下的任何原始檔。
- 前端腳本是傳統 <script> (非 ES module)，彼此共用全域範圍，所以 HTML 內的 inline onclick 可直接呼叫；
  依序串接後行為與單一大檔完全一致。新增腳本時，只要在 index.html 依序加上 <script> 標籤即可。
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import get_dashboard_payload
from snapshot_bundle import SNAPSHOT_SLOT, inline_snapshot

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
FRONTEND_HTML = os.path.join(FRONTEND_DIR, "index.html")
CSS_PATH = os.path.join(FRONTEND_DIR, "assets", "app.css")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
DOCS_INDEX_HTML = os.path.join(DOCS_DIR, "index.html")
DOCS_DATA_JSON = os.path.join(DOCS_DIR, "data.json")

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


def build_shell():
    """只有程式 (HTML + CSS + JS)、不含資料快照的 index.html；內含 SNAPSHOT_SLOT 供組成單檔版。"""
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

    html = _replace_once(html, CSS_TAG, f"<style>\n{css}</style>")
    block = f"  {SNAPSHOT_SLOT}\n  <script>\n{js}</script>\n"
    return JS_BLOCK_RE.sub(lambda _m: block, html, count=1)


def serialize_data(payload):
    """data.json 的內容：縮排輸出，讓 git diff 以「行」為單位，只看到真正變動的欄位。"""
    return json.dumps(payload, ensure_ascii=False, indent=1) + "\n"


def build_bundle(payload):
    """單檔離線版：程式 + 內嵌資料快照。"""
    return inline_snapshot(build_shell(), payload)


def _write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def export_standalone():
    """寫出拆分版：docs/index.html (程式) 與 docs/data.json (資料)。"""
    payload = get_dashboard_payload(use_cache=False)
    shell, data = build_shell(), serialize_data(payload)
    _write(DOCS_INDEX_HTML, shell)
    _write(DOCS_DATA_JSON, data)
    _write(os.path.join(DOCS_DIR, ".nojekyll"), "")
    print(f"Exported app shell ({len(shell.encode('utf-8')) / 1024:.0f} KB) to: {DOCS_INDEX_HTML}")
    print(f"Exported data snapshot ({len(data.encode('utf-8')) / 1024:.0f} KB) to: {DOCS_DATA_JSON}")


def export_single(path):
    """寫出單檔離線版到指定路徑。"""
    bundle = build_bundle(get_dashboard_payload(use_cache=False))
    _write(path, bundle)
    print(f"Exported single-file offline dashboard ({len(bundle.encode('utf-8')) / 1024:.0f} KB) to: {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="匯出前端：預設輸出 docs/index.html + docs/data.json")
    ap.add_argument("--single", metavar="PATH", help="改為輸出可離線雙擊開啟的單檔版到 PATH")
    args = ap.parse_args(argv)
    if args.single:
        export_single(args.single)
    else:
        export_standalone()


if __name__ == "__main__":
    main()
