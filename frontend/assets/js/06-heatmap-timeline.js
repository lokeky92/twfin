/* =========================================================================
   4. 渲染 17宮格五色產業資金熱度地圖 (17-Sector Interactive Heatmap)
   ========================================================================= */
function getExpanded17Sectors(overrideMap = {}) {
  // 由 SQLite 14大產業展開為指令第三節要求之完整 17 大產業方塊（共用真實資料庫評分與 MOPS 匯總）
  const baseMap = {};
  (STATE.industries || []).forEach(ind => { baseMap[ind.industry_id] = ind; });

  const specs = [
    { id: "IND_SEMI_FOUNDRY", displayTitle: "01. 半導體(晶圓代工/封裝)", icon: "🔬" },
    { id: "IND_AI_SERVER", displayTitle: "02. AI伺服器与整機櫃", icon: "🖥️" },
    { id: "IND_THERMAL", displayTitle: "03. 水冷散熱與機構件", icon: "❄️" },
    { id: "IND_SEMI_EQUIP", displayTitle: "04. 半導體設備與測試介面", icon: "⚙️" },
    { id: "IND_FIN_HOLDING", displayTitle: "05. 金融(金控/銀行/保險)", icon: "🏦" },
    { id: "IND_CPO_NET", displayTitle: "06. CPO矽光子與高階網通", icon: "🌐" },
    { id: "IND_POWER_GREEN", displayTitle: "07. 電力設備與重電", icon: "⚡" },
    { id: "IND_IC_DESIGN", displayTitle: "08. IC設計與IP矽智財", icon: "🧠" },
    { id: "IND_SHIPPING", displayTitle: "09. 航運與航空物流", icon: "🚢" },
    { id: "IND_PCB_ABF", displayTitle: "10. PCB與高階CCL/ABF載板", icon: "🟩" },
    { id: "IND_AI_SERVER", displayTitle: "11. 電子零組件與連接線束", icon: "🔌", subOverride: "AI高速AEC線束(貿聯-KY 3665)、高階電源(台達電 2308)" },
    { id: "IND_POWER_GREEN", displayTitle: "12. 綠能、儲能與環保工程", icon: "🌱", subOverride: "太陽能、儲能電網與碳捕捉工程" },
    { id: "IND_MACH_AUTO", displayTitle: "13. 機械、工具機與車用零件", icon: "🤖" },
    { id: "IND_BIO_RETAIL", displayTitle: "14. 生技醫療與新藥研發", icon: "🧬", subOverride: "新藥(藥華藥 6446)、CDMO與高階醫材（次產業異質觀察）" },
    { id: "IND_BIO_RETAIL", displayTitle: "15. 觀光與連鎖餐飲", icon: "🍽️", subOverride: "連鎖餐飲(王品 2727)、飯店旅宿（外食CPI +3.01%轉嫁觀察）" },
    { id: "IND_BIO_RETAIL", displayTitle: "16. 零售百貨與電信防禦", icon: "🛍️", subOverride: "電信防禦龍頭(中華電 2412)、超商百貨內需服務" },
    { id: "IND_CONSTRUCTION", displayTitle: "17. 營建、塑化與鋼鐵原物料", icon: "🏗️", subOverride: "營建(興富發 2542, 47.1分) / 塑化鋼鐵(台塑/中鋼, 43.0分)" }
  ];

  // 若想要把鋼鐵與塑化獨立顯示也可直接對應
  const custom17 = [
    { id: "IND_SEMI_FOUNDRY", title: "半導體(晶圓代工/封裝)", icon: "🔬" },
    { id: "IND_AI_SERVER", title: "AI伺服器與整機櫃", icon: "🖥️" },
    { id: "IND_THERMAL", title: "水冷散熱與機構件", icon: "❄️" },
    { id: "IND_SEMI_EQUIP", title: "半導體設備與測試", icon: "⚙️" },
    { id: "IND_FIN_HOLDING", title: "金融(金控/銀行/保險)", icon: "🏦" },
    { id: "IND_CPO_NET", title: "CPO光通訊與高階網通", icon: "🌐" },
    { id: "IND_POWER_GREEN", title: "電力設備與重電外銷", icon: "⚡" },
    { id: "IND_IC_DESIGN", title: "IC設計與AI ASIC", icon: "🧠" },
    { id: "IND_SHIPPING", title: "航運與航空", icon: "🚢" },
    { id: "IND_PCB_ABF", title: "PCB與銅箔基板(CCL)", icon: "🟩" },
    { id: "IND_AI_SERVER", title: "電子零組件與連接線", icon: "🔌", focusTicker: "3665 貿聯-KY / 2308 台達電" },
    { id: "IND_POWER_GREEN", title: "綠能與儲能系統", icon: "🌱", focusTicker: "太陽能/儲能與強韌電網" },
    { id: "IND_MACH_AUTO", title: "機械、機器人與車用", icon: "🤖" },
    { id: "IND_BIO_RETAIL", title: "生技醫療", icon: "🧬", subNote: "新藥/醫材(異質不硬排名)" },
    { id: "IND_BIO_RETAIL", title: "觀光與連鎖餐飲", icon: "🍽️", subNote: "內需餐飲(異質不硬排名)" },
    { id: "IND_BIO_RETAIL", title: "零售與電信服務", icon: "📡", subNote: "中華電防禦(異質不硬排名)" },
    { id: "IND_CONSTRUCTION", title: "營建不動產", icon: "🏗️" },
    { id: "IND_STEEL_PLASTIC", title: "鋼鐵與大宗金屬", icon: "🔩", focusTicker: "2002 中鋼" },
    { id: "IND_STEEL_PLASTIC", title: "塑化與傳統化工", icon: "🛢️", focusTicker: "1301 台塑 / 1303 南亞" }
  ];

  return custom17.map((item, idx) => {
    const base = baseMap[item.id] || {};
    const st = overrideMap[item.id] || base.rotation_state || 'C';
    return { ...base, ...item, effectiveState: st, tileIndex: idx };
  });
}

function stateToHeatClass(st) {
  if (st === 'A') return { cls: 'heat-deep-green', label: '深綠｜資金明顯流入 (A)' };
  if (st === 'B') return { cls: 'heat-light-green', label: '淺綠｜資金持續增加 (B)' };
  if (st === 'D') return { cls: 'heat-orange', label: '橘色｜資金逐漸流出 (D)' };
  if (st === 'E') return { cls: 'heat-red', label: '紅色｜資金明顯撤退 (E)' };
  return { cls: 'heat-gray', label: '灰色｜資金觀望/分化 (C)' };
}

function renderIndustryHeatmap(overrideMap = {}) {
  const sectors = getExpanded17Sectors(overrideMap);
  window.__HEATMAP_SECTORS__ = sectors;
  const grid = document.getElementById('industryHeatmapGrid');

  grid.innerHTML = sectors.map((sec, idx) => {
    const hInfo = stateToHeatClass(sec.effectiveState);
    const isUnratable = sec.total_weighted_score === null || sec.rotation_state === 'INSUFFICIENT_DATA';
    const scoreDisplay = isUnratable ? '觀察中' : `${sec.total_weighted_score.toFixed(1)} 分`;
    const agg = sec.live_agg || {};
    const compNames = sec.focusTicker || (sec.representative_companies || []).slice(0, 2).map(c => `${c.ticker} ${c.name}`).join('、');

    const sgn = (v) => (v >= 0 ? '+' : '') + v + '%';
    return `
      <div class="heat-tile ${hInfo.cls}" onclick="openIndustryDrawer(${idx})">
        <div>
          <div class="ht-head">
            <span class="ht-icon">${sec.icon}</span>
            <span class="ht-score ${isUnratable ? 'is-na' : ''}">${scoreDisplay}</span>
          </div>
          <div class="ht-title">${sec.title}</div>
          <div class="ht-state">${hInfo.label}</div>
        </div>
        <div>
          <div class="ht-metrics">
            <div><div class="ht-m-label">10 月營收 YoY</div><div class="ht-m-val ${sec.rev_yoy_pct >= 0 ? 'pos' : 'neg'}">${sgn(sec.rev_yoy_pct)}</div></div>
            <div><div class="ht-m-label">20 日相對強弱</div><div class="ht-m-val ${sec.rel_strength_20d >= 0 ? 'pos' : 'neg'}">${sgn(sec.rel_strength_20d)}</div></div>
          </div>
          <div class="ht-comp" style="margin-top:8px;" title="${compNames}">${compNames}</div>
        </div>
      </div>
    `;
  }).join('');
}

function openIndustryDrawer(idx) {
  const sec = window.__HEATMAP_SECTORS__[idx];
  if (!sec) return;
  const hInfo = stateToHeatClass(sec.effectiveState);
  const isUnratable = sec.total_weighted_score === null || sec.rotation_state === 'INSUFFICIENT_DATA';
  const agg = sec.live_agg || {};
  const comps = (sec.representative_companies || []).map(c =>
    `<span class="badge badge-grade-B" style="margin:3px 4px 0 0;">${c.ticker} ${c.name}（${c.role}）</span>`
  ).join('');

  const q1 = `${sec.title} 目前處於「<strong>${hInfo.label}</strong>」，景氣循環位置為「<strong>${sec.cycle_stage}</strong>」，轉折訊號為「<strong>${sec.transition_tag}</strong>」。20日相對大盤表現 ${sec.rel_strength_20d >= 0 ? '+' : ''}${sec.rel_strength_20d}%，60日相對大盤 ${sec.rel_strength_60d >= 0 ? '+' : ''}${sec.rel_strength_60d}%。`;
  const q2 = sec.supporting_evidence;
  const q3 = isUnratable
    ? `此分類涵蓋次產業商業模式差異過大（缺失與不可比資料比例達 ${sec.missing_data_pct}%），本系統嚴格遵守「資料不足不得硬排名」原則，僅列示個別公司營收供觀察。`
    : `綜合研究總分為 <strong>${sec.total_weighted_score} 分</strong>（短期資金動能 ${sec.short_term_momentum_score} 分／中期基本面 ${sec.mid_term_fundamental_score} 分／長期結構成長 ${sec.long_term_structural_score} 分）。法人動向：${sec.itc_net_flow_trend}；${sec.foreign_net_flow_trend}。`;
  const q4 = `供應鏈受惠核心與代表公司：<div style="margin-top:4px;">${comps}</div>`;
  const q5 = `<strong>反方證據與潛在風險：</strong>${sec.counter_evidence}`;
  const q6 = `<strong>結論失效條件：</strong>${sec.invalidation_conditions}<br/><strong>資料統計限制：</strong>${sec.data_limitations}`;

  const liveBox = agg.company_count ? `
    <div class="q6-box" style="border-color:var(--accent-emerald); background:rgba(6,78,59,0.25);">
      <div class="q6-title" style="color:#34d399;">📊 MOPS 公開資訊觀測站全市場 ${agg.company_count} 家上市櫃公司真實匯總</div>
      <div style="font-size:13px; color:#fff;">
        • 115年10月(2026-10) 產業合計總營收：<strong>${agg.ind_rev_billion.toLocaleString()} 億元</strong>（去年同月 ${agg.ind_ly_rev_billion.toLocaleString()} 億元，實測匯總年增率 <strong class="${agg.agg_yoy_pct >= 0 ? 'pos' : 'neg'}">${agg.agg_yoy_pct >= 0 ? '+' : ''}${agg.agg_yoy_pct}%</strong>）<br/>
        • 產業平均本益比 (P/E)：<strong>${agg.avg_pe || 'N/A'} 倍</strong> ｜ 平均股價淨值比 (P/B)：<strong>${agg.avg_pb || 'N/A'} 倍</strong><br/>
        • 最新交易日(11/20) 法人合計買賣超：外資 <strong>${(agg.sum_foreign_shares || 0).toLocaleString()} 股</strong> ｜ 投信 <strong>${(agg.sum_itc_shares || 0).toLocaleString()} 股</strong>
      </div>
    </div>
  ` : '';

  const bodyHtml = liveBox + buildSixQuestionsHtml(q1, q2, q3, q4, q5, q6,
    `資料截止日期：${sec.as_of_date} ｜ 涵蓋期間：${sec.period_covered} ｜ 模型版本：${sec.model_version}`);
  openDrawer(`<span class="badge badge-lvl4">${hInfo.label}</span>`, `${sec.icon} ${sec.title}`, `次產業範圍：${sec.sub_sectors}`, bodyHtml);
}

/* =========================================================================
   5. 資金輪動動畫時間軸播放器 (Timeline Player)
   ========================================================================= */
function onTimelineSliderInput(val) {
  const idx = parseInt(val, 10);
  const snap = TIMELINE_SNAPSHOTS[idx] || TIMELINE_SNAPSHOTS[5];
  document.getElementById('timelineRangeInput').value = idx;

  // 同步更新上方 19宮格產業熱度地圖顏色！
  renderIndustryHeatmap(snap.heatOverrides || {});

  const lblEl = document.getElementById('timelineCurrentLabel');
  if (lblEl) lblEl.textContent = `當前顯示時期：${snap.label}`;
  const compactEl = document.getElementById('timelineCompactBar');
  if (compactEl) {
    compactEl.innerHTML = `
      <strong>🕒 ${snap.label}</strong> ｜ <span style="color:#34d399;">🔥 資金湧入：${snap.hotIndustries}</span> ｜ <span style="color:#fb7185;">🧊 資金撤退：${snap.coldIndustries}</span><br/>
      <span style="color:#94a3b8;">🔄 輪動路徑：${snap.rotationOrder} ｜ 📌 關鍵事件：${snap.keyEvent}</span>
    `;
  }

  document.getElementById('timelineSnapshotPanel').innerHTML = `
    <div class="card" style="background:#0f172a; border-left:3px solid var(--accent-blue);">
      <div style="font-size:11.5px; color:var(--accent-blue); font-weight:700;">當時點資金主要流向</div>
      <div style="font-size:13.5px; font-weight:800; color:#fff; margin:4px 0;">${snap.label}</div>
      <div style="font-size:12.5px; color:#cbd5e1;">${snap.flowSummary}</div>
    </div>
    <div class="card" style="background:#0f172a; border-left:3px solid var(--accent-emerald);">
      <div style="font-size:11.5px; color:var(--accent-emerald); font-weight:700;">🔥 當時最熱門 / 資金湧入產業</div>
      <div style="font-size:13.5px; font-weight:800; color:#34d399; margin:6px 0;">${snap.hotIndustries}</div>
      <div style="font-size:12px; color:#94a3b8;"><strong>輪動順序：</strong>${snap.rotationOrder}</div>
    </div>
    <div class="card" style="background:#0f172a; border-left:3px solid var(--accent-red);">
      <div style="font-size:11.5px; color:var(--accent-red); font-weight:700;">🧊 當時資金撤退 / 降溫產業</div>
      <div style="font-size:13.5px; font-weight:800; color:#fb7185; margin:6px 0;">${snap.coldIndustries}</div>
      <div style="font-size:12px; color:#94a3b8;">上方 17 宮格熱度地圖已同步切換為該時期顏色狀態</div>
    </div>
    <div class="card" style="background:#0f172a; border-left:3px solid var(--accent-orange);">
      <div style="font-size:11.5px; color:var(--accent-orange); font-weight:700;">📌 當時重要經濟與預警事件</div>
      <div style="font-size:12.5px; color:#fde68a; margin-top:6px;">${snap.keyEvent}</div>
    </div>
  `;
}

function stepTimeline(delta) {
  const slider = document.getElementById('timelineRangeInput');
  let v = parseInt(slider.value, 10) + delta;
  if (v < 0) v = 0;
  if (v > 5) v = 5;
  onTimelineSliderInput(v);
}

function jumpTimelineWindow(win) {
  const map = { '3Y': 0, '1Y': 2, '6M': 3, '3M': 4, '1M': 5 };
  onTimelineSliderInput(map[win] ?? 5);
}

function toggleTimelinePlay() {
  const btn = document.getElementById('timelinePlayBtn');
  if (TIMELINE_TIMER) {
    clearInterval(TIMELINE_TIMER);
    TIMELINE_TIMER = null;
    btn.textContent = '▶ 播放輪動歷史';
    return;
  }
  btn.textContent = '⏸ 暫停';
  let idx = 0;
  onTimelineSliderInput(idx);
  TIMELINE_TIMER = setInterval(() => {
    idx++;
    if (idx > 5) {
      clearInterval(TIMELINE_TIMER);
      TIMELINE_TIMER = null;
      btn.textContent = '▶ 重新播放';
      return;
    }
    onTimelineSliderInput(idx);
  }, 2000);
}

