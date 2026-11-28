"""
市場籌碼統計的即時化：融資餘額 (證交所) 與外資臺股期貨未平倉淨部位 (期交所)，補進三大法人逐日列。

原本這兩欄在官方逐日列 (BFI82U) 裡一律是空的，畫面顯示「—」，只有手寫的舊列有數字。

來源 (免費、免金鑰、官方)：
- 證交所 RWD 信用交易統計 MI_MARGN (selectType=MS)：「融資金額(仟元)」今日餘額 → 億元。可指定日期，所以能回補缺漏的日子。
- 期交所 OpenAPI「三大法人-區分各期貨契約-依日期」：契約「臺股期貨」、身份別「外資及陸資」的多空未平倉口數淨額。
  這個 API 只提供最新一個交易日，沒有歷史，所以只能從開始抓的那天起逐日累積，不回補。

規則：
- 只更新同一天、標示「官方API」的逐日列；對不到日期的不寫 (不用別天的數字頂替)。
- 融資餘額採該日「今日餘額」(證交所說明以隔日的「前日餘額」為最終值，當日值可能微調，畫面標示來源即可)。
- 期貨口徑只含「臺股期貨」(大台)，不含小型／微型臺指，不是各家媒體換算成大台等值的口數；畫面備註標明。
- 任一來源失敗只記錄、保留既有資料，絕不寫入 0。
"""
import re
from datetime import date

from common import fetch_json, logger

URL_MARGIN = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d}&selectType=MS&response=json"
URL_TAIFEX = "https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate"
MAX_BACKFILL = 10               # 每次最多回補幾個缺融資餘額的交易日 (逐日查詢，限量避免對證交所造成負擔)
OFFICIAL_LABEL = "官方API"


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _iso(yyyymmdd):
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", str(yyyymmdd or "").strip())
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def parse_margin(payload):
    """MI_MARGN → (ISO 日期, 融資餘額 億元)；非 OK、找不到「融資金額(仟元)」列或數字無法解析回傳 None。"""
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return None
    d = _iso(payload.get("date"))
    for t in payload.get("tables") or []:
        fields = t.get("fields") or []
        if "今日餘額" not in fields:
            continue
        i = fields.index("今日餘額")
        for r in t.get("data") or []:
            if r and str(r[0]).strip() == "融資金額(仟元)" and len(r) > i:
                v = _num(r[i])
                if d and v is not None and v > 0:
                    return d, round(v / 1e5, 1)         # 仟元 → 億元 (1 億 = 100,000 仟元)
    return None


def parse_foreign_oi(rows):
    """期交所 JSON → (ISO 日期, 外資及陸資臺股期貨多空未平倉淨口數)；找不到回傳 None。"""
    if not isinstance(rows, list):
        return None
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("ContractCode") == "臺股期貨" and str(r.get("Item") or "").startswith("外資"):
            v, d = _num(r.get("OpenInterest(Net)")), _iso(r.get("Date"))
            if v is not None and d:
                return d, int(v)
    return None


def apply_market_stats(conn=None, fetchers=None, max_backfill=MAX_BACKFILL):
    """抓取最新融資餘額與外資期貨未平倉，補進同一天的官方逐日列；另回補最近缺融資餘額的幾個交易日。"""
    from db import get_connection
    fj = (fetchers or {}).get("json") or (lambda u: fetch_json(u, timeout=45, retries=2))
    own = conn is None
    conn = conn or get_connection()
    status, written = {}, {"margin": [], "futures": []}
    try:
        cur = conn.cursor()
        like = f"%{OFFICIAL_LABEL}%"

        def set_margin(d, v):
            n = cur.execute("UPDATE institutional_flows SET margin_balance_billion = ? WHERE period_type = 'DAILY' "
                            "AND release_date = ? AND period_label LIKE ?", (v, d, like)).rowcount
            if n:
                written["margin"].append(d)
            return n

        # 1. 最新融資餘額 (不指定日期 → 證交所回傳最新一天) 與回補缺漏
        try:
            latest = parse_margin(fj(URL_MARGIN.format(d=date.today().strftime("%Y%m%d"))))
            status["TWSE 融資餘額"] = "OK" if latest else "非交易日或尚未公布"
            if latest:
                set_margin(*latest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("融資餘額取得失敗：%s: %s", type(exc).__name__, exc)
            status["TWSE 融資餘額"] = f"失敗：{type(exc).__name__}"
        missing = [r["release_date"] for r in cur.execute(
            "SELECT release_date FROM institutional_flows WHERE period_type = 'DAILY' AND period_label LIKE ? "
            "AND margin_balance_billion IS NULL ORDER BY release_date DESC LIMIT ?", (like, max_backfill)).fetchall()]
        filled = 0
        for d in missing:
            try:
                res = parse_margin(fj(URL_MARGIN.format(d=d.replace("-", ""))))
            except Exception as exc:  # noqa: BLE001 — 回補失敗不影響其他日子，下次再試
                logger.warning("融資餘額回補 %s 失敗：%s", d, type(exc).__name__)
                break
            if res and res[0] == d:                           # 回傳日期必須與要求的相同才寫入
                set_margin(*res)
                filled += 1
        if missing:
            status["融資餘額回補"] = f"{filled}/{len(missing)} 日"

        # 2. 外資臺股期貨未平倉 (只有最新一天)
        try:
            oi = parse_foreign_oi(fj(URL_TAIFEX))
            status["TAIFEX 外資期貨未平倉"] = "OK" if oi else "解析不到資料"
            if oi:
                n = cur.execute("UPDATE institutional_flows SET foreign_futures_oi_contracts = ? WHERE period_type = 'DAILY' "
                                "AND release_date = ? AND period_label LIKE ?", (oi[1], oi[0], like)).rowcount
                if n:
                    written["futures"].append(oi[0])
                else:
                    status["TAIFEX 外資期貨未平倉"] = f"{oi[0]} 沒有對應的官方逐日列，未寫入"
        except Exception as exc:  # noqa: BLE001
            logger.warning("外資期貨未平倉取得失敗：%s: %s", type(exc).__name__, exc)
            status["TAIFEX 外資期貨未平倉"] = f"失敗：{type(exc).__name__}"
        conn.commit()
        return {"written": written, "status": status}
    finally:
        if own:
            conn.close()
