/* =========================================================================
   圖 6：多檔 ETF 深度比較器 ＆ 兩兩持股重疊度熱力矩陣 (Holdings Overlap Matrix)
   [已批准提案 ETF-IMPROVE-20261122-001] 跨市場底層資產實體正規化映射 (2330 <-> TSM ADR, 00679B <-> TLT, 00635U <-> GLD)
   ========================================================================= */
function computePairwiseOverlap(etfA, etfB) {
  if (etfA.etf_code === etfB.etf_code) return { overlapPct: 100.0, sharedNames: ['同一檔 ETF'] };
  const mapA = {};
  (etfA.holdings || []).forEach(h => {
    const ent = canonicalEntityInfo(h.constituent_code, h.constituent_name);
    mapA[ent.key] = { w: (mapA[ent.key] ? mapA[ent.key].w : 0) + h.weight_pct, label: ent.label };
  });
  let overlapSum = 0.0;
  const sharedNames = [];
  (etfB.holdings || []).forEach(h => {
    const ent = canonicalEntityInfo(h.constituent_code, h.constituent_name);
    if (mapA[ent.key] !== undefined) {
      const minW = Math.min(mapA[ent.key].w, h.weight_pct);
      overlapSum += minW;
      sharedNames.push(`${ent.label}(共疊 ${minW.toFixed(1)}%)`);
    }
  });
  return { overlapPct: Math.min(100.0, roundTo1(overlapSum)), sharedNames };
}

function roundTo1(v) { return Math.round(v * 10) / 10; }

function toggleCompareEtf(code, checked) {
  if (checked) {
    if (!ETF_COMPARE_CODES.includes(code)) ETF_COMPARE_CODES.push(code);
  } else {
    ETF_COMPARE_CODES = ETF_COMPARE_CODES.filter(c => c !== code);
  }
  renderEtfComparator();
}

function resetDefaultCompareSelection() {
  ETF_COMPARE_CODES = ['0050', '0052', '00878', 'VOO', 'SMH', '00937B'];
  renderEtfComparator();
}

function renderEtfComparator() {
  const etfs = STATE.etf_center.etfs || [];
  const bar = document.getElementById('etfCompareCheckboxBar');
  if (!bar) return;
  bar.innerHTML = etfs.map(e => {
    const chk = ETF_COMPARE_CODES.includes(e.etf_code) ? 'checked' : '';
    return `
      <label style="background:#090e1a; border:1px solid #26334d; padding:6px 12px; border-radius:8px; font-size:14px; cursor:pointer; display:inline-flex; align-items:center; gap:6px;">
        <input type="checkbox" ${chk} onchange="toggleCompareEtf('${e.etf_code}', this.checked)" />
        <span><strong style="color:#f8fafc;">${e.etf_code}</strong> <span style="color:#cbd5e1;">${e.etf_name}</span></span>
      </label>
    `;
  }).join('');

  const picked = etfs.filter(e => ETF_COMPARE_CODES.includes(e.etf_code));
  const matrixBox = document.getElementById('etfChart6OverlapMatrixBox');
  if (picked.length < 1) {
    if (matrixBox) matrixBox.innerHTML = '';
    document.getElementById('etfOverlapAlertBox').innerHTML = '<div class="evidence-box">請至少勾選 2 檔 ETF 進行並排比較與持股重疊度熱力圖分析。</div>';
    document.getElementById('etfComparisonHead').innerHTML = '';
    document.getElementById('etfComparisonBody').innerHTML = '';
    const etfMobEmpty = document.getElementById('etfComparisonMobileCards');
    if (etfMobEmpty) etfMobEmpty.innerHTML = '';
    return;
  }

  // 渲染圖 6：兩兩持股重疊比較熱力圖矩陣 (Pairwise Overlap Heatmap Table)
  if (matrixBox && picked.length >= 2) {
    const headCells = picked.map(e => `<th style="text-align:center;">${e.etf_code}<br/><span style="font-size:12px; color:#94a3b8;">${e.etf_name}</span></th>`).join('');
    const bodyRows = picked.map(rowEtf => {
      const cells = picked.map(colEtf => {
        const res = computePairwiseOverlap(rowEtf, colEtf);
        const p = res.overlapPct;
        let bg = 'rgba(16, 185, 129, 0.12)';
        let textCol = '#34d399';
        if (rowEtf.etf_code === colEtf.etf_code) {
          bg = 'rgba(56, 189, 248, 0.15)';
          textCol = '#94a3b8';
        } else if (p >= 45) {
          bg = 'rgba(244, 63, 94, 0.28)';
          textCol = '#fb7185';
        } else if (p >= 15) {
          bg = 'rgba(245, 158, 11, 0.24)';
          textCol = '#fbbf24';
        }
        return `<td style="text-align:center; background:${bg}; color:${textCol}; font-weight:800; font-size:15px;" title="${res.sharedNames.join('、')}">${rowEtf.etf_code === colEtf.etf_code ? '100% (自身)' : p + '%'}</td>`;
      }).join('');
      return `<tr><td style="font-weight:800; color:#f8fafc;">${rowEtf.etf_code} ${rowEtf.etf_name}</td>${cells}</tr>`;
    }).join('');

    matrixBox.innerHTML = `
      <div style="font-size:15px; font-weight:800; color:#38bdf8; margin-bottom:8px;">
        🔥 兩兩 ETF 前十大核心持股＆跨國 ADR 實體穿透重疊度熱力矩陣（已啟用提案 001：自動貫穿台股 2330 與美股 TSM ADR、00679B 與 TLT）：
      </div>
      <div style="overflow-x:auto;">
        <table style="font-size:14px;">
          <thead><tr><th>ETF 代號與名稱</th>${headCells}</tr></thead>
          <tbody>${bodyRows}</tbody>
        </table>
      </div>
    `;
  } else if (matrixBox) {
    matrixBox.innerHTML = '';
  }

  // 計算所有兩兩組合之持股重疊度文字警示
  const highOverlaps = [];
  for (let i = 0; i < picked.length; i++) {
    for (let j = i + 1; j < picked.length; j++) {
      const res = computePairwiseOverlap(picked[i], picked[j]);
      if (res.overlapPct >= 10.0) {
        highOverlaps.push(`• <strong>${picked[i].etf_code} (${picked[i].etf_name})</strong> 與 <strong>${picked[j].etf_code} (${picked[j].etf_name})</strong>：前十大底層持股直接重疊度達 <strong style="color:#fb7185; font-size:16px;">${res.overlapPct}%</strong>（重疊標的：${res.sharedNames.join('、')}）`);
      }
    }
  }

  document.getElementById('etfOverlapAlertBox').innerHTML = highOverlaps.length ? `
    <div class="evidence-box counter" style="font-size:15px;">
      <strong>🟠 跨 ETF 持股重疊度自動偵測警示（名稱不同但底層重倉相同股票）：</strong><br/>
      ${highOverlaps.join('<br/>')}
    </div>
  ` : `<div class="evidence-box" style="border-left-color:#10b981; font-size:15px;">🟢 目前勾選的 ETF 組合之間無顯著前十大個股重疊（重疊度皆低於 10%），具備良好分散互補效果。</div>`;

  document.getElementById('etfComparisonHead').innerHTML = `
    <tr>
      <th>比較維度 / 指標</th>
      ${picked.map(e => `<th>[${e.listing_market}] ${e.etf_code}<br/><span style="color:#fff; font-size:15px;">${e.etf_name}</span></th>`).join('')}
    </tr>
  `;

  const rows = [
    ["模型 A：長期配置總分與結論", e => `<strong style="color:#34d399; font-size:18px;">${e.is_leveraged_or_inverse ? '隔離' : e.total_score_a_long_term + ' 分'}</strong><br/>${concABadge(e.conclusion_a_long_term)}`],
    ["模型 B：短中期環境總分與雙尺度拆解 (提案003)", e => {
      const mb = computeModelBDualHorizons(e);
      return `<strong style="color:#38bdf8; font-size:18px;">${e.total_score_b_short_mid} 分</strong><br/>${concBBadge(e.conclusion_b_short_mid)}<br/><span style="font-size:13px; color:#cbd5e1;">短期1~3M: <strong>${mb.s1_3m}</strong>｜中期3~12M: <strong>${mb.s3_12m}</strong></span>`;
    }],
    ["追蹤指數與資產類別", e => `${e.tracking_index}<br/><span style="color:var(--text-secondary);">${e.sub_category} (${e.management_style})</span>`],
    ["總費用率 (TER) / 管理費", e => `<strong>${e.total_expense_ratio_pct}%</strong> (管理費 ${e.mgmt_fee_pct}%)`],
    ["台灣投資人稅後實質年化持有成本 (提案004)", e => {
      const td = computeEffectiveTaxAndFeeDrag(e);
      return `<strong style="color:#fbbf24; font-size:16px;">${td.totalDragPct}% / 年</strong><br/><span style="font-size:12.5px; color:#94a3b8;">${td.taxNote}</span>`;
    }],
    ["經常性純股利/票息實質殖利率 (提案004)", e => computeRecurringPureYield(e)],
    ["基金規模 (AUM) 與近1月變化", e => `<strong>${e.aum_value.toLocaleString()} ${e.aum_unit}</strong> (${e.aum_change_1m_pct >= 0 ? '+' : ''}${e.aum_change_1m_pct}%)`],
    ["買賣價差 (Spread) / 追蹤誤差", e => `價差 <strong>${e.bid_ask_spread_bps ?? '-'} bps</strong> ｜ 誤差 <strong>${e.tracking_error_pct ?? 'N/A'}%</strong>`],
    ["折溢價率 / 初級市場近期申贖", e => `折溢價 <strong>${fmtEtfPct(e.premium_discount_pct, true)}</strong><br/>淨申贖 <span class="${e.primary_net_flow_value>=0?'pos':'neg'}"><strong>${e.primary_net_flow_value === null || e.primary_net_flow_value === undefined ? 'N/A' : fmtEtfNum(e.primary_net_flow_value, true) + ' ' + e.aum_unit}</strong></span>`],
    ["前十大集中度 / 最大單一持股", e => `前十大 <strong>${e.top10_concentration_pct}%</strong><br/><span style="color:#fde68a;">最大：${e.max_single_holding_name}</span>`],
    ["前三大核心持股明細", e => (e.holdings || []).slice(0, 3).map(h => `${h.constituent_name} (${h.weight_pct}%)`).join('<br/>')],
    ["底層加權估值 (P/E、P/B) 與10月營收YoY", e => e.asset_class === '債券' ? `YTM <strong>${e.bond_ytm_pct}%</strong>｜存續期 <strong>${e.bond_duration_years}年</strong> (${e.bond_avg_credit_rating})` : `P/E <strong>${e.weighted_pe ?? 'N/A'}x</strong>｜P/B <strong>${e.weighted_pb ?? 'N/A'}x</strong><br/>10月營收YoY：<strong>${e.weighted_rev_yoy_pct !== null ? (e.weighted_rev_yoy_pct>=0?'+':'')+e.weighted_rev_yoy_pct+'%' : 'N/A'}</strong>`],
    ["配息殖利率與配息來源健康度", e => `${fmtEtfPct(e.dividend_yield_pct)} (${e.dividend_frequency})<br/>${e.dividend_breakdown ? `<span style="color:#34d399; font-size:13.5px;">股利/票息佔 ${e.dividend_breakdown.dividend_income_ratio_pct}%｜價差佔 ${e.dividend_breakdown.capital_gains_ratio_pct}%</span>` : '<span style="color:var(--text-secondary); font-size:13.5px;">純股利或零配息滾入</span>'}`],
    ["近1年 / 3年年化 / 5年年化含息報酬", e => `1Y: <strong>${fmtEtfPct(e.return_1y_total_pct, true)}</strong> (TWD: ${fmtEtfPct(e.twd_adjusted_1y_return_pct, true)})<br/>3Y: ${fmtEtfPct(e.return_3y_ann_pct)} ｜ 5Y: ${fmtEtfPct(e.return_5y_ann_pct)}`],
    ["年化波動度 / 最大回撤 / Beta", e => `波動 <strong>${fmtEtfPct(e.annualized_volatility_pct)}</strong>｜回撤 <span class="neg"><strong>${fmtEtfPct(e.max_drawdown_pct)}</strong></span>｜Beta ${fmtEtfNum(e.beta_vs_market)}`],
    ["與台股(0050) / 美股(VOO) / 美債(TLT) 相關性", e => `台股: ${fmtEtfNum(e.corr_tw_stock)} ｜ 美股: ${fmtEtfNum(e.corr_us_stock)} ｜ 美債: ${fmtEtfNum(e.corr_us_bond)}`],
    ["匯率曝險與稅務制度", e => `<div style="font-size:13.5px; max-width:250px;"><strong>${e.fx_hedged}</strong><br/>${e.tax_and_trading_notes}</div>`]
  ];

  document.getElementById('etfComparisonBody').innerHTML = rows.map(r => `
    <tr>
      <td style="font-weight:800; color:var(--accent-blue); white-space:nowrap;">${r[0]}</td>
      ${picked.map(e => `<td>${r[1](e)}</td>`).join('')}
    </tr>
  `).join('');

  const etfMobBox = document.getElementById('etfComparisonMobileCards');
  if (etfMobBox) {
    etfMobBox.innerHTML = rows.map(r => `
      <div class="etf-cmp-mob-card">
        <div class="etf-cmp-mob-title">${r[0]}</div>
        ${picked.map(e => `
          <div class="etf-cmp-mob-row">
            <div class="etf-cmp-mob-etf">[${e.listing_market}] ${e.etf_code} ${e.etf_name}</div>
            <div class="etf-cmp-mob-val">${r[1](e)}</div>
          </div>
        `).join('')}
      </div>
    `).join('');
  }
}

