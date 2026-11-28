"""
台股 ETF 基金規模與基本資料：由證交所 OpenAPI「基金基本資料彙總表」(t187ap47_L) 取得每檔上市 ETF 的
發行單位數、追蹤指數名稱、成立日期與上市日期，取代 etf_master 裡人工維護的規模與成立日期。

方法與限制：
- 基金規模 = 發行單位數 × 單位數日期當天的收盤價 (換算成億元)。這是「以市價計算的規模」，不是用淨值算的官方規模，
  折溢價小時兩者很接近 (淨值沒有免費官方來源)；畫面標示來源。
- 發行單位數只提供「最新一天」，沒有歷史，所以本站每次同步都記下一筆 (etf_units_history)，
  「近 1 月規模變化」與「近 1 月淨申購」要累積滿約一個月才算得出來，之前一律留空，不沿用手寫的舊數字。
- 近 1 月淨申購 = (現在單位數 − 約 30 天前單位數) × 現價。單位數只在申購／贖回時改變，所以這就是初級市場的淨申贖金額估計；
  區間內價格序列有分割斷層的 ETF 留空 (單位數也會跟著分割而變)。
- 上櫃掛牌的 ETF (例如 00937B、00679B) 這張表沒有收錄，也找不到免費官方來源，維持人工維護並標示。
- 費用率、追蹤誤差、持股權重在公開說明書與月報裡，沒有官方 API，維持人工維護。

純函式在前半，資料庫與網路在 refresh。
"""
import re
from datetime import date, timedelta

from common import fetch_json, logger, now_iso

URL_FUNDS = "https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
UNIT = "億元(TWD)"
CHANGE_MIN_DAYS = 28         # 近 1 月變化：基準日要在 28 天以前
CHANGE_MAX_DAYS = 45         # 且不能太舊 (超過 45 天視為沒有可比較的基準)
NO_INDEX = ("", "不適用", "N/A")


def roc_compact(text):
    """'1151127' → '2026-11-27'、'0920625' → '2003-06-25'；無法解析回傳 None。"""
    t = re.sub(r"\D", "", str(text or ""))
    if len(t) < 6:
        return None
    try:
        return date(int(t[:-4]) + 1911, int(t[-4:-2]), int(t[-2:])).isoformat()
    except ValueError:
        return None


def _units(x):
    try:
        v = int(float(str(x).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def parse_funds(rows):
    """→ {代號: {units, as_of, tracking_index, inception, listed}}；格式不符的列略過。"""
    out = {}
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        code = str(r.get("基金代號") or "").strip()
        units = _units(r.get("發行單位數/轉換數"))
        as_of = roc_compact(r.get("出表日期"))
        if not code or units is None or as_of is None:
            continue
        idx = str(r.get("標的指數/追蹤指數名稱") or "").strip()
        out[code] = {"units": units, "as_of": as_of, "tracking_index": None if idx in NO_INDEX else idx,
                     "inception": roc_compact(r.get("成立日期")), "listed": roc_compact(r.get("上市日期"))}
    return out


def _close_on_or_before(closes, day):
    """closes：[(日期, 收盤)] 依日期遞增；回傳 day 當天或之前最近一筆的收盤，沒有則 None。"""
    best = None
    for d, c in closes:
        if d <= day:
            best = c
        else:
            break
    return best


def aum_metrics(info, closes, history):
    """
    info：parse_funds 的單一項目；closes：連續行情 [(日期, 收盤)]；history：[(日期, 單位數)]。
    回傳 {aum_billion, aum_as_of, units, aum_change_1m_pct, net_creation_1m_billion}；沒有的值為 None。
    """
    res = {"aum_billion": None, "aum_as_of": None, "units": None, "aum_change_1m_pct": None, "net_creation_1m_billion": None}
    if not info or not closes:
        return res
    px = _close_on_or_before(closes, info["as_of"]) or closes[-1][1]
    if not px:
        return res
    now_aum = info["units"] * px
    res.update(aum_billion=round(now_aum / 1e8, 1), aum_as_of=info["as_of"], units=info["units"])
    as_of = date.fromisoformat(info["as_of"])
    lo, hi = (as_of - timedelta(days=CHANGE_MAX_DAYS)).isoformat(), (as_of - timedelta(days=CHANGE_MIN_DAYS)).isoformat()
    cands = [(d, u) for d, u in history if lo <= d <= hi]
    if not cands:
        return res
    then_d, then_u = cands[-1]
    then_px = None
    if closes[0][0] <= then_d:             # 基準日必須落在連續行情內 (沒有分割斷層)，否則單位數與價格不可比
        then_px = _close_on_or_before(closes, then_d)
    if then_px:
        res["aum_change_1m_pct"] = round((now_aum / (then_u * then_px) - 1) * 100, 1)
        res["net_creation_1m_billion"] = round((info["units"] - then_u) * px / 1e8, 2)
    return res


def refresh(conn, codes):
    """抓取基金基本資料表，存入 etf_fund_info 與 etf_units_history。失敗時保留舊資料。回傳 {'rows': 筆數} 或 {'error': ...}。"""
    try:
        funds = parse_funds(fetch_json(URL_FUNDS, timeout=60, retries=2))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ETF 基金基本資料取得失敗：%s: %s", type(exc).__name__, exc)
        return {"error": f"{type(exc).__name__}"}
    ts = now_iso()
    cur = conn.cursor()
    n = 0
    for code in codes:
        f = funds.get(code)
        if not f:
            continue
        cur.execute("""INSERT OR REPLACE INTO etf_fund_info (etf_code, tracking_index, inception_date, listing_date, units, as_of_date, fetched_at)
                       VALUES (?,?,?,?,?,?,?)""", (code, f["tracking_index"], f["inception"], f["listed"], f["units"], f["as_of"], ts))
        cur.execute("INSERT OR REPLACE INTO etf_units_history (etf_code, as_of_date, units, fetched_at) VALUES (?,?,?,?)",
                    (code, f["as_of"], f["units"], ts))
        n += 1
    conn.commit()
    return {"rows": n}


def load(conn):
    """回傳 ({代號: info}, {代號: [(日期, 單位數)]})，資料來自資料庫 (不連網)。"""
    info = {}
    for r in conn.execute("SELECT * FROM etf_fund_info"):
        info[r["etf_code"]] = {"units": r["units"], "as_of": r["as_of_date"], "tracking_index": r["tracking_index"],
                               "inception": r["inception_date"], "listed": r["listing_date"]}
    hist = {}
    for r in conn.execute("SELECT etf_code, as_of_date, units FROM etf_units_history ORDER BY as_of_date"):
        hist.setdefault(r["etf_code"], []).append((r["as_of_date"], r["units"]))
    return info, hist
