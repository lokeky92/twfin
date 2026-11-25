/* =========================================================================
   第九節：個人 ETF 投資組合穿透分析器 (未輸入持倉前不得自行假設持倉!)
   ========================================================================= */
function addUserPortfolioItem() {
  const code = document.getElementById('portAddEtfSelect').value;
  const amt = parseFloat(document.getElementById('portAddAmountInput').value) || 0;
  if (!code || amt <= 0) return;
  const existing = USER_PORTFOLIO.find(x => x.etf_code === code);
  if (existing) existing.amount += amt;
  else USER_PORTFOLIO.push({ etf_code: code, amount: amt });
  renderUserPortfolioAnalysis();
}

function removeUserPortfolioItem(code) {
  USER_PORTFOLIO = USER_PORTFOLIO.filter(x => x.etf_code !== code);
  renderUserPortfolioAnalysis();
}

function clearUserPortfolio() {
  USER_PORTFOLIO = [];
  renderUserPortfolioAnalysis();
}

function loadSamplePortfolioForDemo() {
  USER_PORTFOLIO = [
    { etf_code: '0050', amount: 150 },
    { etf_code: '0052', amount: 100 },
    { etf_code: 'SMH', amount: 100 },
    { etf_code: '00878', amount: 100 },
    { etf_code: '00937B', amount: 100 }
  ];
  renderUserPortfolioAnalysis();
}

function renderUserPortfolioAnalysis() {
  const out = document.getElementById('userPortfolioAnalysisOutput');
  if (!out) return;
  if (!USER_PORTFOLIO.length) {
    out.innerHTML = `
      <div style="padding:18px; background:rgba(15,23,42,0.75); border:1px dashed #475569; border-radius:10px; color:#cbd5e1; font-size:15px;">
        <strong>🔒 零假設持倉狀態（遵循第九節規範：使用者未提供持倉資料前，系統絕不自行預設假持倉）：</strong><br/>
        請由上方選單選擇您持有的 ETF 並點擊「<strong>＋ 加入我的投資組合</strong>」（或點擊右上角「載入範例持倉供測試」），系統將立即為您穿透計算台美比例、股債比例、底層單一個股疊加曝險與三大經濟情境風險。
      </div>
    `;
    return;
  }

  const etfMap = {};
  (STATE.etf_center.etfs || []).forEach(e => { etfMap[e.etf_code] = e; });
  const totalAmt = USER_PORTFOLIO.reduce((s, x) => s + x.amount, 0) || 1;

  let twMarketW = 0, usMarketW = 0, globalMarketW = 0;
  let stockW = 0, bondW = 0, cmdtyReitW = 0;
  let usdFxExposureW = 0;
  let weightedVol = 0, weightedTer = 0, weightedEffectiveCost = 0;
  let weightedDuration = 0, weightedBeta = 0;
  const stockPenetration = {};
  const sectorPenetration = {};

  const itemRowsHtml = USER_PORTFOLIO.map(item => {
    const e = etfMap[item.etf_code];
    if (!e) return '';
    const w = (item.amount / totalAmt) * 100;

    if (e.target_region === '台灣') twMarketW += w;
    else if (e.target_region.includes('美國')) usMarketW += w;
    else globalMarketW += w;

    if (e.asset_class === '股票') stockW += w;
    else if (e.asset_class === '債券') bondW += w;
    else cmdtyReitW += w;

    if (e.currency === 'USD' || e.fx_hedged.includes('USD')) usdFxExposureW += w;
    weightedVol += (w / 100) * (e.annualized_volatility_pct || 15);
    weightedTer += (w / 100) * (e.total_expense_ratio_pct || 0.2);
    const td = computeEffectiveTaxAndFeeDrag(e);
    weightedEffectiveCost += (w / 100) * parseFloat(td.totalDragPct || 0.2);
    weightedDuration += (w / 100) * (e.bond_duration_years || 0);
    weightedBeta += (w / 100) * (e.beta_vs_market || 0);

    // [提案 ETF-IMPROVE-20261122-001] 使用跨市場實體正規化累加 (讓 0050/0052 的 2330 與 SMH 的 TSM ADR 合併計算總台積電曝險!)
    (e.holdings || []).forEach(h => {
      const effW = (w * h.weight_pct) / 100.0;
      const ent = canonicalEntityInfo(h.constituent_code, h.constituent_name);
      stockPenetration[ent.label] = (stockPenetration[ent.label] || 0) + effW;
    });

    Object.entries(e.sector_weights || {}).forEach(([secName, secPct]) => {
      sectorPenetration[secName] = (sectorPenetration[secName] || 0) + (w * secPct) / 100.0;
    });

    return `
      <span class="badge" style="background:#1e293b; color:#fff; padding:7px 12px; margin:4px; font-size:14.5px;">
        ${e.etf_code} ${e.etf_name}：${item.amount}萬 (${w.toFixed(1)}%)
        <button onclick="removeUserPortfolioItem('${e.etf_code}')" style="background:none; border:none; color:#fb7185; margin-left:6px; cursor:pointer; font-weight:800;">✕</button>
      </span>
    `;
  }).join('');

  const topPenetratedStocks = Object.entries(stockPenetration)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);

  const topSectors = Object.entries(sectorPenetration)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  const maxStock = topPenetratedStocks[0] || ['無', 0];
  // [提案 ETF-IMPROVE-20261122-005] 計算三大情境之利率(Duration) × 股市(Beta) × 匯率(FX) 量化損益
  const scenA_pct = ((stockW / 100) * 10.0 * Math.max(0.7, weightedBeta)) + (weightedDuration * 0.60);
  const scenA_amt = (totalAmt * scenA_pct / 100).toFixed(1);
  const scenB_pct = -((stockW / 100) * 10.0 * Math.max(0.8, weightedBeta)) - (weightedDuration * 0.50);
  const scenB_amt = (totalAmt * scenB_pct / 100).toFixed(1);
  const scenC_pct = -(usdFxExposureW * 0.05);
  const scenC_amt = (totalAmt * scenC_pct / 100).toFixed(1);

  out.innerHTML = `
    <div style="margin-bottom:14px; font-size:15.5px;"><strong>目前輸入之持倉組合（總計 ${totalAmt.toLocaleString()} 萬）：</strong> ${itemRowsHtml}</div>
    <div class="etf-grid-4" style="margin-bottom:14px;">
      <div style="background:#090e1a; padding:14px; border-radius:10px; border:1px solid #1e293b;">
        <div style="font-size:14px; color:var(--text-secondary);">1. 股債比例與稅後實質年化成本</div>
        <div style="font-size:20px; font-weight:700; color:#fff; margin-top:4px;">股票 ${stockW.toFixed(1)}% ｜ 債券 ${bondW.toFixed(1)}%</div>
        <div style="font-size:13.5px; color:#94a3b8; margin-top:4px;">加權TER：${weightedTer.toFixed(2)}% ｜ 含美股預扣稅實質年耗損：<strong style="color:#fbbf24;">${weightedEffectiveCost.toFixed(2)}%</strong></div>
      </div>
      <div style="background:#090e1a; padding:14px; border-radius:10px; border:1px solid #1e293b;">
        <div style="font-size:14px; color:var(--text-secondary);">2. 台灣 vs 美國市場與匯率曝險</div>
        <div style="font-size:20px; font-weight:700; color:#38bdf8; margin-top:4px;">台灣 ${twMarketW.toFixed(1)}% ｜ 美國 ${usMarketW.toFixed(1)}%</div>
        <div style="font-size:14px; color:#fde68a; margin-top:4px;">美元(USD)自然匯率曝險：<strong>${usdFxExposureW.toFixed(1)}%</strong></div>
      </div>
      <div style="background:#090e1a; padding:14px; border-radius:10px; border:1px solid #1e293b;">
        <div style="font-size:14px; color:var(--text-secondary);">3. 跨國實體穿透重疊警訊 (2330+TSM)</div>
        <div style="font-size:20px; font-weight:700; color:${maxStock[1] > 25 ? '#fb7185' : '#34d399'}; margin-top:4px;">最大穿透：${maxStock[0]} (${maxStock[1].toFixed(1)}%)</div>
        <div style="font-size:13.5px; color:#cbd5e1; margin-top:4px;">${topPenetratedStocks.slice(0, 3).map(x => `${x[0]} ${x[1].toFixed(1)}%`).join('｜')}</div>
      </div>
      <div style="background:#090e1a; padding:14px; border-radius:10px; border:1px solid #1e293b;">
        <div style="font-size:14px; color:var(--text-secondary);">4. 組合波動率、Beta 與有效存續期</div>
        <div style="font-size:20px; font-weight:700; color:#fff; margin-top:4px;">波動度 ${weightedVol.toFixed(1)}% ｜ 存續期 ${weightedDuration.toFixed(1)}年</div>
        <div style="font-size:13.5px; color:#cbd5e1; margin-top:4px;">組合加權 Beta：<strong>${weightedBeta.toFixed(2)}</strong> ｜ 前二產業：${topSectors.slice(0, 2).map(x => `${x[0]}(${x[1].toFixed(1)}%)`).join('、')}</div>
      </div>
    </div>
    <div class="evidence-box invalid" style="font-size:15px;">
      <strong>🌪️ 三大經濟情境壓力測試診斷（已啟用提案 005：存續期 Duration × Beta × 匯率量化損益試算）：</strong><br/>
      • <strong>情境 A（美債殖利率回落 -60bps 至 4.37%＋AI 股市反彈 +10% 樂觀情境）</strong>：預估組合總淨值變化 <strong class="pos">+${scenA_pct.toFixed(2)}%（約 +${scenA_amt} 萬台幣）</strong>，股票與長債同步享受股債雙漲紅利。<br/>
      • <strong>情境 B（聯準會鷹派使美債殖利率升 +50bps＋半導體再跌 -10% 壓力情境）</strong>：預估組合總淨值回撤 <strong class="neg">${scenB_pct.toFixed(2)}%（約 ${scenB_amt} 萬台幣）</strong>。${maxStock[1] > 25 ? `<span style="color:#fb7185;">🔴 警示：您的投資組合跨市場穿透後對單一企業「${maxStock[0]}」總曝險高達 ${maxStock[1].toFixed(1)}%，建議提高超短債(SGOV)、投等債(00937B/LQD)或低波價值股(00713/SCHD)比重！</span>` : `🟢 您的單一企業穿透曝險低於25%且具備股債分散，抗震韌性良好。`}<br/>
      • <strong>情境 C（新台幣由 32.92 升值 5% 至 31.27 元之匯率風險）</strong>：您有 <strong>${usdFxExposureW.toFixed(1)}%</strong> 資產暴露於美元無避險部位，若台幣升值 5% 將產生約 <strong class="neg">${scenC_pct.toFixed(2)}%（約 ${scenC_amt} 萬台幣）</strong> 之匯兌評價逆風。
    </div>
  `;
}

