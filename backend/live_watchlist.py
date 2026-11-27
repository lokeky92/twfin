"""
個股研究名單：由全市場即時資料機械式篩選，取代 seed_and_engine.py 裡手寫的 11 檔。

原本的名單是人工挑的 11 家公司，類別 (優先研究／中長期觀察／等待估值合理／基本面或風險不佳) 與支持、反對理由
都是 11/22 手寫，之後只有營收與本益比數字會被更新，類別與理由不會跟著變。

這裡改成每次排程對「營收前 N 大、且有收盤價」的上市櫃公司套用固定規則分類，理由全部由當期數字組成：
  strong  單月營收年增 ≥ STRONG_YOY 且 累計營收年增 ≥ STRONG_CUM
  優先研究        strong、本益比 0 < P/E ≤ PE_OK、當日法人淨買超、單月營收月增為正
  中長期觀察      strong、本益比 0 < P/E ≤ PE_OK，但法人或月增沒有同時確認
  等待估值合理    strong，但本益比 > PE_OK 或沒有有效本益比 (虧損)
  基本面或風險不佳  累計營收年增為負，或單月年增為負且累計年增未達 STRONG_CUM
                  (單月衰退但累計仍強者不歸類，多半是單月一次性認列)
規則是機械式篩選，不是投資建議；沒有財報獲利、毛利率、產業地位等資訊，這些限制會寫在每檔的理由裡。

純函式，無資料庫依賴，方便測試。
"""
import statistics

UNIVERSE_SIZE = 150          # 營收前 N 大
PER_CATEGORY = 6             # 每個類別最多列幾檔
STRONG_YOY = 30.0
STRONG_CUM = 20.0
PE_OK = 35.0
ONE_OFF_GAP_PP = 40.0        # 單月與累計年增相差達此值時提醒可能是一次性因素
MIN_ROWS_TO_REPLACE = 4      # 篩出的檔數少於此值時不取代種子名單 (資料明顯不足)

CATEGORIES = ("優先研究", "中長期觀察", "等待估值合理", "基本面或風險不佳")
EPS_NOTE = "本系統沒有財報 EPS 資料 (只有月營收、本益比與股價淨值比)"


def _num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _sg(x, nd=1, unit=""):
    return "N/A" if x is None else f"{x:+,.{nd}f}{unit}"


def industry_pe_medians(companies):
    by = {}
    for c in companies:
        pe = _num(c.get("pe"))
        if pe is not None and pe > 0 and c.get("industry"):
            by.setdefault(c["industry"], []).append(pe)
    return {k: round(statistics.median(v), 2) for k, v in by.items() if len(v) >= 3}


def _inst_value(c):
    """外資+投信當日淨買賣金額 (億元)；缺收盤價或法人資料時回傳 None。"""
    close = _num(c.get("close"))
    f, i = c.get("foreign"), c.get("itc")
    if not close or close <= 0 or f is None or i is None:
        return None
    return (f + i) * close / 1e8


def categorize(c):
    """回傳類別字串或 None (不列入名單)。"""
    yoy, cum, mom, pe = _num(c.get("rev_yoy")), _num(c.get("cum_yoy")), _num(c.get("rev_mom")), _num(c.get("pe"))
    if yoy is None or cum is None:
        return None
    # 單月衰退但累計仍強 (多半是單月一次性認列，例如金控) 不硬歸類；累計也不強才算基本面不佳
    if cum < 0 or (yoy < 0 and cum < STRONG_CUM):
        return "基本面或風險不佳"
    if yoy < 0:
        return None
    if yoy >= STRONG_YOY and cum >= STRONG_CUM:
        if pe is None or pe <= 0 or pe > PE_OK:
            return "等待估值合理"
        inst = _inst_value(c)
        if inst is not None and inst > 0 and mom is not None and mom > 0:
            return "優先研究"
        return "中長期觀察"
    return None


def _facts(c, pe_med):
    """(正面事實, 負面事實) 兩個清單；全部是數字描述。"""
    yoy, cum, mom, pe = _num(c.get("rev_yoy")), _num(c.get("cum_yoy")), _num(c.get("rev_mom")), _num(c.get("pe"))
    inst = _inst_value(c)
    pos, neg = [], []
    if yoy is not None:
        (pos if yoy >= STRONG_YOY else neg if yoy < 0 else []).append(f"單月營收年增 {_sg(yoy, 1, '%')}")
    if cum is not None:
        (pos if cum >= STRONG_CUM else neg if cum < 0 else []).append(f"累計營收年增 {_sg(cum, 1, '%')}")
    if mom is not None:
        (pos if mom > 0 else neg).append(f"單月營收月增 {_sg(mom, 1, '%')}")
    if yoy is not None and cum is not None and yoy - cum <= -20:
        neg.append(f"單月年增 ({_sg(yoy, 1, '%')}) 明顯低於累計年增 ({_sg(cum, 1, '%')})，營收動能放緩")
    if yoy is not None and cum is not None and yoy - cum >= 20:
        pos.append(f"單月年增 ({_sg(yoy, 1, '%')}) 明顯高於累計年增 ({_sg(cum, 1, '%')})，營收動能加速")
    if yoy is not None and cum is not None and abs(yoy - cum) >= ONE_OFF_GAP_PP:
        neg.append(f"單月年增與累計年增相差 {abs(yoy - cum):.0f} 個百分點，單月可能受一次性或認列時點影響，不宜單看一個月")
    if inst is not None:
        (pos if inst > 0 else neg).append(f"外資+投信當日淨{'買超' if inst > 0 else '賣超'} {abs(inst):.2f} 億元")
    if pe is not None and pe > 0:
        if pe_med and pe <= pe_med:
            pos.append(f"本益比 {pe:.1f} 倍，不高於所屬產業中位數 {pe_med:.1f} 倍")
        elif pe_med and pe > pe_med * 1.5:
            neg.append(f"本益比 {pe:.1f} 倍，高於所屬產業中位數 {pe_med:.1f} 倍的 1.5 倍")
    elif pe is None or pe <= 0:
        neg.append("沒有有效本益比 (可能虧損)")
    return pos, neg


def build_entry(c, category, industry_name, pe_med, as_of_iso, now_note=""):
    """回傳可寫入 company_research_watchlist 的 dict。"""
    pos, neg = _facts(c, pe_med)
    yoy, cum, mom = _num(c.get("rev_yoy")), _num(c.get("cum_yoy")), _num(c.get("rev_mom"))
    pe, pb, dy = _num(c.get("pe")), _num(c.get("pb")), _num(c.get("dy"))
    ym = str(c.get("data_ym") or "")
    period = f"{int(ym[:-2]) + 1911}-{ym[-2:]} (民國{ym})" if ym.isdigit() and len(ym) >= 4 else (ym or "N/A")
    pe_txt = f"P/E {pe:.2f}x" if pe is not None and pe > 0 else "P/E N/A(虧損或極高)"
    val_status = f"【TWSE/TPEx官方API】{pe_txt}｜P/B {pb:.2f}x" if pb is not None else f"【TWSE/TPEx官方API】{pe_txt}｜P/B N/A"
    if dy is not None:
        val_status += f"｜殖利率 {dy:.2f}%"
    d = str(c.get("insti_trade_date") or "")
    d_txt = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else "日期未知"
    inst = _inst_value(c)
    f, i, dl = c.get("foreign"), c.get("itc"), c.get("dealer")
    insti = (f"【{d_txt} T86/TPEx官方API】外資 {(f or 0):+,}股｜投信 {(i or 0):+,}股｜自營商 {(dl or 0):+,}股"
             + (f"（外資+投信約 {inst:+.2f} 億元）" if inst is not None else ""))

    bull = ("；".join(pos) + "。") if pos else "目前沒有達到門檻的正面數字。"
    bear = ("；".join(neg) + "。") if neg else "目前沒有明顯的負面數字。"
    if category == "基本面或風險不佳":
        bull = "；".join(pos) + "。" if pos else "目前沒有達到門檻的正面數字。"
    limits = "僅依月營收、本益比與法人買賣超的機械式篩選，沒有財報獲利、毛利率、客戶集中度或產業地位資訊，不是投資建議。"
    if pe is not None and pe > 0:
        val_risk = (f"本益比 {pe:.1f} 倍" + (f"（所屬產業中位數 {pe_med:.1f} 倍）" if pe_med else "") + "；營收年增是單月數字，"
                    "若基期墊高、營收放緩，高本益比可能快速壓縮。" if pe > PE_OK else
                    f"本益比 {pe:.1f} 倍" + (f"（所屬產業中位數 {pe_med:.1f} 倍）" if pe_med else "") + "，在篩選門檻內，但仍需搭配財報確認獲利。")
    else:
        val_risk = "沒有有效本益比，無法以估值判斷；請另外查閱財報。"
    val_risk += " " + limits

    if category == "基本面或風險不佳":
        invalid = ("下個月單月營收年增轉為正、且累計營收年增回升到 0% 以上，即不再符合此類別。")
    else:
        floor = max((yoy or 0) / 2, 0)
        invalid = (f"下個月單月營收年增由 {_sg(yoy, 1, '%')} 掉到 {floor:.0f}% 以下、或累計營收年增跌破 {STRONG_CUM:.0f}%，"
                   "或法人轉為連續賣超，即不再符合此類別。")
    return {
        "ticker": str(c["company_code"]), "company_name": str(c["company_name"]), "industry_id": c["industry"],
        "watchlist_category": category,
        "supply_chain_position": f"{c.get('official_industry') or '未分類'}（對應本系統產業：{industry_name}）",
        "latest_rev_period": period,
        "latest_rev_billion_twd": round((_num(c.get("rev_cur")) or 0.0) / 1e5, 2),
        "rev_mom_pct": round(mom, 2) if mom is not None else 0.0,
        "rev_yoy_pct": round(yoy, 2) if yoy is not None else 0.0,
        "eps_ttm_or_est": EPS_NOTE,
        "pe_ratio_status": val_status, "institutional_ownership_trend": insti,
        "bull_case": bull, "bear_case": bear, "valuation_risk": val_risk, "invalidation_condition": invalid,
        "as_of_date": d or as_of_iso, "source_id": "SRC_MOPS",
    }


def select_watchlist(companies, industry_names, as_of_iso):
    """
    companies: [{company_code, company_name, industry, official_industry, data_ym, rev_cur, rev_mom, rev_yoy, cum_yoy,
                 pe, pb, dy, foreign, itc, dealer, close, insti_trade_date}]
    回傳 entry 清單 (已依類別與排序規則截取)。
    """
    pe_med = industry_pe_medians(companies)
    uni = sorted((c for c in companies if _num(c.get("rev_cur")) and _num(c.get("close"))),
                 key=lambda c: -_num(c["rev_cur"]))[:UNIVERSE_SIZE]
    buckets = {k: [] for k in CATEGORIES}
    for c in uni:
        cat = categorize(c)
        if cat:
            buckets[cat].append(c)
    out = []
    for cat in CATEGORIES:
        rows = buckets[cat]
        if cat == "基本面或風險不佳":
            rows.sort(key=lambda c: _num(c["rev_yoy"]))                       # 最差的在前
        else:
            rows.sort(key=lambda c: -(_num(c["rev_yoy"]) or 0.0))             # 營收年增最高的在前
        for c in rows[:PER_CATEGORY]:
            out.append(build_entry(c, cat, industry_names.get(c["industry"], c["industry"]), pe_med.get(c["industry"]), as_of_iso))
    return out


def apply_live_watchlist(conn=None):
    """以即時資料重建 company_research_watchlist (取代手寫種子)。資料不足時完全不動。回傳摘要 dict。"""
    from db import get_connection
    from live_scoring import _date_expr

    own = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT l.company_code, l.company_name, l.mapped_industry_id AS industry, l.official_industry, l.data_ym,
                   l.rev_current_thousand AS rev_cur, l.rev_mom_pct AS rev_mom, l.rev_yoy_pct AS rev_yoy,
                   l.cum_rev_yoy_pct AS cum_yoy, l.pe_ratio AS pe, l.pb_ratio AS pb, l.dividend_yield AS dy,
                   l.foreign_net_shares AS "foreign", l.itc_net_shares AS itc, l.dealer_net_shares AS dealer,
                   l.insti_trade_date, q.close_price AS close
            FROM live_company_fundamentals l
            LEFT JOIN live_stock_quotes q ON q.company_code = l.company_code AND q.trade_date = {_date_expr()}
            WHERE l.mapped_industry_id IS NOT NULL
              AND l.data_ym = (SELECT MAX(x.data_ym) FROM live_company_fundamentals x WHERE x.company_code = l.company_code)
        """)
        companies = [dict(r) for r in cur.fetchall()]
        if not companies:
            return {"applied": False, "reason": "沒有即時公司資料"}
        cur.execute("SELECT industry_id, industry_name FROM industry_taxonomy")
        names = {r["industry_id"]: r["industry_name"] for r in cur.fetchall()}
        as_of = max((c["insti_trade_date"] for c in companies if c.get("insti_trade_date")), default="") or ""
        as_of_iso = f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}" if len(as_of) == 8 else ""
        entries = select_watchlist(companies, names, as_of_iso)
        if len(entries) < MIN_ROWS_TO_REPLACE:
            return {"applied": False, "reason": f"篩出 {len(entries)} 檔 (< {MIN_ROWS_TO_REPLACE})，保留原名單"}
        cur.execute("DELETE FROM company_research_watchlist")
        cur.executemany("""
            INSERT INTO company_research_watchlist
            (ticker, company_name, industry_id, watchlist_category, supply_chain_position, latest_rev_period,
             latest_rev_billion_twd, rev_mom_pct, rev_yoy_pct, eps_ttm_or_est, pe_ratio_status, institutional_ownership_trend,
             bull_case, bear_case, valuation_risk, invalidation_condition, as_of_date, source_id, text_source)
            VALUES (:ticker, :company_name, :industry_id, :watchlist_category, :supply_chain_position, :latest_rev_period,
                    :latest_rev_billion_twd, :rev_mom_pct, :rev_yoy_pct, :eps_ttm_or_est, :pe_ratio_status, :institutional_ownership_trend,
                    :bull_case, :bear_case, :valuation_risk, :invalidation_condition, :as_of_date, :source_id, 'live')
        """, entries)
        conn.commit()
        counts = {c: sum(1 for e in entries if e["watchlist_category"] == c) for c in CATEGORIES}
        return {"applied": True, "rows": len(entries), "by_category": counts}
    finally:
        if own:
            conn.close()
