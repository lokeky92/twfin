"""趨勢預警說明文字的即時產生：訊號規則、反方證據措辭、失效條件、缺失資料提醒，以及資料庫整合 (取代手寫種子、不重複、無即時資料時保留)"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="twfin_lw_test_")
sys.path.insert(0, os.path.join(ROOT, "backend"))

import live_scoring as ls  # noqa: E402
import live_warnings as lw  # noqa: E402

db = None
seed_and_compute_all = None
_ORIG_DB_PATH = None


def setUpModule():
    global db, seed_and_compute_all, _ORIG_DB_PATH
    import db as _db
    from seed_and_engine import seed_and_compute_all as _seed
    db, seed_and_compute_all = _db, _seed
    _ORIG_DB_PATH = db.DB_PATH
    db.DB_PATH = os.path.join(_TMP, "lw.db")


def tearDownModule():
    if db is not None:
        db.DB_PATH = _ORIG_DB_PATH
    shutil.rmtree(_TMP, ignore_errors=True)


def scores(cf, fu, fg, ins, va):
    return {"capital_flow": cf, "fundamentals": fu, "future_growth": fg, "institutional": ins, "valuation": va}


def metrics(**kw):
    m = {"companies": 10, "yoy": 40.0, "mom": 5.0, "cum_yoy": 30.0, "accel": 10.0, "pe_median": 20.0, "pb_median": 2.0, "peg": 0.6,
         "foreign_billion": 1.5, "itc_billion": -0.5, "dealer_billion": 0.1, "inst_net_billion": 1.0, "turnover_billion": 50.0,
         "inst_ratio_pct": 2.0, "price_coverage": 1.0, "rev_billion": 100.0, "rev_ly_billion": 70.0, "rs_pct": 1.5, "rs_days": 5,
         "share_change_pct": None}
    m.update(kw)
    return m


def build(sc, m=None, level="LEVEL 2", up=True, missing=()):
    return lw.build_warning("IND_X", "測試產業", m or metrics(), {"scores": sc, "missing": list(missing)}, 66.6, level, 13, up,
                            ls.SUB_LABELS, ls.LIMITATIONS, "2026-11-27T20:00:00+08:00")


class TestSignalRules(unittest.TestCase):
    def cat(self, *s):
        return lw.classify_signal(scores(*s))[0]

    def test_all_patterns_are_reachable_and_ordered(self):
        self.assertEqual(self.cat(80, 90, 80, 50, 50), "基本面與資金同步居前")
        self.assertEqual(self.cat(30, 90, 80, 50, 50), "基本面居前、資金流向偏弱")
        self.assertEqual(self.cat(55, 90, 80, 50, 50), "基本面居前、資金面中性")        # 以前會掉到「無明顯訊號」(實際遇過)
        self.assertEqual(self.cat(80, 50, 50, 50, 50), "資金居前、基本面排名未居前(留意追價風險)")
        self.assertEqual(self.cat(30, 30, 30, 50, 50), "資金與基本面同步落後(撤退風險)")
        self.assertEqual(self.cat(30, 55, 55, 50, 50), "資金流向落後")
        self.assertEqual(self.cat(55, 55, 55, 50, 50), "多空分歧、無明顯單向訊號")

    def test_strong_future_growth_alone_counts_as_strong_fundamentals(self):
        self.assertEqual(self.cat(80, 50, 90, 50, 50), "基本面與資金同步居前")


class TestBuildWarning(unittest.TestCase):
    def test_every_field_present_and_built_from_numbers(self):
        w = build(scores(80, 90, 80, 50, 50))
        for k in ("warning_id", "industry_id", "alert_level", "signal_category", "horizon", "trigger_reason", "raw_data_evidence",
                  "triggered_at", "source_id", "credibility_grade", "missing_data_notes", "counter_evidence", "invalidation_conditions"):
            self.assertTrue(w[k], k)
        self.assertEqual(w["warning_id"], "LIVE_IND_X")
        self.assertEqual(w["source_id"], "SRC_MOPS")
        self.assertIn("66.6", w["trigger_reason"])
        self.assertIn("+40.0%", w["raw_data_evidence"])
        self.assertIn("近 5 日相對大盤 +1.50%", w["raw_data_evidence"])
        self.assertIn("機械式規則", w["missing_data_notes"])

    def test_level_is_not_embedded_in_text_so_governance_changes_cannot_stale_it(self):
        w = build(scores(80, 90, 80, 50, 50), level="LEVEL 3")
        blob = " ".join(str(v) for k, v in w.items() if k != "alert_level")
        self.assertNotIn("LEVEL", blob)

    def test_counter_evidence_only_lists_items_that_are_actually_weak(self):
        up = build(scores(80, 90, 80, 75, 70), up=True)["counter_evidence"]          # 沒有任何項目低於 65
        self.assertIn("沒有明顯落後", up)
        mixed = build(scores(48, 95, 85, 75, 88), up=True)["counter_evidence"]
        self.assertIn("資金流向 48", mixed)
        self.assertNotIn("法人布局", mixed)                                            # 75 分不能被說成偏弱
        down = build(scores(20, 20, 20, 30, 40), up=False)["counter_evidence"]
        self.assertIn("沒有明顯居前", down)
        down2 = build(scores(20, 20, 20, 30, 68), up=False)["counter_evidence"]
        self.assertIn("估值 68", down2)

    def test_invalidation_uses_current_numbers_and_direction(self):
        up = build(scores(80, 90, 80, 50, 50), metrics(yoy=80.0), up=True)["invalidation_conditions"]
        self.assertIn("+80.0%", up)
        self.assertIn("40%", up)                      # 掉到一半以下
        down = build(scores(20, 20, 20, 30, 40), metrics(yoy=-10.0), up=False)["invalidation_conditions"]
        self.assertIn("回升", down)
        self.assertNotIn("掉到", down)

    def test_negative_growth_floor_is_zero_not_negative(self):
        w = build(scores(80, 90, 80, 50, 50), metrics(yoy=-4.0), up=True)
        self.assertIn("0%", w["invalidation_conditions"])
        self.assertNotIn("-2%", w["invalidation_conditions"])

    def test_missing_data_notes_are_honest(self):
        w = build(scores(50, 50, 50, 50, 50), metrics(price_coverage=0.8, share_change_pct=None), missing=["capital_flow"])
        self.assertIn("本次缺少：資金流向", w["missing_data_notes"])
        self.assertIn("覆蓋率 80%", w["missing_data_notes"])
        self.assertIn("至少 2 天歷史", w["missing_data_notes"])
        self.assertTrue(w["credibility_grade"].startswith("B級"))
        ok = build(scores(50, 50, 50, 50, 50), metrics(share_change_pct=3.0))
        self.assertNotIn("覆蓋率", ok["missing_data_notes"])
        self.assertNotIn("至少 2 天歷史", ok["missing_data_notes"])
        self.assertTrue(ok["credibility_grade"].startswith("A級"))

    def test_one_off_month_warning_when_monthly_and_cumulative_diverge(self):
        w = build(scores(20, 20, 30, 30, 70), metrics(yoy=-50.0, cum_yoy=28.0), up=False)
        self.assertIn("一次性", w["missing_data_notes"])
        calm = build(scores(20, 20, 30, 30, 70), metrics(yoy=30.0, cum_yoy=28.0), up=False)
        self.assertNotIn("一次性", calm["missing_data_notes"])

    def test_text_with_na_values_does_not_crash(self):
        m = metrics(yoy=None, cum_yoy=None, accel=None, pe_median=None, peg=None, rs_pct=None, inst_ratio_pct=None)
        w = build(scores(50, 50, 50, 50, 50), m)
        self.assertIn("N/A", w["raw_data_evidence"])
        self.assertNotIn("None", " ".join(str(v) for v in w.values()))


class TestDatabaseIntegration(unittest.TestCase):
    def setUp(self):
        db.init_database()                       # 全新的暫存庫第一次還沒有資料表
        conn = db.get_connection()
        conn.execute("DELETE FROM industry_rotation_scores")
        conn.execute("DELETE FROM industry_score_history")
        conn.execute("DELETE FROM trend_early_warnings")          # 上一個測試產生的即時預警不會被種子重灌覆蓋
        conn.commit()
        conn.close()
        seed_and_compute_all()

    def _load(self, conn):
        """替每個可評分產業塞 4 家公司 (營收年增與法人買賣隨序號遞增)、收盤價與類股指數；回傳產業 id 清單。"""
        from backtest import BENCHMARK_INDEX, INDUSTRY_INDEX_MAP
        for t in ("live_company_fundamentals", "live_stock_quotes", "live_market_indices"):
            conn.execute(f"DELETE FROM {t}")
        version = conn.execute("SELECT version_id FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        ids = [r[0] for r in conn.execute("SELECT industry_id FROM industry_rotation_scores WHERE model_version = ? "
                                          "AND rotation_state != 'INSUFFICIENT_DATA' ORDER BY industry_id", (version,))]
        for k, ind in enumerate(ids):
            for j in range(4):
                code = f"{k:02d}{j}0"
                conn.execute("""INSERT INTO live_company_fundamentals
                    (company_code, company_name, market_type, official_industry, mapped_industry_id, data_ym, report_date,
                     rev_current_thousand, rev_prev_month_thousand, rev_last_year_thousand, rev_mom_pct, rev_yoy_pct,
                     cum_rev_current_thousand, cum_rev_last_year_thousand, cum_rev_yoy_pct, pe_ratio, pb_ratio, dividend_yield,
                     foreign_net_shares, itc_net_shares, dealer_net_shares, total_3insti_net_shares, insti_trade_date,
                     fetched_at, source_url, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (code, f"公司{code}", "TWSE", "x", ind, "11510", "1151110", 100.0 + 10 * k, 100.0, 100.0, 0, 10 * k,
                              1000.0 + 20 * k, 1000.0, 0, 20.0, 2.0, 3.0, 100_000 * (k - 6), 0, 0, 0, "20261127", "t", "u", ""))
                conn.execute("INSERT INTO live_stock_quotes VALUES (?,?,?,?,?,?,?)", (code, "2026-11-27", "TWSE", 100.0, 0.5, 1e9, "t"))
        for k, ind in enumerate(ids):
            for d in range(5):
                conn.execute("INSERT OR REPLACE INTO live_market_indices VALUES (?,?,?,?,?,?,?,?)",
                             (INDUSTRY_INDEX_MAP[ind], f"115112{d}", 100.0, "+", 0, 0.1 * k, "t", "u"))
        for d in range(5):
            conn.execute("INSERT OR REPLACE INTO live_market_indices VALUES (?,?,?,?,?,?,?,?)",
                         (BENCHMARK_INDEX, f"115112{d}", 100.0, "+", 0, 0.0, "t", "u"))
        conn.commit()
        return ids

    def test_seed_warnings_replaced_by_one_live_warning_per_scored_industry(self):
        conn = db.get_connection()
        seeded = conn.execute("SELECT COUNT(*) FROM trend_early_warnings WHERE text_source = 'seed'").fetchone()[0]
        self.assertGreater(seeded, 0)
        ids = self._load(conn)
        res = ls.apply_live_scoring(conn)
        self.assertEqual(res["warnings_synced"], len(ids))
        rows = conn.execute("SELECT * FROM trend_early_warnings").fetchall()
        conn.close()
        by = {r["industry_id"]: r for r in rows}
        self.assertEqual(set(by) & set(ids), set(ids))
        self.assertEqual(len(rows), len({r["industry_id"] for r in rows}))                 # 每個產業只有一則
        for i in ids:
            self.assertEqual(by[i]["text_source"], "live")
            self.assertEqual(by[i]["warning_id"], f"LIVE_{i}")
            self.assertNotIn("2026-11-22", by[i]["triggered_at"])                           # 不再是手寫時點
        self.assertFalse([r for r in rows if r["warning_id"].startswith("WARN_202611") and r["industry_id"] in ids])

    def test_levels_match_classification_and_text_never_mentions_old_handwritten_facts(self):
        from scoring import classify_alert_level, effective_thresholds
        conn = db.get_connection()
        ids = self._load(conn)
        ls.apply_live_scoring(conn)
        version = conn.execute("SELECT version_id, thresholds_json FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1").fetchone()
        th = effective_thresholds(json.loads(version["thresholds_json"]))
        for w in conn.execute("SELECT * FROM trend_early_warnings WHERE text_source = 'live'").fetchall():
            r = conn.execute("SELECT total_weighted_score, score_capital_flow FROM industry_rotation_scores WHERE industry_id = ? AND model_version = ?",
                             (w["industry_id"], version["version_id"])).fetchone()
            self.assertEqual(w["alert_level"], classify_alert_level(r["total_weighted_score"], r["score_capital_flow"], th))
            blob = " ".join(str(w[k]) for k in ("trigger_reason", "raw_data_evidence", "counter_evidence", "invalidation_conditions"))
            for stale in ("奇鋐", "新青安", "26萬棟", "費半", "5,868.9"):
                self.assertNotIn(stale, blob)
        conn.close()

    def test_rerun_after_reseed_does_not_duplicate(self):
        conn = db.get_connection()
        ids = self._load(conn)
        ls.apply_live_scoring(conn)
        conn.close()
        seed_and_compute_all()                        # 下一次排程：手寫預警又被重灌
        conn = db.get_connection()
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM trend_early_warnings WHERE text_source = 'seed'").fetchone()[0], 0)
        ls.apply_live_scoring(conn)
        per = conn.execute("SELECT industry_id, COUNT(*) c FROM trend_early_warnings GROUP BY industry_id").fetchall()
        conn.close()
        self.assertTrue(all(r["c"] == 1 for r in per))
        self.assertEqual(len({r["industry_id"] for r in per} & set(ids)), len(ids))

    def test_without_live_data_handwritten_warnings_are_kept(self):
        conn = db.get_connection()
        conn.execute("DELETE FROM live_company_fundamentals")
        conn.commit()
        before = conn.execute("SELECT warning_id FROM trend_early_warnings ORDER BY 1").fetchall()
        self.assertFalse(ls.apply_live_scoring(conn)["applied"])
        after = conn.execute("SELECT warning_id, text_source FROM trend_early_warnings ORDER BY 1").fetchall()
        conn.close()
        self.assertEqual([r[0] for r in before], [r[0] for r in after])
        self.assertTrue(all(r[1] == "seed" for r in after))

    def test_payload_exposes_text_source_and_publisher(self):
        import server
        conn = db.get_connection()
        self._load(conn)
        ls.apply_live_scoring(conn)
        conn.close()
        server.invalidate_dashboard_cache()
        ws = server.get_dashboard_payload(use_cache=False)["warnings"]
        self.assertTrue(ws and all(w["text_source"] == "live" for w in ws))
        self.assertTrue(all(w["publisher"] for w in ws))                                   # 前端顯示「來源」需要


if __name__ == "__main__":
    unittest.main()
