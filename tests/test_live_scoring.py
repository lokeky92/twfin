"""即時評分：百分位與指標計算、子分數方向、缺資料處理、資金流向矩陣、資料庫整合 (權重沿用、種子不被覆蓋、可重複執行)"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="twfin_ls_test_")
sys.path.insert(0, os.path.join(ROOT, "backend"))

import live_scoring as ls  # noqa: E402
from scoring import compute_weighted_total  # noqa: E402

# db.DB_PATH 在第一次 import db 時就固定了，環境變數沒用；與其他測試一樣在 setUpModule 改路徑、結束後還原，
# 這樣不會動到真實資料庫，也不會影響其他測試模組的暫存庫。
db = None
seed_and_compute_all = None
_ORIG_DB_PATH = None


def get_connection():
    return db.get_connection()


def setUpModule():
    global db, seed_and_compute_all, _ORIG_DB_PATH
    import db as _db
    from seed_and_engine import seed_and_compute_all as _seed
    db, seed_and_compute_all = _db, _seed
    _ORIG_DB_PATH = db.DB_PATH
    db.DB_PATH = os.path.join(_TMP, "ls.db")


def tearDownModule():
    if db is not None:
        db.DB_PATH = _ORIG_DB_PATH
    shutil.rmtree(_TMP, ignore_errors=True)


def comp(ind, rev_cur=100, rev_prev=100, rev_ly=100, cum_cur=1000, cum_ly=1000, pe=20, pb=2,
         f=0, i=0, d=0, close=100.0, tv=1e9, code=None):
    return {"industry": ind, "company_code": code, "rev_cur": rev_cur, "rev_prev": rev_prev, "rev_ly": rev_ly,
            "cum_cur": cum_cur, "cum_ly": cum_ly, "pe": pe, "pb": pb, "foreign": f, "itc": i, "dealer": d,
            "close": close, "trade_value": tv}


def industry(ind, n=3, **kw):
    return [comp(ind, **kw) for _ in range(n)]


class TestPureFunctions(unittest.TestCase):
    def test_pct_rank_handles_none_and_ties(self):
        self.assertEqual(ls.pct_rank([None, None]), [None, None])
        self.assertEqual(ls.pct_rank([5, None]), [0.5, None])
        self.assertEqual(ls.pct_rank([1, None, 3, 2]), [0.0, None, 1.0, 0.5])
        self.assertEqual(ls.pct_rank([2, 2, 2]), [0.5, 0.5, 0.5])

    def test_to_score_range(self):
        self.assertEqual(ls.to_score(0.0), 15.0)
        self.assertEqual(ls.to_score(1.0), 95.0)
        self.assertIsNone(ls.to_score(None))

    def test_metrics_growth_valuation_and_coverage(self):
        rows = industry("A", rev_cur=200, rev_prev=100, rev_ly=100, cum_cur=1500, cum_ly=1000, pe=24)
        m = ls.compute_industry_metrics(rows)["A"]
        self.assertAlmostEqual(m["yoy"], 100.0)
        self.assertAlmostEqual(m["mom"], 100.0)
        self.assertAlmostEqual(m["cum_yoy"], 50.0)
        self.assertAlmostEqual(m["accel"], 50.0)
        self.assertAlmostEqual(m["peg"], 24 / 50.0)          # 本益比中位數 ÷ 累計營收年增
        self.assertEqual(m["pe_median"], 24.0)

    def test_peg_growth_floor_prevents_division_by_tiny_or_negative(self):
        rows = industry("A", cum_cur=900, cum_ly=1000, pe=20)    # 累計年增 −10%
        self.assertAlmostEqual(ls.compute_industry_metrics(rows)["A"]["peg"], 20 / ls.PEG_GROWTH_FLOOR)

    def test_negative_or_missing_pe_excluded_from_median(self):
        rows = [comp("A", pe=-5), comp("A", pe=None), comp("A", pe=10), comp("A", pe=30)]
        self.assertEqual(ls.compute_industry_metrics(rows)["A"]["pe_median"], 20.0)

    def test_institutional_amount_uses_shares_times_close(self):
        rows = industry("A", f=1_000_000, i=500_000, d=-200_000, close=100.0, tv=2e9)
        m = ls.compute_industry_metrics(rows)["A"]
        self.assertAlmostEqual(m["foreign_billion"], 3 * 1_000_000 * 100 / 1e8)    # 3 家 × 100萬股 × 100 元 = 3 億
        self.assertAlmostEqual(m["itc_billion"], 1.5)
        self.assertAlmostEqual(m["dealer_billion"], -0.6)
        self.assertAlmostEqual(m["turnover_billion"], 3 * 2e9 / 1e8)
        self.assertAlmostEqual(m["inst_ratio_pct"], (3 + 1.5) / 60 * 100, places=3)

    def test_low_price_coverage_is_missing_not_misleading(self):
        # 3 家有法人資料但只有 1 家有收盤價：覆蓋率 33% < 60% → 法人強度視為缺資料，不拿殘缺的金額去排名
        rows = [comp("A", f=100, close=50.0), comp("A", f=100, close=None), comp("A", f=100, close=None)]
        m = ls.compute_industry_metrics(rows)["A"]
        self.assertAlmostEqual(m["price_coverage"], 1 / 3, places=3)
        self.assertIsNone(m["inst_ratio_pct"])

    def test_small_industries_are_not_scored(self):
        self.assertEqual(ls.compute_industry_metrics(industry("A", n=2)), {})

    def test_turnover_share_change_needs_history(self):
        rows = industry("A") + industry("B")
        one_day = {"2026-11-27": {"A": 1e9, "B": 1e9}}
        self.assertIsNone(ls.compute_industry_metrics(rows, one_day)["A"]["share_change_pct"])
        hist = {"2026-11-26": {"A": 1e9, "B": 3e9}, "2026-11-27": {"A": 3e9, "B": 1e9}}    # A 占比 25% → 75%
        m = ls.compute_industry_metrics(rows, hist)
        self.assertAlmostEqual(m["A"]["share_change_pct"], 200.0)
        self.assertAlmostEqual(m["B"]["share_change_pct"], -66.67, places=1)


class TestScoring(unittest.TestCase):
    def world(self):
        rows = []
        rows += industry("HOT", rev_cur=300, rev_ly=100, cum_cur=2000, cum_ly=1000, pe=15, f=5_000_000, tv=1e9)
        rows += industry("MID", rev_cur=150, rev_ly=100, cum_cur=1300, cum_ly=1000, pe=25, f=0, tv=1e9)
        rows += industry("COLD", rev_cur=50, rev_ly=100, cum_cur=800, cum_ly=1000, pe=60, f=-5_000_000, tv=1e9)
        return ls.compute_industry_metrics(rows, rel_returns={"HOT": {"pct": 5, "days": 5}, "MID": {"pct": 0, "days": 5},
                                                              "COLD": {"pct": -5, "days": 5}})

    def test_directions(self):
        r = ls.score_industries(self.world())
        for key in ls.SUB_KEYS:
            self.assertGreater(r["HOT"]["scores"][key], r["COLD"]["scores"][key], key)    # 各項都是越強分數越高
        self.assertEqual(r["HOT"]["missing"], [])
        self.assertEqual(r["HOT"]["state"], "A")
        self.assertEqual(r["COLD"]["state"], "E")

    def test_valuation_cheaper_per_growth_scores_higher(self):
        rows = industry("CHEAP", cum_cur=2000, cum_ly=1000, pe=10) + industry("RICH", cum_cur=2000, cum_ly=1000, pe=80)
        r = ls.score_industries(ls.compute_industry_metrics(rows))
        self.assertGreater(r["CHEAP"]["scores"]["valuation"], r["RICH"]["scores"]["valuation"])

    def test_missing_subscores_use_neutral_and_lower_confidence(self):
        m = self.world()
        for k in m:
            m[k]["rs_pct"] = None
            m[k]["share_change_pct"] = None        # 資金流向兩個來源都沒有
        r = ls.score_industries(m)
        self.assertEqual(r["HOT"]["missing"], ["capital_flow"])
        self.assertEqual(r["HOT"]["scores"]["capital_flow"], ls.NEUTRAL)
        self.assertIn("中", r["HOT"]["confidence"])

    def test_excluded_industries_not_ranked(self):
        r = ls.score_industries(self.world(), excluded={"COLD"})
        self.assertNotIn("COLD", r)
        self.assertEqual(set(r), {"HOT", "MID"})

    def test_state_boundaries(self):
        self.assertEqual(next((s for s, c in ls.STATE_CUTS if 75.0 >= c), "E"), "A")
        self.assertEqual(next((s for s, c in ls.STATE_CUTS if 74.9 >= c), "E"), "B")
        self.assertEqual(next((s for s, c in ls.STATE_CUTS if 27.9 >= c), "E"), "E")

    def test_narrative_is_built_from_numbers(self):
        m = self.world()
        res = ls.score_industries(m)
        sup, cnt, inv, facts = ls.build_narrative("熱門產業", m["HOT"], res["HOT"])
        self.assertIn("營收年增 +200.0%", facts["fundamentals"])
        self.assertTrue(sup and cnt and inv)
        self.assertNotIn("N/A", facts["valuation"].split("、")[0])


class TestFlowMatrix(unittest.TestCase):
    def test_buy_sell_split_and_totals(self):
        rows = (industry("A", f=1_000_000, i=-200_000, d=0, close=100.0)
                + industry("B", f=-500_000, i=300_000, d=100_000, close=100.0))
        m = ls.compute_industry_metrics(rows)
        fm = ls.flow_matrix(m, {"A": "產業甲", "B": "產業乙"}, "20261127")
        self.assertTrue(fm["available"])
        self.assertEqual(fm["as_of"], "2026-11-27")
        by = {r["id"]: r for r in fm["industries"]}
        self.assertAlmostEqual(by["A"]["flows"]["foreign"], 3.0)
        self.assertAlmostEqual(by["A"]["flows"]["itc"], -0.6)
        self.assertAlmostEqual(by["A"]["buy"], 3.0)
        self.assertAlmostEqual(by["A"]["sell"], 0.6)
        self.assertAlmostEqual(by["A"]["net"], 2.4)
        inst = {i["key"]: i for i in fm["institutions"]}
        self.assertAlmostEqual(inst["foreign"]["buy"], 3.0)
        self.assertAlmostEqual(inst["foreign"]["sell"], 1.5)
        self.assertAlmostEqual(inst["foreign"]["net"], 1.5)
        # 每個 (法人, 產業) 不是買超就是賣超；各欄加總必須守恆
        self.assertAlmostEqual(sum(r["buy"] for r in fm["industries"]), sum(i["buy"] for i in fm["institutions"]))
        self.assertAlmostEqual(sum(r["sell"] for r in fm["industries"]), sum(i["sell"] for i in fm["institutions"]))
        self.assertEqual([r["id"] for r in fm["industries"]], ["A", "B"])     # 依淨額由高到低

    def test_empty_is_unavailable(self):
        self.assertFalse(ls.flow_matrix({}, {}, None)["available"])


class TestDatabaseIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_and_compute_all()

    def setUp(self):
        conn = get_connection()
        conn.execute("DELETE FROM industry_rotation_scores")    # 上一個測試改過日期的即時列不會被種子重灌覆蓋，先清掉
        conn.execute("DELETE FROM industry_score_history")
        conn.commit()
        conn.close()
        seed_and_compute_all()     # 乾淨的種子分數 (INSERT OR REPLACE 會把 score_source 重設為 'seed')

    def _ids(self, conn):
        return [r[0] for r in conn.execute("SELECT industry_id FROM industry_rotation_scores WHERE model_version = ? "
                                           "AND rotation_state != 'INSUFFICIENT_DATA' ORDER BY industry_id", (self._version(conn),))]

    def _version(self, conn):
        return conn.execute("SELECT version_id FROM model_governance_configs WHERE active = 1 "
                            "ORDER BY created_at DESC LIMIT 1").fetchone()[0]

    def _load_world(self, conn, idx_days=5):
        """替每個可評分產業塞 4 家公司 (營收年增與法人買賣依序遞增)，外加收盤價與類股指數。"""
        conn.execute("DELETE FROM live_company_fundamentals")
        conn.execute("DELETE FROM live_stock_quotes")
        conn.execute("DELETE FROM live_market_indices")
        ids = self._ids(conn)
        for k, ind in enumerate(ids):
            for j in range(4):
                code = f"{k:02d}{j}0"
                conn.execute("""INSERT INTO live_company_fundamentals
                    (company_code, company_name, market_type, official_industry, mapped_industry_id, data_ym, report_date,
                     rev_current_thousand, rev_prev_month_thousand, rev_last_year_thousand, rev_mom_pct, rev_yoy_pct,
                     cum_rev_current_thousand, cum_rev_last_year_thousand, cum_rev_yoy_pct, pe_ratio, pb_ratio, dividend_yield,
                     foreign_net_shares, itc_net_shares, dealer_net_shares, total_3insti_net_shares, insti_trade_date,
                     fetched_at, source_url, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (code, f"公司{code}", "TWSE", "x", ind, "11510", "1151110",
                              100.0 + 10 * k, 100.0, 100.0, 0, 10 * k, 1000.0 + 20 * k, 1000.0, 0, 20.0, 2.0, 3.0,
                              100_000 * (k - 6), 0, 0, 0, "20261127", "t", "u", ""))
                conn.execute("INSERT INTO live_stock_quotes VALUES (?,?,?,?,?,?,?)",
                             (code, "2026-11-27", "TWSE", 100.0, 0.5, 1e9, "t"))
        # 類股報酬指數：序號越大的產業表現越好
        for k, ind in enumerate(ids):
            name = ls_index_name(ind)
            for d in range(idx_days):
                conn.execute("INSERT OR REPLACE INTO live_market_indices VALUES (?,?,?,?,?,?,?,?)",
                             (name, f"115112{d}", 100.0, "+", 0, 0.1 * k, "t", "u"))
        for d in range(idx_days):
            conn.execute("INSERT OR REPLACE INTO live_market_indices VALUES (?,?,?,?,?,?,?,?)",
                         (bench_name(), f"115112{d}", 100.0, "+", 0, 0.0, "t", "u"))
        conn.commit()
        return ids

    def test_no_live_data_leaves_seed_scores_untouched(self):
        conn = get_connection()
        conn.execute("DELETE FROM live_company_fundamentals")
        conn.commit()
        before = conn.execute("SELECT industry_id, total_weighted_score, score_source FROM industry_rotation_scores").fetchall()
        res = ls.apply_live_scoring(conn)
        after = conn.execute("SELECT industry_id, total_weighted_score, score_source FROM industry_rotation_scores").fetchall()
        conn.close()
        self.assertFalse(res["applied"])
        self.assertEqual([tuple(r) for r in before], [tuple(r) for r in after])
        self.assertTrue(all(r[2] == "seed" for r in after))

    def test_apply_live_scoring_recomputes_with_active_weights_and_is_idempotent(self):
        conn = get_connection()
        ids = self._load_world(conn)
        version = self._version(conn)
        res = ls.apply_live_scoring(conn)
        self.assertTrue(res["applied"])
        self.assertEqual(res["industries"], len(ids))

        rows = {r["industry_id"]: dict(r) for r in conn.execute("SELECT * FROM industry_rotation_scores WHERE model_version = ?", (version,))}
        weights = json.loads(conn.execute("SELECT weights_json FROM model_governance_configs WHERE version_id = ?", (version,)).fetchone()[0])
        for ind in ids:
            r = rows[ind]
            self.assertEqual(r["score_source"], "live")
            self.assertEqual(r["total_weighted_score"], compute_weighted_total(r, weights))   # 沿用啟用版本的權重
            self.assertIn(r["rotation_state"], "ABCDE")
            self.assertTrue(r["supporting_evidence"] and r["counter_evidence"])
            self.assertIn("代理指標", r["data_limitations"])
        # 序號大 (營收年增高、法人買超、指數強) 的產業總分較高
        self.assertGreater(rows[ids[-1]]["total_weighted_score"], rows[ids[0]]["total_weighted_score"])
        # 異質混合分類維持不評分，不被硬排名
        bio = rows["IND_BIO_RETAIL"]
        self.assertEqual(bio["rotation_state"], "INSUFFICIENT_DATA")
        self.assertIsNone(bio["total_weighted_score"])
        self.assertEqual(bio["score_source"], "seed")

        first = {k: v["total_weighted_score"] for k, v in rows.items()}
        ls.apply_live_scoring(conn)
        again = {r["industry_id"]: r["total_weighted_score"] for r in conn.execute(
            "SELECT industry_id, total_weighted_score FROM industry_rotation_scores WHERE model_version = ?", (version,))}
        self.assertEqual(first, again)                                                         # 重複執行結果相同
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM industry_rotation_scores WHERE model_version = ?", (version,)).fetchone()[0],
                         len(rows))                                                            # 不會多出列
        conn.close()

    def test_reseeding_between_runs_does_not_duplicate_rows_or_hit_unique_key(self):
        """每次排程先重灌種子列再評分；啟用版本是種子版本時，不能因此出現重複列或唯一鍵衝突 (實際遇過的漏洞)。"""
        conn = get_connection()
        self._load_world(conn)
        version = self._version(conn)
        ls.apply_live_scoring(conn)
        conn.close()
        seed_and_compute_all()                    # 第二次排程：種子列 (資料日 2026-11-21) 又被插入
        conn = get_connection()
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM industry_rotation_scores WHERE model_version = ?", (version,)).fetchone()[0], 14)
        res = ls.apply_live_scoring(conn)         # 不可丟出 IntegrityError
        self.assertTrue(res["applied"])
        per = conn.execute("SELECT industry_id, COUNT(*) c FROM industry_rotation_scores WHERE model_version = ? GROUP BY industry_id",
                           (version,)).fetchall()
        conn.close()
        self.assertTrue(per and all(r["c"] == 1 for r in per))

    def test_warning_levels_follow_live_scores(self):
        conn = get_connection()
        self._load_world(conn)
        conn.execute("UPDATE trend_early_warnings SET alert_level = 'LEVEL 1'")
        conn.commit()
        res = ls.apply_live_scoring(conn)
        self.assertGreater(res["warnings_synced"], 0)
        from scoring import classify_alert_level, effective_thresholds
        version = self._version(conn)
        th = effective_thresholds(json.loads(conn.execute("SELECT thresholds_json FROM model_governance_configs WHERE version_id = ?", (version,)).fetchone()[0]))
        for w in conn.execute("SELECT industry_id, alert_level FROM trend_early_warnings").fetchall():
            r = conn.execute("SELECT total_weighted_score, score_capital_flow, score_source FROM industry_rotation_scores "
                             "WHERE industry_id = ? AND model_version = ?", (w["industry_id"], version)).fetchone()
            if r and r["score_source"] == "live":
                self.assertEqual(w["alert_level"], classify_alert_level(r["total_weighted_score"], r["score_capital_flow"], th))
        conn.close()

    def test_custom_weights_are_respected(self):
        conn = get_connection()
        ids = self._load_world(conn)
        version = self._version(conn)
        original = conn.execute("SELECT weights_json FROM model_governance_configs WHERE version_id = ?", (version,)).fetchone()[0]
        only_fund = {"capital_flow": 0.0, "fundamentals": 1.0, "future_growth": 0.0, "institutional": 0.0, "valuation": 0.0}
        conn.execute("UPDATE model_governance_configs SET weights_json = ? WHERE version_id = ?", (json.dumps(only_fund), version))
        conn.commit()
        try:
            ls.apply_live_scoring(conn)
            for r in conn.execute("SELECT industry_id, total_weighted_score, score_fundamentals FROM industry_rotation_scores "
                                  "WHERE model_version = ? AND score_source = 'live'", (version,)):
                self.assertAlmostEqual(r["total_weighted_score"], r["score_fundamentals"], places=2)
        finally:
            conn.execute("UPDATE model_governance_configs SET weights_json = ? WHERE version_id = ?", (original, version))
            conn.commit()
            conn.close()

    def test_snapshot_records_live_source(self):
        from history import snapshot_industry_scores
        conn = get_connection()
        self._load_world(conn)
        ls.apply_live_scoring(conn)
        conn.close()
        snapshot_industry_scores("2026-11-27")
        conn = get_connection()
        srcs = dict(conn.execute("SELECT industry_id, score_source FROM industry_score_history WHERE snapshot_date = '2026-11-27'").fetchall())
        conn.close()
        self.assertEqual(srcs["IND_BIO_RETAIL"], "seed")
        self.assertEqual({v for k, v in srcs.items() if k != "IND_BIO_RETAIL"}, {"live"})


def bench_name():
    from backtest import BENCHMARK_INDEX
    return BENCHMARK_INDEX


def ls_index_name(industry_id):
    from backtest import INDUSTRY_INDEX_MAP
    return INDUSTRY_INDEX_MAP[industry_id]


if __name__ == "__main__":
    unittest.main()
