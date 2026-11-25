# Cloudflare Worker：私有存取 + 準時排程觸發

## 為什麼需要準時觸發

GitHub Actions 的 `schedule` 不準時。這個 repo 實測 08:30 UTC 的排程平均延遲約 70 分鐘、12:00 UTC 約 60 分鐘
（整點與半點是最擁擠的時段）。Cloudflare 的 cron 觸發則很準時，所以由 Worker 在預定時間呼叫 GitHub 的
`workflow_dispatch` 來啟動同步：

| 時間 (台灣) | UTC cron | 觸發者 |
|---|---|---|
| 週一～五 16:30 | `30 8 * * MON-FRI` | Cloudflare Worker (準時) |
| 週一～五 20:00 | `0 12 * * MON-FRI` | Cloudflare Worker (準時) |
| 約 16:43 / 20:17 | `43 8` / `17 12` | GitHub 自己的排程 (備援) |

GitHub 的備援排程仍保留：Cloudflare 或權杖出問題時資料還是會更新。兩者都正常時，晚到的備援排程會被
workflow 的 `gate` job 判斷「資料庫 90 分鐘內剛更新過」而略過，不會重複抓取。

## 一次性設定

1. **建立 GitHub 權杖**（Fine-grained personal access token）
   - GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
   - Repository access：只選這個 repo
   - Permissions：**Actions: Read and write**（其餘維持無權限）
   - 到期日建議設 90 天，並在行事曆上提醒自己更換（權杖過期時 Worker 的 cron 會顯示失敗，備援排程仍會執行）
2. **把權杖存成 Worker 機密**（不要寫進任何檔案）
   ```bash
   cd cloudflare
   npx wrangler secret put GH_DISPATCH_TOKEN
   ```
3. **確認變數**：`wrangler.toml` 的 `GH_REPO` 是 `owner/repo`。要觸發別的 workflow 或分支時可另外設
   `GH_WORKFLOW`、`GH_REF`。
4. **建置並部署**
   ```bash
   python build_worker.py      # 產生 worker.mjs (內嵌目前的 docs/index.html)
   npx wrangler deploy
   ```
   注意：私有網站內容是「建置當下」的 `docs/index.html`；之後要更新私有網站的畫面，需要重新建置並部署。

## 驗證

- 本機模擬：`npx wrangler dev --test-scheduled`，另開終端機執行
  `curl "http://localhost:8787/__scheduled?cron=30+8+*+*+MON-FRI"`，再用 `gh run list --event workflow_dispatch` 確認有新的執行。
- 正式環境：Cloudflare 後台 → Workers → `twfin-private` → Logs 可看到 `dispatchSync ok`；
  失敗（HTTP 401/403/404）時會顯示錯誤並把該次 cron 標示為失敗。
- 延遲追蹤：每次執行的 Actions summary 都有「排程閘門」區塊，列出排程類觸發的實際延遲與是否被略過。

## 未設定時

沒有設定 `GH_DISPATCH_TOKEN` 時，`scheduled()` 只會記錄一行訊息然後結束，不影響私有網站本身，也不會有錯誤。
