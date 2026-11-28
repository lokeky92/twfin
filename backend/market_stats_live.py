"""
市場籌碼統計的即時化：融資餘額 (證交所) 與外資臺股期貨未平倉淨部位 (期交所)，補進三大法人逐日列。

原本這兩欄在官方逐日列 (BFI82U) 裡一律是空的，畫面顯示「—」，只有手寫的舊列有數字。

來源 (免費、免金鑰、官方)：
- 證交所 RWD 信用交易統計 MI_MARGN (selectType=MS)：「融資金額(仟元)」今日餘額 → 億元。可指定日期，所以能回補缺漏的日子。
- 期交所 OpenAPI「三大法人-區分各期貨契約-依日期」：契約「臺股期貨」、身份別「外資及陸資」的多空未平倉口數淨額。
  這個 API 只提供最新一個交易日，沒有歷史，所以只能從開始抓的那天起逐日累積，不回補。

規則：
- 官方值存在 market_stats_official (以日期為鍵)；標示「官方API」的逐日列的這兩欄一律從它同步，沒有官方值就留空 (清掉手寫殘留)，
  不用別天的數字頂替。
- 融資餘額採該日「今日餘額」(證交所說明以隔日的「前日餘額」為最終值，當日值可能微調，畫面標示來源即可)。
- 期貨口徑只含「臺股期貨」(大台)，不含小型／微型臺指，不是各家媒體換算成大台等值的口數；畫面備註標明。
- 任一來源失敗只記錄、保留既有資料，絕不寫入 0。
"""
import csv
import io
import json
import re
import urllib.request
from datetime import date

from common import _SSL_CTX, _USER_AGENT, describe_error, fetch_json, logger, now_iso

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


# 期交所同一個端點依來源不同，有時回傳 JSON、有時回傳 CSV (欄位名稱是中文)；兩種格式的欄位對照
CSV_FIELDS = {"日期": "Date", "商品名稱": "ContractCode", "身份別": "Item", "多空未平倉口數淨額": "OpenInterest(Net)"}


def parse_taifex_body(raw):
    """期交所回應 (bytes) → list[dict]，鍵為 JSON 版的英文欄位名；JSON 或 CSV 都接受，兩者都不是就丟 ValueError。"""
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except ValueError:
        pass
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "身份別" not in rows[0]:
        raise ValueError("期交所回應格式無法辨識：" + " ".join(text[:60].split()))
    def name(k):
        k = k.strip()
        if "未平倉口數" in k and "淨額" in k:          # 「多空未平倉口數淨額」：欄名若有細微差異仍可對上
            return "OpenInterest(Net)"
        return CSV_FIELDS.get(k, k)
    return [{name(k): v for k, v in r.items() if k} for r in rows]


def _fetch_taifex_rows(url):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
        return parse_taifex_body(resp.read())


def parse_foreign_oi(rows):
    """期交所資料列 → (ISO 日期, 外資及陸資臺股期貨多空未平倉淨口數)；找不到回傳 None。"""
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
    """
    抓取最新融資餘額與外資期貨未平倉，記入 market_stats_official (官方值的唯一來源)，再把它們同步到官方逐日列。
    同步時「官方逐日列」的這兩欄一律以 market_stats_official 為準：沒有官方值的日子留空，
    所以舊的手寫數字 (例如曾誤植在官方列上的 8,343 億) 不會留在官方列上。
    """
    from db import get_connection
    fj = (fetchers or {}).get("json") or (lambda u: fetch_json(u, timeout=45, retries=2))
    ftx = (fetchers or {}).get("taifex") or _fetch_taifex_rows
    own = conn is None
    conn = conn or get_connection()
    status, written = {}, {"margin": [], "futures": []}
    try:
        cur = conn.cursor()
        like = f"%{OFFICIAL_LABEL}%"
        ts = now_iso()

        def put(d, margin=None, futures=None):
            cur.execute("INSERT OR IGNORE INTO market_stats_official (release_date, fetched_at) VALUES (?, ?)", (d, ts))
            if margin is not None:
                cur.execute("UPDATE market_stats_official SET margin_balance_billion = ?, fetched_at = ? WHERE release_date = ?", (margin, ts, d))
                written["margin"].append(d)
            if futures is not None:
                cur.execute("UPDATE market_stats_official SET foreign_futures_oi_contracts = ?, fetched_at = ? WHERE release_date = ?", (futures, ts, d))
                written["futures"].append(d)

        # 1. 最新融資餘額 (今天的日期；非交易日或尚未公布就略過) 與回補官方逐日列中還沒有官方融資餘額的日子
        try:
            latest = parse_margin(fj(URL_MARGIN.format(d=date.today().strftime("%Y%m%d"))))
            status["TWSE 融資餘額"] = "OK" if latest else "非交易日或尚未公布"
            if latest:
                put(latest[0], margin=latest[1])
        except Exception as exc:  # noqa: BLE001
            logger.warning("融資餘額取得失敗：%s: %s", type(exc).__name__, exc)
            status["TWSE 融資餘額"] = f"失敗：{describe_error(exc)}"
        missing = [r["release_date"] for r in cur.execute(
            "SELECT DISTINCT f.release_date FROM institutional_flows f LEFT JOIN market_stats_official o ON o.release_date = f.release_date "
            "WHERE f.period_type = 'DAILY' AND f.period_label LIKE ? AND o.margin_balance_billion IS NULL "
            "ORDER BY f.release_date DESC LIMIT ?", (like, max_backfill)).fetchall()]
        filled = 0
        for d in missing:
            try:
                res = parse_margin(fj(URL_MARGIN.format(d=d.replace("-", ""))))
            except Exception as exc:  # noqa: BLE001 — 回補失敗不影響其他日子，下次再試
                logger.warning("融資餘額回補 %s 失敗：%s", d, type(exc).__name__)
                break
            if res and res[0] == d:                           # 回傳日期必須與要求的相同才寫入
                put(d, margin=res[1])
                filled += 1
        if missing:
            status["融資餘額回補"] = f"{filled}/{len(missing)} 日"

        # 2. 外資臺股期貨未平倉 (期交所只有最新一天，不回補)
        try:
            oi = parse_foreign_oi(ftx(URL_TAIFEX))
            status["TAIFEX 外資期貨未平倉"] = "OK" if oi else "解析不到資料"
            if oi:
                put(oi[0], futures=oi[1])
        except Exception as exc:  # noqa: BLE001
            logger.warning("外資期貨未平倉取得失敗：%s: %s", type(exc).__name__, exc)
            status["TAIFEX 外資期貨未平倉"] = f"失敗：{describe_error(exc)}"

        # 3. 同步到官方逐日列：沒有官方值的日子一律留空 (清掉任何手寫殘留)；對不到官方逐日列的官方值不寫
        cur.execute("""UPDATE institutional_flows SET
                         margin_balance_billion = (SELECT o.margin_balance_billion FROM market_stats_official o WHERE o.release_date = institutional_flows.release_date),
                         foreign_futures_oi_contracts = (SELECT o.foreign_futures_oi_contracts FROM market_stats_official o WHERE o.release_date = institutional_flows.release_date)
                       WHERE period_type = 'DAILY' AND period_label LIKE ?""", (like,))
        conn.commit()
        return {"written": written, "status": status}
    finally:
        if own:
            conn.close()
