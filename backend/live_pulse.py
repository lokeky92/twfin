"""
首頁「10 秒看懂台灣資金現況」六張摘要卡 (Q1~Q6) 的即時產生器。

只使用儀表板 payload 裡「真正即時」的欄位，不含任何手寫敘事：
  - institutional_flows  官方 BFI82U 三大法人逐日買賣超 (只取標示「官方API」的列，不用手寫的種子列)
  - live_indices         證交所大盤與類股指數 (近數個交易日)
  - industries[].live_agg 各產業由 MOPS 月營收、T86 / 櫃買三大法人彙總出的即時數字
  - live_top_companies   營收前 N 大公司的月營收年增、本益比、法人買賣超
  - live_summary         全市場月營收彙總
總體經濟 (央行、經濟部) 與融資、期貨未平倉仍是人工維護資料：只作為「背景」引用，並一律附上資料所屬期間，
不參與標題與排名判斷。

純函式、無資料庫依賴，方便單元測試。輸出會被放進 data.json 的 home_pulse 欄位。
"""
from html import escape

# 各區塊顏色 (沿用原本首頁卡片配色)
COLORS = ["#10b981", "#38bdf8", "#34d399", "#fb7185", "#a855f7", "#f59e0b"]
NEUTRAL = "#94a3b8"

# 判斷用門檻 (集中在這裡，改規則時一目了然)
WINDOW_DAYS = 5                    # 法人與指數的觀察窗：最近 5 個有資料的交易日
FOREIGN_SELL_ALERT_BILLION = -1000.0   # 外資窗內合計賣超達此值 (億元) 視為提款警訊
MARKET_DROP_ALERT_PCT = -3.0       # 大盤窗內累計跌幅達此值 (%) 視為回檔警訊
DAY_DROP_ALERT_PCT = -2.0          # 大盤單日跌幅達此值 (%) 視為急跌警訊
HEAT_WEIGHT_YOY = 0.6              # 產業即時熱度 = 0.6 × 營收年增排名 + 0.4 × 法人買超排名
HEAT_WEIGHT_INST = 0.4
MIN_INDUSTRY_COMPANIES = 3         # 產業即時彙總至少要有這麼多家公司才納入排名
EMERGING_MIN_YOY = 50.0            # Q5 篩選：單月營收年增
EMERGING_MIN_CUM_YOY = 30.0        # Q5 篩選：累計營收年增 (排除單月波動)
EMERGING_MAX_PE = 40.0             # Q5 篩選：本益比上限 (排除純題材高估值)

# 產業簡稱 (資料表裡的名稱太長，卡片放不下)
SHORT_NAMES = {
    "IND_SEMI_FOUNDRY": "半導體(晶圓代工/封裝)",
    "IND_AI_SERVER": "AI伺服器與連接",
    "IND_THERMAL": "散熱與機構件",
    "IND_SEMI_EQUIP": "半導體設備與測試",
    "IND_FIN_HOLDING": "金融(金控/銀行/保險)",
    "IND_CPO_NET": "CPO光通訊與網通",
    "IND_POWER_GREEN": "電力設備與綠能",
    "IND_IC_DESIGN": "IC設計與IP",
    "IND_SHIPPING": "航運與航空",
    "IND_PCB_ABF": "PCB與ABF載板",
    "IND_MACH_AUTO": "機械與車用零組件",
    "IND_CONSTRUCTION": "營建不動產",
    "IND_STEEL_PLASTIC": "鋼鐵塑化與化工",
    "IND_BIO_RETAIL": "生技/電信/觀光零售",
}

MARKET_INDEX = "發行量加權股價報酬指數"
STYLE_INDEXES = ["臺灣50報酬指數", "臺灣高股息報酬指數", "臺灣資訊科技股報酬指數"]


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _e(text):
    """所有進入 innerHTML 的動態文字 (公司名稱等來自官方 API) 一律跳脫。"""
    return escape(str(text), quote=False)


def _num(x, default=None):
    try:
        if x is None:
            return default
        v = float(x)
        if v != v:   # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def _fmt(x):
    """總經數字去掉浮點尾巴 (68.5398 → 68.54)。"""
    return f"{float(x):.5g}"


def _sgn(x, nd=1, unit=""):
    return f"{x:+,.{nd}f}{unit}"


def _lots(x):
    """股數 → 張 (1 張 = 1000 股)，帶正負號與千分位。"""
    return f"{x / 1000:+,.0f} 張"


def to_iso_date(value):
    """接受 '1151126' (民國)、'20261126'、'2026-11-26'，回傳 ISO 日期字串；無法解析回傳 None。"""
    s = str(value or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    if s.isdigit() and len(s) == 7:
        return f"{int(s[:3]) + 1911:04d}-{s[3:5]}-{s[5:7]}"
    if s.isdigit() and len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _md(iso):
    return iso[5:] if iso else "?"


def _ym_label(data_ym):
    """'11510' → '2026年10月'。"""
    s = str(data_ym or "")
    if s.isdigit() and len(s) >= 4:
        return f"{int(s[:-2]) + 1911}年{int(s[-2:])}月"
    return "最新月"


def _short(ind):
    return SHORT_NAMES.get(ind.get("industry_id")) or str(ind.get("industry_name") or ind.get("industry_id"))


def _pct_rank(values):
    """每個值在清單中的百分位 (0~1)，最小者 0、最大者 1；並列取平均名次。"""
    n = len(values)
    if n <= 1:
        return [0.5] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg / (n - 1)
        i = j + 1
    return ranks


def _card(idx, q, a, sub, q6, basis, color=None):
    return {
        "q": q, "a": a, "sub": sub, "color": color or COLORS[idx], "q6": q6, "basis": basis,
    }


def _no_data_card(idx, q, what):
    return _card(idx, q, "資料不足，暫無法判斷", f"{what}尚未取得足夠的即時資料，待下次排程同步後自動補上。",
                 ["目前沒有足夠的即時資料可以回答這個問題。", "—", "—", "—", "—", "等下一次排程同步完成後，這張卡會自動更新。"],
                 "資料來源：官方 OpenAPI（本項目前無資料）", NEUTRAL)


# ---------------------------------------------------------------------------
# 資料整理
# ---------------------------------------------------------------------------
def live_daily_flows(institutional_flows):
    """官方 BFI82U 逐日資料 (排除手寫的種子列)，同一天只留一筆，依日期由舊到新。"""
    by_date = {}
    for r in institutional_flows or []:
        if r.get("period_type") != "DAILY" or "官方API" not in str(r.get("period_label") or ""):
            continue
        d = to_iso_date(r.get("release_date"))
        tot, frg, itc = _num(r.get("total_3insti_billion")), _num(r.get("foreign_net_billion")), _num(r.get("itc_net_billion"))
        if d is None or tot is None or frg is None or itc is None:
            continue
        by_date[d] = {
            "date": d, "total": tot, "foreign": frg, "itc": itc,
            "dealer": round(tot - frg - itc, 2),
        }
    return [by_date[d] for d in sorted(by_date)]


def manual_market_stats(institutional_flows):
    """融資餘額與外資期貨未平倉是人工維護欄位：回傳「最近一筆有值」及其日期，只做背景引用。"""
    best = {}
    for key in ("margin_balance_billion", "foreign_futures_oi_contracts"):
        rows = [(to_iso_date(r.get("release_date")), _num(r.get(key))) for r in institutional_flows or []
                if r.get("period_type") == "DAILY" and _num(r.get(key)) is not None and to_iso_date(r.get("release_date"))]
        if rows:
            best[key] = max(rows)   # (最新日期, 數值)
    return best


def index_series(live_indices):
    """{指數名稱: [(ISO 日期, 收盤, 單日漲跌%), ...] 由舊到新}。"""
    out = {}
    for r in live_indices or []:
        d, close = to_iso_date(r.get("trade_date")), _num(r.get("close_index"))
        if d is None or close is None:
            continue
        out.setdefault(r.get("index_name"), {})[d] = (d, close, _num(r.get("change_pct")))
    return {name: [rows[d] for d in sorted(rows)] for name, rows in out.items()}


def window_return(series, days=WINDOW_DAYS):
    """
    最近 days 個資料日「每一天的漲跌」連乘後的累計報酬 (%)：以第一天收盤與其單日漲跌反推前一日收盤當基準，
    因此和 [from, to] 之間每一天的 change_pct 一致。沒有單日漲跌可反推時退回以第一天收盤為基準 (少算一天)。
    """
    rows = series[-days:] if series else []
    if not rows:
        return None
    first, last = rows[0], rows[-1]
    chg = first[2]
    if chg is not None and chg > -100.0 and first[1]:
        base, n = first[1] / (1 + chg / 100.0), len(rows)
    elif len(rows) >= 2 and first[1]:
        base, n = first[1], len(rows) - 1
    else:
        return None
    return {"pct": (last[1] / base - 1) * 100.0, "from": first[0], "to": last[0], "days": n}


def industry_live_table(industries):
    """
    各產業的即時排名表。
    - 模型模式：啟用版本的分數已由即時資料重算 (score_source == 'live') 時，直接用模型總分排名，
      這樣首頁摘要、熱度圖、排行榜、預警用的是同一組分數，不會互相矛盾。
    - 簡易模式 (只有種子分數的舊資料庫)：營收年增 + 法人買超張數的百分位加權。
    """
    rows = []
    for ind in industries or []:
        a = ind.get("live_agg") or {}
        yoy = _num(a.get("agg_yoy_pct"))
        frg, itc = _num(a.get("sum_foreign_shares")), _num(a.get("sum_itc_shares"))
        if yoy is None or frg is None or itc is None or (_num(a.get("company_count"), 0) < MIN_INDUSTRY_COMPANIES):
            continue
        rows.append({
            "id": ind.get("industry_id"), "name": _short(ind), "yoy": yoy,
            "foreign": frg, "itc": itc, "inst": frg + itc,
            "companies": int(a.get("company_count")), "pe": _num(a.get("avg_pe")),
            "model_score": _num(ind.get("total_weighted_score")), "model_asof": ind.get("as_of_date"),
            "live_scored": ind.get("score_source") == "live" and _num(ind.get("total_weighted_score")) is not None,
            "state": ind.get("rotation_state"),
            "inst_billion": _num((ind.get("live_metrics") or {}).get("inst_net_billion")),
        })
    scored = [r for r in rows if r["live_scored"]]
    if len(scored) >= 5:
        for r in scored:
            r["heat"] = round(r["model_score"], 1)
            r["mode"] = "model"
        scored.sort(key=lambda r: (-r["heat"], -r["yoy"]))
        return scored
    yr = _pct_rank([r["yoy"] for r in rows])
    ir = _pct_rank([r["inst"] for r in rows])
    for r, y, i in zip(rows, yr, ir):
        r["heat"] = round(100.0 * (HEAT_WEIGHT_YOY * y + HEAT_WEIGHT_INST * i), 1)
        r["mode"] = "heuristic"
    rows.sort(key=lambda r: (-r["heat"], -r["yoy"]))
    return rows


def _industry_phrase(r):
    inst = f"法人 {_sgn(r['inst_billion'], 1)} 億" if r.get("inst_billion") is not None else f"法人 {_lots(r['inst'])}"
    return f"{_e(r['name'])}（營收年增 {_sgn(r['yoy'], 1, '%')}、{inst}）"


# ---------------------------------------------------------------------------
# 六張卡
# ---------------------------------------------------------------------------
def _flow_window(flows):
    win = flows[-WINDOW_DAYS:]
    return {
        "rows": win, "n": len(win), "latest": win[-1],
        "total": sum(r["total"] for r in win), "foreign": sum(r["foreign"] for r in win),
        "itc": sum(r["itc"] for r in win), "dealer": sum(r["dealer"] for r in win),
    }


def _flow_day_list(win):
    return "、".join(f"{_md(r['date'])} {_sgn(r['total'], 0)}" for r in win["rows"])


def _macro_context(macro_latest):
    """背景：人工維護的總體指標，附上所屬期間，絕不當作即時數字。"""
    want = {"TW_DOM_BANK_DEPOSITS": "國銀存款", "TW_SEC_GIRO_BAL": "證券劃撥存款", "TW_FIVE_BANK_NEW_RATE": "五大銀行新放款利率"}
    parts = []
    for m in macro_latest or []:
        if m.get("metric_code") in want and _num(m.get("cleaned_value")) is not None:
            parts.append(f"{want[m['metric_code']]} {_fmt(m['cleaned_value'])}{m.get('unit') or ''}（{_e(m.get('period_covered'))}）")
    return "、".join(parts)


def _card_q1(d, flows, table, idx_series):
    q = "Q1. 現在台灣整體資金是增加還是減少？"
    if not flows:
        return _no_data_card(0, q, "三大法人買賣超")
    w = _flow_window(flows)
    last = w["latest"]
    if w["total"] > 0:
        a, color = f"🟢 三大法人近 {w['n']} 日淨買超，資金淨流入", COLORS[0]
    elif w["itc"] > 0 and w["foreign"] < 0:
        a, color = "🟠 外資賣超、投信買超（內外資方向相反）", "#f59e0b"
    else:
        a, color = f"🔴 三大法人近 {w['n']} 日同步賣超，資金淨流出", "#fb7185"
    sub = (f"{_md(last['date'])} 三大法人合計 {_sgn(last['total'], 1)} 億（外資 {_sgn(last['foreign'], 1)}、投信 {_sgn(last['itc'], 1)}）；"
           f"近 {w['n']} 日合計 {_sgn(w['total'], 0)} 億")

    mkt = window_return(idx_series.get(MARKET_INDEX), WINDOW_DAYS)
    mkt_txt = (f"大盤（{MARKET_INDEX}）{_md(mkt['from'])}~{_md(mkt['to'])} 累計 {_sgn(mkt['pct'], 2, '%')}。" if mkt else "")
    biggest = max(("外資", w["foreign"]), ("投信", w["itc"]), ("自營商", w["dealer"]), key=lambda kv: abs(kv[1]))
    sells = sum(1 for r in w["rows"] if r["foreign"] < 0)
    by_inst = sorted(table, key=lambda r: r["inst"], reverse=True)
    buyers, sellers = [r for r in by_inst if r["inst"] > 0][:3], [r for r in reversed(by_inst) if r["inst"] < 0][:3]

    q6 = [
        f"最近 {w['n']} 個交易日（{_md(w['rows'][0]['date'])}~{_md(last['date'])}）三大法人合計 {_sgn(w['total'], 1)} 億元：外資 {_sgn(w['foreign'], 1)}、"
        f"投信 {_sgn(w['itc'], 1)}、自營商 {_sgn(w['dealer'], 1)}。逐日合計（億）：{_flow_day_list(w)}。{mkt_txt}",
        f"數據顯示主要力道來自{biggest[0]}（窗內合計 {_sgn(biggest[1], 1)} 億）；外資在 {w['n']} 日中有 {sells} 日為賣超。"
        "這裡只呈現官方買賣超數字，不推測原因。",
        (f"法人合計為{'買超' if w['total'] > 0 else '賣超'}，投信{'買超' if w['itc'] > 0 else '賣超'}、外資{'買超' if w['foreign'] > 0 else '賣超'}。"
         + ("內外資方向相反，整體淨額被兩邊互相抵銷。" if (w["itc"] > 0) != (w["foreign"] > 0) else "內外資方向一致。")
         + (f" 背景（人工維護、非即時）：{_macro_context(d.get('macro_latest'))}。" if _macro_context(d.get("macro_latest")) else "")),
        ("、".join(_e(r["name"]) + f"（{_lots(r['inst'])}）" for r in buyers) or "目前沒有產業同時呈現法人淨買超。")
        + "　[單日外資+投信買超張數最多的產業]",
        ("、".join(_e(r["name"]) + f"（{_lots(r['inst'])}）" for r in sellers) or "目前沒有產業呈現法人淨賣超。")
        + "　[單日外資+投信賣超張數最多的產業]",
        f"外資是否停止連續賣超、窗內合計是否由 {_sgn(w['total'], 0)} 億轉正；投信買超是否延續。下一個交易日收盤後（約 17:30）資料會自動更新。",
    ]
    basis = f"資料來源：證交所 BFI82U 三大法人買賣金額（官方 API，{_md(w['rows'][0]['date'])}~{_md(last['date'])}）、證交所指數、MOPS/T86 產業彙總；背景為人工維護總經資料。"
    return _card(0, q, a, sub, q6, basis, color)


def _card_q2(d, flows, table, idx_series):
    q = "Q2. 資金目前主要流向哪些地方？"
    if not table:
        return _no_data_card(1, q, "產業法人買賣超")
    by_inst = sorted(table, key=lambda r: r["inst"], reverse=True)
    buyers = [r for r in by_inst if r["inst"] > 0][:3]
    sellers = [r for r in reversed(by_inst) if r["inst"] < 0][:3]
    if buyers:
        a = "💰 法人買超集中在 " + "、".join(_e(r["name"]) for r in buyers[:3])
    else:
        a = "🔻 法人今日全面賣超，無明顯資金流入產業"
    sub = ("買超：" + "、".join(f"{_e(r['name'])} {_lots(r['inst'])}" for r in buyers[:2]) if buyers else "無法人淨買超產業") \
        + ("；賣超最多：" + f"{_e(sellers[0]['name'])} {_lots(sellers[0]['inst'])}" if sellers else "")
    insti_date = None
    for c in d.get("live_top_companies") or []:
        insti_date = to_iso_date(c.get("insti_trade_date")) or insti_date
    style = []
    for nm in STYLE_INDEXES:
        wr = window_return(idx_series.get(nm), WINDOW_DAYS)
        if wr:
            style.append((nm.replace("報酬指數", "").replace("臺灣", "台灣"), wr))
    style_txt = "；".join(f"{n} {_sgn(w['pct'], 2, '%')}" for n, w in style)
    q6 = [
        f"{_md(insti_date)} 外資+投信買超張數最多的產業：" + ("、".join(f"{_e(r['name'])} {_lots(r['inst'])}" for r in buyers) or "無")
        + "；賣超最多：" + ("、".join(f"{_e(r['name'])} {_lots(r['inst'])}" for r in sellers) or "無") + "。（單位為張，不同產業股價不同，只比方向與相對大小，不是金額。）",
        "彙總方式：把各產業旗下公司當日的外資、投信買賣超股數加總（T86 / 櫃買三大法人），資料每個交易日收盤後更新。",
        (f"風格表現（近 {WINDOW_DAYS} 日報酬指數）：{style_txt}。" if style_txt else "近期風格指數資料不足。"),
        "、".join(f"{_e(r['name'])}（外資 {_lots(r['foreign'])}、投信 {_lots(r['itc'])}）" for r in buyers) or "—",
        "、".join(f"{_e(r['name'])}（外資 {_lots(r['foreign'])}、投信 {_lots(r['itc'])}）" for r in sellers) or "—",
        "觀察買超是否連續多日集中在同一批產業；單日張數容易受權值股影響，需搭配下一個交易日資料確認。",
    ]
    basis = f"資料來源：證交所 T86 / 櫃買三大法人個股買賣超 {_md(insti_date)}，依產業對照表彙總；指數為證交所報酬指數。"
    return _card(1, q, a, sub, q6, basis)


def _rank_text(table):
    """排名依據的說明 (依模式不同)：模型模式用即時重算的總分；簡易模式用營收年增 + 法人買超百分位。"""
    if table and table[0].get("mode") == "model":
        return ("排名依據：啟用中模型的總分 (5 項子分數都由官方即時資料重算：基本面=營收年增、成長動能=累計營收年增與加速度、"
                "法人布局=法人買賣金額占成交值、估值=PEG 代理、資金流向=類股相對大盤報酬與成交值占比；各取產業間百分位後依治理頁權重加總)。")
    return (f"排名依據：{int(HEAT_WEIGHT_YOY * 100)}% 產業營收年增（MOPS）+ {int(HEAT_WEIGHT_INST * 100)}% 當日外資+投信買超張數，"
            f"各取 {len(table)} 個產業間的百分位 (此資料庫尚未啟用即時評分，採簡易模式)。")


def _score_word(table):
    return "模型分數" if table and table[0].get("mode") == "model" else "即時熱度"


def _card_q3(d, table):
    q = "Q3. 哪些產業正在明顯升溫？"
    if not table:
        return _no_data_card(2, q, "產業營收與法人資料")
    s = d.get("live_summary") or {}
    ym = _ym_label((d.get("live_top_companies") or [{}])[0].get("data_ym"))
    top = table[:5]
    word = _score_word(table)
    a = "🔥 " + "、".join(_e(r["name"]) for r in top[:3])
    total_rev, yoy = _num(s.get("total_rev_trillion")), _num(s.get("total_yoy_pct"))
    sub = (f"全市場 {s.get('total_companies')} 家{ym}營收 {total_rev} 兆（{_sgn(yoy, 1, '%')}）" if total_rev is not None and yoy is not None
           else f"{word}前三名") + f"；{word}第 1 名 {_e(top[0]['name'])} {top[0]['heat']:.1f} 分"
    q6 = [
        f"{word}前五名：" + "；".join(f"#{i + 1} {_industry_phrase(r)} {r['heat']:.1f} 分" for i, r in enumerate(top)) + "。",
        _rank_text(table),
        (f"代表這幾個產業在綜合排名居前，但各項子分數不一定同時偏強，請看各產業數字。{ym}全市場營收 {total_rev} 兆、年增 {_sgn(yoy, 1, '%')}。"
         if total_rev is not None and yoy is not None else "代表這幾個產業在綜合排名居前，但各項子分數不一定同時偏強。"),
        "；".join(_industry_phrase(r) for r in top[:3]),
        f"{word}偏低（見 Q4）的產業。",
        "下個月 10 日前公布的當月營收是否延續年增，以及法人買超是否連續；分數每個交易日收盤後重算。",
    ]
    basis = f"資料來源：MOPS {ym}營收（t187ap05）、證交所 T86 / 櫃買三大法人、個股收盤價與成交金額，14 個產業對照表彙總。"
    return _card(2, q, a, sub, q6, basis)


def _card_q4(d, table):
    q = "Q4. 哪些產業正在明顯降溫？"
    if len(table) < 3:
        return _no_data_card(3, q, "產業營收與法人資料")
    ym = _ym_label((d.get("live_top_companies") or [{}])[0].get("data_ym"))
    word = _score_word(table)
    bottom = list(reversed(table[-3:]))   # 分數最低在前
    a = "🧊 " + "、".join(_e(r["name"]) for r in bottom)
    sub = "；".join(f"{_e(r['name'])} 營收年增 {_sgn(r['yoy'], 1, '%')}、"
                    + (f"法人 {_sgn(r['inst_billion'], 1)} 億" if r.get("inst_billion") is not None else f"法人 {_lots(r['inst'])}")
                    for r in bottom[:2])
    q6 = [
        f"{word}最低：" + "；".join(f"{_industry_phrase(r)} {r['heat']:.1f} 分" for r in bottom) + "。",
        _rank_text(table),
        "代表綜合排名落後；但營收年增只反映單月，金融、營建等產業的營收認列本來就有季節與一次性因素，不宜單看一個月。",
        f"{word}排名上升的產業（見 Q3）。",
        "、".join(_e(r["name"]) for r in bottom),
        "下個月營收是否轉強、法人是否轉為買超；若連續兩個月都落後才較有訊號意義。",
    ]
    basis = f"資料來源：MOPS {ym}營收、證交所 T86 / 櫃買三大法人、個股收盤價與成交金額，14 個產業對照表彙總。"
    return _card(3, q, a, sub, q6, basis)


def _card_q5(d, table):
    q = "Q5. 有沒有值得提早關注的新興趨勢？"
    comps = d.get("live_top_companies") or []
    if not comps:
        return _no_data_card(4, q, "個股營收與法人資料")
    ym = _ym_label(comps[0].get("data_ym"))
    hot_ids = {r["id"] for r in table[:3]}

    def passes(c):
        yoy, cum, mom, pe, net = (_num(c.get("rev_yoy_pct")), _num(c.get("cum_rev_yoy_pct")), _num(c.get("rev_mom_pct")),
                                  _num(c.get("pe_ratio")), _num(c.get("total_3insti_net_shares")))
        return (yoy is not None and yoy >= EMERGING_MIN_YOY and cum is not None and cum >= EMERGING_MIN_CUM_YOY
                and mom is not None and mom > 0 and pe is not None and 0 < pe <= EMERGING_MAX_PE and net is not None and net > 0)

    cands = sorted((c for c in comps if passes(c)), key=lambda c: -_num(c["rev_yoy_pct"]))
    fresh = [c for c in cands if c.get("mapped_industry_id") not in hot_ids]
    pick = (fresh if len(fresh) >= 2 else cands)[:5]
    if not pick:
        return _card(4, q, "🌱 目前沒有同時符合條件的標的",
                     f"{ym}營收年增 ≥{EMERGING_MIN_YOY:.0f}%、累計年增 ≥{EMERGING_MIN_CUM_YOY:.0f}%、月增為正、本益比 ≤{EMERGING_MAX_PE:.0f}、法人買超，無一檔同時成立",
                     ["營收前 120 大公司中，沒有任何一檔同時符合篩選條件。", "—", "—", "—", "—", "下一次資料更新後會重新篩選。"],
                     f"資料來源：MOPS {ym}營收前 {len(comps)} 大公司、本益比（證交所/櫃買）、三大法人買賣超。")

    def line(c):
        return (f"{_e(c['company_code'])} {_e(c['company_name'])}（營收年增 {_sgn(_num(c['rev_yoy_pct']), 1, '%')}、累計 {_sgn(_num(c['cum_rev_yoy_pct']), 1, '%')}、"
                f"本益比 {_num(c['pe_ratio']):.1f}、法人 {_lots(_num(c['total_3insti_net_shares']))}）")
    a = "🌱 " + "、".join(f"{_e(c['company_name'])}" for c in pick[:3])
    sub = f"{ym}營收年增 {_sgn(_num(pick[0]['rev_yoy_pct']), 1, '%')}（{_e(pick[0]['company_name'])}）起，且當日法人買超、本益比 ≤{EMERGING_MAX_PE:.0f}"
    q6 = [
        f"營收前 {len(comps)} 大公司中，同時符合條件的有 {len(cands)} 檔，營收年增最高的前 {len(pick)} 檔：" + "；".join(line(c) for c in pick) + "。",
        f"篩選條件：{ym}營收年增 ≥{EMERGING_MIN_YOY:.0f}%、累計年增 ≥{EMERGING_MIN_CUM_YOY:.0f}%（排除單月波動）、月增為正、本益比 ≤{EMERGING_MAX_PE:.0f}（排除純題材高估值）、當日三大法人合計買超。"
        + ("已優先列出不在 Q3 熱度前三名產業的標的。" if len(fresh) >= 2 else ""),
        "代表營收加速、估值尚未過熱、且法人當日已在買進的組合；僅是量化篩選，不是投資建議。",
        "、".join(_e(c["company_name"]) for c in pick),
        "營收前 120 大以外的公司、以及本益比為負或缺值的公司不在篩選範圍內。",
        "下個月營收是否延續成長、本益比是否因股價上漲而超過上限。",
    ]
    basis = f"資料來源：MOPS {ym}營收前 {len(comps)} 大公司、本益比（證交所/櫃買）、三大法人買賣超（{_md(to_iso_date(comps[0].get('insti_trade_date')))}）。"
    return _card(4, q, a, sub, q6, basis)


def _card_q6(d, flows, idx_series):
    q = "Q6. 現在最大的經濟或市場風險是什麼？"
    if not flows and not idx_series.get(MARKET_INDEX):
        return _no_data_card(5, q, "外資與大盤")
    triggers, facts = [], []
    if flows:
        w = _flow_window(flows)
        facts.append(f"外資近 {w['n']} 日合計 {_sgn(w['foreign'], 0)} 億（{sum(1 for r in w['rows'] if r['foreign'] < 0)}/{w['n']} 日賣超）")
        if w["foreign"] <= FOREIGN_SELL_ALERT_BILLION:
            triggers.append("外資提款")
    mkt_series = idx_series.get(MARKET_INDEX) or []
    mkt = window_return(mkt_series, WINDOW_DAYS)
    worst = min((r for r in mkt_series[-WINDOW_DAYS:] if r[2] is not None), key=lambda r: r[2], default=None)
    if mkt:
        facts.append(f"大盤 {_md(mkt['from'])}~{_md(mkt['to'])} 累計 {_sgn(mkt['pct'], 2, '%')}")
        if mkt["pct"] <= MARKET_DROP_ALERT_PCT:
            triggers.append("大盤回檔")
    if worst and worst[2] <= DAY_DROP_ALERT_PCT:
        facts.append(f"{_md(worst[0])} 單日 {_sgn(worst[2], 2, '%')}")
        triggers.append("單日急跌")
    manual = manual_market_stats(d.get("institutional_flows"))
    ctx = []
    if "margin_balance_billion" in manual:
        dt, v = manual["margin_balance_billion"]
        ctx.append(f"融資餘額 {v:,.0f} 億（人工維護，截至 {_md(dt)}）")
    if "foreign_futures_oi_contracts" in manual:
        dt, v = manual["foreign_futures_oi_contracts"]
        ctx.append(f"外資期貨未平倉 {v:,.0f} 口（人工維護，截至 {_md(dt)}）")
    for m in d.get("macro_latest") or []:
        if m.get("metric_code") in ("US_10Y_YIELD", "INTL_DXY", "INTL_SOX_INDEX") and _num(m.get("cleaned_value")) is not None:
            nm = {"US_10Y_YIELD": "美國10年期公債殖利率", "INTL_DXY": "美元指數", "INTL_SOX_INDEX": "費城半導體指數"}[m["metric_code"]]
            ctx.append(f"{nm} {_fmt(m['cleaned_value'])}{m.get('unit') or ''}（人工維護，{_e(m.get('period_covered'))}）")

    if not triggers:
        a, color = "🟢 即時風險訊號平靜", COLORS[0]
    elif len(triggers) == 1:
        a, color = f"🟡 留意：{triggers[0]}", "#facc15"
    else:
        a, color = "⚠️ " + "＋".join(triggers), "#f59e0b"
    sub = "；".join(facts) or "即時資料不足"
    q6 = [
        "；".join(facts) + "。",
        f"警示規則（機械式，不推測原因）：外資窗內合計 ≤{FOREIGN_SELL_ALERT_BILLION:,.0f} 億、大盤窗內累計 ≤{MARKET_DROP_ALERT_PCT:.0f}%、大盤單日 ≤{DAY_DROP_ALERT_PCT:.0f}%。目前觸發：{('、'.join(triggers) if triggers else '無')}。",
        ("觸發的訊號越多代表即時資金面與價格面同步轉弱。" if len(triggers) >= 2 else "目前即時訊號尚未同時轉弱，但仍需持續追蹤。")
        + (" 背景（人工維護、非即時）：" + "；".join(ctx) + "。" if ctx else ""),
        "即時訊號平靜時，無特別需要迴避的產業。" if not triggers else "訊號轉弱期間，法人持續買超的產業相對有支撐（見 Q2）。",
        "高本益比、融資使用率高且法人持續賣超的個股較易放大跌幅（以 Q2 的賣超產業為準）。",
        f"外資窗內合計是否回到 {FOREIGN_SELL_ALERT_BILLION:,.0f} 億以上、大盤累計跌幅是否收斂到 {MARKET_DROP_ALERT_PCT:.0f}% 以內，即視為訊號解除。",
    ]
    basis = "資料來源：證交所 BFI82U、證交所發行量加權股價報酬指數（即時）；融資、期貨與美債/美元/費半為人工維護，只作背景。"
    return _card(5, q, a, sub, q6, basis, color)


def compute_home_pulse(dash):
    """由儀表板 payload 產生首頁六張卡。任何單一卡片出錯都只讓該卡降級，不影響整頁。"""
    flows = live_daily_flows(dash.get("institutional_flows"))
    idx = index_series(dash.get("live_indices"))
    table = industry_live_table(dash.get("industries"))
    builders = [
        lambda: _card_q1(dash, flows, table, idx),
        lambda: _card_q2(dash, flows, table, idx),
        lambda: _card_q3(dash, table),
        lambda: _card_q4(dash, table),
        lambda: _card_q5(dash, table),
        lambda: _card_q6(dash, flows, idx),
    ]
    items = []
    for i, build in enumerate(builders):
        try:
            items.append(build())
        except Exception as exc:   # noqa: BLE001  單卡失敗時降級，不拖垮整份 payload
            items.append(_no_data_card(i, f"Q{i + 1}", f"（產生失敗：{type(exc).__name__}）"))
    return {
        "items": items,
        "flows_through": flows[-1]["date"] if flows else None,
        "timeline_latest": _timeline_latest(items, table, flows),
        "method": "由官方 OpenAPI 即時資料機械式產生；規則與門檻見 backend/live_pulse.py。",
    }


def _timeline_latest(items, table, flows):
    """熱度圖時間軸「最新」那一格的文字 (原本是手寫)；資料不足時回傳 None，前端保留舊文字並標示。"""
    if not table or not flows:
        return None
    word = _score_word(table)
    hot, cold = table[:3], list(reversed(table[-3:]))
    by_inst = sorted((r for r in table if r.get("inst_billion") is not None), key=lambda r: -r["inst_billion"])
    buyers = [r for r in by_inst if r["inst_billion"] > 0][:3]
    sellers = [r for r in reversed(by_inst) if r["inst_billion"] < 0][:3]
    fmt = lambda rs: "、".join(f"{_e(r['name'])}（{_sgn(r['inst_billion'], 1)} 億）" for r in rs) or "無"   # noqa: E731
    d = flows[-1]["date"]
    return {
        "label": f"最新（{d} 盤後，即時評分）",
        "flowSummary": f"{items[0]['a']}。{items[0]['sub']}。",
        "hotIndustries": "、".join(f"{_e(r['name'])}（{r['heat']:.1f}）" for r in hot),
        "coldIndustries": "、".join(f"{_e(r['name'])}（{r['heat']:.1f}）" for r in cold),
        "rotationOrder": f"法人當日買超：{fmt(buyers)} ｜ 賣超：{fmt(sellers)}",
        "keyEvent": f"{items[5]['a'].lstrip('⚠️🟡🟢 ')}：{items[5]['sub']}",
        "scoreWord": word,
    }
