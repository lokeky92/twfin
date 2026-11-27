"""
Argon 多代理研究團隊 — 即時稽核版 (取代 2026-11-22 手寫的固定研究記錄)。

原本的 run_full_multi_agent_session() 是 ~750 行預先寫好的報告 (固定 SESSION-20261122-001)，內容主要是 11/22 當時對 ETF 模組的
程式缺陷審查，其中大多數缺陷後來都已修正 (分數寫死、日期寫死、上櫃 ETF 沒接、重複請求…)，報告已過時甚至不正確。

這裡改成每次排程由六位 Agent 以「規則」檢查目前真實的系統狀態 (唯讀資料庫)，每個發現都附數字證據：
  Agent 01 長期配置   ETF 模型 A 的覆蓋、集中度、分數區辨力
  Agent 02 市場時機   大盤狀態、價量與資金背離、模型 B 的結構性限制
  Agent 03 數據品質   七項法定稽核 (新鮮度、完整度、彙總一致性、缺漏誠實標示、手寫比例、重複)
  Agent 04 風險管理   槓桿型占成交值比重、高相關重複配置、持股重疊、流動性
  Agent 05 反方審查   回測是否成熟、百分位評分的人為效應、一次性營收、手寫內容仍在畫面上
  Agent 06 系統工程   同步健康度、回補進度、資料庫大小、程式規模
流程 Phase 2 獨立研究 → Phase 3 交叉審查 (每人審下一位，檢查樣本數與證據是否足夠) → Phase 4 回應 (被質疑者降低嚴重度或維持)
→ Phase 5 總指揮整合 → Phase 6 由發現產生改善提案 (需人工批准，不會自動修改任何程式)。

誠實的限制：這是「規則式稽核」，不是語言模型在思考：能偵測的只有規則寫得出來的問題，每條規則與門檻都在本檔案頂端；
沒有被規則涵蓋的問題 (例如商業判斷、程式邏輯錯誤) 不會被發現。
"""
import copy
import glob
import html
import json
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from argon_multi_agent.engine import multi_agent_orchestrator as mao
except ImportError:      # 直接以 engine 目錄執行時
    import multi_agent_orchestrator as mao  # type: ignore

TW_TZ = timezone(timedelta(hours=8))
KEEP_SESSIONS = 5

# ---- 規則門檻 -------------------------------------------------------------------------------
CONC_MAX_SINGLE = 40.0           # 單一持股占比 (%) 達此值視為高度集中
LEVERAGED_TURNOVER_SHARE = 25.0  # 槓桿型占台股 ETF 成交值 (%) 達此值視為風險
CORR_REDUNDANT = 0.97            # 與 0050 日報酬相關係數達此值視為重複配置
OVERLAP_PAIR = 50.0              # 前十大持股重疊度 (%) 達此值視為高度重疊
SPREAD_WIDE_BPS = 15.0           # 買賣價差達此值視為流動性偏弱
BACKTEST_MIN_DAYS = 20           # 前瞻回測至少要累積這麼多快照日才有統計意義
LEVEL_R_SHARE = 30.0             # 預警 LEVEL R 的產業占比 (%) 達此值，懷疑是百分位評分的人為效應
ONE_OFF_GAP_PP = 40.0            # 單月與累計營收年增相差 (百分點)
COVERAGE_LOW = 0.6               # 產業彙總法人金額相對官方的覆蓋率低於此值視為偏低
MIN_SAMPLE = 3                   # 交叉審查：樣本數低於此值視為證據偏少
SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2, "INFO": 3}
AGENTS = [
    ("AGENT_01", "Agent 01：長期配置研究員", "Long-Term Allocation & Fund Quality Auditor"),
    ("AGENT_02", "Agent 02：短中期市場時機研究員", "Short/Mid-Term Market Timing & Flow Auditor"),
    ("AGENT_03", "Agent 03：數據品質研究員", "Data Quality, Freshness & Cross-Source Consistency Auditor"),
    ("AGENT_04", "Agent 04：風險管理研究員", "Portfolio Risk, Redundancy & Liquidity Auditor"),
    ("AGENT_05", "Agent 05：反方審查研究員", "Devil's Advocate & Assumption Challenger"),
    ("AGENT_06", "Agent 06：系統架構與測試工程師", "Pipeline Health & System Engineering Auditor"),
]
AGENT_NAME = {a: n for a, n, _ in AGENTS}


def _e(x):
    return html.escape(str(x), quote=False)


def _pct(x, nd=1):
    return "N/A" if x is None else f"{x:+.{nd}f}%"


def _lst(items, n=6):
    items = list(items)
    return "、".join(str(i) for i in items[:n]) + (f" 等 {len(items)} 檔" if len(items) > n else "")


# ---------------------------------------------------------------------------
# 證據蒐集 (唯讀)
# ---------------------------------------------------------------------------
def gather_evidence(conn, backend_dir=None, db_path=None):
    cur = conn.cursor()
    q = lambda sql, *a: [dict(r) for r in cur.execute(sql, a)]   # noqa: E731
    ev = {"now": datetime.now(TW_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")}

    ev["sources"] = q("SELECT source_key, status, data_date, record_count, message FROM data_source_status")
    live_metrics = {}
    try:
        live_metrics = {r["etf_code"]: json.loads(r["metrics_json"]) for r in cur.execute("SELECT * FROM etf_live_metrics")}
    except Exception:  # noqa: BLE001
        pass
    ev["etfs"] = []
    for r in q("""
        SELECT m.etf_code code, m.etf_name name, m.listing_market market, m.asset_class, m.is_leveraged_or_inverse lev,
               m.total_expense_ratio_pct ter, d.bid_ask_spread_bps spread, d.turnover_value turn, d.trade_date,
               a.top10_concentration_pct top10, a.max_single_weight_pct maxs,
               s.total_score_a_long_term A, s.total_score_b_short_mid B, s.conclusion_a_long_term ca, s.conclusion_b_short_mid cb,
               s.missing_data_pct miss, s.credibility_grade cred, s.score_source,
               d.nav_price nav, d.premium_discount_pct prem, d.metrics_source msrc
        FROM etf_master m LEFT JOIN etf_daily_metrics d ON d.etf_code = m.etf_code
        LEFT JOIN etf_allocation_summary a ON a.etf_code = m.etf_code
        LEFT JOIN etf_dual_scores s ON s.etf_code = m.etf_code"""):
        r["live"] = live_metrics.get(r["code"])
        ev["etfs"].append(r)
    hold = {}
    for r in q("SELECT etf_code, constituent_code, weight_pct FROM etf_holdings"):
        hold.setdefault(r["etf_code"], {})[r["constituent_code"]] = r["weight_pct"]
    ev["holdings"] = hold

    idx = [r["close_index"] for r in q("SELECT close_index FROM index_price_history WHERE index_name = '發行量加權股價指數' ORDER BY trade_date")]
    ev["taiex"] = None
    if len(idx) >= 60:
        ma60 = sum(idx[-60:]) / 60
        r20 = [idx[i] / idx[i - 1] - 1 for i in range(len(idx) - 20, len(idx))]
        mean = sum(r20) / len(r20)
        vol = (sum((x - mean) ** 2 for x in r20) / len(r20)) ** 0.5 * (252 ** 0.5) * 100
        ev["taiex"] = {"close": idx[-1], "ma60": ma60, "vs_ma60": (idx[-1] / ma60 - 1) * 100, "vol20": vol}

    version = (q("SELECT version_id FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1") or [{}])[0].get("version_id")
    last_day = (q("SELECT MAX(trade_date) d FROM live_industry_daily") or [{}])[0].get("d")
    inds = q("""SELECT r.industry_id id, t.industry_name name, r.total_weighted_score score, r.rotation_state state, r.score_source,
                       r.rev_yoy_pct yoy, w.alert_level level
                FROM industry_rotation_scores r JOIN industry_taxonomy t ON t.industry_id = r.industry_id
                LEFT JOIN trend_early_warnings w ON w.industry_id = r.industry_id WHERE r.model_version = ?""", version)
    daily = {r["industry_id"]: r for r in q("SELECT * FROM live_industry_daily WHERE trade_date = ?", last_day)} if last_day else {}
    for i in inds:
        d = daily.get(i["id"]) or {}
        i["inst"] = None if not d else (d.get("foreign_billion") or 0) + (d.get("itc_billion") or 0)
    ev["industries"] = inds
    ev["last_industry_day"] = last_day
    ev["snapshot_days"] = (q("SELECT COUNT(DISTINCT snapshot_date) n FROM industry_score_history WHERE score_source = 'live'") or [{"n": 0}])[0]["n"]

    def count(sql):
        try:
            return {r["k"]: r["n"] for r in q(sql)}
        except Exception:  # noqa: BLE001
            return {}
    ev["inventory"] = {
        "趨勢預警": count("SELECT text_source k, COUNT(*) n FROM trend_early_warnings GROUP BY 1"),
        "個股研究名單": count("SELECT text_source k, COUNT(*) n FROM company_research_watchlist GROUP BY 1"),
        "固定研究報告": count("SELECT text_source k, COUNT(*) n FROM research_reports GROUP BY 1"),
        "ETF 雙軌評分": count("SELECT score_source k, COUNT(*) n FROM etf_dual_scores GROUP BY 1"),
        "ETF 研究報告": count("SELECT text_source k, COUNT(*) n FROM etf_research_reports GROUP BY 1"),
        "產業評分": count("SELECT score_source k, COUNT(*) n FROM industry_rotation_scores WHERE model_version = '%s' GROUP BY 1" % str(version).replace("'", "")),
    }
    flows = q("SELECT * FROM institutional_flows WHERE period_label LIKE '%官方API%' ORDER BY release_date DESC LIMIT 1")
    ev["official_flow"] = flows[0] if flows else None
    ev["dups"] = {
        "etf_daily_metrics": [r["etf_code"] for r in q("SELECT etf_code FROM etf_daily_metrics GROUP BY 1 HAVING COUNT(*) > 1")],
        "trend_early_warnings": [r["industry_id"] for r in q("SELECT industry_id FROM trend_early_warnings GROUP BY 1 HAVING COUNT(*) > 1")],
        "industry_rotation_scores": [r["industry_id"] for r in q("SELECT industry_id FROM industry_rotation_scores WHERE model_version = ? GROUP BY 1 HAVING COUNT(*) > 1", version)],
    }
    ev["audit_failures"] = q("SELECT task_name, status, message FROM ingestion_audit_logs WHERE status NOT IN ('SUCCESS') ORDER BY log_id DESC LIMIT 8")
    ev["backfill_missing"] = None
    try:
        sys.path.insert(0, backend_dir or os.path.join(mao.BASE_DIR, "backend"))
        import etf_live_data as ed
        from datetime import date
        done = {(r["etf_code"], r["ym"]): r["fetched_at"] for r in q("SELECT etf_code, ym, fetched_at FROM etf_history_fetch")}
        codes = [r["etf_code"] for r in q("SELECT etf_code FROM etf_master WHERE listing_market != 'US'")]
        ev["backfill_missing"] = sum(1 for c in codes for ym in ed.month_list(date.today())
                                     if (c, ym) not in done or not ed._month_complete(done[(c, ym)], ym) and ym != ed.month_list(date.today())[0])
    except Exception:  # noqa: BLE001
        pass
    p = db_path or mao.DB_PATH
    ev["db_mb"] = round(os.path.getsize(p) / 1e6, 2) if os.path.exists(p) else None
    bd = backend_dir or os.path.join(mao.BASE_DIR, "backend")
    ev["loc"] = {}
    for f in sorted(glob.glob(os.path.join(bd, "*.py"))):
        with open(f, encoding="utf-8") as fh:
            ev["loc"][os.path.basename(f)] = sum(1 for _ in fh)
    return ev


# ---------------------------------------------------------------------------
# 發現 (純函式)
# ---------------------------------------------------------------------------
def F(key, agent, sev, title, detail, evidence, topic, n=None, insufficient=False, proposal=None, gap=False):
    """insufficient=True：結論依賴不完整的資料，交叉審查會質疑並降級；gap=True：事實本身確定，但代表系統有證據缺口 (只列入整合報告的缺口清單，不降級)。"""
    return {"key": key, "agent": agent, "severity": sev, "title": title, "detail": detail, "evidence": evidence, "topic": topic,
            "n": n, "insufficient": insufficient, "gap": gap, "proposal": proposal}


def findings_01(ev):
    out, tw = [], [e for e in ev["etfs"] if e["market"] == "TW"]
    us = [e for e in ev["etfs"] if e["market"] == "US"]
    seed_us = [e for e in us if e["score_source"] != "live"]
    if seed_us:
        out.append(F("US_ETF_SEED_SCORES", "AGENT_01", "P1", "美股 ETF 的評分仍是手寫種子值",
                     f"{len(seed_us)}/{len(ev['etfs'])} 檔 ETF (全部美股) 的長短期分數與敘述沒有官方即時依據，不會隨資料更新。",
                     f"手寫評分：{_lst(e['code'] for e in seed_us)}", "seed_scores", n=len(seed_us),
                     proposal={"change": "評估可合法使用的美股行情來源 (需確認授權與穩定性)，接入後套用與台股相同的公式評分；在此之前維持「手寫評分」標籤。",
                               "modules": ["backend/etf_engine.py", "backend/etf_live.py"], "effect": "讓美股 ETF 與台股 ETF 使用同一套可驗證的公式。",
                               "side": "需處理匯率、時區與授權；第三方來源可能中斷。", "difficulty": "高"}))
    conc = [e for e in tw if (e["maxs"] or 0) >= CONC_MAX_SINGLE]
    if conc:
        out.append(F("TW_CONCENTRATION", "AGENT_01", "INFO", "部分台股 ETF 單一持股高度集中",
                     "集中度是商品本身的結構特性，評分已用「分散度」子分數與「需注意集中風險」結論反映；持股權重為人工維護 (非即時)。",
                     "；".join(f"{e['code']} 最大單一持股 {e['maxs']:.1f}%" for e in conc), "concentration", n=len(conc)))
    lack = [e for e in tw if e["miss"] is not None and e["miss"] >= 20]
    if lack:
        out.append(F("A_MISSING_INPUTS", "AGENT_01", "P2", "部分台股 ETF 有 20% 以上的子分數缺資料 (以 50 分中性值代入)",
                     "債券、黃金等沒有持股或本益比的 ETF，底層品質與分散度無法計算；其長期配置總分的可比性較低。",
                     "；".join(f"{e['code']} 缺 {e['miss']:.0f}%" for e in lack), "missing_inputs", n=len(lack)))
    a_scores = [e["A"] for e in tw if e["A"] is not None and not e["lev"]]
    if len(a_scores) >= 5:
        spread = max(a_scores) - min(a_scores)
        if spread < 20:
            out.append(F("A_LOW_SPREAD", "AGENT_01", "P2", "長期配置分數區辨力偏低",
                         f"非槓桿台股 ETF 的模型 A 總分只分布在 {min(a_scores):.1f}～{max(a_scores):.1f} (相差 {spread:.1f} 分)，排名差異可能不顯著。",
                         f"樣本 {len(a_scores)} 檔", "score_spread", n=len(a_scores)))
    return out


def findings_02(ev):
    out, tw = [], [e for e in ev["etfs"] if e["market"] == "TW" and e["live"]]
    t = ev["taiex"]
    if t:
        out.append(F("MARKET_REGIME", "AGENT_02", "INFO", "大盤目前狀態",
                     f"加權指數 {t['close']:,.0f}，相對 60 日均線 {t['vs_ma60']:+.1f}%，近 20 日年化波動 {t['vol20']:.1f}%。",
                     "指數逐日歷史 (證交所 FMTQIK)", "regime"))
    div = []
    for e in tw:
        L = e["live"]
        r1m, ins = L.get("ret_1m"), L.get("insti_ratio_pct")
        if r1m is not None and ins is not None and ((r1m > 3 and ins < -1) or (r1m < -3 and ins > 1)):
            div.append(f"{e['code']} (近 1 月 {r1m:+.1f}%、法人 {ins:+.2f}%)")
    if div:
        out.append(F("FLOW_PRICE_DIVERGENCE", "AGENT_02", "P2", "價格與法人買賣方向相反的 ETF",
                     "單日法人買賣金額很容易受單一事件影響，單看一天不宜過度解讀；需要連續多日確認。",
                     "；".join(div), "divergence", n=len(div)))
    non_lev = [e for e in tw if not e["lev"] and e["cb"]]
    risky = [e for e in non_lev if e["cb"] == "風險偏高"]
    if len(non_lev) >= 5 and len(risky) / len(non_lev) >= 0.5:
        out.append(F("B_UNIFORMLY_WEAK", "AGENT_02", "P2", "多數台股 ETF 的短中期結論同為「風險偏高」",
                     "模型 B 的「大盤環境」子分數對所有股票型 ETF 相同，因此大盤轉弱時全體同向被拉低；這是公式的結構限制，"
                     "不代表每檔 ETF 個別都有風險。", f"{len(risky)}/{len(non_lev)} 檔 (非槓桿型)", "b_structure", n=len(non_lev),
                     proposal={"change": "把「大盤環境」子分數改為各 ETF 對大盤的敏感度 (Beta) 加權，而不是對全體套用同一個數值。",
                               "modules": ["backend/etf_live.py"], "effect": "讓防禦型 ETF (低 Beta) 與進攻型 ETF 在同一大盤環境下有不同的環境分數。",
                               "side": "Beta 需要足夠歷史，資料不足的 ETF 要回退到目前做法。", "difficulty": "低"}))
    return out


def checks_03(ev):
    """七項法定稽核 → [{check_no, name, status, detail}]。"""
    checks = []
    bad = [s for s in ev["sources"] if s["status"] != "OK"]
    checks.append((1, "資料來源新鮮度與健康度", "PASS" if not bad and ev["sources"] else ("WARNING" if ev["sources"] else "FAIL"),
                   f"{len(ev['sources'])} 個官方來源，異常 {len(bad)} 個" + (f"：{_lst(s['source_key'] + '=' + s['status'] for s in bad)}" if bad else "")))
    tw = [e for e in ev["etfs"] if e["market"] == "TW" and e["live"]]
    dates = {e["live"]["last_date"] for e in tw}
    days = sorted({e["live"]["history_days"] for e in tw})
    checks.append((2, "台股 ETF 行情新鮮度", "PASS" if len(dates) == 1 and tw else "WARNING",
                   f"{len(tw)} 檔的最新交易日：{_lst(sorted(dates))}" if tw else "沒有任何 ETF 即時行情"))
    pending = ev.get("backfill_missing")
    checks.append((3, "ETF 歷史資料完整度", "PASS" if pending == 0 and days else "WARNING",
                   (f"歷史交易日數 {days[0]}～{days[-1]} (新上市 ETF 天然較短)" if days else "無歷史")
                   + (f"；仍有 {pending} 個 (ETF, 月份) 尚未回補" if pending else ("" if pending == 0 else "；回補進度無法判斷"))))
    of, inds = ev["official_flow"], [i for i in ev["industries"] if i["inst"] is not None]
    if of and inds:
        official = (of["foreign_net_billion"] or 0) + (of["itc_net_billion"] or 0)
        ours = sum(i["inst"] for i in inds)
        ratio = abs(ours) / abs(official) if official else None
        ok = ratio is not None and ratio >= COVERAGE_LOW and (ours * official >= 0)
        checks.append((4, "官方統計 vs 產業彙總一致性", "PASS" if ok else "WARNING",
                       f"官方外資+投信 {official:+.1f} 億；各產業彙總 {ours:+.1f} 億 (只含有營收資料的個股，不含 ETF 與其他證券)，涵蓋約 {ratio * 100:.0f}%"
                       if ratio is not None else "官方合計為 0，無法比較"))
    else:
        checks.append((4, "官方統計 vs 產業彙總一致性", "WARNING", "缺少官方逐日資料或產業彙總，無法比較"))
    fabricated = [e["code"] for e in ev["etfs"] if e["market"] == "TW" and e.get("msrc") == "live" and (e.get("nav") is not None or e.get("prem") is not None)]
    checks.append((5, "缺漏值誠實標示 (不偽造)", "PASS" if not fabricated else "FAIL",
                   "即時評分的台股 ETF 淨值與折溢價皆為空 (沒有官方來源，顯示 N/A，非偽造值)" if not fabricated
                   else f"這些即時 ETF 仍帶有淨值或折溢價 (可能是由手寫值反推)：{_lst(fabricated)}"))
    seed = {k: v.get("seed", 0) for k, v in ev["inventory"].items() if v.get("seed")}
    checks.append((6, "手寫內容比例", "PASS" if not seed else "WARNING",
                   "沒有手寫的列" if not seed else "仍有手寫內容：" + "；".join(f"{k} {n} 列" for k, n in seed.items())))
    dup = {k: v for k, v in ev["dups"].items() if v}
    checks.append((7, "重複與唯一性", "PASS" if not dup else "FAIL",
                   "沒有重複列" if not dup else "；".join(f"{k}：{_lst(v)}" for k, v in dup.items())))
    return [{"check_no": a, "name": b, "status": c, "detail": d} for a, b, c, d in checks]


def findings_03(ev):
    out = []
    for c in checks_03(ev):
        if c["status"] == "PASS":
            continue
        sev = "P0" if c["status"] == "FAIL" else "P2"
        out.append(F(f"DQ_CHECK_{c['check_no']}", "AGENT_03", sev, f"數據品質檢查 {c['check_no']}：{c['name']}", c["detail"], c["detail"],
                     {1: "sources", 2: "etf_fresh", 3: "history", 4: "coverage", 5: "honesty", 6: "seed_inventory", 7: "duplicates"}[c["check_no"]],
                     n=None, insufficient=(c["check_no"] in (3, 4))))
    tw = [e for e in ev["etfs"] if e["market"] == "TW"]
    if tw:
        out.append(F("NAV_NO_SOURCE", "AGENT_03", "P1", "台股 ETF 缺少淨值與折溢價的官方來源",
                     "折溢價是 ETF 追價風險的核心指標，目前評分沒有納入；官方 OpenAPI 沒有 ETF 淨值。",
                     f"{len(tw)} 檔台股 ETF 的淨值與折溢價為空", "nav_missing", n=len(tw), gap=True,
                     proposal={"change": "評估各投信公開網站的每日淨值 (注意網頁結構穩定性與使用條款)，取得後在評分「估值與價位」加入折溢價。",
                               "modules": ["backend/etf_live_data.py", "backend/etf_live.py"], "effect": "把溢價追價風險納入短中期分數。",
                               "side": "網頁改版會讓抓取失效，需要健康度監控。", "difficulty": "中"}))
    return out


def findings_04(ev):
    out, tw = [], [e for e in ev["etfs"] if e["market"] == "TW"]
    tot = sum((e["live"] or {}).get("turnover_twd") or e["turn"] or 0 for e in tw)
    lev = sum((e["live"] or {}).get("turnover_twd") or e["turn"] or 0 for e in tw if e["lev"])
    if tot and lev / tot * 100 >= LEVERAGED_TURNOVER_SHARE:
        names = [e["code"] for e in tw if e["lev"]]
        out.append(F("LEVERAGED_TURNOVER", "AGENT_04", "P1", "槓桿型 ETF 占台股 ETF 成交值比重偏高",
                     "槓桿型每日重設，持有越久波動耗損越大；成交值集中在此代表短線交易盛行，不代表適合長期持有。",
                     f"{_lst(names)} 占 {lev / tot * 100:.0f}% (槓桿 {lev / 1e8:,.1f} 億 / 全部 {tot / 1e8:,.1f} 億)", "leverage", n=len(names),
                     proposal={"change": "在 ETF 卡片與比較器對槓桿型標示「近 N 日占市場成交值比重」，並在持倉診斷中對槓桿型累積曝險加警示。",
                               "modules": ["frontend/assets/js/11-etf-lists.js", "frontend/assets/js/14-etf-portfolio.js"],
                               "effect": "讓使用者看見自己的持倉是否過度集中在短線工具。", "side": "增加畫面資訊量，需放在第二層。", "difficulty": "低"}))
    red = [e for e in tw if e["live"] and e["code"] not in ("0050", "006208") and (e["live"].get("corr_0050") or 0) >= CORR_REDUNDANT and not e["lev"]]
    if red:
        out.append(F("REDUNDANT_WITH_CORE", "AGENT_04", "P2", "與 0050 日報酬高度相關的 ETF (分散效果有限)",
                     f"相關係數 ≥ {CORR_REDUNDANT}。同時持有幾乎沒有分散效果 (仍可能因費用率或配息方式而有差異)。",
                     "；".join(f"{e['code']} ({e['live']['corr_0050']:.2f})" for e in red), "redundancy", n=len(red)))
    hold, codes, pairs = ev["holdings"], [e["code"] for e in tw if e["asset_class"] == "股票" and not e["lev"]], []
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            ha, hb = hold.get(a, {}), hold.get(b, {})
            ov = sum(min(ha[k], hb[k]) for k in set(ha) & set(hb))
            if ov >= OVERLAP_PAIR:
                pairs.append(f"{a}×{b} {ov:.0f}%")
    if pairs:
        out.append(F("HOLDING_OVERLAP", "AGENT_04", "P2", "前十大持股重疊度高的 ETF 組合",
                     "重疊度只用前十大持股計算，且持股權重為人工維護 (非即時)，僅供參考。", "；".join(pairs), "overlap", n=len(pairs)))
    wide = [e for e in tw if e["spread"] is not None and e["spread"] >= SPREAD_WIDE_BPS]
    if wide:
        out.append(F("WIDE_SPREAD", "AGENT_04", "P2", "買賣價差偏寬的台股 ETF",
                     "價差越寬，實際成交價與市價差越大；只有上市 ETF 有官方的最後揭示買賣價。",
                     "；".join(f"{e['code']} {e['spread']:.1f} bps" for e in wide), "liquidity", n=len(wide)))
    return out


def findings_05(ev):
    out = []
    d = ev["snapshot_days"] or 0
    if d < BACKTEST_MIN_DAYS:
        out.append(F("BACKTEST_IMMATURE", "AGENT_05", "P1", "「即時評分有預測力」目前沒有任何驗證",
                     f"前瞻回測只計即時評分之後的快照；目前 {d} 個快照日，至少需要 {BACKTEST_MIN_DAYS} 個才有統計意義。在這之前，"
                     "分數與預警等級只是描述性指標，不能當作預測。", f"快照日 {d}/{BACKTEST_MIN_DAYS}", "backtest", n=d, gap=True))
    inds = [i for i in ev["industries"] if i["score"] is not None and i["score_source"] == "live"]
    if len(inds) >= 5:
        r = [i for i in inds if i["level"] == "LEVEL R"]
        if len(r) / len(inds) * 100 >= LEVEL_R_SHARE:
            out.append(F("LEVEL_R_ARTIFACT", "AGENT_05", "P2", "預警 LEVEL R 的比例可能是百分位評分的人為效應",
                         "各子分數是產業之間的相對百分位，資金流向分數低於門檻的產業比例天生偏高；即使整體市場很強，也總有產業落在後段。",
                         f"{len(r)}/{len(inds)} 個產業 ({len(r) / len(inds) * 100:.0f}%)：{_lst(i['name'] for i in r)}", "level_r", n=len(inds),
                         proposal={"change": "改用絕對門檻 (例如相對大盤超額報酬低於 -X%) 作為 LEVEL R 條件，或在畫面註明「LEVEL R 是相對落後，不是絕對撤退」。",
                                   "modules": ["backend/scoring.py", "backend/live_scoring.py"], "effect": "避免把「相對落後」誤讀成「資金撤出」。",
                                   "side": "改動門檻會讓前瞻回測的歷史快照不可比。", "difficulty": "中"}))
    ev_ind = [i for i in inds if i["yoy"] is not None]
    contra = []
    if ev_ind:
        best, worst = max(ev_ind, key=lambda i: i["score"]), min(ev_ind, key=lambda i: i["score"])
        if best["inst"] is not None and best["inst"] < 0:
            contra.append(f"分數最高的 {best['name']} ({best['score']:.1f}) 當日外資+投信淨賣 {abs(best['inst']):.1f} 億")
        if worst["inst"] is not None and worst["inst"] > 0:
            contra.append(f"分數最低的 {worst['name']} ({worst['score']:.1f}) 當日外資+投信淨買 {worst['inst']:.1f} 億")
    if contra:
        out.append(F("SCORE_VS_FLOW", "AGENT_05", "P2", "最高／最低分產業的法人買賣方向與分數相反", "單日法人買賣可能只是雜訊，但分數與資金方向相反值得持續追蹤。",
                     "；".join(contra), "score_flow", n=len(contra)))
    seed = {k: v["seed"] for k, v in ev["inventory"].items() if v.get("seed")}
    if seed:
        out.append(F("SEED_STILL_SHOWN", "AGENT_05", "P1", "畫面上仍有手寫內容",
                     "這些列不會隨資料更新；畫面已標示來源，但使用者仍可能忽略標籤。", "；".join(f"{k} {n} 列" for k, n in seed.items()),
                     "seed_inventory", n=sum(seed.values())))
    return out


def findings_06(ev):
    out = []
    fails = ev["audit_failures"]
    if fails:
        out.append(F("INGEST_FAILURES", "AGENT_06", "P1", "擷取紀錄中有非成功的項目", "最近的審計日誌出現失敗或降級備援。",
                     "；".join(f"{f['task_name']}={f['status']}" for f in fails[:5]), "sources", n=len(fails)))
    if ev.get("backfill_missing"):
        out.append(F("BACKFILL_PENDING", "AGENT_06", "INFO", "ETF 歷史行情仍在分批回補",
                     "證交所限制每 3 秒 1 個請求，每次排程最多回補固定數量；補齊前年度指標 (近 1 年報酬等) 會是 N/A。",
                     f"尚有 {ev['backfill_missing']} 個 (ETF, 月份) 未完成", "history", n=ev["backfill_missing"]))
    if ev.get("db_mb") is not None and ev["db_mb"] > 50:
        out.append(F("DB_SIZE", "AGENT_06", "P2", "資料庫檔案偏大", "資料庫每次同步都會整檔上傳到 Release，過大會拖慢同步。",
                     f"{ev['db_mb']} MB", "db_size", n=1))
    big = sorted(ev["loc"].items(), key=lambda kv: -kv[1])[:3]
    out.append(F("CODE_SIZE", "AGENT_06", "INFO", "後端程式規模", "僅供參考的規模統計。",
                 f"{len(ev['loc'])} 個模組、共 {sum(ev['loc'].values()):,} 行；最大：" + "、".join(f"{k} {v} 行" for k, v in big), "code", n=len(ev["loc"])))
    return out


BUILDERS = {"AGENT_01": findings_01, "AGENT_02": findings_02, "AGENT_03": findings_03,
            "AGENT_04": findings_04, "AGENT_05": findings_05, "AGENT_06": findings_06}


def collect_findings(ev):
    return {aid: sorted(fn(ev), key=lambda f: SEV_ORDER[f["severity"]]) for aid, fn in BUILDERS.items()}


# ---------------------------------------------------------------------------
# Phase 2~6 (純函式)
# ---------------------------------------------------------------------------
def phase2_reports(findings, ev):
    out = {}
    for aid, name, role in AGENTS:
        fs = findings[aid]
        issues = [f for f in fs if f["severity"] != "INFO"]
        infos = [f for f in fs if f["severity"] == "INFO"]
        props = [f for f in fs if f["proposal"]]
        n = lambda i: aid[-2:] + "-" + str(i)   # noqa: E731
        out[aid] = {
            "agent_id": aid, "agent_name": name, "role": role, "submitted_at": ev["now"],
            "data_timestamp_used": f"資料庫即時快照；稽核時間 {ev['now']}",
            "current_system_problems": ("\n".join(f"{i + 1}. 【{f['severity']}】{f['title']}：{f['detail']}" for i, f in enumerate(issues))
                                        or "本次規則稽核沒有發現需要處理的問題。")
                                       + ("\n" + "\n".join(f"• 觀察：{f['title']} — {f['detail']}" for f in infos) if infos else ""),
            "research_evidence": "\n".join(f"• {f['title']}：{f['evidence']}" for f in fs) or "• 無",
            "identified_defects": "\n".join(f"缺陷 {n(i + 1)}：{f['title']}" for i, f in enumerate(issues)) or "無",
            "improvement_suggestions": "\n".join(f"建議 {i + 1}（{f['title']}）：{f['proposal']['change']}" for i, f in enumerate(props)) or "本次沒有需要提案的項目。",
            "expected_effects": "；".join(f["proposal"]["effect"] for f in props) or "維持目前的資料與評分品質。",
            "potential_risks": "；".join(f["proposal"]["side"] for f in props) or "無新增風險。",
            "findings": fs,
        }
    return out


def phase3_reviews(findings):
    """每位 Agent 審查下一位的最高嚴重度發現：檢查樣本數與證據是否足夠 (規則)。"""
    ids = [a for a, _, _ in AGENTS]
    out = []
    for k, rid in enumerate(ids):
        tid = ids[(k + 1) % len(ids)]
        top = next((f for f in findings[tid] if f["severity"] != "INFO"), None)
        if top is None:
            stance, comment = "NO_FINDINGS (沒有可審查的問題)", f"{AGENT_NAME[tid]} 本次沒有提出需處理的問題；我檢查了其證據清單，沒有發現遺漏。"
            q = None
        elif top["insufficient"]:
            stance = "QUESTION (證據不足)"
            comment = f"對「{top['title']}」：此項依賴尚未取得的資料或尚未累積的樣本，結論只能當作暫定。證據：{top['evidence']}"
            q = "insufficient"
        elif top["n"] is not None and top["n"] < MIN_SAMPLE:
            stance = "QUESTION (樣本偏少)"
            comment = f"對「{top['title']}」：樣本數 n={top['n']} 低於 {MIN_SAMPLE}，容易受單一標的影響，不宜據此下結論。證據：{top['evidence']}"
            q = "small_sample"
        else:
            stance = "SUPPORT (檢查證據與樣本數後支持)"
            comment = f"對「{top['title']}」：已核對證據與樣本數 (n={top['n'] if top['n'] is not None else 'N/A'})，支持其嚴重度 {top['severity']}。證據：{top['evidence']}"
            q = None
        rev = {"reviewer_id": rid, "reviewer_name": AGENT_NAME[rid], "target_agent_id": tid,
               "target_topic": f"審查 {AGENT_NAME[tid]} 的最高嚴重度發現：{top['title'] if top else '無'}",
               "review_stance": stance, "comment": comment, "_question": q, "_finding": top["key"] if top else None}
        if rid == "AGENT_05":
            rev["critic_structured_blocks"] = {
                "supporting_evidence": top["evidence"] if top else "無",
                "counter_evidence": "此項是規則檢查的結果，只偵測規則寫得出來的問題；沒有被規則涵蓋的問題 (商業判斷、邏輯錯誤) 不會被發現。",
                "unverified_assumptions": "各門檻 (集中度、相關係數、價差、回測天數等) 是人工設定的經驗值，尚未用歷史資料校準。",
                "unverifiable_or_missing_data": "美股 ETF 沒有官方來源；淨值與折溢價、配息率、含息報酬沒有官方來源。"}
        out.append(rev)
    return out


def phase4_rebuttals(findings, reviews):
    """被質疑的發現降低一級嚴重度 (最低 P2)；沒被質疑則維持。原地更新 findings 並回傳回應紀錄。"""
    out = []
    for rev in reviews:
        tid, q = rev["target_agent_id"], rev["_question"]
        if q is None:
            dec, reason = "MAINTAIN (維持原判斷)", "審查未提出需修正之處。" if rev["_finding"] else "沒有發現需要回應。"
        else:
            f = next(x for x in findings[tid] if x["key"] == rev["_finding"])
            old = f["severity"]
            f["severity"] = {"P0": "P1", "P1": "P2"}.get(old, old)
            dec = "MODIFY (接納質疑，降低嚴重度並標註限制)" if f["severity"] != old else "MAINTAIN (嚴重度已是下限，補註限制)"
            reason = f"接納 {AGENT_NAME[rev['reviewer_id']]} 的質疑：{('證據不足' if q == 'insufficient' else '樣本偏少')}；嚴重度 {old} → {f['severity']}，結論標註為暫定。"
            f["detail"] += "（經交叉審查，結論為暫定）"
        out.append({"agent_id": tid, "agent_name": AGENT_NAME[tid], "responding_to": [rev["reviewer_id"]], "decision": dec, "reason": reason})
    return out


def phase5_synthesis(findings, reviews, ev):
    by_topic = {}
    for aid, fs in findings.items():
        for f in fs:
            if f["severity"] != "INFO":
                by_topic.setdefault(f["topic"], []).append(f)
    consensus = [f"【{'/'.join(sorted({x['agent'][-2:] for x in fs}))} 號 Agent 共同指出】{_e(fs[0]['title'])}：{_e(fs[0]['evidence'])}"
                 for fs in by_topic.values() if len({x["agent"] for x in fs}) >= 2]
    if not consensus:   # 沒有跨 Agent 重疊時，列出最高嚴重度項目
        top = sorted((f for fs in findings.values() for f in fs if f["severity"] in ("P0", "P1")), key=lambda f: SEV_ORDER[f["severity"]])[:4]
        consensus = [f"【{f['severity']}】{_e(f['title'])}：{_e(f['evidence'])}" for f in top] or ["本次沒有需要優先處理的共識項目。"]
    divergent = []
    for r in reviews:
        if r["_question"]:
            f = next(x for x in findings[r["target_agent_id"]] if x["key"] == r["_finding"])
            divergent.append({"issue": _e(f["title"]), "agent_01_initial_view": _e(f"{AGENT_NAME[r['target_agent_id']]}：{f['evidence']}"),
                              "agent_05_critic_view": _e(f"{AGENT_NAME[r['reviewer_id']]}：{r['comment']}"),
                              "argon_arbitration": "保留雙方：嚴重度已降一級並標註為暫定，待樣本累積或資料來源補齊後重新評估，不以多數決抹除疑慮。"})
    warnings = [f"{_e(f['title'])}：{_e(f['detail'])}" for f in findings["AGENT_05"] if f["severity"] != "INFO"] or ["反方審查本次沒有提出警示。"]
    insuff = [f"{_e(f['title'])}：{_e(f['evidence'])}" for fs in findings.values() for f in fs if f["insufficient"] or f["gap"]] or ["本次沒有標記為證據不足的區域。"]
    return {"session_id": ev["session_id"], "synthesized_at": ev["now"], "orchestrator": "ARGON_ORCHESTRATOR",
            "consensus_solutions": consensus, "divergent_views_preserved": divergent, "critic_risk_warnings": warnings,
            "insufficient_evidence_areas": insuff}


def phase6_proposals(findings, ev):
    out = []
    pool = [f for fs in findings.values() for f in fs if f["proposal"] and f["severity"] != "INFO"]
    for f in sorted(pool, key=lambda f: SEV_ORDER[f["severity"]])[:6]:
        p, sev = f["proposal"], f["severity"]
        ev_score = 25 if not f["insufficient"] and (f["n"] or 0) >= MIN_SAMPLE else 18 if not f["insufficient"] else 12
        val = {"P0": 25, "P1": 20, "P2": 14}[sev]
        risk = {"P0": 20, "P1": 16, "P2": 12}[sev]
        feas = {"低": 15, "中": 11, "高": 6}.get(p.get("difficulty", "中"), 10)
        total = ev_score + val + risk + feas + 12
        out.append({
            "proposal_id": f"LIVE-IMPROVE-{f['key']}", "session_id": ev["session_id"], "created_at": ev["now"],
            "proposer_agents": [f["agent"]], "priority": sev, "status": "PENDING_APPROVAL", "title": f["title"],
            "current_problem": f["detail"], "problem_evidence": f"規則稽核 (資料庫即時快照 {ev['now']})：{f['evidence']}",
            "proposed_change": p["change"], "diff_preview": "", "expected_effect": p["effect"], "affected_modules": p["modules"],
            "potential_side_effects": p["side"], "implementation_difficulty": p.get("difficulty", "中"),
            "testing_plan": "實作時需新增對應的單元測試並通過完整測試套件；用即時資料副本驗證輸出合理。",
            "rollback_plan": "以 git revert 還原該次提交。",
            "score_breakdown": {"data_and_evidence_reliability": ev_score, "expected_improvement_value": val, "risk_control": risk,
                                "technical_feasibility": feas, "system_compatibility": 12, "total_score": total,
                                "scoring_rationale": f"規則式評分：證據{'充足' if ev_score == 25 else '尚可' if ev_score == 18 else '不足'}、嚴重度 {sev}、實作難度 {p.get('difficulty', '中')}。"}})
    return out


def dq_audit(ev):
    return {"session_id": ev["session_id"], "auditor": "AGENT_03 (數據品質研究員)", "audited_at": ev["now"], "seven_statutory_checks": checks_03(ev)}


# ---------------------------------------------------------------------------
# 完整流程
# ---------------------------------------------------------------------------
def _proposal_md(p):
    sb = p["score_breakdown"]
    return (f"# 改善提案：{p['proposal_id']}｜{p['title']}\n\n- **優先級**：`{p['priority']}` ｜ **總評分**：**{sb['total_score']} / 100 分**\n"
            f"- **提案 Agent**：`{', '.join(p['proposer_agents'])}`\n- **核准狀態**：`{p['status']}`（⚠️ 未經使用者明確批准前，嚴禁執行修改）\n\n"
            f"## 1. 目前問題\n{p['current_problem']}\n\n## 2. 問題證據\n{p['problem_evidence']}\n\n## 3. 建議修改方式\n{p['proposed_change']}\n\n"
            f"## 4. 預期效果\n{p['expected_effect']}\n\n## 5. 影響模組\n`{', '.join(p['affected_modules'])}`\n\n## 6. 可能副作用\n{p['potential_side_effects']}\n\n"
            f"## 7. 實作難度\n{p['implementation_difficulty']}\n\n## 8. 測試方式\n{p['testing_plan']}\n\n## 9. 回復方案\n{p['rollback_plan']}\n\n"
            f"## 10. 評分\n{sb['scoring_rationale']}\n")


def _prune_old_sessions():
    """只保留最近 KEEP_SESSIONS 次即時稽核的檔案。檔名比對不分大小寫 (Windows 會把路徑寫成小寫)。"""
    hist = os.path.join(mao.MA_ROOT, "research", "history")
    if not os.path.isdir(hist):
        return
    sids = sorted((f[:-len("_full_record.json")] for f in os.listdir(hist)
                   if f.lower().startswith("session-live-") and f.lower().endswith("_full_record.json")), key=str.lower)
    for sid in sids[:-KEEP_SESSIONS]:
        for sub in ("research/history", "research/completed", "discussions/debate_records", "evaluations/model_evaluations",
                    "evaluations/data_quality", "logs/agent_logs"):
            d = os.path.join(mao.MA_ROOT, *sub.split("/"))
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if f.lower().startswith(sid.lower() + "_") or f.lower() == sid.lower() + ".jsonl":
                    try:
                        os.remove(os.path.join(d, f))
                    except OSError:
                        pass


def run_live_audit_session(topic="ETF 與產業輪動系統即時稽核", trigger_mode="SCHEDULED_LIVE_AUDIT"):
    mao.ensure_ma_directories()
    pre = mao.compute_production_checksums()
    now = datetime.now(TW_TZ)
    sid = f"SESSION-LIVE-{now.strftime('%Y%m%d-%H%M%S')}"
    mao.log_agent_activity(sid, "ARGON_ORCHESTRATOR", "PHASE_1", f"啟動即時稽核：{topic} (觸發模式: {trigger_mode})")
    conn = mao.get_readonly_db_connection()
    try:
        ev = gather_evidence(conn)
    finally:
        conn.close()
    ev["session_id"] = sid
    findings = collect_findings(ev)
    reports = phase2_reports(copy.deepcopy(findings), ev)      # Phase 2 = 辯論之前的獨立研究結果 (深拷貝，不受後續降級影響)
    for aid, rpt in reports.items():
        mao.safe_write_ma_file(f"research/completed/{sid}_{aid}.json", rpt)
        mao.safe_write_ma_file(f"research/completed/{sid}_{aid}.md", f"# {rpt['agent_name']}\n\n## 問題\n{rpt['current_system_problems']}\n\n## 證據\n{rpt['research_evidence']}\n")
        mao.log_agent_activity(sid, aid, "PHASE_2", f"完成獨立稽核 ({len(findings[aid])} 項發現)")
    reviews = phase3_reviews(findings)
    rebuttals = phase4_rebuttals(findings, reviews)      # 會原地降低被質疑發現的嚴重度
    clean_reviews = [{k: v for k, v in r.items() if not k.startswith("_")} for r in reviews]
    mao.safe_write_ma_file(f"discussions/debate_records/{sid}_debate.json",
                           {"session_id": sid, "phase3_cross_reviews": clean_reviews, "phase4_rebuttals": rebuttals})
    synthesis = phase5_synthesis(findings, reviews, ev)
    mao.safe_write_ma_file(f"evaluations/model_evaluations/{sid}_synthesis.json", synthesis)
    proposals = phase6_proposals(findings, ev)
    written = []
    for p in proposals:
        if mao.find_proposal_copies(p["proposal_id"]):    # 已存在於任何資料夾 (含已批准／拒絕／實作)：不重建、不覆蓋人工決定
            continue
        mao.safe_write_ma_file(f"proposals/pending/{p['proposal_id']}.json", p)
        mao.safe_write_ma_file(f"proposals/pending/{p['proposal_id']}.md", _proposal_md(p))
        written.append(p["proposal_id"])
    dq = dq_audit(ev)
    mao.safe_write_ma_file(f"evaluations/data_quality/{sid}_dq_audit.json", dq)
    post = mao.compute_production_checksums()
    bundle = {"session_id": sid, "origin": "live_audit", "topic": topic, "trigger_mode": trigger_mode, "started_at": ev["now"],
              "completed_at": datetime.now(TW_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"), "status": "COMPLETED_AWAITING_USER_APPROVAL",
              "production_integrity_verified": pre == post, "production_checksums": post,
              "phase2_independent_reports": reports, "phase3_cross_reviews": clean_reviews, "phase4_rebuttals": rebuttals,
              "phase5_synthesis": synthesis, "phase6_proposals": proposals, "data_quality_audit": dq,
              "new_proposals_written": written, "method_note": "規則式稽核 (非語言模型)；規則與門檻見 live_audit_session.py 頂端。"}
    mao.safe_write_ma_file(f"research/history/{sid}_full_record.json", bundle)
    mao.log_agent_activity(sid, "ARGON_ORCHESTRATOR", "PHASE_6", f"完成：{len(proposals)} 項提案 (新增 {len(written)})，正式系統完整性 {pre == post}")
    _prune_old_sessions()
    return bundle
