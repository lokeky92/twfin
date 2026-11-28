"""情境條件監控：門檻判定、來源標示、無資料、外資連續賣超、不產生機率 (離線)"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import scenario_monitor as sm  # noqa: E402


def macro(code, value, live=True, period="2026-11-20", yoy=None, unit="%"):
    return {"metric_code": code, "cleaned_value": value, "yoy_pct": yoy, "period_covered": period, "unit": unit,
            "revision_version": "live (官方開放資料)" if live else "v1.0"}


def flow_row(d, frg):
    return {"period_type": "DAILY", "period_label": f"{d} (TWSE BFI82U 官方API直連)", "release_date": d, "market_scope": "TWSE",
            "foreign_net_billion": frg, "itc_net_billion": 0.0, "dealer_prop_billion": 0.0, "dealer_hedge_billion": 0.0, "total_3insti_billion": frg}


def dash(macros, frgs=()):
    return {"macro_latest": macros,
            "institutional_flows": [flow_row(f"2026-11-{20 + i:02d}", v) for i, v in enumerate(frgs)]}


def cond(r, cid):
    return next(c for c in r["conditions"] if c["id"] == cid)


class TestJudge(unittest.TestCase):
    def test_operators(self):
        self.assertTrue(sm._judge("lt", 4.5, 4.4))
        self.assertFalse(sm._judge("lt", 4.5, 4.5))
        self.assertTrue(sm._judge("between", (4.8, 5.1), 5.1))
        self.assertFalse(sm._judge("between", (4.8, 5.1), 5.11))
        self.assertTrue(sm._judge("ge", 38, 38))
        self.assertIsNone(sm._judge("lt", 1, None))


class TestMonitor(unittest.TestCase):
    def test_thresholds_and_sources(self):
        r = sm.compute_scenario_monitor(dash([macro("US_10Y_YIELD", 4.4, live=True), macro("INTL_DXY", 103.5, live=False), macro("TW_NDC_SCORE", 40, live=True)]))
        c = cond(r, "bull_us10y")
        self.assertTrue(c["met"])
        self.assertEqual(c["source"], "live")
        self.assertIs(cond(r, "base_dxy")["met"], True)
        self.assertEqual(cond(r, "base_dxy")["source"], "seed")                # 手寫數值照算但標示
        self.assertIs(cond(r, "bull_dxy")["met"], False)
        self.assertIs(cond(r, "base_ndc")["met"], True)

    def test_missing_data_is_none_not_guessed(self):
        r = sm.compute_scenario_monitor(dash([]))
        for cid in ("bull_sox", "bear_sox", "bull_us10y", "base_taiex"):
            c = cond(r, cid)
            self.assertIsNone(c["met"])
            self.assertIsNone(c["source"])
        self.assertEqual(r["summary"]["BULL"]["no_data"], 5)

    def test_taiex_counts_as_live(self):
        r = sm.compute_scenario_monitor(dash([macro("TW_TAIEX_INDEX", 40000, live=False, unit="點")]))
        self.assertEqual(cond(r, "base_taiex")["source"], "live")
        self.assertIs(cond(r, "base_taiex")["met"], True)
        self.assertIs(cond(r, "base_inv")["met"], False)

    def test_invalidation_hit_is_reported(self):
        r = sm.compute_scenario_monitor(dash([macro("TW_TAIEX_INDEX", 35000, unit="點")]))
        self.assertEqual(r["summary"]["BASE"]["invalidation_hit"], ["base_inv"])

    def test_export_orders_uses_yoy(self):
        r = sm.compute_scenario_monitor(dash([macro("TW_EXPORT_ORDERS", 1238.2, live=False, yoy=78.3)]))
        self.assertIs(cond(r, "bear_inv")["met"], True)
        self.assertEqual(cond(r, "bear_inv")["value"], 78.3)

    def test_foreign_five_day_and_sell_streak(self):
        r = sm.compute_scenario_monitor(dash([], frgs=[-100, -900, -850, 50, 20]))
        self.assertEqual(cond(r, "bull_foreign")["value"], -1780.0)
        self.assertIs(cond(r, "bull_foreign")["met"], False)
        self.assertEqual(cond(r, "bear_sell")["value"], 2.0)                    # 連續 2 天 < -800
        self.assertIs(cond(r, "bear_sell")["met"], True)
        r = sm.compute_scenario_monitor(dash([], frgs=[-900, 10, -900, 10, -900]))
        self.assertIs(cond(r, "bear_sell")["met"], False)                       # 不連續
        r = sm.compute_scenario_monitor(dash([], frgs=[-900]))
        self.assertIsNone(cond(r, "bear_sell")["met"])                          # 資料太少不判定

    def test_summary_separates_live_and_seed_and_has_no_probability(self):
        r = sm.compute_scenario_monitor(dash([macro("US_10Y_YIELD", 4.4, live=True), macro("INTL_DXY", 101, live=False), macro("TW_USD_TWD", 32.0, live=True)]))
        s = r["summary"]["BULL"]
        self.assertEqual((s["live_met"], s["live_known"], s["seed_met"], s["seed_known"]), (2, 2, 1, 1))
        self.assertEqual(s["triggers_total"], 5)
        flat = str(r)
        for banned in ("probability", "機率：", "%)"):
            self.assertNotIn(banned, flat.replace("年增率 ≥", ""))

    def test_every_condition_has_a_source_citation(self):
        for row in sm.SCENARIO_CONDITIONS:
            self.assertTrue(row[7].endswith(("條件 1", "條件 2", "條件 3", "指標", "條件")))


if __name__ == "__main__":
    unittest.main()
