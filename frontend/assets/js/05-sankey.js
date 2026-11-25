/* =========================================================================
   3. 渲染互動式 Sankey 台灣資金流向四層全景圖 (Habr 1016620 設計風格實裝)
   - 四層結構：資金來源(L0) ➔ 台灣總資金樞紐(L1) ➔ 資產配置類別(L2) ➔ 17大細分產業與次級去向(L3)
   - 漸層填充貝茲面積色帶 (Filled Gradient Bezier Ribbons)
   - 懸停聚光燈高亮 (Spotlight Dimming) & 點擊釘選浮動明細卡片 (Pin Tooltip with 1,989 Live Companies)
   ========================================================================= */
let SANKEY_PINNED_ID = null;
let SANKEY_ZOOM = 1.0;
let SANKEY_LIST_MODE = false;

function makeRibbonPath(x0, y0_top, y0_bot, x1, y1_top, y1_bot) {
  const mx = (x0 + x1) / 2;
  return `M ${x0} ${y0_top} C ${mx} ${y0_top}, ${mx} ${y1_top}, ${x1} ${y1_top} L ${x1} ${y1_bot} C ${mx} ${y1_bot}, ${mx} ${y0_bot}, ${x0} ${y0_bot} Z`;
}

function makeCenterCurve(x0, y0_mid, x1, y1_mid) {
  const mx = (x0 + x1) / 2;
  return `M ${x0} ${y0_mid} C ${mx} ${y0_mid}, ${mx} ${y1_mid}, ${x1} ${y1_mid}`;
}

function renderSankeyDiagram(periodIdx) {
  const cfg = SANKEY_PERIOD_CONFIGS[periodIdx] || SANKEY_PERIOD_CONFIGS[4];
  const m = cfg.mult;

  // X 軸四層座標 (預留左右充足文字排版空間，杜絕文字重疊)
  const X0 = 178, W0 = 13;
  const X1 = 385, W1 = 15;
  const X2 = 640, W2 = 15;
  const X3 = 935, W3 = 11;

  // 第一層 (L0)：6大資金來源 (垂直總高度與中央樞紐對齊)
  const L0 = [
    { id: "N0_BANK", title: "本國銀行存款池", val: "68.54 兆", share: "76.8%", y: 38, h: Math.round(255 * m[0]), color: "#34d399", flowIdx: 0,
      indId: "IND_FIN_HOLDING", obs: "直接統計 (等級A)",
      txs: ["2026-09 38家國銀存款總額: 68兆5,398億元", "2026-09 單月新增存款: +7,425億元 (同期新高)", "2026-09 M2年增率: +7.24% / M1B年增率: +7.20%", "定儲解約轉向活存與股市交割池趨勢顯著"] },
    { id: "N0_FX", title: "企業營收與外匯存款", val: "10.06 兆", share: "11.3%", y: 307, h: Math.round(64 * m[5]), color: "#10b981", flowIdx: 0,
      indId: "IND_AI_SERVER", obs: "直接統計 (等級A)",
      txs: ["2026-09 企業外匯存款: 10兆591億元 (首破10兆)", "2026-10 1,989家上市櫃總營收: 6.8635兆元 (+45.49%)", "2026-10 外銷訂單: 1,238.2億美元 (+78.3% 歷史新高)", "2026-10 海關出口: 967.6億美元 (+58.9% 歷史新高)"] },
    { id: "N0_GIRO", title: "內資散戶證券劃撥池", val: "4.70 兆", share: "5.3%", y: 383, h: Math.round(46 * m[1]), color: "#2dd4bf", flowIdx: 1,
      indId: "IND_SEMI_FOUNDRY", obs: "代理指標 (等級A)",
      txs: ["2026-09 證券劃撥存款餘額: 4兆6,981億元 (歷史新高)", "2026-09 單月大增: +1,269億元", "2026-11 上市融資餘額: 8,343億元 (歷史高檔)", "【防重複】此為待命交割池(Stock)，不可與ETF申購直接相加"] },
    { id: "N0_INS", title: "投信、保險與退休金", val: "3.85 兆", share: "4.3%", y: 441, h: Math.round(36 * m[3]), color: "#38bdf8", flowIdx: 3,
      indId: "IND_FIN_HOLDING", obs: "直接統計 (等級A/B)",
      txs: ["2026-11 投信累計買超台股: +1,597.6億元", "2026-Q3+Q4 投信累計買超: +6,168.8億元", "2026-11 0050單月淨申購: >2,200億元 (歷史新高)", "法人鎖定高評級投等債ETF (00937B等)"] },
    { id: "N0_GOV", title: "政府公建與政策信貸", val: "1.35 兆", share: "1.5%", y: 489, h: Math.round(22 * m[4]), color: "#60a5fa", flowIdx: 4,
      indId: "IND_POWER_GREEN", obs: "直接統計 (等級A)",
      txs: ["台電強韌電網計畫與電力基建預算持續撥付", "2026-10 新青安2.0房貸撥款佔五大銀行45.32%", "2026-11 金管會穩定股市措施(限空令)護盤"] },
    { id: "N0_FINI", title: cfg.finiOut ? "外資資金調節池" : "外資匯入資金池", val: cfg.finiOut ? "-7,607 億" : "+1,840 億", share: "0.8%", y: 523, h: 16, color: cfg.finiOut ? "#fb7185" : "#818cf8", flowIdx: 2,
      indId: "IND_SEMI_FOUNDRY", obs: "直接統計 (等級A)",
      txs: ["2026-10 外資單月淨匯出: 65億美元 (約2,112億台幣)", "2026-10 外匯存底降至: 5,964.37億美元", "2026-11 外資上市櫃現貨賣超: -5,494.6億元", "2026-11-20 外資台指期未平倉淨空單: -98,650口"] }
  ];

  // 第二層 (L1)：中央「台灣總體資金配置樞紐」柱 (仿照 Habr 中央 Бюджет 灰藍核心柱)
  const HUB = {
    id: "N1_HUB", title: "台灣總資金樞紐", val: "89.26 兆", share: "100% 總池",
    y: 42, h: 492, color: "#64748b", flowIdx: 0, indId: "IND_SEMI_FOUNDRY", obs: "總體資金池核心樞紐",
    txs: [
      "國內銀行存款總池: 68.54 兆元",
      "企業外匯存款池: 10.06 兆元",
      "內資證券劃撥交割池: 4.70 兆元",
      "全體貨幣機構放款與投資年增率: +9.79% (28年新高)",
      "五大銀行新承做放款平均利率: 2.254% (17年新高)"
    ]
  };

  // 第三層 (L2)：6大資產配置去向 (仿照 Habr 中右層黃、橘、琥珀、紅分流柱)
  const L2 = [
    { id: "N2_CAPEX", title: "企業資本支出與信貸", val: "49.68 兆", share: "55.7%", y: 34, h: 170, color: "#eab308", flowIdx: 5,
      indId: "IND_SEMI_FOUNDRY", obs: "直接統計 (等級A)",
      txs: ["38家國銀放款總餘額: 49兆6,829億元 (+9.79% YoY)", "9月單月新增放款: +4,674億元 (歷年同期新高)", "9月景氣燈號之機械及電機設備進口: 紅燈", "主要投向: 2奈米晶圓廠、CoWoS封裝、AI伺服器產線"] },
    { id: "N2_STOCK", title: "台股市場與ETF配置", val: "18.45 兆", share: "20.7%", y: 218, h: 138, color: "#f97316", flowIdx: 1,
      indId: "IND_AI_SERVER", obs: "直接統計 + 代理指標",
      txs: ["11月 0050 單月淨申購: >2,200億元 (歷史新高)", "11月 投信現貨買超: +1,597.6億元 (護盤主力)", "1,989家上市櫃10月營收: 6.8635兆元 (+45.49% YoY)", "資金集中於一線低PEG權值股與大型金控"] },
    { id: "N2_DEPOSIT", title: "外匯與定存停泊池", val: "10.06 兆", share: "11.3%", y: 370, h: 58, color: "#14b8a6", flowIdx: 0,
      indId: "IND_FIN_HOLDING", obs: "直接統計 (等級A)",
      txs: ["企業與個人外匯存款餘額: 10兆591億元", "含出口AI貨款與海外ECB籌資暫泊資金", "隨新台幣貶近32.92元具潛在結匯動能"] },
    { id: "N2_BOND", title: "債券市場與投等債ETF", val: "3.15 兆", share: "3.5%", y: 440, h: 36, color: "#38bdf8", flowIdx: 3,
      indId: "IND_FIN_HOLDING", obs: "代理指標 (等級B)",
      txs: ["美國10年期公債殖利率: 4.97% (11月中曾達5.14%)", "00937B與20年美債ETF頻居三大法人週買超前十", "防禦型資金鎖定高殖利率固定收益商品"] },
    { id: "N2_PROP", title: "房地產與購屋貸款", val: "727.9 億/月", share: "結構降溫", y: 488, h: 24, color: "#d97706", flowIdx: 4,
      indId: "IND_CONSTRUCTION", obs: "直接統計 (結構背離)",
      txs: ["10月五大銀行新增房貸: 727.89億元 (新青安佔45.32%)", "2026全年全台建物買賣移轉棟數: 26萬棟保衛戰", "央行第七波信用管制持續，成屋實質買氣轉冷"] },
    { id: "N2_OUT", title: "外資匯出與海外調節", val: "-2,112 億/月", share: "跨境流出", y: 522, h: 18, color: "#f43f5e", flowIdx: 2,
      indId: "IND_STEEL_PLASTIC", obs: "直接統計 (Confirmed Outflow)",
      txs: ["10月外資單月淨匯出: 約65億美元 (2,112億台幣)", "11/20 TWSE BFI82U 三大法人單日合計賣超: -509.4億元", "費城半導體指數11/20重挫-10.67%引發外資提款"] }
  ];

  // 第四層 (L3)：17大細分產業與次級資金去向 (仿照 Habr 最右側密集細分流線束！)
  const L3 = [
    // 來自 N2_CAPEX (企業資本支出與擴產流線束 - 金黃色系)
    { id: "N3_01", parent: "N2_CAPEX", title: "晶圓代工2nm/CoWoS擴產 (2330 台積電)", val: "10月營收 5,869億 (+59.7%)", y: 24, h: 24, color: "#facc15", indId: "IND_SEMI_FOUNDRY", flowIdx: 5 },
    { id: "N3_02", parent: "N2_CAPEX", title: "AI伺服器機櫃產線與週轉 (2317 鴻海 / 2382 廣達)", val: "鴻海1.305兆 / 廣達+104%", y: 54, h: 22, color: "#eab308", indId: "IND_AI_SERVER", flowIdx: 5 },
    { id: "N3_03", parent: "N2_CAPEX", title: "半導體測試介面與設備採購 (6223 旺矽 / 3131 弘塑)", val: "旺矽10月+92.7% 創高", y: 82, h: 16, color: "#eab308", indId: "IND_SEMI_EQUIP", flowIdx: 5 },
    { id: "N3_04", parent: "N2_CAPEX", title: "水冷散熱Cold Plate/CDU擴產 (3017 奇鋐 / 3324 雙鴻)", val: "奇鋐221億 (+34.4%)", y: 104, h: 15, color: "#ca8a04", indId: "IND_THERMAL", flowIdx: 5 },
    { id: "N3_05", parent: "N2_CAPEX", title: "強韌電網與外銷變壓器重電 (1519 華城 / 1513 中興電)", val: "在手訂單能見度2~3年", y: 125, h: 13, color: "#ca8a04", indId: "IND_POWER_GREEN", flowIdx: 5 },
    { id: "N3_06", parent: "N2_CAPEX", title: "高階CCL銅箔基板與PCB擴產 (2383 台光電 / 2368 金像電)", val: "M8材料與AI伺服器板", y: 144, h: 11, color: "#d97706", indId: "IND_PCB_ABF", flowIdx: 5 },
    { id: "N3_07", parent: "N2_CAPEX", title: "綠能儲能、精密機械與車用零組件 (1319 東陽 / 2049 上銀)", val: "AM車用旺季+台幣貶值匯兌", y: 161, h: 9, color: "#d97706", indId: "IND_MACH_AUTO", flowIdx: 5 },

    // 來自 N2_STOCK (台股市場與ETF配置流線束 - 珊瑚橘色系)
    { id: "N3_08", parent: "N2_STOCK", title: "市值型ETF 0050權值核心 (台積電/鴻海/聯發科)", val: "0050單月吸金 >2,200億", y: 184, h: 24, color: "#fb923c", indId: "IND_SEMI_FOUNDRY", flowIdx: 1 },
    { id: "N3_09", parent: "N2_STOCK", title: "一線AI機櫃與高速連接線束 (3665 貿聯-KY / 6669 緯穎)", val: "貿聯118.5億(+80%)破百億", y: 214, h: 19, color: "#f97316", indId: "IND_AI_SERVER", flowIdx: 1 },
    { id: "N3_10", parent: "N2_STOCK", title: "大型金控穩盤與利差擴張 (2891 中信金 / 2882 國泰金)", val: "20日相對大盤 +5.2% 居冠", y: 239, h: 18, color: "#f97316", indId: "IND_FIN_HOLDING", flowIdx: 1 },
    { id: "N3_11", parent: "N2_STOCK", title: "800G資料中心交換器與CPO光通訊 (2345 智邦 / 3363 上詮)", val: "智邦446.6億 (+91.2%) P/E 16.8x", y: 263, h: 15, color: "#ea580c", indId: "IND_CPO_NET", flowIdx: 1 },
    { id: "N3_12", parent: "N2_STOCK", title: "IC設計與CSP自研AI ASIC (2454 聯發科 / 3661 世芯-KY)", val: "旗艦SoC與ASIC設計服務", y: 284, h: 13, color: "#ea580c", indId: "IND_IC_DESIGN", flowIdx: 1 },
    { id: "N3_13", parent: "N2_STOCK", title: "貨櫃航運與AI晶片航空物流 (2603 長榮 / 2618 長榮航)", val: "高現金流與高息防禦支撐", y: 303, h: 11, color: "#ea580c", indId: "IND_SHIPPING", flowIdx: 1 },
    { id: "N3_14", parent: "N2_STOCK", title: "電信防禦、生技新藥與內需餐飲零售 (2412 中華電 / 6446 藥華藥)", val: "次產業異質觀察(不硬排名)", y: 320, h: 9, color: "#f97316", indId: "IND_BIO_RETAIL", flowIdx: 1 },

    // 來自 N2_DEPOSIT / N2_BOND / N2_PROP / N2_OUT (下方細分去向)
    { id: "N3_15", parent: "N2_DEPOSIT", title: "企業海外ECB暫泊與外幣活存池 (外匯存款 10.06兆)", val: "待匯率穩定轉資本支出", y: 376, h: 24, color: "#14b8a6", indId: "IND_FIN_HOLDING", flowIdx: 0 },
    { id: "N3_16", parent: "N2_DEPOSIT", title: "定儲解約轉入交割備付金 (M1B-M2差距收斂至-0.04%)", val: "散戶銀彈持續活期化", y: 406, h: 18, color: "#0d9488", indId: "IND_FIN_HOLDING", flowIdx: 0 },
    { id: "N3_17", parent: "N2_BOND", title: "長天期美債20年與ESG投等債ETF (00937B等)", val: "鎖定4.97%美債高殖利率", y: 444, h: 26, color: "#38bdf8", indId: "IND_FIN_HOLDING", flowIdx: 3 },
    { id: "N3_18", parent: "N2_PROP", title: "營建交屋撥款 vs 買方市場盤整 (2542 興富發 LEVEL R)", val: "全年移轉26萬棟保衛戰", y: 488, h: 20, color: "#d97706", indId: "IND_CONSTRUCTION", flowIdx: 4 },
    { id: "N3_19", parent: "N2_OUT", title: "外資提款與傳統塑化/鋼鐵資金撤出 (1301 台塑 / 2002 中鋼 LEVEL R)", val: "11月外資賣超5,495億", y: 522, h: 18, color: "#f43f5e", indId: "IND_STEEL_PLASTIC", flowIdx: 2 }
  ];

  // 建立漸層定義与流帶資料
  let defsHtml = '';
  let ribbonsHtml = '';
  let particlesHtml = '';
  const allNodesMap = {};
  [...L0, HUB, ...L2, ...L3].forEach(n => { allNodesMap[n.id] = n; });

  // 輔助：新增一條漸層色帶
  let ribCounter = 0;
  function addRibbon(srcId, dstId, x0, y0_t, y0_b, x1, y1_t, y1_b, c0, c1, isReverse = false) {
    const gid = `sankey_grad_${ribCounter++}`;
    defsHtml += `
      <linearGradient id="${gid}" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="${c0}" stop-opacity="0.48" />
        <stop offset="100%" stop-color="${c1}" stop-opacity="0.48" />
      </linearGradient>
    `;
    const pathD = makeRibbonPath(x0, y0_t, y0_b, x1, y1_t, y1_b);
    const curveD = makeCenterCurve(x0, (y0_t + y0_b) / 2, x1, (y1_t + y1_b) / 2);
    const thick = Math.max(1.5, (y1_b - y1_t) * 0.25);

    ribbonsHtml += `
      <path d="${pathD}" fill="url(#${gid})" stroke="${c1}" stroke-width="0.6" stroke-opacity="0.35"
            class="sankey-ribbon" data-src="${srcId}" data-dst="${dstId}"
            onmouseenter="highlightSankeyNode('${dstId}', event)"
            onmouseleave="resetSankeyHighlight()"
            onclick="pinSankeyNode('${dstId}', event)" />
    `;
    if ((y0_b - y0_t) >= 6) {
      particlesHtml += `
        <path d="${curveD}" fill="none" stroke="${c1}" stroke-width="${Math.min(4, thick)}"
              stroke-opacity="0.72" class="${isReverse ? 'flow-particle-reverse' : 'flow-particle-line'}"
              data-src="${srcId}" data-dst="${dstId}" />
      `;
    }
  }

  // 1) L0 -> HUB 流帶 (自動依 L0 高度比例堆疊進入 HUB)
  const totalL0H = L0.reduce((acc, n) => acc + n.h, 0);
  let hubInCursor = HUB.y;
  L0.forEach(n => {
    const sliceH = (n.h / totalL0H) * HUB.h;
    addRibbon(n.id, HUB.id, X0 + W0, n.y, n.y + n.h, X1, hubInCursor, hubInCursor + sliceH, n.color, HUB.color, n.id === 'N0_FINI' && cfg.finiOut);
    hubInCursor += sliceH;
  });

  // 2) HUB -> L2 流帶 (依 L2 高度比例由 HUB 分流而出)
  const totalL2H = L2.reduce((acc, n) => acc + n.h, 0);
  let hubOutCursor = HUB.y;
  L2.forEach(n => {
    const sliceH = (n.h / totalL2H) * HUB.h;
    addRibbon(HUB.id, n.id, X1 + W1, hubOutCursor, hubOutCursor + sliceH, X2, n.y, n.y + n.h, HUB.color, n.color, n.id === 'N2_OUT');
    hubOutCursor += sliceH;
  });

  // 3) L2 -> L3 細分產業流線束 (仿照 Habr 最右側分流束)
  L2.forEach(pNode => {
    const children = L3.filter(c => c.parent === pNode.id);
    const totChildH = children.reduce((acc, c) => acc + c.h, 0) || 1;
    let pCursor = pNode.y;
    children.forEach(ch => {
      const sliceH = (ch.h / totChildH) * pNode.h;
      addRibbon(pNode.id, ch.id, X2 + W2, pCursor, pCursor + sliceH, X3, ch.y, ch.y + ch.h, pNode.color, ch.color, pNode.id === 'N2_OUT');
      pCursor += sliceH;
    });
  });

  // 繪製四層節點柱與高精度不重疊文字標籤
  let nodesHtml = '';

  // L0 左側節點 (文字靠右對齊於 X0 - 10)
  L0.forEach(n => {
    nodesHtml += `
      <g class="sankey-node-group" data-node="${n.id}"
         onmouseenter="highlightSankeyNode('${n.id}', event)"
         onmouseleave="resetSankeyHighlight()"
         onclick="pinSankeyNode('${n.id}', event)">
        <rect x="${X0}" y="${n.y}" width="${W0}" height="${n.h}" rx="3" fill="${n.color}" />
        <text x="${X0 - 10}" y="${n.y + Math.min(n.h / 2, 16)}" text-anchor="end" fill="#f8fafc" font-size="12.5" font-weight="700">${n.title}</text>
        ${n.h >= 24 ? `<text x="${X0 - 10}" y="${n.y + Math.min(n.h / 2 + 15, n.h - 2)}" text-anchor="end" fill="#94a3b8" font-size="11" font-family="Consolas, monospace">${n.val} (${n.share})</text>` : ''}
      </g>
    `;
  });

  // L1 中央樞紐柱
  nodesHtml += `
    <g class="sankey-node-group" data-node="${HUB.id}"
       onmouseenter="highlightSankeyNode('${HUB.id}', event)"
       onmouseleave="resetSankeyHighlight()"
       onclick="pinSankeyNode('${HUB.id}', event)">
      <rect x="${X1}" y="${HUB.y}" width="${W1}" height="${HUB.h}" rx="4" fill="#64748b" stroke="#94a3b8" stroke-width="1" />
      <text x="${X1 + W1 / 2}" y="${HUB.y - 12}" text-anchor="middle" fill="#fff" font-size="13.5" font-weight="800">${HUB.title}</text>
      <text x="${X1 + W1 / 2}" y="${HUB.y + HUB.h + 18}" text-anchor="middle" fill="#cbd5e1" font-size="12" font-family="Consolas, monospace" font-weight="700">${HUB.val}</text>
    </g>
  `;

  // L2 資產配置柱 (文字位於柱右側 X2 + W2 + 8)
  L2.forEach(n => {
    nodesHtml += `
      <g class="sankey-node-group" data-node="${n.id}"
         onmouseenter="highlightSankeyNode('${n.id}', event)"
         onmouseleave="resetSankeyHighlight()"
         onclick="pinSankeyNode('${n.id}', event)">
        <rect x="${X2}" y="${n.y}" width="${W2}" height="${n.h}" rx="3" fill="${n.color}" />
        <text x="${X2 + W2 + 8}" y="${n.y + Math.min(n.h / 2 - 2, 18)}" fill="#fff" font-size="12.5" font-weight="800">${n.title}</text>
        <text x="${X2 + W2 + 8}" y="${n.y + Math.min(n.h / 2 + 13, 32)}" fill="#cbd5e1" font-size="11" font-family="Consolas, monospace">${n.val}｜${n.share}</text>
      </g>
    `;
  });

  // L3 最右側 19 項細分產業與次級去向 (文字位於 X3 + W3 + 8)
  L3.forEach(n => {
    nodesHtml += `
      <g class="sankey-node-group" data-node="${n.id}"
         onmouseenter="highlightSankeyNode('${n.id}', event)"
         onmouseleave="resetSankeyHighlight()"
         onclick="pinSankeyNode('${n.id}', event)">
        <rect x="${X3}" y="${n.y}" width="${W3}" height="${n.h}" rx="2" fill="${n.color}" />
        <text x="${X3 + W3 + 8}" y="${n.y + n.h / 2 + 4}" fill="${n.color}" font-size="11.5" font-weight="700">${n.title} <tspan fill="#94a3b8" font-family="Consolas, monospace">(${n.val})</tspan></text>
      </g>
    `;
  });

  window.__SANKEY_NODES_MAP__ = allNodesMap;

  document.getElementById('sankeySvgContainer').innerHTML = `
    <svg id="mainSankeySvg" class="sankey-svg" viewBox="0 0 1320 565" style="transform: scale(${SANKEY_ZOOM});">
      <defs>${defsHtml}</defs>
      <g id="sankeyRibbonsLayer">${ribbonsHtml}</g>
      <g id="sankeyParticlesLayer">${particlesHtml}</g>
      <g id="sankeyNodesLayer">${nodesHtml}</g>
    </svg>
  `;

  // 同時產生行動端/精確分析用之「方案 A＋B 結合版：直向動態瀑布流線 SVG ＋ 手風琴可展開 19 產業能量條」
  const mobSvgW = 360, mobSvgTopH = 68, mobSvgBotH = 74;
  const mobHubX = 180;
  const mobTopCurves = L0.map((n, idx) => {
    const sx = 30 + idx * 60;
    const sw = Math.max(2, Math.min(9, n.h / 24));
    const isRev = n.id === 'N0_FINI' && cfg.finiOut;
    const pathD = `M ${sx} 2 C ${sx} 34, ${mobHubX} 34, ${mobHubX} ${mobSvgTopH - 2}`;
    return `
      <path d="${pathD}" fill="none" stroke="${n.color}" stroke-width="${sw}" stroke-opacity="0.32" />
      <path d="${pathD}" fill="none" stroke="${n.color}" stroke-width="${Math.max(1.8, sw * 0.55)}" stroke-opacity="0.88"
            class="${isRev ? 'flow-particle-reverse' : 'flow-particle-line'}" />
    `;
  }).join('');

  const mobBotCurves = L2.map((n, idx) => {
    const dx = 30 + idx * 60;
    const sw = Math.max(2, Math.min(10, n.h / 18));
    const isRev = n.id === 'N2_OUT';
    const pathD = `M ${mobHubX} 2 C ${mobHubX} 36, ${dx} 36, ${dx} ${mobSvgBotH - 2}`;
    return `
      <path d="${pathD}" fill="none" stroke="${n.color}" stroke-width="${sw}" stroke-opacity="0.35" />
      <path d="${pathD}" fill="none" stroke="${n.color}" stroke-width="${Math.max(1.8, sw * 0.55)}" stroke-opacity="0.9"
            class="${isRev ? 'flow-particle-reverse' : 'flow-particle-line'}" />
    `;
  }).join('');

  document.getElementById('sankeyAltListView').innerHTML = `
    <div style="margin-bottom:6px;">
      <div style="font-size:13.5px; font-weight:800; color:#94a3b8; margin-bottom:8px;">① 上層資金來源池（點擊膠囊查看明細）</div>
      <div class="mob-flow-sources-grid">
        ${L0.map(n => `
          <div class="mob-flow-source-pill" style="border-left:4px solid ${n.color};" onclick="pinSankeyNode('${n.id}', event)">
            <div style="font-size:13px; font-weight:800; color:#f8fafc; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${n.title}</div>
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-top:2px;">
              <strong style="font-size:15px; color:${n.color};">${n.val}</strong>
              <span style="font-size:11.5px; color:#94a3b8;">${n.share}</span>
            </div>
          </div>
        `).join('')}
      </div>

      <!-- 直向 SVG 動態瀑布流線 (上 ➔ 中樞) -->
      <svg viewBox="0 0 ${mobSvgW} ${mobSvgTopH}" style="width:100%; height:auto; display:block; margin:2px 0;">
        ${mobTopCurves}
      </svg>

      <!-- 中樞匯聚條 -->
      <div class="mob-flow-hub-banner" onclick="pinSankeyNode('${HUB.id}', event)">
        <div style="font-size:12px; color:#cbd5e1; font-weight:700;">② 台灣總體資金配置樞紐（點擊檢視總池）</div>
        <div style="font-size:19px; font-weight:700; color:#fff;">${HUB.val} <span style="font-size:13px; color:#34d399;">(100% 總池)</span></div>
      </div>

      <!-- 直向 SVG 動態瀑布流線 (中樞 ➔ 六大去向) -->
      <svg viewBox="0 0 ${mobSvgW} ${mobSvgBotH}" style="width:100%; height:auto; display:block; margin:2px 0 8px 0;">
        ${mobBotCurves}
      </svg>

      <!-- ③ 手風琴可展開：六大去向 ＋ 19 大細分產業能量條 -->
      <div style="font-size:13.5px; font-weight:800; color:#94a3b8; margin-bottom:8px;">③ 六大資金去向 ＆ 19 細分產業（點擊展開細項與公司營收）</div>
      ${L2.map((n, idx) => {
        const children = L3.filter(c => c.parent === n.id);
        const barW = Math.max(14, Math.min(100, Math.round((n.h / 170) * 100)));
        const isOpenByDefault = idx < 2; // 預設展開前兩大主力去向（企業資本支出 & 台股ETF）
        return `
          <div class="mob-flow-acc-card" style="border-left:4px solid ${n.color};">
            <div class="mob-flow-acc-header" onclick="toggleMobFlowAcc('mobAcc_${n.id}', 'mobAccArrow_${n.id}')">
              <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
                <strong style="font-size:15.5px; color:#f8fafc;">${n.title}</strong>
                <span style="font-size:15px; font-weight:700; color:${n.color}; white-space:nowrap;">${n.val} <span style="font-size:12px; color:#94a3b8;">(${n.share})</span></span>
              </div>
              <div class="mob-flow-acc-bar-track">
                <div class="mob-flow-acc-bar-fill" style="width:${barW}%; background-image:linear-gradient(90deg, ${n.color}99 0%, #ffffffcc 50%, ${n.color}99 100%); background-color:${n.color};"></div>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; font-size:12.5px; color:#94a3b8;">
                <span>涵蓋 ${children.length} 項細分產業流向</span>
                <span id="mobAccArrow_${n.id}" style="color:#38bdf8; font-weight:700;">${isOpenByDefault ? '▲ 收合細項' : '▼ 展開細項'}</span>
              </div>
            </div>
            <div id="mobAcc_${n.id}" class="mob-flow-acc-body ${isOpenByDefault ? 'open' : ''}">
              <div style="padding:8px 0 6px 0; display:flex; justify-content:flex-end;">
                <button class="btn btn-outline btn-sm" style="font-size:12px; padding:3px 10px;" onclick="pinSankeyNode('${n.id}', event)">📊 查看「${n.title}」完整明細</button>
              </div>
              ${children.map(ch => `
                <div onclick="pinSankeyNode('${ch.id}', event)" style="padding:9px 6px; border-top:1px solid #1e293b; cursor:pointer;">
                  <div style="font-size:13.5px; font-weight:800; color:${ch.color};">${ch.title}</div>
                  <div style="font-size:12.5px; color:#cbd5e1; margin-top:2px;">${ch.val} <span style="color:#38bdf8; float:right;">點擊查公司 ➔</span></div>
                </div>
              `).join('')}
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;

  // 行動裝置自動開啟「方案 A＋B 直向動態流線＋手風琴」視圖（使用者亦可隨時切換回橫向桑基圖）
  if (window.innerWidth <= 768 && !window.__SANKEY_MOBILE_INIT__) {
    window.__SANKEY_MOBILE_INIT__ = true;
    SANKEY_LIST_MODE = true;
    document.getElementById('sankeyStageBox').style.display = 'none';
    document.getElementById('sankeyAltListView').style.display = 'block';
    const tBtn = document.getElementById('sankeyViewToggleBtn');
    if (tBtn) tBtn.textContent = '📊 橫向桑基圖';
  }

  document.getElementById('sankeyPeriodNarrative').innerHTML =
    `<strong>當前時期：</strong>${cfg.title} <span style="color:var(--text-muted); margin-left:8px;">（提示：滑過色帶可高亮；點擊節點或流帶可釘選明細卡）</span>`;
}

function populateSankeyFloatCard(nodeId, evt, isPinned = false) {
  const node = (window.__SANKEY_NODES_MAP__ || {})[nodeId];
  if (!node) return;
  const card = document.getElementById('sankeyFloatCard');
  document.getElementById('sfcCategoryTag').textContent = node.obs || '台灣資金流向節點';
  document.getElementById('sfcTitle').textContent = node.title;
  document.getElementById('sfcMainValue').textContent = node.val;
  document.getElementById('sfcMainValue').style.color = node.color || '#fbbf24';
  document.getElementById('sfcSharePill').textContent = node.share ? `佔比/狀態：${node.share}` : '細分產業流向';

  // 從 SQLite 1,989 家真實上市櫃公司中撈出屬於該產業之代表公司真實 10 月營收與法人買賣超明細 (仿照 Habr 圖3的逐筆交易明細!)
  const liveComps = (STATE.live_top_companies || []).filter(c => c.mapped_industry_id === node.indId).slice(0, 10);
  document.getElementById('sfcTypePill').textContent = liveComps.length ? `${liveComps.length}+ 家官方API實證` : '央行/官方統計';

  let txLines = [];
  if (node.txs && node.txs.length) {
    txLines = node.txs.map(t => `<div>• ${t}</div>`);
  }
  if (liveComps.length) {
    txLines.push(`<div style="color:var(--accent-blue); font-weight:700; margin-top:4px;">[MOPS 115年10月營收 & 11/20 法人明細]</div>`);
    liveComps.forEach(c => {
      const yoyStr = (c.rev_yoy_pct >= 0 ? '+' : '') + (c.rev_yoy_pct ?? 0) + '%';
      txLines.push(`<div>2026.10 — <strong>${c.company_code} ${c.company_name}</strong>: ${c.rev_billion.toLocaleString()}億 (<span class="${c.rev_yoy_pct >= 0 ? 'pos' : 'neg'}">YoY ${yoyStr}</span>｜P/E ${c.pe_ratio ?? '-'}x)</div>`);
    });
  }
  document.getElementById('sfcSubSummary').textContent =
    node.parent ? `上層資金來源：${((window.__SANKEY_NODES_MAP__||{})[node.parent]||{}).title || ''}` : '點擊下方按鈕可開啟完整 AI 白話六問與防重複計算稽核';
  document.getElementById('sfcTxList').innerHTML = txLines.join('');
  document.getElementById('sfcPinHint').textContent = isPinned ? '📌 已釘選固定（可捲動明細，點擊右上✕關閉）' : '💡 點擊節點可固定此卡片';

  const drawerBtn = document.getElementById('sfcDrawerBtn');
  drawerBtn.onclick = () => {
    if (node.indId && node.parent) {
      openIndustryByCode(node.indId);
    } else {
      openSankeyFlowDrawer(node.flowIdx || 0);
    }
  };

  // 智慧邊界定位 (防止超出畫布右側或底部，解決 Habr 作者提到的 Tooltip 邊界問題)
  const stage = document.getElementById('sankeyStageBox');
  const rect = stage.getBoundingClientRect();
  let leftPx = 395, topPx = 70;
  if (evt && evt.clientX) {
    leftPx = evt.clientX - rect.left + 18;
    topPx = evt.clientY - rect.top - 20;
    if (leftPx + 365 > rect.width) leftPx = Math.max(16, evt.clientX - rect.left - 365);
    if (topPx + 310 > rect.height) topPx = Math.max(12, rect.height - 320);
    if (topPx < 10) topPx = 10;
  }
  card.style.left = `${leftPx}px`;
  card.style.top = `${topPx}px`;
  card.classList.add('visible');
}

function applySankeySpotlight(nodeId) {
  const ribbons = document.querySelectorAll('.sankey-ribbon');
  const nodes = document.querySelectorAll('.sankey-node-group');
  const connectedNodes = new Set([nodeId]);

  ribbons.forEach(r => {
    const s = r.getAttribute('data-src');
    const d = r.getAttribute('data-dst');
    if (s === nodeId || d === nodeId) {
      r.style.fillOpacity = '0.92';
      r.style.strokeOpacity = '0.95';
      connectedNodes.add(s);
      connectedNodes.add(d);
    } else {
      r.style.fillOpacity = '0.10';
      r.style.strokeOpacity = '0.08';
    }
  });

  nodes.forEach(n => {
    const nid = n.getAttribute('data-node');
    n.style.opacity = connectedNodes.has(nid) ? '1' : '0.25';
  });
}

function highlightSankeyNode(nodeId, evt) {
  if (SANKEY_PINNED_ID) return;
  applySankeySpotlight(nodeId);
  populateSankeyFloatCard(nodeId, evt, false);
}

function resetSankeyHighlight() {
  if (SANKEY_PINNED_ID) return;
  document.querySelectorAll('.sankey-ribbon').forEach(r => {
    r.style.fillOpacity = '';
    r.style.strokeOpacity = '';
  });
  document.querySelectorAll('.sankey-node-group').forEach(n => {
    n.style.opacity = '1';
  });
  document.getElementById('sankeyFloatCard').classList.remove('visible');
}

function pinSankeyNode(nodeId, evt) {
  if (evt) evt.stopPropagation();
  SANKEY_PINNED_ID = nodeId;
  applySankeySpotlight(nodeId);
  populateSankeyFloatCard(nodeId, evt, true);
}

function unpinSankeyCard(evt) {
  if (evt) evt.stopPropagation();
  SANKEY_PINNED_ID = null;
  resetSankeyHighlight();
}

function zoomSankey(factor) {
  if (factor === 0) SANKEY_ZOOM = 1.0;
  else SANKEY_ZOOM = Math.min(1.6, Math.max(0.75, SANKEY_ZOOM * factor));
  const svg = document.getElementById('mainSankeySvg');
  if (svg) svg.style.transform = `scale(${SANKEY_ZOOM})`;
}

function toggleMobFlowAcc(bodyId, arrowId) {
  const body = document.getElementById(bodyId);
  const arrow = document.getElementById(arrowId);
  if (!body) return;
  const willOpen = !body.classList.contains('open');
  body.classList.toggle('open', willOpen);
  if (arrow) arrow.textContent = willOpen ? '▲ 收合細項' : '▼ 展開細項';
}

function toggleSankeyListView() {
  SANKEY_LIST_MODE = !SANKEY_LIST_MODE;
  document.getElementById('sankeyStageBox').style.display = SANKEY_LIST_MODE ? 'none' : 'block';
  document.getElementById('sankeyAltListView').style.display = SANKEY_LIST_MODE ? 'block' : 'none';
  document.getElementById('sankeyViewToggleBtn').textContent = SANKEY_LIST_MODE ? '📊 橫向桑基圖' : '📋 結構清單';
}

function onSankeyPeriodChange(val) {
  renderSankeyDiagram(parseInt(val, 10));
}

function toggleSankeyPlay() {
  const btn = document.getElementById('sankeyPlayBtn');
  const sel = document.getElementById('sankeyPeriodSelect');
  if (SANKEY_TIMER) {
    clearInterval(SANKEY_TIMER);
    SANKEY_TIMER = null;
    btn.textContent = '▶ 播放演變';
    return;
  }
  btn.textContent = '⏸ 暫停';
  let idx = 0;
  sel.value = String(idx);
  renderSankeyDiagram(idx);
  SANKEY_TIMER = setInterval(() => {
    idx = (idx + 1) % SANKEY_PERIOD_CONFIGS.length;
    sel.value = String(idx);
    renderSankeyDiagram(idx);
    if (idx === SANKEY_PERIOD_CONFIGS.length - 1) {
      clearInterval(SANKEY_TIMER);
      SANKEY_TIMER = null;
      btn.textContent = '▶ 重新播放';
    }
  }, 2200);
}

function openSankeyFlowDrawer(flowIdx) {
  if (!STATE.asset_flows || !STATE.asset_flows[flowIdx]) return;
  const f = STATE.asset_flows[flowIdx];
  const html = `
    <div class="q6-box">
      <div class="q6-title">資金流向路徑與最新規模</div>
      <div style="font-size:14px; font-weight:700; color:#fff; margin:4px 0;">
        ${f.source_pool} ➔ ${f.asset_class}（${f.sub_category}）
      </div>
      <div style="font-size:13px; color:var(--accent-emerald);">
        最新規模：<strong>${f.total_scale_value.toLocaleString()} ${f.scale_unit}</strong> ｜ 近期淨流量/變動：<strong>${f.net_flow_value >= 0 ? '+' : ''}${f.net_flow_value.toLocaleString()}</strong>
      </div>
    </div>
    <div class="q6-box">
      <div class="q6-title">統計範圍與白話解讀</div>
      <div style="font-size:13px; color:#e2e8f0;">${f.statistical_scope}<br/><br/>${f.notes}</div>
    </div>
    <div class="q6-box" style="border-color:var(--accent-orange);">
      <div class="q6-title" style="color:var(--accent-orange);">🛡️ 防重複計算強制規範（附錄B必答）</div>
      <div style="font-size:13px; color:#fde68a;">${f.double_counting_guard}</div>
    </div>
    <div style="font-size:12px; color:var(--text-secondary); margin-top:10px;">
      資料性質：<strong>${f.observation_type}</strong> ｜ 資料品質等級：<strong>等級 ${f.quality_grade}</strong><br/>
      資料涵蓋期間：<strong>${f.period_covered}</strong> ｜ 官方發布日：<strong>${f.release_date}</strong> ｜ 來源：<a href="${f.source_url}" target="_blank" style="color:var(--accent-blue);">${f.publisher}</a>
    </div>
  `;
  openDrawer(`<span class="badge badge-grade-${f.quality_grade}">等級 ${f.quality_grade}｜${f.observation_type}</span>`, `${f.asset_class}`, f.sub_category, html);
}

