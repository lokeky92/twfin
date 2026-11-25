"""評分與預警分級純函式的單元測試 (python -m unittest discover -s tests)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from scoring import (  # noqa: E402
    DEFAULT_WEIGHTS,
    classify_alert_level,
    compute_weighted_total,
    WEIGHT_KEYS,
    parse_weights,
    effective_thresholds,
    sensitivity_analysis,
    shift_weight,
    threshold_sensitivity,
    validate_thresholds,
)


def _row(cap=80, fun=70, gro=60, ins=50, val=40, state="ACCUMULATING"):
    return {
        "score_capital_flow": cap,
        "score_fundamentals": fun,
        "score_future_growth": gro,
        "score_institutional": ins,
        "score_valuation": val,
        "rotation_state": state,
    }


class TestWeightedTotal(unittest.TestCase):
    def test_default_weights(self):
        # 80*.25 + 70*.25 + 60*.2 + 50*.15 + 40*.15 = 20 + 17.5 + 12 + 7.5 + 6
        self.assertEqual(compute_weighted_total(_row(), DEFAULT_WEIGHTS), 63.0)

    def test_insufficient_data_state_returns_none(self):
        self.assertIsNone(compute_weighted_total(_row(state="INSUFFICIENT_DATA"), DEFAULT_WEIGHTS))

    def test_any_missing_sub_score_returns_none(self):
        # 舊版只檢查資金分數，其他子分數為 None 時會 TypeError 崩潰
        self.assertIsNone(compute_weighted_total(_row(val=None), DEFAULT_WEIGHTS))
        self.assertIsNone(compute_weighted_total(_row(cap=None), DEFAULT_WEIGHTS))

    def test_all_weight_on_one_factor(self):
        w = {k: 0.0 for k in DEFAULT_WEIGHTS}
        w["fundamentals"] = 1.0
        self.assertEqual(compute_weighted_total(_row(fun=77.7), w), 77.7)


class TestParseWeights(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_weights(dict(DEFAULT_WEIGHTS)), DEFAULT_WEIGHTS)

    def test_defaults_when_missing(self):
        self.assertEqual(parse_weights({}), DEFAULT_WEIGHTS)

    def test_sum_not_one(self):
        with self.assertRaises(ValueError):
            parse_weights({**DEFAULT_WEIGHTS, "valuation": 0.5})

    def test_negative_weight_rejected(self):
        with self.assertRaises(ValueError):
            parse_weights({**DEFAULT_WEIGHTS, "capital_flow": -0.25, "fundamentals": 0.75})

    def test_non_numeric_rejected(self):
        with self.assertRaises(ValueError):
            parse_weights({**DEFAULT_WEIGHTS, "capital_flow": "abc"})


class TestAlertLevel(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(classify_alert_level(85, 80), "LEVEL 4")
        self.assertEqual(classify_alert_level(80, 80), "LEVEL 4")  # 邊界含等號
        self.assertEqual(classify_alert_level(75, 80), "LEVEL 3")
        self.assertEqual(classify_alert_level(65, 80), "LEVEL 2")
        self.assertEqual(classify_alert_level(55, 80), "LEVEL 1")

    def test_capital_flow_retreat_overrides(self):
        # 總分再高，資金分數低於 R 門檻仍判為撤退風險
        self.assertEqual(classify_alert_level(90, 44.9), "LEVEL R")
        self.assertEqual(classify_alert_level(90, 45), "LEVEL 4")

    def test_none_total(self):
        self.assertIsNone(classify_alert_level(None, 80))

    def test_custom_thresholds(self):
        th = {"lvl4_min": 90, "lvl3_min": 80, "lvl2_min": 70, "lvlR_cap_max": 30}
        self.assertEqual(classify_alert_level(85, 50, th), "LEVEL 3")
        self.assertEqual(classify_alert_level(85, 20, th), "LEVEL R")

    def test_threshold_order_validated(self):
        with self.assertRaises(ValueError):
            validate_thresholds({"lvl4_min": 70, "lvl3_min": 72, "lvl2_min": 62, "lvlR_cap_max": 45})
        with self.assertRaises(ValueError):
            validate_thresholds({"lvl4_min": 180, "lvl3_min": 72, "lvl2_min": 62, "lvlR_cap_max": 45})


def _ind(iid, cap, fun, gro, ins, val, state="ACCUMULATING"):
    r = _row(cap, fun, gro, ins, val, state)
    r.update({"industry_id": iid, "industry_name": "產業" + iid})
    return r


class TestShiftWeight(unittest.TestCase):
    def test_sum_stays_one_and_direction(self):
        for key in WEIGHT_KEYS:
            for delta in (-0.05, 0.05):
                w = shift_weight(DEFAULT_WEIGHTS, key, delta)
                self.assertAlmostEqual(sum(w.values()), 1.0, places=9)
                self.assertAlmostEqual(w[key], DEFAULT_WEIGHTS[key] + delta, places=9)
                self.assertTrue(all(v >= 0 for v in w.values()))

    def test_clamped_at_zero(self):
        w = shift_weight({"capital_flow": 0.02, "fundamentals": 0.5, "future_growth": 0.2,
                          "institutional": 0.2, "valuation": 0.08}, "capital_flow", -0.05)
        self.assertEqual(w["capital_flow"], 0.0)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=9)


class TestSensitivityAnalysis(unittest.TestCase):
    def test_clearly_separated_industries_are_stable(self):
        rows = [_ind("A", 90, 90, 90, 90, 90), _ind("B", 70, 70, 70, 70, 70), _ind("C", 50, 50, 50, 50, 50)]
        res = sensitivity_analysis(rows)
        self.assertTrue(res["available"])
        self.assertEqual(res["top1_same_pct"], 100.0)
        self.assertEqual(res["top3_same_pct"], 100.0)
        self.assertEqual(res["unstable_count"], 0)
        self.assertTrue(all(x["min_rank"] == x["max_rank"] == x["base_rank"] for x in res["industries"]))

    def test_near_tie_flips_rank_under_perturbation(self):
        # 預設權重下 E 略勝 D；提高資金流向權重就會翻盤
        rows = [_ind("D", 80, 60, 60, 60, 60), _ind("E", 60, 60, 60, 60, 100), _ind("F", 20, 20, 20, 20, 20)]
        res = sensitivity_analysis(rows)
        d = next(x for x in res["industries"] if x["industry_id"] == "D")
        self.assertEqual(d["base_rank"], 2)
        self.assertEqual(d["min_rank"], 1)
        self.assertLess(res["top1_same_pct"], 100.0)

    def test_deterministic(self):
        rows = [_ind("D", 80, 60, 60, 60, 60), _ind("E", 60, 60, 60, 60, 100), _ind("F", 20, 20, 20, 20, 20)]
        self.assertEqual(sensitivity_analysis(rows), sensitivity_analysis(rows))

    def test_insufficient_data_excluded_and_empty_handled(self):
        rows = [_ind("A", 90, 90, 90, 90, 90), _ind("X", 50, 50, 50, 50, 50, state="INSUFFICIENT_DATA")]
        res = sensitivity_analysis(rows)
        self.assertEqual([x["industry_id"] for x in res["industries"]], ["A"])
        self.assertFalse(sensitivity_analysis([rows[1]])["available"])

    def test_level_change_detected_near_threshold(self):
        # 總分約 72.0 (LEVEL 3 門檻)：權重微調會讓等級在 LEVEL 2 / 3 間變動
        rows = [_ind("G", 75, 75, 75, 60, 70)]
        res = sensitivity_analysis(rows)
        self.assertGreater(res["industries"][0]["level_change_pct"], 0)


class TestEffectiveThresholds(unittest.TestCase):
    def test_seed_description_text_falls_back_to_defaults(self):
        # 種子模型存的是描述文字 (沒有數值)
        seed = {"LEVEL 4": "總分 >= 80 且 ...", "LEVEL R": "資金流向 < 45"}
        self.assertEqual(effective_thresholds(seed), {"lvl4_min": 80.0, "lvl3_min": 72.0, "lvl2_min": 62.0, "lvlR_cap_max": 45.0})

    def test_numeric_block_written_by_governance_update_is_used(self):
        stored = {"LEVEL 4": "文字", "numeric": {"lvl4_min": 85, "lvl3_min": 75, "lvl2_min": 65, "lvlR_cap_max": 40}}
        self.assertEqual(effective_thresholds(stored), {"lvl4_min": 85.0, "lvl3_min": 75.0, "lvl2_min": 65.0, "lvlR_cap_max": 40.0})

    def test_partial_or_garbage_values_fall_back_per_key(self):
        th = effective_thresholds({"numeric": {"lvl4_min": "abc", "lvl3_min": 70}})
        self.assertEqual(th["lvl4_min"], 80.0)
        self.assertEqual(th["lvl3_min"], 70.0)
        self.assertEqual(effective_thresholds(None), effective_thresholds({}))


class TestThresholdSensitivity(unittest.TestCase):
    def test_far_from_every_threshold_is_stable(self):
        rows = [_ind("A", 95, 95, 95, 95, 95), _ind("B", 20, 20, 20, 20, 20)]
        res = threshold_sensitivity(rows)
        a, b = res["industries"]
        self.assertEqual((a["base_level"], a["level_change_pct"], a["stability"]), ("LEVEL 4", 0.0, "穩定"))
        self.assertEqual(a["margin_points"], 15.0)
        self.assertEqual(a["nearest_threshold"], "lvl4_min")
        self.assertEqual(b["base_level"], "LEVEL R")          # 資金分數 20 < 45
        self.assertEqual(res["never_changes_count"], 2)
        self.assertEqual(res["unstable_count"], 0)

    def test_score_exactly_on_threshold_flips_about_half_the_time(self):
        res = threshold_sensitivity([_ind("G", 80, 80, 80, 80, 80)])      # 總分 80.0 = LEVEL 4 門檻
        g = res["industries"][0]
        self.assertEqual(g["base_level"], "LEVEL 4")
        self.assertEqual(g["margin_points"], 0.0)
        self.assertGreater(g["level_change_pct"], 25)
        self.assertLess(g["level_change_pct"], 75)
        self.assertEqual(g["stability"], "不穩定")
        self.assertEqual(set(g["level_distribution"]), {"LEVEL 3", "LEVEL 4"})
        self.assertEqual(res["near_boundary_count"], 1)

    def test_capital_flow_cutoff_for_level_r(self):
        res = threshold_sensitivity([_ind("H", 45.5, 70, 70, 70, 70)])    # 資金分數貼著 LEVEL R 上限 45
        h = res["industries"][0]
        self.assertEqual(h["nearest_threshold"], "lvlR_cap_max")
        self.assertIn("LEVEL R", h["level_distribution"])
        self.assertGreater(h["level_change_pct"], 0)

    def test_by_threshold_lists_affected_industries(self):
        rows = [_ind("G", 80, 80, 80, 80, 80), _ind("A", 95, 95, 95, 95, 95)]
        by = {b["threshold_key"]: b for b in threshold_sensitivity(rows)["by_threshold"]}
        self.assertEqual(by["lvl4_min"]["affected"], ["產業G"])
        self.assertEqual(by["lvl4_min"]["affected_count"], 1)
        self.assertEqual(by["lvl2_min"]["affected_count"], 0)

    def test_invalid_orderings_are_skipped(self):
        # L4=80, L3=79：L4 -2 與 L3 +2 都會違反 L4 > L3 > L2，應被略過 (508 - 2 = 506)
        th = {"numeric": {"lvl4_min": 80, "lvl3_min": 79, "lvl2_min": 62, "lvlR_cap_max": 45}}
        res = threshold_sensitivity([_ind("A", 90, 90, 90, 90, 90)], thresholds=th)
        self.assertEqual(res["scenario_count"], 506)

    def test_uses_numeric_thresholds_from_governance(self):
        th = {"numeric": {"lvl4_min": 90, "lvl3_min": 80, "lvl2_min": 70, "lvlR_cap_max": 45}}
        res = threshold_sensitivity([_ind("A", 85, 85, 85, 85, 85)], thresholds=th)   # 總分 85：LEVEL 3，距 L4 門檻 5
        self.assertEqual(res["industries"][0]["base_level"], "LEVEL 3")
        self.assertEqual(res["thresholds"]["lvl4_min"], 90.0)

    def test_deterministic_excludes_unrated_and_handles_empty(self):
        rows = [_ind("G", 80, 80, 80, 80, 80), _ind("X", 50, 50, 50, 50, 50, state="INSUFFICIENT_DATA")]
        self.assertEqual(threshold_sensitivity(rows), threshold_sensitivity(rows))
        self.assertEqual([x["industry_id"] for x in threshold_sensitivity(rows)["industries"]], ["G"])
        self.assertFalse(threshold_sensitivity([rows[1]])["available"])

    def test_weight_sensitivity_levels_follow_governance_thresholds(self):
        # 回歸測試：舊版把整包 thresholds_json 直接傳入，使用者調過門檻 (numeric) 後仍用預設值判等級
        rows = [_ind("G", 80, 80, 80, 80, 80)]
        default = sensitivity_analysis(rows, thresholds=effective_thresholds({}))["industries"][0]["base_level"]
        raised = sensitivity_analysis(rows, thresholds=effective_thresholds(
            {"numeric": {"lvl4_min": 90, "lvl3_min": 80, "lvl2_min": 70, "lvlR_cap_max": 45}}))["industries"][0]["base_level"]
        self.assertEqual((default, raised), ("LEVEL 4", "LEVEL 3"))


if __name__ == "__main__":
    unittest.main()
