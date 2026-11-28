"""ETF 配息與含息報酬：除權息表解析、配息率、含息報酬、涵蓋判斷、資料庫整合 (離線)"""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import etf_dividends as edv  # noqa: E402

TWSE_FIELDS = ["資料日期", "股票代號", "股票名稱", "除權息前收盤價", "除權息參考價", "權值+息值", "權/息", "漲停價格", "跌停價格", "開盤競價基準", "減除股利參考價", "詳細資料"]
TPEX_FIELDS = ["除權息日期", "代號", "名稱", "除權息前收盤價", "除權息參考價", "權值", "息值", "權值+息值", "權/息", "漲停價"]


def trading_days(n, start=date(2025, 1, 6)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


class TestParsers(unittest.TestCase):
    def test_roc_dates(self):
        self.assertEqual(edv.parse_roc_date("114年11月03日"), "2025-11-03")
        self.assertEqual(edv.parse_roc_date("114/11/03"), "2025-11-03")
        self.assertIsNone(edv.parse_roc_date("--"))
        self.assertIsNone(edv.parse_roc_date("114/13/40"))

    def test_twse_keeps_cash_only(self):
        p = {"stat": "OK", "fields": TWSE_FIELDS, "data": [
            ["114年11月03日", "00939", "x", "14.58", "14.50", "0.072000", "息", "1", "1", "1", "1", ""],
            ["114年11月04日", "2330", "y", "1", "1", "5.0", "權", "1", "1", "1", "1", ""],            # 股票股利不計
            ["114年11月05日", "00946", "z", "1", "1", "0", "息", "1", "1", "1", "1", ""],              # 0 不計
        ]}
        self.assertEqual(edv.parse_twse(p), [("00939", "2025-11-03", 0.072)])
        self.assertEqual(edv.parse_twse({"stat": "很抱歉，沒有符合條件的資料!"}), [])

    def test_twse_schema_drift_is_an_error(self):
        with self.assertRaises(ValueError):
            edv.parse_twse({"stat": "OK", "fields": ["a", "b"], "data": []})

    def test_tpex_uses_cash_column(self):
        p = {"stat": "ok", "tables": [{"fields": TPEX_FIELDS, "data": [
            ["114/11/03", "00950B", "n", "14.26", "14.19", "0.000000", "0.066000", "0.066000", "息", "9999.95"],
            ["114/11/04", "6523", "m", "1", "1", "2.0", "0.000000", "2.0", "權", "1"]]}]}
        self.assertEqual(edv.parse_tpex(p), [("00950B", "2025-11-03", 0.066)])
        self.assertEqual(edv.parse_tpex({"stat": "ok", "tables": [{"fields": TPEX_FIELDS, "data": []}]}), [])


class TestCompute(unittest.TestCase):
    def series(self, n, price=lambda i: 100.0):
        return [(d, price(i), 1, 1) for i, d in enumerate(trading_days(n))]

    def test_ttm_window_and_future_excluded(self):
        divs = [("2025-01-01", 9.0), ("2025-06-10", 1.0), ("2026-01-10", 2.0), ("2026-03-01", 5.0)]
        total, n = edv.ttm_dividend(divs, "2026-02-01")
        self.assertEqual((total, n), (3.0, 2))                       # 2025-01-01 太舊、2026-03-01 還沒發生

    def test_total_return_flat_price_equals_dividends(self):
        s = self.series(260)
        d = s[100][0]
        r = edv.total_return_1y(s, [(d, 5.0)])
        self.assertAlmostEqual(r, 5.0, places=1)                      # 價格持平，配 5 元 = +5%

    def test_total_return_reinvests_at_close(self):
        s = self.series(260, price=lambda i: 100.0 if i < 130 else 50.0)   # 中途價格減半 (模擬除息後的價格)
        # 在價格減半的那天配 50 元：(50 + 50) / 100 = 1 → 含息報酬 0
        r = edv.total_return_1y(s, [(s[130][0], 50.0)])
        self.assertAlmostEqual(r, 0.0, places=2)
        self.assertAlmostEqual(edv.total_return_1y(s, []), -50.0, places=2)   # 不含息 = 價格報酬

    def test_total_return_needs_full_year(self):
        self.assertIsNone(edv.total_return_1y(self.series(252), []))
        self.assertIsNotNone(edv.total_return_1y(self.series(253), []))

    def test_dividend_before_window_start_is_ignored(self):
        s = self.series(260)
        self.assertAlmostEqual(edv.total_return_1y(s, [(s[0][0], 9.0)]), 0.0, places=2)

    def test_dividend_on_non_trading_day_moves_to_next(self):
        s = self.series(260)
        sat = date.fromisoformat(s[100][0]) + timedelta(days=1)       # 隔天可能是週末或交易日
        nxt = next(x[0] for x in s if x[0] >= sat.isoformat())
        a = edv.total_return_1y(s, [(sat.isoformat(), 4.0)])
        b = edv.total_return_1y(s, [(nxt, 4.0)])
        self.assertEqual(a, b)

    def test_metrics_blank_when_not_covered_or_new(self):
        s = self.series(260)
        m = edv.dividend_metrics(s, [], 100.0, covered=False)
        self.assertIsNone(m["dividend_yield_pct"])                    # 沒抓到配息表 ≠ 零配息
        self.assertIn("尚未成功取得", m["div_note"])
        m = edv.dividend_metrics(self.series(100), [], 100.0, covered=True)
        self.assertIsNone(m["ret_1y_total"])
        self.assertIn("未滿一年", m["div_note"])

    def test_metrics_values_and_no_dividend_case(self):
        s = self.series(300)
        divs = [(s[150][0], 1.5), (s[250][0], 1.5)]
        m = edv.dividend_metrics(s, divs, 100.0, covered=True)
        self.assertEqual(m["div_count"], 2)
        self.assertEqual(m["div_ttm"], 3.0)
        self.assertEqual(m["dividend_yield_pct"], 3.0)
        self.assertGreater(m["ret_1y_total"], 2.9)
        z = edv.dividend_metrics(s, [], 100.0, covered=True)
        self.assertEqual(z["dividend_yield_pct"], 0.0)
        self.assertIn("沒有配息紀錄", z["div_note"])

    def test_covers(self):
        cov = {"TWSE": ("2025-10-01", "2026-11-27")}
        self.assertTrue(edv.covers(cov, "TWSE", "2026-11-27"))
        self.assertFalse(edv.covers(cov, "TWSE", "2026-12-20"))       # 表已經太舊
        self.assertFalse(edv.covers(cov, "TWSE", "2026-09-01"))       # 起點沒涵蓋視窗
        self.assertFalse(edv.covers(cov, "TPEx", "2026-11-27"))


class TestDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="twfin_div_")
        import db
        cls.db = db
        cls.orig = db.DB_PATH
        db.DB_PATH = os.path.join(cls.tmp, "t.db")
        db.init_database()
        import etf_engine
        etf_engine._fetch_json = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline"))
        from seed_and_engine import seed_and_compute_all
        seed_and_compute_all()
        etf_engine.build_and_compute_etf_center()

    @classmethod
    def tearDownClass(cls):
        cls.db.DB_PATH = cls.orig
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def conn(self):
        c = self.db.get_connection()
        self.addCleanup(c.close)
        return c

    def test_refresh_stores_only_tracked_etfs_and_records_coverage(self):
        conn = self.conn()
        conn.execute("DELETE FROM etf_dividends")
        conn.execute("DELETE FROM etf_dividend_fetch")
        today = date(2026, 11, 27)
        twse = {"stat": "OK", "fields": TWSE_FIELDS, "data": [
            ["115年10月20日", "0050", "n", "1", "1", "1.0", "息", "1", "1", "1", "1", ""],
            ["115年10月21日", "9999", "not tracked", "1", "1", "1.0", "息", "1", "1", "1", "1", ""]]}
        calls = []

        def fake(url, **k):
            calls.append(url)
            if "twse" in url:
                return twse
            raise ConnectionError("tpex down")
        orig = edv.fetch_json
        edv.fetch_json = fake
        try:
            res = edv.refresh(conn, today=today)
        finally:
            edv.fetch_json = orig
        self.assertEqual(res["TWSE"], 1)
        self.assertIn("失敗", res["TPEx"])
        divs, cov = edv.load(conn)
        self.assertEqual(divs, {"0050": [("2026-10-20", 1.0)]})
        self.assertIn("TWSE", cov)
        self.assertNotIn("TPEx", cov)                                 # 失敗的市場不可記為已涵蓋

    def test_apply_live_etf_writes_dividend_fields(self):
        import etf_live as el
        conn = self.conn()
        for t in ("etf_price_history", "index_price_history", "etf_dividends", "etf_dividend_fetch", "etf_live_metrics"):
            conn.execute(f"DELETE FROM {t}")
        ds = trading_days(300, start=date(2025, 6, 2))
        for d in ds:
            conn.execute("INSERT INTO etf_price_history VALUES ('0050', ?, 100.0, 1e6, 2e9, 'TWSE')", (d,))
            conn.execute("INSERT INTO index_price_history VALUES ('發行量加權股價指數', ?, 30000)", (d,))
        conn.execute("INSERT INTO etf_dividends VALUES ('0050', ?, 4.0, 'TWSE', 't')", (ds[200],))
        conn.execute("INSERT INTO etf_dividend_fetch VALUES ('TWSE', ?, ?, 't', 1)", ((date.fromisoformat(ds[-1]) - timedelta(days=380)).isoformat(), ds[-1]))
        conn.commit()
        res = el.apply_live_etf(conn, backfill_requests=0)
        self.assertTrue(res["applied"])
        row = conn.execute("SELECT dividend_yield_pct, return_1y_total_pct, return_price_only_1y_pct FROM etf_daily_metrics WHERE etf_code = '0050'").fetchone()
        self.assertEqual(row["dividend_yield_pct"], 4.0)
        self.assertAlmostEqual(row["return_1y_total_pct"], 4.0, places=1)
        self.assertEqual(row["return_price_only_1y_pct"], 0.0)
        import json
        live = json.loads(conn.execute("SELECT metrics_json FROM etf_live_metrics WHERE etf_code = '0050'").fetchone()[0])
        self.assertEqual(live["div_count"], 1)

    def test_apply_without_dividend_table_leaves_fields_blank(self):
        import etf_live as el
        conn = self.conn()
        conn.execute("DELETE FROM etf_dividend_fetch")
        conn.commit()
        el.apply_live_etf(conn, backfill_requests=0)
        row = conn.execute("SELECT dividend_yield_pct, return_1y_total_pct FROM etf_daily_metrics WHERE etf_code = '0050'").fetchone()
        self.assertIsNone(row["dividend_yield_pct"])
        self.assertIsNone(row["return_1y_total_pct"])


if __name__ == "__main__":
    unittest.main()
