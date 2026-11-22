"""
將 SQLite 資料庫最新快照編譯並注入至獨立可執行的 HTML 研究儀表板 (dist/twfin_dashboard_standalone.html)
讓使用者即使不啟動 Python Server 也能直接雙擊開啟完整功能，啟動 Server 時則自動切換為 Live SQLite API 模式。
"""
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import get_dashboard_payload

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_HTML = os.path.join(BASE_DIR, "frontend", "index.html")
STANDALONE_HTML = os.path.join(BASE_DIR, "frontend", "twfin_dashboard_standalone.html")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
DOCS_INDEX_HTML = os.path.join(DOCS_DIR, "index.html")

def export_standalone():
    payload = get_dashboard_payload()
    with open(FRONTEND_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    inject_script = f"""
    <script>
      window.__INITIAL_SQLITE_SNAPSHOT__ = {json.dumps(payload, ensure_ascii=False)};
    </script>
    """
    # 修改 frontend/index.html 使其同時支援 Live API 與本地嵌入式 SQLite 快照備援
    old_loader = """    async function loadDashboard() {
      const res = await fetch('/api/dashboard');
      STATE = await res.json();
      renderAll();
    }"""

    new_loader = """    async function loadDashboard() {
      try {
        const res = await fetch('/api/dashboard');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        STATE = await res.json();
      } catch (e) {
        if (window.__INITIAL_SQLITE_SNAPSHOT__) {
          STATE = window.__INITIAL_SQLITE_SNAPSHOT__;
        }
      }
      renderAll();
    }"""

    updated_html = html.replace(old_loader, new_loader)
    with open(FRONTEND_HTML, "w", encoding="utf-8") as f:
        f.write(updated_html)

    standalone_content = updated_html.replace("</head>", inject_script + "\n</head>")
    with open(STANDALONE_HTML, "w", encoding="utf-8") as f:
        f.write(standalone_content)

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(DOCS_INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(standalone_content)
    with open(os.path.join(DOCS_DIR, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")

    print(f"Exported standalone & dual-mode dashboard to: {STANDALONE_HTML}")
    print(f"Exported GitHub Pages / Cloudflare Pages ready site to: {DOCS_INDEX_HTML}")

if __name__ == "__main__":
    export_standalone()
