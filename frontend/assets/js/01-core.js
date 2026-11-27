let STATE = null;
let APP_MODE = 'A';
let REDUCED_MOTION = false;
let SANKEY_TIMER = null;
let TIMELINE_TIMER = null;

// 在某個容器上方放一行「資料來源說明」(即時 / 手寫 / 月資料…)；同一個 id 重複呼叫只會更新文字
function setSourceNote(anchorId, noteId, text) {
  let anchor = document.getElementById(anchorId);
  if (!anchor) return;
  if (anchor.tagName === 'TBODY' && anchor.closest) anchor = anchor.closest('table') || anchor;   // 不能把 div 塞進表格內部
  let note = document.getElementById(noteId);
  if (!note) {
    note = document.createElement('div');
    note.id = noteId;
    note.style.cssText = 'font-size:12.5px; margin:4px 2px 12px; color:var(--text-muted);';
    anchor.parentNode.insertBefore(note, anchor);
  }
  note.textContent = text;
}

// 前瞻追蹤用的「快照組成」說明：哪幾天用內建種子子分數、哪幾天用即時評分 (兩者尺度不同，結果混合兩種模型)
function snapshotCompositionHtml(src) {
  if (!src) return '';
  const seed = src.seed || [], live = src.live || [];
  const fmt = (a) => a.length ? a.map(d => esc(d.slice(5))).join('、') : '無';
  return `<div class="callout" style="margin:8px 0; --callout-col:var(--accent-orange); font-size:12.5px;">
    <strong>快照組成</strong>：舊模型 ${seed.length} 天（${fmt(seed)}：營收與法人輸入是官方資料，但 5 項子分數是內建種子值）＋ 即時評分 ${live.length} 天（${fmt(live)}：子分數由官方資料每日重算）。
    兩種分數的尺度與方法不同，下方統計混合了兩種模型，請自行判斷；之後新增的快照都是即時評分。</div>`;
}

// ---- 安全性工具 ----
// 將任意值轉為可安全插入 innerHTML 的字串（防止儲存型 XSS）
function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const ADMIN_TOKEN_KEY = 'twfin_admin_token';
function getAdminToken() {
  try { return localStorage.getItem(ADMIN_TOKEN_KEY) || ''; } catch (e) { return ''; }
}
function setAdminToken(t) {
  try { localStorage.setItem(ADMIN_TOKEN_KEY, t); } catch (e) {}
}

// 所有寫入型 API 統一由此送出；伺服器要求權杖 (401) 時會提示輸入一次並記住
async function apiPost(path, body) {
  const send = () => {
    const headers = { 'Content-Type': 'application/json' };
    const token = getAdminToken();
    if (token) headers['X-Admin-Token'] = token;
    return fetch(path, { method: 'POST', headers, body: JSON.stringify(body || {}) });
  };
  let res = await send();
  if (res.status === 401) {
    const t = window.prompt('此操作需要管理權杖（伺服器環境變數 TWFIN_ADMIN_TOKEN）：');
    if (t) {
      setAdminToken(t.trim());
      res = await send();
    }
  }
  return res;
}

// 顯示目前資料中「即時官方 API」與「內建種子／參考資料」的比例，並依各來源新鮮度標示整體狀態
const SOURCE_STATUS_LABEL = {
  OK: ['正常', 'var(--accent-green, #34d399)'], DEGRADED: ['筆數異常', '#fbbf24'], STALE: ['資料過期', '#fbbf24'],
  FAILED: ['擷取失敗', '#fb7185'], EMPTY: ['無資料', '#fb7185'],
};
function renderDataProvenance() {
  const el = document.getElementById('dataProvenanceBadge');
  if (!el) return;
  const p = STATE && STATE.data_provenance;
  if (!p) { el.style.display = 'none'; return; }
  el.style.display = '';
  const live = p.live_sections || [];
  const seed = p.seed_sections || [];
  const ss = p.source_status || [];
  const bad = ss.filter(x => x.status !== 'OK');
  const hasBad = bad.length > 0;
  const hasFatal = bad.some(x => x.status === 'FAILED' || x.status === 'EMPTY');
  el.textContent = !p.live_data_available
    ? '⚠️ 目前僅有內建種子資料'
    : hasBad
      ? `⚠️ ${bad.length} 個來源異常｜即時 ${live.length} 區｜種子 ${seed.length} 區`
      : `即時資料 ${live.length} 區｜種子參考 ${seed.length} 區`;
  el.className = 'badge ' + (!p.live_data_available || hasFatal ? 'badge-lvlR' : hasBad ? 'badge-grade-C' : 'badge-grade-B');
  el.style.cursor = 'pointer';
  el.onclick = toggleFreshnessPanel;
  el.title = [
    p.note || '',
    '',
    `即時官方 API：${live.join('、') || '無'}`,
    `內建種子／參考：${seed.join('、') || '無'}`,
    p.last_live_ingestion ? `最近一次即時擷取：${p.last_live_ingestion}` : '',
    '',
    '點擊展開「資料新鮮度」面板',
  ].join('\n');
  renderFreshnessPanel();
  renderStaleBanner();
}

// ---- 資料過期警示橫幅 ----
// 靜態頁可能在資料產生很多天後才被開啟，所以以「開啟當下」的日期重算：最新資料日期落後 STALE_BUSINESS_DAYS 個營業日以上就顯示橫幅。
// 只排除週末，不含國定假日；連假期間出現屬正常，橫幅文字會說明。
const STALE_BUSINESS_DAYS = 4;
function businessDaysBetween(fromIso, toDate) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(fromIso || ''));
  if (!m) return null;
  const from = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  const to = new Date(Date.UTC(toDate.getFullYear(), toDate.getMonth(), toDate.getDate()));
  if (to <= from) return 0;
  let n = 0;
  for (let d = new Date(from.getTime() + 86400000); d <= to; d = new Date(d.getTime() + 86400000)) {
    const w = d.getUTCDay();
    if (w !== 0 && w !== 6) n++;
  }
  return n;
}
function computeStaleness(p, generatedAt, now) {
  const dates = ((p && p.source_status) || []).map(x => String(x.data_date || '').slice(0, 10)).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d)).sort();
  const latest = dates.length ? dates[dates.length - 1] : String(generatedAt || '').slice(0, 10);
  const days = businessDaysBetween(latest, now);
  const failed = ((p && p.source_status) || []).filter(x => x.status === 'FAILED' || x.status === 'EMPTY');
  return { latest, days, stale: days !== null && days >= STALE_BUSINESS_DAYS, failed };
}
function renderStaleBanner(now) {
  const p = STATE && STATE.data_provenance;
  let bar = document.getElementById('staleBanner');
  if (!p) { if (bar) bar.style.display = 'none'; return; }
  const r = computeStaleness(p, STATE.generated_at, now || new Date());
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'staleBanner';
    bar.style.cssText = 'margin:8px 16px; padding:10px 14px; border-radius:8px; font-size:13px; cursor:pointer; border:1px solid #fb7185; background:rgba(251,113,133,.12); color:#fecdd3;';
    bar.onclick = toggleFreshnessPanel;
    const header = document.querySelector('header');
    if (header) header.parentNode.insertBefore(bar, header.nextSibling);
  }
  if (!r.stale && !r.failed.length) { bar.style.display = 'none'; return; }
  bar.style.display = '';
  const parts = [];
  if (r.stale) parts.push(`資料可能已停止更新：最新資料日期 ${esc(r.latest)}，距今已 ${r.days} 個營業日（只排除週末，不含國定假日；若逢連假屬正常）。排程每個交易日約 16:30 與 20:00 (台灣時間) 自動更新，若連假後仍未更新請檢查 GitHub Actions。`);
  if (r.failed.length) parts.push(`${r.failed.length} 個來源擷取失敗或無資料：${r.failed.map(x => esc(x.label)).join('、')}。`);
  bar.innerHTML = '⚠️ ' + parts.join(' ') + ' <span style="text-decoration:underline;">點擊查看各來源狀態</span>';
}

function toggleFreshnessPanel() {
  const panel = document.getElementById('dataFreshnessPanel');
  if (panel) panel.style.display = panel.style.display === 'none' ? '' : 'none';
}

function renderFreshnessPanel() {
  let panel = document.getElementById('dataFreshnessPanel');
  const p = STATE && STATE.data_provenance;
  if (!p) return;
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'dataFreshnessPanel';
    panel.style.cssText = 'display:none; margin:8px 16px; padding:12px 14px; border:1px solid rgba(148,163,184,.3); border-radius:8px; background:rgba(15,23,42,.6); font-size:12px;';
    const header = document.querySelector('header');
    header.parentNode.insertBefore(panel, header.nextSibling);
  }
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const rows = (p.source_status || []).map(x => {
    const [label, color] = SOURCE_STATUS_LABEL[x.status] || [x.status, '#9aabc6'];
    return `<tr>
      <td style="padding:3px 10px 3px 0;">${esc(x.label)}</td>
      <td style="padding:3px 10px 3px 0; color:${color}; font-weight:600;">${esc(label)}</td>
      <td style="padding:3px 10px 3px 0;">${esc(x.data_date || '—')}</td>
      <td style="padding:3px 10px 3px 0; text-align:right;">${(x.record_count || 0).toLocaleString()}</td>
      <td style="padding:3px 0; color:var(--text-secondary);">${esc(x.message)}</td></tr>`;
  }).join('');
  const h = p.score_history || {};
  panel.innerHTML = `
    <div style="font-weight:700; margin-bottom:6px;">資料新鮮度（官方 OpenAPI 各來源最近一次擷取結果）</div>
    ${rows ? `<table style="border-collapse:collapse; width:100%;"><thead><tr style="color:var(--text-secondary); text-align:left;">
      <th>來源</th><th>狀態</th><th>資料日期</th><th style="text-align:right;">筆數</th><th>說明</th></tr></thead><tbody>${rows}</tbody></table>`
      : '<div style="color:var(--text-secondary);">尚無來源狀態紀錄（需執行一次排程或「同步資料」）。</div>'}
    <div style="margin-top:8px; color:var(--text-secondary);">
      「種子參考」區塊（${esc((p.seed_sections || []).join('、'))}）不隨排程更新。
      評分歷史快照：已累積 ${h.days || 0} 天${h.first ? `（${esc(h.first)} ~ ${esc(h.last)}）` : ''}，累積足夠後才能計算預警命中率。
    </div>`;
}

// 時間軸 6 大歷史節點真實數據快照 (用於時間軸播放器與熱度圖動態連動)
