"""
產業輪動「即時評分」：把 5 項子分數由官方即時資料算出，取代手寫的種子值。

為什麼要做：原本 industry_rotation_scores 的 5 項子分數是 seed_and_engine.py 內建的固定數字，只有 11/21 一個時間點，
警示等級、排名、前瞻回測、策略模擬全都吃這組不會動的分數。這裡改成每次排程用當下的官方資料重算。

方法 (橫斷面百分位：每項指標在「可評分產業」之間排名，再線性映射成 15~95 分；輪動本來就是相對概念)：
  fundamentals   產業合計單月營收年增 (MOPS)
  future_growth  0.5 × 累計營收年增 + 0.5 × 營收加速度 (單月年增 − 累計年增)        ← 動能代理指標，不是分析師預估
  institutional  外資+投信當日淨買賣金額 ÷ 產業當日成交值 (買賣超強度，消除產業規模差異)
  valuation      PEG 代理：產業本益比中位數 ÷ max(累計營收年增, 5)，越低越合理      ← 不是真正的 PEG (用營收成長取代盈餘成長)
  capital_flow   0.5 × 近 N 日類股報酬指數相對加權報酬指數的超額報酬 + 0.5 × 成交值占比相對前幾日均值的變化
                 (成交值占比需要至少 2 天歷史；累積不足時只用超額報酬)
總分仍由 scoring.compute_weighted_total 以「啟用版本的權重」計算，預警等級仍由 scoring.classify_alert_level 判定，
所以治理頁調整過的權重與門檻照常生效。

誠實的限制 (也會顯示在每個產業的 data_limitations)：
  - 全是代理指標：沒有財報獲利、毛利率、資本支出、分析師預估，所以不是完整的基本面模型。
  - 百分位分數只反映「相對其他產業」，所有產業都弱時最高分的產業仍會拿高分。
  - 法人金額 = 淨買賣股數 × 當日收盤價 (近似，實際成交均價不同)；缺收盤價的公司不計入，覆蓋率會列出。
  - 「生技／電信／觀光零售」是異質混合分類，維持不評分 (資料不足不得硬排名)。

純函式在檔案前半 (無資料庫依賴，方便測試)，資料庫存取在後半。
"""
import json
import statistics

SCORE_FLOOR = 15.0
SCORE_SPAN = 80.0                 # 百分位 0 → 15 分、1 → 95 分
MIN_COMPANIES = 3                 # 產業旗下至少要有這麼多家公司才評分
MIN_COVERAGE_FOR_INSTI = 0.6      # 法人金額覆蓋率 (有收盤價的公司比例) 低於此值視為缺資料
PEG_GROWTH_FLOOR = 5.0            # 成長率低於 5% 一律以 5% 計，避免除以接近 0 或負數
SHARE_HISTORY_DAYS = 5            # 成交值占比的比較基準：前最多 5 個交易日的平均
NEUTRAL = 50.0

# 資金流向狀態 A~E：以「資金面」= (資金流向分數 + 法人分數) / 2 分級
STATE_CUTS = (("A", 75.0), ("B", 58.0), ("C", 42.0), ("D", 28.0))   # 其餘為 E

SUB_KEYS = ("capital_flow", "fundamentals", "future_growth", "institutional", "valuation")
SUB_LABELS = {"capital_flow": "資金流向", "fundamentals": "基本面", "future_growth": "成長動能",
              "institutional": "法人布局", "valuation": "估值"}

LIMITATIONS = ("全部為代理指標 (無財報獲利、毛利率、資本支出或分析師預估)；百分位分數只反映相對其他產業的位置；"
               "法人金額以收盤價近似；估值為營收成長調整後的 PEG 代理指標。")


# ---------------------------------------------------------------------------
# 純函式
# ---------------------------------------------------------------------------
def pct_rank(values):
    """百分位 (0~1)：最小 0、最大 1、並列取平均名次；None 保持 None，只在有值者之間排名。"""
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [None] * len(values)
    n = len(idx)
    if n == 0:
        return out
    if n == 1:
        out[idx[0]] = 0.5
        return out
    order = sorted(idx, key=lambda i: values[i])
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            out[order[k]] = avg / (n - 1)
        i = j + 1
    return out


def to_score(p):
    return None if p is None else round(SCORE_FLOOR + SCORE_SPAN * p, 1)


def _num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def compute_industry_metrics(companies, turnover_by_date=None, rel_returns=None, min_companies=MIN_COMPANIES):
    """
    companies: [{industry, rev_cur, rev_prev, rev_ly, cum_cur, cum_ly, pe, pb, foreign, itc, dealer, close, trade_value}]
               金額單位：營收為「千元」、trade_value 為「元」、法人為「股」、close 為「元」。
    turnover_by_date: {ISO 日期: {industry_id: 成交值(元)}} (含最新一天)，用來算成交值占比變化。
    rel_returns: {industry_id: {"pct": 超額報酬%, "days": 天數}}。
    回傳 {industry_id: metrics dict}。公司數不足的產業不輸出。
    """
    groups = {}
    for c in companies:
        if c.get("industry"):
            groups.setdefault(c["industry"], []).append(c)
    out = {}
    for ind, rows in groups.items():
        if len(rows) < min_companies:
            continue
        s = lambda k: sum((_num(r.get(k)) or 0.0) for r in rows)   # noqa: E731
        rev_cur, rev_prev, rev_ly, cum_cur, cum_ly = s("rev_cur"), s("rev_prev"), s("rev_ly"), s("cum_cur"), s("cum_ly")
        yoy = (rev_cur / rev_ly - 1) * 100 if rev_ly else None
        mom = (rev_cur / rev_prev - 1) * 100 if rev_prev else None
        cum_yoy = (cum_cur / cum_ly - 1) * 100 if cum_ly else None
        accel = (yoy - cum_yoy) if (yoy is not None and cum_yoy is not None) else None

        pes = [p for p in (_num(r.get("pe")) for r in rows) if p is not None and p > 0]
        pbs = [p for p in (_num(r.get("pb")) for r in rows) if p is not None and p > 0]
        pe_med = _median(pes)
        peg = (pe_med / max(cum_yoy, PEG_GROWTH_FLOOR)) if (pe_med is not None and cum_yoy is not None) else None

        # 法人買賣金額 (億元)：只計有收盤價的公司
        priced = [r for r in rows if _num(r.get("close")) and _num(r.get("close")) > 0 and r.get("foreign") is not None]
        with_insti = [r for r in rows if r.get("foreign") is not None]
        val = lambda k: sum((_num(r.get(k)) or 0.0) * _num(r["close"]) for r in priced) / 1e8   # noqa: E731
        f_val, i_val, d_val = val("foreign"), val("itc"), val("dealer")
        turnover = sum((_num(r.get("trade_value")) or 0.0) for r in priced) / 1e8
        coverage = (len(priced) / len(with_insti)) if with_insti else 0.0
        inst_ratio = ((f_val + i_val) / turnover * 100) if (turnover > 0 and coverage >= MIN_COVERAGE_FOR_INSTI) else None
        out[ind] = {
            "companies": len(rows), "yoy": yoy, "mom": mom, "cum_yoy": cum_yoy, "accel": accel,
            "pe_median": pe_med, "pb_median": _median(pbs), "peg": peg,
            "foreign_billion": round(f_val, 2), "itc_billion": round(i_val, 2), "dealer_billion": round(d_val, 2),
            "inst_net_billion": round(f_val + i_val, 2), "turnover_billion": round(turnover, 2),
            "inst_ratio_pct": None if inst_ratio is None else round(inst_ratio, 3),
            "price_coverage": round(coverage, 3),
            "rev_billion": round(rev_cur / 1e5, 2), "rev_ly_billion": round(rev_ly / 1e5, 2),
            "rs_pct": None, "rs_days": 0, "share_change_pct": None,
        }
        rr = (rel_returns or {}).get(ind)
        if rr and rr.get("pct") is not None:
            out[ind]["rs_pct"], out[ind]["rs_days"] = round(rr["pct"], 2), rr.get("days", 0)

    # 成交值占比變化：最新一天的占比 vs 前最多 SHARE_HISTORY_DAYS 天占比的平均
    dates = sorted(turnover_by_date or {})
    if len(dates) >= 2:
        latest, prev_dates = dates[-1], dates[-1 - SHARE_HISTORY_DAYS:-1]

        def share(d, ind):
            tot = sum(turnover_by_date[d].values())
            return (turnover_by_date[d].get(ind, 0.0) / tot) if tot else None

        for ind, m in out.items():
            now = share(latest, ind)
            prevs = [x for x in (share(d, ind) for d in prev_dates) if x]
            if now is not None and prevs:
                m["share_change_pct"] = round((now / (sum(prevs) / len(prevs)) - 1) * 100, 2)
    return out


def score_industries(metrics, excluded=()):
    """
    metrics: compute_industry_metrics 的輸出。excluded: 不評分的產業 id (異質分類)。
    回傳 {industry_id: {"scores": {五項}, "missing": [缺的項目], "state": A~E, "confidence": 高/中/低}}。
    缺資料的子分數以 50 (中性) 代入並列在 missing，信心等級隨之下降。
    """
    ids = [i for i in metrics if i not in set(excluded)]
    if not ids:
        return {}
    col = lambda f: [f(metrics[i]) for i in ids]   # noqa: E731
    p_fund = pct_rank(col(lambda m: m["yoy"]))
    p_acc = pct_rank(col(lambda m: m["accel"]))
    p_cum = pct_rank(col(lambda m: m["cum_yoy"]))
    p_inst = pct_rank(col(lambda m: m["inst_ratio_pct"]))
    p_peg = pct_rank(col(lambda m: None if m["peg"] is None else -m["peg"]))   # 越低越好
    p_rs = pct_rank(col(lambda m: m["rs_pct"]))
    p_share = pct_rank(col(lambda m: m["share_change_pct"]))

    def avg(*ps):
        ps = [p for p in ps if p is not None]
        return sum(ps) / len(ps) if ps else None

    out = {}
    for k, ind in enumerate(ids):
        raw = {
            "fundamentals": p_fund[k],
            "future_growth": avg(p_cum[k], p_acc[k]),
            "institutional": p_inst[k],
            "valuation": p_peg[k],
            "capital_flow": avg(p_rs[k], p_share[k]),
        }
        scores, missing = {}, []
        for key in SUB_KEYS:
            sc = to_score(raw[key])
            if sc is None:
                missing.append(key)
                sc = NEUTRAL
            scores[key] = sc
        flow = (scores["capital_flow"] + scores["institutional"]) / 2.0
        state = next((s for s, cut in STATE_CUTS if flow >= cut), "E")
        out[ind] = {
            "scores": scores, "missing": missing, "state": state,
            "confidence": "高 (High)" if not missing else ("中 (Medium)" if len(missing) == 1 else "低 (Low)"),
        }
    return out


def _fmt_pct(x):
    return "N/A" if x is None else f"{x:+.1f}%"


def build_narrative(ind_name, m, res, rank_text=""):
    """由數字產生 supporting / counter / invalidation 文字 (全部來自 metrics，不含手寫敘事)。"""
    sc = res["scores"]
    facts = {
        "fundamentals": f"單月營收年增 {_fmt_pct(m['yoy'])}",
        "future_growth": f"累計營收年增 {_fmt_pct(m['cum_yoy'])}、營收加速度 {_fmt_pct(m['accel'])}",
        "institutional": ("外資+投信當日淨買賣 " + (f"{m['inst_net_billion']:+.1f} 億元 (占成交值 {m['inst_ratio_pct']:+.2f}%)"
                                                      if m["inst_ratio_pct"] is not None else "資料不足")),
        "valuation": ("本益比中位數 " + (f"{m['pe_median']:.1f} 倍" if m["pe_median"] is not None else "N/A")
                      + (f"、PEG 代理 {m['peg']:.2f}" if m["peg"] is not None else "")),
        "capital_flow": ("近 %d 日相對大盤 %s" % (m["rs_days"], _fmt_pct(m["rs_pct"])) if m["rs_pct"] is not None else "類股指數資料不足")
                        + ("、成交值占比變化 " + _fmt_pct(m["share_change_pct"]) if m["share_change_pct"] is not None else ""),
    }
    ranked = sorted(SUB_KEYS, key=lambda k: -sc[k])
    best, worst = ranked[:2], ranked[-2:][::-1]
    supporting = "；".join(f"{SUB_LABELS[k]} {sc[k]:.0f} 分 ({facts[k]})" for k in best)
    counter = "；".join(f"{SUB_LABELS[k]} {sc[k]:.0f} 分 ({facts[k]})" for k in worst)
    invalid = (f"下個月營收年增若由 {_fmt_pct(m['yoy'])} 明顯下滑、或法人轉為連續賣超，即時分數會下降；"
               "評分每個交易日收盤後重算，結論以最新一次為準。")
    return supporting, counter, invalid, facts


def flow_matrix(metrics, names, insti_date=None):
    """
    即時資金流向桑基圖的資料：三大法人 (外資／投信／自營商) 對各產業的「淨買賣金額」(億元)。
    每個 (法人, 產業) 的淨額 > 0 是買超 (法人 → 產業)，< 0 是賣超 (產業 → 法人)。只呈現官方數字，不做預測。
    金額 = 淨買賣股數 × 當日收盤價 (近似)；沒有收盤價的公司不計入，覆蓋率隨附。
    """
    inst_keys = (("foreign", "外資", "foreign_billion"), ("itc", "投信", "itc_billion"), ("dealer", "自營商", "dealer_billion"))
    rows, tot_buy, tot_sell = [], {k: 0.0 for k, _, _ in inst_keys}, {k: 0.0 for k, _, _ in inst_keys}
    for ind, m in metrics.items():
        flows = {k: m[f] for k, _, f in inst_keys}
        for k, v in flows.items():
            if v > 0:
                tot_buy[k] += v
            else:
                tot_sell[k] += -v
        rows.append({"id": ind, "name": names.get(ind, ind), "flows": flows, "net": round(sum(flows.values()), 2),
                     "buy": round(sum(v for v in flows.values() if v > 0), 2),
                     "sell": round(sum(-v for v in flows.values() if v < 0), 2),
                     "turnover": m["turnover_billion"], "coverage": m["price_coverage"], "companies": m["companies"]})
    rows.sort(key=lambda r: -r["net"])
    d = str(insti_date or "")
    return {
        "available": bool(rows),
        "as_of": f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else None,
        "unit": "億元",
        "institutions": [{"key": k, "label": lbl, "buy": round(tot_buy[k], 2), "sell": round(tot_sell[k], 2),
                          "net": round(tot_buy[k] - tot_sell[k], 2)} for k, lbl, _ in inst_keys],
        "industries": rows,
        "note": "淨買賣金額 = 法人淨買賣股數 × 當日收盤價 (近似，實際成交均價不同)；只含有營收資料的上市櫃個股，不含 ETF 與權證。",
    }


# ---------------------------------------------------------------------------
# 資料庫存取
# ---------------------------------------------------------------------------
def _date_expr(col="l.insti_trade_date"):
    """'20261127' → '2026-11-27'，用來對應 live_stock_quotes.trade_date。"""
    return f"substr({col},1,4)||'-'||substr({col},5,2)||'-'||substr({col},7,2)"


def load_inputs(conn):
    """從資料庫讀出評分所需資料。回傳 (companies, turnover_by_date, rel_returns, info) ；沒有即時資料時 companies 為空。"""
    from backtest import BENCHMARK_INDEX, INDUSTRY_INDEX_MAP   # 延遲匯入：沿用回測對照的類股指數

    cur = conn.cursor()
    cur.execute(f"""
        SELECT l.mapped_industry_id AS industry, l.company_code, l.rev_current_thousand AS rev_cur,
               l.rev_prev_month_thousand AS rev_prev, l.rev_last_year_thousand AS rev_ly,
               l.cum_rev_current_thousand AS cum_cur, l.cum_rev_last_year_thousand AS cum_ly,
               l.pe_ratio AS pe, l.pb_ratio AS pb, l.foreign_net_shares AS "foreign", l.itc_net_shares AS itc,
               l.dealer_net_shares AS dealer, l.insti_trade_date, l.data_ym, q.close_price AS close, q.trade_value_twd AS trade_value
        FROM live_company_fundamentals l
        LEFT JOIN live_stock_quotes q ON q.company_code = l.company_code AND q.trade_date = {_date_expr()}
        WHERE l.mapped_industry_id IS NOT NULL
          AND l.data_ym = (SELECT MAX(x.data_ym) FROM live_company_fundamentals x WHERE x.company_code = l.company_code)
    """)
    companies = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT q.trade_date, l.mapped_industry_id AS industry, SUM(q.trade_value_twd) AS v
        FROM live_stock_quotes q
        JOIN (SELECT company_code, mapped_industry_id FROM live_company_fundamentals GROUP BY company_code) l
          ON l.company_code = q.company_code
        WHERE l.mapped_industry_id IS NOT NULL AND q.trade_value_twd IS NOT NULL
        GROUP BY q.trade_date, l.mapped_industry_id
    """)
    turnover = {}
    for r in cur.fetchall():
        turnover.setdefault(r["trade_date"], {})[r["industry"]] = r["v"]

    # 類股報酬指數相對加權報酬指數的超額報酬：以資料庫現有的連續交易日 (最多 20 日) 連乘每日漲跌幅
    cur.execute("SELECT index_name, trade_date, change_pct FROM live_market_indices WHERE change_pct IS NOT NULL")
    daily = {}
    for r in cur.fetchall():
        daily.setdefault(r["index_name"], {})[r["trade_date"]] = r["change_pct"]

    def window(name, dates):
        pct = 1.0
        for d in dates:
            if d not in daily.get(name, {}):
                return None
            pct *= 1 + daily[name][d] / 100.0
        return (pct - 1) * 100

    bench_dates = sorted(daily.get(BENCHMARK_INDEX, {}))[-20:]
    rel_returns = {}
    for ind, idx_name in INDUSTRY_INDEX_MAP.items():
        common = [d for d in bench_dates if d in daily.get(idx_name, {})]
        if len(common) >= 2:
            a, b = window(idx_name, common), window(BENCHMARK_INDEX, common)
            if a is not None and b is not None:
                rel_returns[ind] = {"pct": a - b, "days": len(common)}
    info = {"insti_date": max((c["insti_trade_date"] for c in companies if c.get("insti_trade_date")), default=None),
            "data_ym": max((c["data_ym"] for c in companies if c.get("data_ym")), default=None)}
    return companies, turnover, rel_returns, info


def apply_live_scoring(conn=None):
    """
    以即時資料重算「啟用中模型版本」各產業的 5 項子分數、總分、狀態與證據文字 (權重與門檻沿用該版本)，
    並把 score_source 標成 'live'。沒有足夠的即時資料時完全不動 (保留種子分數與 'seed' 標記)。
    回傳摘要 dict。
    """
    from db import get_connection
    from scoring import classify_alert_level, compute_weighted_total, effective_thresholds

    own = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.cursor()
        companies, turnover, rel_returns, info = load_inputs(conn)
        if not companies:
            return {"applied": False, "reason": "沒有即時公司資料"}
        cur.execute("SELECT version_id, weights_json FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
        cfg = cur.fetchone()
        if not cfg:
            return {"applied": False, "reason": "沒有啟用中的模型版本"}
        weights = json.loads(cfg["weights_json"])
        version = cfg["version_id"]

        cur.execute("SELECT industry_id, industry_name FROM industry_taxonomy")
        names = {r["industry_id"]: r["industry_name"] for r in cur.fetchall()}
        cur.execute("SELECT industry_id, rotation_state FROM industry_rotation_scores WHERE model_version = ?", (version,))
        seed_state = {r["industry_id"]: r["rotation_state"] for r in cur.fetchall()}
        # 異質混合分類維持不評分
        excluded = {i for i, st in seed_state.items() if st == "INSUFFICIENT_DATA"}

        metrics = compute_industry_metrics(companies, turnover, rel_returns)
        results = score_industries(metrics, excluded)
        if len(results) < 5:
            return {"applied": False, "reason": f"可評分產業只有 {len(results)} 個 (< 5)，不足以做橫斷面排名"}

        insti_iso = None
        if info["insti_date"] and len(info["insti_date"]) == 8:
            d = info["insti_date"]
            insti_iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        as_of = insti_iso or "latest"
        ym = info["data_ym"] or ""
        period = (f"{int(ym[:-2]) + 1911}-{ym[-2:]}營收 + {as_of} 盤後" if ym.isdigit() else f"{as_of} 盤後")
        # 每次排程都會先重灌種子列 (資料日 2026-11-21)；唯一鍵是 (產業, 資料日, 版本)，所以若啟用版本剛好是種子版本，
        # 種子列會與上次即時評分改過日期的列並存，同一產業出現兩列。更新前先只留最新的一列，避免重複與撞唯一鍵。
        cur.execute("""
            DELETE FROM industry_rotation_scores
            WHERE model_version = ?
              AND record_id NOT IN (SELECT MAX(record_id) FROM industry_rotation_scores
                                    WHERE model_version = ? GROUP BY industry_id)
        """, (version, version))
        n = 0
        for ind, res in results.items():
            m = metrics[ind]
            row = {"rotation_state": res["state"], "score_capital_flow": res["scores"]["capital_flow"],
                   "score_fundamentals": res["scores"]["fundamentals"], "score_future_growth": res["scores"]["future_growth"],
                   "score_institutional": res["scores"]["institutional"], "score_valuation": res["scores"]["valuation"]}
            total = compute_weighted_total(row, weights)
            supporting, counter, invalid, facts = build_narrative(names.get(ind, ind), m, res)
            tag = ("營收年增強且法人買超" if res["scores"]["fundamentals"] >= 65 and res["scores"]["institutional"] >= 65 else
                   "營收強但法人偏賣" if res["scores"]["fundamentals"] >= 65 else
                   "法人買超但營收偏弱" if res["scores"]["institutional"] >= 65 else
                   "營收與法人皆偏弱" if res["scores"]["fundamentals"] < 40 and res["scores"]["institutional"] < 40 else "多空分歧")
            flow_txt = lambda who, v: f"{who} 當日淨{'買超' if v >= 0 else '賣超'} {abs(v):.1f} 億元 (收盤價近似，{as_of})"   # noqa: E731
            cur.execute("""
                UPDATE industry_rotation_scores SET
                    as_of_date = ?, period_covered = ?, score_source = 'live',
                    rel_strength_20d = ?, rel_strength_60d = NULL,
                    foreign_net_flow_trend = ?, itc_net_flow_trend = ?, dealer_net_flow_trend = ?,
                    rev_yoy_pct = ?, rev_mom_pct = ?, rotation_state = ?, transition_tag = ?,
                    score_capital_flow = ?, score_fundamentals = ?, score_future_growth = ?,
                    score_institutional = ?, score_valuation = ?, total_weighted_score = ?,
                    short_term_momentum_score = ?, mid_term_fundamental_score = ?, long_term_structural_score = ?,
                    confidence_level = ?, missing_data_pct = ?,
                    supporting_evidence = ?, counter_evidence = ?, invalidation_conditions = ?, data_limitations = ?
                WHERE industry_id = ? AND model_version = ?
            """, (
                as_of, period, m["rs_pct"],
                flow_txt("外資", m["foreign_billion"]), flow_txt("投信", m["itc_billion"]), flow_txt("自營商", m["dealer_billion"]),
                None if m["yoy"] is None else round(m["yoy"], 2), None if m["mom"] is None else round(m["mom"], 2),
                res["state"], tag,
                res["scores"]["capital_flow"], res["scores"]["fundamentals"], res["scores"]["future_growth"],
                res["scores"]["institutional"], res["scores"]["valuation"], total,
                res["scores"]["capital_flow"], res["scores"]["fundamentals"], res["scores"]["future_growth"],
                res["confidence"], round(100.0 * len(res["missing"]) / len(SUB_KEYS), 1),
                supporting, counter, invalid,
                LIMITATIONS + (f" 本次缺少：{'、'.join(SUB_LABELS[k] for k in res['missing'])} (以 50 分中性值代入)。" if res["missing"] else ""),
                ind, version,
            ))
            n += cur.rowcount
        # 預警中心的等級跟著分數走 (治理頁調整門檻時本來就是這樣重算的)；預警的說明文字仍是手寫，不在這裡改
        cur.execute("SELECT thresholds_json FROM model_governance_configs WHERE version_id = ?", (version,))
        th = effective_thresholds(json.loads(cur.fetchone()["thresholds_json"]))
        synced = 0
        for ind, res in results.items():
            cur.execute("SELECT total_weighted_score FROM industry_rotation_scores WHERE industry_id = ? AND model_version = ?", (ind, version))
            row = cur.fetchone()
            level = classify_alert_level(row["total_weighted_score"] if row else None, res["scores"]["capital_flow"], th)
            if level:
                cur.execute("UPDATE trend_early_warnings SET alert_level = ? WHERE industry_id = ?", (level, ind))
                synced += cur.rowcount
        if n:
            cur.execute("""
                INSERT INTO ingestion_audit_logs (run_timestamp, task_name, source_id, status, records_affected, message)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (_now_iso(), "LIVE_INDUSTRY_SCORING", "SRC_MOPS", "SUCCESS", n,
                  f"已用官方即時資料重算 {n} 個產業的 5 項子分數 (模型 {version}，資料日 {as_of}，{period})"))
        conn.commit()
        return {"applied": bool(n), "version": version, "industries": n, "warnings_synced": synced, "as_of": as_of, "excluded": sorted(excluded),
                "rs_available": len(rel_returns), "turnover_days": len(turnover)}
    finally:
        if own:
            conn.close()


def _now_iso():
    from common import now_iso
    return now_iso()
