"""ETF 官方規模：基金基本資料解析、規模計算、近 1 月變化與淨申購 (需累積歷史)、失敗不動資料、資料庫整合 (離線)"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import etf_fund_info as efi  # noqa: E402


def row(code, units, idx="臺灣50指數", out="1151127", inc="0920625", lst="0920630"):
    return {"出表日期": out, "基金代號": code, "基金簡稱": code, "標的指數/追蹤指數名稱": idx, "成立日期": inc, "上市日期": lst,
            "發行單位數/轉換數": units}


def days(n, end=date(2026, 11, 27)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


class TestParse(unittest.TestCase):
    def test_roc_compact(self):
        self.assertEqual(efi.roc_compact("1151127"), "2026-11-27")
        self.assertEqual(efi.roc_compact("0920625"), "2003-06-25")
        self.assertEqual(efi.roc_compact("1150330"), "2026-03-30")
        for bad in (None, "", "abc", "1151399", "12"):
            self.assertIsNone(efi.roc_compact(bad))

    def test_parse_funds(self):
        f = efi.parse_funds([row("0050", "26542500000"), row("00400A", "2,597,640,000", idx="不適用", inc="1150330"),
                             row("BAD", "0"), row("", "1"), {"基金代號": "X"}, "junk", row("NODATE", "5", out="")])
        self.assertEqual(set(f), {"0050", "00400A"})
        self.assertEqual(f["0050"]["units"], 26542500000)
        self.assertEqual(f["0050"]["as_of"], "2026-11-27")
        self.assertEqual(f["0050"]["tracking_index"], "臺灣50指數")
        self.assertIsNone(f["00400A"]["tracking_index"])               # 「不適用」不當作指數名稱
        self.assertEqual(f["00400A"]["units"], 2597640000)
        self.assertEqual(f["00400A"]["inception"], "2026-03-30")
        self.assertEqual(efi.parse_funds(None), {})


class TestAum(unittest.TestCase):
    def info(self, units=1_000_000_000, as_of="2026-11-27"):
        return {"units": units, "as_of": as_of, "tracking_index": None, "inception": None, "listed": None}

    def test_aum_is_units_times_close_on_unit_date(self):
        ds = days(60)
        closes = [(d, 100.0) for d in ds[:-1]] + [(ds[-1], 110.0)]
        m = efi.aum_metrics(self.info(as_of=ds[-2]), closes, [])
        self.assertEqual(m["aum_billion"], 1000.0)                      # 單位數日期當天的收盤 100，不是最新的 110
        self.assertEqual(m["aum_as_of"], ds[-2])
        self.assertIsNone(m["aum_change_1m_pct"])                       # 沒有歷史 → 留空，不猜
        self.assertIsNone(m["net_creation_1m_billion"])

    def test_one_month_change_and_net_creation(self):
        ds = days(80)
        closes = [(d, 100.0 if i < 60 else 120.0) for i, d in enumerate(ds)]
        then = (date.fromisoformat(ds[-1]) - timedelta(days=30)).isoformat()
        m = efi.aum_metrics(self.info(units=1_200_000_000, as_of=ds[-1]), closes, [(then, 1_000_000_000)])
        self.assertEqual(m["aum_billion"], 1440.0)
        # 規模：1.2e9×120 對 當時 1e9×(當時收盤)；淨申購 = 2e8 單位 × 現價 120 = 240 億
        self.assertEqual(m["net_creation_1m_billion"], 240.0)
        self.assertIsNotNone(m["aum_change_1m_pct"])

    def test_history_too_recent_or_too_old_is_ignored(self):
        ds = days(120)
        closes = [(d, 100.0) for d in ds]
        for age in (5, 20, 60, 90):                                     # 要落在 28~45 天前
            then = (date.fromisoformat(ds[-1]) - timedelta(days=age)).isoformat()
            m = efi.aum_metrics(self.info(as_of=ds[-1]), closes, [(then, 900_000_000)])
            self.assertIsNone(m["aum_change_1m_pct"], age)
        then = (date.fromisoformat(ds[-1]) - timedelta(days=35)).isoformat()
        self.assertIsNotNone(efi.aum_metrics(self.info(as_of=ds[-1]), closes, [(then, 900_000_000)])["aum_change_1m_pct"])

    def test_baseline_before_continuous_segment_is_ignored(self):
        ds = days(40)                                                   # 連續行情只有 40 個交易日 (之前有分割斷層)
        closes = [(d, 100.0) for d in ds]
        then = (date.fromisoformat(ds[0]) - timedelta(days=10)).isoformat()   # 基準日在連續行情開始之前
        info = self.info(as_of=ds[-1])
        gap = (date.fromisoformat(ds[-1]) - date.fromisoformat(then)).days
        self.assertGreaterEqual(gap, 28)
        m = efi.aum_metrics(info, closes, [(then, 400_000_000)])
        self.assertIsNone(m["aum_change_1m_pct"])
        self.assertIsNone(m["net_creation_1m_billion"])

    def test_missing_inputs(self):
        self.assertIsNone(efi.aum_metrics(None, [("2026-11-27", 1.0)], [])["aum_billion"])
        self.assertIsNone(efi.aum_metrics(self.info(), [], [])["aum_billion"])


class TestDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="twfin_fund_")
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

    def test_refresh_stores_info_and_history_and_failure_keeps_old(self):
        conn = self.conn()
        conn.execute("DELETE FROM etf_fund_info")
        conn.execute("DELETE FROM etf_units_history")
        orig = efi.fetch_json
        efi.fetch_json = lambda url, **k: [row("0050", "26542500000"), row("9999", "5")]
        try:
            res = efi.refresh(conn, ["0050", "0056"])
        finally:
            efi.fetch_json = orig
        self.assertEqual(res, {"rows": 1})                              # 只存追蹤中的；0056 不在表內則略過
        info, hist = efi.load(conn)
        self.assertEqual(set(info), {"0050"})
        self.assertEqual(hist["0050"], [("2026-11-27", 26542500000)])

        def boom(url, **k):
            raise ConnectionError("down")
        efi.fetch_json = boom
        try:
            res = efi.refresh(conn, ["0050"])
        finally:
            efi.fetch_json = orig
        self.assertIn("error", res)
        self.assertEqual(efi.load(conn)[0]["0050"]["units"], 26542500000)   # 失敗時保留舊資料

    def test_apply_live_etf_uses_official_aum_and_leaves_unsupported_manual(self):
        import etf_live as el
        conn = self.conn()
        for t in ("etf_price_history", "index_price_history", "etf_live_metrics", "etf_fund_info", "etf_units_history"):
            conn.execute(f"DELETE FROM {t}")
        ds = days(300)
        for code, mkt in (("0050", "TWSE"), ("00937B", "TPEx")):
            for d in ds:
                conn.execute("INSERT INTO etf_price_history VALUES (?, ?, 100.0, 1e6, 2e9, ?)", (code, d, mkt))
        for d in ds:
            conn.execute("INSERT INTO index_price_history VALUES ('發行量加權股價指數', ?, 30000)", (d,))
        then = (date.fromisoformat(ds[-1]) - timedelta(days=31)).isoformat()
        conn.execute("INSERT INTO etf_fund_info VALUES ('0050', '臺灣50指數(官方)', '2003-06-25', '2003-06-30', 2000000000, ?, 't')", (ds[-1],))
        conn.execute("INSERT INTO etf_units_history VALUES ('0050', ?, 1800000000, 't')", (then,))
        conn.execute("INSERT INTO etf_units_history VALUES ('0050', ?, 2000000000, 't')", (ds[-1],))
        conn.commit()
        res = el.apply_live_etf(conn, backfill_requests=0)
        self.assertTrue(res["applied"])
        m = conn.execute("SELECT aum_value, aum_unit, aum_change_1m_pct, tracking_index, inception_date FROM etf_master WHERE etf_code = '0050'").fetchone()
        self.assertEqual(m["aum_value"], 2000.0)                        # 20 億單位 × 100 元 = 2,000 億
        self.assertEqual(m["aum_unit"], "億元(TWD)")
        self.assertEqual(m["aum_change_1m_pct"], 11.1)                  # 1.8e9→2.0e9 單位，價格不變
        self.assertEqual(m["tracking_index"], "臺灣50指數(官方)")
        self.assertEqual(m["inception_date"], "2003-06-25")
        d = conn.execute("SELECT primary_net_flow_value FROM etf_daily_metrics WHERE etf_code = '0050'").fetchone()
        self.assertEqual(d["primary_net_flow_value"], 200.0)            # 2e8 單位 × 100 = 200 億
        live = json.loads(conn.execute("SELECT metrics_json FROM etf_live_metrics WHERE etf_code = '0050'").fetchone()[0])
        self.assertEqual(live["aum_source"], "official")
        self.assertEqual(live["aum_as_of"], ds[-1])
        # 沒有官方資料的 (上櫃) 維持人工維護值並標示，淨申購留空
        live2 = json.loads(conn.execute("SELECT metrics_json FROM etf_live_metrics WHERE etf_code = '00937B'").fetchone()[0])
        self.assertEqual(live2["aum_source"], "manual")
        m2 = conn.execute("SELECT aum_value FROM etf_master WHERE etf_code = '00937B'").fetchone()
        self.assertGreater(m2["aum_value"], 0)
        d2 = conn.execute("SELECT primary_net_flow_value FROM etf_daily_metrics WHERE etf_code = '00937B'").fetchone()
        self.assertIsNone(d2["primary_net_flow_value"])

    def test_first_run_without_history_blanks_change_instead_of_keeping_handwritten(self):
        import etf_live as el
        conn = self.conn()
        conn.execute("DELETE FROM etf_units_history")
        conn.execute("DELETE FROM etf_fund_info")
        conn.execute("UPDATE etf_master SET tracking_index = 'MANUAL-INDEX', aum_change_1m_pct = 38.5 WHERE etf_code = '0050'")
        ds = days(300)
        conn.execute("INSERT INTO etf_fund_info VALUES ('0050', NULL, NULL, NULL, 2000000000, ?, 't')", (ds[-1],))
        conn.execute("INSERT INTO etf_units_history VALUES ('0050', ?, 2000000000, 't')", (ds[-1],))
        conn.commit()
        el.apply_live_etf(conn, backfill_requests=0)
        m = conn.execute("SELECT aum_change_1m_pct, tracking_index FROM etf_master WHERE etf_code = '0050'").fetchone()
        self.assertIsNone(m["aum_change_1m_pct"])
        self.assertEqual(m["tracking_index"], "MANUAL-INDEX")          # 官方沒給指數名稱時保留原值


if __name__ == "__main__":
    unittest.main()
