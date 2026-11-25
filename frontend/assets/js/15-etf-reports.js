/* =========================================================================
   ETF 7問結構化報告中心 ＆ 雙軌獨立歷史回測渲染
   ========================================================================= */
function renderEtfReportsAndBacktests() {
  const rFilter = document.getElementById('etfReportTypeFilter');
  const rType = rFilter ? rFilter.value : 'ALL';
  const rpts = (STATE.etf_center.reports || []).filter(r => rType === 'ALL' || r.report_type === rType);

  const rptBox = document.getElementById('etfReportsContainer');
  if (rptBox) {
    rptBox.innerHTML = rpts.map(r => `
      <div class="etf-clean-card" style="border-top:4px solid var(--accent-orange);">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
          <div>
            <span class="badge badge-lvl3">${r.report_type}</span>
            <strong style="font-size:19px; color:#fff; margin-left:8px;">${r.report_title}</strong>
          </div>
          <span class="badge badge-grade-A">${r.version_tag}</span>
        </div>
        <div style="font-size:14px; color:var(--text-secondary); margin-bottom:10px;">資料基準：${r.as_of_date} ｜ 來源：${r.primary_sources}</div>
        <div class="evidence-box" style="font-size:15px;"><strong>1️⃣ 發生什麼事？</strong><br/>${r.q1_what_happened}</div>
        <div class="evidence-box" style="white-space:pre-line; font-size:15px;"><strong>2️⃣ 哪些數據支持？</strong><br/>${r.q2_supporting_data}</div>
        <div class="evidence-box" style="white-space:pre-line; font-size:15px;"><strong>3️⃣ 對哪些 ETF 有影響？</strong><br/>${r.q3_affected_etfs}</div>
        <div class="evidence-box" style="border-left-color:#10b981; font-size:15px;"><strong>4️⃣ 可能的正面影響：</strong><br/>${r.q4_positive_impacts}</div>
        <div class="evidence-box counter" style="font-size:15px;"><strong>5️⃣ 可能的負面影響（反方證據）：</strong><br/>${r.q5_negative_impacts}</div>
        <div class="evidence-box invalid" style="font-size:15px;">
          <strong>6️⃣ 接下來應該觀察什麼？</strong> ${r.q6_next_watch}<br/>
          <strong>7️⃣ 哪些條件會讓目前判斷失效？</strong> ${r.q7_invalidation}
        </div>
      </div>
    `).join('');
  }

  const bts = STATE.etf_center.backtests || [];
  const btBox = document.getElementById('etfDualBacktestContainer');
  if (btBox) {
    btBox.innerHTML = bts.map(b => {
      const km = b.key_metrics || {};
      const isLong = b.model_track === 'MODEL_A_LONG_TERM';
      return `
        <div class="etf-clean-card" style="border-left:5px solid ${isLong ? '#10b981' : '#38bdf8'};">
          <div style="margin-bottom:10px;">
            <span class="badge ${isLong ? 'badge-lvl4' : 'badge-lvl3'}">${isLong ? '🟢 模型 A：長期配置模型回測 (3~10年視角)' : '🔵 模型 B：短中期進場時機模型回測 (1~12M視角)'}</span>
            <div style="font-size:18px; font-weight:800; color:#fff; margin-top:6px;">回測區間：${b.test_period}</div>
          </div>
          <div style="font-size:14.5px; color:#cbd5e1; margin-bottom:10px;"><strong>測試樣本：</strong>${b.sample_description}</div>
          <div style="background:#090e1a; padding:12px 16px; border-radius:8px; font-size:14.5px; margin-bottom:10px;">
            ${Object.entries(km).map(([k, v]) => `<div style="margin:4px 0;">• <strong style="color:var(--accent-blue);">${k}：</strong>${v}</div>`).join('')}
          </div>
          <div class="evidence-box" style="font-size:14.5px;">
            <strong>交易成本、買賣價差、匯率與30%美股股息預扣稅處理：</strong><br/>${b.cost_and_tax_assumptions}<br/><br/>
            <strong>防偏差治理（未來資料洩漏、存活者偏差、指數變更）：</strong><br/>${b.biases_guarded}
          </div>
          <div class="evidence-box invalid" style="font-size:14.5px;">
            <strong>不同市場環境表現：</strong>${b.regime_performance_notes}<br/><br/>
            <strong>訊號失效情境與模型限制揭露：</strong>${b.failure_cases_and_limits}
          </div>
        </div>
      `;
    }).join('');
  }
}

