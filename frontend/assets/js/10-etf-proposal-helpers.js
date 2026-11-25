/* =========================================================================
   [已批准提案 ETF-IMPROVE-20261122-001 ~ 005 補助運算函數]
   - 001: 跨市場底層資產實體正規化映射 (2330 <-> TSM ADR, 00679B <-> TLT, 00635U <-> GLD)
   - 002: 禁止未滿 3/5 年 ETF 外推成立前歷史曲線 & 台美跨時區收盤時間戳 (UTC+8 T+2 vs EST T+1)
   - 003: 模型 B 短中期拆分為「1~3M 短期戰術」與「3~12M 中期景氣」雙尺度 + 資金價格四象限 + 長短債存續期分級
   - 004: 台灣投資人稅後實質年化持有成本 (TER + 美股30%股息預扣稅損) & 54C 經常性純股利殖利率
   - 005: 個人投資組合加權有效存續期 (Duration)、加權 Beta 與利率×匯率量化損益試算
   ========================================================================= */
function canonicalEntityInfo(code, name) {
  const c = String(code || '').trim().toUpperCase();
  if (c === '2330' || c === 'TSM') {
    return { key: 'ENTITY_TSMC', label: '台積電 (2330現股 / TSM ADR 同企業實體)' };
  }
  if (c === 'US_TREASURY_20Y' || c === 'US_T_20Y' || (name && name.includes('20年期以上美國政府公債'))) {
    return { key: 'ENTITY_UST20Y', label: '20年期以上美國政府公債 (00679B/TLT 同底層)' };
  }
  if (c === 'COMEX_GOLD_FUT' || c === 'LBMA_GOLD_BULLION' || (name && name.includes('黃金'))) {
    return { key: 'ENTITY_GOLD', label: '黃金資產曝險 (COMEX黃金期貨 / LBMA實體黃金)' };
  }
  return { key: c, label: `${code} ${name}` };
}

function getTimezoneAndSettlementTag(e) {
  if (e.listing_market === 'TW') {
    return '🇹🇼 TW收盤 13:30 UTC+8 (T+2交割)';
  }
  return '🇺🇸 US收盤 16:00 EST / 台灣隔日05:00 (T+1交割)';
}

function computeModelBDualHorizons(e) {
  const s1_3m = roundTo1(
    (Number(e.score_b_valuation_and_pos || 65) * 0.35) +
    (Number(e.score_b_vol_event_downside || 65) * 0.35) +
    (Number(e.score_b_flow_and_breadth || 65) * 0.30)
  );
  const s3_12m = roundTo1(
    (Number(e.score_b_macro_environment || 70) * 0.45) +
    (Number(e.score_b_trend_and_momentum || 70) * 0.45) +
    (Number(e.score_b_flow_and_breadth || 70) * 0.10)
  );
  const flow = Number(e.primary_net_flow_value || 0);
  const chg = Number(e.change_pct || 0);
  let flowPriceQuad = '🔵 價穩量平觀望';
  if (flow > 0 && chg >= 0) flowPriceQuad = '🟢 象限I：價強＋初級淨申購（真順風共識）';
  else if (flow > 0 && chg < 0) flowPriceQuad = (s3_12m >= 74)
    ? '🟠 象限II：價跌＋內資逆勢申購（基本面強・宜左側分批慢買）'
    : '🔴 象限II：價跌＋散戶逆勢申購（⚠️ 留意長債/貼息接刀風險）';
  else if (flow < 0 && chg >= 0) flowPriceQuad = '🟠 象限III：價彈＋初級淨贖回（主力逢高調節背離）';
  else if (flow < 0 && chg < 0) flowPriceQuad = '🔴 象限IV：價跌＋初級淨贖回（資金撤退雙殺）';

  let bondRiskClass = '';
  if (e.asset_class === '債券') {
    const dur = Number(e.bond_duration_years || 0);
    if (dur <= 1.5) bondRiskClass = '🟢 超短債現金避風港（存續期 ' + dur + '年｜幾乎零利率波動回撤）';
    else if (dur <= 9.5) bondRiskClass = '🔵 中天期鎖利型債券（存續期 ' + dur + '年｜中度利率敏感）';
    else bondRiskClass = '🟠 長存續期利率敏感型債券（存續期 ' + dur + '年｜歷史回撤 -34%~-42% 波動等同股票！）';
  }
  return { s1_3m, s3_12m, flowPriceQuad, bondRiskClass };
}

function computeEffectiveTaxAndFeeDrag(e) {
  const ter = Number(e.total_expense_ratio_pct || 0);
  const dy = Number(e.dividend_yield_pct || 0);
  // 美股股票型與 REITs 現金股利須預扣 30% 不可退稅款；美債 ETF 屬 Portfolio Interest 免預扣稅
  let usWithholdingDrag = 0;
  let taxNote = '境內免預扣 (單筆股利≥2萬課2.11%補充保費)';
  if (e.listing_market === 'US') {
    if (e.asset_class === '股票' || e.asset_class === 'REITs不動產') {
      usWithholdingDrag = roundTo1(dy * 0.30 * 10) / 10;
      taxNote = `含美股30%股息預扣稅年耗損 ${usWithholdingDrag.toFixed(2)}%`;
    } else {
      taxNote = '美國公債/投等債屬 Portfolio Interest 免30%預扣稅 (QI券商)';
    }
  }
  const totalDrag = (ter + usWithholdingDrag).toFixed(2);
  return { totalDragPct: totalDrag, terPct: ter, usWithholdingDragPct: usWithholdingDrag.toFixed(2), taxNote };
}

function computeRecurringPureYield(e) {
  const dy = Number(e.dividend_yield_pct || 0);
  if (e.dividend_breakdown) {
    const ratio = Number(e.dividend_breakdown.dividend_income_ratio_pct || 100) / 100.0;
    const pureY = (dy * ratio).toFixed(2);
    return `真實純股利/票息殖利率 <strong style="color:#34d399;">${pureY}%</strong> <span style="font-size:12.5px; color:#94a3b8;">(帳面 ${dy}% × 經常性股利佔比 ${e.dividend_breakdown.dividend_income_ratio_pct}%)</span>`;
  }
  if (e.listing_market === 'US' && (e.asset_class === '股票' || e.asset_class === 'REITs不動產')) {
    const afterTaxY = (dy * 0.70).toFixed(2);
    return `扣30%美股預扣稅後實拿 <strong style="color:#38bdf8;">${afterTaxY}%</strong> <span style="font-size:12.5px; color:#94a3b8;">(100%純股利・稅前 ${dy}%)</span>`;
  }
  return `<strong style="color:#34d399;">${dy}%</strong> <span style="font-size:12.5px; color:#94a3b8;">(100%純股利/票息或滾入再投資)</span>`;
}

