/* =========================================================================
   6. 六大產業趨勢排行榜 (嚴格區分「目前最熱門」vs「可能即將轉強」)
   ========================================================================= */
// 即時排行榜：六個榜都由 STATE.industries 的即時指標 (live_metrics) 與即時評分產生，沒有任何手寫數字。
// 只有拿不到即時指標的舊快照才退回下面的靜態版本 (2026-11-21 前後手寫)。
function buildLiveBoards() {
  const inds = (STATE.industries || []).filter(i => i.live_metrics);
  if (inds.length < 6) return null;
  const sg = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v)) ? 'N/A' : (v >= 0 ? '+' : '') + v.toFixed(d);
  const scored = inds.filter(i => i.score_source === 'live' && i.total_weighted_score !== null);
  const rank = (list, key, dir, n = 3) => [...list].filter(i => key(i) !== null && key(i) !== undefined)
    .sort((a, b) => dir * (key(b) - key(a))).slice(0, n);
  const L = i => i.live_metrics;
  const item = (i, metric, plain) => ({ name: esc(i.industry_name), metric, plain, indId: esc(i.industry_id) });
  const facts = i => `營收年增 ${sg(L(i).yoy)}%、法人當日淨買賣 ${sg(L(i).inst_net_billion)} 億、${L(i).rs_days ? '近 ' + L(i).rs_days + ' 日相對大盤 ' + sg(L(i).rs_pct, 2) + '%' : '相對強弱資料不足'}`;
  const none = '目前沒有符合條件的產業。';
  const boardOf = (title, badge, color, list, mk) => ({ title, badge, color, items: list.length ? list.map(mk) : [{ name: none, metric: '', plain: '', indId: '' }] });

  const gap = i => i.score_fundamentals - i.score_capital_flow;
  return [
    boardOf('1. 💰 法人當日淨買超金額最多的產業', '外資+投信+自營商，股數×收盤價', '#10b981',
      rank(inds, i => L(i).foreign_billion + L(i).itc_billion + L(i).dealer_billion, 1).filter(i => (L(i).foreign_billion + L(i).itc_billion + L(i).dealer_billion) > 0),
      i => item(i, `三大法人 ${sg(L(i).foreign_billion + L(i).itc_billion + L(i).dealer_billion)} 億`, `外資 ${sg(L(i).foreign_billion)}、投信 ${sg(L(i).itc_billion)}、自營商 ${sg(L(i).dealer_billion)} 億元；${facts(i)}。`)),
    boardOf('2. ⚡ 相對大盤表現最強的產業（動能領先）', '類股報酬指數 − 加權報酬指數', '#38bdf8',
      rank(inds, i => L(i).rs_pct, 1),
      i => item(i, `近 ${L(i).rs_days} 日 ${sg(L(i).rs_pct, 2)}%`, `${facts(i)}。`)),
    boardOf('3. 📈 營收年增最高的產業（實質營收爆發）', `${window.__HEATMAP_MONTH__ || '最新月'}營收，MOPS 全市場彙總`, '#34d399',
      rank(inds, i => L(i).yoy, 1),
      i => item(i, `營收年增 ${sg(L(i).yoy)}%`, `累計營收年增 ${sg(L(i).cum_yoy)}%、營收加速度 ${sg(L(i).accel)}（單月年增 − 累計年增）；旗下 ${L(i).companies} 家公司。`)),
    boardOf('4. 🌱 基本面強但資金尚未跟上（可能即將轉強）', '基本面分數高、資金流向分數低', '#a855f7',
      rank(scored.filter(i => i.score_fundamentals >= 65 && i.score_capital_flow <= 50), gap, 1),
      i => item(i, `基本面 ${i.score_fundamentals}／資金流向 ${i.score_capital_flow}`, `${facts(i)}。條件：基本面分數 ≥65 且資金流向分數 ≤50（機械式篩選，不是預測）。`)),
    boardOf('5. 📉 法人當日淨賣超金額最多的產業（避開弱勢）', '外資+投信+自營商，股數×收盤價', '#fb7185',
      rank(inds, i => L(i).foreign_billion + L(i).itc_billion + L(i).dealer_billion, -1).filter(i => (L(i).foreign_billion + L(i).itc_billion + L(i).dealer_billion) < 0),
      i => item(i, `三大法人 ${sg(L(i).foreign_billion + L(i).itc_billion + L(i).dealer_billion)} 億`, `外資 ${sg(L(i).foreign_billion)}、投信 ${sg(L(i).itc_billion)}、自營商 ${sg(L(i).dealer_billion)} 億元；${facts(i)}。`)),
    boardOf('6. 🚨 即時評分最低的產業', '模型總分由低到高', '#f59e0b',
      rank(scored, i => i.total_weighted_score, -1),
      i => item(i, `總分 ${i.total_weighted_score}｜狀態 ${i.rotation_state}`, `${facts(i)}。評分是相對其他產業的百分位，分數低代表「相對落後」，不等於一定下跌。`)),
  ];
}

function renderSixLeaderboards() {
  const liveBoards = buildLiveBoards();
  const grid = document.getElementById('sixLeaderboardsGrid');
  let note = document.getElementById('sixBoardsNote');
  if (!note) {
    note = document.createElement('div');
    note.id = 'sixBoardsNote';
    note.style.cssText = 'font-size:12.5px; margin:4px 2px 10px; color:var(--text-muted);';
    grid.parentNode.insertBefore(note, grid);
  }
  note.textContent = liveBoards
    ? `✅ 六個排行榜皆由官方即時資料產生（${((STATE.live_sankey || {}).as_of) || ''} 盤後），每個交易日收盤後更新。`
    : '⚠️ 此快照沒有即時指標，以下為 2026-11-21 前後手寫的靜態排行榜，不會隨資料更新。';
  const staticBoards = [
    {
      title: "1. 💰 資金流入最多的產業（規模主力）",
      badge: "內資ETF與法人重倉核心",
      color: "#10b981",
      items: [
        { name: "半導體－晶圓代工與先進封裝", metric: "總分 88.4 ｜ 0050權重核心", plain: "0050單月淨申購破2,200億與投信護盤最大受惠者，台積電10月營收5,868.9億創歷史新高。", indId: "IND_SEMI_FOUNDRY" },
        { name: "AI伺服器、機櫃系統與高速連接", metric: "總分 85.0 ｜ 10月營收破2兆", plain: "鴻海10月營收1.305兆、廣達3,532.5億(+104%)，長線內外資核心配置。", indId: "IND_AI_SERVER" },
        { name: "金融－金控、銀行、保險與證券", metric: "總分 79.7 ｜ 資金分流85分", plain: "11月大盤震盪期獲投信與存股資金大舉買進穩盤，受惠國銀放款創28年新高。", indId: "IND_FIN_HOLDING" }
      ]
    },
    {
      title: "2. ⚡ 資金流入速度最快的產業（動能領先）",
      badge: "近期相對大盤強弱居前",
      color: "#38bdf8",
      items: [
        { name: "金融－金控、銀行、保險與證券", metric: "20日相對大盤 +5.2%", plain: "科技股遭費半重挫拖累時，避險與利差擴張買盤流入速度居冠。", indId: "IND_FIN_HOLDING" },
        { name: "散熱與伺服器機構件", metric: "20日 +4.5% ｜ 60日 +16.5%", plain: "AI水冷散熱剛需強勁，每逢大盤反彈時資金回補速度最快（惟須留意估值擁擠度）。", indId: "IND_THERMAL" },
        { name: "半導體－晶圓代工與先進封裝", metric: "20日 +3.8% ｜ 60日 +14.2%", plain: "內資被動ETF銀彈每日逢低承接，抗跌領漲韌性極強。", indId: "IND_SEMI_FOUNDRY" }
      ]
    },
    {
      title: "3. 📈 基本面改善最快的產業（實質營收爆發）",
      badge: "10月營收與外銷訂單驗證",
      color: "#34d399",
      items: [
        { name: "AI伺服器、機櫃系統與高速連接", metric: "代表廠10月YoY +68.5%", plain: "10月資通信外銷訂單年增107.2%創高；廣達10月營收年增104%、貿聯-KY年增80%破百億。", indId: "IND_AI_SERVER" },
        { name: "半導體－設備、材料與測試介面", metric: "旺矽10月YoY +92.7%", plain: "受惠CSP自研AI ASIC晶片測試需求，探針卡龍頭旺矽10月營收22.32億年增92.7%創高。", indId: "IND_SEMI_EQUIP" },
        { name: "CPO光通訊與高階網通", metric: "智邦10月YoY +91.2%", plain: "800G資料中心交換器出貨大爆發，智邦10月營收達446.63億元、年增91.16%創歷史新高。", indId: "IND_CPO_NET" }
      ]
    },
    {
      title: "4. 🌱 可能即將轉強的產業（基本面強但股價未充分反映）",
      badge: "★ 不追高！低PEG潛力轉折區",
      color: "#c084fc",
      items: [
        { name: "AI伺服器一線系統組裝 (鴻海/廣達)", metric: "P/E僅 10.3x ~ 12.7x", plain: "10月營收雙創歷史新高(+45%~+104%)，但受11月外資期現貨避險壓抑，本益比僅10~12倍具極高安全邊際。", indId: "IND_AI_SERVER" },
        { name: "高階800G網通交換器 (智邦)", metric: "10月YoY +91.2%｜P/E 16.8x", plain: "別只看高本益比純題材股！智邦實質營收年增91%且TWSE官方本益比僅16.84倍，基本面遠強於股價反映。", indId: "IND_CPO_NET" },
        { name: "晶圓代工龍頭 (台積電)", metric: "10月YoY +59.7%｜P/E 20.4x", plain: "受費半單日重挫10%短線拖累，但10月營收近6千億年增近60%，PEG遠小於1，待外資賣壓收斂即具轉強潛力。", indId: "IND_SEMI_FOUNDRY" }
      ]
    },
    {
      title: "5. 📉 資金流出最快的產業（避開弱勢）",
      badge: "法人與市場資金持續撤離",
      color: "#f59e0b",
      items: [
        { name: "營建與不動產代銷", metric: "20日 -8.6% ｜ 60日 -18.5%", plain: "受央行信用管制與銀行排撥緊縮影響，外資與投信逢反彈持續減碼調節。", indId: "IND_CONSTRUCTION" },
        { name: "鋼鐵、塑化、水泥與化工", metric: "20日 -7.8% ｜ 60日 -15.4%", plain: "外資長期連續賣超傳統塑化與普鋼，市值型ETF權重持續萎縮。", indId: "IND_STEEL_PLASTIC" },
        { name: "機械、工具機與傳統車用", metric: "20日 -3.4% ｜ 60日 -5.2%", plain: "雖有台幣貶值匯兌支撐，但全球高利率壓抑傳統工具機訂單，資金偏觀望。", indId: "IND_MACH_AUTO" }
      ]
    },
    {
      title: "6. 🚨 目前風險最高的產業（LEVEL R / 估值擁擠警告）",
      badge: "基本面惡化或估值過熱洗牌",
      color: "#fb7185",
      items: [
        { name: "傳統塑化與大宗鋼鐵 (LEVEL R)", metric: "價值陷阱風險｜總分 43.0", plain: "雖股價淨值比低(如台塑P/B 0.52x)，但受中國產能過剩與10月進口礦產物價大漲雙重擠壓。", indId: "IND_STEEL_PLASTIC" },
        { name: "營建與不動產代銷 (LEVEL R)", metric: "政策緊縮風險｜總分 47.1", plain: "表面P/E看似極低(興富發P/E 7.25x、殖利率11%)，但此為過去完銷交屋之落後反映，未來新案去化與土建融成本壓力大。", indId: "IND_CONSTRUCTION" },
        { name: "純題材無實質EPS之二線CPO/設備高估值股", metric: "估值修正風險｜P/E > 60x", plain: "在美債殖利率近5%與費半重挫環境下，缺乏當季實質獲利支撐的高P/E題材股面臨劇烈去槓桿風險。", indId: "IND_CPO_NET" }
      ]
    }
  ];

  const boards = liveBoards || staticBoards;
  grid.innerHTML = boards.map(b => `
    <div class="lb-card" style="border-top: 4px solid ${b.color};">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; gap:8px; flex-wrap:wrap;">
        <strong style="font-size:17px; color:#fff;">${b.title}</strong>
        <span class="badge" style="background:rgba(255,255,255,0.08); color:${b.color}; font-size:13px;">${b.badge}</span>
      </div>
      ${b.items.map(it => `
        <div class="lb-item" ${it.indId ? `onclick="openIndustryByCode('${it.indId}')"` : ''}>
          <div style="flex:1; padding-right:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
              <strong style="color:#f8fafc; font-size:15.5px;">${it.name}</strong>
              <span style="font-size:14px; font-weight:800; color:${b.color};">${it.metric}</span>
            </div>
            <div style="font-size:14.5px; color:#cbd5e1; margin-top:5px; line-height:1.6;">${it.plain}</div>
          </div>
        </div>
      `).join('')}
    </div>
  `).join('');
}

function openIndustryByCode(indId) {
  const idx = (window.__HEATMAP_SECTORS__ || []).findIndex(s => s.id === indId);
  if (idx >= 0) openIndustryDrawer(idx);
}

/* =========================================================================
   7. 「市場正在發生什麼事」產業趨勢故事模式 (Trend Story Mode)
   ========================================================================= */
// 趨勢故事是依特定日期寫成的敘事文章 (沒有可即時化的來源)，每一篇都標明撰寫期間，避免被當成最新分析。
function renderTrendStories() {
  const stories = [
    {
      title: "故事一：台灣史上最大規模「內資被動化承接」正在對決「外資避險提款」",
      time: "2026年10月 ~ 11月21日（現在進行式）",
      industries: "晶圓代工(2330)、一線AI伺服器(2317/2382)、大型金控(2891/2882)",
      credibility: "A級（央行劃撥存款＋證交所BFI82U＋投信投顧公會申贖實證）",
      steps: [
        "1. 外部衝擊：美國10月通膨黏性使10年期美債殖利率逼近5%，加上11/20費城半導體指數重挫逾10%，外資11月在台股現貨大賣 5,494.6 億元、期貨空單高達 9.86 萬口。",
        "2. 內資覺醒：台灣散戶沒有恐慌逃命，反而將定期存款解約轉入交割戶（證券劃撥存款衝上 4.6981 兆元歷史新高）。",
        "3. 銀彈流向：內資在回檔時瘋狂申購元大台灣50 (0050)，11月單月淨申購衝破 2,200 億元改寫歷史紀錄，推升投信11月買超 1,597.6 億元。",
        "4. 結構改變：與此同時，主動式 ETF 遭數百億贖回、高股息 ETF 面臨貼息考驗，內資正從「盲目追高息」進化為「鎖定市值權值龍頭」。"
      ],
      support: "9月證券劃撥存款4.6981兆(月增1,269億)；11月0050淨申購>2,200億；投信Q3+Q4累計買超逾6,160億元。",
      counter: "台股上市融資餘額同步創下 8,343 億元歷史新高，若指數跌破 36,000 點，高槓桿散戶融資仍可能引發多殺多斷頭。",
      watch: "觀察 0050 每日申購淨額是否持續、融資餘額是否適度減肥，以及外資期貨空單何時降至 7 萬口以下。"
    },
    {
      title: "故事二：AI 進入「實質營收兌現與估值大洗牌」——一線低本益比龍頭勝出",
      time: "2026年10月營收公告 ~ 11月中旬 Nvidia 財報周",
      industries: "AI伺服器機櫃(2317/2382/3665)、800G網通(2345)、測試介面(6223)、水冷散熱(3017)",
      credibility: "A級（經濟部10月外銷訂單＋MOPS 1,989家10月營收＋TWSE BWIBBU估值實證）",
      steps: [
        "1. 訂單與營收狂飆：10月台灣外銷訂單達 1,238.2 億美元(+78.3%)、全體1,989家上市櫃10月營收達 6.8635 兆元(+45.49%)，雙雙改寫歷史單月新高。",
        "2. 龍頭數據說話：鴻海10月營收 1.305 兆(+45.7%)、台積電 5,868.9 億(+59.7%)、廣達 3,532.5 億(+104.0%)、智邦 446.6 億(+91.2%)、貿聯-KY 118.5 億(+80.0%)、旺矽 22.3 億(+92.7%)全面創高。",
        "3. 市場審視趨嚴：在美債近 5% 高利率環境下，法人不再為「只有題材沒有營收」的二線概念股買單。",
        "4. 估值安全邊際浮現：經11月震盪修正後，廣達官方本益比僅 10.28 倍、鴻海 12.70 倍、智邦 16.84 倍、台積電 20.36 倍，呈現「基本面創高但估值極具吸引力」的不對稱機會。"
      ],
      support: "10月電子產品外銷訂單 539.1 億美元(+89.8%)、資通信 467.7 億美元(+107.2%)雙創歷史新高。",
      counter: "10月新台幣計價進口物價年增高達 33.32%（AI晶片與記憶體價格走高），可能壓縮下游組裝廠第四季毛利率。",
      watch: "觀察 Q4 季報之「營業利益率」是否與營收同步創高，以及四大 CSP 對 2027 年資本支出之最新指引。"
    },
    {
      title: "故事三：房市「表面房貸創19個月新高」背後的真相——實質買氣急凍與資金撤出",
      time: "2026年9月 ~ 11月",
      industries: "營建與不動產代銷(2542/2501/5534)、銀行房貸部門",
      credibility: "A級（央行五大銀行新承做房貸＋內政部建物買賣移轉棟數交叉驗證）",
      steps: [
        "1. 表面數據迷思：央行公布10月五大銀行新承做購屋貸款回升至 727.89 億元（創19個月新高），許多人誤以為房市回溫。",
        "2. 拆解統計口徑：該筆撥款高達 45.32% 來自「新青安 2.0 末班車趕撥效應」以及過去預售屋完工交屋的強制撥款，屬於「落後交割指標」。",
        "3. 實質買氣真相：受央行第七波信用管制與銀行限貸排撥影響，2026全年全台建物買賣移轉棟數面臨 26 萬棟保衛戰，市場已全面轉為自住買方市場。",
        "4. 營建股價值陷阱警示：部分建商因交屋入帳呈現低本益比、高殖利率（如興富發 P/E 7.25x、殖利率 11.08%），但外資與投信持續撤出（60日相對大盤 -18.5%）。"
      ],
      support: "五大銀行10月新承做放款平均利率升至 2.254% 創 2009 年以來新高；營建類股觸發本系統 LEVEL R 資金撤退預警。",
      counter: "蛋黃區剛性自住需求與科技廠辦工程仍有基本盤支撐，不至於發生系統性爛尾樓危機。",
      watch: "觀察六都每月買賣移轉棟數年增率何時止跌回升，以及央行是否鬆綁不動產放款集中度上限。"
    },
    {
      title: "故事四：企業借貸擴產創 28 年新高，大型金控成為震盪市下的「攻守兼備避風港」",
      time: "2026年9月 ~ 11月",
      industries: "金融－金控、銀行、保險與證券(2891/2882/2881/2883)",
      credibility: "A級（中央銀行金融情況月報＋證交所類股相對強弱實證）",
      steps: [
        "1. 信貸需求爆發：9月全體貨幣機構放款與投資年增率達 9.79%（創1998年12月以來近28年新高），38家國銀放款總額達 49.68 兆元（單月大增 4,674 億元）。",
        "2. 利差實質擴張：因企業週轉金與擴產貸款需求極強，10月五大銀行新承做放款加權平均利率升至 2.254%，直接擴大商業銀行存放利差(NIM)。",
        "3. 震盪市穩盤主力：11月台股在四萬點劇烈震盪時，投信與內資防禦資金大舉進駐大型金控（金融類股20日相對大盤 +5.2% 居全市場第一）。",
        "4. 回測歷史驗證：本系統於 10/23 即對金控發出 LEVEL 3 預警，成功提前 22 天捕捉 11 月科技股震盪下的金控抗跌領漲行情。"
      ],
      support: "國銀總存款 68.54 兆、總放款 49.68 兆雙創歷史新高；中信金 P/E 16.5x、殖利率 3.68%，11/20獲外資逆勢買超 5,329 張。",
      counter: "美債10年期殖利率維持 4.97% 高檔加上台股波段回檔，對壽險比重過高之金控未實現淨值(OCI)仍有壓抑。",
      watch: "觀察美債10年期殖利率是否突破 5.25%，以及銀行淨利息收入(NII)季成長率。"
    }
  ];

  const storiesGrid = document.getElementById('trendStoriesGrid');
  let storiesNote = document.getElementById('trendStoriesNote');
  if (!storiesNote) {
    storiesNote = document.createElement('div');
    storiesNote.id = 'trendStoriesNote';
    storiesNote.style.cssText = 'font-size:12.5px; margin:4px 2px 10px; color:var(--text-muted);';
    storiesGrid.parentNode.insertBefore(storiesNote, storiesGrid);
  }
  storiesNote.textContent = '🕰️ 以下四篇是 2026-11-21 前後撰寫的敘事文章，引用當時的總經與市場數字，不會隨資料更新；最新數字請看上方即時區塊。';
  storiesGrid.innerHTML = stories.map(st => `
    <div class="story-card">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
        <span class="badge badge-grade-A">${st.credibility}</span>
        <span style="font-size:14px; color:var(--text-secondary);">🕒 ${st.time}</span>
      </div>
      <h3 style="font-size:19px; font-weight:700; color:#fff; margin-bottom:8px; line-height:1.4;">${st.title}</h3>
      <div style="font-size:14.5px; color:var(--accent-blue); margin-bottom:12px;"><strong>相關產業：</strong>${st.industries}</div>
      <div style="background:#0a0f1d; padding:14px 16px; border-radius:8px; font-size:15px; color:#e2e8f0; line-height:1.75; margin-bottom:10px;">
        ${st.steps.join('<br/>')}
      </div>
      <div class="evidence-box"><strong>🟢 支持證據：</strong>${st.support}</div>
      <div class="evidence-box counter"><strong>🔴 反面證據：</strong>${st.counter}</div>
      <div class="evidence-box invalid"><strong>🟠 後續觀察指標：</strong>${st.watch}</div>
    </div>
  `).join('');
}

