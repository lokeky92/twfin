"""
總體經濟月統計的即時化：從官方開放資料取得最新數值，取代 seed 裡「寫死到 2026-10 為止」的手寫列。

來源 (全部免費、不需金鑰，除了 FRED)：
- 中央銀行 cpx.cbc.gov.tw 資料 API：EF01M01 (M1B、M2 日平均年增率)、EF07M01 (外匯存底、CPI 年增率)、BP01D01 (新台幣對美元日匯率)、
  EF03M01 (貨幣機構外匯存款期底餘額)、EFA4M01 (貨幣機構放款與投資年增率)、EH45m01 (五大銀行新承作購屋貸款金額)；
  項目代號取自央行「統計資料庫 API 說明文件」的官方代號表 (https://cpx.cbc.gov.tw/Data/ExportToAPIInfo)
- 國發會 景氣指標及燈號 (data.gov.tw 資料集 6099，ZIP/CSV)：景氣對策信號綜合分數與燈號、五大銀行新承做放款平均利率
- 財政部 進出口貿易統計 (data.gov.tw 資料集 8378，CSV)：海關出口單月金額 (百萬美元)
- 經濟部統計處 外銷訂單 (data.gov.tw 資料集 101580，CSV「按地區分」的「地區別總計」)：外銷訂單單月金額 (百萬美元)
- 全市場上市櫃公司月營收合計：由已累積的 MOPS 月營收 (live_company_fundamentals) 加總
- FRED (需要免費金鑰，環境變數 FRED_API_KEY，沒有就整段略過)：美國 10 年期公債殖利率 (DGS10)、聯邦資金利率目標上限 (DFEDTARU)、VIX (VIXCLS)、聯準會廣義美元指數 (DTWEXBGS，不是 ICE 的 DXY)

規則：
- 官方資料比 seed 新或一樣新才取代：刪除 seed 裡「期間 ≤ 官方最新期間」的手寫列，之後的手寫列 (官方還沒公布的期間) 保留，畫面標示版本。
- 任何來源失敗都只記錄，保留既有資料 (含先前累積的即時列)；不拿手寫值冒充，也不把失敗當成 0。
- 備註文字由規則產生 (來源、期間、燈號)，不含敘事；年增率若官方沒給就由同表歷史計算，算不出來就留空。
- 仍是手寫、沒有可程式取得的免費官方來源的指標 (GDP、存放款餘額、證券劃撥、ICE 美元指數 DXY、SOX 等) 維持原樣並標示。

純函式在前半 (parse_*、build_rows)，網路與資料庫在 apply_live_macro。
"""
import csv
import io
import os
import re
import zipfile
from datetime import date, datetime, timedelta

from common import fetch_json, logger, now_iso

URL_CBC = "https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName={f}"
URL_NDC = "https://ws.ndc.gov.tw/Download.ashx?u=LzAwMS9hZG1pbmlzdHJhdG9yLzEwL3JlbGZpbGUvNTc4MS82MzkyL2VhMjM1YmQ5LWQwNTItNGE2OS1hYmZjLWQ1Yzc4NWQzZDBlMi56aXA%3d&n=5pmv5rCj5oyH5qiZ5Y%2bK54eI6JmfLnppcA%3d%3d&icon=.zip"
URL_NDC_DATASET = "https://data.gov.tw/api/v2/rest/dataset/6099"
URL_MOF = "https://web02.mof.gov.tw/njswww/webMain.aspx?sys=220&ym=9000&kind=21&type=4&funid=i8101&cycle=41&outmode=12&compmode=00&outkind=1&fld0=1&codlst0=11001001&utf=1"
URL_MOEA_ORDERS = "https://service.moea.gov.tw/EE520/opendata/%E7%B6%93%E6%BF%9F%E9%83%A8%E7%B5%B1%E8%A8%88%E8%99%95_%E5%A4%96%E9%8A%B7%E8%A8%82%E5%96%AE_%E6%8C%89%E5%9C%B0%E5%8D%80%E5%88%86.csv"
URL_FRED = "https://api.stlouisfed.org/fred/series/observations?series_id={sid}&api_key={key}&file_type=json&observation_start={start}"
REVISION = "live (官方開放資料)"
KEEP_MONTHS = 14
KEEP_DAYS = 30
NEW_DICTIONARY = {
    "INTL_USD_BROAD": ("INTL_USD_BROAD", "廣義美元指數 (聯準會 Nominal Broad Dollar Index)", "M03", "SRC_FED_UST", "DIRECT_STAT", "點(2006-01=100)", "USD", "NSA",
                       "聯準會 H.10 對廣義貿易夥伴貨幣的名目加權美元指數 (經 FRED DTWEXBGS 取得)；不是 ICE 美元指數 DXY，兩者數值不同",
                       "衡量美元對一籃子貿易夥伴貨幣的整體強弱", "MARK_MISSING_NO_IMPUTE"),
    "INTL_VIX": ("INTL_VIX", "VIX 恐慌指數 (CBOE)", "M03", "SRC_FED_UST", "DIRECT_STAT", "點", "USD", "NSA",
                 "CBOE S&P 500 波動率指數收盤 (經 FRED VIXCLS 取得)", "衡量美股選擇權隱含波動，風險偏好的即時指標", "MARK_MISSING_NO_IMPUTE"),
}


# ---------------------------------------------------------------------------
# 解析 (純函式)
# ---------------------------------------------------------------------------
def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def cbc_period(p):
    """'2026M09' → '2026-09'；'20261030' → '2026-10-30'；其他回傳 None。"""
    p = str(p).strip()
    m = re.match(r"^(\d{4})M(\d{2})$", p)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", p)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def parse_cbc(payload, t1, t2=None, t3=None):
    """
    央行資料 API 的 JSON → [(期間, 數值)] 由舊到新。欄位依 structure 的標籤對應 (不靠位置)，
    改版時找不到標籤就丟 ValueError，不會悄悄取錯欄。
    """
    try:
        struct = payload["data"]["structure"]
        rows = payload["data"]["dataSets"]
    except (KeyError, TypeError) as exc:
        raise ValueError("央行 API 回應格式改版") from exc

    def labels(name):
        return [x["data"].strip() for x in struct.get(name, [])]

    L1, L2, L3 = labels("Table1"), labels("Table2"), labels("Table3")

    def pos(L, want):
        if want is None:
            if len(L) > 1:
                raise ValueError("缺少欄位條件")
            return 0
        if want not in L:
            raise ValueError(f"央行表欄位找不到：{want}（有：{L}）")
        return L.index(want)

    i1 = pos(L1, t1)
    i2 = pos(L2, t2) if L2 else 0
    i3 = pos(L3, t3) if L3 else 0
    offset = (i1 * max(1, len(L2)) + i2) * max(1, len(L3)) + i3
    out = []
    for r in rows:
        per = cbc_period(r[0])
        if per is None or len(r) <= offset + 1:
            continue
        v = _num(r[offset + 1])
        if v is not None:
            out.append((per, v))
    return sorted(out)


def parse_ndc_zip(raw):
    """國發會 ZIP → {'score': [(YYYY-MM, 分數, 燈號)], 'five_rate': [(YYYY-MM, 利率)]}；找不到欄位的項目為空 list。"""
    out = {"score": [], "five_rate": []}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".csv") or info.filename.lower().startswith("schema") or "manifest" in info.filename.lower():
                continue
            data = z.read(info)
            text = None
            for enc in ("utf-8-sig", "big5"):
                try:
                    text = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if not text:
                continue
            rows = list(csv.reader(io.StringIO(text)))
            if not rows:
                continue
            head = rows[0]
            if "景氣對策信號綜合分數" in head and "景氣對策信號" in head:
                i_s, i_c = head.index("景氣對策信號綜合分數"), head.index("景氣對策信號")
                for r in rows[1:]:
                    v = _num(r[i_s]) if len(r) > i_s else None
                    ym = str(r[0]).strip()
                    if v is not None and re.match(r"^\d{6}$", ym):
                        out["score"].append((f"{ym[:4]}-{ym[4:]}", v, r[i_c].strip() if len(r) > i_c else ""))
            col = "五大銀行新承做放款平均利率(年息百分比)"
            if col in head:
                i = head.index(col)
                for r in rows[1:]:
                    v = _num(r[i]) if len(r) > i else None
                    ym = str(r[0]).strip()
                    if v is not None and re.match(r"^\d{6}$", ym):
                        out["five_rate"].append((f"{ym[:4]}-{ym[4:]}", v))
    for k in out:
        out[k].sort()
    return out


def parse_mof_trade(text):
    """財政部進出口 CSV → [(YYYY-MM, 出口總值 百萬美元)]。只取「115年 10月」這種月資料列。"""
    out = []
    for r in csv.reader(io.StringIO(text.lstrip("﻿"))):
        m = re.match(r"^\s*(\d{2,3})年\s*(\d{1,2})月\s*$", r[0]) if r else None
        if not m or len(r) < 3:
            continue
        v = _num(r[2])
        if v is not None:
            out.append((f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}", v))
    return sorted(out)


def parse_moea_orders(text):
    """經濟部統計處外銷訂單 CSV (按地區分) → [(YYYY-MM, 外銷訂單金額 百萬美元)]，只取「地區別總計」。民國年月 '11510' → 2026-10。"""
    out = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        if str(r.get("地區代碼") or "").strip() != "00" or str(r.get("統計項目") or "").strip() != "外銷訂單金額_美元":
            continue
        m = re.match(r"^(\d{2,3})(\d{2})$", str(r.get("資料期(民國年)") or "").strip())
        v = _num(r.get("統計值(金額)"))
        if m and v is not None and 1 <= int(m.group(2)) <= 12:
            out.append((f"{int(m.group(1)) + 1911}-{m.group(2)}", v))
    return sorted(out)


def parse_fred(payload):
    """FRED observations JSON → [(日期, 數值)]；'.' (缺值) 略過。"""
    if not isinstance(payload, dict) or "observations" not in payload:
        raise ValueError(f"FRED 回應異常：{str(payload)[:120]}")
    out = []
    for o in payload["observations"]:
        v = _num(o.get("value"))
        if v is not None and re.match(r"^\d{4}-\d{2}-\d{2}$", str(o.get("date"))):
            out.append((o["date"], v))
    return sorted(out)


# ---------------------------------------------------------------------------
# 組成資料列 (純函式)
# ---------------------------------------------------------------------------
def _prior_year_value(points, per):
    """同一序列中一年前的值：月資料取 12 個月前同月；日資料取 365 天前或更早的最近一筆。找不到回傳 None。"""
    if len(per) == 7:
        y, m = int(per[:4]), int(per[5:7])
        key = f"{y - 1}-{m:02d}"
        return dict(points).get(key)
    target = (date.fromisoformat(per) - timedelta(days=365)).isoformat()
    cand = [v for p, v in points if p <= target and len(p) == 10]
    # 一年前那天附近必須有資料 (10 天內)，否則資料有缺口，不硬算
    if not cand:
        return None
    last_p = [p for p, _ in points if p <= target and len(p) == 10][-1]
    return cand[-1] if (date.fromisoformat(target) - date.fromisoformat(last_p)).days <= 10 else None


def build_rows(points, mode, scale=1.0, keep=None, note_fn=None):
    """
    points: [(期間, 數值)]。mode：
      'yoy_rate'：數值本身就是年增率 (M1B、CPI、放款利率…)：年增 = 數值，期增 = 與前期的差 (百分點)。
      'level'   ：水準值 (外匯存底、出口、匯率…)：期增 = 與前期的百分比變化，年增由同序列一年前的值計算。
      'score'   ：分數 (景氣燈號)：期增 = 與前期的差，沒有年增。
    回傳最近 keep 筆的 dict 列 (舊到新)。
    """
    pts = [(p, v) for p, v in points if v is not None]
    scaled = [(p, v * scale) for p, v in pts]
    rows = []
    for i, (p, v) in enumerate(scaled):
        prev = scaled[i - 1][1] if i > 0 else None
        if mode == "level":
            mom = round((v / prev - 1) * 100, 2) if prev else None
            py = _prior_year_value(scaled, p)
            yoy = round((v / py - 1) * 100, 2) if py else None
        elif mode == "yoy_rate":
            mom = round(v - prev, 3) if prev is not None else None
            yoy = round(v, 3)
        else:
            mom = round(v - prev, 3) if prev is not None else None
            yoy = None
        rows.append({"period": p, "raw": round(v, 4), "prev": None if prev is None else round(prev, 4), "mom": mom, "yoy": yoy,
                     "note": note_fn(p, v) if note_fn else ""})
    return rows[-keep:] if keep else rows


def spread_points(a, b):
    """兩個同期間序列相減 (a − b)，只保留兩邊都有的期間。"""
    bd = dict(b)
    return [(p, round(v - bd[p], 3)) for p, v in a if p in bd]


def month_total_points(conn):
    """全體上市櫃公司最新一期月營收合計 (兆元)：只在涵蓋公司數夠多時才算。回傳 ([(YYYY-MM, 兆元)], 上月兆元, 去年同月兆元, 公司數)。"""
    rows = conn.execute("""SELECT data_ym, COUNT(*) n, SUM(rev_current_thousand) cur, SUM(rev_prev_month_thousand) prv, SUM(rev_last_year_thousand) ly
                           FROM live_company_fundamentals WHERE rev_current_thousand IS NOT NULL GROUP BY data_ym ORDER BY data_ym""").fetchall()
    if not rows:
        return None
    biggest = max(r["n"] for r in rows)
    ok = [r for r in rows if r["n"] >= 0.9 * biggest]
    if not ok:
        return None
    r = ok[-1]
    ym = str(r["data_ym"])
    if not (ym.isdigit() and len(ym) >= 4):
        return None
    per = f"{int(ym[:-2]) + 1911}-{int(ym[-2:]):02d}"
    return {"period": per, "value": r["cur"] / 1e9, "prev": (r["prv"] / 1e9) if r["prv"] else None, "ly": (r["ly"] / 1e9) if r["ly"] else None, "companies": r["n"]}


# ---------------------------------------------------------------------------
# 網路與資料庫
# ---------------------------------------------------------------------------
def _http_bytes(url, timeout=60):
    import urllib.request
    from common import _SSL_CTX, _USER_AGENT
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return resp.read()


def _release(cbc_payload):
    try:
        return str(cbc_payload["meta"]["last_updated"])[:10]
    except (KeyError, TypeError):
        return None


def gather(fred_key=None, fetch_json_fn=None, fetch_bytes_fn=None):
    """抓取全部來源 → ({metric_code: spec dict}, {來源: 狀態文字})。spec: {rows, release, unit_note, source}。"""
    fj = fetch_json_fn or (lambda u: fetch_json(u, timeout=60, retries=2))
    fb = fetch_bytes_fn or _http_bytes
    specs, status = {}, {}

    def cbc(name, f):
        try:
            payload = fj(URL_CBC.format(f=f))
            status[name] = "OK"
            return payload
        except Exception as exc:  # noqa: BLE001
            logger.warning("總體資料 %s 取得失敗：%s: %s", name, type(exc).__name__, exc)
            status[name] = f"失敗：{type(exc).__name__}"
            return None

    p = cbc("CBC EF01M01", "EF01M01")
    if p:
        try:
            m1b = parse_cbc(p, "貨幣總計數-M1B", "日平均", "年增率")
            m2 = parse_cbc(p, "貨幣總計數-M2", "日平均", "年增率")
            rel = _release(p)
            n = lambda lbl: (lambda per, v: f"央行金融統計月報 EF01M01：{lbl}日平均年增率 {v:.2f}%（{per}）")   # noqa: E731
            specs["TW_M1B_YOY"] = {"rows": build_rows(m1b, "yoy_rate", keep=KEEP_MONTHS, note_fn=n("M1B")), "release": rel}
            specs["TW_M2_YOY"] = {"rows": build_rows(m2, "yoy_rate", keep=KEEP_MONTHS, note_fn=n("M2")), "release": rel}
            specs["TW_M1B_M2_SPREAD"] = {"rows": build_rows(spread_points(m1b, m2), "score", keep=KEEP_MONTHS,
                                                            note_fn=lambda per, v: f"M1B 年增率減 M2 年增率 = {v:+.2f} 個百分點（{per}，央行 EF01M01）"), "release": rel}
        except ValueError as exc:
            status["CBC EF01M01"] = f"解析失敗：{exc}"
    p = cbc("CBC EF07M01", "EF07M01")
    if p:
        try:
            rel = _release(p)
            fx = parse_cbc(p, "外匯存底(百萬美元)")
            cpi = parse_cbc(p, "消費者物價指數年增率")
            specs["TW_FX_RESERVES"] = {"rows": build_rows(fx, "level", scale=0.01, keep=KEEP_MONTHS,
                                                          note_fn=lambda per, v: f"央行 EF07M01：外匯存底 {v:,.2f} 億美元（{per} 月底）"), "release": rel}
            specs["TW_CPI_YOY"] = {"rows": build_rows(cpi, "yoy_rate", keep=KEEP_MONTHS,
                                                      note_fn=lambda per, v: f"央行 EF07M01 轉載主計總處 CPI 年增率 {v:.2f}%（{per}）"), "release": rel}
        except ValueError as exc:
            status["CBC EF07M01"] = f"解析失敗：{exc}"
    p = cbc("CBC EF03M01", "EF03M01")
    if p:
        try:
            fxd = parse_cbc(p, "貨幣機構存款-企業及個人存款-外匯存款", "期底餘額")
            specs["TW_FX_DEPOSIT_BAL"] = {"rows": build_rows(fxd, "level", scale=1e-4, keep=KEEP_MONTHS,
                                                             note_fn=lambda per, v: f"央行 EF03M01：貨幣機構企業及個人外匯存款期底餘額 {v:,.4f} 兆元（{per} 月底，折合新台幣）"),
                                          "release": _release(p)}
        except ValueError as exc:
            status["CBC EF03M01"] = f"解析失敗：{exc}"
    p = cbc("CBC EFA4M01", "EFA4M01")
    if p:
        try:
            li = parse_cbc(p, "貨幣機構放款與投資(性質別)-合計", "年增率")
            specs["TW_BANK_LOAN_INV_YOY"] = {"rows": build_rows(li, "yoy_rate", keep=KEEP_MONTHS,
                                                                note_fn=lambda per, v: f"央行 EFA4M01：全體貨幣機構放款與投資年增率 {v:.2f}%（{per}，以成本衡量）"),
                                             "release": _release(p)}
        except ValueError as exc:
            status["CBC EFA4M01"] = f"解析失敗：{exc}"
    p = cbc("CBC EH45m01", "EH45m01")
    if p:
        try:
            mg = parse_cbc(p, "購屋貸款", "金額")
            specs["TW_FIVE_BANK_MORTGAGE"] = {"rows": build_rows(mg, "level", scale=0.01, keep=KEEP_MONTHS,
                                                                 note_fn=lambda per, v: f"央行 EH45m01：五大銀行新承作購屋貸款金額 {v:,.2f} 億元（{per}）"),
                                              "release": _release(p)}
        except ValueError as exc:
            status["CBC EH45m01"] = f"解析失敗：{exc}"
    p = cbc("CBC BP01D01", "BP01D01")
    if p:
        try:
            ntd = parse_cbc(p, "新台幣NTD/USD")
            specs["TW_USD_TWD"] = {"rows": build_rows(ntd, "level", keep=KEEP_DAYS,
                                                      note_fn=lambda per, v: f"央行 BP01D01：新台幣兌美元 {v:.3f}（{per}，央行公布值，約落後 1~4 週）"), "release": _release(p)}
        except ValueError as exc:
            status["CBC BP01D01"] = f"解析失敗：{exc}"
    try:
        nd = parse_ndc_zip(fb(URL_NDC))
        status["NDC 景氣指標及燈號"] = "OK" if nd["score"] else "解析不到資料"
        if nd["score"]:
            color = {per: c for per, _v, c in nd["score"]}
            specs["TW_NDC_SCORE"] = {"rows": build_rows([(p_, v) for p_, v, _c in nd["score"]], "score", keep=KEEP_MONTHS,
                                                        note_fn=lambda per, v: f"國發會景氣對策信號：{v:g} 分，{color.get(per, '')}燈（{per}）"), "release": None}
        if nd["five_rate"]:
            specs["TW_FIVE_BANK_NEW_RATE"] = {"rows": build_rows(nd["five_rate"], "yoy_rate", keep=KEEP_MONTHS,
                                                                 note_fn=lambda per, v: f"國發會景氣指標資料集：五大銀行新承做放款平均利率 {v:.3f}%（{per}）"), "release": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("總體資料 NDC 取得失敗：%s: %s", type(exc).__name__, exc)
        status["NDC 景氣指標及燈號"] = f"失敗：{type(exc).__name__}"
    try:
        mof = parse_mof_trade(fb(URL_MOF).decode("utf-8-sig"))
        status["MOF 進出口"] = "OK" if mof else "解析不到資料"
        if mof:
            specs["TW_CUSTOMS_EXPORTS"] = {"rows": build_rows(mof, "level", scale=0.01, keep=KEEP_MONTHS,
                                                              note_fn=lambda per, v: f"財政部進出口統計：海關出口 {v:,.1f} 億美元（{per}）"), "release": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("總體資料 MOF 取得失敗：%s: %s", type(exc).__name__, exc)
        status["MOF 進出口"] = f"失敗：{type(exc).__name__}"

    try:
        orders = parse_moea_orders(fb(URL_MOEA_ORDERS).decode("utf-8-sig"))
        status["MOEA 外銷訂單"] = "OK" if orders else "解析不到資料"
        if orders:
            specs["TW_EXPORT_ORDERS"] = {"rows": build_rows(orders, "level", scale=0.01, keep=KEEP_MONTHS,
                                                            note_fn=lambda per, v: f"經濟部統計處：外銷訂單 {v:,.1f} 億美元（{per}）"), "release": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("總體資料 MOEA 外銷訂單取得失敗：%s: %s", type(exc).__name__, exc)
        status["MOEA 外銷訂單"] = f"失敗：{type(exc).__name__}"

    if fred_key:
        start = (date.today() - timedelta(days=400)).isoformat()
        for code, sid, label in (("US_10Y_YIELD", "DGS10", "美國 10 年期公債殖利率"), ("US_FED_RATE_UPPER", "DFEDTARU", "聯邦資金利率目標上限"),
                                 ("INTL_VIX", "VIXCLS", "VIX 恐慌指數"), ("INTL_USD_BROAD", "DTWEXBGS", "聯準會廣義美元指數")):
            try:
                pts = parse_fred(fj(URL_FRED.format(sid=sid, key=fred_key, start=start)))
                status[f"FRED {sid}"] = "OK" if pts else "解析不到資料"
                if pts:
                    specs[code] = {"rows": build_rows(pts, "score", keep=KEEP_DAYS,
                                                      note_fn=lambda per, v, label=label, sid=sid: f"FRED {sid}：{label} {v:g}（{per}）"), "release": None}
            except Exception as exc:  # noqa: BLE001 — 金鑰錯誤的訊息可能含金鑰，只記錄型別
                logger.warning("總體資料 FRED %s 取得失敗：%s", sid, type(exc).__name__)
                status[f"FRED {sid}"] = f"失敗：{type(exc).__name__}"
    else:
        status["FRED"] = "略過：未設定 FRED_API_KEY"
    return specs, status


def apply_live_macro(conn=None, today=None, fetchers=None):
    """抓取官方總體資料並寫入 macro_observations；官方期間內的手寫列被取代。回傳 {metrics: [...], status: {...}}。"""
    from db import get_connection

    own = conn is None
    conn = conn or get_connection()
    try:
        fred_key = os.environ.get("FRED_API_KEY", "").strip()
        specs, status = gather(fred_key or None, **(fetchers or {}))
        cur = conn.cursor()
        # 全體上市櫃月營收合計：由已累積的 MOPS 資料加總 (本機計算，不需網路)
        mt = month_total_points(conn)
        if mt:
            note = (f"MOPS 月營收加總：{mt['companies']:,} 家公司 {mt['period']} 合計 {mt['value']:.2f} 兆元")
            mom = round((mt["value"] / mt["prev"] - 1) * 100, 2) if mt["prev"] else None
            yoy = round((mt["value"] / mt["ly"] - 1) * 100, 2) if mt["ly"] else None
            specs["TW_MOPS_TOTAL_REV"] = {"rows": [{"period": mt["period"], "raw": round(mt["value"], 4),
                                                    "prev": None if not mt["prev"] else round(mt["prev"], 4), "mom": mom, "yoy": yoy, "note": note}],
                                          "release": None}
            status["MOPS 月營收加總"] = "OK"
        ts = now_iso()
        today_iso = (today or date.today()).isoformat()
        for code, spec in NEW_DICTIONARY.items():
            if code in specs:
                cur.execute("INSERT OR IGNORE INTO data_dictionary (metric_code, metric_name, module_id, source_id, observation_type, unit, currency, "
                            "seasonal_adjustment, statistical_scope, calculation_method, missing_value_policy) VALUES (?,?,?,?,?,?,?,?,?,?,?)", spec)
        applied = []
        for code, spec in specs.items():
            rows = spec["rows"]
            if not rows:
                continue
            exists = cur.execute("SELECT 1 FROM data_dictionary WHERE metric_code = ?", (code,)).fetchone()
            if not exists:
                continue
            latest = rows[-1]["period"]
            # 官方資料涵蓋的期間內，手寫列不再保留 (官方還沒公布的更新期間才留下)
            cur.execute("DELETE FROM macro_observations WHERE metric_code = ? AND revision_version != ? AND period_covered <= ?", (code, REVISION, latest))
            for r in rows:
                cur.execute("""INSERT OR REPLACE INTO macro_observations
                    (metric_code, period_covered, release_date, fetched_at, raw_value, cleaned_value, prev_value, mom_pct, yoy_pct,
                     quality_grade, observation_type, revision_version, notes)
                    VALUES (?,?,?,?,?,?,?,?,?, 'A', (SELECT observation_type FROM data_dictionary WHERE metric_code = ?), ?, ?)""",
                            (code, r["period"], spec.get("release") or today_iso, ts, r["raw"], r["raw"], r["prev"], r["mom"], r["yoy"], code, REVISION, r["note"]))
            applied.append(code)
        conn.commit()
        return {"applied": applied, "status": status}
    finally:
        if own:
            conn.close()
