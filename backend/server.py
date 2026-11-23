"""
台灣經濟資金流向與產業趨勢預警研究中心 (Taiwan Capital Flow Intelligence & Industry Rotation System)
後端 API 與網頁伺服器 (HTTP Server + REST API + Live Connector + Dynamic Re-Scoring Engine)
支援：
- 查詢真實總體經濟指標、資產配置流向矩陣、14大產業輪動評分、預警訊號、個股研究中心、資料來源清單與資料字典
- 動態調整 PART 4 評分權重 (保留歷史版本與變更理由於 SQLite) 並即時重算所有產業分數
- 執行真實外部 API 連線測試 (TWSE / TPEx / Gov OpenData)，並自動記錄審計日誌與離線降級保護
"""
import hmac
import json
import os
import re
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from common import logger, now_iso, now_tw
from db import DB_PATH, get_connection
from scoring import (
    DEFAULT_THRESHOLDS,
    classify_alert_level,
    compute_weighted_total,
    parse_weights,
    validate_thresholds,
)
from seed_and_engine import seed_and_compute_all
from live_api_connector import run_live_ingestion
from etf_engine import build_and_compute_etf_center
import sys

BASE_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_ROOT_DIR not in sys.path:
    sys.path.insert(0, BASE_ROOT_DIR)
from argon_multi_agent.engine.multi_agent_orchestrator import (
    get_multi_agent_state,
    run_full_multi_agent_session,
    update_proposal_approval_status
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

# 寫入型 API 的管理權杖。未設定時只允許本機 (127.0.0.1) 呼叫寫入端點。
ADMIN_TOKEN = os.environ.get("TWFIN_ADMIN_TOKEN", "").strip()
LOCAL_ADDRESSES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
MAX_BODY_BYTES = 64 * 1024

# 每個模型版本都會複製一份產業分數；只保留最近 N 個版本的分數列以免資料表無限成長
KEEP_SCORE_VERSIONS = 20

# 各區塊資料來源分類 (顯示於前端「即時 / 種子」標示)
LIVE_SECTIONS = ["上市櫃月營收與估值 (MOPS/TWSE/TPEx)", "三大法人個股買賣超", "大盤與類股指數", "ETF 每日行情"]
SEED_SECTIONS = ["總體經濟指標", "資產配置流向矩陣", "產業輪動子分數", "趨勢預警訊號", "個股研究名單",
                 "情境分析", "歷史回測結果", "固定研究報告", "ETF 持股／配息／回測", "AI 研究團隊 (規則式模擬)"]


class AuthError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


_payload_cache = {"key": None, "data": None}
_payload_lock = threading.Lock()


def _db_signature():
    try:
        st = os.stat(DB_PATH)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def invalidate_dashboard_cache():
    with _payload_lock:
        _payload_cache["key"] = None
        _payload_cache["data"] = None


def get_dashboard_payload(use_cache=True):
    """
    回傳儀表板完整資料。資料庫部分依 SQLite 檔案的 (mtime, size) 快取，
    只有資料庫實際變動 (排程擷取、權重調整…) 時才重新查詢；多 Agent 狀態每次即時讀取。
    """
    key = _db_signature()
    with _payload_lock:
        hit = use_cache and key is not None and _payload_cache["key"] == key
        cached = _payload_cache["data"] if hit else None
    if cached is None:
        cached = _build_dashboard_base()
        with _payload_lock:
            _payload_cache["key"] = key
            _payload_cache["data"] = cached
    payload = dict(cached)
    payload["multi_agent_center"] = get_multi_agent_state()
    return payload


def _data_provenance(cur):
    cur.execute("SELECT COUNT(*) AS n FROM live_company_fundamentals")
    live_rows = cur.fetchone()["n"]
    cur.execute("""
        SELECT MAX(run_timestamp) AS ts FROM ingestion_audit_logs
        WHERE substr(task_name, 1, 5) = 'LIVE_' AND task_name != 'LIVE_CONNECTOR_CHECK' AND status = 'SUCCESS'
    """)
    last_live = cur.fetchone()["ts"]
    return {
        "live_data_available": bool(live_rows and last_live),
        "last_live_ingestion": last_live,
        "live_sections": LIVE_SECTIONS,
        "seed_sections": SEED_SECTIONS,
        "note": "「種子」區塊的數值為程式內建的參考資料 (seed_and_engine.py / phase2_to_6_engine.py / etf_engine.py)，"
                "不會隨每日排程自動更新；只有「即時」區塊來自官方 OpenAPI。",
    }


def _build_dashboard_base():
    conn = get_connection()
    cur = conn.cursor()

    # 1. 最新總體經濟指標 (每個 metric_code 取最新一期與歷史序列)
    cur.execute("""
        SELECT m.*, d.metric_name, d.module_id, d.unit, d.currency, d.statistical_scope,
               d.calculation_method, s.publisher, s.source_url
        FROM macro_observations m
        JOIN data_dictionary d ON m.metric_code = d.metric_code
        JOIN data_sources s ON d.source_id = s.source_id
        ORDER BY m.metric_code, m.period_covered ASC
    """)
    all_macro_rows = [dict(r) for r in cur.fetchall()]
    macro_latest = {}
    macro_series = {}
    for r in all_macro_rows:
        code = r["metric_code"]
        macro_series.setdefault(code, []).append(r)
        macro_latest[code] = r

    # 2. 資產配置與資金流向矩陣 (MODULE 02)
    cur.execute("""
        SELECT a.*, s.publisher, s.source_url
        FROM asset_allocation_flows a
        JOIN data_sources s ON a.source_id = s.source_id
        ORDER BY a.flow_id ASC
    """)
    asset_flows = [dict(r) for r in cur.fetchall()]

    # 3. 當前啟用的模型版本與權重
    cur.execute("SELECT * FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
    active_model = dict(cur.fetchone())
    active_model["weights"] = json.loads(active_model["weights_json"])
    active_model["thresholds"] = json.loads(active_model["thresholds_json"])

    # 4. 產業輪動排行榜與未評分清單 (MODULE 04, 05 & PART 4)
    cur.execute("""
        SELECT r.*, t.major_category, t.industry_name, t.sub_sectors,
               t.representative_companies, t.supply_chain_stage, t.data_completeness_pct, t.cycle_stage
        FROM industry_rotation_scores r
        JOIN industry_taxonomy t ON r.industry_id = t.industry_id
        WHERE r.model_version = ?
        ORDER BY CASE WHEN r.total_weighted_score IS NULL THEN 1 ELSE 0 END,
                 r.total_weighted_score DESC
    """, (active_model["version_id"],))
    industries = []
    for r in cur.fetchall():
        d = dict(r)
        d["representative_companies"] = json.loads(d["representative_companies"])
        industries.append(d)

    # 5. 趨勢預警中心 (MODULE 07)
    cur.execute("""
        SELECT w.*, t.industry_name, t.major_category, s.publisher, s.source_url
        FROM trend_early_warnings w
        JOIN industry_taxonomy t ON w.industry_id = t.industry_id
        JOIN data_sources s ON w.source_id = s.source_id
        ORDER BY CASE w.alert_level
            WHEN 'LEVEL 4' THEN 1
            WHEN 'LEVEL 3' THEN 2
            WHEN 'LEVEL 2' THEN 3
            WHEN 'LEVEL R' THEN 4
            WHEN 'LEVEL 1' THEN 5
            ELSE 6 END
    """)
    warnings = [dict(r) for r in cur.fetchall()]

    # 6. 個股研究中心與四類名單 (MODULE 06)
    cur.execute("""
        SELECT c.*, t.industry_name, t.major_category, s.publisher
        FROM company_research_watchlist c
        JOIN industry_taxonomy t ON c.industry_id = t.industry_id
        JOIN data_sources s ON c.source_id = s.source_id
        ORDER BY CASE c.watchlist_category
            WHEN '優先研究' THEN 1
            WHEN '中長期觀察' THEN 2
            WHEN '等待估值合理' THEN 3
            WHEN '基本面或風險不佳' THEN 4
            ELSE 5 END, c.rev_yoy_pct DESC
    """)
    companies = [dict(r) for r in cur.fetchall()]

    # 7. 情境分析 (PART 5)
    cur.execute("SELECT * FROM scenario_analyses ORDER BY scenario_id ASC")
    scenarios = [dict(r) for r in cur.fetchall()]

    # 8. 資料來源清單與資料字典 (PART 3 & PART 11)
    cur.execute("SELECT * FROM data_sources ORDER BY source_id ASC")
    sources = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT d.*, s.publisher, s.quality_grade, s.update_frequency, s.publication_lag_days
        FROM data_dictionary d
        JOIN data_sources s ON d.source_id = s.source_id
        ORDER BY d.module_id, d.metric_code
    """)
    dictionary = [dict(r) for r in cur.fetchall()]

    # 9. 模型歷史版本與審計日誌
    cur.execute("SELECT * FROM model_governance_configs ORDER BY created_at DESC")
    model_versions = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM ingestion_audit_logs ORDER BY log_id DESC LIMIT 25")
    audit_logs = [dict(r) for r in cur.fetchall()]

    # 10. 三大法人每日/每週/每月/每季資金追蹤 (MODULE 04 & MODULE 08 - 階段二/三)
    cur.execute("""
        SELECT i.*, s.publisher
        FROM institutional_flows i
        JOIN data_sources s ON i.source_id = s.source_id
        ORDER BY i.flow_record_id ASC
    """)
    institutional_flows = [dict(r) for r in cur.fetchall()]

    # 11. 資料品質監控、SLA過期檢測與Z-Score異常通知 (階段二/六)
    cur.execute("SELECT * FROM data_quality_checks ORDER BY check_id ASC")
    dq_checks = [dict(r) for r in cur.fetchall()]

    # 12. 歷史樣本外回測與基準模型比較 (階段五 & PART 8)
    cur.execute("SELECT * FROM backtest_runs ORDER BY run_timestamp DESC")
    backtest_runs = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT e.*, t.industry_name, t.major_category
        FROM backtest_signal_events e
        JOIN industry_taxonomy t ON e.industry_id = t.industry_id
        ORDER BY e.signal_date ASC
    """)
    backtest_events = [dict(r) for r in cur.fetchall()]

    # 13. 固定研究報告中心 (每日/每週/每月/每季 - 階段四/六 & PART 6)
    cur.execute("SELECT * FROM research_reports ORDER BY report_id ASC")
    research_reports = []
    for r in cur.fetchall():
        d = dict(r)
        d["key_findings"] = json.loads(d["key_findings_json"])
        research_reports.append(d)

    # 14. 全市場上市櫃 Live OpenAPI 統計與前100大公司明細 (1,989家真實公司)
    cur.execute("""
        SELECT COUNT(*) AS total_companies,
               SUM(CASE WHEN market_type='TWSE' THEN 1 ELSE 0 END) AS twse_count,
               SUM(CASE WHEN market_type='TPEx' THEN 1 ELSE 0 END) AS tpex_count,
               ROUND(SUM(rev_current_thousand)/1e9, 4) AS total_rev_trillion,
               ROUND(SUM(rev_last_year_thousand)/1e9, 4) AS ly_rev_trillion
        FROM live_company_fundamentals
    """)
    live_summary = dict(cur.fetchone())
    if live_summary.get("total_rev_trillion") and live_summary.get("ly_rev_trillion"):
        live_summary["total_yoy_pct"] = round((live_summary["total_rev_trillion"] / live_summary["ly_rev_trillion"] - 1) * 100, 2)
    else:
        live_summary["total_yoy_pct"] = 0.0

    # 各產業由 1,989 家上市櫃公司真實匯總之統計
    cur.execute("""
        SELECT mapped_industry_id,
               COUNT(*) AS company_count,
               ROUND(SUM(rev_current_thousand)/1e5, 2) AS ind_rev_billion,
               ROUND(SUM(rev_last_year_thousand)/1e5, 2) AS ind_ly_rev_billion,
               ROUND((SUM(rev_current_thousand)/NULLIF(SUM(rev_last_year_thousand),0) - 1)*100, 2) AS agg_yoy_pct,
               ROUND(AVG(pe_ratio), 2) AS avg_pe,
               ROUND(AVG(pb_ratio), 2) AS avg_pb,
               SUM(foreign_net_shares) AS sum_foreign_shares,
               SUM(itc_net_shares) AS sum_itc_shares
        FROM live_company_fundamentals
        GROUP BY mapped_industry_id
    """)
    live_industry_agg = {r["mapped_industry_id"]: dict(r) for r in cur.fetchall()}
    for ind in industries:
        ind["live_agg"] = live_industry_agg.get(ind["industry_id"], {})

    cur.execute("""
        SELECT company_code, company_name, market_type, official_industry, mapped_industry_id,
               data_ym, report_date, ROUND(rev_current_thousand/1e5, 2) AS rev_billion,
               ROUND(rev_mom_pct, 2) AS rev_mom_pct, ROUND(rev_yoy_pct, 2) AS rev_yoy_pct,
               ROUND(cum_rev_yoy_pct, 2) AS cum_rev_yoy_pct,
               pe_ratio, pb_ratio, dividend_yield,
               foreign_net_shares, itc_net_shares, dealer_net_shares, total_3insti_net_shares,
               insti_trade_date
        FROM live_company_fundamentals
        ORDER BY rev_current_thousand DESC
        LIMIT 120
    """)
    live_top_companies = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM live_market_indices ORDER BY close_index DESC LIMIT 60")
    live_indices = [dict(r) for r in cur.fetchall()]

    # 15. ETF 投資決策中心全套資料 (台灣 ETF + 美國 ETF 雙軌獨立評分、持股穿透、配息拆解、雙軌回測與7問報告)
    etf_center = {}
    try:
        cur.execute("""
            SELECT m.*, d.trade_date, d.close_price, d.change_pct, d.nav_price, d.premium_discount_pct,
                   d.volume_shares, d.turnover_value, d.bid_price, d.ask_price, d.bid_ask_spread_bps,
                   d.primary_net_flow_value, d.foreign_net_shares, d.itc_net_shares, d.dealer_net_shares,
                   d.regular_saving_accounts, d.weighted_pe, d.weighted_pb, d.weighted_rev_yoy_pct,
                   d.weighted_roe_pct, d.dividend_yield_pct, d.bond_ytm_pct, d.bond_duration_years,
                   d.bond_avg_credit_rating, d.bond_credit_spread_bps, d.roll_yield_cost_note,
                   d.return_1y_total_pct, d.return_3y_ann_pct, d.return_5y_ann_pct,
                   d.return_price_only_1y_pct, d.twd_adjusted_1y_return_pct,
                   d.annualized_volatility_pct, d.max_drawdown_pct, d.beta_vs_market,
                   d.corr_tw_stock, d.corr_us_stock, d.corr_us_bond, d.missing_fields_note,
                   a.top10_concentration_pct, a.max_single_weight_pct, a.max_single_holding_name,
                   a.sector_weights_json, a.country_weights_json, a.holdings_coverage_note,
                   s.eval_methodology_type,
                   s.score_a_underlying_quality, s.score_a_diversification_role, s.score_a_long_valuation_rr,
                   s.score_a_cost_liquidity_track, s.score_a_complementarity, s.total_score_a_long_term, s.conclusion_a_long_term,
                   s.score_b_macro_environment, s.score_b_flow_and_breadth, s.score_b_trend_and_momentum,
                   s.score_b_valuation_and_pos, s.score_b_vol_event_downside, s.total_score_b_short_mid, s.conclusion_b_short_mid,
                   s.divergence_tag, s.top_advantage, s.top_risk, s.supporting_evidence, s.counter_evidence,
                   s.contradiction_notes, s.invalidation_conditions, s.next_watch_indicator,
                   s.credibility_grade, s.missing_data_pct
            FROM etf_master m
            LEFT JOIN etf_daily_metrics d ON m.etf_code = d.etf_code
            LEFT JOIN etf_allocation_summary a ON m.etf_code = a.etf_code
            LEFT JOIN etf_dual_scores s ON m.etf_code = s.etf_code
            ORDER BY m.is_leveraged_or_inverse ASC, s.total_score_a_long_term DESC
        """)
        etf_list = []
        for r in cur.fetchall():
            item = dict(r)
            item["sector_weights"] = json.loads(item["sector_weights_json"]) if item.get("sector_weights_json") else {}
            item["country_weights"] = json.loads(item["country_weights_json"]) if item.get("country_weights_json") else {}
            etf_list.append(item)

        cur.execute("""
            SELECT h.*, l.rev_yoy_pct AS live_rev_yoy, l.pe_ratio AS live_pe, l.pb_ratio AS live_pb
            FROM etf_holdings h
            LEFT JOIN live_company_fundamentals l ON h.constituent_code = l.company_code
            ORDER BY h.etf_code, h.weight_pct DESC
        """)
        holdings_by_etf = {}
        for r in cur.fetchall():
            hd = dict(r)
            holdings_by_etf.setdefault(hd["etf_code"], []).append(hd)

        cur.execute("SELECT * FROM etf_dividend_breakdown")
        div_map = {r["etf_code"]: dict(r) for r in cur.fetchall()}

        for item in etf_list:
            ec = item["etf_code"]
            item["holdings"] = holdings_by_etf.get(ec, [])
            item["dividend_breakdown"] = div_map.get(ec)

        cur.execute("SELECT * FROM etf_backtest_runs ORDER BY bt_id ASC")
        etf_bts = []
        for r in cur.fetchall():
            bd = dict(r)
            bd["key_metrics"] = json.loads(bd["key_metrics_json"])
            etf_bts.append(bd)

        cur.execute("SELECT * FROM etf_research_reports ORDER BY etf_report_id ASC")
        etf_rpts = [dict(r) for r in cur.fetchall()]

        etf_center = {
            "etfs": etf_list,
            "backtests": etf_bts,
            "reports": etf_rpts
        }
    except Exception as e:
        logger.exception("ETF 決策中心資料讀取失敗")
        etf_center = {"error": str(e), "etfs": [], "backtests": [], "reports": []}

    provenance = _data_provenance(cur)
    conn.close()
    return {
        "generated_at": now_tw().strftime("%Y-%m-%d %H:%M:%S (UTC+8)"),
        "data_provenance": provenance,
        "active_model": active_model,
        "macro_latest": list(macro_latest.values()),
        "macro_series": macro_series,
        "asset_flows": asset_flows,
        "industries": industries,
        "warnings": warnings,
        "companies": companies,
        "scenarios": scenarios,
        "sources": sources,
        "dictionary": dictionary,
        "model_versions": model_versions,
        "audit_logs": audit_logs,
        "institutional_flows": institutional_flows,
        "dq_checks": dq_checks,
        "backtest_runs": backtest_runs,
        "backtest_events": backtest_events,
        "research_reports": research_reports,
        "live_summary": live_summary,
        "live_top_companies": live_top_companies,
        "live_indices": live_indices,
        "etf_center": etf_center,
    }

def _next_model_version(cur):
    """以既有最大序號 +1 產生版本號 (不用 COUNT，避免刪除或並行時重號)。"""
    cur.execute("SELECT version_id FROM model_governance_configs")
    seqs = []
    for (vid,) in cur.fetchall():
        m = re.match(r"v1\.(\d+)\.0", vid or "")
        if m:
            seqs.append(int(m.group(1)))
    return f"v1.{max(seqs, default=0) + 1}.0 ({now_tw().strftime('%m%d-%H%M%S')})"


def update_weights_and_rescore(payload):
    """動態調整產業評分權重，保存新版本並重算所有可評分產業之總分 (PART 4 & PART 9)"""
    weights_dict = parse_weights(payload)
    w_cap = weights_dict["capital_flow"]
    w_fun = weights_dict["fundamentals"]
    w_gro = weights_dict["future_growth"]
    w_ins = weights_dict["institutional"]
    w_val = weights_dict["valuation"]

    reason = str(payload.get("reason") or "").strip()[:500] or "使用者自訂權重調整"
    now_str = now_iso()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")  # 先取得寫入鎖再產生版本號，避免兩個請求拿到同一個號碼

    new_version = _next_model_version(cur)

    cur.execute("SELECT * FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
    prev_cfg = dict(cur.fetchone())
    old_version = prev_cfg["version_id"]

    cur.execute("UPDATE model_governance_configs SET active = 0")
    cur.execute("""
        INSERT INTO model_governance_configs
        (version_id, created_at, weights_json, thresholds_json, change_reason, active)
        VALUES (?, ?, ?, ?, ?, 1)
    """, (new_version, now_str, json.dumps(weights_dict, ensure_ascii=False), prev_cfg["thresholds_json"], reason))

    # 複製並以新權重重算產業分數
    cur.execute("SELECT * FROM industry_rotation_scores WHERE model_version = ?", (old_version,))
    old_rows = [dict(r) for r in cur.fetchall()]
    for r in old_rows:
        new_total = compute_weighted_total(r, weights_dict)

        cur.execute("""
            INSERT INTO industry_rotation_scores
            (industry_id, as_of_date, period_covered, model_version,
             rel_strength_20d, rel_strength_60d, foreign_net_flow_trend, itc_net_flow_trend,
             dealer_net_flow_trend, etf_flow_impact, rev_yoy_pct, rev_mom_pct, margin_trend,
             capex_inventory_status, rotation_state, transition_tag,
             score_capital_flow, score_fundamentals, score_future_growth, score_institutional,
             score_valuation, total_weighted_score, short_term_momentum_score,
             mid_term_fundamental_score, long_term_structural_score, confidence_level,
             missing_data_pct, supporting_evidence, counter_evidence, invalidation_conditions, data_limitations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["industry_id"], r["as_of_date"], r["period_covered"], new_version,
            r["rel_strength_20d"], r["rel_strength_60d"], r["foreign_net_flow_trend"], r["itc_net_flow_trend"],
            r["dealer_net_flow_trend"], r["etf_flow_impact"], r["rev_yoy_pct"], r["rev_mom_pct"], r["margin_trend"],
            r["capex_inventory_status"], r["rotation_state"], r["transition_tag"],
            r["score_capital_flow"], r["score_fundamentals"], r["score_future_growth"], r["score_institutional"],
            r["score_valuation"], new_total, r["short_term_momentum_score"],
            r["mid_term_fundamental_score"], r["long_term_structural_score"], r["confidence_level"],
            r["missing_data_pct"], r["supporting_evidence"], r["counter_evidence"],
            r["invalidation_conditions"], r["data_limitations"]
        ))

    cur.execute("""
        INSERT INTO ingestion_audit_logs
        (run_timestamp, task_name, source_id, status, records_affected, message)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        now_str, "MODEL_WEIGHT_RESCORE", "SRC_MOPS", "SUCCESS", len(old_rows),
        f"模型權重已更新為版本 {new_version} (資金{int(w_cap*100)}%/基本面{int(w_fun*100)}%/成長{int(w_gro*100)}%/法人{int(w_ins*100)}%/估值{int(w_val*100)}%)，理由：{reason}"
    ))

    # 只保留最近 KEEP_SCORE_VERSIONS 個版本 (含目前啟用版本) 的產業分數列
    cur.execute("""
        DELETE FROM industry_rotation_scores
        WHERE model_version != ?
          AND model_version NOT IN (
              SELECT version_id FROM model_governance_configs ORDER BY created_at DESC LIMIT ?
          )
    """, (new_version, KEEP_SCORE_VERSIONS))

    conn.commit()
    conn.close()
    invalidate_dashboard_cache()
    return new_version

def update_governance_settings(payload):
    """動態調整預警門檻 (LEVEL 2/3/4/R) 與產業分類歸屬 (補充執行指令第9點)"""
    try:
        return _update_governance_settings(payload)
    finally:
        invalidate_dashboard_cache()


def _update_governance_settings(payload):
    now_str = now_iso()
    conn = get_connection()
    cur = conn.cursor()

    action_type = payload.get("action_type", "THRESHOLDS")
    if action_type == "THRESHOLDS":
        try:
            th = validate_thresholds({k: float(payload.get(k, v)) for k, v in DEFAULT_THRESHOLDS.items()})
        except (TypeError, ValueError) as e:
            conn.close()
            raise ValueError(f"門檻設定無效：{e}")
        lvl4_min, lvl3_min, lvl2_min, lvlR_cap_max = th["lvl4_min"], th["lvl3_min"], th["lvl2_min"], th["lvlR_cap_max"]
        reason = str(payload.get("reason") or "").strip()[:500] or "使用者自訂預警門檻"

        cur.execute("SELECT * FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
        active_cfg = dict(cur.fetchone())
        new_th = {
            "LEVEL 4": f"總分 >= {lvl4_min} 且 資金流向 >= 75 且 基本面 >= 80",
            "LEVEL 3": f"總分 >= {lvl3_min} 且 資金與基本面同時轉強",
            "LEVEL 2": f"總分 >= {lvl2_min} 或 基本面改善但市場尚未反映",
            "LEVEL R": f"資金流向分數 < {lvlR_cap_max} 或 基本面惡化風險",
            "numeric": {"lvl4_min": lvl4_min, "lvl3_min": lvl3_min, "lvl2_min": lvl2_min, "lvlR_cap_max": lvlR_cap_max}
        }
        cur.execute("""
            UPDATE model_governance_configs
            SET thresholds_json = ?, change_reason = ?
            WHERE version_id = ?
        """, (json.dumps(new_th, ensure_ascii=False), f"{active_cfg['change_reason']} | 門檻更新: {reason}", active_cfg["version_id"]))

        # 根據新門檻動態重算各產業在 trend_early_warnings 的預警等級
        cur.execute("""
            SELECT industry_id, total_weighted_score, score_capital_flow, score_fundamentals
            FROM industry_rotation_scores WHERE model_version = ?
        """, (active_cfg["version_id"],))
        for r in cur.fetchall():
            new_lvl = classify_alert_level(r["total_weighted_score"], r["score_capital_flow"], th)
            if new_lvl is None:
                continue
            cur.execute("UPDATE trend_early_warnings SET alert_level = ? WHERE industry_id = ?", (new_lvl, r["industry_id"]))

        cur.execute("""
            INSERT INTO ingestion_audit_logs
            (run_timestamp, task_name, source_id, status, records_affected, message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now_str, "THRESHOLD_GOVERNANCE_UPDATE", "SRC_TWSE", "SUCCESS", 7, f"預警門檻已更新 (L4>={lvl4_min}, L3>={lvl3_min}, L2>={lvl2_min}, LR<{lvlR_cap_max})：{reason}"))
        conn.commit()
        conn.close()
        return {"updated": "THRESHOLDS", "thresholds": new_th}

    elif action_type == "COMPANY_MAPPING":
        code = str(payload.get("company_code", "")).strip()
        new_ind_id = str(payload.get("mapped_industry_id", "")).strip()
        cur.execute("SELECT 1 FROM industry_taxonomy WHERE industry_id = ?", (new_ind_id,))
        if not cur.fetchone():
            conn.close()
            raise ValueError(f"未知的產業代碼：{new_ind_id}")
        cur.execute("SELECT 1 FROM live_company_fundamentals WHERE company_code = ?", (code,))
        if not cur.fetchone():
            conn.close()
            raise ValueError(f"找不到公司代號：{code}")
        cur.execute("UPDATE live_company_fundamentals SET mapped_industry_id = ? WHERE company_code = ?", (new_ind_id, code))
        cur.execute("UPDATE company_research_watchlist SET industry_id = ? WHERE ticker = ?", (new_ind_id, code))
        cur.execute("""
            INSERT INTO ingestion_audit_logs
            (run_timestamp, task_name, source_id, status, records_affected, message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now_str, "INDUSTRY_TAXONOMY_REMAP", "SRC_MOPS", "SUCCESS", 1, f"已調整公司代號 {code} 之產業分類歸屬至 {new_ind_id}"))
        conn.commit()
        conn.close()
        return {"updated": "COMPANY_MAPPING", "company_code": code, "mapped_industry_id": new_ind_id}

    conn.close()
    return {"updated": "NONE"}

def probe_live_sources():
    """測試真實官方 API 連線狀態，若處於無外網沙盒則觸發資料中斷保護機制並誠實記錄 (PART 9 & 附錄A)"""
    endpoints = [
        ("SRC_TWSE", "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"),
        ("SRC_TPEX", "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"),
        ("SRC_CBC", "https://www.cbc.gov.tw/tw/lp-640-1.html")
    ]
    now_str = now_iso()
    results = []
    conn = get_connection()
    cur = conn.cursor()

    for src_id, url in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TWFin-Intelligence-Research/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                code = resp.status
                status = "SUCCESS"
                msg = f"成功連線官方端點 {url} (HTTP {code})"
        except Exception as e:
            status = "FALLBACK_USED"
            msg = (f"外部端點連線失敗 ({type(e).__name__})：本次未取得新資料，畫面沿用資料庫中上一次成功擷取的內容"
                   f"（其中標示為「種子」的區塊本來就是內建參考資料）")

        cur.execute("""
            INSERT INTO ingestion_audit_logs
            (run_timestamp, task_name, source_id, status, records_affected, message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now_str, "LIVE_CONNECTOR_CHECK", src_id, status, 0, msg))
        results.append({"source_id": src_id, "url": url, "status": status, "message": msg})

    conn.commit()
    conn.close()
    invalidate_dashboard_cache()
    return results

class TWFinRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard":
            self._send_json(get_dashboard_payload())
        elif parsed.path == "/api/health":
            self._send_json({"status": "ok", "system": "Taiwan Capital Flow Intelligence & Industry Rotation System v1.0"})
        else:
            super().do_GET()

    def _authorize_write(self):
        """寫入端點授權：有設定 TWFIN_ADMIN_TOKEN 時比對 X-Admin-Token；否則只允許本機。"""
        if ADMIN_TOKEN:
            provided = self.headers.get("X-Admin-Token", "")
            if not hmac.compare_digest(provided.encode("utf-8"), ADMIN_TOKEN.encode("utf-8")):
                raise AuthError("需要有效的管理權杖 (X-Admin-Token)", 401)
            return
        if self.client_address[0] not in LOCAL_ADDRESSES:
            raise AuthError("伺服器未設定 TWFIN_ADMIN_TOKEN，寫入操作僅允許從本機執行", 403)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise ValueError("Content-Length 無效")
        if length > MAX_BODY_BYTES:
            raise ValueError("請求內容過大")
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            raise ValueError("請求內容不是有效的 JSON")
        if not isinstance(payload, dict):
            raise ValueError("請求內容必須是 JSON 物件")
        return payload

    def do_POST(self):
        path = urlparse(self.path).path
        handler = POST_ROUTES.get(path)
        if handler is None:
            self._send_json({"status": "error", "message": "Unknown endpoint"}, status=404)
            return
        try:
            self._authorize_write()
            payload = self._read_json_body()
            self._send_json(handler(payload))
        except AuthError as e:
            self._send_json({"status": "error", "message": str(e)}, status=e.status)
        except (ValueError, KeyError, PermissionError) as e:
            self._send_json({"status": "error", "message": str(e)}, status=400)
        except Exception:
            logger.exception("POST %s 發生未預期錯誤", path)
            self._send_json({"status": "error", "message": "伺服器內部錯誤，請查看伺服器日誌"}, status=500)


def _handle_rescore(payload):
    new_ver = update_weights_and_rescore(payload)
    return {"status": "ok", "new_version": new_ver, "dashboard": get_dashboard_payload()}


def _handle_update_governance(payload):
    res = update_governance_settings(payload)
    return {"status": "ok", "result": res, "dashboard": get_dashboard_payload()}


def _handle_probe_sources(payload):
    live_res = run_live_ingestion()
    shared_map = live_res.pop("shared_insti_map", None) if isinstance(live_res, dict) else None
    build_and_compute_etf_center(shared_insti_map=shared_map)
    res = probe_live_sources()
    return {"status": "ok", "probe_results": res, "live_ingestion": live_res, "dashboard": get_dashboard_payload()}


def _handle_proposal_decision(payload):
    pid = str(payload.get("proposal_id", "")).strip()
    decision = str(payload.get("decision", "APPROVE")).strip()
    note = str(payload.get("note", "")).strip()[:500]
    if pid == "ALL":
        st = get_multi_agent_state()
        for p in st.get("phase6_proposals", []):
            update_proposal_approval_status(p["proposal_id"], decision, note)
        res_obj = {"batch": "ALL", "decision": decision}
    else:
        res_obj = update_proposal_approval_status(pid, decision, note)
    return {"status": "ok", "proposal": res_obj, "multi_agent_center": get_multi_agent_state()}


def _handle_run_session(payload):
    topic = str(payload.get("topic") or "台美 ETF 雙軌評分模型、跨時區數據品質、跨國持股穿透重疊與系統架構全面體檢").strip()[:200]
    mode = str(payload.get("trigger_mode", "MANUAL_START")).strip()[:50]
    bundle = run_full_multi_agent_session(topic=topic, trigger_mode=mode)
    return {"status": "ok", "multi_agent_center": bundle}


POST_ROUTES = {
    "/api/rescore": _handle_rescore,
    "/api/update_governance": _handle_update_governance,
    "/api/probe_sources": _handle_probe_sources,
    "/api/multi_agent/proposal_decision": _handle_proposal_decision,
    "/api/multi_agent/run_session": _handle_run_session,
}


def run_server(port=None):
    if port is None:
        port = int(os.environ.get("PORT", 8765))
    host = os.environ.get("HOST", "0.0.0.0")
    if not os.path.exists(os.path.join(os.path.dirname(FRONTEND_DIR), "data", "twfin_intelligence.db")):
        seed_and_compute_all()
        build_and_compute_etf_center()
    server = ThreadingHTTPServer((host, port), TWFinRequestHandler)
    print(f"TWFin Intelligence Server running at http://127.0.0.1:{port} (bound to {host}:{port})")
    if ADMIN_TOKEN:
        print("寫入型 API 已啟用管理權杖保護 (TWFIN_ADMIN_TOKEN)")
    else:
        print("未設定 TWFIN_ADMIN_TOKEN：寫入型 API 僅接受本機 127.0.0.1 的請求")
    server.serve_forever()

if __name__ == "__main__":
    run_server()
