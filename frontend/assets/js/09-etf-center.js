/* ETF 數字格式化：官方沒有來源而留空的欄位 (淨值、折溢價、配息率、含息報酬…) 一律顯示 N/A，不可印出 null 或 NaN */
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

function renderEtfDecisionCenter() {
  if (!STATE || !STATE.etf_center || !STATE.etf_center.etfs) return;
  const etfs = STATE.etf_center.etfs;

  // =====================================================================
  // 第一區：全球市場環境（台灣市場 / 美國市場 / 利率環境 / 全球資金流向）
  // =====================================================================
  setSourceNote('etfSec1GlobalEnv', 'etfSec1Note', '⚠️ 下方「全球市場環境」四張卡是 2026-11-21 前後手寫的市場摘要（卡片標題已寫明資料基準日），沒有每日的官方來源，不會隨資料更新。');
  const sec1 = document.getElementById('etfSec1GlobalEnv');
  if (sec1) {
    sec1.innerHTML = `
      <div class="etf-clean-card" style="border-top:4px solid #10b981;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:16px; font-weight:800; color:#94a3b8;">1. 台灣市場狀況</span>
          <span class="badge badge-lvl4">🟢 基本面強勁擴張</span>
        </div>
        <div class="etf-hero-num pos" style="margin:10px 0 6px 0;">景氣 41 分紅燈</div>
        <div style="font-size:16px; font-weight:800; color:#f8fafc; margin-bottom:6px;">
          上市櫃10月營收 6.86 兆 (+45.5%)・外銷訂單 +78.3%
        </div>
        <div style="font-size:15px; color:#cbd5e1; line-height:1.65;">
          AI 伺服器與半導體先進製程帶動台灣企業獲利創歷史新高（0050 成分股10月加權營收年增 <strong>+55.4%</strong>），長線基本面極為扎實，惟需留意美國科技股回檔帶來的短線震盪。
        </div>
      </div>

      <div class="etf-clean-card" style="border-top:4px solid #f59e0b;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:16px; font-weight:800; color:#94a3b8;">2. 美國市場狀況</span>
          <span class="badge badge-grade-C">🟠 長線優質・短期震盪</span>
        </div>
        <div class="etf-hero-num" style="color:#fbbf24; margin:10px 0 6px 0;">S&amp;P 本益比 27.4x</div>
        <div style="font-size:16px; font-weight:800; color:#f8fafc; margin-bottom:6px;">
          11/20 費城半導體單日重挫 <span class="neg">-10.67%</span>・VIX 跳升
        </div>
        <div style="font-size:15px; color:#cbd5e1; line-height:1.65;">
          美國大型科技巨頭長線護城河依然穩固（VOO/QQQ 長期高分），但估值位於歷史 88% 高位，加上費半暴跌引發短線去槓桿，目前美股科技呈現「<strong>長期適合研究、短期等待更佳條件</strong>」。
        </div>
      </div>

      <div class="etf-clean-card" style="border-top:4px solid #38bdf8;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:16px; font-weight:800; color:#94a3b8;">3. 利率環境</span>
          <span class="badge badge-lvl3">🔵 高利率鎖利期</span>
        </div>
        <div class="etf-hero-num" style="color:#38bdf8; margin:10px 0 6px 0;">美債10Y 4.97%</div>
        <div style="font-size:16px; font-weight:800; color:#f8fafc; margin-bottom:6px;">
          台灣五大銀行放款利率 2.254%（創17年新高）
        </div>
        <div style="font-size:15px; color:#cbd5e1; line-height:1.65;">
          美債殖利率逼近 5% 大關，使<strong>美元超短債 (SGOV) 與投資級公司債 (00937B/LQD)</strong> 具備 5.1%～5.85% 優質鎖利空間；台灣利率走升則推升<strong>銀行金融股 (0055)</strong> 淨利差擴張，但壓抑高舉債 REITs (VNQ)。
        </div>
      </div>

      <div class="etf-clean-card" style="border-top:4px solid #10b981;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:16px; font-weight:800; color:#94a3b8;">4. 全球與台灣資金流向</span>
          <span class="badge badge-lvl4">🟢 內資大買市值與債券</span>
        </div>
        <div class="etf-hero-num pos" style="margin:10px 0 6px 0;">0050 吸金 +2,200億</div>
        <div style="font-size:16px; font-weight:800; color:#f8fafc; margin-bottom:6px;">
          劃撥存款 4.70 兆創高 vs 外資11月賣超 <span class="neg">-5,495億</span>
        </div>
        <div style="font-size:15px; color:#cbd5e1; line-height:1.65;">
          儘管外資因費半重挫而提款台股，台灣內資交割戶資金充沛，趁回檔大舉申購<strong>被動市值型 (0050/006208)</strong> 與<strong>投等債 (00937B)</strong>；反觀主動式 ETF (00400A) 與槓桿 ETF 遭遇資金撤出。
        </div>
      </div>
    `;
  }

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
  setSourceNote('etfSec4AiPlainGrid', 'etfSec4Note', '⚠️ 下方四則白話解讀是 2026-11-21 前後手寫的文章，引用當時的市場數字與美股手寫評分，不會隨資料更新。');
  const sec4 = document.getElementById('etfSec4AiPlainGrid');
  if (sec4) {
    sec4.innerHTML = `
      <div class="etf-clean-card" style="border-left:5px solid #f59e0b;">
        <div style="font-size:17px; font-weight:700; color:#f8fafc; margin-bottom:10px; line-height:1.5;">
          💡 白話解讀 1：為什麼美股科技 ETF (QQQ / SMH / VOO)「長期分數很高」，但「短期分數卻建議等待」？
        </div>
        <div style="font-size:15.5px; color:#cbd5e1; line-height:1.75;">
          • <strong>長期角度（3～10年）：</strong>微軟、蘋果、輝達與台積電掌握全球 AI 與雲端核心獲利，長期競爭力無可取代，所以<strong>模型 A 長期配置給出 81～92 分的高分</strong>。<br/>
          • <strong>短期角度（1～12個月）：</strong>目前美股本益比高達 27.4 倍（歷史偏貴區間），加上 11/20 費城半導體指數單日重挫 <strong>-10.67%</strong>，短線波動劇烈。因此<strong>模型 B 提醒「等待更佳條件」</strong>——白話來說就是：<strong>好東西值得放進長期清單，但現在適合趁回檔分批慢慢買，不要在劇烈震盪時一次重壓。</strong>
        </div>
      </div>

      <div class="etf-clean-card" style="border-left:5px solid #38bdf8;">
        <div style="font-size:17px; font-weight:700; color:#f8fafc; margin-bottom:10px; line-height:1.5;">
          💡 白話解讀 2：買高股息 ETF (0056 / 00878 / 00919) 只看「配息率 8%～10%」會有什麼盲點？
        </div>
        <div style="font-size:15.5px; color:#cbd5e1; line-height:1.75;">
          • <strong>配息從哪裡來更重要：</strong>本系統把每檔高股息 ETF 的配息拆成三塊——「<strong>真正的公司股利</strong>」、「<strong>賣股票賺的價差（資本利得）</strong>」與「<strong>收益平準金（自己的本金）</strong>」。<br/>
          • 目前台股高股息 ETF 的真實股息殖利率約為 4%～5%，其餘約 <strong>32%～40% 來自過去累積的已實現價差</strong>。若未來股市震盪、沒有價差可配，配息率就會回歸正常水準；相比之下，具備低波動選股邏輯的 <strong>00713</strong> 或美國純股息成長型 <strong>SCHD（100% 來自真實股息）</strong> 現金流永續性更穩健。
        </div>
      </div>

      <div class="etf-clean-card" style="border-left:5px solid #f43f5e;">
        <div style="font-size:17px; font-weight:700; color:#f8fafc; margin-bottom:10px; line-height:1.5;">
          💡 白話解讀 3：同時買「0050 ＋ 0052 ＋ 00881」以為很分散？小心全部都在買台積電！
        </div>
        <div style="font-size:15.5px; color:#cbd5e1; line-height:1.75;">
          • <strong>名稱不同、底層卻是同一家公司：</strong>0050 的台積電佔比高達 <strong>58.2%</strong>，0052 的台積電佔比更高達 <strong>63.5%</strong>，00881 也有超過 <strong>33%</strong> 的台積電。<br/>
          • 如果您同時持有這幾檔 ETF，表面上買了 3 檔不同產品，實際上<strong>超過一半以上的資金都押在台積電單一檔股票上</strong>（兩兩重疊度高達 62.6%）。建議搭配金融股 (<strong>0055</strong>)、低波高息 (<strong>00713</strong>)、美股價值股 (<strong>SCHD</strong>) 或債券 ETF (<strong>00937B / SGOV</strong>) 才能真正達到分散風險的效果。
        </div>
      </div>

      <div class="etf-clean-card" style="border-left:5px solid #10b981;">
        <div style="font-size:17px; font-weight:700; color:#f8fafc; margin-bottom:10px; line-height:1.5;">
          💡 白話解讀 4：現在美債殖利率將近 5%，「超短債、投資級公司債、20年長天期公債」該怎麼選？
        </div>
        <div style="font-size:15.5px; color:#cbd5e1; line-height:1.75;">
          • <strong>想要穩健領息、不想承受價格波動 ➔ 選超短債 (SGOV)：</strong>存續期僅 0.1 年，幾乎零回撤（最大回撤僅 -0.15%），年化配息率 5.12%，是極佳的美元資金停泊港。<br/>
          • <strong>想要鎖定 5.5%～6% 高息兼顧降息潛力 ➔ 選投資級公司債 (00937B / LQD)：</strong>違約風險低且票息優渥，目前長短線評分雙雙領先。<br/>
          • <strong>想賭大幅降息賺價差 ➔ 20年長債 (00679B / TLT) 需注意波動：</strong>存續期長達 16.5 年，只要美債殖利率反彈 1%，價格就會下跌約 16%，波動度其實接近股票。
        </div>
      </div>
    `;
  }

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

