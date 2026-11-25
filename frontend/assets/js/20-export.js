/* =========================================================================
   匯出功能：CSV (Excel 可直接開啟) 與排行榜 PNG 圖片
   - 全部在瀏覽器端完成，不需要伺服器，雙擊離線檔案也能使用
   - 匯出內容與畫面目前的篩選／排序一致
   - CSV 以 UTF-8 BOM 開頭，避免 Excel 開啟中文亂碼；字串欄位會防範「公式注入」(= + - @ 開頭)
   ========================================================================= */

/* ---------- 純函式 (不碰 DOM，方便單元測試) ---------- */
function csvCell(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '';
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE';
  let s = String(value).replace(/\r?\n/g, ' ').trim();
  // 試算表會把 = + - @ 與 Tab 開頭的文字當成公式執行；前面補一個單引號使其維持純文字
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  if (/[",]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
  return s;
}

// columns: [{ label, value: row => any }]
function buildCsv(columns, rows) {
  const lines = [columns.map(c => csvCell(c.label)).join(',')];
  rows.forEach(r => lines.push(columns.map(c => csvCell(c.value(r))).join(',')));
  return '﻿' + lines.join('\r\n') + '\r\n';
}

function exportDateStamp(generatedAt) {
  const m = String(generatedAt || '').match(/(\d{4})-(\d{2})-(\d{2})/);
  return m ? m[1] + m[2] + m[3] : 'export';
}

function exportFilename(prefix, ext) {
  return `twfin_${prefix}_${exportDateStamp(STATE && STATE.generated_at)}.${ext}`;
}

/* ---------- 下載 ---------- */
function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadCsv(prefix, columns, rows) {
  if (!rows.length) { alert('目前沒有可匯出的資料（請檢查篩選條件）。'); return; }
  downloadBlob(exportFilename(prefix, 'csv'), new Blob([buildCsv(columns, rows)], { type: 'text/csv;charset=utf-8' }));
}

/* 每份 CSV 都附上資料基準與模型版本，離開網站後仍能追溯 */
function exportMetaColumns() {
  const gen = (STATE && STATE.generated_at) || '';
  const ver = (STATE && STATE.active_model && STATE.active_model.version_id) || '';
  return [
    { label: '資料基準時間', value: () => gen },
    { label: '模型版本', value: () => ver },
  ];
}

/* ---------- 敏感度資料：把權重與門檻敏感度依產業編號合併 (純函式) ---------- */
function joinSensitivity(state) {
  const out = {};
  const ws = state && state.weight_sensitivity;
  const ts = state && state.threshold_sensitivity;
  if (ws && ws.available) ws.industries.forEach(x => { (out[x.industry_id] = out[x.industry_id] || {}).w = x; });
  if (ts && ts.available) ts.industries.forEach(x => { (out[x.industry_id] = out[x.industry_id] || {}).t = x; });
  return out;
}

function sensitivitySettingText(state) {
  const ws = state && state.weight_sensitivity, ts = state && state.threshold_sensitivity;
  const parts = [];
  if (ws && ws.available) parts.push(`權重±${ws.delta_pct}%(${ws.scenario_count}種情境)`);
  if (ts && ts.available) parts.push(`門檻±${ts.delta_points}分(${ts.scenario_count}種情境)`);
  return parts.join('；');
}

/* ---------- CSV：產業排行 ---------- */
function exportIndustriesCsv() {
  const list = getVisibleIndustries();
  let rank = 0;
  const ranked = list.map(ind => {
    const rated = !(ind.total_weighted_score === null || ind.rotation_state === 'INSUFFICIENT_DATA');
    return { ind, rank: rated ? ++rank : null };
  });
  const agg = (r, k) => (r.ind.live_agg ? r.ind.live_agg[k] : null);
  const sens = joinSensitivity(STATE);
  const sw = (r, k) => { const x = sens[r.ind.industry_id]; return x && x.w ? x.w[k] : null; };
  const st = (r, k) => { const x = sens[r.ind.industry_id]; return x && x.t ? x.t[k] : null; };
  const thLabel = (key) => {
    const hit = ((STATE.threshold_sensitivity || {}).by_threshold || []).find(b => b.threshold_key === key);
    return hit ? hit.label : key;
  };
  const columns = [
    { label: '排名', value: r => r.rank },
    { label: '產業', value: r => r.ind.industry_name },
    { label: '產業大類', value: r => r.ind.major_category },
    { label: '輪動狀態', value: r => r.ind.rotation_state },
    { label: '轉折標籤', value: r => r.ind.transition_tag },
    { label: '景氣循環位置', value: r => r.ind.cycle_stage },
    { label: '綜合加權總分', value: r => r.ind.total_weighted_score },
    { label: '信心等級', value: r => r.ind.confidence_level },
    { label: '資料缺失率(%)', value: r => r.ind.missing_data_pct },
    { label: '資金流向分數', value: r => r.ind.score_capital_flow },
    { label: '產業基本面分數', value: r => r.ind.score_fundamentals },
    { label: '未來成長性分數', value: r => r.ind.score_future_growth },
    { label: '法人布局分數', value: r => r.ind.score_institutional },
    { label: '估值合理性分數', value: r => r.ind.score_valuation },
    { label: '短期動能分數', value: r => r.ind.short_term_momentum_score },
    { label: '中期基本面分數', value: r => r.ind.mid_term_fundamental_score },
    { label: '長期結構分數', value: r => r.ind.long_term_structural_score },
    { label: '20日相對大盤(%)', value: r => r.ind.rel_strength_20d },
    { label: '60日相對大盤(%)', value: r => r.ind.rel_strength_60d },
    { label: '代表廠營收年增率(%)', value: r => r.ind.rev_yoy_pct },
    { label: '全市場匯總公司數', value: r => agg(r, 'company_count') },
    { label: '全市場匯總營收(億)', value: r => agg(r, 'ind_rev_billion') },
    { label: '全市場匯總營收年增率(%)', value: r => agg(r, 'agg_yoy_pct') },
    { label: '平均P/E', value: r => agg(r, 'avg_pe') },
    { label: '平均P/B', value: r => agg(r, 'avg_pb') },
    { label: '支持證據', value: r => r.ind.supporting_evidence },
    { label: '反方證據', value: r => r.ind.counter_evidence },
    { label: '失效條件', value: r => r.ind.invalidation_conditions },
    { label: '資料限制', value: r => r.ind.data_limitations },
    // 敏感度：結論有多依賴權重與門檻的主觀設定 (名次為「全部產業」中的名次，與上方依目前排序的排名可能不同)
    { label: '基準名次(全部產業)', value: r => sw(r, 'base_rank') },
    { label: '權重擾動最佳名次', value: r => sw(r, 'min_rank') },
    { label: '權重擾動最差名次', value: r => sw(r, 'max_rank') },
    { label: '權重擾動進入前三名機率(%)', value: r => sw(r, 'top3_pct') },
    { label: '權重擾動預警等級變動機率(%)', value: r => sw(r, 'level_change_pct') },
    { label: '權重敏感度穩定度', value: r => sw(r, 'stability') },
    { label: '目前預警等級', value: r => st(r, 'base_level') },
    { label: '距最近預警門檻(分)', value: r => st(r, 'margin_points') },
    { label: '最近預警門檻', value: r => (st(r, 'nearest_threshold') ? thLabel(st(r, 'nearest_threshold')) : null) },
    { label: '門檻擾動預警等級變動機率(%)', value: r => st(r, 'level_change_pct') },
    { label: '門檻敏感度穩定度', value: r => st(r, 'stability') },
    { label: '敏感度設定', value: () => sensitivitySettingText(STATE) },
  ].concat(exportMetaColumns());
  downloadCsv('industry_ranking', columns, ranked);
}

/* ---------- CSV：預警 ---------- */
function exportWarningsCsv() {
  const lvl = document.getElementById('warningLevelFilter').value;
  const list = STATE.warnings.filter(w => lvl === 'ALL' || w.alert_level === lvl);
  const columns = [
    { label: '預警等級', value: w => w.alert_level },
    { label: '產業', value: w => w.industry_name },
    { label: '訊號類別', value: w => w.signal_category },
    { label: '期間', value: w => w.horizon },
    { label: '可信度', value: w => w.credibility_grade },
    { label: '觸發時間', value: w => w.triggered_at },
    { label: '觸發原因', value: w => w.trigger_reason },
    { label: '原始數據證據', value: w => w.raw_data_evidence },
    { label: '反方證據', value: w => w.counter_evidence },
    { label: '失效條件', value: w => w.invalidation_conditions },
    { label: '缺失資料與限制', value: w => w.missing_data_notes },
    { label: '資料來源單位', value: w => w.publisher },
    { label: '來源網址', value: w => w.source_url },
  ].concat(exportMetaColumns());
  downloadCsv('warnings', columns, list);
}

/* ---------- CSV：三大法人 ---------- */
function exportInstiCsv() {
  const p = document.getElementById('instiPeriodFilter').value;
  const list = (STATE.institutional_flows || []).filter(r => p === 'ALL' || r.period_type === p);
  const columns = [
    { label: '週期類型', value: r => r.period_type },
    { label: '期別', value: r => r.period_label },
    { label: '發布日', value: r => r.release_date },
    { label: '範圍', value: r => r.market_scope },
    { label: '外資買賣超(億元)', value: r => r.foreign_net_billion },
    { label: '投信買賣超(億元)', value: r => r.itc_net_billion },
    { label: '自營商自行買賣(億元)', value: r => r.dealer_prop_billion },
    { label: '自營商避險(億元)', value: r => r.dealer_hedge_billion },
    { label: '三大法人合計(億元)', value: r => r.total_3insti_billion },
    { label: '外資台指期未平倉(口)', value: r => r.foreign_futures_oi_contracts },
    { label: '融資餘額(億元)', value: r => r.margin_balance_billion },
    { label: '備註', value: r => r.notes },
    { label: '資料來源單位', value: r => r.publisher },
  ].concat(exportMetaColumns());
  downloadCsv('institutional_flows', columns, list);
}

/* ---------- CSV：全市場公司檢索結果 (營收前段班) ---------- */
function exportLiveCompaniesCsv() {
  const q = (document.getElementById('liveCompanySearch').value || '').trim().toLowerCase();
  const list = (STATE.live_top_companies || []).filter(r => !q ||
    r.company_code.toLowerCase().includes(q) || r.company_name.toLowerCase().includes(q) ||
    r.official_industry.toLowerCase().includes(q) || (r.mapped_industry_id || '').toLowerCase().includes(q));
  const columns = [
    { label: '公司代號', value: r => r.company_code },
    { label: '公司名稱', value: r => r.company_name },
    { label: '市場', value: r => r.market_type },
    { label: '官方產業別', value: r => r.official_industry },
    { label: '對應產業', value: r => r.mapped_industry_id },
    { label: '營收資料年月', value: r => r.data_ym },
    { label: '當月營收(億)', value: r => r.rev_billion },
    { label: '月增率(%)', value: r => r.rev_mom_pct },
    { label: '年增率(%)', value: r => r.rev_yoy_pct },
    { label: '累計年增率(%)', value: r => r.cum_rev_yoy_pct },
    { label: '本益比', value: r => r.pe_ratio },
    { label: '股價淨值比', value: r => r.pb_ratio },
    { label: '殖利率(%)', value: r => r.dividend_yield },
    { label: '外資買賣超(股)', value: r => r.foreign_net_shares },
    { label: '投信買賣超(股)', value: r => r.itc_net_shares },
    { label: '自營商買賣超(股)', value: r => r.dealer_net_shares },
    { label: '法人資料日期', value: r => r.insti_trade_date },
  ].concat(exportMetaColumns());
  downloadCsv('companies', columns, list);
}

/* ---------- PNG：產業排行榜圖片 (Canvas 自繪，不依賴外部函式庫) ---------- */
const EXPORT_STATE_COLORS = { A: '#34d399', B: '#38bdf8', C: '#fbbf24', D: '#fb7185', E: '#fb7185' };
const EXPORT_FONT = '"Noto Sans TC","Microsoft JhengHei","PingFang TC","Heiti TC",sans-serif';

function truncateToWidth(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + '…').width > maxWidth) t = t.slice(0, -1);
  return t + '…';
}

const EXPORT_STABILITY_COLORS = { '穩定': '#34d399', '中等': '#fbbf24', '不穩定': '#fb7185' };

function exportIndustriesPng() {
  const list = getVisibleIndustries();
  const rated = list.filter(i => !(i.total_weighted_score === null || i.rotation_state === 'INSUFFICIENT_DATA'));
  const unrated = list.filter(i => !rated.includes(i));
  if (!list.length) { alert('目前沒有可匯出的資料（請檢查篩選條件）。'); return; }
  const sens = joinSensitivity(STATE);
  const hasSens = rated.some(i => sens[i.industry_id] && (sens[i.industry_id].w || sens[i.industry_id].t));

  const W = hasSens ? 1560 : 1200, PAD = 40, ROW_H = 54, HEAD_H = 150;
  const NOTE_LINES = hasSens ? 3 : 2;
  const FOOT_H = 70 + NOTE_LINES * 24 + (unrated.length ? 28 : 0);
  const H = HEAD_H + rated.length * ROW_H + FOOT_H;
  const scale = 2;   // 固定 2 倍解析度，分享時文字才清楚
  const canvas = document.createElement('canvas');
  canvas.width = W * scale;
  canvas.height = H * scale;
  const ctx = canvas.getContext('2d');
  ctx.scale(scale, scale);

  ctx.fillStyle = '#0b1220';
  ctx.fillRect(0, 0, W, H);
  ctx.textBaseline = 'middle';

  // 標題區
  ctx.fillStyle = '#ffffff';
  ctx.font = `700 30px ${EXPORT_FONT}`;
  ctx.fillText('台灣產業資金輪動排行', PAD, 48);
  const model = (STATE.active_model && STATE.active_model.version_id) || '';
  const w = (STATE.active_model && STATE.active_model.weights) || {};
  const wText = ['capital_flow', 'fundamentals', 'future_growth', 'institutional', 'valuation']
    .map((k, i) => ['資金', '基本面', '成長', '法人', '估值'][i] + Math.round((w[k] || 0) * 100) + '%').join(' ');
  ctx.fillStyle = '#9aabc6';
  ctx.font = `400 15px ${EXPORT_FONT}`;
  ctx.fillText(`資料基準：${STATE.generated_at || ''}　｜　模型 ${model}　｜　權重：${wText}`, PAD, 84);
  const catSel = document.getElementById('rotationCatFilter').value;
  ctx.fillText(`範圍：${catSel === 'ALL' ? '全部產業' : catSel}　｜　綜合加權總分 (0~100)`, PAD, 108);

  // 欄位 (含敏感度) 的 x 座標
  const nameX = PAD + 60, barX = 470, barW = hasSens ? 400 : 520;
  const scoreX = barX + barW + 16, stateX = scoreX + 62;
  // 「狀態」欄約佔 stateX 起算 80px，名次範圍欄要留出空隙以免重疊
  const rangeX = 1050, levelX = 1170, wStabX = 1340, tStabX = 1450;

  // 欄位標題
  ctx.fillStyle = '#6f84a8';
  ctx.font = `600 13px ${EXPORT_FONT}`;
  const headY = HEAD_H - 16;
  ctx.fillText('產業', nameX, headY);
  ctx.fillText('綜合總分', barX, headY);
  if (hasSens) {
    ctx.fillText('權重±擾動名次', rangeX, headY);
    ctx.fillText('預警等級 / 距門檻', levelX, headY);
    ctx.fillText('權重穩定度', wStabX, headY);
    ctx.fillText('門檻穩定度', tStabX, headY);
  }

  // 排行列
  rated.forEach((ind, i) => {
    const y = HEAD_H + i * ROW_H;
    if (i % 2 === 0) { ctx.fillStyle = 'rgba(255,255,255,0.03)'; ctx.fillRect(PAD - 12, y, W - 2 * PAD + 24, ROW_H); }
    const cy = y + ROW_H / 2;
    ctx.fillStyle = i < 3 ? '#38bdf8' : '#9aabc6';
    ctx.font = `700 20px ${EXPORT_FONT}`;
    ctx.fillText('#' + (i + 1), PAD, cy);
    ctx.fillStyle = '#e8eefb';
    ctx.font = `600 18px ${EXPORT_FONT}`;
    ctx.fillText(truncateToWidth(ctx, ind.industry_name, barX - nameX - 16), nameX, cy);
    // 分數長條
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.fillRect(barX, cy - 9, barW, 18);
    const color = EXPORT_STATE_COLORS[ind.rotation_state] || '#9aabc6';
    ctx.fillStyle = color;
    ctx.fillRect(barX, cy - 9, barW * Math.max(0, Math.min(100, ind.total_weighted_score)) / 100, 18);
    ctx.fillStyle = '#ffffff';
    ctx.font = `700 20px ${EXPORT_FONT}`;
    ctx.fillText(ind.total_weighted_score.toFixed(1), scoreX, cy);
    ctx.fillStyle = color;
    ctx.font = `600 14px ${EXPORT_FONT}`;
    ctx.fillText('狀態 ' + ind.rotation_state, stateX, cy);

    if (!hasSens) return;
    const s = sens[ind.industry_id] || {};
    // 名次範圍：基準名次與擾動後最佳~最差名次
    if (s.w) {
      ctx.fillStyle = '#e8eefb';
      ctx.font = `600 16px ${EXPORT_FONT}`;
      const rng = s.w.min_rank === s.w.max_rank ? `${s.w.base_rank}` : `${s.w.min_rank} – ${s.w.max_rank}`;
      ctx.fillText(`#${s.w.base_rank}`, rangeX, cy - 9);
      ctx.fillStyle = '#9aabc6';
      ctx.font = `400 13px ${EXPORT_FONT}`;
      ctx.fillText(`範圍 ${rng}`, rangeX, cy + 11);
    }
    // 預警等級與距最近門檻
    if (s.t) {
      ctx.fillStyle = '#e8eefb';
      ctx.font = `600 16px ${EXPORT_FONT}`;
      ctx.fillText(s.t.base_level || '—', levelX, cy - 9);
      ctx.fillStyle = s.t.margin_points <= (STATE.threshold_sensitivity.delta_points || 0) ? '#fbbf24' : '#9aabc6';
      ctx.font = `400 13px ${EXPORT_FONT}`;
      ctx.fillText(`距門檻 ${s.t.margin_points} 分`, levelX, cy + 11);
    }
    // 穩定度標籤
    const pill = (label, x) => {
      if (!label) return;
      const col = EXPORT_STABILITY_COLORS[label] || '#9aabc6';
      ctx.font = `700 14px ${EXPORT_FONT}`;
      const tw = ctx.measureText(label).width + 22;
      ctx.fillStyle = col + '26';
      ctx.fillRect(x, cy - 12, tw, 24);
      ctx.strokeStyle = col + '88';
      ctx.strokeRect(x + 0.5, cy - 11.5, tw - 1, 23);
      ctx.fillStyle = col;
      ctx.fillText(label, x + 11, cy);
    };
    pill(s.w && s.w.stability, wStabX);
    pill(s.t && s.t.stability, tStabX);
  });

  // 頁尾
  let fy = HEAD_H + rated.length * ROW_H + 24;
  ctx.font = `400 13px ${EXPORT_FONT}`;
  ctx.fillStyle = '#9aabc6';
  if (unrated.length) {
    ctx.fillText('不可評分（資料不足，依規不予補分）：' + unrated.map(i => i.industry_name).join('、'), PAD, fy);
    fy += 28;
  }
  if (hasSens) {
    const ws = STATE.weight_sensitivity || {}, ts = STATE.threshold_sensitivity || {};
    ctx.fillText(`敏感度：權重 ±${ws.delta_pct}%（${ws.scenario_count} 種情境）後的最佳~最差名次；門檻 ±${ts.delta_points} 分（${ts.scenario_count} 種情境）後預警等級的變動機率。` +
      '穩定 = 變動機率低於 10%，不穩定 = 30% 以上。', PAD, fy);
    fy += 24;
    ctx.fillText('名次與預警等級落在「中等／不穩定」的產業，其結論主要取決於權重或門檻的主觀設定，解讀時應更保守。', PAD, fy);
    fy += 24;
  }
  ctx.fillText('資料來源：證交所 TWSE / 櫃買中心 TPEx / 公開資訊觀測站 MOPS 官方 OpenAPI。', PAD, fy);
  ctx.fillText('部分子分數（成長性、基本面等）含內建種子參考資料，並非全部即時更新。本圖僅供研究參考，不構成投資建議。', PAD, fy + 24);

  canvas.toBlob(blob => {
    if (!blob) { alert('圖片產生失敗，請改用 CSV 匯出。'); return; }
    downloadBlob(exportFilename('industry_ranking', 'png'), blob);
  }, 'image/png');
}
