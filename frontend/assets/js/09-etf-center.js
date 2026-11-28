/* ETF 數字格式化：官方沒有來源而留空的欄位 (淨值、折溢價、配息率、含息報酬…) 一律顯示 N/A，不可印出 null 或 NaN */
// 基金規模的來源標籤：上市 ETF = 官方發行單位數 × 收盤價 (live.aum_source = 'official')，其餘為人工維護
function etfAumTag(e) {
  const L = e && e.live;
  if (L && L.aum_source === 'official') return `<span class="badge badge-grade-A" title="官方發行單位數 × 收盤價，單位數日期 ${esc(L.aum_as_of || '')}">官方</span>`;
  return '<span class="badge badge-grade-C" title="人工維護的數值，不會自動更新">手寫</span>';
}
function etfAumChangeText(e) {
  return (e.aum_change_1m_pct === null || e.aum_change_1m_pct === undefined) ? '近 1 月變化：累積中' : `近 1 月 ${e.aum_change_1m_pct >= 0 ? '+' : ''}${e.aum_change_1m_pct}%`;
}
function fmtEtfNum(v, signed, digits) {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  const n = (digits === undefined) ? v : Number(v).toFixed(digits);
  return (signed && v >= 0 ? '+' : '') + n;
}
function fmtEtfPct(v, signed, digits) {
  const t = fmtEtfNum(v, signed, digits);
  return t === 'N/A' ? t : t + '%';
}
function etfLiveBadge(e) {
  return e.score_source === 'live'
    ? '<span class="badge badge-grade-A" title="雙軌評分由官方逐日行情用公式即時計算">即時評分</span>'
    : '<span class="badge badge-grade-C" title="評分為 2026-11-21 前後手寫，不會隨資料更新">手寫評分</span>';
}
// 官方逐日收盤價的迷你走勢圖 (curve: [[日期, 收盤], ...]；正規化為起點 = 100)
function etfSparkline(curve, w, h) {
  if (!Array.isArray(curve) || curve.length < 2) return '';
  w = w || 220; h = h || 44;
  const base = curve[0][1];
  const vals = curve.map(p => p[1] / base * 100);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = Math.max(1e-9, hi - lo);
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 3 - (v - lo) / span * (h - 6)).toFixed(1)}`).join(' ');
  const up = vals[vals.length - 1] >= 100;
  return `<svg viewBox="0 0 ${w} ${h}" style="width:${w}px; height:${h}px; display:block; margin:4px 0;" role="img" aria-label="近 1 年價格走勢">
    <polyline fill="none" stroke="${up ? '#34d399' : '#fb7185'}" stroke-width="2" points="${pts}"/></svg>`;
}

// 配息與含息報酬一行：配息率 = 近 12 個月已發放的現金配息 ÷ 現價 (過去配息，不是預期殖利率)；含息報酬假設除息日以收盤價再投入
function etfDividendLine(L) {
  if (L.div_note && L.dividend_yield_pct == null) return `<span style="color:var(--text-secondary);">配息與含息報酬：N/A（${esc(L.div_note)}）</span><br/>`;
  if (L.dividend_yield_pct == null) return '';
  const note = L.div_note ? `（${esc(L.div_note)}）` : '';
  return `近 12 個月配息 ${fmtEtfNum(L.div_ttm, false, 3)} 元／單位（${L.div_count} 次）→ 配息率 ${fmtEtfPct(L.dividend_yield_pct, false, 2)}（過去已發放 ÷ 現價，非預期殖利率）｜含息報酬 1 年 <strong>${fmtEtfPct(L.ret_1y_total, true, 1)}</strong>（除息日以收盤價再投入，不計稅與手續費）${note}<br/>`;
}

// 台股 ETF 由官方逐日行情與除權息表算出的指標 (價格報酬不含息；含息報酬與配息率另列)
function etfLiveMetricsHtml(e) {
  const L = e.live;
  if (!L) return '';
  const p = (v) => fmtEtfPct(v, true, 1);
  return `
    <div style="margin-top:10px; padding:10px 12px; border-radius:8px; background:rgba(6,78,59,0.22); border:1px solid rgba(52,211,153,0.35); font-size:13.5px; line-height:1.7;">
      <strong style="color:#34d399;">📡 即時指標（官方逐日行情，${esc(L.last_date)}；共 ${L.history_days} 個交易日資料）</strong><br/>
      ${etfSparkline(L.curve)}<span style="font-size:12px; color:var(--text-secondary);">近 1 年實際價格走勢（官方逐日收盤，不含息；起點 = 100）</span><br/>
      價格報酬（不含息）：1 月 ${p(L.ret_1m)}｜3 月 ${p(L.ret_3m)}｜6 月 ${p(L.ret_6m)}｜1 年 ${p(L.ret_1y)}<br/>
      ${etfDividendLine(L)}
      年化波動 ${fmtEtfPct(L.vol_ann, false, 1)}｜最大回撤 ${fmtEtfPct(L.mdd, false, 1)}｜距 1 年高點 ${fmtEtfPct(L.dd_from_high, true, 1)}｜Beta ${fmtEtfNum(L.beta, false, 2)}｜與加權指數相關 ${fmtEtfNum(L.corr_taiex, false, 2)}｜與 0050 相關 ${fmtEtfNum(L.corr_0050, false, 2)}<br/>
      外資+投信當日淨買賣 ${fmtEtfNum(L.insti_billion, true, 2)} 億元（占成交金額 ${fmtEtfPct(L.insti_ratio_pct, true, 2)}）｜20 日均成交值 ${fmtEtfNum(L.turnover_20d_billion, false, 2)} 億元
      ${L.split_break ? `<div style="font-size:12.5px; color:#fbbf24; margin-top:4px;">⚠️ 價格歷史在 ${esc(L.split_break)} 有分割／合併造成的斷層（單日變動超過 35%，不是真實漲跌），以上指標與走勢只使用該日之後的資料。</div>` : ''}
      <div style="font-size:12px; color:var(--text-secondary); margin-top:4px;">淨值／折溢價、3／5 年報酬與初級市場申贖沒有官方即時來源，一律顯示 N/A；配息率與含息報酬由證交所／櫃買除權息表計算（上市未滿一年者留空）；規模、費用率、追蹤誤差與持股權重是人工維護（非即時）。</div>
    </div>`;
}

/* =========================================================================
   🎯 ETF 投資決策中心 (台灣 ETF ＋ 美國 ETF)｜可讀性全面優化＆七大視覺圖表渲染引擎
   ========================================================================= */
let ETF_DEEP_MODE = false;
let ETF_MAIN_TAB = 'TW'; // 'TW' | 'US' | 'BOND' | 'SECTOR' | 'ALL'
let ETF_EXPANDED_SET = new Set();
let ETF_PERF_HORIZON = '1Y'; // '1Y' | '3Y' | '5Y'
let ETF_COMPARE_CODES = ['0050', '0052', '00878', 'VOO', 'SMH', '00937B'];
// 第九節強制規範：使用者沒有提供持倉資料前，不得自行假設持倉！(初始為空陣列)
let USER_PORTFOLIO = [];
// 清單預設只顯示前幾檔，避免頁面過長（搜尋、篩選或專業模式時顯示全部）
const ETF_PAGE_SIZE = 6;
let ETF_SHOW_ALL = false;

function setEtfDetailMode(deep) {
  ETF_DEEP_MODE = !!deep;
  const simple = document.getElementById('etfModeBtnSimple');
  const pro = document.getElementById('etfModeBtnPro');
  if (simple) simple.classList.toggle('on', !ETF_DEEP_MODE);
  if (pro) pro.classList.toggle('on', ETF_DEEP_MODE);
  if (ETF_DEEP_MODE) ETF_SHOW_ALL = true;
  renderEtfLists();
}

function toggleEtfDetailMode() { setEtfDetailMode(!ETF_DEEP_MODE); }

function switchEtfMainTab(tab) {
  ETF_MAIN_TAB = tab;
  if (!ETF_DEEP_MODE) ETF_SHOW_ALL = false;
  ['TW', 'US', 'BOND', 'SECTOR', 'ALL'].forEach(t => {
    const el = document.getElementById('etfTab_' + t);
    if (el) el.classList.toggle('active', t === tab);
  });
  renderEtfLists();
}

function toggleSingleEtfCard(code, evt) {
  if (evt) evt.stopPropagation();
  if (ETF_EXPANDED_SET.has(code)) {
    ETF_EXPANDED_SET.delete(code);
  } else {
    ETF_EXPANDED_SET.add(code);
  }
  const panel = document.getElementById('etfLayer2_' + code);
  const btn = document.getElementById('etfExpandBtn_' + code);
  const isOpen = ETF_DEEP_MODE || ETF_EXPANDED_SET.has(code);
  if (panel) panel.classList.toggle('open', isOpen);
  if (btn) {
    btn.innerHTML = isOpen
      ? '▲ 收合完整分析'
      : '▼ 查看完整分析';
  }
}

function jumpToEtfCard(code) {
  ETF_SHOW_ALL = true;
  switchEtfMainTab('ALL');
  ETF_EXPANDED_SET.add(code);
  renderEtfLists();
  const el = document.getElementById('etfCard_' + code);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.style.boxShadow = '0 0 0 3px #38bdf8, 0 12px 32px rgba(56,189,248,0.35)';
    setTimeout(() => { el.style.boxShadow = ''; }, 2600);
  }
}

function toggleEtfSec5Panel() {
  const box = document.getElementById('etfSec5DeepContainer');
  if (!box) return;
  box.style.display = box.style.display === 'none' ? 'block' : 'none';
}

// 嚴格語意色彩紀律：綠色＝正向、紅色＝風險/負向、橘色＝警示、藍色＝資訊/中性
function concABadge(c) {
  if (c === '適合進一步研究') return '<span class="badge badge-lvl4">🟢 適合進一步研究</span>';
  if (c === '需注意集中風險') return '<span class="badge badge-grade-C">🟠 需注意集中風險</span>';
  if (c === '條件普通') return '<span class="badge badge-lvl3">🔵 條件普通</span>';
  if (c === '不符合配置角色') return '<span class="badge badge-lvlR">🔴 不符合配置角色</span>';
  return `<span class="badge badge-unratable">${c}</span>`;
}

function concBBadge(c) {
  if (c === '條件相對有利') return '<span class="badge badge-lvl4">🟢 條件相對有利</span>';
  if (c === '持續觀察') return '<span class="badge badge-lvl3">🔵 持續觀察</span>';
  if (c === '等待更佳條件') return '<span class="badge badge-grade-C">🟠 等待更佳條件</span>';
  if (c === '風險偏高') return '<span class="badge badge-lvlR">🔴 風險偏高</span>';
  return `<span class="badge badge-unratable">${c}</span>`;
}

// ===== 第一區：全球市場環境 (數字全部來自 STATE.macro_latest／institutional_flows，逐項標示即時或手寫) =====
const NDC_LAMPS = [[38, '紅燈'], [32, '黃紅燈'], [23, '綠燈'], [17, '黃藍燈'], [9, '藍燈']];   // 國發會景氣對策信號分數級距

function ndcLampName(score) {
  const hit = NDC_LAMPS.find(([lo]) => score >= lo);
  return hit ? hit[1] : '';
}

function globalEnvFlows() {
  const rows = ((STATE && STATE.institutional_flows) || []).filter(r => r.period_type === 'DAILY' && r.text_source === 'live' && r.release_date);
  rows.sort((a, b) => String(a.release_date).localeCompare(String(b.release_date)));
  if (!rows.length) return null;
  const last = rows[rows.length - 1];
  const month = String(last.release_date).slice(0, 7);
  const inMonth = rows.filter(r => String(r.release_date).slice(0, 7) === month && r.foreign_net_billion != null);
  return { last, month, days: inMonth.length, foreignMonth: inMonth.reduce((s, r) => s + Number(r.foreign_net_billion), 0) };
}

function renderGlobalEnv() {
  const macros = {};
  ((STATE && STATE.macro_latest) || []).forEach(m => { macros[m.metric_code] = m; });
  const isLive = m => String(m.revision_version || '').startsWith('live') || m.metric_code === 'TW_TAIEX_INDEX';
  const num = (v, d) => Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 2 : d });
  const signed = (v, d) => (Number(v) > 0 ? '+' : '') + num(v, d);
  const cls = v => Number(v) > 0 ? 'pos' : Number(v) < 0 ? 'neg' : '';
  const badge = live => live ? '<span class="badge badge-grade-A" title="官方開放資料自動更新">即時</span>' : '<span class="badge badge-grade-C" title="人工維護的數值，不會自動更新">手寫</span>';
  let nLive = 0, nHand = 0;
  // 一列：標籤 / 數值 / 資料期間 / 來源；沒有資料就顯示「無資料」，不猜
  const line = (label, valueHtml, asOf, live) => {
    if (valueHtml == null) return `<tr><td>${label}</td><td style="color:var(--text-muted);">無資料</td><td></td><td></td></tr>`;
    if (live) nLive++; else nHand++;
    return `<tr><td>${label}</td><td style="text-align:right; font-weight:700;">${valueHtml}</td><td style="font-size:11px; color:var(--text-muted);">${esc(asOf || '')}</td><td>${badge(live)}</td></tr>`;
  };
  const mline = (label, code, fmt) => {
    const m = macros[code];
    if (!m || m.cleaned_value == null) return line(label, null);
    return line(label, fmt(m), m.period_covered, isLive(m));
  };
  const card = (color, title, heroHtml, rows) => `
      <div class="etf-clean-card" style="border-top:4px solid ${color};">
        <div style="font-size:16px; font-weight:800; color:#94a3b8;">${title}</div>
        <div class="etf-hero-num" style="margin:10px 0 8px 0;">${heroHtml}</div>
        <table style="width:100%; font-size:13px;"><tbody>${rows.join('')}</tbody></table>
      </div>`;
  const hero = (text, extraCls) => `<span class="${extraCls || ''}">${text}</span>`;
  const flows = globalEnvFlows();

  const ndc = macros.TW_NDC_SCORE;
  const c1 = card('#10b981', '1. 台灣市場狀況',
    ndc && ndc.cleaned_value != null ? hero(`景氣 ${num(ndc.cleaned_value, 0)} 分 ${ndcLampName(Number(ndc.cleaned_value))}`) : hero('景氣燈號 無資料'), [
      mline('景氣燈號分數 (9~45)', 'TW_NDC_SCORE', m => `${num(m.cleaned_value, 0)} 分 ${ndcLampName(Number(m.cleaned_value))}`),
      mline('上市櫃月營收合計', 'TW_MOPS_TOTAL_REV', m => `${num(m.cleaned_value, 2)} 兆元 <span class="${cls(m.yoy_pct)}">(${signed(m.yoy_pct, 1)}%)</span>`),
      mline('海關出口 (年增)', 'TW_CUSTOMS_EXPORTS', m => `${num(m.cleaned_value, 1)} 億美元 <span class="${cls(m.yoy_pct)}">(${signed(m.yoy_pct, 1)}%)</span>`),
      mline('外銷訂單 (年增)', 'TW_EXPORT_ORDERS', m => `<span class="${cls(m.yoy_pct)}">${signed(m.yoy_pct, 1)}%</span>`),
      mline('加權指數', 'TW_TAIEX_INDEX', m => `${num(m.cleaned_value, 0)} 點`),
    ]);

  const vix = macros.INTL_VIX;
  const c2 = card('#f59e0b', '2. 美國市場狀況',
    vix && vix.cleaned_value != null ? hero(`VIX ${num(vix.cleaned_value, 1)}`, Number(vix.cleaned_value) >= 25 ? 'neg' : '') : hero('VIX 無資料'), [
      mline('VIX 恐慌指數', 'INTL_VIX', m => num(m.cleaned_value, 1)),
      mline('費城半導體指數 (SOX)', 'INTL_SOX_INDEX', m => `${num(m.cleaned_value, 0)} 點`),
      mline('美元指數 (DXY)', 'INTL_DXY', m => num(m.cleaned_value, 2)),
      mline('聯準會利率上限', 'US_FED_RATE_UPPER', m => `${num(m.cleaned_value, 2)}%`),
    ]);

  const us10 = macros.US_10Y_YIELD;
  const c3 = card('#38bdf8', '3. 利率環境',
    us10 && us10.cleaned_value != null ? hero(`美債10Y ${num(us10.cleaned_value, 2)}%`, '') : hero('美債10Y 無資料'), [
      mline('美國 10 年期公債殖利率', 'US_10Y_YIELD', m => `${num(m.cleaned_value, 2)}%`),
      mline('五大銀行新承作放款利率', 'TW_FIVE_BANK_NEW_RATE', m => `${num(m.cleaned_value, 3)}%`),
      mline('M1B 年增率', 'TW_M1B_YOY', m => `${num(m.cleaned_value, 2)}%`),
      mline('M2 年增率', 'TW_M2_YOY', m => `${num(m.cleaned_value, 2)}%`),
      mline('新台幣兌美元', 'TW_USD_TWD', m => num(m.cleaned_value, 2)),
    ]);

  const fl = flows;
  const flowRows = [];
  if (fl) {
    nLive += 3;
    flowRows.push(`<tr><td>外資本月累計 (${esc(fl.month)}，${fl.days} 個交易日)</td><td style="text-align:right; font-weight:700;" class="${cls(fl.foreignMonth)}">${signed(fl.foreignMonth, 0)} 億</td><td style="font-size:11px; color:var(--text-muted);">截至 ${esc(fl.last.release_date)}</td><td>${badge(true)}</td></tr>`);
    flowRows.push(`<tr><td>最新交易日 外資</td><td style="text-align:right; font-weight:700;" class="${cls(fl.last.foreign_net_billion)}">${signed(fl.last.foreign_net_billion, 1)} 億</td><td style="font-size:11px; color:var(--text-muted);">${esc(fl.last.release_date)}</td><td>${badge(true)}</td></tr>`);
    flowRows.push(`<tr><td>最新交易日 三大法人合計</td><td style="text-align:right; font-weight:700;" class="${cls(fl.last.total_3insti_billion)}">${signed(fl.last.total_3insti_billion, 1)} 億</td><td style="font-size:11px; color:var(--text-muted);">${esc(fl.last.release_date)}</td><td>${badge(true)}</td></tr>`);
  } else {
    flowRows.push(line('外資買賣超', null));
  }
  flowRows.push(mline('證券劃撥存款餘額', 'TW_SEC_GIRO_BAL', m => `${num(m.cleaned_value, 2)} 兆元`));
  flowRows.push(mline('外匯存底', 'TW_FX_RESERVES', m => `${num(m.cleaned_value, 0)} 億美元`));
  const c4 = card('#10b981', '4. 全球與台灣資金流向',
    fl ? hero(`外資本月 ${signed(fl.foreignMonth, 0)} 億`, cls(fl.foreignMonth)) : hero('外資買賣超 無資料'), flowRows);

  const html = c1 + c2 + c3 + c4;
  const note = `✅ 四張卡的數字都是從資料讀出來的：標「即時」的來自官方開放資料並隨每次同步更新（共 ${nLive} 項）；標「手寫」的是人工維護、不會自動更新的數值（共 ${nHand} 項，例如費半、美元指數、外銷訂單、劃撥存款，沒有免費的官方 API），看資料期間自行判斷是否過期。已移除先前手寫的市場敘事文字。`;
  return { html, note };
}

// ===== 第四區：白話市場解讀 (規則產生：數字全部來自台股 ETF 的即時計算與已標示的人工維護欄位，沒有手寫敘事) =====
function renderEtfPlainReading(etfs) {
  const n1 = (v, d) => (v == null || isNaN(Number(v))) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 1 : d });
  const sg = (v) => (v == null || isNaN(Number(v))) ? '—' : (Number(v) > 0 ? '+' : '') + n1(v);
  const cl = (v) => (v == null || isNaN(Number(v))) ? '' : Number(v) > 0 ? 'pos' : Number(v) < 0 ? 'neg' : '';
  const tw = (etfs || []).filter(e => e.score_source === 'live');
  const twNon = tw.filter(e => e.is_leveraged_or_inverse === 0);
  const nm = e => `<strong>${esc(e.etf_code)}</strong> ${esc(e.etf_name)}`;
  const card = (color, title, body) => `
      <div class="etf-clean-card" style="border-left:5px solid ${color};">
        <div style="font-size:17px; font-weight:700; color:#f8fafc; margin-bottom:10px; line-height:1.5;">${title}</div>
        <div style="font-size:15px; color:#cbd5e1; line-height:1.75;">${body}</div>
      </div>`;
  const none = '目前沒有足夠的即時資料可以解讀。';
  const macros = {};
  ((STATE && STATE.macro_latest) || []).forEach(m => { macros[m.metric_code] = m; });
  const us10 = macros.US_10Y_YIELD;
  const us10Live = us10 && String(us10.revision_version || '').startsWith('live');

  // 1. 長期分數 vs 短期結論
  let c1 = none;
  if (twNon.length) {
    const by = (k) => [...twNon].sort((a, b) => (b[k] || 0) - (a[k] || 0));
    const topA = by('total_score_a_long_term')[0], topB = by('total_score_b_short_mid')[0];
    const cnt = {};
    twNon.forEach(e => { cnt[e.conclusion_b_short_mid] = (cnt[e.conclusion_b_short_mid] || 0) + 1; });
    const parts = ['條件相對有利', '持續觀察', '等待更佳條件', '風險偏高'].filter(k => cnt[k]).map(k => `${k} ${cnt[k]} 檔`);
    const gap = twNon.filter(e => (e.total_score_a_long_term || 0) >= 65 && ['風險偏高', '等待更佳條件'].includes(e.conclusion_b_short_mid));
    const ref = twNon.find(e => e.live && e.live.facts && e.live.facts.b1 && !/N\/A/.test(e.live.facts.b1));
    c1 = `• <strong>兩個模型看的時間不同：</strong>模型 A 看 3～10 年的長期配置品質，模型 B 看 1～12 個月的進場環境，所以同一檔 ETF 常常「長期還不錯、短期卻建議等」。<br/>
      • <strong>現在的台股 ETF（${twNon.length} 檔，不含槓反）：</strong>長期分數最高是 ${nm(topA)}（${n1(topA.total_score_a_long_term)} 分）；短期分數最高是 ${nm(topB)}（${n1(topB.total_score_b_short_mid)} 分）；短期結論分布：${parts.join('、')}。<br/>
      • <strong>長期分數 65 分以上、但短期不建議追的：</strong>${gap.length ? gap.map(e => `${nm(e)}（A ${n1(e.total_score_a_long_term)}／B ${n1(e.total_score_b_short_mid)}）`).join('、') : '目前沒有'}。白話來說：值得放進長期清單，但短期適合分批、不要一次重壓。<br/>
      ${ref ? `• <strong>短期環境的一項依據：</strong>${esc(ref.live.facts.b1)}。<br/>` : ''}
      <span style="font-size:12px; color:var(--text-muted);">分數由官方逐日行情用公式計算；台股公式的「大盤環境」子分數偏保守，整體分數較低是正常的。美股 ETF 沒有官方來源，這裡不解讀。</span>`;
  }

  // 2. 高股息 ETF：配息率 vs 實際含息報酬
  const hy = twNon.filter(e => e.asset_class === '股票' && /高股息|高息/.test(e.sub_category || '') && e.live);
  let c2 = none;
  if (hy.length) {
    const rows = hy.map(e => {
      const L = e.live;
      return `<tr><td>${nm(e)}</td><td style="text-align:right;">${n1(L.dividend_yield_pct, 2)}%</td><td style="text-align:right;" class="${cl(L.ret_1y)}">${sg(L.ret_1y)}%</td><td style="text-align:right;" class="${cl(L.ret_1y_total)}">${sg(L.ret_1y_total)}%</td></tr>`;
    }).join('');
    c2 = `• <strong>配息率不等於賺到的錢：</strong>這裡的配息率是「過去 12 個月實際配出的現金股利 ÷ 最新收盤價」（證交所／櫃買除權息表計算）；真正的成果要看「含息報酬」= 配息 + 股價漲跌。股價若跌掉的比配息還多，含息報酬就會比配息率低。<br/>
      <div style="overflow-x:auto; margin:8px 0;"><table style="width:100%; font-size:13px;"><thead><tr><th>ETF</th><th style="text-align:right;">近 12 月配息率</th><th style="text-align:right;">近 1 年價格報酬</th><th style="text-align:right;">近 1 年含息報酬</th></tr></thead><tbody>${rows}</tbody></table></div>
      <span style="font-size:12px; color:var(--text-muted);">「—」代表歷史不足一年或除權息表沒有成功取得，不當作 0。配息中有多少來自價差或本金（收益平準金），發行商每期公告才有，本站沒有官方逐期資料，所以不拆解。</span>`;
  }

  // 3. 持股重疊：台積電佔比高的 ETF
  const heavy = twNon.filter(e => e.asset_class === '股票' && Number(e.max_single_weight_pct) >= 30 && (e.holdings || []).length)
    .sort((a, b) => b.max_single_weight_pct - a.max_single_weight_pct);
  let c3 = twNon.length ? '目前台股 ETF 沒有任何一檔的最大單一持股占比達 30%。' : none;
  if (heavy.length) {
    let pairs = '';
    if (heavy.length >= 2 && typeof computePairwiseOverlap === 'function') {
      const list = [];
      for (let i = 0; i < heavy.length; i++) for (let j = i + 1; j < heavy.length; j++) {
        const r = computePairwiseOverlap(heavy[i], heavy[j]);
        list.push(`${esc(heavy[i].etf_code)} 與 ${esc(heavy[j].etf_code)} 重疊 <strong>${n1(r.overlapPct)}%</strong>`);
      }
      pairs = `• <strong>兩兩持股重疊度（前十大持股取較小權重加總）：</strong>${list.join('、')}。<br/>`;
    }
    const asOf = (heavy[0].holdings[0] || {}).as_of_date;
    c3 = `• <strong>名稱不同、底層可能是同一家公司：</strong>下列 ETF 的最大單一持股占比都在 30% 以上——${heavy.map(e => `${nm(e)}：${esc(e.max_single_holding_name)}`).join('、')}。<br/>
      ${pairs}• 同時持有這幾檔，表面上買了多檔，實際上有很大一部分資金押在同一檔股票上；要分散可以考慮搭配持股較分散的 ETF（例如最大單一持股占比低的高股息或債券 ETF）。<br/>
      <span style="font-size:12px; color:var(--text-muted);">持股與權重是人工維護（手寫）的前十大持股${asOf ? `，基準日 ${esc(asOf)}` : ''}，不會自動更新。</span>`;
  }

  // 4. 利率與債券 ETF
  const bonds = twNon.filter(e => e.asset_class === '債券' && e.live);
  let c4 = none;
  if (bonds.length) {
    const rows = bonds.map(e => {
      const L = e.live, dur = Number(e.bond_duration_years);
      return `<tr><td>${nm(e)}</td><td style="text-align:right;">${n1(L.dividend_yield_pct, 2)}%</td><td style="text-align:right;" class="${cl(L.ret_1y)}">${sg(L.ret_1y)}%</td><td style="text-align:right;">${n1(L.vol_ann)}%</td><td style="text-align:right;">${n1(L.mdd)}%</td><td style="text-align:right;">${dur > 0 ? '約 −' + n1(dur) + '%' : '—'}</td></tr>`;
    }).join('');
    c4 = `• <strong>${us10 && us10.cleaned_value != null ? `美國 10 年期公債殖利率目前 ${n1(us10.cleaned_value, 2)}%（${esc(us10.period_covered || '')}，${us10Live ? '即時' : '手寫'}）。` : ''}</strong>債券 ETF 的價格會反向跟著利率動：殖利率上升，價格下跌；存續期越長，跌得越多。<br/>
      <div style="overflow-x:auto; margin:8px 0;"><table style="width:100%; font-size:13px;"><thead><tr><th>ETF</th><th style="text-align:right;">近 12 月配息率</th><th style="text-align:right;">近 1 年價格報酬</th><th style="text-align:right;">年化波動度</th><th style="text-align:right;">最大回撤</th><th style="text-align:right;">殖利率 +1% 的價格影響</th></tr></thead><tbody>${rows}</tbody></table></div>
      <span style="font-size:12px; color:var(--text-muted);">「價格影響」= 存續期 × 1%，是粗略的估算；存續期是人工維護（手寫）的數字。美國的超短債、投資級公司債與長天期公債 ETF 沒有官方行情來源，這裡不比較。</span>`;
  }

  return [
    card('#f59e0b', '💡 長期分數很高，短期結論卻是「等待」或「風險偏高」，是什麼意思？', c1),
    card('#38bdf8', '💡 看高股息 ETF 只看配息率，會漏掉什麼？', c2),
    card('#f43f5e', '💡 同時買好幾檔台股 ETF 以為很分散？看看它們的最大持股', c3),
    card('#10b981', '💡 利率變動對債券 ETF 的影響有多大？', c4),
  ].join('');
}

function renderEtfDecisionCenter() {
  if (!STATE || !STATE.etf_center || !STATE.etf_center.etfs) return;
  const etfs = STATE.etf_center.etfs;

  // =====================================================================
  // 第一區：全球市場環境（台灣市場 / 美國市場 / 利率環境 / 全球資金流向）
  // =====================================================================
  // 第一區的數字都從 STATE 讀 (官方即時資料；沒有免費來源的才用手寫數值並標「手寫」)，不再放手寫的敘事文字
  const sec1Info = renderGlobalEnv();
  setSourceNote('etfSec1GlobalEnv', 'etfSec1Note', sec1Info.note);
  const sec1 = document.getElementById('etfSec1GlobalEnv');
  if (sec1) sec1.innerHTML = sec1Info.html;

  // =====================================================================
  // 第二區：ETF 決策摘要（長期配置環境 / 短中期進場環境 / 值得研究 / 注意風險）
  // =====================================================================
  const sec2 = document.getElementById('etfSec2DecisionSummary');
  if (sec2) {
    // 台股 ETF 是官方逐日行情用公式即時計算 (score_source = 'live')，美股 ETF 是手寫評分：兩者尺度不同 (台股公式對大盤環境偏保守，
    // 分數普遍較低)，混在同一個門檻下比較會讓美股全部「優先研究」、台股全部「高風險」，所以分來源各自呈現。
    const isLive = e => e.score_source === 'live';
    const nonLev = e => e.is_leveraged_or_inverse === 0;
    const twAll = etfs.filter(isLive), usAll = etfs.filter(e => !isLive(e));
    const twNon = twAll.filter(nonLev), usNon = usAll.filter(nonLev);
    const byA = (a, b) => (b.total_score_a_long_term || 0) - (a.total_score_a_long_term || 0);
    const byB = (a, b) => (b.total_score_b_short_mid || 0) - (a.total_score_b_short_mid || 0);

    const twTopA = [...twNon].sort(byA).slice(0, 4);
    const usCoreLong = usNon.filter(e => e.total_score_a_long_term >= 84);
    const twTopB = [...twNon].sort(byB).slice(0, 4);
    const twFav = twNon.filter(e => e.conclusion_b_short_mid === '條件相對有利');
    const usFav = usNon.filter(e => e.conclusion_b_short_mid === '條件相對有利' && e.total_score_a_long_term >= 78);
    const usDiverge = usNon.filter(e => e.total_score_a_long_term >= 78 && e.conclusion_b_short_mid === '等待更佳條件');
    const twRisk = twAll.filter(e => e.is_leveraged_or_inverse === 1 || e.conclusion_b_short_mid === '風險偏高');
    const usRisk = usAll.filter(e => e.is_leveraged_or_inverse === 1 || e.conclusion_b_short_mid === '風險偏高' || e.total_score_b_short_mid < 62);

    const makePill = (e, col) => `
      <span class="etf-pill" style="--pill-col:${col};" onclick="jumpToEtfCard('${esc(e.etf_code)}')" title="${esc(e.etf_code)} ${esc(e.etf_name)}">
        <b>${esc(e.etf_code)}</b><span>${esc(e.etf_name)}</span>
      </span>`;
    const row = (label, list, col, score) => `
      <div style="margin-top:8px;">
        <div style="font-size:13px; font-weight:700; color:#94a3b8; margin-bottom:4px;">${label}</div>
        ${list.length ? list.map(e => makePill(e, col)).join('') : '<span style="font-size:13px; color:var(--text-secondary);">目前沒有符合條件的 ETF</span>'}
      </div>`;
    const TW = '🇹🇼 台股（即時公式評分）', US = '🇺🇸 美股（手寫評分，不會更新）';

    setSourceNote('etfSec2DecisionSummary', 'etfSec2Note',
      'ℹ️ 台股 ETF 的分數由官方逐日行情用公式即時計算，美股 ETF 是手寫評分；兩者的尺度與方法不同（台股公式的「大盤環境」子分數目前偏保守，整體分數較低），所以下方分開呈現，不用同一個門檻互相比較。');

    sec2.innerHTML = `
      <div class="etf-clean-card" style="border-left:5px solid #10b981;">
        <div style="font-size:16px; font-weight:800; color:#34d399;">【模型 A】長期配置環境（3～10年視角）</div>
        <div class="etf-hero-num pos" style="margin:8px 0;">台股前 ${twTopA.length} 名・美股 ${usCoreLong.length} 檔高分</div>
        ${row(TW + '：模型 A 分數最高', twTopA, '#10b981')}
        ${row(US + '：模型 A ≥ 84 分', usCoreLong.slice(0, 7), '#10b981')}
      </div>

      <div class="etf-clean-card" style="border-left:5px solid #f59e0b;">
        <div style="font-size:16px; font-weight:800; color:#fbbf24;">【模型 B】短中期進場環境（長短線是否一致？）</div>
        <div class="etf-hero-num" style="color:#fbbf24; margin:8px 0;">台股 ${twFav.length} 檔順風・美股 ${usFav.length} 檔順風 / ${usDiverge.length} 檔分歧</div>
        ${row(TW + '：模型 B 分數最高', twTopB, '#f59e0b')}
        ${row(US + '：長期佳、短期等待', usDiverge, '#f59e0b')}
      </div>

      <div class="etf-clean-card" style="border-left:5px solid #10b981;">
        <div style="font-size:16px; font-weight:800; color:#34d399;">🟢 短中期條件相對有利的 ETF</div>
        <div class="etf-hero-num pos" style="margin:8px 0;">${twFav.length + usFav.length} 檔</div>
        ${row(TW, twFav, '#10b981')}
        ${row(US + '：長短線雙軌順風', usFav, '#10b981')}
      </div>

      <div class="etf-clean-card" style="border-left:5px solid #f43f5e;">
        <div style="font-size:16px; font-weight:800; color:#fb7185;">🔴 需要注意風險的 ETF（槓反 / 短中期環境偏弱）</div>
        <div class="etf-hero-num neg" style="margin:8px 0;">台股 ${twRisk.length} 檔・美股 ${usRisk.length} 檔</div>
        ${row(TW + '：槓桿型或模型 B 為「風險偏高」', twRisk, '#f43f5e')}
        ${row(US, usRisk, '#f43f5e')}
      </div>
    `;
  }

  // =====================================================================
  // 第四區：AI 白話市場解讀（無艱深術語，一眼看懂四大核心問題）
  // =====================================================================
  setSourceNote('etfSec4AiPlainGrid', 'etfSec4Note',
    '✅ 四則白話解讀由規則從資料產生，不是手寫文章：配息率、報酬、波動度、分數都是官方行情即時計算；持股權重與債券存續期是人工維護（手寫）的欄位，卡片內有標明。美國 ETF 沒有官方來源，不在這裡解讀。');
  const sec4 = document.getElementById('etfSec4AiPlainGrid');
  if (sec4) sec4.innerHTML = renderEtfPlainReading(etfs);

  // 初始化第五區下拉選單
  const portSel = document.getElementById('portAddEtfSelect');
  if (portSel && !portSel.options.length) {
    portSel.innerHTML = etfs.map(e =>
      `<option value="${e.etf_code}">[${e.listing_market}] ${e.etf_code} ${e.etf_name} (${e.sub_category})</option>`
    ).join('');
  }
  const c5Sel = document.getElementById('chart5EtfSelect');
  if (c5Sel && !c5Sel.options.length) {
    c5Sel.innerHTML = etfs.map(e =>
      `<option value="${e.etf_code}">[${e.listing_market}] ${e.etf_code} ${e.etf_name} (前十大集中度 ${e.top10_concentration_pct}%)</option>`
    ).join('');
  }

  renderEtfLists();
  renderChart1Flows();
  renderChart2And3Scores();
  renderChart4PerfCurve();
  renderChart5HoldingsDist();
  renderEtfComparator();
  renderChart7RiskReturn();
  renderUserPortfolioAnalysis();
  renderEtfReportsAndBacktests();
  renderArgonMultiAgentCenter();
}

