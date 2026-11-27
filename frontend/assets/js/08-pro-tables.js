/* =========================================================================
   以下為模式 B / C 完整保留之專業資料表與互動治理函數 (零刪減)
   ========================================================================= */
function obsBadge(type) {
  if (type === 'DIRECT_STAT') return '<span class="badge badge-direct">直接官方統計</span>';
  if (type === 'PROXY_INDICATOR') return '<span class="badge badge-proxy">間接代理指標</span>';
  return '<span class="badge badge-grade-C">模型推估</span>';
}

function gradeBadge(g) {
  return `<span class="badge badge-grade-${g}">等級 ${g}</span>`;
}

function renderMacroCards() {
  const modFilter = document.getElementById('macroModuleFilter').value;
  const typeFilter = document.getElementById('macroTypeFilter').value;
  const container = document.getElementById('macroCardsContainer');
  const items = STATE.macro_latest.filter(item => {
    if (modFilter !== 'ALL' && item.module_id !== modFilter) return false;
    if (typeFilter !== 'ALL' && item.observation_type !== typeFilter) return false;
    return true;
  });

  container.innerHTML = items.map(item => {
    const momClass = item.mom_pct > 0 ? 'pos' : (item.mom_pct < 0 ? 'neg' : 'neu');
    const yoyClass = item.yoy_pct > 0 ? 'pos' : (item.yoy_pct < 0 ? 'neg' : 'neu');
    return `
      <div class="card">
        <div class="card-header">
          <div>
            <div style="font-size:11.5px; color:var(--accent-blue); font-weight:700;">[${item.module_id}] ${item.metric_code}</div>
            <div class="card-title">${item.metric_name}</div>
          </div>
          <div style="display:flex; flex-direction:column; gap:4px; align-items:flex-end;">
            ${gradeBadge(item.quality_grade)}
            ${obsBadge(item.observation_type)}
          </div>
        </div>
        <div style="font-size:24px; font-weight:800; color:#fff; margin:6px 0;">${item.cleaned_value.toLocaleString()} <span style="font-size:13px; font-weight:500; color:var(--text-secondary);">${item.unit}</span></div>
        <div style="font-size:12px; display:flex; gap:10px;">
          <span>前期：${item.prev_value !== null ? item.prev_value.toLocaleString() : 'N/A'}</span>
          <span class="${momClass}">期增：${item.mom_pct > 0 ? '+' : ''}${item.mom_pct}%</span>
          <span class="${yoyClass}">年增：${item.yoy_pct > 0 ? '+' : ''}${item.yoy_pct}%</span>
        </div>
        <p style="font-size:12px; color:#cbd5e1; margin-top:8px;">${item.notes}</p>
        <div style="font-size:11.5px; color:var(--text-secondary); margin-top:8px; border-top:1px solid rgba(255,255,255,0.06); padding-top:6px;">
          涵蓋期間：<strong>${item.period_covered}</strong> ｜ 發布日：<strong>${item.release_date}</strong><br/>
          來源：<a href="${item.source_url}" target="_blank" style="color:var(--accent-blue);">${item.publisher}</a> ｜ 版本：${item.revision_version}
        </div>
      </div>
    `;
  }).join('');
}

function renderAssetFlows() {
  const container = document.getElementById('assetFlowsContainer');
  const dirBadge = (d) => {
    if (d === 'CONFIRMED_INFLOW') return '<span class="badge badge-lvl4">已確認資金流入 (Confirmed Inflow)</span>';
    if (d === 'CONFIRMED_OUTFLOW') return '<span class="badge badge-lvlR">已確認資金流出 (Confirmed Outflow)</span>';
    return '<span class="badge badge-grade-C">結構位移與背離 (Structural Shift)</span>';
  };
  container.innerHTML = STATE.asset_flows.map(f => `
    <div class="card" style="margin-bottom:10px;">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
        <div style="font-size:15px; font-weight:700;">
          <span style="color:var(--accent-blue);">[資金來源] ${f.source_pool}</span>
          ➔ <span style="color:#fff;">[資產類別] ${f.asset_class}</span>
          ➔ <span style="color:var(--accent-emerald);">[標的細項] ${f.sub_category}</span>
        </div>
        <div style="display:flex; gap:6px; align-items:center;">
          ${dirBadge(f.flow_direction)}
          ${obsBadge(f.observation_type)}
          ${gradeBadge(f.quality_grade)}
        </div>
      </div>
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:12px; margin-bottom:8px;">
        <div><strong>最新規模數值：</strong> ${f.total_scale_value.toLocaleString()} ${f.scale_unit}</div>
        <div><strong>近期淨流量/變動指標：</strong> <span class="${f.net_flow_value >= 0 ? 'pos' : 'neg'}">${f.net_flow_value >= 0 ? '+' : ''}${f.net_flow_value.toLocaleString()}</span></div>
        <div><strong>涵蓋期間 / 發布日：</strong> ${f.period_covered} （發布日：${f.release_date}｜來源：${f.publisher}）</div>
      </div>
      <div class="evidence-box">
        <strong>統計口徑與範圍：</strong> ${f.statistical_scope}<br/>
        <strong>現況解析：</strong> ${f.notes}
      </div>
      <div class="evidence-box invalid">
        <strong>防重複計算強制機制 (Double-Counting Guard)：</strong> ${f.double_counting_guard}
      </div>
    </div>
  `).join('');
}

// 畫面目前顯示的產業清單 (依「排序基準」與「產業大類」篩選)；匯出功能也使用同一份，確保所見即所得
function getVisibleIndustries() {
  const sortKey = document.getElementById('rotationSortMode').value;
  const catFilter = document.getElementById('rotationCatFilter').value;
  const list = STATE.industries.filter(ind => catFilter === 'ALL' || ind.major_category === catFilter);
  list.sort((a, b) => {
    if (a.total_weighted_score === null && b.total_weighted_score === null) return 0;
    if (a.total_weighted_score === null) return 1;
    if (b.total_weighted_score === null) return -1;
    return (b[sortKey] || 0) - (a[sortKey] || 0);
  });
  return list;
}

function renderIndustryTable() {
  const tbody = document.getElementById('industryRotationBody');
  const list = getVisibleIndustries();

  let rankCounter = 1;
  tbody.innerHTML = list.map(ind => {
    const isUnratable = ind.total_weighted_score === null || ind.rotation_state === 'INSUFFICIENT_DATA';
    const rankDisplay = isUnratable
      ? '<span class="badge badge-unratable">不列入排名</span>'
      : `<strong style="font-size:16px; color:var(--accent-blue);">#${rankCounter++}</strong>`;

    const stateColor = {
      'A': 'badge-lvl4', 'B': 'badge-lvl3', 'C': 'badge-grade-C',
      'D': 'badge-lvlR', 'E': 'badge-lvlR', 'INSUFFICIENT_DATA': 'badge-unratable'
    }[ind.rotation_state] || 'badge-grade-C';

    const companiesHtml = ind.representative_companies.map(c =>
      `<span class="badge" style="background:#1e293b; color:#e2e8f0; margin:2px 2px 0 0;">${c.ticker} ${c.name}</span>`
    ).join('');

    return `
      <tr>
        <td>${rankDisplay}<div style="font-size:11px; color:var(--text-secondary); margin-top:4px;">${ind.major_category}</div></td>
        <td style="min-width:170px;">
          <div style="font-weight:700; font-size:14px; color:#fff;">${ind.industry_name}</div>
          <div style="font-size:11.5px; color:var(--text-secondary); margin:3px 0;">${ind.sub_sectors}</div>
          <div>${companiesHtml}</div>
        </td>
        <td style="min-width:135px;">
          <div><span class="badge ${stateColor}">狀態 ${ind.rotation_state}</span></div>
          <div style="font-size:12px; font-weight:600; color:#fde68a; margin-top:5px;">轉折：${ind.transition_tag}</div>
          <div style="font-size:12px; color:var(--text-secondary); margin-top:3px;">景氣循環：<strong>${ind.cycle_stage}</strong></div>
        </td>
        <td style="min-width:95px;">
          ${isUnratable
            ? `<span class="badge badge-unratable">不可評分</span>`
            : `<div style="font-size:22px; font-weight:800; color:var(--accent-emerald);">${ind.total_weighted_score.toFixed(2)}</div>`
          }
          <div style="font-size:11.5px; color:var(--text-secondary);">信心：${ind.confidence_level}</div>
          <div style="font-size:11.5px; color:${ind.missing_data_pct > 20 ? '#fb7185' : '#94a3b8'};">缺失率：${ind.missing_data_pct}%</div>
        </td>
        <td style="min-width:120px; font-size:12px;">
          ${isUnratable ? '資料異質/缺失超標，依規不予補分' : `
            資金流向：<strong>${ind.score_capital_flow}</strong><br/>
            基本面：<strong>${ind.score_fundamentals}</strong><br/>
            未來成長：<strong>${ind.score_future_growth}</strong><br/>
            法人布局：<strong>${ind.score_institutional}</strong><br/>
            估值合理：<strong>${ind.score_valuation}</strong>
          `}
        </td>
        <td style="min-width:105px; font-size:12px;">
          ${isUnratable ? '-' : `
            短期動能：<strong>${ind.short_term_momentum_score}</strong><br/>
            中期基本：<strong>${ind.mid_term_fundamental_score}</strong><br/>
            長期結構：<strong>${ind.long_term_structural_score}</strong>
          `}
        </td>
        <td style="min-width:180px; font-size:12px;">
          20日相對大盤：<span class="${ind.rel_strength_20d >= 0 ? 'pos' : 'neg'}">${ind.rel_strength_20d >= 0 ? '+' : ''}${ind.rel_strength_20d}%</span><br/>
          60日相對大盤：<span class="${ind.rel_strength_60d >= 0 ? 'pos' : 'neg'}">${ind.rel_strength_60d >= 0 ? '+' : ''}${ind.rel_strength_60d}%</span><br/>
          代表廠10月YoY：<span class="${ind.rev_yoy_pct >= 0 ? 'pos' : 'neg'}"><strong>${ind.rev_yoy_pct >= 0 ? '+' : ''}${ind.rev_yoy_pct}%</strong></span><br/>
          ${ind.live_agg && ind.live_agg.company_count ? `
            <div style="margin-top:4px; padding-top:4px; border-top:1px dashed #334155; font-size:11px; color:#38bdf8;">
              <strong>[MOPS全市場${ind.live_agg.company_count}家匯總]</strong><br/>
              10月總營收：${ind.live_agg.ind_rev_billion.toLocaleString()}億 (${ind.live_agg.agg_yoy_pct >= 0 ? '+' : ''}${ind.live_agg.agg_yoy_pct}%)<br/>
              平均P/E：${ind.live_agg.avg_pe || '-'}x ｜ P/B：${ind.live_agg.avg_pb || '-'}x
            </div>
          ` : ''}
        </td>
        <td style="min-width:190px; max-width:360px;">
          <details class="evi-details">
            <summary>查看支持／反方證據與失效條件</summary>
            <div class="evidence-box"><strong>支持證據：</strong>${ind.supporting_evidence}</div>
            <div class="evidence-box counter"><strong>反方證據：</strong>${ind.counter_evidence}</div>
            <div class="evidence-box invalid"><strong>失效條件：</strong>${ind.invalidation_conditions}<br/><strong>資料限制：</strong>${ind.data_limitations}</div>
          </details>
        </td>
      </tr>
    `;
  }).join('');

  const mobContainer = document.getElementById('industryRotationMobileCards');
  if (mobContainer) {
    let mobRank = 1;
    mobContainer.innerHTML = list.map(ind => {
      const isUnratable = ind.total_weighted_score === null || ind.rotation_state === 'INSUFFICIENT_DATA';
      const rankDisplay = isUnratable
        ? '<span class="badge badge-unratable">不列入排名</span>'
        : `<strong style="font-size:15px; color:var(--accent-blue);">#${mobRank++}</strong>`;
      const stateColor = {
        'A': 'badge-lvl4', 'B': 'badge-lvl3', 'C': 'badge-grade-C',
        'D': 'badge-lvlR', 'E': 'badge-lvlR', 'INSUFFICIENT_DATA': 'badge-unratable'
      }[ind.rotation_state] || 'badge-grade-C';
      const companiesHtml = ind.representative_companies.map(c =>
        `<span class="badge" style="background:#1e293b; color:#e2e8f0; margin:2px 4px 2px 0;">${c.ticker} ${c.name}</span>`
      ).join('');
      return `
        <div class="pro-rot-mob-card">
          <div class="pro-rot-mob-head">
            <div>
              <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-bottom:4px;">
                ${rankDisplay}
                <span class="badge" style="background:#1e293b; color:#cbd5e1;">${ind.major_category}</span>
                <span class="badge ${stateColor}">狀態 ${ind.rotation_state}</span>
              </div>
              <div style="font-weight:800; font-size:15px; color:#fff;">${ind.industry_name}</div>
              <div style="font-size:12px; color:#fde68a; margin-top:2px;">轉折：${ind.transition_tag} ｜ ${ind.cycle_stage}</div>
            </div>
            <div style="text-align:right; flex-shrink:0;">
              ${isUnratable
                ? `<span class="badge badge-unratable">不可評分</span>`
                : `<div style="font-size:21px; font-weight:800; color:var(--accent-emerald); line-height:1.1;">${ind.total_weighted_score.toFixed(2)}</div>`
              }
              <div style="font-size:11px; color:var(--text-secondary); margin-top:3px;">信心 ${ind.confidence_level}</div>
              <div style="font-size:11px; color:${ind.missing_data_pct > 20 ? '#fb7185' : '#94a3b8'};">缺失 ${ind.missing_data_pct}%</div>
            </div>
          </div>
          <div class="pro-rot-mob-kpis">
            <div>20日強弱：<span class="${ind.rel_strength_20d >= 0 ? 'pos' : 'neg'}"><strong>${ind.rel_strength_20d >= 0 ? '+' : ''}${ind.rel_strength_20d}%</strong></span></div>
            <div>60日強弱：<span class="${ind.rel_strength_60d >= 0 ? 'pos' : 'neg'}"><strong>${ind.rel_strength_60d >= 0 ? '+' : ''}${ind.rel_strength_60d}%</strong></span></div>
            <div>10月YoY：<span class="${ind.rev_yoy_pct >= 0 ? 'pos' : 'neg'}"><strong>${ind.rev_yoy_pct >= 0 ? '+' : ''}${ind.rev_yoy_pct}%</strong></span></div>
          </div>
          <details class="pro-rot-mob-details">
            <summary><span>展開五維明細、代表廠與研究證據</span><span>▾</span></summary>
            <div style="font-size:12.5px; color:#cbd5e1; line-height:1.6;">
              <div style="margin-bottom:6px;">${companiesHtml}</div>
              ${isUnratable ? '<div style="margin-bottom:6px;">資料異質/缺失超標，依規不予補分</div>' : `
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px 8px; padding:8px; background:rgba(9,14,26,0.65); border-radius:8px; margin-bottom:8px;">
                  <div>資金流向：<strong>${ind.score_capital_flow}</strong></div>
                  <div>基本面：<strong>${ind.score_fundamentals}</strong></div>
                  <div>未來成長：<strong>${ind.score_future_growth}</strong></div>
                  <div>法人布局：<strong>${ind.score_institutional}</strong></div>
                  <div>估值合理：<strong>${ind.score_valuation}</strong></div>
                  <div>短/中/長：<strong>${ind.short_term_momentum_score}/${ind.mid_term_fundamental_score}/${ind.long_term_structural_score}</strong></div>
                </div>
              `}
              ${ind.live_agg && ind.live_agg.company_count ? `
                <div style="padding:6px 8px; border-radius:6px; background:rgba(56,189,248,0.08); border:1px dashed #334155; color:#38bdf8; margin-bottom:8px; font-size:12px;">
                  <strong>[MOPS全市場${ind.live_agg.company_count}家匯總]</strong> 10月總營收 ${ind.live_agg.ind_rev_billion.toLocaleString()}億 (${ind.live_agg.agg_yoy_pct >= 0 ? '+' : ''}${ind.live_agg.agg_yoy_pct}%) ｜ P/E ${ind.live_agg.avg_pe || '-'}x ｜ P/B ${ind.live_agg.avg_pb || '-'}x
                </div>
              ` : ''}
              <div class="evidence-box" style="margin-bottom:6px;"><strong>支持證據：</strong>${ind.supporting_evidence}</div>
              <div class="evidence-box counter" style="margin-bottom:6px;"><strong>反方證據：</strong>${ind.counter_evidence}</div>
              <div class="evidence-box invalid"><strong>失效條件：</strong>${ind.invalidation_conditions}<br/><strong>資料限制：</strong>${ind.data_limitations}</div>
            </div>
          </details>
        </div>
      `;
    }).join('');
  }
}

async function submitNewWeights() {
  const payload = {
    capital_flow: parseFloat(document.getElementById('w_cap').value) / 100,
    fundamentals: parseFloat(document.getElementById('w_fun').value) / 100,
    future_growth: parseFloat(document.getElementById('w_gro').value) / 100,
    institutional: parseFloat(document.getElementById('w_ins').value) / 100,
    valuation: parseFloat(document.getElementById('w_val').value) / 100,
    reason: document.getElementById('w_reason').value
  };
  const msgEl = document.getElementById('weightStatusMsg');
  const res = await apiPost('/api/rescore', payload);
  const data = await res.json();
  if (data.status === 'ok') {
    STATE = data.dashboard;
    renderAll();
    msgEl.style.color = '#34d399';
    msgEl.textContent = `已成功儲存新模型版本 ${data.new_version} 並同步更新熱度圖與全產業排名！`;
  } else {
    msgEl.style.color = '#fb7185';
    msgEl.textContent = `錯誤：${data.message}`;
  }
}

function renderInstiFlows() {
  if (!STATE.institutional_flows) return;
  const pFilter = document.getElementById('instiPeriodFilter').value;
  const tbody = document.getElementById('instiFlowsBody');
  const list = STATE.institutional_flows.filter(r => pFilter === 'ALL' || r.period_type === pFilter);
  const fmtVal = (v) => `<span class="${v >= 0 ? 'pos' : 'neg'}"><strong>${v >= 0 ? '+' : ''}${v.toLocaleString()}</strong></span>`;
  tbody.innerHTML = list.map(r => `
    <tr>
      <td><span class="badge badge-grade-B">${r.period_type}</span></td>
      <td><strong>${r.period_label}</strong><div style="font-size:11px; color:var(--text-secondary);">發布：${r.release_date}</div></td>
      <td>${fmtVal(r.foreign_net_billion)}</td>
      <td>${fmtVal(r.itc_net_billion)}</td>
      <td>${fmtVal(r.dealer_prop_billion)}</td>
      <td>${fmtVal(r.dealer_hedge_billion)}</td>
      <td>${fmtVal(r.total_3insti_billion)}</td>
      <td class="neg"><strong>${r.foreign_futures_oi_contracts == null ? '—' : r.foreign_futures_oi_contracts.toLocaleString() + ' 口'}</strong></td>
      <td>${r.margin_balance_billion == null ? '—' : r.margin_balance_billion.toLocaleString() + ' 億'}</td>
      <td style="min-width:300px; font-size:12px;">
        <div><strong style="color:#34d399;">主要買超：</strong>${r.top_buy_industries}</div>
        <div><strong style="color:#fb7185;">主要賣超：</strong>${r.top_sell_industries}</div>
        <div style="color:var(--text-secondary); margin-top:3px;">${r.notes}</div>
      </td>
    </tr>
  `).join('');
}

function renderWarnings() {
  const lvl = document.getElementById('warningLevelFilter').value;
  const container = document.getElementById('warningsContainer');
  const list = STATE.warnings.filter(w => lvl === 'ALL' || w.alert_level === lvl);
  // 說明文字的來源：即時評分自動產生 / 2026-11-22 前後手寫 (沒有即時資料的舊快照)
  const liveCount = STATE.warnings.filter(w => w.text_source === 'live').length;
  let srcNote = document.getElementById('warningsSourceNote');
  if (!srcNote) {
    srcNote = document.createElement('div');
    srcNote.id = 'warningsSourceNote';
    srcNote.style.cssText = 'font-size:12.5px; margin:4px 2px 12px; color:var(--text-muted);';
    container.parentNode.insertBefore(srcNote, container);
  }
  srcNote.textContent = liveCount
    ? `✅ ${liveCount} 則預警的等級與說明文字由官方即時資料自動產生（機械式規則，非分析師撰寫；每個交易日收盤後重算）。`
    : '⚠️ 此快照的預警說明為 2026-11-22 前後手寫的文字，不會隨資料更新。';
  const lvlBadge = (l) => {
    if (l === 'LEVEL 4') return '<span class="badge badge-lvl4">LEVEL 4｜趨勢明確（須檢視估值與擁擠度）</span>';
    if (l === 'LEVEL 3') return '<span class="badge badge-lvl3">LEVEL 3｜資金與基本面同時轉強</span>';
    if (l === 'LEVEL 2') return '<span class="badge badge-lvl2">LEVEL 2｜多項指標改善 / 市場尚未充分反映</span>';
    if (l === 'LEVEL 1') return '<span class="badge badge-grade-C">LEVEL 1｜初步觀察</span>';
    return '<span class="badge badge-lvlR">LEVEL R｜資金撤退或基本面惡化風險警示</span>';
  };
  container.innerHTML = list.map(w => `
    <div class="card" style="margin-bottom: 14px;">
      <div class="card-header">
        <div>
          ${lvlBadge(w.alert_level)}
          <span style="font-size:16px; font-weight:700; margin-left:8px;">${esc(w.industry_name)}</span>
          <span style="font-size:12px; color:var(--accent-blue); margin-left:8px;">[${esc(w.signal_category)}｜期間：${esc(w.horizon)}]</span>
        </div>
        <div style="font-size:12px; color:var(--text-secondary);">
          可信度：<strong>${esc(w.credibility_grade)}</strong> ｜ 觸發時間：${esc(w.triggered_at)}
        </div>
      </div>
      <div class="evidence-box">
        <strong>觸發原因：</strong> ${esc(w.trigger_reason)}<br/>
        <strong>原始數據證據：</strong> ${esc(w.raw_data_evidence)} （來源：${esc(w.publisher)}）
      </div>
      <div class="evidence-box counter">
        <strong>反方證據：</strong> ${esc(w.counter_evidence)}
      </div>
      <div class="evidence-box invalid">
        <strong>結論失效條件：</strong> ${esc(w.invalidation_conditions)}<br/>
        <strong>缺失資料與統計限制：</strong> ${esc(w.missing_data_notes)}
      </div>
    </div>
  `).join('');
}

function renderCompanies() {
  const cat = document.getElementById('companyCatFilter').value;
  const container = document.getElementById('companiesContainer');
  const list = STATE.companies.filter(c => cat === 'ALL' || c.watchlist_category === cat);
  const catBadge = (c) => {
    if (c === '優先研究') return '<span class="badge badge-lvl4">優先研究</span>';
    if (c === '中長期觀察') return '<span class="badge badge-lvl3">中長期觀察</span>';
    if (c === '等待估值合理') return '<span class="badge badge-grade-C">等待估值合理</span>';
    return '<span class="badge badge-lvlR">基本面或風險不佳</span>';
  };
  container.innerHTML = list.map(c => `
    <div class="card">
      <div class="card-header">
        <div>
          <span style="font-size:17px; font-weight:800; color:#fff;">${c.ticker} ${c.company_name}</span>
          <span style="font-size:12px; color:var(--accent-blue); margin-left:6px;">(${c.industry_name})</span>
          <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">供應鏈位置：${c.supply_chain_position}</div>
        </div>
        ${catBadge(c.watchlist_category)}
      </div>
      <div style="display:flex; gap:14px; flex-wrap:wrap; font-size:12.5px; background:#090e1a; padding:8px 12px; border-radius:5px; margin-bottom:8px;">
        <div><strong>${c.latest_rev_period} 營收：</strong>${c.latest_rev_billion_twd.toLocaleString()} 億元</div>
        <div><strong>月增(MoM)：</strong><span class="${c.rev_mom_pct >= 0 ? 'pos' : 'neg'}">${c.rev_mom_pct >= 0 ? '+' : ''}${c.rev_mom_pct}%</span></div>
        <div><strong>年增(YoY)：</strong><span class="${c.rev_yoy_pct >= 0 ? 'pos' : 'neg'}"><strong>${c.rev_yoy_pct >= 0 ? '+' : ''}${c.rev_yoy_pct}%</strong></span></div>
        <div><strong>估值狀態：</strong>${c.pe_ratio_status}</div>
      </div>
      <div style="font-size:12px; color:#cbd5e1; margin-bottom:6px;"><strong>法人持股動向：</strong>${c.institutional_ownership_trend}</div>
      <div class="evidence-box"><strong>支持理由 (Bull Case)：</strong>${c.bull_case}</div>
      <div class="evidence-box counter"><strong>反對理由 (Bear Case)：</strong>${c.bear_case}</div>
      <div class="evidence-box invalid">
        <strong>估值風險：</strong>${c.valuation_risk}<br/>
        <strong>結論失效條件：</strong>${c.invalidation_condition}
      </div>
      <div style="font-size:11.5px; color:var(--text-secondary); margin-top:8px;">資料基準日：${c.as_of_date} ｜ 來源：${c.publisher}</div>
    </div>
  `).join('');
  renderLiveTopCompanies();
}

function renderLiveTopCompanies() {
  if (!STATE.live_summary || !STATE.live_top_companies) return;
  const s = STATE.live_summary;
  document.getElementById('liveSummaryBanner').innerHTML =
    `已由官方 OpenAPI 實時入庫：共 <strong>${s.total_companies.toLocaleString()} 家上市櫃公司</strong>（上市 ${s.twse_count} 家 ＋ 上櫃 ${s.tpex_count} 家）｜ 115年10月(2026-10) 全體上市櫃單月合計總營收：<strong>${s.total_rev_trillion} 兆元</strong>（去年同月 ${s.ly_rev_trillion} 兆元，實測年增率 <strong class="pos">+${s.total_yoy_pct}%</strong>）`;

  const q = (document.getElementById('liveCompanySearch').value || '').trim().toLowerCase();
  const list = STATE.live_top_companies.filter(r => {
    if (!q) return true;
    return r.company_code.toLowerCase().includes(q) ||
           r.company_name.toLowerCase().includes(q) ||
           r.official_industry.toLowerCase().includes(q) ||
           (r.mapped_industry_id || '').toLowerCase().includes(q);
  });

  document.getElementById('liveTopCompaniesBody').innerHTML = list.map(r => `
    <tr>
      <td><strong style="color:#fff;">${r.company_code} ${r.company_name}</strong></td>
      <td><span class="badge ${r.market_type === 'TWSE' ? 'badge-grade-A' : 'badge-grade-B'}">${r.market_type}</span> ${r.official_industry}</td>
      <td style="font-size:11.5px; color:var(--accent-blue);">${r.mapped_industry_id}</td>
      <td><strong>${(r.rev_billion || 0).toLocaleString()} 億</strong></td>
      <td class="${(r.rev_mom_pct || 0) >= 0 ? 'pos' : 'neg'}">${(r.rev_mom_pct || 0) >= 0 ? '+' : ''}${r.rev_mom_pct ?? '-'}%</td>
      <td class="${(r.rev_yoy_pct || 0) >= 0 ? 'pos' : 'neg'}"><strong>${(r.rev_yoy_pct || 0) >= 0 ? '+' : ''}${r.rev_yoy_pct ?? '-'}%</strong></td>
      <td class="${(r.cum_rev_yoy_pct || 0) >= 0 ? 'pos' : 'neg'}">${(r.cum_rev_yoy_pct || 0) >= 0 ? '+' : ''}${r.cum_rev_yoy_pct ?? '-'}%</td>
      <td>P/E: <strong>${r.pe_ratio ?? 'N/A'}</strong><br/>P/B: ${r.pb_ratio ?? 'N/A'}</td>
      <td>${r.dividend_yield ?? '-'}%</td>
      <td style="font-size:11.5px;">
        外資: <span class="${(r.foreign_net_shares || 0) >= 0 ? 'pos' : 'neg'}">${(r.foreign_net_shares || 0).toLocaleString()}</span><br/>
        投信: <span class="${(r.itc_net_shares || 0) >= 0 ? 'pos' : 'neg'}">${(r.itc_net_shares || 0).toLocaleString()}</span> ｜ 自營: ${(r.dealer_net_shares || 0).toLocaleString()}
      </td>
    </tr>
  `).join('');
}

async function submitNewThresholds() {
  const payload = {
    action_type: 'THRESHOLDS',
    lvl4_min: parseFloat(document.getElementById('th_lvl4').value),
    lvl3_min: parseFloat(document.getElementById('th_lvl3').value),
    lvl2_min: parseFloat(document.getElementById('th_lvl2').value),
    lvlR_cap_max: parseFloat(document.getElementById('th_lvlR').value),
    reason: document.getElementById('th_reason').value
  };
  const res = await apiPost('/api/update_governance', payload);
  const data = await res.json();
  if (data.status === 'ok') {
    STATE = data.dashboard;
    renderAll();
    document.getElementById('thStatusMsg').textContent = '預警門檻已成功更新並寫入SQLite！';
  } else {
    document.getElementById('thStatusMsg').textContent = `錯誤：${data.message || res.status}`;
  }
}

async function submitCompanyRemap() {
  const code = document.getElementById('remap_code').value.trim();
  const ind = document.getElementById('remap_ind').value;
  if (!code) { alert('請輸入公司代號'); return; }
  const res = await apiPost('/api/update_governance', { action_type: 'COMPANY_MAPPING', company_code: code, mapped_industry_id: ind });
  const data = await res.json();
  if (data.status === 'ok') {
    STATE = data.dashboard;
    renderAll();
    alert(`已成功將公司 ${code} 歸屬調整至 ${ind} 並重新計算產業匯總！`);
  } else {
    alert(`錯誤：${data.message || res.status}`);
  }
}

function renderScenarios() {
  const container = document.getElementById('scenariosContainer');
  container.innerHTML = STATE.scenarios.map(s => `
    <div class="card">
      <div class="card-header">
        <div class="card-title">${s.scenario_name}</div>
        <span class="badge badge-grade-B">參考權重：${s.probability_weight}</span>
      </div>
      <div class="evidence-box" style="white-space:pre-line;"><strong>成立條件：</strong>\n${s.trigger_conditions}</div>
      <div style="font-size:12px; margin-top:8px;"><strong>核心觀察指標：</strong>${s.monitoring_indicators}</div>
      <div style="font-size:12px; margin-top:6px; color:#34d399;"><strong>可能受惠產業：</strong>${s.beneficiary_industries}</div>
      <div style="font-size:12px; margin-top:6px; color:#fb7185;"><strong>脆弱/受損產業：</strong>${s.vulnerable_industries}</div>
      <div style="font-size:12px; margin-top:6px;"><strong>資金可能流向：</strong>${s.capital_flow_direction}</div>
      <div class="evidence-box counter"><strong>反證：</strong>${s.counter_evidence}</div>
      <div class="evidence-box invalid"><strong>失效條件：</strong>${s.invalidation_conditions}</div>
    </div>
  `).join('');
}

function renderReports() {
  if (!STATE.research_reports) return;
  const freq = document.getElementById('reportFreqFilter').value;
  const container = document.getElementById('reportsContainer');
  const list = STATE.research_reports.filter(r => freq === 'ALL' || r.frequency === freq);
  container.innerHTML = list.map(r => {
    const sectionsHtml = (r.key_findings || []).map(sec => `
      <div style="margin-top:8px; background:#090e1a; padding:10px 12px; border-radius:5px; white-space:pre-line;">
        <strong style="color:var(--accent-blue);">${sec.section}</strong><br/>
        <span style="font-size:12.5px; color:#e2e8f0;">${sec.content}</span>
      </div>
    `).join('');
    return `
      <div class="card" style="margin-bottom: 16px;">
        <div class="card-header">
          <div>
            <span class="badge badge-lvl3">${r.frequency}固定報告</span>
            <span style="font-size:16px; font-weight:800; color:#fff; margin-left:8px;">${r.report_title}</span>
          </div>
          <span class="badge badge-grade-A">${r.version_tag}｜${r.update_status}</span>
        </div>
        <div style="font-size:12px; color:var(--text-secondary); margin-bottom:8px;">
          資料截止基準日：<strong>${r.as_of_cutoff_date}</strong> ｜ 主要官方來源：${r.primary_sources}
        </div>
        <div class="evidence-box" style="font-size:13px;"><strong>執行摘要 (Executive Summary)：</strong>${r.executive_summary}</div>
        ${sectionsHtml}
        <div class="evidence-box counter" style="margin-top:8px;"><strong>反方證據：</strong>${r.counter_evidence}</div>
        <div class="evidence-box invalid">
          <strong>分析假設與資料限制：</strong>${r.assumptions_and_limits}<br/>
          <strong>需持續追蹤之驗證指標：</strong>${r.tracking_indicators}
        </div>
      </div>
    `;
  }).join('');
}

function renderBacktest() {
  if (!STATE.backtest_runs || !STATE.backtest_runs.length) return;
  const bt = STATE.backtest_runs[0];
  document.getElementById('backtestSummaryContainer').innerHTML = `
    <div class="card" style="border-left: 4px solid var(--accent-emerald); margin-bottom: 16px;">
      <div class="card-header">
        <div>
          <div class="card-title" style="font-size:16px;">第五階段：時間序列滾動樣本外回測與三大基準模型對照 (${bt.run_id})</div>
          <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">回測區間：${bt.backtest_window} ｜ 模型版本：${bt.model_version} ｜ 單邊交易摩擦成本假設：${bt.cost_assumption_bps} bps</div>
        </div>
        <span class="badge badge-lvlR">示範數據 (非實測)</span>
      </div>
      <div class="grid-4" style="margin-top:12px; margin-bottom:12px;">
        <div style="background:#090e1a; padding:12px; border-radius:6px;">
          <div style="font-size:12px; color:var(--text-secondary);">預警命中率 / 誤報率 / 漏報率</div>
          <div style="font-size:22px; font-weight:800; color:#34d399; margin:4px 0;">命中 ${bt.hit_rate_pct}%</div>
          <div style="font-size:12px;">誤報率：<span class="neu">${bt.false_positive_pct}%</span> ｜ 漏報率：<span class="neg">${bt.false_negative_pct}%</span> (N=${bt.sample_count})</div>
        </div>
        <div style="background:#090e1a; padding:12px; border-radius:6px;">
          <div style="font-size:12px; color:var(--text-secondary);">平均提前預警天數 (Lead Time)</div>
          <div style="font-size:22px; font-weight:800; color:var(--accent-blue); margin:4px 0;">提前 ${bt.avg_lead_time_days} 天</div>
          <div style="font-size:12px; color:var(--text-secondary);">領先市場主升段或主跌段約 1.1 個月</div>
        </div>
        <div style="background:#090e1a; padding:12px; border-radius:6px;">
          <div style="font-size:12px; color:var(--text-secondary);">LEVEL 3/4 輪動超額報酬 (扣成本)</div>
          <div style="font-size:22px; font-weight:800; color:#34d399; margin:4px 0;">+${bt.model_cum_excess_return_pct}% (超額)</div>
          <div style="font-size:12px;">優於等權重(+${bt.benchmark_equal_weight_pct}%)及20日動能(+${bt.benchmark_naive_mom_pct}%)</div>
        </div>
        <div style="background:#090e1a; padding:12px; border-radius:6px;">
          <div style="font-size:12px; color:var(--text-secondary);">LEVEL R 風險預警規避回撤</div>
          <div style="font-size:22px; font-weight:800; color:#fb7185; margin:4px 0;">${bt.level_r_avoided_drawdown_pct}%</div>
          <div style="font-size:12px; color:var(--text-secondary);">成功提前規避營建與傳統塑化鋼鐵弱勢</div>
        </div>
      </div>
      <div class="evidence-box">
        <strong>時間序列切分方法：</strong>${bt.split_method}<br/>
        <strong>防止未來資料洩漏 (Look-Ahead Guard)：</strong>${bt.lookahead_guard}<br/>
        <strong>防止存活者偏差 (Survivorship Guard)：</strong>${bt.survivorship_guard}
      </div>
      <div class="evidence-box invalid">
        <strong>不同市場環境穩定性：</strong>${bt.regime_stability_notes}<br/>
        <strong>回測限制與免責聲明：</strong>${bt.model_limitations}
      </div>
    </div>
  `;

  const outcomeBadge = (c) => {
    if (c === 'TRUE_POSITIVE_HIT') return '<span class="badge badge-lvl4">正向命中 (True Positive)</span>';
    if (c === 'RISK_AVOIDED_HIT') return '<span class="badge badge-lvl3">成功避險 (Risk Avoided)</span>';
    return '<span class="badge badge-lvlR">誤報檢討 (False Positive)</span>';
  };

  document.getElementById('backtestEventsBody').innerHTML = (STATE.backtest_events || []).map(e => `
    <tr>
      <td><strong>${e.event_id}</strong><br/><span style="color:var(--accent-blue);">${e.signal_date}</span></td>
      <td><strong>${e.industry_name}</strong><br/><span style="font-size:11px; color:var(--text-secondary);">${e.major_category}</span></td>
      <td><span class="badge ${e.alert_level === 'LEVEL R' ? 'badge-lvlR' : 'badge-lvl4'}">${e.alert_level}</span></td>
      <td style="max-width:340px; font-size:12px;">${e.trigger_metrics_pit}</td>
      <td class="${e.forward_3m_rel_return_pct >= 0 ? 'pos' : 'neg'}"><strong>${e.forward_3m_rel_return_pct >= 0 ? '+' : ''}${e.forward_3m_rel_return_pct}%</strong></td>
      <td class="${e.forward_6m_rel_return_pct >= 0 ? 'pos' : 'neg'}"><strong>${e.forward_6m_rel_return_pct >= 0 ? '+' : ''}${e.forward_6m_rel_return_pct}%</strong></td>
      <td><strong>${e.lead_time_days} 天</strong></td>
      <td style="min-width:260px; font-size:12px;">
        ${outcomeBadge(e.outcome_classification)}
        <div style="margin-top:4px; color:#cbd5e1;">${e.review_notes}</div>
      </td>
    </tr>
  `).join('');
}

function renderGovernance() {
  if (STATE.dq_checks) {
    const stBadge = (s) => {
      if (s === 'PASS') return '<span class="badge badge-lvl4">PASS (正常)</span>';
      if (s === 'WARNING') return '<span class="badge badge-grade-C">WARNING (提醒/防呆生效)</span>';
      return '<span class="badge badge-lvlR">CRITICAL_ALERT (跨市場異常波動)</span>';
    };
    document.getElementById('dqChecksBody').innerHTML = STATE.dq_checks.map(c => `
      <tr>
        <td><strong>${c.check_id}</strong></td>
        <td><span class="badge badge-grade-B">${c.check_type}</span></td>
        <td><strong>${c.target_table_or_metric}</strong></td>
        <td>${stBadge(c.status)}</td>
        <td style="font-size:12px;">${c.expected_sla_or_bound}</td>
        <td style="font-size:12px;"><strong>${c.observed_value}</strong></td>
        <td style="font-size:12px; color:#cbd5e1;">${c.action_taken}</td>
      </tr>
    `).join('');
  }

  document.getElementById('modelVersionsBody').innerHTML = STATE.model_versions.map(v => {
    const w = JSON.parse(v.weights_json);
    return `
      <tr>
        <td><strong>${v.version_id}</strong></td>
        <td>${v.created_at}</td>
        <td>資${Math.round(w.capital_flow*100)}% / 基${Math.round(w.fundamentals*100)}% / 成${Math.round(w.future_growth*100)}% / 法${Math.round(w.institutional*100)}% / 估${Math.round(w.valuation*100)}%</td>
        <td>${esc(v.change_reason)}</td>
        <td>${v.active ? '<span class="badge badge-lvl4">啟用中</span>' : '<span class="badge badge-unratable">歷史版本</span>'}</td>
      </tr>
    `;
  }).join('');

  document.getElementById('auditLogsBody').innerHTML = STATE.audit_logs.map(l => `
    <tr>
      <td style="white-space:nowrap;">${l.run_timestamp}</td>
      <td><strong>${l.task_name}</strong></td>
      <td>${l.source_id}</td>
      <td><span class="badge ${l.status === 'SUCCESS' ? 'badge-lvl4' : 'badge-grade-C'}">${l.status}</span></td>
      <td>${esc(l.message)}</td>
    </tr>
  `).join('');

  document.getElementById('sourcesBody').innerHTML = STATE.sources.map(s => `
    <tr>
      <td><strong>${s.source_id}</strong><br/>${s.source_name}</td>
      <td>${s.category}<br/><span style="color:var(--text-secondary);">${s.publisher}</span></td>
      <td>${gradeBadge(s.quality_grade)}</td>
      <td>${s.access_method}<br/><a href="${s.source_url}" target="_blank" style="color:var(--accent-blue); font-size:11.5px;">${s.source_url}</a></td>
      <td>${s.update_frequency}<br/><span style="color:#fde68a;">延遲約 ${s.publication_lag_days} 天</span></td>
      <td>${s.cost_tier}<br/><span style="font-size:11.5px; color:var(--text-secondary);">${s.license_terms}</span></td>
      <td>${s.fallback_strategy}</td>
    </tr>
  `).join('');

  document.getElementById('dictionaryBody').innerHTML = STATE.dictionary.map(d => `
    <tr>
      <td><strong>${d.metric_code}</strong></td>
      <td>${d.metric_name}</td>
      <td>${d.module_id}</td>
      <td>${obsBadge(d.observation_type)}</td>
      <td>${d.unit} / ${d.currency} / ${d.seasonal_adjustment}</td>
      <td>${d.statistical_scope}</td>
      <td>${d.calculation_method}<br/><span style="color:var(--accent-orange); font-size:11px;">缺漏處理：${d.missing_value_policy}</span></td>
    </tr>
  `).join('');
}

