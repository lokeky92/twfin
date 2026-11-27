"""ETF 前瞻追蹤：還原價格 (分割)、快照建立、成熟度、命中率、與 apply_live_etf 寫入快照的整合 (離線)"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import etf_backtest as eb  # noqa: E402


def days(n, start=date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


class TestAdjusted(unittest.TestCase):
    def test_split_is_not_a_crash(self):
        rows = [("2026-01-05", 100.0), ("2026-01-06", 101.0), ("2026-01-07", 25.25), ("2026-01-08", 25.5)]   # 1 拆 4
        s = eb.adjusted_series(rows)
        vals = [s[d] for d in sorted(s)]
        self.assertAlmostEqual(vals[2], vals[1])                    # 分割日報酬視為 0
        self.assertGreater(vals[3], vals[2])                        # 之後的漲幅照算

    def test_normal_moves_kept(self):
        s = eb.adjusted_series([("2026-01-05", 100.0), ("2026-01-06", 110.0)])
        self.assertAlmostEqual(s[date(2026, 1, 6)] / s[date(2026, 1, 5)], 1.10)

    def test_skips_bad_rows(self):
        s = eb.adjusted_series([("bad", 1.0), ("2026-01-05", None), ("2026-01-06", 10.0)])
        self.assertEqual(list(s), [date(2026, 1, 6)])


class TestSnapshots(unittest.TestCase):
    def row(self, code, a_c, b_c, lev=0, sa=70.0, sb=70.0, d="2026-01-05"):
        return {"etf_code": code, "snapshot_date": d, "score_a": sa, "score_b": sb, "conclusion_a": a_c, "conclusion_b": b_c, "is_leveraged": lev}

    def test_leveraged_and_unmapped_are_excluded(self):
        rows = [self.row("A", "適合進一步研究", "條件相對有利"), self.row("L", "不符合配置角色", "風險偏高", lev=1),
                self.row("N", "資料不足，暫不評分", "資料不足，暫不評分")]
        b = eb.build_snapshots(rows, "B")
        a = eb.build_snapshots(rows, "A")
        self.assertEqual([s["industry_id"] for s in b], ["A"])
        self.assertEqual(b[0]["level"], "LEVEL 4")
        self.assertEqual([s["industry_id"] for s in a], ["A"])

    def test_missing_score_is_skipped(self):
        self.assertEqual(eb.build_snapshots([self.row("A", "x", "條件相對有利", sb=None)], "B"), [])


class TestCompute(unittest.TestCase):
    def make_conn(self, snap_day_idx, n_days=40):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE etf_score_history (etf_code TEXT, snapshot_date TEXT, score_a REAL, score_b REAL, conclusion_a TEXT, conclusion_b TEXT,
                is_leveraged INTEGER, missing_count INTEGER, created_at TEXT, PRIMARY KEY (etf_code, snapshot_date));
            CREATE TABLE etf_price_history (etf_code TEXT, trade_date TEXT, close_price REAL, volume_shares REAL, turnover_twd REAL, market TEXT);
            CREATE TABLE index_price_history (index_name TEXT, trade_date TEXT, close_index REAL);""")
        ds = days(n_days)
        for i, d in enumerate(ds):
            conn.execute("INSERT INTO index_price_history VALUES (?,?,?)", (eb.BENCH_NAME, d.isoformat(), 1000.0))      # 基準持平
            conn.execute("INSERT INTO etf_price_history VALUES ('UP',?,?,1,1,'TWSE')", (d.isoformat(), 100.0 * 1.01 ** i))   # 每日 +1%
            conn.execute("INSERT INTO etf_price_history VALUES ('DN',?,?,1,1,'TWSE')", (d.isoformat(), 100.0 * 0.99 ** i))   # 每日 -1%
        sd = ds[snap_day_idx].isoformat()
        conn.execute("INSERT INTO etf_score_history VALUES ('UP',?,80,80,'適合進一步研究','條件相對有利',0,0,'t')", (sd,))
        conn.execute("INSERT INTO etf_score_history VALUES ('DN',?,30,30,'條件普通','風險偏高',0,0,'t')", (sd,))
        return conn

    def test_no_snapshots_is_unavailable(self):
        conn = self.make_conn(0)
        conn.execute("DELETE FROM etf_score_history")
        self.assertFalse(eb.compute_etf_forward(conn)["available"])

    def test_missing_table_is_unavailable(self):
        self.assertFalse(eb.compute_etf_forward(sqlite3.connect(":memory:"))["available"])

    def test_pending_until_horizon_reached(self):
        conn = self.make_conn(snap_day_idx=38, n_days=40)          # 快照後只剩 1 個交易日
        r = eb.compute_etf_forward(conn)
        self.assertTrue(r["available"])
        self.assertFalse(r["any_matured"])
        h5 = r["models"]["B"]["horizon_results"][0]
        self.assertEqual(h5["matured_signals"], 0)
        self.assertEqual(h5["pending_signals"], 2)
        self.assertGreater(h5["trading_days_needed"], 0)

    def test_hit_rates_when_matured(self):
        conn = self.make_conn(snap_day_idx=5, n_days=40)
        r = eb.compute_etf_forward(conn)
        self.assertTrue(r["any_matured"])
        h5 = r["models"]["B"]["horizon_results"][0]
        by = {l["level"]: l for l in h5["levels"]}
        self.assertEqual(by["LEVEL 4"]["hit_rate_pct"], 100.0)     # 看好的 +1%/日 > 基準 0
        self.assertEqual(by["LEVEL R"]["hit_rate_pct"], 100.0)     # 風險偏高的 -1%/日 < 基準 0 → 成功避險
        self.assertEqual(by["LEVEL 4"]["label"], "條件相對有利")
        self.assertFalse(h5["enough_for_rates"])                   # 樣本遠少於 30 → 標示不足
        self.assertEqual(r["snapshot_days"], 1)

    def test_split_inside_window_does_not_fake_a_crash(self):
        conn = self.make_conn(snap_day_idx=5, n_days=40)
        ds = days(40)
        conn.execute("DELETE FROM etf_price_history WHERE etf_code = 'UP'")
        for i, d in enumerate(ds):
            px = 100.0 * 1.01 ** i
            if i >= 8:
                px /= 4                                            # 第 8 天 1 拆 4
            conn.execute("INSERT INTO etf_price_history VALUES ('UP',?,?,1,1,'TWSE')", (d.isoformat(), px))
        h5 = eb.compute_etf_forward(conn)["models"]["B"]["horizon_results"][0]
        up = [l for l in h5["levels"] if l["level"] == "LEVEL 4"][0]
        self.assertGreater(up["mean_rel_pct"], 0)                  # 沒被分割拖成 -75%


class TestIntegration(unittest.TestCase):
    """apply_live_etf 每次都要寫一列快照；同一資料日重跑只留一列。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="twfin_etfbt_")
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

    def test_snapshot_written_once_per_day(self):
        import etf_live as el
        conn = self.db.get_connection()
        self.addCleanup(conn.close)
        for t in ("etf_price_history", "index_price_history", "etf_score_history"):
            conn.execute(f"DELETE FROM {t}")
        start = date(2025, 6, 2)
        for d in days(300, start=start):
            conn.execute("INSERT INTO etf_price_history VALUES ('0050',?,?,1e6,2e9,'TWSE')", (d.isoformat(), 100 + (d - start).days * 0.05))
            conn.execute("INSERT INTO index_price_history VALUES ('發行量加權股價指數',?,?)", (d.isoformat(), 30000 + (d - start).days))
        conn.commit()
        el.apply_live_etf(conn, backfill_requests=0)
        el.apply_live_etf(conn, backfill_requests=0)                   # 同一資料日重跑
        rows = conn.execute("SELECT * FROM etf_score_history WHERE etf_code = '0050'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["score_a"])
        self.assertIsNotNone(rows[0]["conclusion_b"])


if __name__ == "__main__":
    unittest.main()
