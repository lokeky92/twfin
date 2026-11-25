"""前瞻追蹤回測：純函式與資料庫整合測試 (不連外網)"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="twfin_bt_test_")
sys.path.insert(0, os.path.join(ROOT, "backend"))

import backtest as bt  # noqa: E402  (只依賴 scoring / data_health，不會匯入 db)

# 注意：不能在模組載入時匯入 db / history / seed_and_engine。
# unittest 會先匯入所有測試模組才開始執行，其他測試 (test_live_parsers、test_server) 依賴「由它們先匯入 db 並以環境變數
# 指定暫存資料庫」；若這裡先匯入，db 會落在預設的本機真實資料庫。所以延後到 setUpModule，並且只在本模組執行期間
# 把資料庫路徑換成暫存檔，結束後還原。
db = None
snapshot_industry_scores = None
_ORIG_DB_PATH = None


def setUpModule():
    global db, snapshot_industry_scores, _ORIG_DB_PATH
    import db as _db
    from history import snapshot_industry_scores as _snap
    from seed_and_engine import seed_and_compute_all
    db, snapshot_industry_scores = _db, _snap
    _ORIG_DB_PATH = db.DB_PATH
    db.DB_PATH = os.path.join(_TMP, "bt.db")
    seed_and_compute_all()                 # 建立資料表與啟用中的模型


def tearDownModule():
    if db is not None:
        db.DB_PATH = _ORIG_DB_PATH
    shutil.rmtree(_TMP, ignore_errors=True)


def trading_days(start, n):
    """從 start 起 n 個週一～週五。"""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = trading_days(date(2026, 11, 2), 40)
FLAT = {d: 100.0 for d in DAYS}


def growing(rate):
    """每個交易日以固定比率成長的指數。"""
    return {d: 100.0 * (1 + rate) ** i for i, d in enumerate(DAYS)}


class TestForwardReturn(unittest.TestCase):
    def test_entry_is_first_day_after_signal_and_exit_is_h_days_later(self):
        sig = DAYS[3]
        series = growing(0.01)
        rel, entry, exit_ = bt.forward_relative_return(series, FLAT, sig, 5)
        self.assertEqual(entry, DAYS[4])
        self.assertEqual(exit_, DAYS[9])
        self.assertAlmostEqual(rel, ((1.01 ** 5) - 1) * 100, places=3)

    def test_signal_day_close_is_never_used(self):
        # 快照在收盤後產生：訊號日當天的收盤價 (即使被竄改) 不可影響結果
        sig = DAYS[3]
        a = growing(0.01)
        b = dict(a)
        b[sig] = 9999.0
        self.assertEqual(bt.forward_relative_return(a, FLAT, sig, 5), bt.forward_relative_return(b, FLAT, sig, 5))

    def test_signal_on_a_weekend_enters_next_trading_day(self):
        saturday = date(2026, 11, 7)
        self.assertEqual(saturday.weekday(), 5)
        rel, entry, _ = bt.forward_relative_return(growing(0.01), FLAT, saturday, 5)
        self.assertEqual(entry, date(2026, 11, 9))

    def test_immature_signal_returns_none(self):
        self.assertIsNone(bt.forward_relative_return(growing(0.01), FLAT, DAYS[-3], 5))
        self.assertIsNone(bt.forward_relative_return(growing(0.01), FLAT, DAYS[-1], 5))
        # 剛好差一天：進場日 + 5 個交易日 = 最後一天才算成熟
        self.assertIsNotNone(bt.forward_relative_return(growing(0.01), FLAT, DAYS[-7], 5))
        self.assertIsNone(bt.forward_relative_return(growing(0.01), FLAT, DAYS[-6], 5))

    def test_uses_only_dates_present_in_both_series(self):
        series = growing(0.01)
        gappy = {d: v for d, v in FLAT.items() if d != DAYS[6]}      # 基準少一天
        rel, entry, exit_ = bt.forward_relative_return(series, gappy, DAYS[3], 5)
        self.assertEqual(entry, DAYS[4])
        self.assertEqual(exit_, DAYS[10])                           # 跳過缺的那天，仍是第 5 個「共同」交易日

    def test_relative_to_benchmark(self):
        rel, *_ = bt.forward_relative_return(growing(0.01), growing(0.01), DAYS[3], 5)
        self.assertAlmostEqual(rel, 0.0, places=6)


class TestSpearman(unittest.TestCase):
    def test_perfect_and_inverse(self):
        self.assertAlmostEqual(bt.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(bt.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)

    def test_ties_and_degenerate_inputs(self):
        self.assertIsNone(bt.spearman([1, 1, 1, 1], [1, 2, 3, 4]))       # 完全沒有變化
        self.assertIsNone(bt.spearman([1, 2], [1, 2]))                   # 樣本太少
        v = bt.spearman([1, 2, 2, 3], [1, 2, 3, 4])
        self.assertTrue(0.9 < v < 1.0)


def make_world(n_dates=3, n_ind=10, signal_gap=1):
    """n_ind 個產業：產業 i 的指數每天成長 i*0.1%，分數也隨 i 遞增 -> 分數與其後報酬完全正相關。"""
    ids = [f"IND_{i:02d}" for i in range(n_ind)]
    series = {iid: {d: 100.0 * (1 + 0.001 * i) ** k for k, d in enumerate(DAYS)} for i, iid in enumerate(ids)}
    snaps = []
    for s in range(n_dates):
        for i, iid in enumerate(ids):
            total = 50 + i * 5
            level = "LEVEL 4" if i >= 8 else ("LEVEL 3" if i >= 6 else ("LEVEL R" if i == 0 else "LEVEL 2"))
            snaps.append({"snapshot_date": DAYS[2 + s * signal_gap], "industry_id": iid, "industry_name": iid,
                          "total": total, "level": level})
    return ids, series, snaps


class TestEvaluateAndSummarize(unittest.TestCase):
    def test_matured_counts_and_pending(self):
        ids, series, snaps = make_world(n_dates=3)
        recs = bt.evaluate(snaps, series, FLAT)
        total = len(snaps)
        for h in (5, 10, 20):
            s = bt.summarize_horizon(recs, total, h)
            self.assertEqual(s["matured_signals"] + s["pending_signals"], total)
        late = bt.evaluate([dict(snaps[0], snapshot_date=DAYS[-2])], series, FLAT)
        self.assertEqual(late, [])                                       # 太晚的訊號沒有任何成熟結果

    def test_ic_and_spread_detect_a_predictive_ranking(self):
        ids, series, snaps = make_world()
        s = bt.summarize_horizon(bt.evaluate(snaps, series, FLAT), len(snaps), 5)
        self.assertAlmostEqual(s["ic"]["mean"], 1.0, places=3)
        self.assertEqual(s["ic"]["positive_pct"], 100.0)
        self.assertGreater(s["top_bottom_spread_pct"], 0)
        self.assertFalse(s["enough_for_ic"])                            # 只有 3 個快照日：必須標示樣本不足
        self.assertFalse(s["enough_for_rates"])                         # 命中率筆數 < 30

    def test_hit_definitions_for_bull_and_risk_levels(self):
        ids, series, snaps = make_world()
        # 產業 0 (LEVEL R) 成長率 0 = 與持平基準相同；改成下跌才算「成功避險」
        series[ids[0]] = {d: 100.0 * (0.999 ** k) for k, d in enumerate(DAYS)}
        recs = bt.evaluate(snaps, series, FLAT)
        lv = {l["level"]: l for l in bt.summarize_horizon(recs, len(snaps), 5)["levels"]}
        self.assertEqual(lv["LEVEL 4"]["hit_rate_pct"], 100.0)           # 看多且上漲
        self.assertEqual(lv["LEVEL R"]["hit_rate_pct"], 100.0)           # 看空且下跌
        self.assertIn("成功避險", lv["LEVEL R"]["hit_definition"])
        self.assertIsNone(lv["LEVEL 2"]["hit_rate_pct"])                 # 中性等級不計命中率
        self.assertGreater(lv["LEVEL 4"]["mean_rel_pct"], 0)

    def test_wrong_direction_signals_are_counted_as_misses(self):
        ids, series, snaps = make_world()
        for iid in ids:                                                   # 全部下跌 -> 看多全部落空
            series[iid] = {d: 100.0 * (0.998 ** k) for k, d in enumerate(DAYS)}
        lv = {l["level"]: l for l in bt.summarize_horizon(bt.evaluate(snaps, series, FLAT), len(snaps), 5)["levels"]}
        self.assertEqual(lv["LEVEL 4"]["hit_rate_pct"], 0.0)
        self.assertEqual(lv["LEVEL R"]["hit_rate_pct"], 100.0)

    def test_industries_without_a_price_series_are_skipped_not_invented(self):
        ids, series, snaps = make_world()
        series[ids[5]] = {}
        recs = bt.evaluate(snaps, series, FLAT)
        self.assertNotIn(ids[5], {r["industry_id"] for r in recs})


class TestDatabaseIntegration(unittest.TestCase):
    def setUp(self):
        conn = db.get_connection()
        conn.execute("DELETE FROM industry_score_history")
        conn.execute("DELETE FROM live_market_indices")
        conn.commit()
        conn.close()

    def _load_indices(self, days, rates):
        """rates: {指數名稱: 每日成長率}；日期以證交所的 7 碼民國格式存入。"""
        conn = db.get_connection()
        for name, r in rates.items():
            for k, d in enumerate(days):
                roc = f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}"
                conn.execute("INSERT OR REPLACE INTO live_market_indices (index_name, trade_date, close_index, change_dir, "
                             "change_points, change_pct, fetched_at, source_url) VALUES (?,?,?,?,?,?,?,?)",
                             (name, roc, 100.0 * (1 + r) ** k, "", 0, 0, "t", "u"))
        conn.commit()
        conn.close()

    def test_empty_history_reports_accumulating_state_without_numbers(self):
        conn = db.get_connection()
        r = bt.compute_live_backtest(conn)
        conn.close()
        self.assertTrue(r["available"])
        self.assertEqual(r["snapshot_days"], 0)
        self.assertFalse(r["any_matured"])
        self.assertEqual([h["matured_signals"] for h in r["horizon_results"]], [0, 0, 0])
        self.assertEqual(len(r["caveats"]), len(bt.CAVEATS))

    def test_snapshot_records_alert_level_and_feeds_the_backtest(self):
        snap_day = DAYS[2]
        self.assertGreater(snapshot_industry_scores(snap_day.isoformat()), 5)
        conn = db.get_connection()
        rated = [r[0] for r in conn.execute("SELECT alert_level FROM industry_score_history WHERE total_weighted_score IS NOT NULL")]
        unrated = [r[0] for r in conn.execute("SELECT alert_level FROM industry_score_history WHERE total_weighted_score IS NULL")]
        self.assertTrue(rated and all(rated))                          # 每筆可評分的快照都帶有預警等級
        self.assertTrue(all(l is None for l in unrated))               # 不可評分的產業沒有等級，不硬編
        conn.close()

        names = list(bt.INDUSTRY_INDEX_MAP.values()) + [bt.BENCHMARK_INDEX]
        self._load_indices(DAYS, {n: 0.001 for n in names})
        conn = db.get_connection()
        r = bt.compute_live_backtest(conn)
        conn.close()
        self.assertEqual(r["snapshot_days"], 1)
        self.assertEqual(r["first_snapshot"], snap_day.isoformat())
        self.assertTrue(r["any_matured"])                               # 快照之後有 37 個交易日的行情
        h5 = r["horizon_results"][0]
        self.assertGreater(h5["matured_signals"], 5)
        self.assertEqual(h5["trading_days_needed"], 0)
        # 所有指數同樣成長 -> 超額報酬 0；用不同名稱的指數與基準互相抵消
        for lv in h5["levels"]:
            self.assertAlmostEqual(lv["mean_rel_pct"], 0.0, places=2)

    def test_progress_when_not_enough_trading_days_yet(self):
        snapshot_industry_scores(DAYS[10].isoformat())
        names = list(bt.INDUSTRY_INDEX_MAP.values()) + [bt.BENCHMARK_INDEX]
        self._load_indices(DAYS[:13], {n: 0.001 for n in names})        # 快照日之後只有 2 個交易日
        conn = db.get_connection()
        r = bt.compute_live_backtest(conn)
        conn.close()
        self.assertFalse(r["any_matured"])
        self.assertEqual(r["index_trading_days_after_first_snapshot"], 2)
        self.assertEqual([h["trading_days_needed"] for h in r["horizon_results"]], [4, 9, 19])

    def test_legacy_rows_without_alert_level_are_classified_on_the_fly(self):
        snapshot_industry_scores(DAYS[2].isoformat())
        conn = db.get_connection()
        conn.execute("UPDATE industry_score_history SET alert_level = NULL")
        conn.commit()
        conn.close()
        self._load_indices(DAYS, {n: 0.001 for n in list(bt.INDUSTRY_INDEX_MAP.values()) + [bt.BENCHMARK_INDEX]})
        conn = db.get_connection()
        r = bt.compute_live_backtest(conn)
        conn.close()
        self.assertTrue(any(h["levels"] for h in r["horizon_results"]))


class TestMigrationAndMapping(unittest.TestCase):
    def test_old_database_gets_alert_level_column_without_losing_rows(self):
        path = os.path.join(_TMP, "old.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE industry_score_history (snapshot_date TEXT NOT NULL, industry_id TEXT NOT NULL, "
                     "model_version TEXT NOT NULL, total_weighted_score REAL, score_capital_flow REAL, score_fundamentals REAL, "
                     "score_future_growth REAL, score_institutional REAL, score_valuation REAL, rotation_state TEXT, "
                     "PRIMARY KEY (snapshot_date, industry_id, model_version))")
        conn.execute("INSERT INTO industry_score_history VALUES ('2026-11-25','IND_X','v1',80,1,2,3,4,5,'A')")
        conn.commit()
        db._migrate(conn)
        db._migrate(conn)                                               # 重複執行不會出錯
        cols = {r[1] for r in conn.execute("PRAGMA table_info(industry_score_history)")}
        rows = conn.execute("SELECT industry_id, alert_level FROM industry_score_history").fetchall()
        conn.close()
        self.assertIn("alert_level", cols)
        self.assertEqual(rows, [("IND_X", None)])

    def test_mapping_covers_every_taxonomy_industry_and_uses_total_return_indices(self):
        conn = db.get_connection()
        ids = {r[0] for r in conn.execute("SELECT industry_id FROM industry_taxonomy")}
        conn.close()
        self.assertTrue(ids)
        self.assertEqual(ids - set(bt.INDUSTRY_INDEX_MAP), set())
        for name in list(bt.INDUSTRY_INDEX_MAP.values()) + [bt.BENCHMARK_INDEX]:
            self.assertTrue(name.endswith("報酬指數"), name)             # 含息指數，避免除息日扭曲


if __name__ == "__main__":
    unittest.main()
