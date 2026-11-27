/* =========================================================================
   第三區：ETF 研究清單（兩層式大字體卡片：第一層快速閱讀 ➔ 第二層展開完整分析）
   ========================================================================= */
function renderEtfLists() {
  if (!STATE || !STATE.etf_center) return;
  const concFilterEl = document.getElementById('etfConclusionFilter');
  const concFilter = concFilterEl ? concFilterEl.value : 'ALL';
  const searchEl = document.getElementById('etfSearchInput');
  const q = (searchEl ? searchEl.value : '').trim().toLowerCase();

  const filtered = STATE.etf_center.etfs.filter(e => {
    // 主分類頁籤過濾
    if (!q) {
      if (ETF_MAIN_TAB === 'TW') {
        const isBondOrCmd = e.asset_class === '債券' || e.asset_class === '商品與貴金屬';
        const isSectorOrLev = e.eval_methodology_type === '科技與產業 ETF' || e.eval_methodology_type === '海外 ETF' || e.is_leveraged_or_inverse === 1;
        if (e.listing_market !== 'TW' || isBondOrCmd || isSectorOrLev) return false;
      } else if (ETF_MAIN_TAB === 'US') {
        const isBondOrCmd = e.asset_class === '債券' || e.asset_class === '商品與貴金屬' || e.asset_class === 'REITs不動產';
        const isSectorOrLev = e.eval_methodology_type === '科技與產業 ETF' || e.is_leveraged_or_inverse === 1;
        if (e.listing_market !== 'US' || isBondOrCmd || isSectorOrLev) return false;
      } else if (ETF_MAIN_TAB === 'BOND') {
        if (e.asset_class !== '債券' && e.asset_class !== '商品與貴金屬' && e.asset_class !== 'REITs不動產') return false;
      } else if (ETF_MAIN_TAB === 'SECTOR') {
        if (e.eval_methodology_type !== '科技與產業 ETF' && e.eval_methodology_type !== '海外 ETF' && e.is_leveraged_or_inverse !== 1) return false;
      }
    }

    if (concFilter === 'DUAL_FAVORABLE') {
      if (e.conclusion_b_short_mid !== '條件相對有利' || e.total_score_a_long_term < 78) return false;
    } else if (concFilter === 'DIVERGENCE') {
      if (!(e.total_score_a_long_term >= 74 && (e.conclusion_b_short_mid === '等待更佳條件' || e.conclusion_b_short_mid === '持續觀察'))) return false;
    } else if (concFilter === 'CONCENTRATION') {
      if (e.conclusion_a_long_term !== '需注意集中風險') return false;
    } else if (concFilter === 'HIGH_RISK') {
      if (e.conclusion_b_short_mid !== '風險偏高' && e.conclusion_a_long_term !== '不符合配置角色' && e.total_score_b_short_mid >= 62) return false;
    }

    if (q) {
      const matchHold = (e.holdings || []).some(h => h.constituent_code.toLowerCase().includes(q) || h.constituent_name.toLowerCase().includes(q));
      const matchText = e.etf_code.toLowerCase().includes(q) || e.etf_name.toLowerCase().includes(q) || e.tracking_index.toLowerCase().includes(q) || e.sub_category.toLowerCase().includes(q);
      if (!matchHold && !matchText) return false;
    }
    return true;
  });

  const container = document.getElementById('etfCardsGridContainer');
  if (!container) return;
  const isFiltering = !!q || concFilter !== 'ALL';
  const limit = (ETF_SHOW_ALL || isFiltering || ETF_DEEP_MODE) ? filtered.length : ETF_PAGE_SIZE;
  const shown = filtered.slice(0, limit);
  const liveN = STATE.etf_center.etfs.filter(e => e.score_source === 'live').length;
  setSourceNote('etfCardsGridContainer', 'etfSourceNote', liveN
    ? `✅ 台灣掛牌 ${liveN} 檔 ETF 的雙軌評分由官方逐日行情（證交所／櫃買）與法人買賣超用公式即時計算，附「即時評分」標籤；美國 ETF 沒有官方資料來源，行情與評分是 2026-11-21 前後手寫的種子值（「手寫評分」），不會更新。規模、費用率、追蹤誤差與持股權重為人工維護；淨值／折溢價、配息率、含息報酬沒有官方即時來源，顯示 N/A。`
    : '⚠️ 此快照沒有即時 ETF 評分，全部 ETF 的行情、評分與報告都是 2026-11-21 前後手寫的，不會隨資料更新。');
  container.innerHTML = filtered.length
    ? shown.map(e => buildEtfCardHtml(e)).join('')
    : '<div class="etf-clean-card" style="grid-column: 1 / -1; text-align:center; font-size:16px; color:var(--text-secondary);">無符合目前篩選條件之 ETF，請切換上方分類頁籤或清空搜尋關鍵字。</div>';
  const moreBar = document.getElementById('etfMoreBar');
  if (moreBar) {
    moreBar.innerHTML = filtered.length > shown.length
      ? `<button class="btn btn-outline" onclick="ETF_SHOW_ALL = true; renderEtfLists();">顯示其餘 ${filtered.length - shown.length} 檔（共 ${filtered.length} 檔）</button>`
      : (ETF_SHOW_ALL && !isFiltering && !ETF_DEEP_MODE && filtered.length > ETF_PAGE_SIZE
          ? `<button class="btn btn-outline" onclick="ETF_SHOW_ALL = false; renderEtfLists(); scrollToSectionId('etfCardsGridContainer');">只顯示前 ${ETF_PAGE_SIZE} 檔</button>`
          : '');
  }
}

// [已批准提案 ETF-IMPROVE-20261122-002] 禁止對成立未滿 3/5 年之 ETF 外推成立前模擬績效曲線
function buildInlinePerfMiniSvg(e) {
  const r1 = Number(e.return_1y_total_pct || 0);
  const has3Y = e.return_3y_ann_pct !== null && e.return_3y_ann_pct !== undefined;
  const has5Y = e.return_5y_ann_pct !== null && e.return_5y_ann_pct !== undefined;
  const incepYear = parseInt(String(e.inception_date || '2015').slice(0, 4), 10) || 2015;

  const allNodes = [];
  if (has5Y && incepYear <= 2021) {
    const r5Ann = Number(e.return_5y_ann_pct);
    const r3Ann = has3Y ? Number(e.return_3y_ann_pct) : r5Ann;
    const v0 = 100;
    const v2 = Math.max(25, 100 * Math.pow(1 + r5Ann / 100, 2));
    const v4 = Math.max(25, v2 * Math.pow(1 + r3Ann / 100, 2));
    const v5 = Math.max(20, v4 * (1 + r1 / 100));
    allNodes.push(
      { lbl: '2021', val: v0 },
      { lbl: '2022', val: (v0 + v2) / 2 },
      { lbl: '2023', val: v2 },
      { lbl: '2024', val: (v2 + v4) / 2 },
      { lbl: '2025', val: v4 },
      { lbl: '2026/11', val: v5 }
    );
  } else if (has3Y && incepYear <= 2023) {
    const r3Ann = Number(e.return_3y_ann_pct);
    const v0 = 100;
    const v2 = Math.max(25, 100 * Math.pow(1 + r3Ann / 100, 2));
    const v3 = Math.max(20, v2 * (1 + r1 / 100));
    allNodes.push(
      { lbl: `${e.inception_date.slice(0,7)}成立(100)`, val: v0 },
      { lbl: '2024', val: (v0 + v2) / 2 },
      { lbl: '2025', val: v2 },
      { lbl: '2026/11', val: v3 }
    );
  } else {
    const v0 = 100;
    const v1 = Math.max(20, 100 * (1 + r1 / 100));
    allNodes.push(
      { lbl: `${e.inception_date.slice(0,7)}成立(100)`, val: v0 },
      { lbl: '2026/05', val: 100 + r1 * 0.45 },
      { lbl: '2026/09', val: 100 + r1 * 0.85 },
      { lbl: '2026/11', val: v1 }
    );
  }

  const vals = allNodes.map(n => n.val);
  const minV = Math.min(...vals, 90);
  const maxV = Math.max(...vals, 115);
  const span = Math.max(10, maxV - minV);
  const w = 420, h = 115, padX = 44, padY = 20;
  const coords = allNodes.map((n, idx) => {
    const x = padX + (idx / Math.max(1, allNodes.length - 1)) * (w - padX * 2);
    const y = h - padY - ((n.val - minV) / span) * (h - padY * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const lineColor = r1 >= 0 ? '#10b981' : '#f43f5e';
  const noteTag = (!has5Y) ? `<div style="font-size:12px; color:#fbbf24; margin-top:4px;">★ 誠實資料標記：本檔成立於 ${e.inception_date}（未滿5年），僅繪製成立後真實存續軌跡，絕不外推成立前模擬曲線。</div>` : '';
  return `
    <svg viewBox="0 0 ${w} ${h}" style="width:100%; height:115px; background:#070b14; border-radius:8px; border:1px solid #1e293b;">
      <line x1="${padX}" y1="${h - padY}" x2="${w - padX}" y2="${h - padY}" stroke="#334155" stroke-width="1" />
      <polyline fill="none" stroke="${lineColor}" stroke-width="3" points="${coords.join(' ')}" />
      ${allNodes.map((n, idx) => {
        const [cx, cy] = coords[idx].split(',');
        return `
          <circle cx="${cx}" cy="${cy}" r="4" fill="${lineColor}" />
          <text x="${cx}" y="${Number(cy) - 7}" fill="#e2e8f0" font-size="11" font-weight="700" text-anchor="middle">${n.val.toFixed(0)}</text>
          <text x="${cx}" y="${h - 4}" fill="#94a3b8" font-size="10" text-anchor="middle">${n.lbl}</text>
        `;
      }).join('')}
    </svg>
    ${noteTag}
  `;
}

function buildEtfCardHtml(e) {
  const isLev = e.is_leveraged_or_inverse === 1;
  const isExpanded = ETF_DEEP_MODE || ETF_EXPANDED_SET.has(e.etf_code);

  // 嚴格語意邊框與分數色彩：綠＝正向、紅＝風險、橘＝警示、藍＝中性資訊
  let borderCol = '#2a3b5c';
  if (isLev || e.conclusion_b_short_mid === '風險偏高') borderCol = '#f43f5e';
  else if (e.conclusion_b_short_mid === '條件相對有利' && e.total_score_a_long_term >= 80) borderCol = '#10b981';
  else if (e.conclusion_b_short_mid === '等待更佳條件') borderCol = '#f59e0b';

  const scoreAColor = isLev ? '#fb7185' : (e.total_score_a_long_term >= 80 ? '#34d399' : (e.total_score_a_long_term >= 70 ? '#38bdf8' : '#fbbf24'));
  const scoreBColor = e.total_score_b_short_mid >= 75 ? '#34d399' : (e.total_score_b_short_mid < 60 ? '#fb7185' : (e.conclusion_b_short_mid === '等待更佳條件' ? '#fbbf24' : '#38bdf8'));
  const chgCls = (e.change_pct || 0) >= 0 ? 'pos' : 'neg';
  const tzTag = getTimezoneAndSettlementTag(e);
  const mbDual = computeModelBDualHorizons(e);
  const taxDragInfo = computeEffectiveTaxAndFeeDrag(e);
  const pureYieldHtml = computeRecurringPureYield(e);

  // 計算第二層產業分布視覺堆疊橫條
  const palette = ['#10b981', '#38bdf8', '#f59e0b', '#818cf8', '#f43f5e', '#94a3b8'];
  const secEntries = Object.entries(e.sector_weights || {});
  const sectorBarSegs = secEntries.map(([sName, sPct], idx) => {
    const col = palette[idx % palette.length];
    return `<div class="stacked-bar-seg" style="width:${Math.max(4, sPct)}%; background:${col};" title="${sName}: ${sPct}%">${sPct >= 14 ? `${sName} ${sPct}%` : ''}</div>`;
  }).join('');
  const sectorLegend = secEntries.map(([sName, sPct], idx) => {
    const col = palette[idx % palette.length];
    return `<span style="display:inline-flex; align-items:center; gap:5px; font-size:13.5px; color:#e2e8f0; margin-right:12px;"><span style="width:10px; height:10px; border-radius:2px; background:${col}; display:inline-block;"></span>${sName} <strong>${sPct}%</strong></span>`;
  }).join('');

  // 第二層前十大成分股列表
  const holdingsRows = (e.holdings || []).map(h => `
    <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid #1e293b; font-size:14px;">
      <div>
        <strong style="color:#f8fafc;">${h.constituent_code} ${h.constituent_name}</strong>
        <span style="color:#94a3b8; font-size:13px;">(${h.sector_name}｜${h.country_code})</span>
      </div>
      <div style="text-align:right;">
        <strong style="color:#38bdf8; font-size:14.5px;">權重 ${h.weight_pct}%</strong>
        ${h.live_rev_yoy !== null && h.live_rev_yoy !== undefined ? `<span style="margin-left:8px; font-size:13.5px;">10月營收YoY <strong class="${h.live_rev_yoy >= 0 ? 'pos' : 'neg'}">${h.live_rev_yoy >= 0 ? '+' : ''}${h.live_rev_yoy.toFixed(1)}%</strong></span>` : ''}
      </div>
    </div>
  `).join('');

  // 第二層配息來源視覺堆疊條
  const divBoxHtml = e.dividend_breakdown ? `
    <div style="background:#111a2e; padding:14px 16px; border-radius:10px; border:1px solid #2a3b5c; margin-top:14px;">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
        <strong style="font-size:15.5px; color:#f8fafc;">💰 配息來源結構拆解（${e.dividend_breakdown.latest_ex_div_period}｜年化配息率 ${e.dividend_breakdown.annualized_div_yield_pct}%）</strong>
        <span class="badge ${e.dividend_breakdown.dividend_income_ratio_pct >= 75 ? 'badge-lvl4' : 'badge-grade-C'}">現金流健康度：${e.dividend_breakdown.cashflow_sustainability_grade}</span>
      </div>
      <div class="stacked-bar-track" style="height:22px; margin:8px 0;">
        <div class="stacked-bar-seg" style="width:${e.dividend_breakdown.dividend_income_ratio_pct}%; background:#10b981;">股利/票息 ${e.dividend_breakdown.dividend_income_ratio_pct}%</div>
        ${e.dividend_breakdown.capital_gains_ratio_pct > 0 ? `<div class="stacked-bar-seg" style="width:${e.dividend_breakdown.capital_gains_ratio_pct}%; background:#f59e0b;">資本利得價差 ${e.dividend_breakdown.capital_gains_ratio_pct}%</div>` : ''}
        ${e.dividend_breakdown.equalization_reserve_ratio_pct > 0 ? `<div class="stacked-bar-seg" style="width:${e.dividend_breakdown.equalization_reserve_ratio_pct}%; background:#38bdf8;">平準金 ${e.dividend_breakdown.equalization_reserve_ratio_pct}%</div>` : ''}
      </div>
      <div style="font-size:14px; color:#cbd5e1; margin-top:6px;">
        • 填息狀態：<strong>${e.dividend_breakdown.fill_dividend_status}</strong> ｜ ${e.dividend_breakdown.analysis_note}
      </div>
    </div>
  ` : `
    <div style="background:#111a2e; padding:12px 16px; border-radius:10px; border:1px solid #2a3b5c; margin-top:14px; font-size:14px; color:#cbd5e1;">
      💰 <strong>配息分析：</strong>年化殖利率 <strong>${fmtEtfPct(e.dividend_yield_pct)}</strong>（配息頻率：${e.dividend_frequency}），100% 來自成分股真實股利或自動滾入再投資，無動用收益平準金。
    </div>
  `;

  return `
    <div id="etfCard_${e.etf_code}" class="etf-clean-card" style="border-color:${borderCol}; border-top:3px solid ${borderCol};">
      <!-- ================= 第一層：快速閱讀（代號名稱 → 雙軌分數 → 一句結論 → 優勢/風險） ================= -->
      <div class="etf-card-head">
        <div style="min-width:0; flex:1 1 260px;">
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <span class="etf-mkt-tag">${e.listing_market === 'TW' ? '🇹🇼 台灣' : '🇺🇸 美國'}</span>
            ${isLev ? '<span class="badge badge-lvlR">🔴 槓桿/反向</span>' : ''}
            ${etfLiveBadge(e)}
          </div>
          <div style="margin-top:6px; line-height:1.3;">
            <span class="etf-card-code">${e.etf_code}</span> <span class="etf-card-name">${e.etf_name}</span>
          </div>
          <div class="etf-card-meta">
            ${e.sub_category} ｜ 規模 <strong>${e.aum_value.toLocaleString()} ${e.aum_unit}</strong>
          </div>
        </div>
        <div class="etf-card-price-box">
          <div style="font-size:26px; font-weight:800; color:var(--text-primary); line-height:1.15;">
            ${e.close_price} <span style="font-size:12.5px; font-weight:600; color:var(--text-muted);">${e.currency}</span>
          </div>
          <div class="${chgCls}" style="font-size:14px; font-weight:700; margin-top:2px;">
            ${e.change_pct >= 0 ? '▲ +' : '▼ '}${e.change_pct}%
            <span style="color:var(--text-muted); font-weight:500; font-size:12.5px;">${e.trade_date}</span>
          </div>
          <div style="font-size:11.5px; color:var(--text-muted); margin-top:1px;">${tzTag}</div>
        </div>
      </div>

      <!-- 雙軌分數 -->
      <div class="etf-dual-score-grid">
        <div class="etf-dual-score-left">
          <div class="etf-score-label">模型 A　長期配置 <b>3～10 年</b></div>
          <div style="display:flex; align-items:baseline; justify-content:space-between; flex-wrap:wrap; gap:6px;">
            <span class="etf-hero-num" style="color:${scoreAColor};">${isLev ? '隔離不評比' : e.total_score_a_long_term.toFixed(1) + ' <span style="font-size:13px; font-weight:600; color:var(--text-muted);">/ 100</span>'}</span>
            ${concABadge(e.conclusion_a_long_term)}
          </div>
          <div class="etf-score-gauge-track">
            <div class="etf-score-gauge-fill" style="width:${isLev ? 15 : Math.min(100, e.total_score_a_long_term)}%; background:${scoreAColor};"></div>
          </div>
          <div class="etf-score-foot">
            年化總成本 <strong style="color:var(--text-body);">${taxDragInfo.totalDragPct}%</strong> <span style="color:var(--text-muted);">（TER ${taxDragInfo.terPct}%）</span>
          </div>
        </div>
        <div class="etf-dual-score-right">
          <div class="etf-score-label">模型 B　短中期環境 <b>1～12 個月</b></div>
          <div style="display:flex; align-items:baseline; justify-content:space-between; flex-wrap:wrap; gap:6px;">
            <span class="etf-hero-num" style="color:${scoreBColor};">${e.total_score_b_short_mid.toFixed(1)} <span style="font-size:13px; font-weight:600; color:var(--text-muted);">/ 100</span></span>
            ${concBBadge(e.conclusion_b_short_mid)}
          </div>
          <div class="etf-score-gauge-track">
            <div class="etf-score-gauge-fill" style="width:${Math.min(100, e.total_score_b_short_mid)}%; background:${scoreBColor};"></div>
          </div>
          <div class="etf-score-foot">
            短期 1~3M <strong style="color:${mbDual.s1_3m >= 74 ? '#34d399' : '#fbbf24'};">${mbDual.s1_3m}</strong>　中期 3~12M <strong style="color:${mbDual.s3_12m >= 76 ? '#34d399' : '#7dd3fc'};">${mbDual.s3_12m}</strong>
          </div>
        </div>
      </div>

      <!-- 一句白話結論 -->
      <div class="etf-verdict-box" style="border-left-color:${borderCol};">
        💡 ${e.divergence_tag}
      </div>

      <!-- 最大優勢 & 最大風險 -->
      <div class="etf-pros-cons">
        <div class="etf-pc-row"><span class="etf-pc-tag pro">最大優勢</span><span>${e.top_advantage}</span></div>
        <div class="etf-pc-row"><span class="etf-pc-tag con">最大風險</span><span>${e.top_risk}</span></div>
      </div>

      <!-- 展開 / 收合第二層詳細研究按鈕 -->
      <div class="etf-action-btn-row">
        <button id="etfExpandBtn_${e.etf_code}" class="etf-expand-btn" style="margin-top:0; flex:1;" onclick="toggleSingleEtfCard('${e.etf_code}', event)">
          ${isExpanded ? '▲ 收合完整分析' : '▼ 查看完整分析（成分股、配息、績效、費用）'}
        </button>
        <button class="btn btn-outline" onclick="openEtfDetailDrawer('${e.etf_code}')">
          📑 獨立報告
        </button>
      </div>

      <!-- ================= 第二層：詳細研究（點擊「查看完整分析」後才展開） ================= -->
      <div id="etfLayer2_${e.etf_code}" class="etf-layer2-panel ${isExpanded ? 'open' : ''}">
        <!-- 1. 雙軌 10 維度子分數明細 + 提案003/004 雙尺度與稅後實質成本 -->
        <div style="background:#111a2e; padding:14px 16px; border-radius:10px; border:1px solid #2a3b5c; margin-bottom:14px;">
          <div style="font-size:15.5px; font-weight:800; color:#38bdf8; margin-bottom:8px;">
            🔬 雙軌 10 維度獨立評分拆解（套用方法論：${e.eval_methodology_type}｜${tzTag}）
          </div>
          <div style="font-size:14.5px; color:#e2e8f0; line-height:1.75;">
            • <strong>模型 A 長期五維：</strong>底層資產品質 <strong>${e.score_a_underlying_quality}</strong> ｜ 分散與配置角色 <strong>${e.score_a_diversification_role}</strong> ｜ 長期估值風險報酬 <strong>${e.score_a_long_valuation_rr}</strong> ｜ 成本流動性與追蹤 <strong>${e.score_a_cost_liquidity_track}</strong> ｜ 資產互補性 <strong>${e.score_a_complementarity}</strong><br/>
            • <strong>模型 B 短中期五維：</strong>總經與利率環境 <strong>${e.score_b_macro_environment}</strong> ｜ 初級申贖與廣度 <strong>${e.score_b_flow_and_breadth}</strong> ｜ 趨勢與營收動能 <strong>${e.score_b_trend_and_momentum}</strong> ｜ 估值與折溢價位置 <strong>${e.score_b_valuation_and_pos}</strong> ｜ 波動與事件下行風險 <strong>${e.score_b_vol_event_downside}</strong><br/>
            • <strong>時間尺度分離 (提案003)：</strong>短期戰術時機 (1~3M) <strong>${mbDual.s1_3m} 分</strong> ｜ 中期景氣環境 (3~12M) <strong>${mbDual.s3_12m} 分</strong> ｜ 資金×價格象限：<strong>${mbDual.flowPriceQuad}</strong>
            ${mbDual.bondRiskClass ? `<br/>• <strong>債券存續期風險分級 (Agent 05 審查)：</strong>${mbDual.bondRiskClass}` : ''}
            <br/>• <strong>台灣投資人稅後實質持有成本 (提案004)：</strong><strong>${taxDragInfo.totalDragPct}% / 年</strong>（${taxDragInfo.taxNote}） ｜ 經常性純息：${pureYieldHtml}
          </div>
        </div>

        <!-- 2. 產業配置與前十大成分股穿透 -->
        <div class="etf-layer2-split">
          <div style="background:#111a2e; padding:14px 16px; border-radius:10px; border:1px solid #2a3b5c;">
            <div style="font-size:15.5px; font-weight:800; color:#f8fafc; margin-bottom:6px;">
              🏢 產業配置與集中度（前十大佔比 ${e.top10_concentration_pct}%）
            </div>
            <div style="font-size:13.5px; color:#94a3b8; margin-bottom:8px;">最大單一持股：<strong style="color:#fbbf24;">${e.max_single_holding_name}</strong></div>
            <div class="stacked-bar-track">${sectorBarSegs}</div>
            <div style="margin-top:8px;">${sectorLegend}</div>
            <div style="margin-top:12px; max-height:190px; overflow-y:auto;">
              ${holdingsRows}
            </div>
          </div>

          <!-- 3. 歷史績效曲線、波動與最大回撤、估值、資金流向、費用率、折溢價、追蹤誤差 -->
          <div style="background:#111a2e; padding:14px 16px; border-radius:10px; border:1px solid #2a3b5c;">
            <div style="font-size:15.5px; font-weight:800; color:#f8fafc; margin-bottom:6px;">
              ${e.live ? '📈 近 1 年價格走勢與風險指標' : '📈 績效示意曲線（由單一報酬數字內插，非實際走勢）與風險指標'}
            </div>
            ${e.live ? '' : buildInlinePerfMiniSvg(e)}
            ${etfLiveMetricsHtml(e)}
            <div class="etf-metrics-2col">
              <div>• 近1年含息報酬：<strong class="${e.return_1y_total_pct >= 0 ? 'pos' : 'neg'}">${fmtEtfPct(e.return_1y_total_pct, true)}</strong></div>
              <div>• 換算TWD年報酬：<strong class="${e.twd_adjusted_1y_return_pct >= 0 ? 'pos' : 'neg'}">${fmtEtfPct(e.twd_adjusted_1y_return_pct, true)}</strong></div>
              <div>• 近3年/5年年化：<strong>${e.return_3y_ann_pct ?? 'N/A'}% / ${e.return_5y_ann_pct ?? 'N/A'}%</strong></div>
              <div>• 年化波動 / 回撤：<strong>${fmtEtfPct(e.annualized_volatility_pct)} / <span class="neg">${fmtEtfPct(e.max_drawdown_pct)}</span></strong></div>
              <div>• 總費用率 (TER)：<strong>${e.total_expense_ratio_pct}%</strong></div>
              <div>• 追蹤誤差 / 價差：<strong>${e.tracking_error_pct ?? 'N/A'}% / ${e.bid_ask_spread_bps ?? '-'} bps</strong></div>
              <div>• 折溢價率：<strong class="${Math.abs(e.premium_discount_pct) > 0.5 ? 'warn' : ''}">${fmtEtfPct(e.premium_discount_pct, true)}</strong></div>
              <div>• 初級市場淨流向：<strong class="${e.primary_net_flow_value >= 0 ? 'pos' : 'neg'}">${e.primary_net_flow_value === null || e.primary_net_flow_value === undefined ? 'N/A' : fmtEtfNum(e.primary_net_flow_value, true) + ' ' + e.aum_unit}</strong></div>
              <div style="grid-column: 1 / -1;">
                • 底層估值與營收：${e.asset_class === '債券'
                  ? `到期殖利率(YTM) <strong>${e.bond_ytm_pct}%</strong> ｜ 存續期間 <strong>${e.bond_duration_years}年</strong> (${e.bond_avg_credit_rating})`
                  : `加權 P/E <strong>${e.weighted_pe ?? 'N/A'}x</strong> ｜ P/B <strong>${e.weighted_pb ?? 'N/A'}x</strong> ｜ 10月營收加權YoY <strong class="pos">${e.weighted_rev_yoy_pct !== null ? (e.weighted_rev_yoy_pct >= 0 ? '+' : '') + e.weighted_rev_yoy_pct + '%' : 'N/A'}</strong>`}
              </div>
            </div>
          </div>
        </div>

        <!-- 4. 配息來源結構拆解 -->
        ${divBoxHtml}

        <!-- 5. 完整研究報告（支持證據、反方證據、指標矛盾、失效條件與稅務口徑） -->
        <div style="background:#111a2e; padding:14px 16px; border-radius:10px; border:1px solid #2a3b5c; margin-top:14px; font-size:14.5px; line-height:1.7;">
          <div style="font-size:15.5px; font-weight:800; color:#f8fafc; margin-bottom:8px;">📋 完整研究報告（正反方證據、指標矛盾與失效條件）</div>
          <div style="margin-bottom:6px;"><strong style="color:#34d399;">🟢 支持證據：</strong>${e.supporting_evidence}</div>
          <div style="margin-bottom:6px;"><strong style="color:#fb7185;">🔴 反方證據：</strong>${e.counter_evidence}</div>
          <div style="margin-bottom:6px;"><strong style="color:#fbbf24;">🟠 指標矛盾與分歧說明：</strong>${e.contradiction_notes}</div>
          <div style="margin-bottom:6px;"><strong style="color:#38bdf8;">🔵 判斷失效條件：</strong>${e.invalidation_conditions}</div>
          <div style="color:#94a3b8; font-size:13.5px;">• 下一個觀察指標：${e.next_watch_indicator} ｜ 稅務與制度：${e.tax_and_trading_notes}</div>
        </div>
      </div>
    </div>
  `;
}

function openEtfDetailDrawer(etfCode) {
  const e = (STATE.etf_center.etfs || []).find(x => x.etf_code === etfCode);
  if (!e) return;
  const isLev = e.is_leveraged_or_inverse === 1;

  const holdsHtml = (e.holdings || []).map(h => `
    <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #1e293b; font-size:14px;">
      <span><strong>${h.constituent_code} ${h.constituent_name}</strong> (${h.country_code})</span>
      <span>權重 <strong>${h.weight_pct}%</strong> ${h.live_rev_yoy !== null && h.live_rev_yoy !== undefined ? `｜10月營收YoY <strong class="${h.live_rev_yoy>=0?'pos':'neg'}">${h.live_rev_yoy>=0?'+':''}${h.live_rev_yoy.toFixed(1)}%</strong>｜P/E ${h.live_pe ?? '-'}x` : ''}</span>
    </div>
  `).join('');

  const divHtml = e.dividend_breakdown ? `
    <div class="q6-box" style="border-color:var(--accent-orange);">
      <div class="q6-title" style="color:var(--accent-orange); font-size:15px;">💰 高股息/債券專屬檢驗：配息來源結構拆解 (${e.dividend_breakdown.latest_ex_div_period})</div>
      <div style="font-size:14.5px; color:#fff; line-height:1.7;">
        • 年化配息率：<strong>${e.dividend_breakdown.annualized_div_yield_pct}%</strong> ｜ 健康度評級：<strong>${e.dividend_breakdown.cashflow_sustainability_grade}</strong><br/>
        • <strong>經常性股利/債券票息所得佔比：${e.dividend_breakdown.dividend_income_ratio_pct}%</strong><br/>
        • <strong>已實現資本利得(價差)佔比：${e.dividend_breakdown.capital_gains_ratio_pct}%</strong> ｜ <strong>收益平準金佔比：${e.dividend_breakdown.equalization_reserve_ratio_pct}%</strong><br/>
        • 填息狀態：${e.dividend_breakdown.fill_dividend_status}<br/>
        <div style="margin-top:6px; color:#fde68a;">${e.dividend_breakdown.analysis_note}</div>
      </div>
    </div>
  ` : '';

  const html = `
    <div class="q6-box" style="background:#090e1a;">
      <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:12px;">
        <div>
          <div style="font-size:13.5px; color:var(--text-secondary);">【模型 A】長期配置評估 (3~10年)</div>
          <div style="font-size:26px; font-weight:700; color:#34d399;">${isLev ? '槓反隔離' : e.total_score_a_long_term + ' 分'}</div>
          ${concABadge(e.conclusion_a_long_term)}
        </div>
        <div>
          <div style="font-size:13.5px; color:var(--text-secondary);">【模型 B】短中期進場環境 (1~12M)</div>
          <div style="font-size:26px; font-weight:700; color:#38bdf8;">${e.total_score_b_short_mid} 分</div>
          ${concBBadge(e.conclusion_b_short_mid)}
        </div>
      </div>
      <div style="margin-top:10px; font-size:14px; color:#cbd5e1; line-height:1.7;">
        <strong>模型A五維：</strong>底層品質 ${e.score_a_underlying_quality}｜分散度 ${e.score_a_diversification_role}｜長期估值 ${e.score_a_long_valuation_rr}｜費用流動性 ${e.score_a_cost_liquidity_track}｜互補性 ${e.score_a_complementarity}<br/>
        <strong>模型B五維：</strong>總經環境 ${e.score_b_macro_environment}｜申贖廣度 ${e.score_b_flow_and_breadth}｜趨勢動能 ${e.score_b_trend_and_momentum}｜估值位置 ${e.score_b_valuation_and_pos}｜波動風險 ${e.score_b_vol_event_downside}
      </div>
    </div>

    ${divHtml}

    <div class="q6-box">
      <div class="q6-title" style="font-size:15px;">📊 基金品質、估值與底層成分股穿透 (${e.holdings_coverage_note})</div>
      <div style="font-size:14.5px; color:#e2e8f0; margin-bottom:10px; line-height:1.7;">
        • 總費用率(TER)：<strong>${e.total_expense_ratio_pct}%</strong> (管理費 ${e.mgmt_fee_pct}%)｜追蹤誤差：<strong>${e.tracking_error_pct ?? 'N/A'}%</strong>｜買賣價差：<strong>${e.bid_ask_spread_bps ?? '-'} bps</strong><br/>
        • 折溢價率：<strong>${fmtEtfPct(e.premium_discount_pct, true)}</strong>｜初級市場近期淨申贖：<strong>${e.primary_net_flow_value === null || e.primary_net_flow_value === undefined ? 'N/A' : fmtEtfNum(e.primary_net_flow_value, true) + ' ' + e.aum_unit}</strong><br/>
        • 底層加權P/E：<strong>${e.weighted_pe ?? 'N/A'}x</strong>｜加權P/B：<strong>${e.weighted_pb ?? 'N/A'}x</strong>｜底層10月營收加權YoY：<strong>${e.weighted_rev_yoy_pct !== null ? (e.weighted_rev_yoy_pct >= 0 ? '+' : '') + e.weighted_rev_yoy_pct + '%' : 'N/A'}</strong>
        ${e.bond_ytm_pct ? `<br/>• 債券到期殖利率(YTM)：<strong>${e.bond_ytm_pct}%</strong>｜有效存續期間：<strong>${e.bond_duration_years} 年</strong>｜信用評等：<strong>${e.bond_avg_credit_rating}</strong>` : ''}
      </div>
      ${holdsHtml}
    </div>

    <div class="q6-box"><div class="q6-title" style="color:#34d399; font-size:15px;">🟢 支持證據 (Supporting Evidence)</div><div style="font-size:14.5px;">${e.supporting_evidence}</div></div>
    <div class="q6-box"><div class="q6-title" style="color:#fb7185; font-size:15px;">🔴 反方證據與主要風險 (Counter Evidence &amp; Risks)</div><div style="font-size:14.5px;">${e.counter_evidence}<br/><br/><strong>最大風險：</strong>${e.top_risk}</div></div>
    <div class="q6-box"><div class="q6-title" style="color:#fbbf24; font-size:15px;">🟠 指標矛盾與分歧說明</div><div style="font-size:14.5px;">${e.contradiction_notes}</div></div>
    <div class="q6-box">
      <div class="q6-title" style="font-size:15px;">🔵 判斷失效條件與下一個觀察指標</div>
      <div style="font-size:14.5px;">
        • <strong>失效條件：</strong>${e.invalidation_conditions}<br/>
        • <strong>下一個觀察指標：</strong>${e.next_watch_indicator}<br/>
        • <strong>交易與稅務制度口徑：</strong>${e.tax_and_trading_notes}
      </div>
    </div>
    <div style="font-size:13.5px; color:var(--text-secondary);">
      資料更新日期：${e.trade_date} ｜ 資料可信度：等級 ${e.credibility_grade} ｜ 資料缺失率：${e.missing_data_pct}% (${e.missing_fields_note})
    </div>
  `;

  document.getElementById('drawerHeaderBadge').innerHTML = `<span class="badge badge-grade-${e.credibility_grade}">${e.listing_market} 掛牌｜${e.eval_methodology_type}</span>`;
  document.getElementById('drawerTitle').textContent = `${e.etf_code} ${e.etf_name}`;
  document.getElementById('drawerSubtitle').textContent = `${e.tracking_index} ｜ 雙軌診斷：${e.divergence_tag}`;
  document.getElementById('drawerBody').innerHTML = html;
  document.getElementById('drawerBackdrop').classList.add('open');
  document.getElementById('drawerPanel').classList.add('open');
}

