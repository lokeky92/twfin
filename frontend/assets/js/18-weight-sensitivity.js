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


/* =========================================================================
   預警門檻敏感度：LEVEL 2/3/4 分數線與 LEVEL R 資金分數線 ±N 分擾動後，各產業的預警等級還穩不穩？
   資料由後端 threshold_sensitivity() 產生 (STATE.threshold_sensitivity)，固定種子、可重現。
   ========================================================================= */
function renderThresholdSensitivity() {
  const box = document.getElementById('thresholdSensitivityCard');
  if (!box) return;
  const ts = STATE && STATE.threshold_sensitivity;
  if (!ts || !ts.available) {
    box.style.display = 'none';
    return;
  }
  box.style.display = '';

  const thLabel = (key) => {
    const hit = (ts.by_threshold || []).find(b => b.threshold_key === key);
    return hit ? hit.label : key;
  };
  const verdict = ts.unstable_count === 0
    ? '<span class="badge badge-grade-A">預警等級判斷穩健</span>'
    : `<span class="badge badge-grade-C">${ts.unstable_count} 個產業的等級貼著門檻</span>`;

  const rows = ts.industries.map(x => {
    const dist = Object.entries(x.level_distribution)
      .sort((a, b) => b[1] - a[1])
      .map(([lv, pct]) => `${esc(lv)} ${pct}%`).join('｜');
    const near = x.margin_points <= ts.delta_points;
    const marginStyle = near ? 'color:#fbbf24; font-weight:600;' : '';
    return `<tr>
      <td><strong>${esc(x.industry_name)}</strong></td>
      <td>${x.total_score.toFixed(1)}<div style="font-size:11px; color:var(--text-secondary);">資金 ${x.capital_flow_score == null ? '—' : x.capital_flow_score}</div></td>
      <td><span class="badge badge-grade-B">${esc(x.base_level || '—')}</span></td>
      <td style="${marginStyle}">${x.margin_points} 分<div style="font-size:11px; color:var(--text-secondary);">距 ${esc(thLabel(x.nearest_threshold))}</div></td>
      <td style="font-size:12px;">${dist}</td>
      <td>${x.level_change_pct}%</td>
      <td><span class="badge ${STABILITY_BADGE[x.stability] || 'badge-grade-B'}">${esc(x.stability)}</span></td>
    </tr>`;
  }).join('');

  const byTh = (ts.by_threshold || []).map(b =>
    `${esc(b.label)}（${b.value}）：${b.affected_count ? `會改變 ${b.affected_count} 個產業的等級（${b.affected.map(esc).join('、')}）` : '不影響任何產業'}`
  ).join('<br/>');

  box.innerHTML = `
    <details>
      <summary style="cursor:pointer; font-weight:700;">
        預警門檻敏感度分析（四條門檻 ±${ts.delta_points} 分擾動）${verdict}
        <span style="font-weight:400; font-size:12px; color:var(--text-secondary);">
          等級完全不變 ${ts.never_changes_count}/${ts.industry_count} 個產業｜距門檻不到 ${ts.delta_points} 分 ${ts.near_boundary_count} 個
        </span>
      </summary>
      <p style="font-size:12px; color:var(--text-secondary); margin:8px 0;">
        預警分數線同樣是主觀設定。這裡用 ${ts.scenario_count} 種門檻情境（每條門檻單獨 ±${ts.delta_points} 分，加上隨機組合，且維持 LEVEL 4 &gt; 3 &gt; 2）
        重判各產業的預警等級。總分剛好貼著門檻的產業，其等級主要是門檻選擇的結果而不是市場訊號，解讀時應更保守。
      </p>
      <div style="overflow-x:auto;">
        <table>
          <thead><tr>
            <th>產業</th><th>總分</th><th>目前預警等級</th><th>距最近門檻</th>
            <th>各等級出現機率</th><th>等級變動機率</th><th>穩定度</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p style="font-size:12px; color:var(--text-secondary); margin-top:8px;">單一門檻 ±${ts.delta_points} 分的影響：<br/>${byTh}</p>
    </details>`;
}
