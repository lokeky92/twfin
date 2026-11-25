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

// 匯出的靜態版 (docs/index.html) 會把資料快照嵌在 <script id="twfin-snapshot" type="application/json">
function readEmbeddedSnapshot(doc) {
  const el = (doc || document).getElementById('twfin-snapshot');
  if (!el) return null;
  try { return JSON.parse(el.textContent); } catch (e) { return null; }
}

async function loadDashboard() {
  // 直接雙擊開啟 (file://) 時不可能有 API，直接使用內嵌快照
  const embedded = readEmbeddedSnapshot();
  if (embedded && location.protocol === 'file:') {
    STATE = embedded;
  } else {
    try {
      const res = await fetch('/api/dashboard');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      STATE = await res.json();
    } catch (e) {
      STATE = embedded;
    }
  }
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

