"""
資料來源健康度判定 (純函式，不依賴資料庫與網路，方便單元測試)。

狀態：
  OK        成功取得，筆數與資料日期都正常
  DEGRADED  成功取得，但筆數比前次少超過 50%（官方改版或回傳不完整的徵兆）
  STALE     成功取得，但資料日期已落後超過 STALE_BUSINESS_DAYS 個營業日
  FAILED    本次擷取失敗（沿用上一次的資料，不寫入假日期）
  EMPTY     擷取成功但沒有任何資料列

CRITICAL_SOURCES 失敗代表核心資料缺失，排程應整體失敗，避免把舊資料當成新資料發佈。
"""
from datetime import date, datetime

STALE_BUSINESS_DAYS = 4
DROP_RATIO = 0.5

# source_key -> (顯示名稱, 資料日期是否每個營業日更新, 是否為關鍵來源)
SOURCES = {
    "twse_rev":  ("上市公司月營收 (MOPS t187ap05_L)", False, True),
    "tpex_rev":  ("上櫃公司月營收 (MOPS t187ap05_O)", False, True),
    "twse_pe":   ("上市本益比/股價淨值比 (BWIBBU_ALL)", True, False),
    "tpex_pe":   ("上櫃本益比/股價淨值比", True, False),
    "twse_t86":  ("上市三大法人個股買賣超 (T86)", True, False),
    "tpex_3i":   ("上櫃三大法人個股買賣超", True, False),
    "mi_index":  ("大盤與類股指數 (MI_INDEX)", True, False),
    "bfi82u":    ("三大法人買賣金額統計 (BFI82U)", True, False),
    "twse_quotes": ("上市個股每日收盤行情 (MI_INDEX ALLBUT0999)", True, False),
    "tpex_quotes": ("上櫃個股每日收盤行情", True, False),
}
CRITICAL_SOURCES = tuple(k for k, v in SOURCES.items() if v[2])


def parse_date(value):
    """接受 'YYYYMMDD'、'YYYY-MM-DD'、民國 'YYYMMDD' (7 碼)；無法解析回傳 None。"""
    if value is None:
        return None
    s = str(value).strip().replace("-", "").replace("/", "")
    if not s.isdigit():
        return None
    try:
        if len(s) == 8:
            return datetime.strptime(s, "%Y%m%d").date()
        if len(s) == 7:
            return date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    except ValueError:
        return None
    return None


def business_days_between(start, end):
    """start (不含) 到 end (含) 之間的週一~週五天數；未考慮國定假日，所以門檻要寬鬆。"""
    if start is None or end is None or end <= start:
        return 0
    days = 0
    d = start
    while d < end:
        d = date.fromordinal(d.toordinal() + 1)
        if d.weekday() < 5:
            days += 1
    return days


def classify(ok, count, prev_count, data_date, today, daily=True):
    """回傳 (status, message)。"""
    if not ok:
        return "FAILED", "本次擷取失敗，沿用上一次的資料"
    if not count:
        return "EMPTY", "擷取成功但沒有任何資料列"
    if prev_count and count < prev_count * DROP_RATIO:
        return "DEGRADED", f"筆數 {count} 比前次 {prev_count} 少超過 {int(DROP_RATIO * 100)}%，可能是回傳不完整"
    if daily:
        d = parse_date(data_date)
        if d is not None and business_days_between(d, today) > STALE_BUSINESS_DAYS:
            return "STALE", f"資料日期 {d.isoformat()} 已落後 {business_days_between(d, today)} 個營業日"
    return "OK", "正常"


def critical_failures(statuses):
    """statuses: {source_key: status}。回傳需要讓排程失敗的來源清單。"""
    bad = ("FAILED", "EMPTY")
    return [k for k in CRITICAL_SOURCES if statuses.get(k) in bad or k not in statuses]


def age_status(data_date, today, daily=True):
    """依資料日期在『顯示當下』重新判斷是否過期 (靜態網站會比擷取時間更老)。"""
    if not daily:
        return None
    d = parse_date(data_date)
    if d is None:
        return None
    n = business_days_between(d, today)
    return "STALE" if n > STALE_BUSINESS_DAYS else "OK"


def minguo_ym_to_iso(data_ym):
    """'11510' -> '2026-10'；無法解析回傳原字串。"""
    s = str(data_ym or "").strip()
    if len(s) in (5, 6) and s.isdigit():
        return f"{int(s[:-2]) + 1911}-{s[-2:]}"
    return s
