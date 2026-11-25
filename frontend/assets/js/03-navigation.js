function scrollToSectionId(elId) {
  const el = document.getElementById(elId);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function updateQuickJumpBar(mode) {
  const bar = document.getElementById('globalQuickJumpBar');
  if (!bar) return;
  const pill = (label, target, cls = '') =>
    `<button class="quick-jump-pill ${cls}" onclick="scrollToSectionId('${target}')">${label}</button>`;
  const label = (t) => `<span class="quick-jump-label">${t}</span>`;
  if (mode === 'A') {
    bar.innerHTML = label('本頁導覽') +
      pill('10 秒結論', 'tenSecPulseGrid') +
      pill('資金流向全景圖', 'sankeyWrapperBox') +
      pill('19 大產業熱度地圖', 'industryHeatmapGrid') +
      `<button class="quick-jump-pill is-cta" onclick="setAppMode('ETF')">ETF 決策中心 ➔</button>`;
  } else if (mode === 'B') {
    bar.innerHTML = label('本頁導覽') +
      pill('八大資金池', 'eightVitalCardsGrid') +
      pill('產業趨勢排行榜', 'sixLeaderboardsGrid') +
      pill('市場趨勢故事', 'trendStoriesGrid') +
      pill('歷史輪動對照', 'timelineSnapshotPanel');
  } else if (mode === 'C') {
    bar.innerHTML = label('專業數據') +
      '<span style="color:var(--text-secondary);">使用下方 01～10 分頁，切換評分、個股檢索、預警、法人、回測與資料字典</span>';
  } else if (mode === 'ETF') {
    bar.innerHTML = label('本頁導覽') +
      pill('① 全球環境', 'etfSec1GlobalEnv') +
      pill('② 決策摘要', 'etfSec2DecisionSummary') +
      pill('③ ETF 清單', 'etfCardsGridContainer') +
      pill('④ 白話解讀', 'etfSec4AiPlainGrid') +
      pill('⑤ 圖表', 'etfChart1FlowsBox') +
      pill('重疊比較', 'etfChart6OverlapMatrixBox') +
      pill('我的投組', 'userPortfolioAnalysisOutput') +
      pill('🤖 AI 研究團隊', 'argonMultiAgentCenterSection', 'is-ai');
  }
}

function setAppMode(mode) {
  APP_MODE = mode;
  document.getElementById('btnModeA').className = 'mode-btn' + (mode === 'A' ? ' active-A' : '');
  document.getElementById('btnModeB').className = 'mode-btn' + (mode === 'B' ? ' active-B' : '');
  document.getElementById('btnModeC').className = 'mode-btn' + (mode === 'C' ? ' active-C' : '');
  const btnEtf = document.getElementById('btnModeETF');
  if (btnEtf) btnEtf.className = 'mode-btn' + (mode === 'ETF' ? ' active-ETF' : '');

  // 同步更新手機底部 App 導覽列高亮狀態
  const mobA = document.getElementById('mobBtnModeA');
  const mobB = document.getElementById('mobBtnModeB');
  const mobC = document.getElementById('mobBtnModeC');
  const mobE = document.getElementById('mobBtnModeETF');
  if (mobA) mobA.className = 'mob-nav-btn' + (mode === 'A' ? ' active-A' : '');
  if (mobB) mobB.className = 'mob-nav-btn' + (mode === 'B' ? ' active-B' : '');
  if (mobC) mobC.className = 'mob-nav-btn' + (mode === 'C' ? ' active-C' : '');
  if (mobE) mobE.className = 'mob-nav-btn' + (mode === 'ETF' ? ' active-ETF' : '');

  const layer1 = document.getElementById('layer1MapSection');
  const layer2 = document.getElementById('layer2AnalysisSection');
  const layer3 = document.getElementById('proResearchSection');
  const layerEtf = document.getElementById('etfDecisionCenterSection');

  if (mode === 'A') {
    layer1.style.display = 'block';
    layer2.style.display = 'none';
    layer3.style.display = 'none';
    if (layerEtf) layerEtf.style.display = 'none';
  } else if (mode === 'B') {
    layer1.style.display = 'none';
    layer2.style.display = 'block';
    layer3.style.display = 'none';
    if (layerEtf) layerEtf.style.display = 'none';
  } else if (mode === 'C') {
    layer1.style.display = 'none';
    layer2.style.display = 'none';
    layer3.style.display = 'block';
    if (layerEtf) layerEtf.style.display = 'none';
  } else if (mode === 'ETF') {
    layer1.style.display = 'none';
    layer2.style.display = 'none';
    layer3.style.display = 'none';
    if (layerEtf) layerEtf.style.display = 'block';
  }
  updateQuickJumpBar(mode);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function toggleReducedMotion() {
  REDUCED_MOTION = !REDUCED_MOTION;
  document.body.classList.toggle('reduced-motion', REDUCED_MOTION);
  document.getElementById('motionToggleBtn').textContent = REDUCED_MOTION ? '⏸ 動畫關' : '✨ 動畫';
}

function switchProTab(tabId, el) {
  document.querySelectorAll('.pro-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.pro-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(tabId).classList.add('active');
  el.classList.add('active');
}

function openDrawer(badgeHtml, title, subtitle, bodyHtml, targetProTabId = 'pro-rotation') {
  document.getElementById('drawerHeaderBadge').innerHTML = badgeHtml;
  document.getElementById('drawerTitle').textContent = title;
  document.getElementById('drawerSubtitle').textContent = subtitle;
  const drillButtonsHtml = `
    <div style="margin-top:16px; padding-top:12px; border-top:1px solid var(--border); display:flex; gap:8px; flex-wrap:wrap;">
      <button class="btn btn-sm" style="background:#0284c7; flex:1;" onclick="closeDrawer(); setAppMode('B');">
        🔍 進入第二層：完整研究分析與趨勢故事 ➔
      </button>
      <button class="btn btn-outline btn-sm" style="flex:1;" onclick="closeDrawer(); setAppMode('C'); jumpToProTab('${targetProTabId}');">
        🗄️ 下鑽第三層：查看原始數據表、1,989家檢索與回測 ➔
      </button>
    </div>
  `;
  document.getElementById('drawerBody').innerHTML = bodyHtml + drillButtonsHtml;
  document.getElementById('drawerBackdrop').classList.add('open');
  document.getElementById('drawerPanel').classList.add('open');
}

function jumpToProTab(tabId) {
  const tabs = document.querySelectorAll('.pro-tab');
  document.querySelectorAll('.pro-panel').forEach(p => p.classList.remove('active'));
  tabs.forEach(t => t.classList.remove('active'));
  const targetPanel = document.getElementById(tabId);
  if (targetPanel) targetPanel.classList.add('active');
  tabs.forEach(t => {
    if ((t.getAttribute('onclick') || '').includes(tabId)) t.classList.add('active');
  });
}

function closeDrawer() {
  document.getElementById('drawerBackdrop').classList.remove('open');
  document.getElementById('drawerPanel').classList.remove('open');
}

function buildSixQuestionsHtml(q1, q2, q3, q4, q5, q6, metaFooter) {
  return `
    <div style="margin-bottom:14px;"><span class="badge badge-grade-A">AI 白話六問解說（100% 基於系統真實數據）</span></div>
    <div class="q6-box"><div class="q6-title">1️⃣ 現在發生什麼事？</div><div style="font-size:15px; color:#f1f5f9;">${q1}</div></div>
    <div class="q6-box"><div class="q6-title">2️⃣ 為什麼會發生？</div><div style="font-size:15px; color:#f1f5f9;">${q2}</div></div>
    <div class="q6-box"><div class="q6-title">3️⃣ 這代表什麼意義？</div><div style="font-size:15px; color:#f1f5f9;">${q3}</div></div>
    <div class="q6-box"><div class="q6-title" style="color:#34d399;">4️⃣ 對哪些產業可能有利？</div><div style="font-size:15px; color:#f1f5f9;">${q4}</div></div>
    <div class="q6-box"><div class="q6-title" style="color:#fb7185;">5️⃣ 對哪些產業可能不利（反方風險）？</div><div style="font-size:15px; color:#f1f5f9;">${q5}</div></div>
    <div class="q6-box"><div class="q6-title" style="color:#fbbf24;">6️⃣ 接下來應該觀察什麼指標（失效條件）？</div><div style="font-size:15px; color:#f1f5f9;">${q6}</div></div>
    <div style="font-size:13.5px; color:var(--text-secondary); margin-top:14px; padding-top:10px; border-top:1px solid var(--border);">${metaFooter}</div>
  `;
}

// 單檔離線版 (Cloudflare / Render 首頁 / Release 下載) 會把資料快照內嵌在 id 為 twfin-snapshot 的 JSON script 標籤內；
// 拆分部署的 docs/index.html 沒有內嵌，資料改由 fetchSnapshotFile() 讀取同目錄的 data.json
function readEmbeddedSnapshot(doc) {
  const el = (doc || document).getElementById('twfin-snapshot');
  if (!el) return null;
  try { return JSON.parse(el.textContent); } catch (e) { return null; }
}

/* -------------------------------------------------------------------------
   資料載入策略 (針對 Render 免費方案閒置後的冷啟動，以及純靜態託管)：
   1. 有內嵌快照：立刻用快照畫出完整畫面，再於背景向 /api/dashboard 取得最新資料 (逾時與重試)
   2. 沒有內嵌快照 (本機開發版)：顯示「伺服器喚醒中」狀態並重試，不再留下空白頁
   3. 純靜態託管 (GitHub Pages / Cloudflare) 沒有 API：回應 404 等明確拒絕時不重試，直接標示為離線快照
   ------------------------------------------------------------------------- */
const API_RETRY_TIMEOUTS_MS = [8000, 25000, 45000];   // 第 2、3 次給喚醒中的伺服器更長的等待時間
let API_MODE = 'unknown';                              // unknown | live | snapshot | waking
let API_REASON = '';                                   // no-api (純靜態託管) | unreachable (連不上伺服器)

function bannerDismissed() {
  try { return sessionStorage.getItem('twfin_api_banner_dismissed') === '1'; } catch (e) { return false; }
}
function dismissApiBanner() {
  try { sessionStorage.setItem('twfin_api_banner_dismissed', '1'); } catch (e) {}
  setApiBanner(null);
}

function setApiBanner(kind, html, withRetry, dismissible) {
  let el = document.getElementById('apiStatusBanner');
  if (!kind) { if (el) el.style.display = 'none'; return; }
  if (!el) {
    el = document.createElement('div');
    el.id = 'apiStatusBanner';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.style.cssText = 'margin:8px 16px; padding:9px 14px; border-radius:8px; font-size:13px; display:flex; gap:10px; align-items:center; flex-wrap:wrap;';
    const header = document.querySelector('header');
    header.parentNode.insertBefore(el, header.nextSibling);
  }
  const palette = {
    waking: ['rgba(245,158,11,.12)', 'rgba(245,158,11,.4)', '#fbbf24'],
    snapshot: ['rgba(56,189,248,.1)', 'rgba(56,189,248,.35)', '#7dd3fc'],
    error: ['rgba(244,63,94,.12)', 'rgba(244,63,94,.4)', '#fda4af'],
  }[kind];
  el.style.background = palette[0];
  el.style.border = '1px solid ' + palette[1];
  el.style.color = palette[2];
  el.style.display = 'flex';
  el.innerHTML = `<span>${html}</span>`
    + (withRetry ? '<button class="btn btn-outline btn-sm" onclick="retryLoadDashboard()">重新連線</button>' : '')
    + (dismissible ? '<button class="btn btn-outline btn-sm" onclick="dismissApiBanner()" aria-label="關閉提示">✕</button>' : '');
}

// 只有「網路不通 / 逾時 / 伺服器 5xx」才值得重試；404、401 等代表此站台根本沒有 API (純靜態託管)
async function fetchDashboardOnce(timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch('/api/dashboard', { signal: ctrl.signal });
    if (res.status >= 500) return { retry: true };
    if (!res.ok) return { retry: false, noApi: true };
    const ct = res.headers.get('content-type') || '';
    if (!ct.includes('json')) return { retry: false, noApi: true };   // 靜態託管常把未知路徑導回 HTML
    return { data: await res.json() };
  } catch (e) {
    return { retry: true };
  } finally {
    clearTimeout(timer);
  }
}

async function fetchDashboardWithRetry(onWaiting) {
  for (let i = 0; i < API_RETRY_TIMEOUTS_MS.length; i++) {
    const r = await fetchDashboardOnce(API_RETRY_TIMEOUTS_MS[i]);
    if (r.data) { API_REASON = ''; return r.data; }
    if (!r.retry) { API_REASON = 'no-api'; return null; }
    if (onWaiting) onWaiting(i + 1);
  }
  API_REASON = 'unreachable';
  return null;
}

// 內容有實質變動才重畫，避免伺服器與快照內容相同時畫面閃動
function dashboardFingerprint(d) {
  if (!d) return '';
  const p = d.data_provenance || {};
  const m = d.active_model || {};
  return [m.version_id, JSON.stringify(m.weights), JSON.stringify(m.thresholds), p.last_live_ingestion,
    (d.warnings || []).length, (d.industries || []).map(i => i.total_weighted_score).join(',')].join('|');
}

async function refreshFromApi() {
  const embedded = STATE;
  setApiBanner('waking', '⏳ 正在連線伺服器取得最新資料…（免費主機閒置後首次喚醒約需 30～60 秒，目前先顯示內嵌的資料快照）', false);
  API_MODE = 'waking';
  const data = await fetchDashboardWithRetry(() =>
    setApiBanner('waking', '⏳ 伺服器仍在喚醒中，請稍候…（目前顯示的是內嵌的資料快照）', false));
  if (data) {
    API_MODE = 'live';
    const changed = dashboardFingerprint(data) !== dashboardFingerprint(embedded);
    STATE = data;
    if (changed) renderAll();
    setApiBanner(null);
  } else {
    API_MODE = 'snapshot';
    const when = (embedded && embedded.generated_at) || '未知';
    if (API_REASON === 'no-api') {
      // 純靜態託管 (GitHub Pages / Cloudflare) 本來就沒有 API，這是正常模式：低調提示，可關閉
      if (!bannerDismissed()) {
        setApiBanner('snapshot', `ℹ️ 雲端快照模式（資料時間：${when}），每個交易日台灣時間 16:30 與 20:00 自動更新。權重調整等需要伺服器的功能在此模式不可用。`, false, true);
      } else {
        setApiBanner(null);
      }
    } else {
      setApiBanner('error', `⚠️ 連不上伺服器，目前顯示離線快照（資料時間：${when}）。`, true);
    }
  }
}

function retryLoadDashboard() {
  if (STATE) refreshFromApi();
  else loadDashboard();
}

// 拆分部署：index.html 只有程式，資料快照放在同目錄的 data.json (單檔離線版則內嵌在頁面內)。
// 以 no-cache 向伺服器驗證：資料沒變時回 304 不必重新下載，有更新時一定拿到最新版。
async function fetchSnapshotFile() {
  try {
    const res = await fetch('data.json', { cache: 'no-cache' });
    if (!res.ok) return null;
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('html')) return null;      // 靜態託管常把不存在的路徑導回 HTML
    return await res.json();
  } catch (e) {
    return null;
  }
}

async function loadDashboard() {
  let embedded = readEmbeddedSnapshot();
  if (!embedded && location.protocol === 'file:') {
    // file:// 無法 fetch 旁邊的 data.json，也不可能有 API
    API_MODE = 'snapshot';
    setApiBanner('error', '❌ 以檔案方式開啟時，瀏覽器無法讀取旁邊的 data.json。請改用「單檔離線版」(twfin-standalone.html：可從 GitHub Release 下載，或執行 python backend/export_standalone.py --single twfin-standalone.html)，或透過網址 (http / https) 開啟。', false);
    return;
  }
  if (!embedded) {
    setApiBanner('waking', '⏳ 正在載入資料快照…', false);
    embedded = await fetchSnapshotFile();
    if (embedded) setApiBanner(null);
  }
  // 直接雙擊開啟 (file://) 時不可能有 API，直接使用內嵌快照
  if (embedded && location.protocol === 'file:') {
    API_MODE = 'snapshot';
    STATE = embedded;
    if (typeof loadMultiAgentLocalOverrides === 'function') loadMultiAgentLocalOverrides();
    renderAll();
    return;
  }
  if (embedded) {
    STATE = embedded;
    if (typeof loadMultiAgentLocalOverrides === 'function') loadMultiAgentLocalOverrides();
    renderAll();          // 第一個畫面不等網路
    refreshFromApi();     // 背景更新，不阻塞
    return;
  }
  // 本機開發版：沒有快照，只能等 API
  setApiBanner('waking', '⏳ 正在連線伺服器載入資料…（若為免費主機閒置後首次喚醒，約需 30～60 秒）', false);
  const data = await fetchDashboardWithRetry(() =>
    setApiBanner('waking', '⏳ 伺服器仍在喚醒中，請稍候…', false));
  if (!data) {
    API_MODE = 'snapshot';
    setApiBanner('error', '❌ 無法連線到伺服器，也沒有內嵌的資料快照可顯示。', true);
    return;
  }
  API_MODE = 'live';
  STATE = data;
  setApiBanner(null);
  if (typeof loadMultiAgentLocalOverrides === 'function') loadMultiAgentLocalOverrides();
  renderAll();
}

function renderAll() {
  if (!STATE) return;
  const m = STATE.active_model;
  const w = m.weights;
  renderDataProvenance();
  const modelBadge = document.getElementById('activeModelBadge');
  modelBadge.textContent = `模型 ${String(m.version_id).split(' ')[0]}`;
  modelBadge.title = `${m.version_id}\n權重：資金${Math.round(w.capital_flow*100)} / 基本面${Math.round(w.fundamentals*100)} / 成長${Math.round(w.future_growth*100)} / 法人${Math.round(w.institutional*100)} / 估值${Math.round(w.valuation*100)}`;
  document.getElementById('lastUpdatedText').textContent =
    `資料基準：${STATE.generated_at} ｜ 已串接 MOPS/TWSE/TPEx ${STATE.live_summary ? STATE.live_summary.total_companies : 1989} 家上市櫃真實數據`;

  document.getElementById('w_cap').value = Math.round(w.capital_flow * 100);
  document.getElementById('w_fun').value = Math.round(w.fundamentals * 100);
  document.getElementById('w_gro').value = Math.round(w.future_growth * 100);
  document.getElementById('w_ins').value = Math.round(w.institutional * 100);
  document.getElementById('w_val').value = Math.round(w.valuation * 100);

  // 渲染全新視覺化指揮中心組件
  renderTenSecPulse();
  renderEightVitalCards();
  renderSankeyDiagram(parseInt(document.getElementById('sankeyPeriodSelect').value || '4', 10));
  renderIndustryHeatmap();
  onTimelineSliderInput(document.getElementById('timelineRangeInput').value || 5);
  renderSixLeaderboards();
  renderTrendStories();

  // 渲染模式 B/C 專業研究底座組件
  renderMacroCards();
  renderAssetFlows();
  renderIndustryTable();
  renderWeightSensitivity();
  renderThresholdSensitivity();
  renderInstiFlows();
  renderWarnings();
  renderCompanies();
  renderScenarios();
  renderReports();
  renderBacktest();
  renderGovernance();
  renderEtfDecisionCenter();
  updateQuickJumpBar(APP_MODE);

  if (APP_MODE === 'A') {
    document.getElementById('proResearchSection').style.display = 'none';
  }
}

