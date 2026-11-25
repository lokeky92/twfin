const TIMELINE_SNAPSHOTS = [
  {
    label: "2024下半年（AI伺服器萌芽／房市交屋高峰期）",
    flowSummary: "銀行房貸與預售屋交屋推升房市資金達高峰；台股資金初步集中於AI伺服器概念與高股息ETF募集熱潮。",
    hotIndustries: "營建不動產、AI伺服器代工、高股息成分股(航運/金融)",
    coldIndustries: "傳統塑化、大宗鋼鐵、成熟製程晶圓代工",
    rotationOrder: "高股息ETF募集潮 ➔ AI硬體初升段 ➔ 重電綠能",
    keyEvent: "央行祭出第七波選擇性信用管制前夕，房市移轉棟數處高檔；高股息ETF規模快速膨脹。",
    heatOverrides: { "IND_CONSTRUCTION": "B", "IND_AI_SERVER": "B", "IND_THERMAL": "C", "IND_FIN_HOLDING": "B", "IND_STEEL_PLASTIC": "D" }
  },
  {
    label: "2025上半年（CoWoS先進封裝擴產／國際關稅震盪期）",
    flowSummary: "外資因國際關稅政策不確定性短線調節，但台積電CoWoS資本支出與AI晶片需求確立，企業放款開始加速。",
    hotIndustries: "晶圓代工與CoWoS封裝(2330)、半導體濕製程設備(3131/3583)",
    coldIndustries: "營建不動產(信用管制發酵)、車用電子、傳統機械",
    rotationOrder: "晶圓代工龍頭 ➔ CoWoS先進封裝設備 ➔ 高階銅箔基板(CCL)",
    keyEvent: "2025年2月本系統回測觸發晶圓代工 LEVEL 4 預警，提前 42 天捕捉先進製程主升段。",
    heatOverrides: { "IND_SEMI_FOUNDRY": "A", "IND_SEMI_EQUIP": "A", "IND_CONSTRUCTION": "D", "IND_STEEL_PLASTIC": "D" }
  },
  {
    label: "2025下半年（AI水冷散熱毛利拐點／房市買氣明顯降溫）",
    flowSummary: "AI晶片功耗突破千瓦，資料中心由氣冷轉向水冷散熱；房市買賣移轉棟數年增率轉負，資金由房市撤往股市。",
    hotIndustries: "水冷散熱與機構件(3017/3324)、AI伺服器機櫃(2317/2382)",
    coldIndustries: "營建與代銷(觸發LEVEL R)、傳統塑化與鋼鐵",
    rotationOrder: "AI晶片與設備 ➔ 水冷板/CDU散熱零組件 ➔ 高速連接線束",
    keyEvent: "2025Q3季報驗證水冷散熱毛利率跳升；2025年11月本系統對營建業發出 LEVEL R 資金撤退警示（後續規避-24.8%相對落後）。",
    heatOverrides: { "IND_THERMAL": "A", "IND_AI_SERVER": "A", "IND_CONSTRUCTION": "E", "IND_STEEL_PLASTIC": "E" }
  },
  {
    label: "2026上半年（外銷訂單連紅／電力變壓器與ASIC測試崛起）",
    flowSummary: "北美資料中心電力缺口與CSP自研AI ASIC晶片放量，帶動台灣外銷訂單與機械電機設備進口連亮紅燈。",
    hotIndustries: "電力設備與重電外銷(1519)、AI ASIC探針卡測試介面(6223)、800G網通(2345)",
    coldIndustries: "二線消費性IC設計、傳統塑化、營建業",
    rotationOrder: "水冷散熱 ➔ 北美電力變壓器重電 ➔ AI ASIC測試介面與800G交換器",
    keyEvent: "台灣實質GDP於2026Q2成長達12.93%，景氣對策信號連續亮出紅燈。",
    heatOverrides: { "IND_POWER_GREEN": "A", "IND_SEMI_EQUIP": "A", "IND_CPO_NET": "B", "IND_CONSTRUCTION": "D" }
  },
  {
    label: "2026年8~9月（外匯存底破6,019億美元／證券劃撥存款4.7兆創高）",
    flowSummary: "外資8月大舉匯入推升外匯存底突破6,019億美元；9月定存解約轉入交割戶，證券劃撥存款達4.6981兆創歷史新高。",
    hotIndustries: "晶圓代工(2330)、AI伺服器整機櫃(2317/2382/3665)、水冷散熱、大型金控",
    coldIndustries: "傳統塑化鋼鐵、營建業",
    rotationOrder: "權值半導體與AI機櫃全面創高 ➔ 國銀放款年增9.79%創28年新高帶動金控利差",
    keyEvent: "2026Q3 GDP概估成長率高達14.36%，9月景氣燈號41分連續10個月紅燈，國銀企業外匯存款首破10兆元。",
    heatOverrides: {}
  },
  {
    label: "2026年10~11月最新（10月營收6.86兆創高／外資提款 vs 內資0050狂買2,200億）",
    flowSummary: "美債10Y殖利率近5%與費半11/20重挫10%引發外資提款；但10月外銷訂單1,238億美元(+78.3%)與上市櫃營收6.86兆雙創歷史新高，內資0050單月淨申購破2,200億歷史新高強力承接！",
    hotIndustries: "一線AI晶圓代工與伺服器(2330/2317/2382/3665)、水冷散熱(3017)、測試介面(6223)、大型金控(2891/2882)",
    coldIndustries: "高估值二線純題材AI股(洗牌撤出)、營建不動產(全年26萬棟保衛戰)、傳統塑化與大宗鋼鐵",
    rotationOrder: "外資期現貨提款高Beta題材股 ➔ 內資0050與投信鎖碼『一線營收創高AI龍頭＋大型金控＋投等債ETF』啞鈴配置",
    keyEvent: "10月外銷訂單1,238.2億美元(+78.3%)、海關出口967.6億美元(+58.9%)、五大銀行放款利率2.254%(17年新高)。",
    heatOverrides: {}
  }
];

// Sankey 時間切片設定
const SANKEY_PERIOD_CONFIGS = [
  { title: "2025-Q3：AI擴產啟動，外資與內資同步流入科技股，房市管制初見效", mult: [0.85, 0.8, 0.75, 0.6, 0.9, 0.85], finiOut: false },
  { title: "2025-Q4：第七波房市信用管制發酵，不動產資金明顯降溫並轉向股市與債券ETF", mult: [0.9, 0.85, 0.82, 0.7, 0.75, 0.9], finiOut: false },
  { title: "2026-Q2：外銷訂單連紅，企業向銀行借貸擴產(資本支出)流量顯著加粗", mult: [0.95, 0.9, 0.88, 0.85, 0.7, 0.95], finiOut: false },
  { title: "2026-08~09：外匯存底創6,019億美元高峰，證券劃撥存款衝上4.6981兆歷史新高", mult: [1.0, 0.95, 0.92, 0.9, 0.8, 0.98], finiOut: false },
  { title: "2026-10~11 最新基準：定存解約轉入0050(單月2,200億創高)與企業放款(+9.79%創28年新高)極粗；外資短線匯出調節(紅線逆流)", mult: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0], finiOut: true }
];

