"""
台股 ETF 逐日歷史行情與加權指數逐日資料的擷取 (官方來源，無手寫數字)：
  - 上市 ETF：證交所 rwd STOCK_DAY (一次一個月、一檔)
  - 上櫃 ETF：櫃買 tradingStock (一次一個月、一檔)；上市查不到就改查上櫃，並記住該檔所屬市場
  - 加權指數：證交所 rwd FMTQIK (一次一個月)

www.twse.com.tw 官方建議每 3 秒最多 1 次 (common.py 已強制)，所以：
  - 每次排程一定補抓「當月」(取得最新交易日)；
  - 過去 13 個月逐步回補，每次最多 MAX_REQUESTS 個請求，幾次排程後就會補齊；
  - 已完整抓過的月份 (抓取時間晚於月底) 不會重抓。
任何單一請求失敗只略過該檔該月，不影響其他。
"""
from datetime import date

from common import fetch_json, logger, now_iso
from data_health import parse_date

URL_TWSE_STOCK_DAY = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={ymd}&stockNo={code}&response=json"
URL_TPEX_STOCK_DAY = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code={code}&date={slash}&response=json"
URL_TWSE_FMTQIK = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={ymd}&response=json"
MONTHS_BACK = 13
MAX_REQUESTS = 80                 # 每次排程最多的回補請求數 (約 4 分鐘)
TAIEX_KEY = "_TAIEX"
TAIEX_NAME = "發行量加權股價指數"


def _num(x):
    s = str(x).replace(",", "").strip()
    if s in ("", "--", "-", "X0.00"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def month_list(today, n=MONTHS_BACK):
    """由當月往前 n 個月 (含當月) 的 YYYYMM 清單，新到舊。"""
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def parse_twse_stock_day(payload, ym):
    """STOCK_DAY → [(ISO 日期, 收盤, 成交股數, 成交金額(元))]；無資料回傳 []。"""
    if payload.get("stat") != "OK":
        return []
    fields = payload.get("fields", [])
    try:
        i_d, i_v, i_t, i_c = fields.index("日期"), fields.index("成交股數"), fields.index("成交金額"), fields.index("收盤價")
    except ValueError as e:
        raise ValueError(f"STOCK_DAY 欄位改版：{e}") from e
    out = []
    for row in payload.get("data", []):
        raw = str(row[i_d]).split("/")                      # 民國 '115/11/02' → 7 碼
        d = parse_date(f"{raw[0]}{raw[1]}{raw[2]}") if len(raw) == 3 else None
        close = _num(row[i_c])
        if d and close:
            out.append((d.isoformat(), close, _num(row[i_v]), _num(row[i_t])))
    return out


def parse_tpex_stock_day(payload, ym):
    """TPEx tradingStock → 同上；成交張數×1000=股、成交仟元×1000=元。"""
    tables = payload.get("tables") or []
    if payload.get("stat") not in ("ok", "OK") or not tables:
        return []
    fields = [str(f).replace(" ", "") for f in tables[0].get("fields", [])]
    try:
        i_d, i_v, i_t, i_c = fields.index("日期"), fields.index("成交張數"), fields.index("成交仟元"), fields.index("收盤")
    except ValueError as e:
        raise ValueError(f"TPEx tradingStock 欄位改版：{e}") from e
    out = []
    for row in tables[0].get("data", []):
        raw = str(row[i_d]).split("/")
        d = parse_date(f"{raw[0]}{raw[1]}{raw[2]}") if len(raw) == 3 else None
        close = _num(row[i_c])
        v, t = _num(row[i_v]), _num(row[i_t])
        if d and close:
            out.append((d.isoformat(), close, None if v is None else v * 1000, None if t is None else t * 1000))
    return out


def parse_fmtqik(payload):
    """FMTQIK → [(ISO 日期, 加權指數收盤)]。"""
    if payload.get("stat") != "OK":
        return []
    fields = payload.get("fields", [])
    try:
        i_d, i_c = fields.index("日期"), fields.index("發行量加權股價指數")
    except ValueError as e:
        raise ValueError(f"FMTQIK 欄位改版：{e}") from e
    out = []
    for row in payload.get("data", []):
        raw = str(row[i_d]).split("/")
        d = parse_date(f"{raw[0]}{raw[1]}{raw[2]}") if len(raw) == 3 else None
        close = _num(row[i_c])
        if d and close:
            out.append((d.isoformat(), close))
    return out


def _month_complete(fetched_at, ym):
    """該月份抓取時是否已過月底 (過了才算完整，不必重抓)。"""
    y, m = int(ym[:4]), int(ym[4:])
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return str(fetched_at)[:10] >= date(ny, nm, 1).isoformat()


def tw_etf_codes(conn):
    return [r[0] for r in conn.execute("SELECT etf_code FROM etf_master WHERE listing_market != 'US' ORDER BY etf_code")]


def _fetch_etf_month(code, ym, market_hint):
    """回傳 (rows, market)。market_hint 為 None 時先試上市、再試上櫃。"""
    order = [market_hint] if market_hint else ["TWSE", "TPEx"]
    for market in order:
        if market == "TWSE":
            rows = parse_twse_stock_day(fetch_json(URL_TWSE_STOCK_DAY.format(ymd=f"{ym}01", code=code), timeout=30, retries=2), ym)
        else:
            rows = parse_tpex_stock_day(fetch_json(URL_TPEX_STOCK_DAY.format(code=code, slash=f"{ym[:4]}/{ym[4:]}/01"), timeout=30, retries=2), ym)
        if rows:
            return rows, market
    return [], market_hint


def backfill(conn, today=None, max_requests=MAX_REQUESTS):
    """補抓當月 + 回補歷史。回傳摘要 dict。任何請求失敗只記錄、不拋出。"""
    from datetime import datetime
    today = today or date.today()
    cur = conn.cursor()
    done = {(r["etf_code"], r["ym"]): (r["fetched_at"], r["market"]) for r in cur.execute("SELECT * FROM etf_history_fetch")}
    market_of = {}
    for (code, _ym), (_f, mk) in done.items():
        if mk:
            market_of[code] = mk
    codes = tw_etf_codes(conn)
    months = month_list(today)
    jobs = []
    for ym in months:                                   # 新到舊，月份優先、各檔輪流
        for code in codes + [TAIEX_KEY]:
            got = done.get((code, ym))
            if got and _month_complete(got[0], ym):
                continue
            jobs.append((code, ym))
    # 當月一定要抓 (不受上限限制)；其餘依上限
    current = [j for j in jobs if j[1] == months[0]]
    rest = [j for j in jobs if j[1] != months[0]][:max(0, max_requests - len(current))]
    requests = failures = fetched_rows = 0
    for code, ym in current + rest:
        requests += 1
        try:
            if code == TAIEX_KEY:
                rows = parse_fmtqik(fetch_json(URL_TWSE_FMTQIK.format(ymd=f"{ym}01"), timeout=30, retries=2))
                cur.executemany("INSERT OR REPLACE INTO index_price_history VALUES (?,?,?)", [(TAIEX_NAME, d, c) for d, c in rows])
                mk = "TWSE"
            else:
                rows, mk = _fetch_etf_month(code, ym, market_of.get(code))
                if mk:
                    market_of[code] = mk
                cur.executemany("INSERT OR REPLACE INTO etf_price_history VALUES (?,?,?,?,?,?)",
                                [(code, d, c, v, t, mk) for d, c, v, t in rows])
            fetched_rows += len(rows)
            cur.execute("INSERT OR REPLACE INTO etf_history_fetch VALUES (?,?,?,?,?)", (code, ym, mk, now_iso(), len(rows)))
            conn.commit()
        except Exception as e:  # noqa: BLE001 — 單一請求失敗不影響其他
            failures += 1
            logger.warning("ETF 歷史行情擷取失敗 %s %s：%s", code, ym, e)
    remaining = len([j for j in jobs if j not in current + rest])
    return {"requests": requests, "failures": failures, "rows": fetched_rows, "remaining_jobs": remaining}
