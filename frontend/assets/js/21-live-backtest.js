/* =========================================================================
   前瞻追蹤回測 (Live out-of-sample tracking)
   資料由後端 backtest.compute_live_backtest() 產生 (STATE.live_backtest)，全部由資料庫計算，沒有手寫數字。
   模型分數的歷史無法事後重建，所以只統計「快照日之後」實際發生的行情；累積期間會明確顯示進度與樣本不足。
   ========================================================================= */
function renderLiveBacktest() {
  const box = document.getElementById('liveBacktestContainer');
  if (!box) return;
  const lb = STATE && STATE.live_backtest;
  if (!lb || !lb.available) {
    box.innerHTML = '<div class="card"><div class="card-title">前瞻追蹤回測</div><div style="color:var(--text-secondary);">尚無評分快照資料，累積後才會顯示。</div></div>';
    return;
  }
  const names = {};
  (STATE.industries || []).forEach(i => { names[i.industry_id] = i.industry_name; });
  const fmtPct = (v) => v == null ? '—' : `<span class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : ''}${v}%</span>`;

  const statusBadge = lb.any_matured
    ? '<span class="badge badge-grade-B">已有成熟訊號</span>'
    : '<span class="badge badge-grade-C">累積中：尚無成熟樣本</span>';

  const progress = lb.horizon_results.map(h => {
    const needed = h.horizon + 1;
    const have = Math.min(needed, lb.index_trading_days_after_first_snapshot);
    const pct = Math.round(100 * have / needed);
    const state = h.matured_signals
      ? `已成熟 ${h.matured_signals} 筆，尚待 ${h.pending_signals} 筆`
      : `還需約 ${h.trading_days_needed} 個交易日才會有第一筆結果`;
    return `<div style="margin:6px 0;">
      <div style="display:flex; justify-content:space-between; font-size:12.5px;"><span><strong>${h.horizon} 個交易日</strong>觀察期</span><span style="color:var(--text-secondary);">${state}</span></div>
      <div style="height:8px; background:rgba(255,255,255,.08); border-radius:4px; overflow:hidden;"><div style="height:100%; width:${pct}%; background:#38bdf8;"></div></div>
    </div>`;
  }).join('');

  const results = lb.horizon_results.filter(h => h.matured_signals > 0).map(h => {
    const levelRows = h.levels.map(l => `<tr>
        <td><span class="badge ${l.level === 'LEVEL R' ? 'badge-lvlR' : 'badge-grade-B'}">${esc(l.level)}</span></td>
        <td>${l.n}</td><td>${fmtPct(l.mean_rel_pct)}</td>
        <td>${l.hit_rate_pct == null ? '—' : l.hit_rate_pct + '%'}<div style="font-size:11px; color:var(--text-secondary);">${esc(l.hit_definition || '不計命中率')}</div></td>
      </tr>`).join('');
    const warn = (!h.enough_for_rates || !h.enough_for_ic)
      ? `<div class="evidence-box invalid" style="margin:8px 0;"><strong>樣本不足，僅供觀察，不是結論：</strong>
          命中率至少需要 ${lb.min_signals} 筆成熟訊號 (目前 ${h.levels.filter(l => l.level === 'LEVEL 3' || l.level === 'LEVEL 4' || l.level === 'LEVEL R').reduce((a, l) => a + l.n, 0)} 筆)，
          IC 至少需要 ${lb.min_dates} 個快照日 (目前 ${h.ic ? h.ic.dates : 0} 天)。</div>` : '';
    const ic = h.ic
      ? `平均 IC <strong>${h.ic.mean}</strong>（${h.ic.dates} 個快照日，其中 ${h.ic.positive_pct}% 為正；0 代表沒有預測力）`
      : '截面 IC：資料不足 (每個快照日需要至少 8 個產業已成熟)';
    const spread = h.top_bottom_spread_pct == null ? '' : `｜總分前 3 名 vs 後 3 名的平均超額報酬差 ${fmtPct(h.top_bottom_spread_pct)}（${h.spread_dates} 天）`;
    return `<div style="margin-top:14px;">
      <div style="font-weight:700;">${h.horizon} 個交易日後：${h.matured_signals} 筆成熟訊號（${h.matured_dates} 個快照日）</div>
      ${warn}
      <table><thead><tr><th>預警等級</th><th>筆數</th><th>平均超額報酬</th><th>命中率</th></tr></thead><tbody>${levelRows}</tbody></table>
      <div style="font-size:12.5px; margin-top:6px;">${ic}${spread}</div>
    </div>`;
  }).join('');

  const emptyState = lb.any_matured ? '' : `
    <div class="evidence-box" style="margin:10px 0;">
      目前還沒有任何一筆訊號走完觀察期，所以<strong>沒有命中率、IC 或超額報酬可以顯示</strong>，這是刻意的：系統不會用事後重建或手寫的數字替代。
      每天排程都會累積一份評分快照；最早的快照日是 ${esc(lb.first_snapshot || '—')}，之後每多一個交易日，進度就會前進。
      預期 5 日結果最先出現，統計上有意義的結論通常要累積 2～3 個月。
    </div>`;

  const mapRows = lb.mapping.map(m => `<tr><td>${esc(names[m.industry_id] || m.industry_id)}</td><td>${esc(m.index_name)}</td><td>${m.index_points}</td></tr>`).join('');

  box.innerHTML = `
    <div class="card" style="border-left:4px solid var(--accent-blue);">
      <div class="card-header">
        <div>
          <div class="card-title" style="font-size:16px;">前瞻追蹤回測（只統計快照日之後實際發生的行情）</div>
          <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">
            模型 ${esc(lb.model_version)}｜已累積 ${lb.snapshot_days} 個快照日（${esc(lb.first_snapshot || '—')} ～ ${esc(lb.last_snapshot || '—')}）｜類股指數最新資料 ${esc(lb.index_last_date || '—')}
          </div>
        </div>
        ${statusBadge}
      </div>
      <div style="margin:10px 0;">${progress}</div>
      ${emptyState}
      ${results}
      <details style="margin-top:12px;">
        <summary style="cursor:pointer; font-weight:600;">每個產業用哪條指數檢驗（近似對應，基準：${esc(lb.benchmark)}）</summary>
        <div style="overflow-x:auto;"><table><thead><tr><th>產業</th><th>對照的類股報酬指數</th><th>已累積資料點</th></tr></thead><tbody>${mapRows}</tbody></table></div>
      </details>
      <details style="margin-top:8px;" open>
        <summary style="cursor:pointer; font-weight:600;">方法與限制</summary>
        <ul style="font-size:12.5px; color:var(--text-secondary); margin:6px 0 0 18px;">${lb.caveats.map(c => `<li>${esc(c)}</li>`).join('')}</ul>
      </details>
    </div>`;
}
