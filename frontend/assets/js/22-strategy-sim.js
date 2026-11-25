/* =========================================================================
   規則模擬器：兩個固定規則 (前 3 名輪動、持有 LEVEL 3/4) vs 兩個基準 (加權報酬指數、全部產業等權重)
   資料由後端 strategy_sim.compute_strategy_sim() 產生 (STATE.strategy_sim)，全部由資料庫計算。
   規則與參數固定、畫面不提供調整，避免看到結果後反覆調參數造成過度擬合。
   ========================================================================= */
const STRATEGY_COLORS = { top_n: '#38bdf8', alert: '#a78bfa', equal: '#fbbf24', bench: '#9aabc6' };

function strategyLineChart(curve) {
  if (!curve || !curve.dates.length) return '';
  const W = 900, H = 260, PL = 46, PR = 12, PT = 12, PB = 26;
  const keys = ['top_n', 'alert', 'equal', 'bench'];
  const all = keys.flatMap(k => curve.series[k]).filter(v => Number.isFinite(v));
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1) { lo -= 0.5; hi += 0.5; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const n = curve.dates.length;
  const x = i => PL + (n === 1 ? 0 : i * (W - PL - PR) / (n - 1));
  const y = v => PT + (hi - v) * (H - PT - PB) / (hi - lo);
  const grid = [0, 1, 2, 3, 4].map(t => {
    const v = lo + (hi - lo) * t / 4;
    return `<line x1="${PL}" x2="${W - PR}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(255,255,255,.08)"/>
            <text x="${PL - 6}" y="${y(v) + 4}" font-size="11" fill="#9aabc6" text-anchor="end">${v.toFixed(1)}</text>`;
  }).join('');
  const lines = keys.map(k => {
    const pts = curve.series[k].map((v, i) => Number.isFinite(v) ? `${x(i).toFixed(1)},${y(v).toFixed(1)}` : null).filter(Boolean).join(' ');
    return `<polyline points="${pts}" fill="none" stroke="${STRATEGY_COLORS[k]}" stroke-width="${k === 'bench' ? 1.6 : 2.2}" ${k === 'bench' ? 'stroke-dasharray="5 4"' : ''}/>`;
  }).join('');
  const first = curve.dates[0], last = curve.dates[n - 1];
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="規則模擬淨值曲線：起始 100，${first} 至 ${last}" style="max-width:900px;">
    ${grid}${lines}
    <text x="${PL}" y="${H - 6}" font-size="11" fill="#9aabc6">${esc(first)}</text>
    <text x="${W - PR}" y="${H - 6}" font-size="11" fill="#9aabc6" text-anchor="end">${esc(last)}</text>
  </svg>`;
}

function renderStrategySim() {
  const box = document.getElementById('strategySimContainer');
  if (!box) return;
  const ss = STATE && STATE.strategy_sim;
  if (!ss || !ss.available) { box.innerHTML = ''; return; }
  const p = ss.params;
  const names = {};
  (STATE.industries || []).forEach(i => { names[i.industry_id] = i.industry_name; });
  const fmtPct = (v, sign = true) => v == null ? '—' : `<span class="${v >= 0 ? 'pos' : 'neg'}">${sign && v >= 0 ? '+' : ''}${v}%</span>`;
  const fmtPp = (v) => v == null ? '—' : `<span class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : ''}${v} 個百分點</span>`;

  const started = ss.strategies && ss.strategies.length > 0;
  const status = !started
    ? '<span class="badge badge-grade-C">尚未開始：還沒有完成一次週調整</span>'
    : ss.max_complete_periods >= p.min_periods
      ? '<span class="badge badge-grade-B">樣本已達標</span>'
      : `<span class="badge badge-grade-C">樣本不足：${ss.max_complete_periods} / ${p.min_periods} 週</span>`;

  const emptyState = started ? '' : `
    <div class="evidence-box" style="margin:10px 0;">
      目前沒有任何績效數字，這是刻意的。規則只會在「每個已結束的週」最後一個快照日做決策，隔個交易日收盤進場，
      所以要累積到至少一個完整的週之後才會有第一次調整，之後每週再多一期。
      已累積 ${ss.snapshot_days} 個快照日${ss.decision_dates.length ? `，已結算 ${ss.decision_dates.length} 週` : ''}。
      統計上有意義的結論通常要累積半年 (26 週) 以上。
    </div>`;

  const rows = (ss.strategies || []).map(s => `<tr>
      <td style="min-width:240px;"><span style="display:inline-block; width:10px; height:10px; border-radius:2px; background:${STRATEGY_COLORS[s.key]}; margin-right:6px;"></span>
          <strong>${esc(s.name)}</strong>${s.kind === 'baseline' ? ' <span class="badge badge-unratable">基準</span>' : ''}</td>
      <td>${fmtPct(s.total_return_pct)}</td>
      <td>${s.key === 'bench' ? '—' : fmtPp(s.vs_benchmark_pp)}</td>
      <td>${fmtPct(s.max_drawdown_pct, false)}</td>
      <td>${s.rebalances}${s.complete_periods != null ? `（完整 ${s.complete_periods} 期）` : ''}</td>
      <td>${s.key === 'bench' || s.win_rate_pct == null ? '—' : s.win_rate_pct + '%'}</td>
      <td>${s.avg_turnover_pct == null ? '—' : s.avg_turnover_pct + '%'}</td>
    </tr>`).join('');

  const holdingLine = (key, label) => {
    const h = ss.holdings_now && ss.holdings_now[key];
    if (!h) return '';
    const ws = Object.entries(h.weights);
    const text = ws.length
      ? ws.map(([iid, w]) => `${esc(names[iid] || iid)} ${(w * 100).toFixed(0)}%`).join('、')
      : '全部現金（沒有任何產業符合條件）';
    return `<div style="margin:4px 0;"><strong>${label}</strong>（決策日 ${esc(h.decision_date)}，進場 ${esc(h.entry_date)}）：${text}</div>`;
  };

  const legend = Object.entries({ top_n: '規則 A', alert: '規則 B', equal: '產業等權重', bench: '加權報酬指數' })
    .map(([k, v]) => `<span style="margin-right:14px;"><span style="display:inline-block; width:18px; height:3px; background:${STRATEGY_COLORS[k]}; vertical-align:middle; margin-right:4px;"></span>${v}</span>`).join('');

  box.innerHTML = `
    <div class="card" style="margin-top:16px; border-left:4px solid #a78bfa;">
      <div class="card-header">
        <div>
          <div class="card-title" style="font-size:16px;">規則模擬器：照規則做會怎樣？（兩個固定規則 vs 兩個基準）</div>
          <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">
            ${esc(p.rebalance)}調整｜規則 A：持有總分前 ${p.top_n} 名等權重｜規則 B：持有 ${p.levels.map(esc).join('/')}，其餘現金｜單邊成本 ${p.cost_one_way_pct}%｜規則與參數固定，不可調整
          </div>
        </div>
        ${status}
      </div>
      ${emptyState}
      ${started ? `
        <div style="overflow-x:auto;"><table>
          <thead><tr><th>策略</th><th>累積報酬（扣成本）</th><th>相對加權指數</th><th>最大回撤</th><th>調整次數</th><th>單期勝過加權指數</th><th>平均單邊換手</th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        <div style="margin:12px 0 4px; font-size:12.5px; color:var(--text-secondary);">淨值走勢（進場日 = 100，已扣成本）　${legend}</div>
        ${strategyLineChart(ss.curve)}
        ${ss.max_complete_periods < p.min_periods ? `<div class="evidence-box invalid" style="margin:10px 0;"><strong>樣本不足，僅供觀察，不是結論：</strong>目前只有 ${ss.max_complete_periods} 個完整調整週期，至少需要 ${p.min_periods} 週。短期內贏或輸大盤，絕大部分是運氣與產業行情。</div>` : ''}
      ` : ''}
      ${Object.keys(ss.holdings_now || {}).length ? `
        <div style="margin-top:10px; font-size:12.5px;"><div style="font-weight:700; margin-bottom:4px;">規則最近一次的持股輸出（僅是規則的輸出，不是買賣建議）</div>
          ${holdingLine('top_n', '規則 A')}${holdingLine('alert', '規則 B')}
        </div>` : ''}
      <details style="margin-top:12px;" open>
        <summary style="cursor:pointer; font-weight:600;">方法與限制</summary>
        <ul style="font-size:12.5px; color:var(--text-secondary); margin:6px 0 0 18px;">${ss.caveats.map(c => `<li>${esc(c)}</li>`).join('')}</ul>
      </details>
    </div>`;
}
