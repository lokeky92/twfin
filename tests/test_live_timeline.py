"""歷史時間軸：由 industry_score_history 的真實快照產生 (離線，純函式 + 記憶體資料庫)"""
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import live_timeline as lt  # noqa: E402

TH = {"level4_min": 80, "level3_min": 70}


def row(day, iid, score, state="C", src="live", level="LEVEL 2", cf=50.0):
    return {"snapshot_date": day, "industry_id": iid, "total_weighted_score": score, "score_capital_flow": cf,
            "rotation_state": state, "alert_level": level, "score_source": src}


NAMES = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}


class TestBuildPoints(unittest.TestCase):
    def test_orders_days_and_marks_first_without_prev(self):
        rows = [row("2026-11-26", "A", 50), row("2026-11-25", "A", 40)]
        out = lt.build_points(rows, NAMES, TH)
        self.assertEqual([p["date"] for p in out["points"]], ["2026-11-25", "2026-11-26"])
        self.assertFalse(out["points"][0]["has_prev"])
        self.assertTrue(out["points"][1]["has_prev"])

    def test_hot_cold_and_movers(self):
        rows = [row("2026-11-25", "A", 40), row("2026-11-25", "B", 60), row("2026-11-25", "C", 50), row("2026-11-25", "D", 30),
                row("2026-11-26", "A", 55), row("2026-11-26", "B", 50), row("2026-11-26", "C", 51), row("2026-11-26", "D", 28)]
        p = lt.build_points(rows, NAMES, TH)["points"][1]
        self.assertEqual(p["hot"][0], {"name": "甲", "score": 55.0})
        self.assertEqual(p["cold"][0], {"name": "丁", "score": 28.0})
        self.assertEqual(p["movers_up"][0], {"name": "甲", "delta": 15.0})
        self.assertEqual(p["movers_down"][0], {"name": "乙", "delta": -10.0})

    def test_unscored_industries_are_not_ranked(self):
        rows = [row("2026-11-25", "A", None, state="INSUFFICIENT_DATA", level=None), row("2026-11-25", "B", 60)]
        p = lt.build_points(rows, NAMES, TH)["points"][0]
        self.assertEqual(p["scored"], 1)
        self.assertEqual(p["total"], 2)
        self.assertEqual([h["name"] for h in p["hot"]], ["乙"])
        self.assertIsNone(p["scores"]["A"]["score"])

    def test_source_live_wins_when_mixed_on_same_day(self):
        rows = [row("2026-11-25", "A", 40, src="seed"), row("2026-11-25", "B", 60, src="live")]
        self.assertEqual(lt.build_points(rows, NAMES, TH)["points"][0]["source"], "live")
        self.assertEqual(lt.build_points([row("2026-11-25", "A", 40, src="seed")], NAMES, TH)["points"][0]["source"], "seed")

    def test_level_counts(self):
        rows = [row("2026-11-25", "A", 80, level="LEVEL 4"), row("2026-11-25", "B", 30, level="LEVEL R"), row("2026-11-25", "C", 31, level="LEVEL R")]
        self.assertEqual(lt.build_points(rows, NAMES, TH)["points"][0]["levels"], {"LEVEL 4": 1, "LEVEL R": 2})

    def test_missing_alert_level_is_recomputed(self):
        r = row("2026-11-25", "A", 85, level=None, cf=90.0)
        p = lt.build_points([r], NAMES, TH)["points"][0]
        self.assertIsNotNone(p["scores"]["A"]["level"])

    def test_max_points_keeps_latest(self):
        rows = [row(f"2026-11-{d:02d}", "A", 40 + d) for d in range(1, 11)]
        out = lt.build_points(rows, NAMES, TH, max_points=4)
        self.assertEqual([p["date"] for p in out["points"]], ["2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10"])
        self.assertEqual(out["total_days"], 10)

    def test_empty(self):
        self.assertFalse(lt.build_points([], NAMES, TH)["available"])


class TestWeekly(unittest.TestCase):
    def points(self, n, src="live", last_src=None):
        rows = []
        for k in range(n):
            day = f"2026-11-{k + 1:02d}"
            s = last_src if (last_src and k == n - 1) else src
            rows += [row(day, "A", 40 + k * 3, src=s, level="LEVEL 2" if k < n - 1 else "LEVEL 3"),
                     row(day, "B", 60 - k * 2, src=s, level="LEVEL 3")]
        return lt.build_points(rows, NAMES, TH)["points"]

    def test_needs_two_snapshots(self):
        self.assertFalse(lt.weekly_changes(self.points(1), [], NAMES)["available"])

    def test_week_compares_with_five_days_back_and_levels(self):
        pts = self.points(8)
        w = lt.weekly_changes(pts, [], NAMES)
        self.assertEqual(w["gap_days"], 5)
        self.assertEqual(w["from_date"], "2026-11-03")
        self.assertEqual(w["score_up"][0]["name"], "甲")
        self.assertEqual(w["score_up"][0]["delta"], 15.0)
        self.assertEqual(w["score_down"][0]["name"], "乙")
        self.assertEqual(w["level_changes"], [{"name": "甲", "from": "LEVEL 2", "to": "LEVEL 3", "direction": "up"}])
        self.assertFalse(w["mixed_scale"])

    def test_short_history_uses_first_snapshot_and_reports_gap(self):
        w = lt.weekly_changes(self.points(3), [], NAMES)
        self.assertEqual(w["gap_days"], 2)
        self.assertEqual(w["from_date"], "2026-11-01")

    def test_mixed_scale_is_flagged(self):
        w = lt.weekly_changes(self.points(4, src="seed", last_src="live"), [], NAMES)
        self.assertTrue(w["mixed_scale"])

    def test_institutional_five_day_and_flips(self):
        days = [f"2026-11-{d:02d}" for d in range(1, 11)]
        inst = []
        for k, d in enumerate(days):
            inst.append({"trade_date": d, "industry_id": "A", "foreign_billion": 10.0 if k >= 5 else -10.0, "itc_billion": 0.0})
            inst.append({"trade_date": d, "industry_id": "B", "foreign_billion": -5.0, "itc_billion": -1.0})
        w = lt.weekly_changes(self.points(8), inst, NAMES)
        i = w["inst"]
        self.assertEqual(i["buy"], [{"name": "甲", "value": 50.0}])
        self.assertEqual(i["sell"], [{"name": "乙", "value": -30.0}])
        self.assertEqual([f["name"] for f in i["flips"]], ["甲"])     # 前 5 日賣超、近 5 日買超

    def test_no_institutional_rows(self):
        self.assertFalse(lt.weekly_changes(self.points(3), [], NAMES)["inst"]["available"])


class TestFromDatabase(unittest.TestCase):
    def test_missing_tables_is_unavailable(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.assertFalse(lt.build_timeline_history(conn)["available"])

    def test_reads_active_model_only(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE model_governance_configs (version_id TEXT, thresholds_json TEXT, active INTEGER, created_at TEXT);
            CREATE TABLE industry_taxonomy (industry_id TEXT, industry_name TEXT);
            CREATE TABLE industry_score_history (snapshot_date TEXT, industry_id TEXT, model_version TEXT, total_weighted_score REAL,
                score_capital_flow REAL, rotation_state TEXT, alert_level TEXT, score_source TEXT);
            INSERT INTO model_governance_configs VALUES ('v2', '{}', 1, '2026-11-01');
            INSERT INTO model_governance_configs VALUES ('v1', '{}', 0, '2026-10-01');
            INSERT INTO industry_taxonomy VALUES ('A', '甲');
            INSERT INTO industry_score_history VALUES ('2026-11-25', 'A', 'v2', 50, 50, 'C', 'LEVEL 2', 'live');
            INSERT INTO industry_score_history VALUES ('2026-11-24', 'A', 'v1', 99, 50, 'A', 'LEVEL 4', 'seed');""")
        out = lt.build_timeline_history(conn)
        self.assertTrue(out["available"])
        self.assertEqual([p["date"] for p in out["points"]], ["2026-11-25"])
        self.assertEqual(out["points"][0]["scores"]["A"]["name"], "甲")


if __name__ == "__main__":
    unittest.main()
