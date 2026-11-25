"""
官方 OpenAPI 解析器與擷取流程測試：全部使用固定範本 (fixture)，不連外網。
官方一旦調整欄位順序或名稱，這裡會先失敗，而不是悄悄算出錯誤的法人買賣超。
"""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="twfin_live_test_")
os.environ["TWFIN_DB_PATH"] = os.path.join(_TMP, "live.db")
sys.path.insert(0, os.path.join(ROOT, "backend"))

import live_api_connector as lac  # noqa: E402
from data_health import (  # noqa: E402
    business_days_between, classify, critical_failures, minguo_ym_to_iso, parse_date,
)
from db import get_connection  # noqa: E402
from seed_and_engine import seed_and_compute_all  # noqa: E402


def t86_row(code, f_net, f_dealer_net, itc, dealer, total):
    row = [""] * 19
    row[0], row[4], row[7], row[10], row[11], row[18] = code, f_net, f_dealer_net, itc, dealer, total
    return row


T86 = {"stat": "OK", "date": "20261124", "data": [
    t86_row("2330", "1,000", "-200", "300", "-50", "1,050"),
    t86_row("2317", "-5,000", "0", "0", "100", "-4,900"),
    ["short", "row"],  # 欄位不足的列要被略過
]}

TPEX_3I = [
    {"Date": "1151124", "SecuritiesCompanyCode": "6223",
     "ForeignInvestorsInclude MainlandAreaInvestors-Difference": "2,000",
     "SecuritiesInvestmentTrustCompanies-Difference": "-100", "Dealers-Difference": "50", "TotalDifference": "1,950"},
]

REV_ROW = {"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業", "資料年月": "11510", "出表日期": "1151110",
           "營業收入-當月營收": "100,000", "營業收入-上月營收": "90,000", "營業收入-去年當月營收": "50,000",
           "營業收入-上月比較增減(%)": "11.1", "營業收入-去年同月增減(%)": "100.0",
           "累計營業收入-當月累計營收": "900,000", "累計營業收入-去年累計營收": "450,000",
           "累計營業收入-前期比較增減(%)": "100.0", "備註": ""}

BFI = {"stat": "OK", "date": "20261124", "title": "115年11月24日 三大法人買賣金額統計表", "data": [
    ["自營商(自行買賣)", "0", "0", "5,000,000,000"],
    ["自營商(避險)", "0", "0", "-2,000,000,000"],
    ["投信", "0", "0", "3,000,000,000"],
    ["外資及陸資(不含外資自營商)", "0", "0", "-10,000,000,000"],
    ["外資自營商", "0", "0", "100,000,000"],
    ["合計", "0", "0", "-3,900,000,000"],
]}


class TestParsers(unittest.TestCase):
    def test_t86_columns_and_date(self):
        m, d = lac.parse_twse_t86(T86)
        self.assertEqual(d, "20261124")
        self.assertEqual(len(m), 2)
        self.assertEqual(m["2330"], {"f": 800, "i": 300, "d": -50, "tot": 1050, "date": "20261124"})
        self.assertEqual(m["2317"]["f"], -5000)

    def test_t86_without_date_is_none_not_fake(self):
        _, d = lac.parse_twse_t86({"data": []})
        self.assertIsNone(d)

    def test_tpex_3insti_uses_own_date(self):
        m, d = lac.parse_tpex_3insti(TPEX_3I, fallback_date="20260101")
        self.assertEqual(d, "20261124")
        self.assertEqual(m["6223"]["f"], 2000)
        self.assertEqual(m["6223"]["tot"], 1950)

    def test_pe_parsers(self):
        twse = lac.parse_twse_pe([{"Code": "2330", "PEratio": "20.5", "PBratio": "5.1", "DividendYield": "1.5"}])
        self.assertEqual(twse["2330"], {"pe": 20.5, "pb": 5.1, "dy": 1.5})
        tpex = lac.parse_tpex_pe([{"SecuritiesCompanyCode": "6223", "PriceEarningRatio": "-", "PriceBookRatio": "3",
                                   "YieldRatio": "0.5"}])
        self.assertIsNone(tpex["6223"]["pe"])

    def test_revenue_row_merges_valuation_and_insti(self):
        pe = {"2330": {"pe": 20.5, "pb": 5.1, "dy": 1.5}}
        insti = {"2330": {"f": 800, "i": 300, "d": -50, "tot": 1050, "date": "20261124"}}
        rows = lac.parse_revenue_rows([REV_ROW], "TWSE", "url", pe, insti, "now")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r[0], "2330")
        self.assertEqual(r[2], "TWSE")
        self.assertEqual(r[4], "IND_SEMI_FOUNDRY")
        self.assertEqual(r[7], 100000.0)
        self.assertEqual(r[15], 20.5)           # pe
        self.assertEqual(r[18:22], (800, 300, -50, 1050))
        self.assertEqual(r[22], "20261124")      # insti_trade_date

    def test_bfi82u_amounts_in_billion(self):
        b = lac.parse_bfi82u(BFI)
        self.assertEqual(b["date"], "2026-11-24")
        self.assertEqual(b["dealer_prop"], 50.0)
        self.assertEqual(b["dealer_hedge"], -20.0)
        self.assertEqual(b["itc"], 30.0)
        self.assertEqual(b["foreign"], -100.0)   # 只計「外資及陸資(不含外資自營商)」
        self.assertEqual(b["total"], -39.0)

    def test_bfi82u_missing_date_rejected(self):
        self.assertIsNone(lac.parse_bfi82u({**BFI, "date": ""}))
        self.assertIsNone(lac.parse_bfi82u({"stat": "很抱歉", "data": []}))


class TestDataHealth(unittest.TestCase):
    def test_parse_date_formats(self):
        self.assertEqual(parse_date("20261124"), date(2026, 11, 24))
        self.assertEqual(parse_date("2026-11-24"), date(2026, 11, 24))
        self.assertEqual(parse_date("1151124"), date(2026, 11, 24))
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("abc"))
        self.assertIsNone(parse_date("20269999"))

    def test_business_days(self):
        self.assertEqual(business_days_between(date(2026, 11, 20), date(2026, 11, 23)), 1)  # 週五 -> 週一
        self.assertEqual(business_days_between(date(2026, 11, 24), date(2026, 11, 24)), 0)

    def test_minguo(self):
        self.assertEqual(minguo_ym_to_iso("11510"), "2026-10")

    def test_classify(self):
        today = date(2026, 11, 25)
        self.assertEqual(classify(False, 0, 100, None, today)[0], "FAILED")
        self.assertEqual(classify(True, 0, 100, "20261124", today)[0], "EMPTY")
        self.assertEqual(classify(True, 40, 100, "20261124", today)[0], "DEGRADED")
        self.assertEqual(classify(True, 100, 100, "20261124", today)[0], "OK")
        self.assertEqual(classify(True, 100, 100, "20261110", today)[0], "STALE")
        # 月營收 (daily=False) 不套用營業日過期判斷
        self.assertEqual(classify(True, 100, 100, "2026-10", today, daily=False)[0], "OK")

    def test_critical_failures(self):
        self.assertEqual(critical_failures({"twse_rev": "OK", "tpex_rev": "OK", "twse_t86": "FAILED"}), [])
        self.assertEqual(critical_failures({"twse_rev": "FAILED", "tpex_rev": "OK"}), ["twse_rev"])
        self.assertEqual(critical_failures({"twse_rev": "OK"}), ["tpex_rev"])  # 缺少 = 視為失敗


class TestIngestionFlow(unittest.TestCase):
    """以假的 fetch 驗證：單一來源失敗不會寫入假日期，也不會用 NULL 蓋掉舊資料。"""

    @classmethod
    def setUpClass(cls):
        seed_and_compute_all()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)

    def _run(self, responses):
        def fake(url, timeout=15):
            for prefix, value in responses.items():
                if url.startswith(prefix):
                    if isinstance(value, Exception):
                        raise value
                    return value
            raise ConnectionError("no fixture for " + url)
        original = lac._fetch_json
        lac._fetch_json = fake
        try:
            return lac.run_live_ingestion()
        finally:
            lac._fetch_json = original

    def _all_ok(self):
        return {
            lac.URL_TWSE_PE: [{"Date": "1151124", "Code": "2330", "PEratio": "20", "PBratio": "5", "DividendYield": "1"}],
            lac.URL_TPEX_PE: [{"Date": "1151124", "SecuritiesCompanyCode": "6223", "PriceEarningRatio": "30",
                               "PriceBookRatio": "4", "YieldRatio": "1"}],
            lac.URL_T86.split("?")[0]: T86,
            lac.URL_TPEX_3I: TPEX_3I,
            lac.URL_TWSE_REV: [REV_ROW],
            lac.URL_TPEX_REV: [{**REV_ROW, "公司代號": "6223", "公司名稱": "旺矽", "產業別": "半導體業"}],
            lac.URL_MI_INDEX: [{"指數": "發行量加權股價指數", "日期": "1151124", "收盤指數": "20000", "漲跌": "+",
                                "漲跌點數": "10", "漲跌百分比": "0.05"}],
            lac.URL_BFI82U.split("?")[0]: BFI,
        }

    def test_failure_keeps_old_institutional_data_and_flags_status(self):
        first = self._run(self._all_ok())
        self.assertEqual(first["critical_failures"], [])
        self.assertEqual(first["health"]["twse_t86"], "OK")

        broken = self._all_ok()
        broken[lac.URL_T86.split("?")[0]] = TimeoutError("boom")
        broken[lac.URL_TPEX_3I] = TimeoutError("boom")
        second = self._run(broken)
        self.assertEqual(second["health"]["twse_t86"], "FAILED")
        self.assertEqual(second["health"]["tpex_3i"], "FAILED")
        self.assertEqual(second["critical_failures"], [])  # 法人資料不是關鍵來源

        conn = get_connection()
        row = conn.execute("SELECT foreign_net_shares, insti_trade_date FROM live_company_fundamentals "
                           "WHERE company_code = '2330'").fetchone()
        status = conn.execute("SELECT status, data_date, record_count FROM data_source_status "
                              "WHERE source_key = 'twse_t86'").fetchone()
        conn.close()
        self.assertEqual(row["foreign_net_shares"], 800)          # 沿用舊值，不是 NULL
        self.assertEqual(row["insti_trade_date"], "20261124")     # 不是寫死的假日期
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["data_date"], "20261124")         # 保留上次成功的資料日期
        self.assertEqual(status["record_count"], 3)   # 原始列數 (含欄位不足、被略過的列)

    def test_revenue_failure_is_critical(self):
        broken = self._all_ok()
        broken[lac.URL_TWSE_REV] = ConnectionError("down")
        res = self._run(broken)
        self.assertIn("twse_rev", res["critical_failures"])

    def test_bfi82u_does_not_fabricate_futures_or_margin(self):
        self._run(self._all_ok())
        conn = get_connection()
        row = conn.execute("SELECT foreign_futures_oi_contracts, margin_balance_billion FROM institutional_flows "
                           "WHERE period_label LIKE '2026-11-24%'").fetchone()
        conn.close()
        self.assertIsNone(row["foreign_futures_oi_contracts"])
        self.assertIsNone(row["margin_balance_billion"])


if __name__ == "__main__":
    unittest.main()
