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
    { id: "IND_CONSTRUCTION", displayTitle: "17. 營建、塑化與鋼鐵原物料", icon: "🏗️", subOverride: "營建(興富發 2542)、塑化鋼鐵(台塑/中鋼)" }
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

function renderIndustryHeatmap(overrideMap = {}, hist = null) {
  const sectors = getExpanded17Sectors(overrideMap);
  window.__HEATMAP_SECTORS__ = sectors;
  const grid = document.getElementById('industryHeatmapGrid');
  const ym = String(((STATE.live_top_companies || [])[0] || {}).data_ym || '');
  const monthLabel = /^\d{4,}$/.test(ym) ? `${parseInt(ym.slice(0, -2), 10) + 1911}年${parseInt(ym.slice(-2), 10)}月` : '最新月';
  window.__HEATMAP_MONTH__ = monthLabel;

  // 說明目前顯示的分數來源 (即時重算 / 種子)；時間軸前 5 格是手寫歷史情境，另外標示
  const liveInds = (STATE.industries || []).filter(i => i.score_source === 'live');
  let note = document.getElementById('heatmapSourceNote');
  if (!note) {
    note = document.createElement('div');
    note.id = 'heatmapSourceNote';
    note.style.cssText = 'font-size:12.5px; margin:8px 2px 10px; color:var(--text-muted);';
    grid.parentNode.insertBefore(note, grid);
  }
  const latestSel = !hist;
  if (!latestSel) {
    const srcTxt = hist.source === 'live' ? '由官方資料即時重算的分數' : '即時評分上線前的舊模型分數 (子分數是內建種子值，與現在的分數尺度不同)';
    note.textContent = `🕰️ 目前顯示的是 ${hist.date} 收盤後當時記下的真實快照（${srcTxt}）。快照只保存分數與等級，所以不顯示營收與相對強弱。拖到最右側「最新」可回到目前的即時分數。`;
  } else if (liveInds.length) {
    const asOf = (liveInds[0].as_of_date || '').slice(0, 10);
    note.textContent = `✅ 分數由官方即時資料重算（${asOf} 盤後；${liveInds.length} 個產業，每個交易日收盤後更新）。方塊顏色為資金流向狀態，分數為啟用模型的綜合總分。`;
  } else {
    note.textContent = '⚠️ 此快照的分數為內建種子值，尚未啟用即時評分，不會隨資料更新。';
  }

  grid.innerHTML = sectors.map((sec, idx) => {
    const hInfo = stateToHeatClass(sec.effectiveState);
    const hs = hist ? (hist.scores || {})[sec.industry_id] : null;
    const isUnratable = hist ? (!hs || hs.score == null) : (sec.total_weighted_score == null || sec.rotation_state === 'INSUFFICIENT_DATA');
    // 歷史格顯示「當時記下」的分數與等級，絕不配上現在的即時分數
    const scoreDisplay = hist ? (isUnratable ? '觀察中' : `${Number(hs.score).toFixed(1)} 分`) : (isUnratable ? '觀察中' : `${sec.total_weighted_score.toFixed(1)} 分`);
    const agg = sec.live_agg || {};
    const compNames = sec.focusTicker || (sec.representative_companies || []).slice(0, 2).map(c => `${c.ticker} ${c.name}`).join('、');

    const lm = sec.live_metrics || null;
    const isLive = !!lm;      // 有即時指標就用 (未評分的產業仍有即時營收與相對強弱，不可顯示手寫的舊數字)
    const sgn = (v) => (v === null || v === undefined || Number.isNaN(v)) ? 'N/A' : (v >= 0 ? '+' : '') + v + '%';
    const cls = (v) => (v === null || v === undefined || v >= 0) ? 'pos' : 'neg';
    const yoyVal = isLive ? (lm.yoy === null ? null : Math.round(lm.yoy * 10) / 10) : sec.rev_yoy_pct;
    // 第二個指標：即時評分時顯示「近 N 日相對大盤」(類股報酬指數)；種子分數時維持原本的 20 日相對強弱
    const rsVal = isLive ? lm.rs_pct : sec.rel_strength_20d;
    const rsLabel = isLive ? `近 ${lm.rs_days || '?'} 日相對大盤` : '20 日相對強弱';
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
          ${hist ? `<div class="ht-metrics"><div><div class="ht-m-label">快照日 ${esc(hist.date.slice(5))} 預警等級</div><div class="ht-m-val">${esc((hs && hs.level) || '—')}</div></div></div>
          <div class="ht-comp" style="margin-top:8px;" title="${compNames}">${compNames}</div>` : `<div class="ht-metrics">
            <div><div class="ht-m-label">${monthLabel} 營收 YoY</div><div class="ht-m-val ${cls(yoyVal)}">${sgn(yoyVal)}</div></div>
            <div><div class="ht-m-label">${rsLabel}</div><div class="ht-m-val ${cls(rsVal)}">${sgn(rsVal)}</div></div>
          </div>
          <div class="ht-comp" style="margin-top:8px;" title="${compNames}">${compNames}</div>`}
        </div>
      </div>
    `;
  }).join('');
}

function openIndustryDrawer(idx) {
  const sec = window.__HEATMAP_SECTORS__[idx];
  if (!sec) return;
  const hInfo = stateToHeatClass(sec.effectiveState);
  const isUnratable = sec.total_weighted_score == null || sec.rotation_state === 'INSUFFICIENT_DATA';
  const agg = sec.live_agg || {};
  const comps = (sec.representative_companies || []).map(c =>
    `<span class="badge badge-grade-B" style="margin:3px 4px 0 0;">${c.ticker} ${c.name}（${c.role}）</span>`
  ).join('');

  const lmX = sec.live_metrics || null;
  const isLiveX = sec.score_source === 'live' && lmX;
  const fmtN = (v, d = 1) => (v === null || v === undefined) ? 'N/A' : (v >= 0 ? '+' : '') + v.toFixed(d);
  const rsText = isLiveX
    ? `近 ${lmX.rs_days || '?'} 日相對大盤 ${fmtN(lmX.rs_pct, 2)}%（類股報酬指數 − 加權報酬指數）`
    : `20日相對大盤表現 ${sec.rel_strength_20d >= 0 ? '+' : ''}${sec.rel_strength_20d}%，60日相對大盤 ${sec.rel_strength_60d >= 0 ? '+' : ''}${sec.rel_strength_60d}%`;
  const q1 = `${sec.title} 目前處於「<strong>${hInfo.label}</strong>」，景氣循環位置為「<strong>${sec.cycle_stage}</strong>」（人工標註，不隨資料更新），轉折訊號為「<strong>${sec.transition_tag}</strong>」。${rsText}。`;
  const q2 = sec.supporting_evidence;
  const q3 = isUnratable
    ? `此分類涵蓋次產業商業模式差異過大（缺失與不可比資料比例達 ${sec.missing_data_pct}%），本系統嚴格遵守「資料不足不得硬排名」原則，僅列示個別公司營收供觀察。`
    : (isLiveX
      ? `綜合研究總分為 <strong>${sec.total_weighted_score} 分</strong>（資金流向 ${sec.score_capital_flow}／基本面 ${sec.score_fundamentals}／成長動能 ${sec.score_future_growth}／法人布局 ${sec.score_institutional}／估值 ${sec.score_valuation}，皆為相對其他產業的百分位分數）。法人動向：${sec.foreign_net_flow_trend}；${sec.itc_net_flow_trend}。`
      : `綜合研究總分為 <strong>${sec.total_weighted_score} 分</strong>（短期資金動能 ${sec.short_term_momentum_score} 分／中期基本面 ${sec.mid_term_fundamental_score} 分／長期結構成長 ${sec.long_term_structural_score} 分）。法人動向：${sec.itc_net_flow_trend}；${sec.foreign_net_flow_trend}。`);
  const q4 = `供應鏈受惠核心與代表公司：<div style="margin-top:4px;">${comps}</div>`;
  const q5 = `<strong>反方證據與潛在風險：</strong>${sec.counter_evidence}`;
  const q6 = `<strong>結論失效條件：</strong>${sec.invalidation_conditions}<br/><strong>資料統計限制：</strong>${sec.data_limitations}`;

  const liveBox = agg.company_count ? `
    <div class="q6-box" style="border-color:var(--accent-emerald); background:rgba(6,78,59,0.25);">
      <div class="q6-title" style="color:#34d399;">📊 MOPS 公開資訊觀測站全市場 ${agg.company_count} 家上市櫃公司真實匯總</div>
      <div style="font-size:13px; color:#fff;">
        • ${window.__HEATMAP_MONTH__ || '最新月'} 產業合計總營收：<strong>${agg.ind_rev_billion.toLocaleString()} 億元</strong>（去年同月 ${agg.ind_ly_rev_billion.toLocaleString()} 億元，實測匯總年增率 <strong class="${agg.agg_yoy_pct >= 0 ? 'pos' : 'neg'}">${agg.agg_yoy_pct >= 0 ? '+' : ''}${agg.agg_yoy_pct}%</strong>）<br/>
        • 產業平均本益比 (P/E)：<strong>${agg.avg_pe || 'N/A'} 倍</strong> ｜ 平均股價淨值比 (P/B)：<strong>${agg.avg_pb || 'N/A'} 倍</strong><br/>
        • ${(sec.as_of_date || '').slice(0, 10) || '最新交易日'} 法人買賣超：外資 <strong>${(agg.sum_foreign_shares || 0).toLocaleString()} 股</strong> ｜ 投信 <strong>${(agg.sum_itc_shares || 0).toLocaleString()} 股</strong>${isLiveX ? `（約 ${fmtN(lmX.foreign_billion)} / ${fmtN(lmX.itc_billion)} 億元；占產業成交值 ${lmX.inst_ratio_pct === null ? 'N/A' : fmtN(lmX.inst_ratio_pct, 2) + '%'}；收盤價覆蓋率 ${Math.round(lmX.price_coverage * 100)}%）` : ''}
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
// 時間軸資料：每一格是 industry_score_history 裡的一個「真實快照日」(後端 live_timeline.py 產生，STATE.timeline_history)。
// 文字由資料機械式產生；最右側「最新」再疊上首頁摘要產生的即時法人文字。沒有任何快照時才退回手寫的「最新」並標示。
// 原本 5 格手寫的歷史情境 (TIMELINE_SNAPSHOTS 前 5 筆) 移到時間軸下方折疊的「手寫歷史情境回顧」。
function timelinePoints() {
  const th = STATE && STATE.timeline_history;
  return (th && th.available && th.points) ? th.points : [];
}

function pointToSnapshot(pt, isLast) {
  const fmt = (arr, f) => (arr && arr.length) ? arr.map(f).join('、') : '無';
  const srcTxt = pt.source === 'live' ? '即時評分' : '舊模型種子分數';
  const heat = {};
  Object.keys(pt.scores || {}).forEach(id => { const st = pt.scores[id].state; if (st) heat[id] = st; });
  const lv = pt.levels || {};
  const lvTxt = Object.keys(lv).sort().map(k => `${k}：${lv[k]}`).join('、') || '無';
  const snap = {
    label: `${pt.date} 盤後（${srcTxt}）`,
    flowSummary: `當日 ${pt.scored} / ${pt.total} 個產業有評分，平均 ${pt.avg == null ? '—' : pt.avg} 分。預警等級分布：${lvTxt}。`,
    hotIndustries: fmt(pt.hot, h => `${h.name}（${h.score}）`),
    coldIndustries: fmt(pt.cold, h => `${h.name}（${h.score}）`),
    rotationOrder: pt.has_prev
      ? `與前一個快照日相比，分數升幅最大：${fmt(pt.movers_up, m => `${m.name}（+${m.delta}）`)} ｜ 降幅最大：${fmt(pt.movers_down, m => `${m.name}（${m.delta}）`)}`
      : '這是第一個快照日，沒有前一期可比較',
    keyEvent: pt.source === 'live' ? '分數由官方資料每日重算；此處不附任何人工撰寫的事件說明。' : '此格的 5 項子分數是內建種子值 (營收與法人輸入是官方資料)，與之後的即時評分尺度不同。',
    heatOverrides: heat,
    hist: { date: pt.date, source: pt.source, scores: pt.scores },
  };
  const live = STATE && STATE.home_pulse && STATE.home_pulse.timeline_latest;
  if (isLast && live && pt.source === 'live') {
    // 最新一格：疊上首頁摘要由即時資料產生的法人買賣超文字，並回到「即時分數」畫面 (不是歷史快照)
    return { ...snap, flowSummary: live.flowSummary, rotationOrder: live.rotationOrder, keyEvent: live.keyEvent, label: live.label, hist: null };
  }
  return isLast && pt.source === 'live' ? { ...snap, hist: null } : snap;
}

function getTimelineSnapshot(idx) {
  const pts = timelinePoints();
  if (pts.length) {
    const i = Math.max(0, Math.min(pts.length - 1, idx));
    return pointToSnapshot(pts[i], i === pts.length - 1);
  }
  // 沒有快照時：只剩手寫的「最新」，明確標示
  const base = TIMELINE_SNAPSHOTS[5];
  const live = STATE && STATE.home_pulse && STATE.home_pulse.timeline_latest;
  if (live) return { ...base, ...live, heatOverrides: {}, hist: null };
  return { ...base, label: `【手寫・未更新】${base.label}`, heatOverrides: {}, hist: null };
}

// 依快照數量設定滑桿範圍與下方日期刻度；也在折疊區列出手寫的歷史情境回顧
function initTimeline() {
  const pts = timelinePoints();
  const n = Math.max(1, pts.length);
  const slider = document.getElementById('timelineRangeInput');
  if (slider) { slider.min = 0; slider.max = n - 1; slider.value = n - 1; }
  const steps = document.getElementById('timelineSteps');
  if (steps) {
    const pick = n <= 6 ? pts.map((_, i) => i) : [0, Math.round((n - 1) / 3), Math.round(2 * (n - 1) / 3), n - 1];
    steps.innerHTML = pts.length
      ? pick.map(i => `<span${i === n - 1 ? ' id="timelineLatestStep" style="color:var(--accent-emerald); font-weight:700;"' : ''}>${esc(pts[i].date.slice(5))}<br/>${i === n - 1 ? '最新' : (pts[i].source === 'live' ? '即時評分' : '舊模型')}</span>`).join('')
      : '<span id="timelineLatestStep" style="color:var(--accent-emerald); font-weight:700;">最新<br/>即時評分</span>';
  }
  const hw = document.getElementById('timelineHandwritten');
  if (hw && typeof TIMELINE_SNAPSHOTS !== 'undefined') {
    hw.innerHTML = `<summary style="cursor:pointer; font-weight:600; color:var(--text-secondary);">📁 手寫的歷史情境回顧（2024～2026 年 5 個時期；寫死的文字，沒有對應的歷史資料可重算，僅供參考）</summary>` +
      TIMELINE_SNAPSHOTS.slice(0, 5).map(t => `<div class="evidence-box" style="margin:8px 0;"><strong>${esc(t.label)}</strong><br/>${esc(t.flowSummary)}<br/><span style="color:#94a3b8;">熱門：${esc(t.hotIndustries)} ｜ 降溫：${esc(t.coldIndustries)}</span></div>`).join('');
  }
}

function onTimelineSliderInput(val) {
  const idx = parseInt(val, 10);
  const snap = getTimelineSnapshot(idx);
  document.getElementById('timelineRangeInput').value = idx;

  // 同步更新上方 19宮格產業熱度地圖顏色！
  renderIndustryHeatmap(snap.hist ? (snap.heatOverrides || {}) : {}, snap.hist || null);

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

function timelineLastIndex() { return Math.max(0, timelinePoints().length - 1); }

function stepTimeline(delta) {
  const slider = document.getElementById('timelineRangeInput');
  let v = parseInt(slider.value, 10) + delta;
  if (v < 0) v = 0;
  if (v > timelineLastIndex()) v = timelineLastIndex();
  onTimelineSliderInput(v);
}

function jumpTimelineWindow(win) {
  const last = timelineLastIndex();
  const map = { FIRST: 0, BACK5: Math.max(0, last - 5), BACK20: Math.max(0, last - 20), LATEST: last };
  onTimelineSliderInput(map[win] ?? last);
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
    if (idx > timelineLastIndex()) {
      clearInterval(TIMELINE_TIMER);
      TIMELINE_TIMER = null;
      btn.textContent = '▶ 重新播放';
      return;
    }
    onTimelineSliderInput(idx);
  }, 2000);
}

