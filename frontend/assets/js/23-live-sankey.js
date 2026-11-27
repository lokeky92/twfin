/* =========================================================================
   即時資金流向桑基圖：三大法人 (外資／投信／自營商) → 各產業的「淨買賣金額」(億元)
   資料來自後端 STATE.live_sankey (backend/live_scoring.flow_matrix)，全部是官方當日盤後資料，沒有手寫數字。
   - 左欄：各法人的「買超」總額 → 流向各產業 (綠色流帶)
   - 中欄：產業 (高度 = 該產業買超 + 賣超的總量，標示淨額)
   - 右欄：各產業對各法人的「賣超」 (紅色流帶) → 該法人的賣超總額
   每個 (法人, 產業) 的淨額只會是買超或賣超其中一種，所以同一對法人與產業不會同時出現綠帶與紅帶。
   原本的總體資金池桑基圖 (央行存款、外匯存款等月資料) 保留在「總體背景」分頁。
   ========================================================================= */
let SANKEY_MODE = 'live';

const LIVE_SANKEY_INST_COLORS = { foreign: '#60a5fa', itc: '#2dd4bf', dealer: '#c084fc' };

function liveSankeyFmt(v, d = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  return (v >= 0 ? '+' : '−') + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
}

function shortIndustryName(name) {
  // 資料表的產業名稱很長，畫在節點旁會重疊：取第一個頓號/「與」之前的主要名稱
  const n = String(name || '');
  const cut = n.search(/[、與]/);
  return cut > 1 ? n.slice(0, cut) : n;
}

function renderLiveSankey() {
  const box = document.getElementById('liveSankeyContainer');
  if (!box) return;
  const ls = STATE && STATE.live_sankey;
  const noteEl = document.getElementById('liveSankeyNote');
  const kpiEl = document.getElementById('liveSankeyKpis');
  const subEl = document.getElementById('liveSankeySub');
  if (!ls || !ls.available || !(ls.industries || []).length) {
    box.innerHTML = '<div class="callout" style="--callout-col:var(--accent-orange);">⚠️ 此快照沒有即時的法人買賣金額資料（需要個股收盤價與三大法人買賣超）。請等下一次排程同步，或切換到「總體背景」。</div>';
    if (kpiEl) kpiEl.innerHTML = '';
    if (noteEl) noteEl.textContent = '';
    return;
  }
  const inst = ls.institutions;   // [{key,label,buy,sell,net}]
  const inds = ls.industries;     // 依淨額由高到低
  if (subEl) subEl.textContent = `${ls.as_of || ''} 盤後｜單位：${ls.unit}｜流帶粗細＝淨買賣金額｜綠＝買超、紅＝賣超`;

  if (kpiEl) {
    kpiEl.innerHTML = inst.map(i => `
      <div class="kpi-tile" style="--kpi-col:${LIVE_SANKEY_INST_COLORS[i.key]};">
        <div class="kt-label">${esc(i.label)} 當日淨買賣</div>
        <div class="kt-value">${liveSankeyFmt(i.net)} 億</div>
        <div class="kt-note">買超 ${liveSankeyFmt(i.buy)} 億（${inds.filter(r => r.flows[i.key] > 0).length} 個產業）／賣超 ${liveSankeyFmt(-i.sell)} 億（${inds.filter(r => r.flows[i.key] < 0).length} 個產業）</div>
      </div>`).join('');
  }

  // --- 版面計算 -------------------------------------------------------
  const W = 1040, PAD_T = 24, NODE_W = 14, GAP = 9, MIN_H = 4;
  const XL = 190, XM = 505, XR = 820;                  // 左／中／右欄節點的左緣
  const grossInd = inds.map(r => r.buy + r.sell);
  const colTotals = [inst.reduce((a, i) => a + i.buy, 0), grossInd.reduce((a, b) => a + b, 0), inst.reduce((a, i) => a + i.sell, 0)];
  let H = Math.max(420, inds.length * 34 + PAD_T * 2);
  const usable = H - PAD_T * 2 - GAP * Math.max(inds.length - 1, 0);
  const k = usable / Math.max(colTotals[1], 1e-9);     // 每 1 億元對應的像素高度 (以中欄為準，三欄共用同一比例)

  // 中欄產業節點
  let y = PAD_T;
  const indNodes = inds.map(r => {
    const h = Math.max(MIN_H, (r.buy + r.sell) * k);
    const node = { r, y, h, inY: y, outY: y };
    y += h + GAP;
    return node;
  });
  // 左欄 / 右欄法人節點：垂直置中對齊中欄的範圍
  const midBottom = y - GAP;
  const stack = (vals, totalFor) => {
    const hs = vals.map(v => Math.max(MIN_H, v * k));
    const total = hs.reduce((a, b) => a + b, 0) + GAP * (vals.length - 1);
    let yy = PAD_T + Math.max(0, (midBottom - PAD_T - total) / 2);
    return hs.map(h => { const o = { y: yy, h, cur: yy }; yy += h + GAP; return o; });
  };
  const left = stack(inst.map(i => i.buy));
  const right = stack(inst.map(i => i.sell));

  const ribbon = (x0, yTop0, yBot0, x1, yTop1, yBot1) => {
    const mx = (x0 + x1) / 2;
    return `M ${x0} ${yTop0} C ${mx} ${yTop0}, ${mx} ${yTop1}, ${x1} ${yTop1} L ${x1} ${yBot1} C ${mx} ${yBot1}, ${mx} ${yBot0}, ${x0} ${yBot0} Z`;
  };

  let defs = '', ribbons = '', nodes = '', labels = '';
  let gid = 0;
  const grad = (c0, c1) => {
    const id = `lsg_${gid++}`;
    defs += `<linearGradient id="${id}" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="${c0}" stop-opacity="0.55"/><stop offset="100%" stop-color="${c1}" stop-opacity="0.55"/></linearGradient>`;
    return id;
  };

  indNodes.forEach(n => {
    inst.forEach((i, ii) => {
      const v = n.r.flows[i.key];
      if (!v) return;
      const th = Math.max(1.2, Math.abs(v) * k);
      const tip = `${i.label} ${v > 0 ? '買超' : '賣超'} ${shortIndustryName(n.r.name)}：${liveSankeyFmt(v)} 億元`;
      if (v > 0) {   // 法人(左) → 產業
        const ly = left[ii].cur; left[ii].cur += th;
        const my = n.inY; n.inY += th;
        const g = grad(LIVE_SANKEY_INST_COLORS[i.key], '#10b981');
        ribbons += `<path class="ls-rib" data-ind="${esc(n.r.id)}" data-inst="${i.key}" d="${ribbon(XL + NODE_W, ly, ly + th, XM, my, my + th)}" fill="url(#${g})" stroke="#10b981" stroke-opacity="0.35" stroke-width="0.6"><title>${esc(tip)}</title></path>`;
      } else {       // 產業 → 法人(右)
        const my = n.outY + 0; n.outY += th;
        const ry = right[ii].cur; right[ii].cur += th;
        const g = grad('#fb7185', LIVE_SANKEY_INST_COLORS[i.key]);
        ribbons += `<path class="ls-rib" data-ind="${esc(n.r.id)}" data-inst="${i.key}" d="${ribbon(XM + NODE_W, my, my + th, XR, ry, ry + th)}" fill="url(#${g})" stroke="#fb7185" stroke-opacity="0.35" stroke-width="0.6"><title>${esc(tip)}</title></path>`;
      }
    });
  });
  // 右側流帶起點要對齊產業節點的右緣、買進流帶終點對齊左緣 (上面已處理)；買進與賣出各自從節點頂端往下疊放，互不重疊

  inst.forEach((i, ii) => {
    const c = LIVE_SANKEY_INST_COLORS[i.key];
    const L = left[ii], R = right[ii];
    nodes += `<rect x="${XL}" y="${L.y}" width="${NODE_W}" height="${L.h}" rx="2" fill="${c}"/>`;
    nodes += `<rect x="${XR}" y="${R.y}" width="${NODE_W}" height="${R.h}" rx="2" fill="${c}"/>`;
    labels += `<text x="${XL - 8}" y="${L.y + L.h / 2 + 4}" text-anchor="end" font-size="13" font-weight="700" fill="#e2e8f0">${esc(i.label)} 買超 ${liveSankeyFmt(i.buy, 0)} 億</text>`;
    labels += `<text x="${XR + NODE_W + 8}" y="${R.y + R.h / 2 + 4}" text-anchor="start" font-size="13" font-weight="700" fill="#e2e8f0">${esc(i.label)} 賣超 ${liveSankeyFmt(-i.sell, 0)} 億</text>`;
  });
  // 小產業的節點很矮，標籤會互相疊在一起：由上往下排，每個標籤與上一個至少相隔 LABEL_PITCH，偏離節點時畫細線連回節點
  const LABEL_PITCH = 15;
  let prevLabel = -Infinity;
  indNodes.forEach(n => {
    const center = n.y + Math.max(n.h, 14) / 2 + 4;
    n.labelY = Math.max(center, prevLabel + LABEL_PITCH);
    prevLabel = n.labelY;
  });
  H = Math.max(H, prevLabel + 14);
  indNodes.forEach(n => {
    const netCol = n.r.net >= 0 ? '#34d399' : '#fb7185';
    nodes += `<rect class="ls-node" data-ind="${esc(n.r.id)}" x="${XM}" y="${n.y}" width="${NODE_W}" height="${n.h}" rx="2" fill="${netCol}" style="cursor:pointer" onclick="openIndustryByCode('${esc(n.r.id)}')" onmouseenter="liveSankeyHighlight('${esc(n.r.id)}')" onmouseleave="liveSankeyHighlight(null)"><title>${esc(shortIndustryName(n.r.name))}：淨 ${liveSankeyFmt(n.r.net)} 億（買超 ${liveSankeyFmt(n.r.buy)}／賣超 ${liveSankeyFmt(-n.r.sell)}）｜成交值 ${n.r.turnover.toLocaleString()} 億｜收盤價覆蓋率 ${Math.round(n.r.coverage * 100)}%</title></rect>`;
    const mid = n.y + n.h / 2;
    if (Math.abs(n.labelY - 4 - mid) > 5) labels += `<line x1="${XM + NODE_W}" y1="${mid.toFixed(1)}" x2="${XM + NODE_W + 6}" y2="${(n.labelY - 4).toFixed(1)}" stroke="#64748b" stroke-width="0.7"/>`;
    labels += `<text x="${XM + NODE_W + 8}" y="${n.labelY}" font-size="12.5" fill="#cbd5e1" style="cursor:pointer" onclick="openIndustryByCode('${esc(n.r.id)}')">${esc(shortIndustryName(n.r.name))} <tspan fill="${netCol}" font-weight="700">${liveSankeyFmt(n.r.net)}</tspan></text>`;
  });

  box.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="三大法人買賣超流向各產業的桑基圖，資料日 ${esc(ls.as_of || '')}" style="width:100%; height:auto; max-height:${H}px;">
      <defs>${defs}</defs>
      <g>${ribbons}</g><g>${nodes}</g><g>${labels}</g>
    </svg>`;

  if (noteEl) {
    const cov = inds.reduce((a, r) => a + r.coverage * r.companies, 0) / Math.max(inds.reduce((a, r) => a + r.companies, 0), 1);
    noteEl.innerHTML = `${esc(ls.note)}　收盤價覆蓋率約 ${Math.round(cov * 100)}%。左欄＝法人買超、右欄＝賣超；點產業節點可看第二層分析。`;
  }
}

function liveSankeyHighlight(indId) {
  document.querySelectorAll('#liveSankeyContainer .ls-rib').forEach(p => {
    p.style.opacity = (!indId || p.getAttribute('data-ind') === indId) ? '1' : '0.08';
  });
}

function setSankeyMode(mode) {
  SANKEY_MODE = mode === 'macro' ? 'macro' : 'live';
  const live = document.getElementById('sankeyLivePane');
  const macro = document.getElementById('sankeyMacroPane');
  if (live) live.style.display = SANKEY_MODE === 'live' ? 'block' : 'none';
  if (macro) macro.style.display = SANKEY_MODE === 'macro' ? 'block' : 'none';
  const lb = document.getElementById('sankeyModeLiveBtn'), mb = document.getElementById('sankeyModeMacroBtn');
  if (lb) lb.classList.toggle('btn-play', SANKEY_MODE === 'live');
  if (mb) mb.classList.toggle('btn-play', SANKEY_MODE === 'macro');
  if (lb) lb.setAttribute('aria-pressed', String(SANKEY_MODE === 'live'));
  if (mb) mb.setAttribute('aria-pressed', String(SANKEY_MODE === 'macro'));
  try { sessionStorage.setItem('twfin_sankey_mode', SANKEY_MODE); } catch (e) {}
}

// 初始顯示：有即時資料就預設即時圖；沒有 (舊快照) 就顯示總體背景。使用者上次手動選的分頁在同一個工作階段內保留。
function initSankeyMode() {
  renderLiveSankey();
  let pref = null;
  try { pref = sessionStorage.getItem('twfin_sankey_mode'); } catch (e) {}
  const hasLive = !!(STATE && STATE.live_sankey && STATE.live_sankey.available);
  setSankeyMode(pref || (hasLive ? 'live' : 'macro'));
  if (!hasLive && SANKEY_MODE === 'live') setSankeyMode('macro');
}
