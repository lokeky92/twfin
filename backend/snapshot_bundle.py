"""
單檔離線版的組裝邏輯 (不依賴資料庫與伺服器，export_standalone.py 與 server.py 共用，避免循環匯入)。

拆分部署時 docs/index.html 只有程式，內含一個「資料快照插入點」註解；把 docs/data.json 的內容內嵌進去，
就得到可離線雙擊開啟的單檔版 (Cloudflare Worker、Render 首頁、CI 上傳的 twfin-standalone.html 都用這個)。
"""
import json

# 拆分版 index.html 內預留的資料快照插入點
SNAPSHOT_SLOT = "<!-- twfin-snapshot-slot -->"


def inline_snapshot(shell_html, data):
    """
    把資料快照內嵌進 index.html。data 可以是 dict 或 data.json 的文字 / bytes。
    shell 已不含插入點 (舊格式的單檔，資料本來就內嵌) 或 data 為 None 時，原樣回傳。
    """
    if data is None or SNAPSHOT_SLOT not in shell_html:
        return shell_html
    payload = json.loads(data) if isinstance(data, (str, bytes)) else data
    # JSON 內的 "</" 需跳脫，避免資料中出現 </script> 時破壞頁面
    snapshot = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return shell_html.replace(
        SNAPSHOT_SLOT, f'<script id="twfin-snapshot" type="application/json">{snapshot}</script>', 1)
