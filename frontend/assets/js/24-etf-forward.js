/* =========================================================================
   ETF 前瞻追蹤 (取代手寫的「ETF 模型回測」)
   資料由後端 etf_backtest.compute_etf_forward() 產生 (STATE.etf_forward)：
   每次即時評分記下 A/B 分數與結論，之後用快照日之後實際的 ETF 相對加權指數超額報酬檢驗；沒有手寫數字。
   ========================================================================= */
function renderEtfForward() {
  const box = document.getElementById('etfForwardContainer');
  if (!box) return;
  const ef = STATE && STATE.etf_forward;
  if (!ef || !ef.available) {
    box.innerHTML = '<div class="card"><div class="card-title">ETF 前瞻追蹤</div><div style="color:var(--text-secondary);">尚無 ETF 評分快照，累積後才會顯示（每次同步記錄一份）。</div></div>';
    return;
  }
  const fmtPct = (v) => v == null ? '—' : `<span class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : ''}${v}%</span>`;
  const badge = ef.any_matured
    ? '<span class="badge badge-grade-B">已有成熟訊號</span>'
    : '<span class="badge badge-grade-C">累積中：尚無成熟樣本</span>';

  const modelBlock = (key, title) => {
    const m = ef.models && ef.models[key];
    if (!m) return '';
    const progress = m.horizon_results.map(h => {
      const needed = h.horizon + 1;
      const have = Math.min(needed, ef.index_trading_days_after_first_snapshot);
      const pct = Math.round(100 * have / needed);
      const state = h.matured_signals
        ? `已成熟 ${h.matured_signals} 筆，尚待 ${h.pending_signals} 筆`
        : `還需約 ${h.trading_days_needed} 個交易日才會有第一筆結果`;
      return `<div style="margin:6px 0;">
        <div style="display:flex; justify-content:space-between; font-size:12.5px;"><span><strong>${h.horizon} 個交易日</strong>觀察期</span><span style="color:var(--text-secondary);">${state}</span></div>
        <div style="height:8px; background:rgba(255,255,255,.08); border-radius:4px; overflow:hidden;"><div style="height:100%; width:${pct}%; background:#38bdf8;"></div></div></div>`;
    }).join('');
    const results = m.horizon_results.filter(h => h.matured_signals > 0).map(h => {
      const rows = h.levels.map(l => `<tr><td>${esc(l.label || l.level)}</td><td>${l.n}</td><td>${fmtPct(l.mean_rel_pct)}</td>
        <td>${l.hit_rate_pct == null ? '—' : l.hit_rate_pct + '%'}<div style="font-size:11px; color:var(--text-secondary);">${esc(l.hit_definition || '不計命中率')}</div></td></tr>`).join('');
      const warn = (!h.enough_for_rates || !h.enough_for_ic)
        ? `<div class="evidence-box invalid" style="margin:8px 0;"><strong>樣本不足，僅供觀察，不是結論</strong>（命中率需 ${ef.min_signals} 筆成熟訊號、IC 需 ${ef.min_dates} 個快照日）。</div>` : '';
      const ic = h.ic ? `平均 IC <strong>${h.ic.mean}</strong>（${h.ic.dates} 個快照日；0 代表沒有預測力）` : 'IC：資料不足 (每個快照日需要至少 8 檔 ETF 已成熟)';
      return `<div style="margin-top:12px;"><div style="font-weight:700;">${h.horizon} 個交易日後：${h.matured_signals} 筆成熟訊號（${h.matured_dates} 個快照日）</div>${warn}
        <table><thead><tr><th>結論</th><th>筆數</th><th>平均超額報酬</th><th>命中率</th></tr></thead><tbody>${rows}</tbody></table>
        <div style="font-size:12.5px; margin-top:6px;">${ic}</div></div>`;
    }).join('');
    return `<div style="margin-top:14px; padding-top:10px; border-top:1px solid rgba(255,255,255,.08);">
      <div style="font-weight:800;">${esc(title)}（${m.signal_count} 筆快照訊號）</div>${progress}${results}</div>`;
  };

  box.innerHTML = `
    <div class="card" style="border-left:4px solid var(--accent-emerald); margin-top:20px;">
      <div class="card-header"><div>
        <div class="card-title" style="font-size:16px;">✅ ETF 前瞻追蹤（取代下方手寫的回測；只統計快照日之後實際發生的行情）</div>
        <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">已累積 ${ef.snapshot_days} 個快照日（${esc(ef.first_snapshot)} ～ ${esc(ef.last_snapshot)}）｜追蹤 ${ef.etf_count} 檔非槓桿 ETF｜基準：${esc(ef.benchmark)}（價格報酬）</div>
      </div>${badge}</div>
      ${ef.any_matured ? '' : `<div class="evidence-box" style="margin:10px 0;">目前還沒有任何一筆訊號走完觀察期，所以<strong>沒有命中率、IC 或超額報酬可以顯示</strong>，這是刻意的：系統不會用手寫數字替代。之後每個交易日進度會前進；統計上有意義的結論通常要累積 2～3 個月。</div>`}
      ${modelBlock('B', '🔵 模型 B：短中期進場時機（結論「條件相對有利」超額報酬 > 0 算命中；「風險偏高」< 0 算成功避險）')}
      ${modelBlock('A', '🟢 模型 A：長期配置（結論「適合進一步研究」超額報酬 > 0 算命中；長期模型本非為 5~20 天設計，只是誠實檢驗）')}
      <details style="margin-top:12px;" open><summary style="cursor:pointer; font-weight:600;">方法與限制</summary>
        <ul style="font-size:12.5px; color:var(--text-secondary); margin:6px 0 0 18px;">${(ef.caveats || []).map(c => `<li>${esc(c)}</li>`).join('')}</ul></details>
    </div>`;
}
