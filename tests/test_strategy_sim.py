"""規則模擬器：引擎數學、時間線 (無未來資料)、規則與基準、資料庫整合 (不連外網)"""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="twfin_ss_test_")
sys.path.insert(0, os.path.join(ROOT, "backend"))

import backtest as bt  # noqa: E402
import strategy_sim as ss  # noqa: E402  (不匯入 db，理由同 test_backtest.py)

db = None
snapshot_industry_scores = None
_ORIG_DB_PATH = None


def setUpModule():
    global db, _ORIG_DB_PATH
    import db as _db
    from seed_and_engine import seed_and_compute_all
    db = _db
    _ORIG_DB_PATH = db.DB_PATH
    db.DB_PATH = os.path.join(_TMP, "ss.db")
    seed_and_compute_all()


def tearDownModule():
    if db is not None:
        db.DB_PATH = _ORIG_DB_PATH
    shutil.rmtree(_TMP, ignore_errors=True)


def tdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


D = tdays(date(2026, 11, 2), 60)
FLAT = {d: 100.0 for d in D}


def growth(rate):
    return {d: 100.0 * (1 + rate) ** i for i, d in enumerate(D)}


class TestEngineMath(unittest.TestCase):
    def test_entry_cost_and_growth(self):
        sim = ss.simulate([(D[2], {"X": 1.0})], {"X": growth(0.01)}, D)
        self.assertAlmostEqual(sim["curve"][0][1], 1 - ss.COST_ONE_WAY, places=9)        # 建倉：買進 100% 扣一次單邊成本
        n = len(sim["curve"]) - 1
        self.assertAlmostEqual(sim["curve"][-1][1], (1 - ss.COST_ONE_WAY) * 1.01 ** n, places=9)
        self.assertEqual(sim["curve"][0][0], D[2])                                      # 進場日之前沒有曲線

    def test_cash_has_no_return_and_no_cost(self):
        sim = ss.simulate([(D[2], {})], {"X": growth(0.01)}, D)
        self.assertTrue(all(abs(v - 1.0) < 1e-12 for _, v in sim["curve"]))

    def test_switching_everything_costs_both_legs(self):
        sim = ss.simulate([(D[2], {"X": 1.0}), (D[10], {"Y": 1.0})], {"X": FLAT, "Y": FLAT}, D)
        self.assertAlmostEqual(sim["turnovers"][0], 1.0, places=6)                      # 建倉：買進 100%
        self.assertAlmostEqual(sim["turnovers"][1], 2.0, places=6)                      # 換股：賣出 100% + 買進 100%
        expected = (1 - 0.002) * (1 - 0.002 * 2.0)                                      # 建倉成本 + 換股雙邊成本
        self.assertAlmostEqual(sim["curve"][-1][1], expected, places=9)

    def test_unchanged_holdings_cost_nothing_extra(self):
        sim = ss.simulate([(D[2], {"X": 1.0}), (D[10], {"X": 1.0})], {"X": FLAT}, D)
        self.assertAlmostEqual(sim["turnovers"][1], 0.0, places=9)
        self.assertAlmostEqual(sim["curve"][-1][1], 1 - 0.002, places=9)

    def test_drift_between_rebalances_is_not_rebalanced(self):
        # 兩個資產各 50%，A 漲 B 持平：持有期間權重漂移，下次調整才會把差額成交
        sim = ss.simulate([(D[2], {"A": 0.5, "B": 0.5}), (D[12], {"A": 0.5, "B": 0.5})],
                          {"A": growth(0.02), "B": FLAT}, D)
        self.assertGreater(sim["turnovers"][1], 0.0)

    def test_drawdown(self):
        self.assertEqual(ss.max_drawdown_pct([(D[0], 1.0), (D[1], 1.2), (D[2], 0.9), (D[3], 1.1)]), -25.0)
        self.assertEqual(ss.max_drawdown_pct([(D[0], 1.0), (D[1], 1.1)]), 0.0)


class TestTimeline(unittest.TestCase):
    def test_current_week_is_not_settled(self):
        snaps = [date(2026, 11, 25), date(2026, 11, 27), date(2026, 12, 1), date(2026, 12, 2)]
        self.assertEqual(ss.weekly_decision_dates(snaps), [date(2026, 11, 27)])
        self.assertEqual(ss.weekly_decision_dates([date(2026, 11, 25)]), [])         # 只有一週：尚未結算
        self.assertEqual(ss.weekly_decision_dates([]), [])

    def test_past_decisions_do_not_change_when_later_data_arrives(self):
        a = [date(2026, 11, 23), date(2026, 11, 27), date(2026, 12, 1)]
        b = a + [date(2026, 12, 4), date(2026, 12, 8)]
        self.assertEqual(ss.weekly_decision_dates(a), ss.weekly_decision_dates(b)[:1])
        self.assertEqual(ss.weekly_decision_dates(b), [date(2026, 11, 27), date(2026, 12, 4)])


class TestRules(unittest.TestCase):
    ROWS = [{"industry_id": f"I{i}", "total": 50 + i * 5, "level": ("LEVEL 4" if i >= 8 else "LEVEL 3" if i >= 6 else "LEVEL 2")}
            for i in range(10)]

    def test_top_n_picks_highest_scores_equal_weight(self):
        w = ss.rule_top_n(self.ROWS)
        self.assertEqual(set(w), {"I9", "I8", "I7"})
        self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_ties_are_broken_deterministically(self):
        rows = [{"industry_id": k, "total": 70.0, "level": "LEVEL 2"} for k in ("B", "A", "D", "C")]
        self.assertEqual(set(ss.rule_top_n(rows)), {"A", "B", "C"})

    def test_alert_rule_holds_level_3_and_4_or_cash(self):
        self.assertEqual(set(ss.rule_alert_levels(self.ROWS)), {"I6", "I7", "I8", "I9"})
        self.assertEqual(ss.rule_alert_levels([dict(r, level="LEVEL 2") for r in self.ROWS]), {})   # 沒有符合 -> 現金

    def test_equal_weight_all(self):
        w = ss.rule_equal_weight_all(self.ROWS)
        self.assertEqual(len(w), 10)
        self.assertAlmostEqual(w["I0"], 0.1)


class TestMetrics(unittest.TestCase):
    def test_win_rate_turnover_and_sample_flag(self):
        entries = [D[2], D[7], D[12]]
        prices = {"A": growth(0.01), "B": FLAT}
        strat = ss.simulate([(e, {"A": 1.0}) for e in entries], prices, D)
        bench = ss.simulate([(D[2], {"B": 1.0})], prices, D)
        m = ss.metrics(strat, bench)
        self.assertEqual(m["rebalances"], 3)
        self.assertEqual(m["complete_periods"], 2)
        self.assertEqual(m["win_rate_pct"], 100.0)                  # 每期都贏過持平的基準
        self.assertEqual(m["avg_turnover_pct"], 0.0)                # 持股不變
        self.assertGreater(m["vs_benchmark_pp"], 0)
        self.assertFalse(m["enough"])                               # 2 期 < 26 期


class TestDatabaseIntegration(unittest.TestCase):
    def setUp(self):
        conn = db.get_connection()
        conn.execute("DELETE FROM industry_score_history")
        conn.execute("DELETE FROM live_market_indices")
        conn.commit()
        conn.close()

    def _load_indices(self, days, drift):
        conn = db.get_connection()
        names = list(bt.INDUSTRY_INDEX_MAP.values()) + [bt.BENCHMARK_INDEX]
        for name in names:
            for k, d in enumerate(days):
                roc = f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}"
                conn.execute("INSERT OR REPLACE INTO live_market_indices (index_name, trade_date, close_index, change_dir, "
                             "change_points, change_pct, fetched_at, source_url) VALUES (?,?,?,?,?,?,?,?)",
                             (name, roc, 100.0 * (1 + drift.get(name, 0.0)) ** k, "", 0, 0, "t", "u"))
        conn.commit()
        conn.close()

    def _snapshots(self, snap_days):
        from history import snapshot_industry_scores
        for d in snap_days:
            snapshot_industry_scores(d.isoformat())

    def test_no_snapshots_means_not_started_and_no_numbers(self):
        conn = db.get_connection()
        r = ss.compute_strategy_sim(conn)
        conn.close()
        self.assertTrue(r["available"])
        self.assertEqual(r["strategies"], [])
        self.assertIsNone(r["curve"])
        self.assertEqual(r["params"]["cost_one_way_pct"], 0.2)

    def test_first_week_only_is_still_pending(self):
        self._snapshots([D[2], D[3]])                                  # 同一週：尚未結算
        self._load_indices(D, {})
        conn = db.get_connection()
        r = ss.compute_strategy_sim(conn)
        conn.close()
        self.assertEqual(r["strategies"], [])
        self.assertEqual(r["decision_dates"], [])

    def test_full_run_compares_rules_with_both_baselines(self):
        weeks = [D[i] for i in (2, 3, 7, 8, 12, 13)]                   # 跨三個 ISO 週
        self._snapshots(weeks)
        drift = {bt.BENCHMARK_INDEX: 0.0005}
        drift.update({idx: 0.0008 for idx in bt.INDUSTRY_INDEX_MAP.values()})
        self._load_indices(D, drift)
        conn = db.get_connection()
        r = ss.compute_strategy_sim(conn)
        conn.close()
        keys = [s["key"] for s in r["strategies"]]
        self.assertEqual(keys, ["top_n", "alert", "equal", "bench"])
        self.assertEqual([s["kind"] for s in r["strategies"]], ["rule", "rule", "baseline", "baseline"])
        self.assertEqual(len(r["decision_dates"]), 2)                  # 最新一週不計入
        top = r["strategies"][0]
        self.assertEqual(top["rebalances"], 2)
        self.assertGreater(top["total_return_pct"], r["strategies"][3]["total_return_pct"])   # 類股漲得比大盤快
        self.assertFalse(top["enough"])                                # 期數太少，必須標示樣本不足
        self.assertEqual(set(r["curve"]["series"]), {"top_n", "alert", "equal", "bench"})
        n = len(r["curve"]["dates"])
        self.assertTrue(all(len(v) == n for v in r["curve"]["series"].values()))
        self.assertEqual(r["curve"]["dates"][0], r["first_entry"])
        # 規則 A 持有 3 個產業、等權重
        w = r["holdings_now"]["top_n"]["weights"]
        self.assertEqual(len(w), 3)
        self.assertTrue(all(abs(x - 1 / 3) < 1e-9 for x in w.values()))

    def test_results_do_not_change_when_future_data_is_appended(self):
        base_days = [D[i] for i in (2, 3, 7, 8, 12, 13)]
        self._snapshots(base_days)
        drift = {idx: 0.001 for idx in bt.INDUSTRY_INDEX_MAP.values()}
        drift[bt.BENCHMARK_INDEX] = 0.0
        self._load_indices(D[:30], drift)
        conn = db.get_connection()
        before = ss.compute_strategy_sim(conn)
        conn.close()

        self._snapshots([D[17], D[18]])                                # 之後又累積了新的週與行情
        self._load_indices(D, drift)
        conn = db.get_connection()
        after = ss.compute_strategy_sim(conn)
        conn.close()
        # 先前已結算的決策與曲線前綴不可被追溯改寫
        self.assertEqual(after["decision_dates"][:len(before["decision_dates"])], before["decision_dates"])
        n = len(before["curve"]["dates"])
        for key in before["curve"]["series"]:
            self.assertEqual(after["curve"]["series"][key][:n], before["curve"]["series"][key])


if __name__ == "__main__":
    unittest.main()
