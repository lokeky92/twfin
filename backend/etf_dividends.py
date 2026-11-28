"""
ETF 配息與含息報酬：由證交所「除權除息計算結果表」(TWT49U) 與櫃買中心「除權息計算結果表」(exDailyQ) 取得每檔 ETF 的
除息日與每單位現金配息，計算 (1) 近 12 個月配息率、(2) 近 1 年含息報酬 (配息於除息日再投入)。

方法：
- 配息率 = 近 365 天內除息日已發生的現金配息合計 ÷ 最新收盤價。這是「已發放的過去配息 ÷ 現價」，不是預期殖利率；
  配息金額不固定的 ETF (高股息、債券) 會隨每期波動。
- 含息報酬：逐日報酬 = (當日收盤 + 當日除息金額) ÷ 前一日收盤，連乘 (與價格報酬使用同一個 252 個交易日視窗)；
  假設配息在除息日以收盤價再投入、不計稅與手續費。價格序列有分割斷層時，與價格報酬一樣只用最後一段連續行情。
- 上市未滿一年 (連續行情不足 253 個交易日) 者留空，不拿不到一年的配息去年化。
- 只有在「該市場的配息表已成功取得且涵蓋整個視窗」時才計算：抓取失敗時留空 (N/A)，絕不把「沒資料」當成「零配息」。
- 不涵蓋：淨值與折溢價、3／5 年報酬、台幣以外幣別；配息來源拆解 (股利／價差／本金) 仍是人工維護。

純函式在前半 (parse_*、ttm_dividend、total_return)，資料庫與網路在 refresh。
"""
import re
from datetime import date, timedelta

from common import fetch_json, logger, now_iso

URL_TWSE = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?response=json&startDate={s}&endDate={e}"
URL_TPEX = "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate={s}&endDate={e}&response=json"
LOOKBACK_DAYS = 400          # 抓取視窗 (比 365 天多一些，涵蓋年初的除息日)
WINDOW_DAYS = 365
MIN_SERIES_FOR_YEAR = 253    # 與價格報酬 (252 個交易日前) 相同


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_roc_date(text):
    """'114年11月03日' 或 '114/11/03' → '2025-11-03'；無法解析回傳 None。"""
    m = re.match(r"^\s*(\d{2,3})\s*(?:年|/)\s*(\d{1,2})\s*(?:月|/)\s*(\d{1,2})", str(text or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _idx(fields, *names):
    for n in names:
        if n in fields:
            return fields.index(n)
    return None


def parse_twse(payload):
    """TWT49U → [(代號, 除息日 ISO, 每單位現金配息)]。只取「息」(排除含股票股利的「權」)。"""
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return []
    fields = payload.get("fields") or []
    i_date, i_code, i_amt, i_kind = _idx(fields, "資料日期"), _idx(fields, "股票代號"), _idx(fields, "權值+息值"), _idx(fields, "權/息")
    if None in (i_date, i_code, i_amt, i_kind):
        raise ValueError(f"TWT49U 欄位改版：{fields}")
    out = []
    for r in payload.get("data") or []:
        kind = str(r[i_kind])
        d, amt = parse_roc_date(r[i_date]), _num(r[i_amt])
        if d and amt is not None and amt > 0 and "息" in kind and "權" not in kind:
            out.append((str(r[i_code]).strip(), d, amt))
    return out


def parse_tpex(payload):
    """櫃買 exDailyQ → [(代號, 除息日 ISO, 每單位現金配息)]；用「息值」欄 (現金部分)。"""
    if not isinstance(payload, dict) or str(payload.get("stat", "")).lower() != "ok":
        return []
    out = []
    for t in payload.get("tables") or []:
        fields = t.get("fields") or []
        i_date, i_code, i_amt = _idx(fields, "除權息日期"), _idx(fields, "代號"), _idx(fields, "息值")
        if None in (i_date, i_code, i_amt):
            if t.get("data"):
                raise ValueError(f"exDailyQ 欄位改版：{fields}")
            continue
        for r in t.get("data") or []:
            d, amt = parse_roc_date(r[i_date]), _num(r[i_amt])
            if d and amt is not None and amt > 0:
                out.append((str(r[i_code]).strip(), d, amt))
    return out


# ---------------------------------------------------------------------------
# 計算 (純函式)
# ---------------------------------------------------------------------------
def ttm_dividend(divs, last_date, window=WINDOW_DAYS):
    """divs: [(除息日 ISO, 每單位配息)]。回傳 (近 window 天合計, 筆數)。除息日在 last_date 之後的不計。"""
    end = date.fromisoformat(last_date)
    start = end - timedelta(days=window)
    sel = [a for d, a in divs if start < date.fromisoformat(d) <= end]
    return round(sum(sel), 4), len(sel)


def total_return_1y(series, divs, k=252):
    """
    series: [(日期, 收盤, ...)] 已是連續行情 (無分割斷層)；回傳近 k 個交易日含息報酬 (%)，不足回傳 None。
    除息日不在交易日序列時，併入其後第一個交易日。
    """
    if len(series) <= k:
        return None
    seg = series[-1 - k:]
    dates = [s[0] for s in seg]
    pend = {}
    for d, a in divs:
        # 找第一個 >= 除息日的交易日；除息日在視窗起點當天或之前者已反映在起點價格，不計
        pos = next((i for i, x in enumerate(dates) if x >= d), None)
        if pos is None or pos == 0:
            continue
        pend[pos] = pend.get(pos, 0.0) + a
    growth = 1.0
    for i in range(1, len(seg)):
        prev = seg[i - 1][1]
        if not prev:
            return None
        growth *= (seg[i][1] + pend.get(i, 0.0)) / prev
    return round((growth - 1.0) * 100, 2)


def dividend_metrics(series, divs, last_close, covered):
    """series: 連續行情；divs: [(除息日, 配息)]；covered: 配息表是否已成功涵蓋整個視窗。回傳 dict (不可算的欄位為 None)。"""
    out = {"div_ttm": None, "div_count": None, "dividend_yield_pct": None, "ret_1y_total": None, "div_note": None}
    if not covered:
        out["div_note"] = "配息表尚未成功取得，配息率與含息報酬留空"
        return out
    if len(series) < MIN_SERIES_FOR_YEAR:
        out["div_note"] = "上市未滿一年，配息率與含息報酬留空"
        return out
    last_date = series[-1][0]
    ttm, n = ttm_dividend(divs, last_date)
    out.update(div_ttm=ttm, div_count=n,
               dividend_yield_pct=round(ttm / last_close * 100, 2) if last_close else None,
               ret_1y_total=total_return_1y(series, divs))
    out["div_note"] = "近 12 個月沒有配息紀錄 (累積型或未配息)" if n == 0 else None
    return out


# ---------------------------------------------------------------------------
# 資料庫與網路
# ---------------------------------------------------------------------------
def refresh(conn, today=None):
    """抓取兩個市場的配息表並存入 etf_dividends；成功才更新 etf_dividend_fetch。回傳 {market: 筆數或錯誤}。"""
    from etf_live_data import tw_etf_codes
    today = today or date.today()
    s, e = today - timedelta(days=LOOKBACK_DAYS), today
    codes = set(tw_etf_codes(conn))
    res = {}
    plans = (("TWSE", URL_TWSE.format(s=s.strftime("%Y%m%d"), e=e.strftime("%Y%m%d")), parse_twse),
             ("TPEx", URL_TPEX.format(s=s.strftime("%Y/%m/%d"), e=e.strftime("%Y/%m/%d")), parse_tpex))
    cur = conn.cursor()
    for market, url, parser in plans:
        try:
            rows = [r for r in parser(fetch_json(url, timeout=60, retries=2)) if r[0] in codes]
        except Exception as exc:  # noqa: BLE001 — 失敗時保留舊資料與舊的涵蓋範圍，下次再試
            logger.warning("ETF 配息表 (%s) 取得失敗：%s: %s", market, type(exc).__name__, exc)
            res[market] = f"失敗：{type(exc).__name__}"
            continue
        ts = now_iso()
        cur.execute("DELETE FROM etf_dividends WHERE market = ? AND ex_date >= ?", (market, s.isoformat()))
        for code, d, amt in rows:
            cur.execute("INSERT OR REPLACE INTO etf_dividends (etf_code, ex_date, cash_per_unit, market, fetched_at) VALUES (?,?,?,?,?)",
                        (code, d, amt, market, ts))
        cur.execute("INSERT OR REPLACE INTO etf_dividend_fetch (market, start_date, end_date, fetched_at, row_count) VALUES (?,?,?,?,?)",
                    (market, s.isoformat(), e.isoformat(), ts, len(rows)))
        res[market] = len(rows)
    conn.commit()
    return res


def load(conn, today=None):
    """回傳 ({代號: [(除息日, 配息)]}, {市場: (涵蓋起, 涵蓋迄)})。"""
    divs = {}
    for r in conn.execute("SELECT etf_code, ex_date, cash_per_unit FROM etf_dividends ORDER BY ex_date"):
        divs.setdefault(r["etf_code"], []).append((r["ex_date"], r["cash_per_unit"]))
    cov = {r["market"]: (r["start_date"], r["end_date"]) for r in conn.execute("SELECT * FROM etf_dividend_fetch")}
    return divs, cov


def covers(cov, market, last_date):
    """該市場配息表是否涵蓋 [last_date − 365 天, last_date]；涵蓋迄日需不早於 last_date 之前 7 天 (表是逐日查詢，之後才除息的由下次抓取補上)。"""
    c = cov.get(market)
    if not c:
        return False
    start = date.fromisoformat(last_date) - timedelta(days=WINDOW_DAYS)
    return date.fromisoformat(c[0]) <= start and date.fromisoformat(c[1]) >= date.fromisoformat(last_date) - timedelta(days=7)
