"""
台灣經濟資金流向與產業趨勢預警研究中心 (Taiwan Capital Flow Intelligence & Industry Rotation System)
真實官方 API 即時擷取器 (Live Official OpenAPI ETL Connector)
直接連線擷取：
1. 證交所公開資訊觀測站 (MOPS) 全體上市公司最新月營收：https://openapi.twse.com.tw/v1/opendata/t187ap05_L
2. 櫃買中心公開資訊觀測站 (MOPS) 全體上櫃公司最新月營收：https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O
3. 證交所全體上市公司本益比、殖利率、股價淨值比：https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL
4. 櫃買中心全體上櫃公司本益比、殖利率、股價淨值比：https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis
5. 證交所三大法人買賣金額統計表 (BFI82U)：https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json
6. 證交所個股三大法人買賣超日報 (T86)：https://www.twse.com.tw/rwd/zh/fund/T86?selectType=ALLBUT0999&response=json
7. 櫃買中心上櫃三大法人買賣明細：https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading
8. 證交所每日收盤指數與各產業類股指數 (MI_INDEX)：https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX

將全市場上市櫃公司之真實營收、估值與法人籌碼寫入 SQLite，並自動彙整各產業真實基本面與法人數據。

設計原則：
- 每個來源獨立失敗：單一來源出錯只標記該來源，並沿用上一次的資料，不寫入假日期或 NULL 覆蓋好資料。
- 每次擷取都把各來源的狀態 (OK/DEGRADED/STALE/FAILED/EMPTY) 寫入 data_source_status，供前端顯示與排程健康閘門使用。
"""
import json
from db import get_connection, init_database
from common import fetch_json, now_iso, now_tw
from data_health import SOURCES, classify, critical_failures, minguo_ym_to_iso, parse_date


def _fetch_json(url, timeout=15):
    return fetch_json(url, timeout=timeout)


def _to_float(val):
    if val is None:
        return None
    s = str(val).replace(",", "").strip()
    if s in ("", "-", "N/A", "null", "None"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _to_int(val):
    f = _to_float(val)
    return int(f) if f is not None else None


def map_official_industry_to_id(official_ind, code, name):
    """將證交所/櫃買中心官方產業別與重點供應鏈公司映射至本系統 14 大產業分類"""
    s = str(official_ind)
    # 核心代表公司優先精準對照
    foundry_set = {"2330", "2303", "3711", "5347", "6770", "2449", "8150"}
    equip_set = {"6223", "3131", "3583", "6187", "6515", "6510", "3680", "2467", "6640"}
    ai_server_set = {"2317", "2382", "6669", "3231", "2356", "2376", "2357", "3665", "2308", "2301", "3013"}
    thermal_set = {"3017", "3324", "6805", "2059", "3653", "2421", "6230", "8210"}
    cpo_net_set = {"2345", "3363", "3163", "4979", "3450", "6442", "4908", "3081", "6285", "5388"}
    pcb_abf_set = {"2383", "3037", "2368", "8046", "3189", "6274", "6213", "2313", "4958"}

    if code in foundry_set:
        return "IND_SEMI_FOUNDRY"
    if code in equip_set:
        return "IND_SEMI_EQUIP"
    if code in ai_server_set:
        return "IND_AI_SERVER"
    if code in thermal_set:
        return "IND_THERMAL"
    if code in cpo_net_set:
        return "IND_CPO_NET"
    if code in pcb_abf_set:
        return "IND_PCB_ABF"

    if "半導體" in s:
        return "IND_IC_DESIGN"
    if "電腦及週邊" in s or "電子零組件" in s or "其他電子" in s:
        return "IND_AI_SERVER"
    if "通信網路" in s or "光電" in s:
        return "IND_CPO_NET"
    if "金融" in s:
        return "IND_FIN_HOLDING"
    if "航運" in s:
        return "IND_SHIPPING"
    if "電機機械" in s or "綠能環保" in s or "油電燃氣" in s:
        return "IND_POWER_GREEN"
    if "建材營造" in s:
        return "IND_CONSTRUCTION"
    if "鋼鐵" in s or "塑膠" in s or "水泥" in s or "化學" in s or "玻璃" in s or "橡膠" in s or "造紙" in s:
        return "IND_STEEL_PLASTIC"
    if "汽車" in s or "紡織" in s or "食品" in s or "運動休閒" in s or "居家生活" in s:
        return "IND_MACH_AUTO"
    return "IND_BIO_RETAIL"


# ---------------------------------------------------------------------------
# 純解析函式 (不連網、不碰資料庫)：官方一旦改欄位，tests/test_live_parsers.py 會先失敗
# ---------------------------------------------------------------------------
URL_TWSE_PE = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
URL_TPEX_PE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
URL_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86?selectType=ALLBUT0999&response=json"
URL_TPEX_3I = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
URL_TWSE_REV = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
URL_TPEX_REV = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
URL_MI_INDEX = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
URL_BFI82U = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"
# 個股每日收盤行情：用 rwd 版 (與 T86 同網域、同日更新)；openapi 的 STOCK_DAY_ALL 會晚一個交易日，換算買賣金額會錯位
URL_TWSE_QUOTES = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?type=ALLBUT0999&response=json"
URL_TPEX_QUOTES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


def parse_twse_pe(rows):
    out = {}
    for r in rows:
        code = str(r.get("Code", "")).strip()
        if code:
            out[code] = {"pe": _to_float(r.get("PEratio")), "pb": _to_float(r.get("PBratio")),
                         "dy": _to_float(r.get("DividendYield"))}
    return out


def parse_tpex_pe(rows):
    out = {}
    for r in rows:
        code = str(r.get("SecuritiesCompanyCode", "")).strip()
        if code:
            out[code] = {"pe": _to_float(r.get("PriceEarningRatio")), "pb": _to_float(r.get("PriceBookRatio")),
                         "dy": _to_float(r.get("YieldRatio"))}
    return out


def parse_twse_t86(payload):
    """回傳 (insti_map, 資料日期字串或 None)。欄位索引依證交所 T86：0 代號、4/7 外資、10 投信、11 自營商、18 合計。"""
    date = str(payload.get("date", "")).strip() or None
    out = {}
    for row in payload.get("data", []):
        if len(row) >= 19:
            code = str(row[0]).strip()
            out[code] = {
                "f": (_to_int(row[4]) or 0) + (_to_int(row[7]) or 0),
                "i": _to_int(row[10]) or 0,
                "d": _to_int(row[11]) or 0,
                "tot": _to_int(row[18]) or 0,
                "date": date,
            }
    return out, date


def parse_tpex_3insti(rows, fallback_date=None):
    """回傳 (insti_map, 資料日期字串或 None)。上櫃資料有自己的 Date 欄位 (民國日期)，缺少時才用 fallback_date。"""
    out = {}
    date = None
    for r in rows:
        code = str(r.get("SecuritiesCompanyCode", "")).strip()
        if not code:
            continue
        parsed = parse_date(r.get("Date"))
        row_date = parsed.strftime("%Y%m%d") if parsed else fallback_date
        date = date or row_date
        f_net = _to_int(r.get("ForeignInvestorsInclude MainlandAreaInvestors-Difference")
                        or r.get("Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference")) or 0
        i_net = _to_int(r.get("SecuritiesInvestmentTrustCompanies-Difference")) or 0
        d_net = _to_int(r.get("Dealers-Difference")) or 0
        tot_net = _to_int(r.get("TotalDifference")) or (f_net + i_net + d_net)
        out[code] = {"f": f_net, "i": i_net, "d": d_net, "tot": tot_net, "date": row_date}
    return out, date


def parse_revenue_rows(rows, market, source_url, pe_map, insti_map, now_str, insti_fallback_date=None):
    """把 MOPS 月營收 JSON 與估值、法人資料合併成 live_company_fundamentals 的資料列。"""
    out = []
    for r in rows:
        code = str(r.get("公司代號", "")).strip()
        name = str(r.get("公司名稱", "")).strip()
        ind = str(r.get("產業別", "")).strip()
        val = pe_map.get(code, {})
        ins = insti_map.get(code, {})
        out.append((
            code, name, market, ind, map_official_industry_to_id(ind, code, name),
            str(r.get("資料年月", "")).strip(), str(r.get("出表日期", "")).strip(),
            _to_float(r.get("營業收入-當月營收")),
            _to_float(r.get("營業收入-上月營收")),
            _to_float(r.get("營業收入-去年當月營收")),
            _to_float(r.get("營業收入-上月比較增減(%)")),
            _to_float(r.get("營業收入-去年同月增減(%)")),
            _to_float(r.get("累計營業收入-當月累計營收")),
            _to_float(r.get("累計營業收入-去年累計營收")),
            _to_float(r.get("累計營業收入-前期比較增減(%)")),
            val.get("pe"), val.get("pb"), val.get("dy"),
            ins.get("f"), ins.get("i"), ins.get("d"), ins.get("tot"),
            ins.get("date") or insti_fallback_date,
            now_str, source_url, str(r.get("備註", "")),
        ))
    return out


def parse_bfi82u(payload):
    """回傳 dict(date, foreign, itc, dealer_prop, dealer_hedge, total, title)；非 OK、無資料或無日期回傳 None。"""
    if payload.get("stat") != "OK" or not payload.get("data"):
        return None
    d = parse_date(payload.get("date"))
    if d is None:
        return None
    d_prop = d_hedge = itc = fini = tot = 0.0
    for row in payload["data"]:
        title = str(row[0]).strip()
        net_bil = round((_to_float(row[3]) or 0.0) / 1e8, 2)
        if "自行買賣" in title:
            d_prop = net_bil
        elif "避險" in title:
            d_hedge = net_bil
        elif "投信" in title:
            itc = net_bil
        elif "外資及陸資" in title:
            fini += net_bil
        elif "合計" in title:
            tot = net_bil
    return {"date": d.isoformat(), "foreign": round(fini, 2), "itc": itc, "dealer_prop": d_prop,
            "dealer_hedge": d_hedge, "total": tot, "title": payload.get("title")}


def parse_mi_index(rows, now_str):
    out = []
    for r in rows:
        iname = str(r.get("指數", "")).strip()
        tdate = str(r.get("日期", "")).strip()
        if iname and tdate:
            out.append((iname, tdate, _to_float(r.get("收盤指數")), str(r.get("漲跌", "")).strip(),
                        _to_float(r.get("漲跌點數")), _to_float(r.get("漲跌百分比")), now_str, URL_MI_INDEX))
    return out


def _quote_row(code, market, close, chg, value, date_iso, now_str):
    """收盤價與漲跌價差 → (代號, 日期, 市場, 收盤, 漲跌幅%, 成交金額, 抓取時間)；收盤價缺值回傳 None。"""
    if not code or close is None or close <= 0:
        return None
    prev = close - chg if chg is not None else None
    pct = round(chg / prev * 100.0, 3) if prev and prev > 0 else None
    return (code, date_iso, market, close, pct, value, now_str)


def parse_twse_quotes(payload, now_str):
    """
    證交所 rwd MI_INDEX (type=ALLBUT0999) 的「每日收盤行情」表。回傳 (rows, ISO 日期或 None)。
    漲跌方向欄 (漲跌(+/-)) 是 HTML 片段，正負號在裡面；無法判斷方向時漲跌幅留空，不猜。
    """
    if payload.get("stat") != "OK":
        raise ValueError(f"MI_INDEX 回傳 stat={payload.get('stat')!r}")
    d = parse_date(payload.get("date"))
    if d is None:
        raise ValueError("MI_INDEX 缺少日期")
    table = next((t for t in payload.get("tables", []) if "每日收盤行情" in str(t.get("title", ""))), None)
    if not table:
        raise ValueError("MI_INDEX 找不到「每日收盤行情」表 (官方可能改版)")
    fields = table.get("fields", [])
    try:
        i_code, i_val, i_close = fields.index("證券代號"), fields.index("成交金額"), fields.index("收盤價")
        i_dir, i_diff = fields.index("漲跌(+/-)"), fields.index("漲跌價差")
    except ValueError as e:
        raise ValueError(f"MI_INDEX 每日收盤行情欄位改版：{e}") from e
    out = []
    for row in table.get("data", []):
        if len(row) <= max(i_code, i_val, i_close, i_dir, i_diff):
            continue
        sign_html = str(row[i_dir])
        sign = 1.0 if "+" in sign_html else (-1.0 if "-" in sign_html else None)
        diff = _to_float(row[i_diff])
        chg = sign * abs(diff) if (sign is not None and diff is not None) else None
        r = _quote_row(str(row[i_code]).strip(), "TWSE", _to_float(row[i_close]), chg, _to_float(row[i_val]), d.isoformat(), now_str)
        if r:
            out.append(r)
    return out, d.isoformat()


def parse_twse_index_tables(payload, now_str):
    """
    同一份 rwd MI_INDEX 裡的「價格指數 / 報酬指數」表 → live_market_indices 的資料列 (日期用民國 7 碼，與既有資料一致)。
    openapi 版 MI_INDEX 會晚一個交易日，這裡的是和 T86 同日的收盤指數。沒有這些表或欄位時回傳空清單 (不是錯誤)。
    """
    d = parse_date(payload.get("date"))
    if d is None:
        return []
    roc = f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}"
    out = []
    for t in payload.get("tables", []):
        title = str(t.get("title", ""))
        if "指數" not in title or "每日收盤行情" in title or "臺灣證券交易所" not in title:
            continue
        fields = t.get("fields", [])
        try:
            i_name, i_close = 0, fields.index("收盤指數")
            i_dir, i_pts, i_pct = fields.index("漲跌(+/-)"), fields.index("漲跌點數"), fields.index("漲跌百分比(%)")
        except ValueError:
            continue
        for row in t.get("data", []):
            if len(row) <= max(i_close, i_dir, i_pts, i_pct):
                continue
            sign_html = str(row[i_dir])
            sign = -1.0 if "-" in sign_html else 1.0
            pts, pct = _to_float(row[i_pts]), _to_float(row[i_pct])
            close = _to_float(row[i_close])
            name = str(row[i_name]).strip()
            if not name or close is None:
                continue
            out.append((name, roc, close, "-" if sign < 0 else "+", pts, None if pct is None else sign * abs(pct), now_str, URL_TWSE_QUOTES))
    return out


def parse_tpex_quotes(rows, now_str):
    """櫃買每日收盤行情 (openapi)。Change 欄自帶正負號。回傳 (rows, ISO 日期或 None)。"""
    out, date_iso = [], None
    for r in rows:
        d = parse_date(r.get("Date"))
        if d is None:
            continue
        date_iso = date_iso or d.isoformat()
        chg_raw = str(r.get("Change", "")).strip().replace(",", "")
        chg = _to_float(chg_raw.replace("+", "")) if chg_raw not in ("", "---", "--") else None
        q = _quote_row(str(r.get("SecuritiesCompanyCode", "")).strip(), "TPEx", _to_float(r.get("Close")), chg,
                       _to_float(r.get("TransactionAmount")), d.isoformat(), now_str)
        if q:
            out.append(q)
    return out, date_iso


# ---------------------------------------------------------------------------
# 來源狀態記錄與沿用舊資料
# ---------------------------------------------------------------------------
def _record_status(cur, key, ok, count, data_date, now_str, today, error=None):
    label, daily, _critical = SOURCES[key]
    cur.execute("SELECT * FROM data_source_status WHERE source_key = ?", (key,))
    prev = cur.fetchone()
    prev_count = prev["record_count"] if prev else None
    status, message = classify(ok, count, prev_count, data_date, today, daily=daily)
    if error:
        message = f"{message}：{error}"[:300]
    if status in ("FAILED", "EMPTY") and prev:
        # 失敗時保留上一次成功的筆數與資料日期，下次才有基準可比較
        count, data_date, last_success = prev["record_count"], prev["data_date"], prev["last_success_at"]
    elif status in ("FAILED", "EMPTY"):
        last_success = None
    else:
        last_success = now_str
    cur.execute("""
        INSERT OR REPLACE INTO data_source_status
        (source_key, label, status, last_attempt_at, last_success_at, data_date, record_count, prev_record_count, message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (key, label, status, now_str, last_success, data_date, count or 0, prev_count, message))
    if status != "OK":
        source_id = "SRC_TWSE" if key.startswith(("twse", "mi", "bfi")) else "SRC_TPEX"
        cur.execute("""
            INSERT INTO ingestion_audit_logs (run_timestamp, task_name, source_id, status, records_affected, message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now_str, f"LIVE_SRC_{key.upper()}", source_id,
              "FAILED" if status in ("FAILED", "EMPTY") else "STALE_WARNING", count or 0, f"{label}：{message}"))
    return status


def _load_previous_rows(cur):
    """每家公司最近一次寫入的估值與法人欄位；來源失敗時沿用，避免用 NULL 蓋掉好資料。"""
    cur.execute("""
        SELECT company_code, pe_ratio, pb_ratio, dividend_yield, foreign_net_shares, itc_net_shares,
               dealer_net_shares, total_3insti_net_shares, insti_trade_date
        FROM live_company_fundamentals ORDER BY data_ym ASC
    """)
    pe, insti = {}, {}
    for r in cur.fetchall():
        pe[r["company_code"]] = {"pe": r["pe_ratio"], "pb": r["pb_ratio"], "dy": r["dividend_yield"]}
        if r["insti_trade_date"]:
            insti[r["company_code"]] = {"f": r["foreign_net_shares"], "i": r["itc_net_shares"],
                                        "d": r["dealer_net_shares"], "tot": r["total_3insti_net_shares"],
                                        "date": r["insti_trade_date"]}
    return pe, insti


def run_live_ingestion():
    init_database()
    conn = get_connection()
    cur = conn.cursor()
    now_str = now_iso()
    today = now_tw().date()
    summary = {}
    results = {}   # source_key -> dict(ok, count, date, error)

    def attempt(key, url, parser, timeout=15):
        """執行單一來源；任何例外都只標記該來源失敗，不影響其他來源。parser(raw) -> (資料, 筆數, 資料日期)。"""
        try:
            parsed, count, date = parser(_fetch_json(url, timeout=timeout))
            results[key] = {"ok": True, "count": count, "date": date}
            summary[f"{key}_count"] = count
            return parsed
        except Exception as e:  # noqa: BLE001
            results[key] = {"ok": False, "count": 0, "date": None, "error": f"{type(e).__name__}: {e}"}
            summary[f"{key}_error"] = str(e)
            return None

    first_date = lambda raw: raw[0].get("Date") if raw else None  # noqa: E731

    # 1. 估值
    twse_pe = attempt("twse_pe", URL_TWSE_PE, lambda raw: (parse_twse_pe(raw), len(raw), first_date(raw)))
    tpex_pe = attempt("tpex_pe", URL_TPEX_PE, lambda raw: (parse_tpex_pe(raw), len(raw), first_date(raw)))

    # 2. 三大法人個股
    def _parse_t86(raw):
        m, d = parse_twse_t86(raw)
        return m, len(raw.get("data", [])), d

    def _parse_3i(raw):
        m, d = parse_tpex_3insti(raw)
        return m, len(raw), d

    t86 = attempt("twse_t86", URL_T86, _parse_t86)
    tpex_3i = attempt("tpex_3i", URL_TPEX_3I, _parse_3i)
    t86_date = results["twse_t86"]["date"]

    # 失敗的一側沿用上一次寫入的值；成功的一側用新值覆蓋
    prev_pe, prev_insti = _load_previous_rows(cur)
    pe_map = {}
    if not (twse_pe and tpex_pe):
        pe_map.update(prev_pe)
    for src in (twse_pe, tpex_pe):
        if src:
            pe_map.update(src)
    insti_map = {}
    if not (t86 and tpex_3i):
        insti_map.update(prev_insti)
    fresh_insti = {}
    for src in (t86, tpex_3i):
        if src:
            fresh_insti.update(src)
    insti_map.update(fresh_insti)

    # 3. 月營收
    company_rows = []
    for key, url, market in (("twse_rev", URL_TWSE_REV, "TWSE"), ("tpex_rev", URL_TPEX_REV, "TPEx")):
        def _parse_rev(raw, market=market, url=url):
            rows = parse_revenue_rows(raw, market, url, pe_map, insti_map, now_str, t86_date)
            return rows, len(raw), minguo_ym_to_iso(raw[0].get("資料年月")) if raw else None
        rows = attempt(key, url, _parse_rev)
        if rows:
            company_rows.extend(rows)

    if company_rows:
        cur.executemany("""
            INSERT OR REPLACE INTO live_company_fundamentals
            (company_code, company_name, market_type, official_industry, mapped_industry_id,
             data_ym, report_date, rev_current_thousand, rev_prev_month_thousand,
             rev_last_year_thousand, rev_mom_pct, rev_yoy_pct, cum_rev_current_thousand,
             cum_rev_last_year_thousand, cum_rev_yoy_pct, pe_ratio, pb_ratio, dividend_yield,
             foreign_net_shares, itc_net_shares, dealer_net_shares, total_3insti_net_shares,
             insti_trade_date, fetched_at, source_url, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, company_rows)
        # 每家公司只保留最新月份：主鍵是 (公司, 資料年月)，不清理的話新月份公布後所有產業彙總會把兩個月加在一起
        cur.execute("""
            DELETE FROM live_company_fundamentals
            WHERE data_ym < (SELECT MAX(x.data_ym) FROM live_company_fundamentals x
                             WHERE x.company_code = live_company_fundamentals.company_code)
        """)
        period = minguo_ym_to_iso(company_rows[0][5])
        cur.execute("""
            INSERT INTO ingestion_audit_logs
            (run_timestamp, task_name, source_id, status, records_affected, message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            now_str, "LIVE_MOPS_PE_T86_FULL_INGEST", "SRC_MOPS", "SUCCESS", len(company_rows),
            f"已寫入上市({summary.get('twse_rev_count', 0)}家)＋上櫃({summary.get('tpex_rev_count', 0)}家)共 "
            f"{len(company_rows)} 家公司之 {period} 月營收、估值與三大法人個股買賣超 (法人資料日期 {t86_date or '沿用舊值'})"
        ))

    # 4. 大盤與類股指數
    def _parse_mi(raw):
        rows = parse_mi_index(raw, now_str)
        return rows, len(rows), rows[0][1] if rows else None

    idx_rows = attempt("mi_index", URL_MI_INDEX, _parse_mi)
    if idx_rows:
        cur.executemany("""
            INSERT OR REPLACE INTO live_market_indices
            (index_name, trade_date, close_index, change_dir, change_points, change_pct, fetched_at, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, idx_rows)
        cur.execute("""
            INSERT INTO ingestion_audit_logs (run_timestamp, task_name, source_id, status, records_affected, message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now_str, "LIVE_TWSE_MI_INDEX_INGEST", "SRC_TWSE", "SUCCESS", len(idx_rows),
              f"已寫入證交所 MI_INDEX 共 {len(idx_rows)} 項指數與產業類股收盤行情 (日期:{idx_rows[0][1]})"))

    # 4b. 個股每日收盤價與成交金額 (法人買賣超股數 → 金額、各產業成交值占比用)。只存已有營收資料的公司，並只保留近 90 天。
    known_codes = {r[0] for r in company_rows}

    same_day_index_rows = []

    def _quote_parser(fn):
        def run(raw):
            rows, d = fn(raw, now_str)
            if fn is parse_twse_quotes:      # 同一份回應順便取得與 T86 同日的指數 (失敗不影響個股行情)
                try:
                    same_day_index_rows.extend(parse_twse_index_tables(raw, now_str))
                except Exception:  # noqa: BLE001
                    pass
            return rows, len(rows), d
        return run

    quote_rows = []
    for key, url, fn, tmo in (("twse_quotes", URL_TWSE_QUOTES, parse_twse_quotes, 30),
                              ("tpex_quotes", URL_TPEX_QUOTES, parse_tpex_quotes, 60)):
        rows = attempt(key, url, _quote_parser(fn), timeout=tmo)
        if rows:
            quote_rows.extend(r for r in rows if r[0] in known_codes)
    if same_day_index_rows:
        cur.executemany("""
            INSERT OR REPLACE INTO live_market_indices
            (index_name, trade_date, close_index, change_dir, change_points, change_pct, fetched_at, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, same_day_index_rows)
    if quote_rows:
        cur.executemany("""
            INSERT OR REPLACE INTO live_stock_quotes
            (company_code, trade_date, market_type, close_price, change_pct, trade_value_twd, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, quote_rows)
        cur.execute("DELETE FROM live_stock_quotes WHERE trade_date < date(?, '-90 day')",
                    (max(r[1] for r in quote_rows),))
        cur.execute("""
            INSERT INTO ingestion_audit_logs (run_timestamp, task_name, source_id, status, records_affected, message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now_str, "LIVE_STOCK_QUOTES_INGEST", "SRC_TWSE", "SUCCESS", len(quote_rows),
              f"已寫入 {len(quote_rows)} 檔上市櫃個股收盤價與成交金額 (日期 {sorted({r[1] for r in quote_rows})})"))

    # 5. BFI82U 三大法人金額 (期貨未平倉與融資餘額此 API 不提供，寫入 NULL 而非假數字)
    def _parse_bfi(raw):
        b = parse_bfi82u(raw)
        if b is None:
            raise ValueError("BFI82U 回傳非 OK、無資料或缺少日期")
        return b, len(raw.get("data", [])), b["date"]

    bfi = attempt("bfi82u", URL_BFI82U, _parse_bfi)
    if bfi:
        cur.execute("""
            INSERT OR REPLACE INTO institutional_flows
            (period_type, period_label, release_date, market_scope,
             foreign_net_billion, itc_net_billion, dealer_prop_billion, dealer_hedge_billion,
             total_3insti_billion, foreign_futures_oi_contracts, margin_balance_billion,
             top_buy_industries, top_sell_industries, source_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "DAILY", f"{bfi['date']} (TWSE BFI82U 官方API直連)", bfi["date"], "TWSE 上市官方精確統計",
            bfi["foreign"], bfi["itc"], bfi["dealer_prop"], bfi["dealer_hedge"], bfi["total"], None, None,
            "此 API 不提供產業別買賣超", "此 API 不提供產業別買賣超", "SRC_TWSE",
            f"證交所 BFI82U ({bfi['title']})：外資 {bfi['foreign']}億、投信 {bfi['itc']}億、"
            f"自營商自行 {bfi['dealer_prop']}億、自營商避險 {bfi['dealer_hedge']}億、合計 {bfi['total']}億元"
        ))
        summary["bfi82u_date"] = bfi["date"]
        summary["bfi82u_total_billion"] = bfi["total"]

    # 6. 將官方 API 數值同步更新至 company_research_watchlist
    cur.execute("SELECT ticker FROM company_research_watchlist")
    watchlist_tickers = [r["ticker"] for r in cur.fetchall()]
    for tk in watchlist_tickers:
        cur.execute("SELECT * FROM live_company_fundamentals WHERE company_code = ? ORDER BY data_ym DESC LIMIT 1", (tk,))
        live_row = cur.fetchone()
        if not live_row:
            continue
        lr = dict(live_row)
        rev_bil = round((lr["rev_current_thousand"] or 0.0) / 1e5, 2)
        pe_str = f"P/E {lr['pe_ratio']}x" if lr["pe_ratio"] is not None else "P/E N/A(虧損或極高)"
        pb_str = f"P/B {lr['pb_ratio']}x" if lr["pb_ratio"] is not None else "P/B N/A"
        dy_str = f"殖利率 {lr['dividend_yield']}%" if lr["dividend_yield"] is not None else ""
        val_status = f"【TWSE/TPEx官方API】{pe_str}｜{pb_str}｜{dy_str}"
        insti_date = lr["insti_trade_date"] or "日期未知"
        insti_str = (f"【{insti_date} T86/TPEx官方API】外資 {(lr['foreign_net_shares'] or 0):+,}股｜"
                     f"投信 {(lr['itc_net_shares'] or 0):+,}股｜自營商 {(lr['dealer_net_shares'] or 0):+,}股")
        cur.execute("""
            UPDATE company_research_watchlist
            SET latest_rev_period = ?, latest_rev_billion_twd = ?, rev_mom_pct = ?, rev_yoy_pct = ?,
                pe_ratio_status = ?, institutional_ownership_trend = ?, as_of_date = ?
            WHERE ticker = ?
        """, (f"{minguo_ym_to_iso(lr['data_ym'])} (民國{lr['data_ym']})", rev_bil,
              round(lr["rev_mom_pct"] or 0.0, 2), round(lr["rev_yoy_pct"] or 0.0, 2),
              val_status, insti_str, lr["insti_trade_date"] or today.isoformat(), tk))

    # 7. 記錄各來源狀態並判定健康度
    statuses = {}
    for key, res in results.items():
        statuses[key] = _record_status(cur, key, res["ok"], res["count"], res["date"], now_str, today, res.get("error"))
    summary["health"] = statuses
    summary["critical_failures"] = critical_failures(statuses)

    conn.commit()
    conn.close()
    summary["shared_insti_map"] = fresh_insti
    return summary


if __name__ == "__main__":
    res = run_live_ingestion()
    res.pop("shared_insti_map", None)
    print("Live Ingestion Summary:", json.dumps(res, ensure_ascii=False, indent=2))
