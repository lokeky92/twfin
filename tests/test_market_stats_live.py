"""融資餘額與外資期貨未平倉：解析、單位換算、只寫同一天的官方逐日列、回補與失敗不寫 0 (離線)"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import market_stats_live as ms  # noqa: E402


def margin_payload(date="20261127", thousand="430,171,978", stat="OK"):
    return {"stat": stat, "date": date, "tables": [{"title": "信用交易統計", "fields": ["項目", "買進", "賣出", "現金(券)償還", "前日餘額", "今日餘額"],
                                                    "data": [["融資(交易單位)", "1", "2", "3", "8,826,426", "8,724,920"],
                                                             ["融券(交易單位)", "1", "2", "3", "173,621", "184,790"],
                                                             ["融資金額(仟元)", "13,435,997", "17,184,983", "563,512", "434,484,476", thousand]]}]}


def taifex_rows(date="20261127", net="-107503"):
    return [{"Date": date, "ContractCode": "臺股期貨", "Item": "自營商", "OpenInterest(Net)": "-3566"},
            {"Date": date, "ContractCode": "臺股期貨", "Item": "外資及陸資", "OpenInterest(Net)": net},
            {"Date": date, "ContractCode": "小型臺指期貨", "Item": "外資及陸資", "OpenInterest(Net)": "999"}]


class TestParse(unittest.TestCase):
    def test_margin_converts_thousand_ntd_to_100_million(self):
        self.assertEqual(ms.parse_margin(margin_payload()), ("2026-11-27", 4301.7))      # 430,171,978 仟元 = 4,301.7 億
        self.assertIsNone(ms.parse_margin(margin_payload(stat="很抱歉，沒有符合條件的資料!")))
        self.assertIsNone(ms.parse_margin(margin_payload(thousand="-")))
        self.assertIsNone(ms.parse_margin(margin_payload(thousand="0")))                  # 0 不當作有資料
        self.assertIsNone(ms.parse_margin(None))
        self.assertIsNone(ms.parse_margin({"stat": "OK", "date": "20261127", "tables": []}))

    def test_foreign_oi_uses_big_txf_and_foreign_only(self):
        self.assertEqual(ms.parse_foreign_oi(taifex_rows()), ("2026-11-27", -107503))
        self.assertIsNone(ms.parse_foreign_oi(taifex_rows(net="-")))
        self.assertIsNone(ms.parse_foreign_oi([{"Date": "20261127", "ContractCode": "小型臺指期貨", "Item": "外資及陸資", "OpenInterest(Net)": "5"}]))
        self.assertIsNone(ms.parse_foreign_oi({"error": "x"}))


class TestTaifexBody(unittest.TestCase):
    def test_json_and_csv_bodies_give_the_same_rows(self):
        import json
        as_json = json.dumps(taifex_rows(), ensure_ascii=False).encode("utf-8")
        head = "日期,商品名稱,身份別,多方交易口數,多空未平倉口數淨額"
        as_csv = ("\ufeff" + head + "\n20261127,臺股期貨,自營商,1,-3566\n20261127,臺股期貨,外資及陸資,2,-107503\n20261127,小型臺指期貨,外資及陸資,3,999\n").encode("utf-8")
        self.assertEqual(ms.parse_foreign_oi(ms.parse_taifex_body(as_json)), ("2026-11-27", -107503))
        self.assertEqual(ms.parse_foreign_oi(ms.parse_taifex_body(as_csv)), ("2026-11-27", -107503))     # CI 實際收到 CSV

    def test_unrecognised_body_raises_with_preview(self):
        with self.assertRaises(ValueError) as cm:
            ms.parse_taifex_body("<html> Access Denied </html>".encode("utf-8"))
        self.assertIn("Access Denied", str(cm.exception))


class TestDescribeError(unittest.TestCase):
    def test_http_and_non_json_errors_are_described(self):
        import json
        import urllib.error
        from common import describe_error
        self.assertEqual(describe_error(urllib.error.HTTPError("u", 403, "Forbidden", {}, None)), "HTTP 403")
        try:
            json.loads("<html>  Access   Denied </html>")
        except json.JSONDecodeError as exc:
            self.assertEqual(describe_error(exc), "回應不是 JSON：<html> Access Denied </html>")
        self.assertEqual(describe_error(ConnectionError("x")), "ConnectionError")


class TestDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="twfin_ms_")
        import db
        cls.db = db
        cls.orig = db.DB_PATH
        db.DB_PATH = os.path.join(cls.tmp, "t.db")
        db.init_database()
        from seed_and_engine import seed_and_compute_all
        seed_and_compute_all()

    @classmethod
    def tearDownClass(cls):
        cls.db.DB_PATH = cls.orig
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def conn(self):
        c = self.db.get_connection()
        self.addCleanup(c.close)
        return c

    def add(self, conn, d, official=True):
        label = f"{d} (TWSE BFI82U 官方API直連)" if official else f"{d} 手寫種子"
        conn.execute("""INSERT OR REPLACE INTO institutional_flows (period_type, period_label, release_date, market_scope, foreign_net_billion,
                        itc_net_billion, dealer_prop_billion, dealer_hedge_billion, total_3insti_billion, top_buy_industries, top_sell_industries,
                        source_id, notes) VALUES ('DAILY', ?, ?, 'TWSE', 1, 1, 1, 1, 4, 'x', 'y', 'SRC_TWSE', 'n')""", (label, d))

    def vals(self, conn, d):
        r = conn.execute("SELECT margin_balance_billion m, foreign_futures_oi_contracts f FROM institutional_flows WHERE release_date = ? "
                         "AND period_label LIKE '%官方API%'", (d,)).fetchone()
        return (r["m"], r["f"])

    def fetcher(self, by_date, taifex, calls):
        def fj(url):
            calls.append(url)
            if "taifex" in url:
                if isinstance(taifex, Exception):
                    raise taifex
                return taifex
            d = url.split("date=")[1][:8]
            if isinstance(by_date.get(d), Exception):
                raise by_date[d]
            return by_date.get(d, {"stat": "很抱歉，沒有符合條件的資料!"})
        return {"json": fj, "taifex": fj}

    def test_writes_same_day_official_rows_and_backfills_missing_days(self):
        conn = self.conn()
        conn.execute("DELETE FROM institutional_flows")
        for d in ("2026-11-25", "2026-11-26", "2026-11-27"):
            self.add(conn, d)
        self.add(conn, "2026-11-20", official=False)                   # 手寫列不可被動到
        conn.commit()
        calls = []
        res = ms.apply_market_stats(conn, fetchers=self.fetcher({"20261125": margin_payload("20261125", "420,000,000"),
                                                                 "20261126": margin_payload("20261126", "425,000,000"),
                                                                 "20261127": margin_payload("20261127")}, taifex_rows(), calls))
        self.assertEqual(self.vals(conn, "2026-11-27"), (4301.7, -107503))
        self.assertEqual(self.vals(conn, "2026-11-26"), (4250.0, None))   # 期貨只有最新一天，不回補也不用別天頂替
        self.assertEqual(self.vals(conn, "2026-11-25"), (4200.0, None))
        seed = conn.execute("SELECT margin_balance_billion FROM institutional_flows WHERE release_date = '2026-11-20'").fetchone()[0]
        self.assertIsNone(seed)
        self.assertEqual(res["status"]["TAIFEX 外資期貨未平倉"], "OK")

    def test_failures_keep_existing_values_and_never_write_zero(self):
        conn = self.conn()
        conn.execute("DELETE FROM institutional_flows")
        self.add(conn, "2026-11-27")
        conn.execute("UPDATE institutional_flows SET margin_balance_billion = 4000.0, foreign_futures_oi_contracts = -5 WHERE release_date = '2026-11-27'")
        conn.commit()
        res = ms.apply_market_stats(conn, fetchers=self.fetcher({}, ConnectionError("down"), []))
        self.assertEqual(self.vals(conn, "2026-11-27"), (4000.0, -5))
        self.assertIn("失敗", res["status"]["TAIFEX 外資期貨未平倉"])

    def test_mismatched_date_and_missing_row_are_not_written(self):
        conn = self.conn()
        conn.execute("DELETE FROM institutional_flows")
        self.add(conn, "2026-11-26")
        conn.commit()
        # 要求 11-26 卻回傳 11-27 的資料 → 不寫入；期貨日期對不到任何官方逐日列 → 不寫入
        ms.apply_market_stats(conn, fetchers=self.fetcher({"20261126": margin_payload("20261127")}, taifex_rows(), []))
        self.assertEqual(self.vals(conn, "2026-11-26"), (None, None))

    def test_backfill_is_limited(self):
        conn = self.conn()
        conn.execute("DELETE FROM institutional_flows")
        for i in range(1, 21):
            self.add(conn, f"2026-10-{i:02d}")
        conn.commit()
        calls = []
        ms.apply_market_stats(conn, fetchers=self.fetcher({}, [], calls), max_backfill=4)
        self.assertEqual(len([c for c in calls if "twse" in c]), 1 + 4)  # 最新一次 + 最多回補 4 天


if __name__ == "__main__":
    unittest.main()
