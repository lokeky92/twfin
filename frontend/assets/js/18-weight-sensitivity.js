/* =========================================================================
   權重敏感度分析面板：把五維權重 ±5% 擾動後，排名與預警等級還穩不穩？
   資料由後端 sensitivity_analysis() 產生 (STATE.weight_sensitivity)，固定種子、可重現。
   ========================================================================= */
const WEIGHT_KEY_LABELS = {
  capital_flow: '資金流向', fundamentals: '產業基本面', future_growth: '未來成長性',
  institutional: '法人布局', valuation: '估值合理性',
};
const STABILITY_BADGE = { '穩定': 'badge-grade-A', '中等': 'badge-grade-C', '不穩定': 'badge-lvlR' };

function renderWeightSensitivity() {
  const box = document.getElementById('weightSensitivityCard');
  if (!box) return;
  const ws = STATE && STATE.weight_sensitivity;
  if (!ws || !ws.available) {
    box.style.display = 'none';
    return;
  }
  box.style.display = '';

  const robust = ws.top1_same_pct >= 90 && ws.top3_same_pct >= 80;
  const verdict = robust
    ? '<span class="badge badge-grade-A">排名結論穩健</span>'
    : '<span class="badge badge-lvlR">排名對權重敏感</span>';

  const rows = ws.industries.map(x => {
    const range = x.min_rank === x.max_rank ? `${x.base_rank}` : `${x.min_rank} – ${x.max_rank}`;
    const levelStyle = x.level_change_pct >= 10 ? 'color:#fbbf24; font-weight:600;' : '';
    return `<tr>
      <td><strong>#${x.base_rank}</strong></td>
      <td>${esc(x.industry_name)}</td>
      <td>${esc(range)}</td>
      <td>${x.top3_pct}%</td>
      <td>${esc(x.base_level || '—')}</td>
      <td style="${levelStyle}">${x.level_change_pct}%</td>
      <td><span class="badge ${STABILITY_BADGE[x.stability] || 'badge-grade-B'}">${esc(x.stability)}</span></td>
    </tr>`;
  }).join('');

  const weightLine = ws.by_weight
    .slice().sort((a, b) => b.max_rank_shift - a.max_rank_shift)
    .map(w => `${esc(WEIGHT_KEY_LABELS[w.weight_key] || w.weight_key)}：最多讓名次移動 ${w.max_rank_shift} 名`
      + (w.max_rank_shift > 0 && w.most_affected ? `（${esc(w.most_affected)}）` : ''))
    .join('｜');

  box.innerHTML = `
    <details>
      <summary style="cursor:pointer; font-weight:700;">
        權重敏感度分析（五維權重 ±${ws.delta_pct}% 擾動）${verdict}
        <span style="font-weight:400; font-size:12px; color:var(--text-secondary);">
          第 1 名不變 ${ws.top1_same_pct}%｜前三名組成不變 ${ws.top3_same_pct}%｜名次不穩定產業 ${ws.unstable_count} 個
        </span>
      </summary>
      <p style="font-size:12px; color:var(--text-secondary); margin:8px 0;">
        權重是主觀設定。這裡用 ${ws.scenario_count} 種權重情境（每項權重單獨 ±${ws.delta_pct}%，加上隨機組合）重算排名，
        觀察結論是否因權重微調而翻盤。名次範圍越寬、預警等級變動機率越高，代表該產業的判斷越依賴權重選擇，解讀時應更保守。
      </p>
      <div style="overflow-x:auto;">
        <table>
          <thead><tr>
            <th>基準名次</th><th>產業</th><th>名次範圍</th><th>進入前三名機率</th>
            <th>目前預警等級</th><th>預警等級變動機率</th><th>穩定度</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p style="font-size:12px; color:var(--text-secondary); margin-top:8px;">單一權重 ±${ws.delta_pct}% 的影響：${weightLine}</p>
    </details>`;
}
