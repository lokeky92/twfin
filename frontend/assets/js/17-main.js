async function probeLiveSources() {
  try {
    const res = await apiPost('/api/probe_sources', {});
    if (res.status === 401 || res.status === 403) {
      alert('❌ 管理權杖錯誤或未提供，無法觸發同步。');
      return;
    }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    if (data.status === 'ok') {
      STATE = data.dashboard;
      renderAll();
      alert('✅ 已完成本地官方 OpenAPI 即時同步與連線檢測！');
      return;
    }
    throw new Error('Unexpected response');
  } catch (e) {
    // 雲端快照模式 (沒有 API)：優先重新抓取 data.json；Cloudflare 單檔版則重新抓頁面並讀取內嵌快照
    try {
      const fresh = await fetchSnapshotFile();
      if (fresh) {
        STATE = fresh;
        loadMultiAgentLocalOverrides();
        renderAll();
        alert(`✅ 已重新同步雲端最新快照！
資料更新時間：${STATE.generated_at || '最新'}`);
        return;
      }
    } catch (dataErr) {}
    try {
      const freshRes = await fetch(window.location.pathname + '?_sync=' + Date.now(), { cache: 'no-store' });
      if (freshRes.ok) {
        const htmlText = await freshRes.text();
        const doc = new DOMParser().parseFromString(htmlText, 'text/html');
        const parsed = readEmbeddedSnapshot(doc);
        {
          if (parsed) {
            STATE = parsed;
            loadMultiAgentLocalOverrides();
            renderAll();
            alert(`✅ 已重新同步雲端最新快照！\n資料更新時間：${STATE.generated_at || '最新'}\n（雲端排程於每個交易日台灣時間 16:30 與 20:00 自動抓取 TWSE / TPEx / MOPS 更新）`);
            return;
          }
        }
      }
    } catch (innerErr) {}
    alert(`ℹ️ 目前為雲端快照模式，最新資料時間：${(STATE && STATE.generated_at) || '最新'}。\n雲端排程會於每個交易日台灣時間 16:30 與 20:00 自動抓取最新台股與 ETF 數據並部署。`);
  }
}

window.addEventListener('DOMContentLoaded', loadDashboard);
