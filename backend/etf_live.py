"""
ETF 決策中心 (台股部分) 的即時化：由官方逐日行情算出風險報酬指標，並用公式重算雙軌評分，取代手寫分數與敘述。

原本的 etf_engine.py 裡，每檔 ETF 的 10 個子分數、結論、優勢、風險、支持／反方證據都是手寫常數；
台股 ETF 的 trade_date 也寫死成 2026-11-20、淨值是用手寫折溢價反推出來的假值。這裡改成 (只處理台股掛牌的 ETF，
美股 ETF 沒有官方資料來源，維持原樣並標示為手寫)：

資料 (官方)：證交所 STOCK_DAY／櫃買 tradingStock 逐日行情、FMTQIK 加權指數逐日、既有的 0099P 買賣價差、T86／櫃買三大法人買賣超、ETFRank 定期定額戶數。
仍是人工維護、不會假裝即時的欄位：基金規模、費用率、追蹤誤差 (etf_master)、前十大持股與權重 (etf_holdings)、
配息來源拆解。沒有官方來源因而一律留空 (N/A) 的欄位：淨值與折溢價、配息率、含息報酬 (1/3/5 年)、初級市場申贖淨額。

模型 A (長期配置)  權重 25/20/20/20/15：底層品質、分散度、估值與風險報酬、成本與流動性、互補性
模型 B (短中期進場) 權重 20 × 5：大盤環境、資金流向、價格趨勢、估值與價位、波動與下行
子分數用固定的分段線性函式 (見 lin() 與各 *_score 函式的常數) 映射到 15~95 分；缺資料的子分數以 50 分代入並降低可信度。
價格報酬不含息 (高股息 ETF 的價格報酬因除息而被低估)，畫面與文字都會標明。

純函式在檔案前半，資料庫存取在 apply_live_etf。
"""
import json
import math
import statistics

from live_pulse import to_iso_date

TRADING_DAYS = 252
LOOKBACK = {"ret_1m": 21, "ret_3m": 63, "ret_6m": 126, "ret_1y": 252}
MIN_DAYS_FOR_VOL = 40
MIN_OVERLAP = 40
CORE_ETFS = ("0050", "006208")
KEEP_REPORTS = 5

A_WEIGHTS = {"a1": 0.25, "a2": 0.20, "a3": 0.20, "a4": 0.20, "a5": 0.15}
B_KEYS = ("b1", "b2", "b3", "b4", "b5")
LABELS = {"a1": "底層資產品質", "a2": "分散度", "a3": "估值與風險報酬", "a4": "成本與流動性", "a5": "互補性",
          "b1": "大盤環境", "b2": "資金流向", "b3": "價格趨勢", "b4": "估值與價位", "b5": "波動與下行"}
NO_SOURCE_NOTE = ("無官方即時來源而留空：淨值與折溢價、配息率、含息報酬 (1/3/5 年)、初級市場申贖淨額、ROE、債券存續期與信評。"
                  "規模、費用率、追蹤誤差與持股權重是人工維護 (非即時)。")


def lin(x, x0, y0, x1, y1):
    """分段線性：x 在 [x0, x1] 之間線性對應到 [y0, y1]，範圍外取端點。x 為 None 回傳 None。"""
    if x is None:
        return None
    if x0 == x1:
        return y0
    t = (x - x0) / (x1 - x0)
    t = max(0.0, min(1.0, t))
    return round(y0 + (y1 - y0) * t, 1)


def _avg(*xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _sg(x, nd=1, unit=""):
    return "N/A" if x is None else f"{x:+,.{nd}f}{unit}"


# ---------------------------------------------------------------------------
# 指標 (純函式)
# ---------------------------------------------------------------------------
def _returns(closes):
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]


SPLIT_JUMP = 0.35     # 單日變動超過 35% 視為分割 / 合併 / 資料斷層 (ETF 有漲跌幅限制，真實行情不可能單日 -35%；槓桿型 2 倍最多約 ±20%)


def continuous_segment(series, jump=SPLIT_JUMP):
    """
    回傳 (最後一段連續的行情, 斷層日期或 None)。價格在分割或合併當天會出現巨大落差 (例如 245 → 35)，那不是下跌；
    若把它當成報酬，波動度、最大回撤與報酬全部失真。這裡保守地只使用「最後一個斷層之後」的資料。
    """
    cut, when = 0, None
    for i in range(1, len(series)):
        prev, cur = series[i - 1][1], series[i][1]
        if prev and cur and abs(cur / prev - 1) > jump:
            cut, when = i, series[i][0]
    return series[cut:], when


def compute_metrics(series):
    """
    series: [(ISO 日期, 收盤, 成交股數, 成交金額)] 依日期遞增。回傳指標 dict；資料不足的指標為 None。
    報酬是價格報酬 (不含息)。
    """
    series, split_break = continuous_segment(series)
    n = len(series)
    if n == 0:
        return {"history_days": 0}
    dates = [s[0] for s in series]
    closes = [s[1] for s in series]
    last = closes[-1]
    m = {"history_days": n, "split_break": split_break, "last_date": dates[-1], "last_close": last,
         "change_pct": round((last / closes[-2] - 1) * 100, 2) if n >= 2 and closes[-2] else None,
         "volume_shares": series[-1][2], "turnover_twd": series[-1][3]}
    for key, k in LOOKBACK.items():
        m[key] = round((last / closes[-1 - k] - 1) * 100, 2) if n > k and closes[-1 - k] else None
    win = closes[-TRADING_DAYS:]
    rets = _returns(win)
    m["vol_ann"] = round(statistics.pstdev(rets) * math.sqrt(TRADING_DAYS) * 100, 2) if len(rets) >= MIN_DAYS_FOR_VOL else None
    peak, mdd = win[0], 0.0
    for c in win:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    m["mdd"] = round(mdd * 100, 2) if len(win) >= MIN_DAYS_FOR_VOL else None
    hi, lo = max(win), min(win)
    m["dd_from_high"] = round((last / hi - 1) * 100, 2)
    m["pos_1y"] = round((last - lo) / (hi - lo), 3) if hi > lo and len(win) >= MIN_DAYS_FOR_VOL else None
    m["window_days"] = len(win)
    # 畫圖用的降採樣價格曲線：最近 (最多) 一年，約 52 個點 (含最後一天)；日期與收盤皆為官方逐日行情
    tail = series[-TRADING_DAYS:]
    step = max(1, -(-len(tail) // 52))            # 向上取整，使點數 ≤ 約 52
    pts = tail[::step]
    if pts[-1][0] != tail[-1][0]:
        pts = pts + [tail[-1]]
    m["curve"] = [[d, c] for d, c, _v, _t in pts]
    m["ma20"] = round(sum(closes[-20:]) / 20, 3) if n >= 20 else None
    m["ma60"] = round(sum(closes[-60:]) / 60, 3) if n >= 60 else None
    m["vs_ma60_pct"] = round((last / m["ma60"] - 1) * 100, 2) if m["ma60"] else None
    t20 = [s[3] for s in series[-20:] if s[3]]
    m["turnover_20d_billion"] = round(sum(t20) / len(t20) / 1e8, 2) if len(t20) >= 10 else None
    return m


def beta_corr(asset, bench, min_overlap=MIN_OVERLAP):
    """asset / bench: [(日期, 收盤)]。以共同日期的日報酬計算 (beta, 相關係數)；樣本不足回傳 (None, None)。"""
    a, b = dict(asset), dict(bench)
    days = sorted(set(a) & set(b))[-TRADING_DAYS:]
    ra = [a[days[i]] / a[days[i - 1]] - 1 for i in range(1, len(days)) if a[days[i - 1]]]
    rb = [b[days[i]] / b[days[i - 1]] - 1 for i in range(1, len(days)) if b[days[i - 1]]]
    k = min(len(ra), len(rb))
    if k < min_overlap:
        return None, None
    ra, rb = ra[-k:], rb[-k:]
    ma, mb = sum(ra) / k, sum(rb) / k
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / k
    va, vb = sum((x - ma) ** 2 for x in ra) / k, sum((y - mb) ** 2 for y in rb) / k
    if va <= 0 or vb <= 0:
        return None, None
    return round(cov / vb, 2), round(cov / math.sqrt(va * vb), 3)


# ---------------------------------------------------------------------------
# 評分 (純函式)
# ---------------------------------------------------------------------------
def score_model(etf, m, taiex, corr_core):
    """
    etf: 輸入 dict：asset_class, is_leveraged (bool), ter, tracking_error, spread_bps, weighted_pe, weighted_yoy,
         top10, max_single, insti_ratio_pct (外資+投信買賣金額 ÷ 成交金額，%)。
    m: compute_metrics 的輸出；taiex: 加權指數的 compute_metrics；corr_core: 與 0050 的日報酬相關係數 (或 None)。
    回傳 {"a": {a1..a5}, "b": {b1..b5}, "missing": [...], "facts": {key: 說明}}。
    """
    r1y, vol, mdd = m.get("ret_1y"), m.get("vol_ann"), m.get("mdd")
    ratio = (r1y / vol) if (r1y is not None and vol) else None
    equity = str(etf.get("asset_class") or "") in ("股票", "equity", "Equity") or etf.get("equity", False)
    a = {
        "a1": lin(etf.get("weighted_yoy"), 0, 40, 60, 92),
        "a2": _avg(lin(etf.get("max_single"), 5, 95, 60, 20), lin(etf.get("top10"), 20, 95, 95, 25)),
        "a3": _avg(lin(etf.get("weighted_pe"), 10, 90, 35, 35), lin(ratio, -0.5, 20, 2.0, 92), lin(mdd, -5, 92, -30, 20)),
        "a4": _avg(lin(etf.get("ter"), 0.1, 95, 1.2, 25), lin(etf.get("spread_bps"), 3, 95, 40, 35),
                   lin(m.get("turnover_20d_billion"), 0.3, 40, 30, 95), lin(etf.get("tracking_error"), 0.05, 95, 1.0, 35)),
        "a5": None if etf.get("code") in CORE_ETFS else lin(corr_core, 1.0, 25, 0.2, 95),
    }
    mkt = (taiex or {})
    b = {
        "b1": _avg(lin(mkt.get("vs_ma60_pct"), -8, 20, 8, 90), lin(mkt.get("vol_20d"), 12, 90, 45, 15)) if equity else None,
        "b2": lin(etf.get("insti_ratio_pct"), -8, 20, 8, 90),
        "b3": _avg(lin(m.get("ret_1m"), -8, 20, 8, 90), lin(m.get("ret_3m"), -15, 20, 15, 90)),
        "b4": _avg(lin(m.get("pos_1y"), 0, 90, 1, 25), lin(etf.get("weighted_pe"), 10, 90, 35, 35)),
        "b5": _avg(lin(vol, 8, 90, 45, 15), lin(m.get("dd_from_high"), 0, 92, -20, 22)),
    }
    missing = [k for k, v in {**a, **b}.items() if v is None]
    a = {k: (50.0 if v is None else v) for k, v in a.items()}
    b = {k: (50.0 if v is None else v) for k, v in b.items()}
    return {"a": a, "b": b, "missing": missing}


def totals(scores):
    ta = round(sum(scores["a"][k] * w for k, w in A_WEIGHTS.items()), 2)
    tb = round(sum(scores["b"][k] for k in B_KEYS) * 0.20, 2)
    return ta, tb


def conclusion_a(total, etf, missing):
    if etf.get("is_leveraged"):
        return "不符合配置角色"
    if sum(1 for k in missing if k.startswith("a")) >= 3:
        return "資料不足，暫不評分"
    if (etf.get("max_single") or 0) >= 40 and total >= 70:
        return "需注意集中風險"
    return "適合進一步研究" if total >= 75 else "條件普通"


def conclusion_b(total, etf, missing):
    if etf.get("is_leveraged"):
        return "風險偏高"
    if sum(1 for k in missing if k.startswith("b")) >= 4:
        return "資料不足，暫不評分"
    return "條件相對有利" if total >= 75 else "持續觀察" if total >= 60 else "等待更佳條件" if total >= 45 else "風險偏高"


def credibility(m, missing):
    n = m.get("history_days", 0)
    if len(missing) <= 2 and n >= 200:
        return "A"
    if len(missing) <= 4 and n >= 60:
        return "B"
    return "C"


def divergence_tag(etf, ca, cb, ta, tb):
    if etf.get("is_leveraged"):
        return "槓桿耗損僅供極短線交易"
    if "資料不足" in ca or "資料不足" in cb:
        return "資料不足，雙軌訊號僅供參考"
    if ta >= 75 and tb >= 75:
        return "長短線雙重順風"
    if ta >= 75 and tb < 60:
        return "長線條件佳惟短線等待更佳條件"
    if ta < 60 and tb >= 75:
        return "短線條件佳惟長線條件普通"
    return "長短線訊號中性或分歧"


def facts_for(etf, m, taiex, corr_core, corr_taiex, beta):
    return {
        "a1": f"底層成分股加權營收年增 {_sg(etf.get('weighted_yoy'), 1, '%')}（持股權重為人工維護）",
        "a2": f"最大單一持股 {_sg(etf.get('max_single'), 1, '%').lstrip('+')}、前十大 {_sg(etf.get('top10'), 1, '%').lstrip('+')}（人工維護）",
        "a3": f"加權本益比 {('%.1f 倍' % etf['weighted_pe']) if etf.get('weighted_pe') else 'N/A'}、近 1 年價格報酬 {_sg(m.get('ret_1y'), 1, '%')}、波動度 {_sg(m.get('vol_ann'), 1, '%').lstrip('+')}、最大回撤 {_sg(m.get('mdd'), 1, '%')}",
        "a4": f"總費用率 {('%.3f%%' % etf['ter']) if etf.get('ter') is not None else 'N/A'}（人工維護）、買賣價差 {('%.1f bps' % etf['spread_bps']) if etf.get('spread_bps') is not None else 'N/A'}、20 日均成交值 {('%.2f 億元' % m['turnover_20d_billion']) if m.get('turnover_20d_billion') else 'N/A'}",
        "a5": ("核心配置，不評互補性" if etf.get("code") in CORE_ETFS else f"與 0050 日報酬相關係數 {('%.2f' % corr_core) if corr_core is not None else 'N/A'}"),
        "b1": f"加權指數相對 60 日均線 {_sg((taiex or {}).get('vs_ma60_pct'), 1, '%')}、近 20 日波動度 {_sg((taiex or {}).get('vol_20d'), 1, '%').lstrip('+')}",
        "b2": f"外資+投信當日淨買賣占成交金額 {_sg(etf.get('insti_ratio_pct'), 2, '%')}",
        "b3": f"近 1 月 {_sg(m.get('ret_1m'), 1, '%')}、近 3 月 {_sg(m.get('ret_3m'), 1, '%')}（價格報酬）",
        "b4": f"價格位於近 1 年區間的 {('%.0f%%' % (m['pos_1y'] * 100)) if m.get('pos_1y') is not None else 'N/A'}",
        "b5": f"波動度 {_sg(m.get('vol_ann'), 1, '%').lstrip('+')}、距 1 年高點 {_sg(m.get('dd_from_high'), 1, '%')}、Beta {('%.2f' % beta) if beta is not None else 'N/A'}",
    }


def build_texts(etf, m, taiex, scores, facts, ca, cb, ta, tb):
    allk = {**scores["a"], **scores["b"]}
    real = [k for k in allk if k not in scores["missing"]]
    ranked = sorted(real, key=lambda k: allk[k], reverse=True)
    best, worst = ranked[:3], ranked[-3:][::-1]
    line = lambda ks: "；".join(f"{LABELS[k]} {allk[k]:.0f} 分（{facts[k]}）" for k in ks)   # noqa: E731
    advantage = f"{LABELS[best[0]]} {allk[best[0]]:.0f} 分：{facts[best[0]]}" if best else "資料不足，無法判斷"
    risk = f"{LABELS[worst[0]]} {allk[worst[0]]:.0f} 分：{facts[worst[0]]}" if worst else "資料不足，無法判斷"
    contra = []
    if abs(ta - tb) >= 15:
        contra.append(f"長期配置分數 {ta:.1f} 與短中期分數 {tb:.1f} 相差 {abs(ta - tb):.0f} 分，兩個模型的結論方向不同，不可混為單一分數。")
    r1m, ins = m.get("ret_1m"), etf.get("insti_ratio_pct")
    if r1m is not None and ins is not None and r1m > 3 and ins < -1:
        contra.append(f"近 1 月價格 {_sg(r1m, 1, '%')} 上漲，但外資+投信當日淨賣出占成交金額 {_sg(ins, 2, '%')}，價格與法人方向相反。")
    if r1m is not None and ins is not None and r1m < -3 and ins > 1:
        contra.append(f"近 1 月價格 {_sg(r1m, 1, '%')} 下跌，但外資+投信當日淨買入占成交金額 {_sg(ins, 2, '%')}，價格與法人方向相反。")
    if etf.get("is_leveraged"):
        contra.append("槓桿型商品每日重設槓桿，長期持有有波動度耗損；本系統強制隔離於長期配置名單之外 (結構性風險，與當期數字無關)。")
    ma60 = m.get("ma60")
    invalid = []
    if ma60:
        invalid.append(f"價格跌破 60 日均線 {ma60:.2f} (目前 {m['last_close']:.2f})")
    invalid.append("外資+投信連續多日淨賣出且占成交金額低於 -3%")
    if (m.get("vol_ann") or 0) > 0:
        invalid.append(f"年化波動度由 {m['vol_ann']:.1f}% 明顯上升")
    watch = []
    if (taiex or {}).get("ma60"):
        watch.append(f"加權指數是否站穩 60 日均線 {taiex['ma60']:,.0f}（目前 {taiex['last_close']:,.0f}）")
    watch.append("外資+投信買賣金額占成交金額是否轉正")
    watch.append("下次 ETFRank 公布的定期定額戶數是否增加")
    return {
        "top_advantage": advantage, "top_risk": risk,
        "supporting_evidence": f"相對強項：{line(best)}。" if best else "資料不足。",
        "counter_evidence": f"相對弱項：{line(worst)}。" if worst else "資料不足。",
        "contradiction_notes": " ".join(contra) or "沒有偵測到互相矛盾的指標 (不代表沒有風險)。",
        "invalidation_conditions": "；".join(invalid) + "，即時分數會下降。",
        "next_watch_indicator": "；".join(watch) + "。",
    }


# ---------------------------------------------------------------------------
# 每日報告 (純函式)
# ---------------------------------------------------------------------------
def _turnover_txt(r):
    return f"{r['m']['turnover_twd'] / 1e8:,.1f} 億元"


def build_daily_report(rows, taiex, now_iso):
    """
    rows: [{code, name, m (指標), insti_billion, insti_ratio_pct, tb, ta, leveraged}]；taiex: 加權指數指標。
    回傳 etf_research_reports 的 dict；沒有資料回傳 None。
    """
    rows = [r for r in rows if r["m"].get("last_date")]
    if not rows:
        return None
    d = max(r["m"]["last_date"] for r in rows)
    today = [r for r in rows if r["m"]["last_date"] == d and r["m"].get("change_pct") is not None]
    up = sum(1 for r in today if r["m"]["change_pct"] > 0)
    down = sum(1 for r in today if r["m"]["change_pct"] < 0)
    gain = sorted(today, key=lambda r: -r["m"]["change_pct"])[:3]
    loss = sorted(today, key=lambda r: r["m"]["change_pct"])[:3]
    fmt = lambda rs, f: "、".join(f"{r['code']} {r['name']}（{f(r)}）" for r in rs) or "無"   # noqa: E731
    pct = lambda r: _sg(r["m"]["change_pct"], 2, "%")   # noqa: E731
    mk = (f"加權指數 {taiex['last_close']:,.2f}，當日 {_sg(taiex.get('change_pct'), 2, '%')}。" if taiex and taiex.get("last_close") else "")
    q1 = (f"{d} 台股掛牌 {len(rows)} 檔 ETF 中，{up} 檔上漲、{down} 檔下跌。{mk}漲幅最大：{fmt(gain, pct)}；跌幅最大：{fmt(loss, pct)}。")
    tot_t = sum((r["m"].get("turnover_twd") or 0) for r in today) / 1e8
    top_t = sorted(today, key=lambda r: -(r["m"].get("turnover_twd") or 0))[:3]
    ins = [r for r in today if r.get("insti_billion") is not None]
    buy = sorted((r for r in ins if r["insti_billion"] > 0), key=lambda r: -r["insti_billion"])[:3]
    sell = sorted((r for r in ins if r["insti_billion"] < 0), key=lambda r: r["insti_billion"])[:3]
    q2 = (f"成交金額合計約 {tot_t:,.1f} 億元，最大：{fmt(top_t, _turnover_txt)}。"
          f"外資+投信淨買超最多：{fmt(buy, lambda r: _sg(r['insti_billion'], 2, ' 億'))}；淨賣超最多：{fmt(sell, lambda r: _sg(r['insti_billion'], 2, ' 億'))}。")
    big = [r for r in today if abs(r["m"]["change_pct"]) >= 1.0]
    q3 = ("單日漲跌幅達 1% 以上：" + fmt(big, pct) + "。") if big else "當日沒有 ETF 單日漲跌幅達 1% 以上。"
    scored = [r for r in rows if r.get("tb") is not None and not r.get("leveraged")]
    best = sorted(scored, key=lambda r: -r["tb"])[:3]
    worst = sorted(scored, key=lambda r: r["tb"])[:3]
    q4 = "短中期環境分數最高（模型 B，不含槓桿型）：" + fmt(best, lambda r: f"{r['tb']:.1f} 分") + "。"
    lev = [r for r in rows if r.get("leveraged")]
    q5 = ("短中期環境分數最低：" + fmt(worst, lambda r: f"{r['tb']:.1f} 分") + "。"
          + ("槓桿／反向型 " + "、".join(r["code"] for r in lev) + " 有每日重設的波動度耗損，單日波動大屬結構性風險。" if lev else ""))
    watch = []
    if taiex and taiex.get("ma60"):
        watch.append(f"加權指數是否站穩 60 日均線 {taiex['ma60']:,.0f}（目前 {taiex['last_close']:,.0f}）")
    watch.append("外資+投信買賣金額占成交金額是否轉正")
    q6 = "；".join(f"{i + 1}. {w}" for i, w in enumerate(watch)) + "。"
    q7 = ("若加權指數收盤跌破 60 日均線、或外資+投信連續多日對市值型 ETF 淨賣出，上述短中期判斷失效。" if watch else "資料不足以設定失效條件。")
    return {
        "etf_report_id": f"ETF_RPT_LIVE_DAILY_{d.replace('-', '')}", "report_type": "每日報告",
        "report_title": f"【台股 ETF 即時日報】{d}", "as_of_date": f"{d} 盤後 (台股掛牌 ETF；美股 ETF 無官方來源，不在本報告)",
        "q1_what_happened": q1, "q2_supporting_data": q2, "q3_affected_etfs": q3, "q4_positive_impacts": q4,
        "q5_negative_impacts": q5, "q6_next_watch": q6, "q7_invalidation": q7,
        "primary_sources": "證交所 STOCK_DAY／FMTQIK、櫃買 tradingStock、證交所與櫃買三大法人買賣超 (官方 OpenAPI)；本報告由機械式規則產生，不是分析師撰寫",
        "version_tag": f"live-ETF-D-{d}",
    }


# ---------------------------------------------------------------------------
# 資料庫存取
# ---------------------------------------------------------------------------
def _series(cur, code):
    return [(r["trade_date"], r["close_price"], r["volume_shares"], r["turnover_twd"]) for r in
            cur.execute("SELECT * FROM etf_price_history WHERE etf_code = ? ORDER BY trade_date", (code,))]


def _taiex_metrics(cur):
    idx = [(r["trade_date"], r["close_index"]) for r in cur.execute(
        "SELECT * FROM index_price_history WHERE index_name = '發行量加權股價指數' ORDER BY trade_date")]
    if not idx:
        return None, []
    closes = [c for _d, c in idx]
    m = compute_metrics([(d, c, None, None) for d, c in idx])
    r20 = _returns(closes[-21:])
    m["vol_20d"] = round(statistics.pstdev(r20) * math.sqrt(TRADING_DAYS) * 100, 2) if len(r20) >= 15 else None
    return m, idx


def apply_live_etf(conn=None, today=None, backfill_requests=None):
    """補抓／回補歷史行情 → 計算指標 → 更新台股 ETF 的每日指標、雙軌評分與即時日報。沒有歷史資料時完全不動。"""
    from db import get_connection
    from common import now_iso
    import etf_live_data as ed

    own = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.cursor()
        bf = None
        if backfill_requests != 0:
            kw = {"max_requests": backfill_requests} if backfill_requests else {}
            bf = ed.backfill(conn, today=today, **kw)
        codes = ed.tw_etf_codes(conn)
        taiex, idx_series = _taiex_metrics(cur)
        series = {c: _series(cur, c) for c in codes}
        series = {c: s for c, s in series.items() if s}
        if not series:
            return {"applied": False, "reason": "沒有 ETF 歷史行情", "backfill": bf}
        core = [(d, c) for d, c, _v, _t in series.get("0050", [])]
        now = now_iso()
        rows_for_report, n = [], 0
        for code, s in series.items():
            m = compute_metrics(s)
            asset = [(d, c) for d, c, _v, _t in continuous_segment(s)[0]]
            beta, corr_taiex = beta_corr(asset, idx_series)
            corr_core = beta_corr(asset, core)[1] if code != "0050" and core else None
            market = cur.execute("SELECT market FROM etf_price_history WHERE etf_code = ? LIMIT 1", (code,)).fetchone()["market"]
            mst = cur.execute("SELECT * FROM etf_master WHERE etf_code = ?", (code,)).fetchone()
            dm = cur.execute("SELECT * FROM etf_daily_metrics WHERE etf_code = ?", (code,)).fetchone()
            al = cur.execute("SELECT * FROM etf_allocation_summary WHERE etf_code = ?", (code,)).fetchone()
            if not mst:
                continue
            f_sh = (dm["foreign_net_shares"] if dm else None)
            i_sh = (dm["itc_net_shares"] if dm else None)
            turnover = m.get("turnover_twd") or 0
            insti_val = ((f_sh or 0) + (i_sh or 0)) * m["last_close"] / 1e8 if (dm and f_sh is not None and i_sh is not None) else None
            etf = {"code": code, "asset_class": mst["asset_class"], "equity": mst["asset_class"] == "股票",
                   "is_leveraged": bool(mst["is_leveraged_or_inverse"]), "ter": mst["total_expense_ratio_pct"],
                   "tracking_error": mst["tracking_error_pct"],
                   "spread_bps": dm["bid_ask_spread_bps"] if (dm and market == "TWSE") else None,
                   "weighted_pe": dm["weighted_pe"] if dm else None, "weighted_yoy": dm["weighted_rev_yoy_pct"] if dm else None,
                   "top10": al["top10_concentration_pct"] if al else None, "max_single": al["max_single_weight_pct"] if al else None,
                   "insti_ratio_pct": round(insti_val * 1e8 / turnover * 100, 3) if (insti_val is not None and turnover) else None}
            prev_type = cur.execute("SELECT eval_methodology_type FROM etf_dual_scores WHERE etf_code = ?", (code,)).fetchone()
            sc = score_model(etf, m, taiex, corr_core)
            ta, tb = totals(sc)
            ca, cb = conclusion_a(ta, etf, sc["missing"]), conclusion_b(tb, etf, sc["missing"])
            facts = facts_for(etf, m, taiex, corr_core, corr_taiex, beta)
            tx = build_texts(etf, m, taiex, sc, facts, ca, cb, ta, tb)
            missing_pct = round(len(sc["missing"]) / 10 * 100, 1)
            full = dict(m, beta=beta, corr_taiex=corr_taiex, corr_0050=corr_core, insti_billion=None if insti_val is None else round(insti_val, 3),
                        insti_ratio_pct=etf["insti_ratio_pct"], facts=facts, missing=sc["missing"])
            cur.execute("INSERT OR REPLACE INTO etf_live_metrics VALUES (?,?,?)", (code, m["last_date"], json.dumps(full, ensure_ascii=False)))
            # 每次排程 ETF 引擎都會以寫死的日期重新插入一列 (本次抓到的最新行情與法人資料)，而上次即時更新已把舊列改成真實日期，
            # 所以同一檔 ETF 會有兩列；唯一鍵是 (代號, 日期)，兩列同時改成同一天就會撞鍵 (實際在雲端遇過)。只留最新插入的一列。
            cur.execute("""DELETE FROM etf_daily_metrics WHERE etf_code = ?
                           AND rowid NOT IN (SELECT MAX(rowid) FROM etf_daily_metrics WHERE etf_code = ?)""", (code, code))
            cur.execute("""
                UPDATE etf_daily_metrics SET trade_date = ?, close_price = ?, change_pct = ?, volume_shares = ?, turnover_value = ?,
                    nav_price = NULL, premium_discount_pct = NULL, primary_net_flow_value = NULL, dividend_yield_pct = NULL,
                    return_1y_total_pct = NULL, return_3y_ann_pct = NULL, return_5y_ann_pct = NULL, twd_adjusted_1y_return_pct = NULL,
                    return_price_only_1y_pct = ?, annualized_volatility_pct = ?, max_drawdown_pct = ?, beta_vs_market = ?,
                    corr_tw_stock = ?, weighted_roe_pct = NULL, missing_fields_note = ?, metrics_source = 'live'
                WHERE etf_code = ?
            """, (m["last_date"], m["last_close"], m["change_pct"], m["volume_shares"], m["turnover_twd"], m["ret_1y"], m["vol_ann"], m["mdd"],
                  beta, corr_taiex, NO_SOURCE_NOTE, code))
            if market != "TWSE":      # 上櫃 ETF：沒有買賣價差的官方來源，不沿用手寫值
                cur.execute("UPDATE etf_daily_metrics SET bid_price = NULL, ask_price = NULL, bid_ask_spread_bps = NULL WHERE etf_code = ?", (code,))
            cur.execute("""
                INSERT OR REPLACE INTO etf_dual_scores
                (etf_code, as_of_date, model_version, eval_methodology_type,
                 score_a_underlying_quality, score_a_diversification_role, score_a_long_valuation_rr, score_a_cost_liquidity_track,
                 score_a_complementarity, total_score_a_long_term, conclusion_a_long_term,
                 score_b_macro_environment, score_b_flow_and_breadth, score_b_trend_and_momentum, score_b_valuation_and_pos,
                 score_b_vol_event_downside, total_score_b_short_mid, conclusion_b_short_mid,
                 divergence_tag, top_advantage, top_risk, supporting_evidence, counter_evidence, contradiction_notes,
                 invalidation_conditions, next_watch_indicator, credibility_grade, missing_data_pct, score_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'live')
            """, (code, m["last_date"], "ETF_LIVE_v1", prev_type["eval_methodology_type"] if prev_type else mst["sub_category"],
                  sc["a"]["a1"], sc["a"]["a2"], sc["a"]["a3"], sc["a"]["a4"], sc["a"]["a5"], ta, ca,
                  sc["b"]["b1"], sc["b"]["b2"], sc["b"]["b3"], sc["b"]["b4"], sc["b"]["b5"], tb, cb,
                  divergence_tag(etf, ca, cb, ta, tb), tx["top_advantage"], tx["top_risk"], tx["supporting_evidence"], tx["counter_evidence"],
                  tx["contradiction_notes"], tx["invalidation_conditions"], tx["next_watch_indicator"], credibility(m, sc["missing"]), missing_pct))
            # 前瞻追蹤用的快照：記下「當時」的分數與結論；同一資料日重跑則覆寫 (同一天只留一筆)
            cur.execute("""INSERT OR REPLACE INTO etf_score_history
                           (etf_code, snapshot_date, score_a, score_b, conclusion_a, conclusion_b, is_leveraged, missing_count, created_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (code, m["last_date"], ta, tb, ca, cb, 1 if etf["is_leveraged"] else 0, len(sc["missing"]), now))
            rows_for_report.append({"code": code, "name": mst["etf_name"], "m": m, "insti_billion": full["insti_billion"],
                                    "insti_ratio_pct": etf["insti_ratio_pct"], "ta": ta, "tb": tb, "leveraged": etf["is_leveraged"]})
            n += 1
        rep = build_daily_report(rows_for_report, taiex, now)
        if rep:
            cur.execute("DELETE FROM etf_research_reports WHERE report_type = '每日報告' AND text_source = 'seed'")
            cur.execute("""
                INSERT OR REPLACE INTO etf_research_reports
                (etf_report_id, report_type, report_title, as_of_date, q1_what_happened, q2_supporting_data, q3_affected_etfs,
                 q4_positive_impacts, q5_negative_impacts, q6_next_watch, q7_invalidation, primary_sources, version_tag, text_source)
                VALUES (:etf_report_id, :report_type, :report_title, :as_of_date, :q1_what_happened, :q2_supporting_data, :q3_affected_etfs,
                        :q4_positive_impacts, :q5_negative_impacts, :q6_next_watch, :q7_invalidation, :primary_sources, :version_tag, 'live')
            """, rep)
            cur.execute("""DELETE FROM etf_research_reports WHERE text_source = 'live' AND report_type = '每日報告' AND etf_report_id NOT IN
                           (SELECT etf_report_id FROM etf_research_reports WHERE text_source = 'live' AND report_type = '每日報告'
                            ORDER BY etf_report_id DESC LIMIT ?)""", (KEEP_REPORTS,))
        conn.commit()
        return {"applied": True, "etfs": n, "backfill": bf, "report": rep["etf_report_id"] if rep else None}
    finally:
        if own:
            conn.close()
