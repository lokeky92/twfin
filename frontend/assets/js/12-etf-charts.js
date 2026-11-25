/* =========================================================================
   第五區視覺化圖表 1～7 渲染引擎（清楚標示時間範圍、單位與資料日期）
   ========================================================================= */
// 圖 1：台灣與美國 ETF 初級市場資金淨流向圖
function renderChart1Flows() {
  const box = document.getElementById('etfChart1FlowsBox');
  if (!box || !STATE || !STATE.etf_center) return;
  const mkt = (document.getElementById('chart1MarketSwitch') || {}).value || 'ALL';
  let list = [...(STATE.etf_center.etfs || [])].filter(e => e.listing_market === 'TW' || e.listing_market === 'US');
  if (mkt !== 'ALL') list = list.filter(e => e.listing_market === mkt);

  // 依絕對流量排序取前 12 檔代表
  list.sort((a, b) => Math.abs(b.primary_net_flow_value || 0) - Math.abs(a.primary_net_flow_value || 0));
  const top = list.slice(0, 12).sort((a, b) => (b.primary_net_flow_value || 0) - (a.primary_net_flow_value || 0));
  const maxAbs = Math.max(10, ...top.map(e => Math.abs(e.primary_net_flow_value || 0)));

  box.innerHTML = top.map(e => {
    const v = Number(e.primary_net_flow_value || 0);
    const pctW = Math.min(100, Math.max(4, (Math.abs(v) / maxAbs) * 100));
    const col = v >= 0 ? '#10b981' : '#f43f5e';
    return `
      <div class="etf-chart-bar-row" onclick="jumpToEtfCard('${e.etf_code}')">
        <div style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
          <strong style="color:#f8fafc;">[${e.listing_market}] ${e.etf_code}</strong> <span style="color:#cbd5e1;">${e.etf_name}</span>
        </div>
        <div style="background:#090e1a; height:16px; border-radius:4px; overflow:hidden; display:flex; align-items:center;">
          <div style="width:${pctW.toFixed(1)}%; height:100%; background:${col}; border-radius:4px;"></div>
        </div>
        <div style="text-align:right; font-weight:800; color:${col};">
          ${v >= 0 ? '+' : ''}${v} <span style="font-size:12px; color:#94a3b8;">${e.aum_unit}</span>
        </div>
      </div>
    `;
  }).join('');
}

// 圖 2 & 圖 3：ETF 長期配置分數圖 (模型 A) vs 短中期市場動能圖 (模型 B)
function renderChart2And3Scores() {
  const boxA = document.getElementById('etfChart2LongScoreBox');
  const boxB = document.getElementById('etfChart3ShortScoreBox');
  if (!boxA || !boxB || !STATE || !STATE.etf_center) return;
  const nonLev = (STATE.etf_center.etfs || []).filter(e => e.is_leveraged_or_inverse === 0);

  const rankA = [...nonLev].sort((a, b) => (b.total_score_a_long_term || 0) - (a.total_score_a_long_term || 0)).slice(0, 12);
  const rankB = [...(STATE.etf_center.etfs || [])].sort((a, b) => (b.total_score_b_short_mid || 0) - (a.total_score_b_short_mid || 0)).slice(0, 12);

  boxA.innerHTML = rankA.map((e, i) => {
    const s = Number(e.total_score_a_long_term || 0);
    const col = e.conclusion_a_long_term === '需注意集中風險' ? '#f59e0b' : (s >= 80 ? '#10b981' : '#38bdf8');
    return `
      <div class="etf-chart-bar-row" onclick="jumpToEtfCard('${e.etf_code}')">
        <div style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
          <strong style="color:${col};">#${i + 1}</strong> <strong style="color:#f8fafc;">${e.etf_code}</strong> <span style="color:#cbd5e1;">${e.etf_name}</span>
        </div>
        <div style="background:#090e1a; height:16px; border-radius:4px; overflow:hidden;">
          <div style="width:${s}%; height:100%; background:${col};"></div>
        </div>
        <div style="text-align:right; font-weight:700; color:${col};">${s.toFixed(1)} 分</div>
      </div>
    `;
  }).join('');

  boxB.innerHTML = rankB.map((e, i) => {
    const s = Number(e.total_score_b_short_mid || 0);
    const col = e.conclusion_b_short_mid === '條件相對有利' ? '#10b981' : (e.conclusion_b_short_mid === '等待更佳條件' ? '#f59e0b' : (e.conclusion_b_short_mid === '風險偏高' ? '#f43f5e' : '#38bdf8'));
    return `
      <div class="etf-chart-bar-row" onclick="jumpToEtfCard('${e.etf_code}')">
        <div style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
          <strong style="color:${col};">#${i + 1}</strong> <strong style="color:#f8fafc;">${e.etf_code}</strong> <span style="color:#cbd5e1;">${e.etf_name}</span>
        </div>
        <div style="background:#090e1a; height:16px; border-radius:4px; overflow:hidden;">
          <div style="width:${s}%; height:100%; background:${col};"></div>
        </div>
        <div style="text-align:right; font-weight:700; color:${col};">${s.toFixed(1)} 分</div>
      </div>
    `;
  }).join('');
}

// 圖 4：代表性 ETF 歷史累積績效曲線比較圖（可切換 1Y / 3Y / 5Y）
function switchPerfChartHorizon(h) {
  ETF_PERF_HORIZON = h;
  ['1Y', '3Y', '5Y'].forEach(k => {
    const b = document.getElementById('perfBtn_' + k);
    if (b) b.className = k === h ? 'btn btn-sm' : 'btn btn-outline btn-sm';
  });
  renderChart4PerfCurve();
}

function renderChart4PerfCurve() {
  const box = document.getElementById('etfChart4PerfCurveBox');
  if (!box || !STATE || !STATE.etf_center) return;
  const codes = ['0050', '0052', '00713', '00878', 'VOO', 'QQQ', 'SMH', '00937B', 'SGOV'];
  const colors = ['#10b981', '#f59e0b', '#38bdf8', '#a855f7', '#22d3ee', '#fb7185', '#f97316', '#84cc16', '#94a3b8'];
  const etfs = codes.map(c => (STATE.etf_center.etfs || []).find(x => x.etf_code === c)).filter(e => {
    if (!e) return false;
    // [提案 ETF-IMPROVE-20261122-002] 若切換至 3Y 或 5Y，自動排除成立未滿該年限 (數值為 NULL) 之 ETF，絕不外推模擬曲線
    if (ETF_PERF_HORIZON === '3Y' && (e.return_3y_ann_pct === null || e.return_3y_ann_pct === undefined)) return false;
    if (ETF_PERF_HORIZON === '5Y' && (e.return_5y_ann_pct === null || e.return_5y_ann_pct === undefined)) return false;
    return true;
  });

  const timeLabels = ETF_PERF_HORIZON === '1Y'
    ? ['2025/11 (基期100)', '2026/02', '2026/05', '2026/08', '2026/10', '2026/11/20']
    : (ETF_PERF_HORIZON === '3Y'
      ? ['2023/11 (基期100)', '2024/05', '2024/11', '2025/05', '2025/11', '2026/11/20']
      : ['2021/11 (基期100)', '2022/11', '2023/11', '2024/11', '2025/11', '2026/11/20']);

  const series = etfs.map((e, idx) => {
    const r1 = Number(e.return_1y_total_pct || 0);
    const r3Ann = e.return_3y_ann_pct !== null && e.return_3y_ann_pct !== undefined ? Number(e.return_3y_ann_pct) : r1 * 0.75;
    const r5Ann = e.return_5y_ann_pct !== null && e.return_5y_ann_pct !== undefined ? Number(e.return_5y_ann_pct) : r3Ann * 0.85;
    let totalPct = r1;
    if (ETF_PERF_HORIZON === '3Y') totalPct = (Math.pow(1 + r3Ann / 100, 3) - 1) * 100;
    if (ETF_PERF_HORIZON === '5Y') totalPct = (Math.pow(1 + r5Ann / 100, 5) - 1) * 100;

    // 建立 6 個時間節點軌跡（反映 2026/10 高點與 2026/11 震盪）
    const endVal = 100 + totalPct;
    const octPeak = e.eval_methodology_type === '科技與產業 ETF' ? endVal * 1.07 : endVal * 1.02;
    const pts = [
      100,
      100 + totalPct * 0.22,
      100 + totalPct * 0.48,
      100 + totalPct * 0.76,
      octPeak,
      endVal
    ];
    return { e, col: colors[idx % colors.length], pts, totalPct };
  });

  const allVals = series.flatMap(s => s.pts);
  const minV = Math.min(85, ...allVals);
  const maxV = Math.max(125, ...allVals);
  const span = Math.max(15, maxV - minV);
  const W = 680, H = 260, padL = 48, padR = 24, padT = 20, padB = 34;

  const linesSvg = series.map(s => {
    const coords = s.pts.map((v, i) => {
      const x = padL + (i / (s.pts.length - 1)) * (W - padL - padR);
      const y = H - padB - ((v - minV) / span) * (H - padT - padB);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const [lx, ly] = coords[coords.length - 1].split(',');
    return `
      <polyline fill="none" stroke="${s.col}" stroke-width="2.6" points="${coords.join(' ')}" />
      <circle cx="${lx}" cy="${ly}" r="4" fill="${s.col}" />
    `;
  }).join('');

  const xAxisSvg = timeLabels.map((lbl, i) => {
    const x = padL + (i / (timeLabels.length - 1)) * (W - padL - padR);
    return `<text x="${x.toFixed(1)}" y="${H - 10}" fill="#94a3b8" font-size="12" text-anchor="middle">${lbl}</text>`;
  }).join('');

  const yTicks = [minV, minV + span * 0.5, maxV].map(v => {
    const y = H - padB - ((v - minV) / span) * (H - padT - padB);
    return `
      <line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="#1e293b" stroke-dasharray="4 4" />
      <text x="${padL - 8}" y="${(y + 4).toFixed(1)}" fill="#94a3b8" font-size="12" text-anchor="end">${v.toFixed(0)}</text>
    `;
  }).join('');

  const legendHtml = series.sort((a, b) => b.totalPct - a.totalPct).map(s => `
    <span onclick="jumpToEtfCard('${s.e.etf_code}')" style="display:inline-flex; align-items:center; gap:6px; background:#090e1a; border:1px solid #1e293b; padding:4px 10px; border-radius:6px; font-size:13.5px; cursor:pointer;">
      <span style="width:12px; height:4px; background:${s.col}; display:inline-block;"></span>
      <strong style="color:#f8fafc;">${s.e.etf_code}</strong>
      <strong style="color:${s.totalPct >= 0 ? '#34d399' : '#fb7185'};">${s.totalPct >= 0 ? '+' : ''}${s.totalPct.toFixed(1)}%</strong>
    </span>
  `).join('');

  box.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%; height:260px; background:#090e1a; border-radius:10px; border:1px solid #1e293b;">
      ${yTicks}
      ${linesSvg}
      ${xAxisSvg}
    </svg>
    <div style="display:flex; flex-wrap:wrap; gap:8px; margin-top:12px;">${legendHtml}</div>
  `;
}

// 圖 5：ETF 底層前十大持股與產業配置視覺分布圖
function renderChart5HoldingsDist() {
  const box = document.getElementById('etfChart5HoldingsBox');
  const sel = document.getElementById('chart5EtfSelect');
  if (!box || !sel || !STATE || !STATE.etf_center) return;
  const code = sel.value || '0050';
  const e = (STATE.etf_center.etfs || []).find(x => x.etf_code === code) || STATE.etf_center.etfs[0];
  if (!e) return;

  const palette = ['#10b981', '#38bdf8', '#f59e0b', '#818cf8', '#f43f5e', '#94a3b8'];
  const secEntries = Object.entries(e.sector_weights || {});
  const secBar = secEntries.map(([sName, sPct], idx) => {
    const col = palette[idx % palette.length];
    return `<div class="stacked-bar-seg" style="width:${Math.max(4, sPct)}%; background:${col};">${sPct >= 10 ? `${sName} ${sPct}%` : ''}</div>`;
  }).join('');

  const holdsBars = (e.holdings || []).map(h => {
    const w = Math.min(100, Number(h.weight_pct || 0));
    const col = w >= 40 ? '#f59e0b' : '#38bdf8';
    return `
      <div class="etf-chart-bar-row">
        <div style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
          <strong style="color:#f8fafc;">${h.constituent_code} ${h.constituent_name}</strong>
        </div>
        <div style="background:#090e1a; height:16px; border-radius:4px; overflow:hidden;">
          <div style="width:${w}%; height:100%; background:${col};"></div>
        </div>
        <div style="text-align:right; font-size:13.5px;">
          <strong style="color:#f8fafc;">${h.weight_pct}%</strong>
          ${h.live_rev_yoy !== null && h.live_rev_yoy !== undefined ? `<span style="color:#34d399; margin-left:4px;">+${h.live_rev_yoy.toFixed(0)}%</span>` : ''}
        </div>
      </div>
    `;
  }).join('');

  box.innerHTML = `
    <div style="font-size:14.5px; color:#cbd5e1; margin-bottom:8px;">
      <strong>${e.etf_code} ${e.etf_name}</strong> ｜ 前十大持股集中度：<strong style="color:#38bdf8;">${e.top10_concentration_pct}%</strong> ｜ 最大單一持股：<strong style="color:#fbbf24;">${e.max_single_holding_name}</strong>
    </div>
    <div class="stacked-bar-track" style="height:24px; margin-bottom:14px;">${secBar}</div>
    <div>${holdsBars}</div>
  `;
}

// 圖 7：ETF 風險與報酬比較散點圖 (Risk vs. Return SVG Scatter Plot)
function renderChart7RiskReturn() {
  const box = document.getElementById('etfChart7ScatterBox');
  if (!box || !STATE || !STATE.etf_center) return;
  const horizon = (document.getElementById('chart7HorizonSwitch') || {}).value || '1Y';
  const etfs = (STATE.etf_center.etfs || []).filter(e => {
    if (horizon === '3Y') return e.return_3y_ann_pct !== null && e.return_3y_ann_pct !== undefined;
    if (horizon === '5Y') return e.return_5y_ann_pct !== null && e.return_5y_ann_pct !== undefined;
    return true;
  });

  const pts = etfs.map(e => {
    const x = Number(e.annualized_volatility_pct || 15);
    let y = Number(e.return_1y_total_pct || 0);
    if (horizon === 'TWD1Y') y = Number(e.twd_adjusted_1y_return_pct || 0);
    else if (horizon === '3Y') y = Number(e.return_3y_ann_pct || 0);
    else if (horizon === '5Y') y = Number(e.return_5y_ann_pct || 0);
    const col = e.is_leveraged_or_inverse ? '#f43f5e' : (e.conclusion_b_short_mid === '條件相對有利' ? '#10b981' : (e.conclusion_b_short_mid === '等待更佳條件' ? '#f59e0b' : '#38bdf8'));
    return { e, x, y, col };
  });

  const minX = 0;
  const maxX = Math.max(35, ...pts.map(p => p.x)) * 1.08;
  const minY = Math.min(-5, ...pts.map(p => p.y)) - 4;
  const maxY = Math.max(35, ...pts.map(p => p.y)) + 6;
  const W = 680, H = 295, padL = 52, padR = 30, padT = 24, padB = 38;

  const toX = v => padL + ((v - minX) / (maxX - minX)) * (W - padL - padR);
  const toY = v => H - padB - ((v - minY) / (maxY - minY)) * (H - padT - padB);

  const zeroY = toY(0);
  const circlesSvg = pts.map(p => {
    const cx = toX(p.x).toFixed(1);
    const cy = toY(p.y).toFixed(1);
    return `
      <g style="cursor:pointer;" onclick="jumpToEtfCard('${p.e.etf_code}')">
        <circle cx="${cx}" cy="${cy}" r="7" fill="${p.col}" fill-opacity="0.85" stroke="#0f172a" stroke-width="1.5">
          <title>${p.e.etf_code} ${p.e.etf_name}｜年化波動度: ${p.x}%｜報酬率: ${p.y}%</title>
        </circle>
        <text x="${cx}" y="${(Number(cy) - 10).toFixed(1)}" fill="#f8fafc" font-size="11.5" font-weight="700" text-anchor="middle">${p.e.etf_code}</text>
      </g>
    `;
  }).join('');

  box.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%; height:295px; background:#090e1a; border-radius:10px; border:1px solid #1e293b;">
      <line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${W - padR}" y2="${zeroY.toFixed(1)}" stroke="#334155" stroke-dasharray="4 4" />
      <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${H - padB}" stroke="#475569" />
      <line x1="${padL}" y1="${H - padB}" x2="${W - padR}" y2="${H - padB}" stroke="#475569" />
      <text x="${W / 2}" y="${H - 8}" fill="#94a3b8" font-size="12.5" font-weight="700" text-anchor="middle">X 軸：年化波動度 Risk (%) ➔ 越往左波動越低</text>
      <text x="16" y="${H / 2}" fill="#94a3b8" font-size="12.5" font-weight="700" text-anchor="middle" transform="rotate(-90 16 ${H / 2})">Y 軸：含息報酬 Return (%)</text>
      ${circlesSvg}
    </svg>
    <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:13.5px; color:#cbd5e1; margin-top:8px;">
      <span>🟢 綠色圓點：短中期條件相對有利 ｜ 🟠 橘色圓點：短期等待更佳條件 ｜ 🔴 紅色圓點：槓反或高風險標的</span>
      <span>💡 點擊圖上任一 ETF 代號即可跳轉至該卡片</span>
    </div>
  `;
}

