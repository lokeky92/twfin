"""
台灣經濟資金流向與產業趨勢預警研究中心 (Taiwan Capital Flow Intelligence & Industry Rotation System)
資料庫架構與管理模組 (SQLite Database Schema & Governance Layer)
符合 Fable 5.2 執行規格 PART 3, PART 4, PART 7, PART 8, PART 9
"""
import sqlite3
import os
import json
from datetime import datetime

# 可用環境變數 TWFIN_DB_PATH 指定其他資料庫 (測試時使用暫存檔)
DB_PATH = os.environ.get("TWFIN_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "twfin_intelligence.db")

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- 1. 資料來源清單表 (PART 3 & PART 11-B)
CREATE TABLE IF NOT EXISTS data_sources (
    source_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    category TEXT NOT NULL,          -- 台灣總體經濟 / 金融監理與市場 / 企業及產業 / 房地產 / 國際
    publisher TEXT NOT NULL,         -- 發布機構 (e.g., 中央銀行, 主計總處, TWSE, TPEx)
    source_url TEXT NOT NULL,        -- 原始資料網址 / API Endpoint
    quality_grade TEXT NOT NULL CHECK(quality_grade IN ('A', 'B', 'C', 'D', 'E')), -- A官方原始, B正式金融機構, C已驗證市場, D新聞觀點, E模型推估
    access_method TEXT NOT NULL,     -- OpenAPI / RWD_JSON / CSV_Download / Web_Public / Paid_API
    api_key_required INTEGER NOT NULL DEFAULT 0,
    cost_tier TEXT NOT NULL DEFAULT '免費公開 (Free Public)',
    license_terms TEXT NOT NULL,
    update_frequency TEXT NOT NULL,  -- 每日 / 每週 / 每月 / 每季
    publication_lag_days INTEGER NOT NULL, -- 發布延遲天數 (用於防止回測未來資料洩漏)
    fallback_strategy TEXT NOT NULL, -- 中斷或無法自動取得時之替代方案
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    last_verified_at TEXT NOT NULL
);

-- 2. 資料字典表 (PART 3 & PART 11-C)
CREATE TABLE IF NOT EXISTS data_dictionary (
    metric_code TEXT PRIMARY KEY,
    metric_name TEXT NOT NULL,
    module_id TEXT NOT NULL,         -- M01 ~ M08
    source_id TEXT NOT NULL,
    observation_type TEXT NOT NULL CHECK(observation_type IN ('DIRECT_STAT', 'PROXY_INDICATOR', 'MODEL_ESTIMATE', 'UNOBSERVABLE')),
    unit TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'TWD',
    seasonal_adjustment TEXT NOT NULL DEFAULT 'NSA', -- SA / NSA
    statistical_scope TEXT NOT NULL, -- 統計口徑說明
    calculation_method TEXT NOT NULL,
    missing_value_policy TEXT NOT NULL DEFAULT 'MARK_MISSING_NO_IMPUTE',
    FOREIGN KEY (source_id) REFERENCES data_sources(source_id)
);

-- 3. 總體經濟與資金池時間序列資料表 (MODULE 01 & MODULE 03)
CREATE TABLE IF NOT EXISTS macro_observations (
    obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_code TEXT NOT NULL,
    period_covered TEXT NOT NULL,    -- 資料涵蓋期間 (e.g., '2026-09', '2026-10', '2026-Q3', '2026-11-20')
    release_date TEXT NOT NULL,      -- 官方發布日期 (Point-in-Time 回測基準日)
    fetched_at TEXT NOT NULL,        -- 系統擷取時間
    raw_value REAL,                  -- 原始值
    cleaned_value REAL,              -- 清理後數值
    prev_value REAL,                 -- 前期數值
    mom_pct REAL,                    -- 月增率 / 期增率 (%)
    yoy_pct REAL,                    -- 年增率 (%)
    quality_grade TEXT NOT NULL CHECK(quality_grade IN ('A', 'B', 'C', 'D', 'E')),
    observation_type TEXT NOT NULL CHECK(observation_type IN ('DIRECT_STAT', 'PROXY_INDICATOR', 'MODEL_ESTIMATE')),
    revision_version TEXT NOT NULL DEFAULT 'v1.0 (初值/最新公布)',
    notes TEXT,
    UNIQUE(metric_code, period_covered, revision_version),
    FOREIGN KEY (metric_code) REFERENCES data_dictionary(metric_code)
);

-- 4. 整體資產配置與資金流向矩陣表 (MODULE 02)
CREATE TABLE IF NOT EXISTS asset_allocation_flows (
    flow_id TEXT PRIMARY KEY,
    period_covered TEXT NOT NULL,
    release_date TEXT NOT NULL,
    source_pool TEXT NOT NULL,       -- 資金來源 (e.g., 銀行體系存款, 外資資金池, 民間超額儲蓄, 保險及退休基金)
    asset_class TEXT NOT NULL,       -- 資產類別 (股票市場, 債券市場, 房地產市場, 銀行定存/活存, 企業資本支出, 海外金融資產)
    sub_category TEXT NOT NULL,      -- 細項 (e.g., 證券劃撥存款, 市值型ETF 0050, 高股息ETF, 五大銀行新增房貸, 企業外匯存款)
    total_scale_value REAL,          -- 規模數值
    scale_unit TEXT NOT NULL,
    net_flow_value REAL,             -- 資金淨流入/流出或變動額
    flow_direction TEXT NOT NULL CHECK(flow_direction IN ('CONFIRMED_INFLOW', 'CONFIRMED_OUTFLOW', 'STRUCTURAL_SHIFT', 'UNCONFIRMED')),
    observation_type TEXT NOT NULL CHECK(observation_type IN ('DIRECT_STAT', 'PROXY_INDICATOR', 'MODEL_ESTIMATE', 'UNOBSERVABLE')),
    quality_grade TEXT NOT NULL CHECK(quality_grade IN ('A', 'B', 'C', 'D', 'E')),
    statistical_scope TEXT NOT NULL, -- 統計範圍與避免重複計算說明
    double_counting_guard TEXT NOT NULL, -- 如何避免重複計算 (附錄B必答)
    source_id TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (source_id) REFERENCES data_sources(source_id)
);

-- 5. 台灣產業完整分類與公司對照表 (MODULE 04 & PART 10-3)
CREATE TABLE IF NOT EXISTS industry_taxonomy (
    industry_id TEXT PRIMARY KEY,
    major_category TEXT NOT NULL,    -- 科技 / 傳統產業 / 金融 / 其他
    industry_name TEXT NOT NULL,
    sub_sectors TEXT NOT NULL,       -- 涵蓋次產業
    representative_companies TEXT NOT NULL, -- JSON array of {ticker, name, role}
    supply_chain_stage TEXT NOT NULL,
    data_completeness_pct REAL NOT NULL,
    cycle_stage TEXT NOT NULL        -- 復甦 / 擴張 / 高峰 / 衰退 / 落底 / 分化整理
);

-- 6. 產業資金輪動、基本面與評分歷史表 (MODULE 04, MODULE 05, PART 4)
CREATE TABLE IF NOT EXISTS industry_rotation_scores (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    industry_id TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    period_covered TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT 'v1.0.0',
    -- 資金與市場指標 (5/20/60/120/240日與法人趨勢)
    rel_strength_20d REAL,           -- 20日相對大盤強弱 (%)
    rel_strength_60d REAL,           -- 60日相對大盤強弱 (%)
    foreign_net_flow_trend TEXT,     -- 外資買賣超與持股趨勢
    itc_net_flow_trend TEXT,         -- 投信買賣超與持股趨勢
    dealer_net_flow_trend TEXT,      -- 自營商趨勢
    etf_flow_impact TEXT,            -- ETF申贖影響
    -- 基本面指標 (MODULE 05)
    rev_yoy_pct REAL,                -- 產業代表公司10月營收年增率 (%)
    rev_mom_pct REAL,                -- 產業代表公司10月營收月增率 (%)
    margin_trend TEXT,               -- 毛利率與營業利益率趨勢
    capex_inventory_status TEXT,     -- 資本支出與庫存狀態
    -- 狀態與轉折標籤 (MODULE 04)
    rotation_state TEXT NOT NULL CHECK(rotation_state IN ('A', 'B', 'C', 'D', 'E', 'INSUFFICIENT_DATA')),
    transition_tag TEXT NOT NULL,    -- 轉折標籤 (e.g., 基本面改善但股價落後, 資金流入轉強, 由流入轉流出...)
    -- PART 4 評分模型 (0-100)
    score_capital_flow REAL,         -- 資金流向分數 (權重 25%)
    score_fundamentals REAL,         -- 產業基本面分數 (權重 25%)
    score_future_growth REAL,        -- 未來成長性分數 (權重 20%)
    score_institutional REAL,        -- 法人布局分數 (權重 15%)
    score_valuation REAL,            -- 估值合理性分數 (權重 15%)
    total_weighted_score REAL,       -- 綜合加權總分 (若資料不足則為 NULL)
    short_term_momentum_score REAL,  -- 短期資金動能 (1-3M)
    mid_term_fundamental_score REAL, -- 中期基本面 (3-12M)
    long_term_structural_score REAL, -- 長期結構成長 (12-24M)
    confidence_level TEXT NOT NULL,  -- 高 / 中 / 低 / 不可評分
    missing_data_pct REAL NOT NULL,  -- 缺失資料比例 (%)
    supporting_evidence TEXT NOT NULL,
    counter_evidence TEXT NOT NULL,
    invalidation_conditions TEXT NOT NULL,
    data_limitations TEXT NOT NULL,
    UNIQUE(industry_id, as_of_date, model_version),
    FOREIGN KEY (industry_id) REFERENCES industry_taxonomy(industry_id)
);

-- 7. 個股研究中心與四類名單表 (MODULE 06)
CREATE TABLE IF NOT EXISTS company_research_watchlist (
    ticker TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    industry_id TEXT NOT NULL,
    watchlist_category TEXT NOT NULL CHECK(watchlist_category IN ('優先研究', '中長期觀察', '等待估值合理', '基本面或風險不佳')),
    supply_chain_position TEXT NOT NULL,
    latest_rev_period TEXT NOT NULL,
    latest_rev_billion_twd REAL,
    rev_mom_pct REAL,
    rev_yoy_pct REAL,
    eps_ttm_or_est TEXT NOT NULL,
    pe_ratio_status TEXT NOT NULL,
    institutional_ownership_trend TEXT NOT NULL,
    bull_case TEXT NOT NULL,         -- 支持理由
    bear_case TEXT NOT NULL,         -- 反對理由
    valuation_risk TEXT NOT NULL,    -- 估值風險
    invalidation_condition TEXT NOT NULL, -- 結論失效條件
    as_of_date TEXT NOT NULL,
    source_id TEXT NOT NULL,
    FOREIGN KEY (industry_id) REFERENCES industry_taxonomy(industry_id),
    FOREIGN KEY (source_id) REFERENCES data_sources(source_id)
);

-- 8. 產業趨勢提前預警引擎紀錄表 (MODULE 07)
CREATE TABLE IF NOT EXISTS trend_early_warnings (
    warning_id TEXT PRIMARY KEY,
    industry_id TEXT NOT NULL,
    alert_level TEXT NOT NULL CHECK(alert_level IN ('LEVEL 0', 'LEVEL 1', 'LEVEL 2', 'LEVEL 3', 'LEVEL 4', 'LEVEL R')),
    signal_category TEXT NOT NULL,   -- 資金提前進場 / 基本面轉折 / 市場尚未反映 / 資金撤退
    horizon TEXT NOT NULL,           -- 短期(1-3M) / 中期(3-12M) / 長期(12-24M)
    trigger_reason TEXT NOT NULL,
    raw_data_evidence TEXT NOT NULL,
    triggered_at TEXT NOT NULL,
    source_id TEXT NOT NULL,
    credibility_grade TEXT NOT NULL,
    missing_data_notes TEXT NOT NULL,
    counter_evidence TEXT NOT NULL,
    invalidation_conditions TEXT NOT NULL,
    FOREIGN KEY (industry_id) REFERENCES industry_taxonomy(industry_id)
);

-- 9. 情境分析與風險管理表 (PART 5)
CREATE TABLE IF NOT EXISTS scenario_analyses (
    scenario_id TEXT PRIMARY KEY,
    scenario_name TEXT NOT NULL,     -- 樂觀 / 中性 / 悲觀
    probability_weight TEXT NOT NULL,
    trigger_conditions TEXT NOT NULL,
    monitoring_indicators TEXT NOT NULL,
    beneficiary_industries TEXT NOT NULL,
    vulnerable_industries TEXT NOT NULL,
    capital_flow_direction TEXT NOT NULL,
    counter_evidence TEXT NOT NULL,
    invalidation_conditions TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 10. 模型版本、權重設定與更新日誌表 (PART 4, PART 8, PART 9)
CREATE TABLE IF NOT EXISTS model_governance_configs (
    version_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    weights_json TEXT NOT NULL,      -- {"capital_flow":0.25, "fundamentals":0.25, "future_growth":0.20, "institutional":0.15, "valuation":0.15}
    thresholds_json TEXT NOT NULL,   -- LEVEL 0 ~ LEVEL R thresholds
    change_reason TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ingestion_audit_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp TEXT NOT NULL,
    task_name TEXT NOT NULL,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SUCCESS', 'CACHED_VERIFIED', 'FALLBACK_USED', 'FAILED', 'STALE_WARNING')),
    records_affected INTEGER NOT NULL,
    message TEXT NOT NULL
);

-- 11. 三大法人每日/每週/每月/每季買賣超與期貨籌碼追蹤表 (MODULE 04 & MODULE 08 - 階段二/三)
CREATE TABLE IF NOT EXISTS institutional_flows (
    flow_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_type TEXT NOT NULL CHECK(period_type IN ('DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY')),
    period_label TEXT NOT NULL,      -- e.g., '2026-11-20', '2026-W47', '2026-11(MTD)', '2026-Q4(QTD)'
    release_date TEXT NOT NULL,
    market_scope TEXT NOT NULL,      -- 'TWSE+TPEx 合計' / 'TWSE 上市' / 'TPEx 上櫃'
    foreign_net_billion REAL NOT NULL,   -- 外資及陸資買賣超 (億元)
    itc_net_billion REAL NOT NULL,       -- 投信買賣超 (億元)
    dealer_prop_billion REAL NOT NULL,   -- 自營商(自行買賣) (億元)
    dealer_hedge_billion REAL NOT NULL,  -- 自營商(避險) (億元)
    total_3insti_billion REAL NOT NULL,  -- 三大法人合計 (億元)
    foreign_futures_oi_contracts INTEGER,-- 外資台指期未平倉淨部位 (口)
    margin_balance_billion REAL,         -- 上市融資餘額 (億元)
    top_buy_industries TEXT NOT NULL,    -- 法人主要買超產業
    top_sell_industries TEXT NOT NULL,   -- 法人主要賣超產業
    source_id TEXT NOT NULL,
    notes TEXT NOT NULL,
    UNIQUE(period_type, period_label, market_scope),
    FOREIGN KEY (source_id) REFERENCES data_sources(source_id)
);

-- 12. 資料品質監控、過期檢測與異常通知表 (PART 7 階段二/六 & PART 9)
CREATE TABLE IF NOT EXISTS data_quality_checks (
    check_id TEXT PRIMARY KEY,
    check_timestamp TEXT NOT NULL,
    target_table_or_metric TEXT NOT NULL,
    check_type TEXT NOT NULL CHECK(check_type IN ('FRESHNESS_SLA', 'ZSCORE_OUTLIER', 'DOUBLE_COUNT_AUDIT', 'MISSING_RATIO_GUARD', 'POINT_IN_TIME_LAG')),
    status TEXT NOT NULL CHECK(status IN ('PASS', 'WARNING', 'CRITICAL_ALERT')),
    expected_sla_or_bound TEXT NOT NULL,
    observed_value TEXT NOT NULL,
    action_taken TEXT NOT NULL
);

-- 13. 歷史樣本外回測與基準模型比較表 (PART 7 階段五 & PART 8)
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    run_timestamp TEXT NOT NULL,
    model_version TEXT NOT NULL,
    backtest_window TEXT NOT NULL,   -- e.g., '2025-01 ~ 2026-11 (22個月，共8個季度輪動節點，88個產業樣本)'
    split_method TEXT NOT NULL,      -- 時間序列滾動樣本外切分 (Expanding/Rolling Window Out-of-Sample)
    lookahead_guard TEXT NOT NULL,   -- Point-in-Time 延遲處理說明
    survivorship_guard TEXT NOT NULL,-- 存活者偏差處理說明
    cost_assumption_bps REAL NOT NULL, -- 單邊交易與摩擦成本假設 (bps)
    sample_count INTEGER NOT NULL,
    hit_rate_pct REAL NOT NULL,      -- 預警命中率 (%)
    false_positive_pct REAL NOT NULL,-- 誤報率 (%)
    false_negative_pct REAL NOT NULL,-- 漏報率 (%)
    avg_lead_time_days REAL NOT NULL,-- 平均提前預警天數
    model_cum_excess_return_pct REAL NOT NULL, -- LEVEL 3/4 組合累計超額報酬 (%)
    benchmark_taiex_return_pct REAL NOT NULL,  -- 基準一：台股加權指數同期表現 (%)
    benchmark_equal_weight_pct REAL NOT NULL,  -- 基準二：14產業等權重基準表現 (%)
    benchmark_naive_mom_pct REAL NOT NULL,     -- 基準三：單純過去20日股價動能基準 (%)
    level_r_avoided_drawdown_pct REAL NOT NULL,-- LEVEL R 成功規避之平均波段回撤 (%)
    regime_stability_notes TEXT NOT NULL,
    model_limitations TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_signal_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    signal_date TEXT NOT NULL,       -- 嚴格依據 release_date 觸發之歷史當下時點
    industry_id TEXT NOT NULL,
    alert_level TEXT NOT NULL,
    trigger_metrics_pit TEXT NOT NULL, -- 當時點已發布之 Point-in-Time 數據
    forward_3m_rel_return_pct REAL NOT NULL, -- 觸發後未來3個月相對大盤超額表現 (%)
    forward_6m_rel_return_pct REAL NOT NULL, -- 觸發後未來6個月相對大盤超額表現 (%)
    lead_time_days INTEGER NOT NULL,
    outcome_classification TEXT NOT NULL CHECK(outcome_classification IN ('TRUE_POSITIVE_HIT', 'FALSE_POSITIVE', 'MISS_LATE', 'RISK_AVOIDED_HIT')),
    review_notes TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id),
    FOREIGN KEY (industry_id) REFERENCES industry_taxonomy(industry_id)
);

-- 14. 固定研究報告中心 (每日/每週/每月/每季歷史版本比較 - PART 6 & MODULE 08)
CREATE TABLE IF NOT EXISTS research_reports (
    report_id TEXT PRIMARY KEY,
    frequency TEXT NOT NULL CHECK(frequency IN ('每日', '每週', '每月', '每季')),
    report_title TEXT NOT NULL,
    as_of_cutoff_date TEXT NOT NULL,
    published_at TEXT NOT NULL,
    update_status TEXT NOT NULL,
    primary_sources TEXT NOT NULL,
    executive_summary TEXT NOT NULL,
    key_findings_json TEXT NOT NULL, -- JSON array of sections
    assumptions_and_limits TEXT NOT NULL,
    counter_evidence TEXT NOT NULL,
    tracking_indicators TEXT NOT NULL,
    version_tag TEXT NOT NULL
);

-- 15. 全市場上市櫃公司真實月營收、估值與三大法人明細表 (LIVE OPENAPI INGESTION - 1,989+ 家公司)
CREATE TABLE IF NOT EXISTS live_company_fundamentals (
    company_code TEXT NOT NULL,
    company_name TEXT NOT NULL,
    market_type TEXT NOT NULL CHECK(market_type IN ('TWSE', 'TPEx')),
    official_industry TEXT NOT NULL,
    mapped_industry_id TEXT,
    data_ym TEXT NOT NULL,           -- 資料年月 (e.g., '11510' = 2026-10)
    report_date TEXT NOT NULL,       -- 出表日期 (e.g., '1151117')
    rev_current_thousand REAL,       -- 當月營收 (仟元)
    rev_prev_month_thousand REAL,    -- 上月營收 (仟元)
    rev_last_year_thousand REAL,     -- 去年當月營收 (仟元)
    rev_mom_pct REAL,                -- 上月比較增減 (%)
    rev_yoy_pct REAL,                -- 去年同月增減 (%)
    cum_rev_current_thousand REAL,   -- 當月累計營收 (仟元)
    cum_rev_last_year_thousand REAL, -- 去年累計營收 (仟元)
    cum_rev_yoy_pct REAL,            -- 前期比較增減 (%)
    pe_ratio REAL,                   -- 本益比 (來自 BWIBBU_ALL / TPEx PE API)
    pb_ratio REAL,                   -- 股價淨值比
    dividend_yield REAL,             -- 殖利率 (%)
    foreign_net_shares INTEGER,      -- 最新交易日外資買賣超股數 (來自 T86 / TPEx 3Insti)
    itc_net_shares INTEGER,          -- 最新交易日投信買賣超股數
    dealer_net_shares INTEGER,       -- 最新交易日自營商買賣超股數
    total_3insti_net_shares INTEGER, -- 最新交易日三大法人合計買賣超股數
    insti_trade_date TEXT,           -- 法人交易日期 (e.g., '20261120')
    fetched_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (company_code, data_ym)
);

-- 16. 證交所真實盤後指數與產業類股指數表 (LIVE MI_INDEX)
CREATE TABLE IF NOT EXISTS live_market_indices (
    index_name TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    close_index REAL,
    change_dir TEXT,
    change_points REAL,
    change_pct REAL,
    fetched_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    PRIMARY KEY (index_name, trade_date)
);

-- ============================================================================
-- ETF 投資決策中心擴充資料表 (17 ~ 23) — 嚴格保留原有 1~16 張表不動
-- ============================================================================

-- 17. 台美 ETF 完整主檔表 (區塊三：基本資料、基金品質、交易與稅務制度、槓反隔離)
CREATE TABLE IF NOT EXISTS etf_master (
    etf_code TEXT PRIMARY KEY,
    etf_name TEXT NOT NULL,
    listing_market TEXT NOT NULL CHECK(listing_market IN ('TW', 'US')),
    exchange_name TEXT NOT NULL,     -- TWSE / TPEx / NYSE Arca / NASDAQ
    issuer TEXT NOT NULL,            -- 發行商 (元大/富邦/國泰/群益/復華/Vanguard/iShares/SPDR/VanEck/Invesco...)
    tracking_index TEXT NOT NULL,    -- 追蹤指數
    inception_date TEXT NOT NULL,    -- 成立日期
    aum_value REAL,                  -- 基金規模 (AUM)
    aum_unit TEXT NOT NULL,          -- 億元(TWD) / 億美元(USD)
    aum_change_1m_pct REAL,          -- 近1月規模變化 (%)
    currency TEXT NOT NULL,          -- TWD / USD
    management_style TEXT NOT NULL CHECK(management_style IN ('被動指數型', '主動管理型', '因子智慧貝塔')),
    asset_class TEXT NOT NULL CHECK(asset_class IN ('股票', '債券', '商品與貴金屬', 'REITs不動產', '多資產')),
    target_region TEXT NOT NULL,     -- 台灣 / 美國 / 全球 / 新興市場
    sub_category TEXT NOT NULL,      -- 對應第二節台灣17類與美國23類細分分類
    investment_style TEXT NOT NULL,  -- 大型權值 / 全市場 / 高股息 / 成長 / 價值 / 科技半導體 / AI主題 / 長天期公債 / 投資級債 / 非投資級債 / 短債現金 / 抗通膨TIPS / 低波動 / 槓桿反向
    fx_hedged TEXT NOT NULL,         -- 無避險(自然曝險) / 台幣計價無避險 / 具匯率避險
    is_leveraged_or_inverse INTEGER NOT NULL DEFAULT 0, -- 1=槓桿/反向/期貨複雜結構(強制獨立隔離警示)
    mgmt_fee_pct REAL,               -- 管理費 (%)
    total_expense_ratio_pct REAL,    -- 總費用率 TER (%)
    tracking_error_pct REAL,         -- 年化追蹤誤差 (%)
    tracking_difference_pct REAL,    -- 年度追蹤差異 (%)
    dividend_frequency TEXT NOT NULL,-- 季配 / 月配 / 半年配 / 年配 / 不配息
    tax_and_trading_notes TEXT NOT NULL, -- 交易時間、交割制度(T+2 vs T+1)、稅務口徑(54C/平準金/海外所得/美股30%預扣稅/QI退稅)
    quality_grade TEXT NOT NULL CHECK(quality_grade IN ('A', 'B', 'C', 'D', 'E')),
    source_url TEXT NOT NULL,
    as_of_date TEXT NOT NULL
);

-- 18. ETF 每日市場行情、折溢價、買賣價差、債券殖利率與績效風險表
CREATE TABLE IF NOT EXISTS etf_daily_metrics (
    etf_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    close_price REAL,
    change_pct REAL,
    nav_price REAL,                  -- 基金淨值 (若官方未即時公布則為 NULL)
    premium_discount_pct REAL,       -- 折溢價率 (%) = (市價-淨值)/淨值*100
    volume_shares INTEGER,           -- 成交股數 (由 TWSE 0099P / TPEx 即時同步)
    turnover_value REAL,             -- 成交金額
    bid_price REAL,                  -- 最後揭示買價 (由 TWSE 0099P 即時同步)
    ask_price REAL,                  -- 最後揭示賣價 (由 TWSE 0099P 即時同步)
    bid_ask_spread_bps REAL,         -- 買賣價差 (bps) = (賣價-買價)/中價*10000
    primary_net_flow_value REAL,     -- 初級市場淨申贖金額 (億元TWD / 億美元USD，嚴格區分次級市場成交量!)
    foreign_net_shares INTEGER,      -- 外資當日買賣超股數 (由 T86 / TPEx 同步)
    itc_net_shares INTEGER,          -- 投信當日買賣超股數
    dealer_net_shares INTEGER,       -- 自營商當日買賣超股數
    regular_saving_accounts INTEGER, -- 定期定額交易戶數 (由 TWSE ETFRank 官方API同步)
    -- 底層估值與債券/商品專屬指標
    weighted_pe REAL,                -- 底層成分股加權本益比 (股票型)
    weighted_pb REAL,                -- 底層成分股加權股價淨值比
    weighted_rev_yoy_pct REAL,       -- 底層成分股加權最新月營收年增率 (由 1,989 家 MOPS 真實數據穿透計算!)
    weighted_roe_pct REAL,           -- 底層成分股加權 ROE (%)
    dividend_yield_pct REAL,         -- 近12個月配息殖利率 (%)
    bond_ytm_pct REAL,               -- 債券型：平均到期殖利率 YTM (%)
    bond_duration_years REAL,        -- 債券型：平均有效存續期間 (年)
    bond_avg_credit_rating TEXT,     -- 債券型：平均信用評等 (AAA / AA / A / BBB / BB)
    bond_credit_spread_bps REAL,     -- 債券型：信用利差 OAS (bps)
    roll_yield_cost_note TEXT,       -- 商品/槓反型：期貨轉倉成本與波動耗損說明
    -- 歷史績效與風險指標
    return_1y_total_pct REAL,        -- 近1年含息總報酬 (%)
    return_3y_ann_pct REAL,          -- 近3年年化含息總報酬 (%)
    return_5y_ann_pct REAL,          -- 近5年年化含息總報酬 (%)
    return_price_only_1y_pct REAL,   -- 近1年純價格報酬 (不含息 %)
    twd_adjusted_1y_return_pct REAL, -- 換算新台幣後之近1年實際總報酬 (%)
    annualized_volatility_pct REAL,  -- 年化波動度 (%)
    max_drawdown_pct REAL,           -- 歷史最大回撤 (%)
    beta_vs_market REAL,             -- Beta 係數
    corr_tw_stock REAL,              -- 與台股大盤(0050)相關係數
    corr_us_stock REAL,              -- 與美股大盤(S&P 500)相關係數
    corr_us_bond REAL,               -- 與美國長債(TLT)相關係數
    missing_fields_note TEXT NOT NULL, -- 缺失欄位誠實揭露
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (etf_code, trade_date),
    FOREIGN KEY (etf_code) REFERENCES etf_master(etf_code)
);

-- 19. ETF 底層持股、集中度與產業/國家配置表 (用於穿透 1,989 家個股與計算 Overlap 重疊度)
CREATE TABLE IF NOT EXISTS etf_holdings (
    holding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    etf_code TEXT NOT NULL,
    constituent_code TEXT NOT NULL,  -- 成分股代號 (如 '2330', '2317', 'NVDA', 'AAPL', 'US_TREASURY_20Y'...)
    constituent_name TEXT NOT NULL,
    weight_pct REAL NOT NULL,        -- 持股權重 (%)
    mapped_industry_id TEXT,         -- 對應本系統 14 大產業 ID (如 IND_SEMI_FOUNDRY, IND_AI_SERVER...)
    country_code TEXT NOT NULL,      -- TW / US / GLOBAL
    as_of_date TEXT NOT NULL,
    source_note TEXT NOT NULL,
    UNIQUE(etf_code, constituent_code),
    FOREIGN KEY (etf_code) REFERENCES etf_master(etf_code)
);

CREATE TABLE IF NOT EXISTS etf_allocation_summary (
    etf_code TEXT PRIMARY KEY,
    top10_concentration_pct REAL NOT NULL, -- 前十大持股合計權重 (%)
    max_single_weight_pct REAL NOT NULL,   -- 最大單一持股權重 (%)
    max_single_holding_name TEXT NOT NULL, -- 最大單一持股名稱
    sector_weights_json TEXT NOT NULL,     -- 產業配置 JSON {"半導體": 62.5, "金融": 12.4, ...}
    country_weights_json TEXT NOT NULL,    -- 國家配置 JSON {"台灣": 100.0} 或 {"美國": 96.5, ...}
    holdings_coverage_note TEXT NOT NULL,  -- 揭露前十大涵蓋率與長尾映射方式
    FOREIGN KEY (etf_code) REFERENCES etf_master(etf_code)
);

-- 20. 高股息與債券 ETF 配息來源結構拆解表 (第六節：禁止只用殖利率判斷好壞)
CREATE TABLE IF NOT EXISTS etf_dividend_breakdown (
    etf_code TEXT PRIMARY KEY,
    latest_ex_div_period TEXT NOT NULL,
    annualized_div_yield_pct REAL NOT NULL,
    dividend_income_ratio_pct REAL NOT NULL,   -- 股利所得(54C)或債券票息佔比 (%)
    capital_gains_ratio_pct REAL NOT NULL,     -- 已實現資本利得(價差)佔比 (%)
    equalization_reserve_ratio_pct REAL NOT NULL, -- 收益平準金佔比 (%)
    fill_dividend_status TEXT NOT NULL,        -- 填息紀錄與11月除息後填息/貼息實況
    cashflow_sustainability_grade TEXT NOT NULL, -- 配息健康度診斷
    analysis_note TEXT NOT NULL,
    source_url TEXT NOT NULL,
    FOREIGN KEY (etf_code) REFERENCES etf_master(etf_code)
);

-- 21. 雙軌獨立評分與決策表 (模型 A 長期配置 vs 模型 B 短中期進場 — 嚴禁混為單一分數!)
CREATE TABLE IF NOT EXISTS etf_dual_scores (
    etf_code TEXT PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT 'ETF_DUAL_v1.0',
    eval_methodology_type TEXT NOT NULL, -- 市值型 / 高股息型 / 科技產業型 / 債券型 / 海外跨國型 / REITs與商品型 / 槓桿反向隔離型
    -- 模型 A：長期配置評估 (3~10年｜權重 25/20/20/20/15)
    score_a_underlying_quality REAL,     -- 底層資產與指數品質 (25%)
    score_a_diversification_role REAL,   -- 分散程度與投資組合角色 (20%)
    score_a_long_valuation_rr REAL,      -- 長期估值與預期風險報酬 (20%)
    score_a_cost_liquidity_track REAL,   -- 基金成本、規模、流動性與追蹤品質 (20%)
    score_a_complementarity REAL,        -- 與既有持倉/基準互補性 (15%)
    total_score_a_long_term REAL,        -- 模型 A 長期配置總分 (0~100，若為槓反或資料不足則設特殊標記)
    conclusion_a_long_term TEXT NOT NULL CHECK(conclusion_a_long_term IN ('適合進一步研究', '條件普通', '需注意集中風險', '不符合配置角色', '資料不足，暫不評分')),
    -- 模型 B：短中期進場時機評估 (1~3M & 3~12M｜權重 20/20/20/20/20)
    score_b_macro_environment REAL,      -- 總體經濟環境 (20%)
    score_b_flow_and_breadth REAL,       -- 資金流向與市場廣度 (20%)
    score_b_trend_and_momentum REAL,     -- 價格趨勢與底層基本面動能 (20%)
    score_b_valuation_and_pos REAL,      -- 估值與價格/折溢價位置 (20%)
    score_b_vol_event_downside REAL,     -- 波動、事件與下行風險 (20%)
    total_score_b_short_mid REAL,        -- 模型 B 短中期環境總分 (0~100)
    conclusion_b_short_mid TEXT NOT NULL CHECK(conclusion_b_short_mid IN ('條件相對有利', '持續觀察', '等待更佳條件', '風險偏高', '資料不足，暫不評分')),
    -- 雙軌分歧與獨立診斷
    divergence_tag TEXT NOT NULL,        -- e.g., '長線優質惟短線等待更佳條件', '長短線雙重順風', '短線高息惟長線注意資本利得耗損', '槓桿耗損僅供極短線交易'
    top_advantage TEXT NOT NULL,         -- 最大優勢
    top_risk TEXT NOT NULL,              -- 最大風險
    supporting_evidence TEXT NOT NULL,   -- 支持證據
    counter_evidence TEXT NOT NULL,      -- 反方證據
    contradiction_notes TEXT NOT NULL,   -- 指標矛盾說明 (第十四節強制要求)
    invalidation_conditions TEXT NOT NULL, -- 判斷失效條件
    next_watch_indicator TEXT NOT NULL,  -- 下一個重要觀察指標
    credibility_grade TEXT NOT NULL,     -- 資料可信度 (A / B / C)
    missing_data_pct REAL NOT NULL,      -- 資料缺失比例 (%)
    FOREIGN KEY (etf_code) REFERENCES etf_master(etf_code)
);

-- 22. ETF 雙軌獨立歷史回測表 (第十三節：長期模型 A 與短中期模型 B 分開回測)
CREATE TABLE IF NOT EXISTS etf_backtest_runs (
    bt_id TEXT PRIMARY KEY,
    model_track TEXT NOT NULL CHECK(model_track IN ('MODEL_A_LONG_TERM', 'MODEL_B_SHORT_MID')),
    test_period TEXT NOT NULL,
    sample_description TEXT NOT NULL,
    cost_and_tax_assumptions TEXT NOT NULL, -- 交易成本、買賣價差、匯率、美股30%股息預扣稅、二代健保補充保費假設
    biases_guarded TEXT NOT NULL,           -- 防止未來資料洩漏、存活者偏差、下市/指數變更處理
    key_metrics_json TEXT NOT NULL,         -- JSON summary of returns, max_dd, vol, sharpe, hit_rate, false_signal_rate
    regime_performance_notes TEXT NOT NULL,
    failure_cases_and_limits TEXT NOT NULL,
    executed_at TEXT NOT NULL
);

-- 23. ETF 自動研究報告中心 (第十二節：每日/每週/每月/重大事件報告，強制包含7大問題)
CREATE TABLE IF NOT EXISTS etf_research_reports (
    etf_report_id TEXT PRIMARY KEY,
    report_type TEXT NOT NULL CHECK(report_type IN ('每日報告', '每週報告', '每月報告', '重大事件報告')),
    report_title TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    q1_what_happened TEXT NOT NULL,      -- 1. 發生什麼事？
    q2_supporting_data TEXT NOT NULL,    -- 2. 哪些數據支持？
    q3_affected_etfs TEXT NOT NULL,      -- 3. 對哪些 ETF 有影響？
    q4_positive_impacts TEXT NOT NULL,   -- 4. 可能的正面影響？
    q5_negative_impacts TEXT NOT NULL,   -- 5. 可能的負面影響（反方證據）？
    q6_next_watch TEXT NOT NULL,         -- 6. 接下來應該觀察什麼？
    q7_invalidation TEXT NOT NULL,       -- 7. 哪些條件會讓目前判斷失效？
    primary_sources TEXT NOT NULL,
    version_tag TEXT NOT NULL
);

-- 查詢效能索引 (get_dashboard_payload 與權重重算的常用條件)
CREATE INDEX IF NOT EXISTS idx_irs_model_version ON industry_rotation_scores(model_version);
CREATE INDEX IF NOT EXISTS idx_tew_industry ON trend_early_warnings(industry_id);
CREATE INDEX IF NOT EXISTS idx_mgc_active ON model_governance_configs(active, created_at);
CREATE INDEX IF NOT EXISTS idx_lcf_industry ON live_company_fundamentals(mapped_industry_id);
CREATE INDEX IF NOT EXISTS idx_lcf_rev ON live_company_fundamentals(rev_current_thousand);
CREATE INDEX IF NOT EXISTS idx_etf_daily_code ON etf_daily_metrics(etf_code);
"""

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # timeout：伺服器多執行緒同時寫入時等待鎖釋放，而不是立即拋出 "database is locked"
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_connection()
    with conn:
        conn.executescript(SCHEMA_SQL)
    conn.close()
    return DB_PATH

if __name__ == "__main__":
    path = init_database()
    print(f"Database initialized at: {path}")
