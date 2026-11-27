"""個股研究名單、固定研究報告、三大法人表／總體指標的即時化：分類規則、文字不含手寫事實、重疊的手寫列被排除、資料庫整合與重跑安全"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="twfin_lwr_test_")
sys.path.insert(0, os.path.join(ROOT, "backend"))

import live_reports as lr  # noqa: E402
import live_views as lv  # noqa: E402
import live_watchlist as lw  # noqa: E402

db = None
seed_and_compute_all = None
_ORIG_DB_PATH = None


def setUpModule():
    global db, seed_and_compute_all, _ORIG_DB_PATH
    import db as _db
    from seed_and_engine import seed_and_compute_all as _seed
    db, seed_and_compute_all = _db, _seed
    _ORIG_DB_PATH = db.DB_PATH
    db.DB_PATH = os.path.join(_TMP, "lwr.db")


def tearDownModule():
    if db is not None:
        db.DB_PATH = _ORIG_DB_PATH
    shutil.rmtree(_TMP, ignore_errors=True)


def co(code="1111", name="甲公司", ind="IND_A", yoy=60, cum=50, mom=5, pe=15, f=1_000_000, i=500_000, d=0, close=100.0, rev=1e8, **kw):
    return {"company_code": code, "company_name": name, "industry": ind, "official_industry": "電子業", "data_ym": "11510", "rev_cur": rev,
            "rev_mom": mom, "rev_yoy": yoy, "cum_yoy": cum, "pe": pe, "pb": 2.0, "dy": 3.0, "foreign": f, "itc": i, "dealer": d,
            "close": close, "insti_trade_date": "20261127", **kw}


# ---------------------------------------------------------------------------
class TestWatchlistRules(unittest.TestCase):
    def test_every_category_reachable(self):
        self.assertEqual(lw.categorize(co()), "優先研究")
        self.assertEqual(lw.categorize(co(f=-1_000_000, i=-500_000)), "中長期觀察")        # 法人賣超 → 不確認
        self.assertEqual(lw.categorize(co(mom=-3)), "中長期觀察")                          # 月增為負 → 不確認
        self.assertEqual(lw.categorize(co(pe=80)), "等待估值合理")
        self.assertEqual(lw.categorize(co(pe=None)), "等待估值合理")
        self.assertEqual(lw.categorize(co(pe=-5)), "等待估值合理")
        self.assertEqual(lw.categorize(co(yoy=-20, cum=-5)), "基本面或風險不佳")
        self.assertIsNone(lw.categorize(co(yoy=10, cum=5)))                                # 沒有強也沒有弱 → 不列入

    def test_single_month_decline_with_strong_cumulative_is_not_called_bad(self):
        """金控常見：單月年增 −60% 但累計 +28%，多半是一次性認列，不能被歸為基本面不佳 (實際遇過)。"""
        self.assertIsNone(lw.categorize(co(yoy=-60, cum=28)))
        self.assertEqual(lw.categorize(co(yoy=-60, cum=5)), "基本面或風險不佳")
        self.assertEqual(lw.categorize(co(yoy=40, cum=-1)), "基本面或風險不佳")

    def test_missing_growth_is_not_listed(self):
        self.assertIsNone(lw.categorize(co(yoy=None)))
        self.assertIsNone(lw.categorize(co(cum=None)))

    def test_text_is_built_from_numbers_and_has_no_handwritten_facts(self):
        e = lw.build_entry(co(yoy=487.7, cum=602.2, pe=6.0), "優先研究", "產業甲", 19.1, "2026-11-27")
        self.assertIn("+487.7%", e["bull_case"])
        self.assertIn("19.1", e["bull_case"])                                   # 與所屬產業中位數比較
        self.assertIn("機械式篩選", e["valuation_risk"])
        self.assertIn("沒有財報", e["valuation_risk"])
        self.assertIn("244%", e["invalidation_condition"])                      # 由目前數字推出的失效門檻
        self.assertEqual(e["eps_ttm_or_est"], lw.EPS_NOTE)
        for stale in ("CSP", "AI伺服器需要", "2.254%", "新青安"):
            self.assertNotIn(stale, " ".join(str(v) for v in e.values()))

    def test_one_off_gap_is_flagged_in_the_bear_case(self):
        e = lw.build_entry(co(yoy=-60, cum=28), "基本面或風險不佳", "產業甲", 19.1, "2026-11-27")
        self.assertIn("一次性", e["bear_case"])
        calm = lw.build_entry(co(yoy=30, cum=28), "中長期觀察", "產業甲", 19.1, "2026-11-27")
        self.assertNotIn("一次性", calm["bear_case"])

    def test_missing_values_do_not_crash_or_print_none(self):
        e = lw.build_entry(co(pe=None, close=None, f=None, i=None, mom=None), "等待估值合理", "產業甲", None, "2026-11-27")
        self.assertNotIn("None", " ".join(str(v) for v in e.values()))
        self.assertIn("沒有有效本益比", e["bear_case"])

    def test_select_limits_universe_and_per_category(self):
        companies = [co(code=f"{k:04d}", rev=1e8 - k, yoy=60 + k) for k in range(40)]                       # 全是優先研究
        companies += [co(code=f"9{k:03d}", rev=1.0, yoy=999) for k in range(5)]                          # 營收太小、不在前 N 大 (UNIVERSE_SIZE 內仍可入選)
        out = lw.select_watchlist(companies, {"IND_A": "產業甲"}, "2026-11-27")
        self.assertEqual(sum(1 for e in out if e["watchlist_category"] == "優先研究"), lw.PER_CATEGORY)
        top = [e for e in out if e["watchlist_category"] == "優先研究"]
        self.assertEqual([e["rev_yoy_pct"] for e in top], sorted([e["rev_yoy_pct"] for e in top], reverse=True))   # 營收年增高的在前

    def test_companies_without_price_are_excluded(self):
        out = lw.select_watchlist([co(close=None) for _ in range(5)], {"IND_A": "甲"}, "2026-11-27")
        self.assertEqual(out, [])


# ---------------------------------------------------------------------------
def flow(d, frg, itc, dealer=0.0):
    return {"date": d, "foreign": frg, "itc": itc, "dealer": dealer, "total": frg + itc + dealer}


def ind(i, score, inst, yoy=40.0, level="LEVEL 2", signal="基本面與資金同步居前"):
    return {"id": i, "name": i, "score": score, "level": level, "signal": signal, "state": "B",
            "metrics": {"inst_net_billion": inst, "yoy": yoy, "cum_yoy": yoy - 5, "rev_billion": 100, "rev_ly_billion": 70}}


def index_rows(name, pcts, start=100.0):
    out, close = [], start
    for k, p in enumerate(pcts):
        close *= 1 + p / 100.0
        out.append({"index_name": name, "trade_date": f"115112{k}", "close_index": close, "change_pct": p})
    return out


def ctx(**kw):
    from live_pulse import index_series
    base = {"flows": [flow("2026-11-23", -100, 10), flow("2026-11-24", -200, 20), flow("2026-11-25", -150, 30)],
            "idx": index_series(index_rows(lr.PRICE_INDEX, [1.0, 0.5, 0.5])),
            "inds": [ind("A", 80, -30.0), ind("B", 60, 5.0), ind("C", 30, 12.0, level="LEVEL R", signal="資金流向落後")],
            "daily_ind": [], "history": [], "picks": [], "revenue": {"label": "2026 年 10 月", "companies": 100, "total_trillion": 1.2, "yoy_pct": 10.0},
            "now": "2026-11-25T20:00:00+08:00"}
    base.update(kw)
    return base


class TestReports(unittest.TestCase):
    def test_daily_is_built_from_numbers(self):
        r = lr.build_daily(ctx())
        self.assertEqual(r["report_id"], "RPT_LIVE_DAILY_20261125")
        self.assertEqual(r["frequency"], "每日")
        self.assertIn("2026-11-25", r["report_title"])
        self.assertIn("-120.0", r["executive_summary"])                          # 當日合計 −150+30
        findings = {f["section"]: f["content"] for f in json.loads(r["key_findings_json"])}
        self.assertIn("近 3 個交易日合計 -390 億", findings["一、三大法人與大盤"])
        self.assertIn("LEVEL R", findings["三、預警等級分布"])
        self.assertIn("機械式規則", r["assumptions_and_limits"])
        for stale in ("費半", "0050", "842", "新青安"):
            self.assertNotIn(stale, json.dumps(r, ensure_ascii=False))

    def test_contradictions_detected_by_rules_and_honest_when_none(self):
        r = lr.build_daily(ctx())
        self.assertIn("反方證據：", r["counter_evidence"])
        self.assertIn("賣壓沒有壓倒買盤", r["counter_evidence"])                  # 法人賣超但大盤上漲
        self.assertIn("外資近 3 日全部賣超", r["counter_evidence"])
        self.assertIn("分數最高的 A", r["counter_evidence"])                      # 最高分產業法人淨賣
        calm = lr.build_daily(ctx(flows=[flow("2026-11-25", 50, 10)], inds=[ind("A", 80, 5.0), ind("C", 30, -5.0)]))
        self.assertIn("沒有偵測到明顯互相矛盾", calm["counter_evidence"])

    def test_no_flows_means_no_report(self):
        self.assertIsNone(lr.build_daily(ctx(flows=[])))
        self.assertIsNone(lr.build_weekly(ctx(flows=[])))
        self.assertIsNone(lr.build_monthly(ctx(flows=[])))

    def test_weekly_states_how_many_days_it_covers(self):
        r = lr.build_weekly(ctx())
        self.assertIn("W48", r["report_id"])
        self.assertIn("共 3 個交易日有資料", r["executive_summary"] + r["key_findings_json"])
        f = {x["section"]: x["content"] for x in json.loads(r["key_findings_json"])}
        self.assertIn("還沒有累積產業層級", f["二、產業累計法人買賣金額"])            # 沒有 live_industry_daily 時不編造
        self.assertIn("尚不足以比較評分變化", f["三、評分變化"])

    def test_weekly_uses_accumulated_industry_data_when_available(self):
        rows = [{"trade_date": "2026-11-24", "industry_id": "A", "foreign_billion": 10.0, "itc_billion": 2.0},
                {"trade_date": "2026-11-25", "industry_id": "A", "foreign_billion": 5.0, "itc_billion": 1.0},
                {"trade_date": "2026-11-25", "industry_id": "B", "foreign_billion": -20.0, "itc_billion": 0.0}]
        hist = [{"snapshot_date": "2026-11-24", "industry_id": "A", "total_weighted_score": 70.0},
                {"snapshot_date": "2026-11-25", "industry_id": "A", "total_weighted_score": 75.0}]
        f = {x["section"]: x["content"] for x in json.loads(lr.build_weekly(ctx(daily_ind=rows, history=hist))["key_findings_json"])}
        self.assertIn("僅累積 2 個交易日", f["二、產業累計法人買賣金額"])
        self.assertIn("+18.0", f["二、產業累計法人買賣金額"])                       # A: 12 + 6
        self.assertIn("-20.0", f["二、產業累計法人買賣金額"])
        self.assertIn("+5.0", f["三、評分變化"])

    def test_monthly_marks_partial_month(self):
        r = lr.build_monthly(ctx())
        self.assertEqual(r["report_id"], "RPT_LIVE_MONTHLY_202611")
        f = {x["section"]: x["content"] for x in json.loads(r["key_findings_json"])}
        self.assertIn("非整月", f["二、當月累計三大法人"])
        self.assertIn("2026 年 10 月", f["一、最新月營收與產業排名"])


def mrev(ym, iid, rev, ly, companies=100):
    return {"data_ym": ym, "industry_id": iid, "rev_thousand": rev, "rev_last_year_thousand": ly, "companies": companies}


class TestQuarterly(unittest.TestCase):
    def test_no_monthly_data_means_no_quarterly(self):
        self.assertIsNone(lr.build_quarterly(ctx()))
        self.assertIsNone(lr.build_quarterly(ctx(monthly_rev=[])))

    def test_partial_quarter_is_marked_accumulating(self):
        rows = [mrev("11510", "A", 200e6, 100e6), mrev("11510", "B", 100e6, 100e6)]
        r = lr.build_quarterly(ctx(monthly_rev=rows))
        self.assertEqual(r["report_id"], "RPT_LIVE_QUARTERLY_2026Q4")
        self.assertEqual(r["frequency"], "每季")
        self.assertIn("累積中 1/3 個月", r["report_title"])
        f = {x["section"]: x["content"] for x in json.loads(r["key_findings_json"])}
        self.assertIn("累積中（本季已有 1/3 個月營收：10 月）", f["一、本季產業營收"])
        self.assertIn("+100.0%", f["一、本季產業營收"])                         # A: 200 / 100 - 1
        self.assertIn("沒有上一季的完整三個月營收", f["二、與上一季比較"])
        self.assertIn("尚不足以比較評分變化", f["三、本季評分變化"])
        self.assertIn("尚未湊滿三個月", r["counter_evidence"])
        self.assertIn("沒有總體經濟", r["counter_evidence"])

    def test_months_with_few_companies_are_not_complete(self):
        rows = [mrev("11510", "A", 200e6, 100e6, 100), mrev("11511", "A", 5e6, 5e6, 20)]          # 11 月只有 20% 公司，視為尚未完整
        r = lr.build_quarterly(ctx(monthly_rev=rows))
        self.assertIn("累積中 1/3 個月", r["report_title"])
        self.assertIn("10 月", json.loads(r["key_findings_json"])[0]["content"])

    def test_full_quarter_with_previous_quarter_has_qoq(self):
        rows = []
        for ym, v in (("11507", 100e6), ("11508", 100e6), ("11509", 100e6), ("11510", 150e6), ("11511", 150e6), ("11512", 150e6)):
            rows.append(mrev(ym, "A", v, 100e6))
        r = lr.build_quarterly(ctx(monthly_rev=rows))
        self.assertIn("完整", r["report_title"])
        f = {x["section"]: x["content"] for x in json.loads(r["key_findings_json"])}
        self.assertIn("季增最高", f["二、與上一季比較"])
        self.assertIn("+50.0%", f["二、與上一季比較"])
        self.assertNotIn("尚未湊滿", r["counter_evidence"])

    def test_quarter_flow_and_scores_only_within_quarter(self):
        rows = [mrev("11510", "A", 200e6, 100e6)]
        daily = [{"trade_date": "2026-11-24", "industry_id": "A", "foreign_billion": 10.0, "itc_billion": 2.0},
                 {"trade_date": "2026-09-30", "industry_id": "A", "foreign_billion": 999.0, "itc_billion": 0.0}]         # 上一季，不可計入
        hist = [{"snapshot_date": "2026-11-24", "industry_id": "A", "total_weighted_score": 60.0},
                {"snapshot_date": "2026-11-25", "industry_id": "A", "total_weighted_score": 66.0}]
        f = {x["section"]: x["content"] for x in json.loads(lr.build_quarterly(ctx(monthly_rev=rows, daily_ind=daily, history=hist))["key_findings_json"])}
        self.assertIn("+12.0", f["四、本季產業法人資金累計"])
        self.assertNotIn("999", f["四、本季產業法人資金累計"])
        self.assertIn("+6.0", f["三、本季評分變化"])


class TestReportsDatabase(unittest.TestCase):
    def setUp(self):
        db.init_database()
        conn = db.get_connection()
        for t in ("research_reports", "institutional_flows", "live_company_fundamentals", "live_stock_quotes", "live_market_indices",
                  "industry_rotation_scores", "industry_score_history", "trend_early_warnings", "company_research_watchlist", "live_industry_daily", "industry_monthly_revenue"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        conn.close()
        seed_and_compute_all()
        from phase2_to_6_engine import populate_phase2_to_phase6      # 手寫的種子報告與三大法人紀錄在這裡灌入
        populate_phase2_to_phase6()

    def _flows(self, conn, dates):
        for k, d in enumerate(dates):
            conn.execute("""INSERT INTO institutional_flows (period_type, period_label, release_date, market_scope, foreign_net_billion,
                itc_net_billion, dealer_prop_billion, dealer_hedge_billion, total_3insti_billion, top_buy_industries, top_sell_industries,
                source_id, notes) VALUES ('DAILY', ?, ?, 'TWSE', ?, ?, 0, 0, ?, 'x', 'x', 'SRC_TWSE', 'n')""",
                         (f"{d} (TWSE BFI82U 官方API直連)", d, -100.0 - k, 10.0, -90.0 - k))
        conn.commit()

    def test_no_live_flows_keeps_handwritten_reports(self):
        conn = db.get_connection()
        before = conn.execute("SELECT COUNT(*) FROM research_reports WHERE text_source = 'seed'").fetchone()[0]
        self.assertGreater(before, 0)
        res = lr.apply_live_reports(conn)
        after = conn.execute("SELECT COUNT(*) FROM research_reports WHERE text_source = 'seed'").fetchone()[0]
        conn.close()
        self.assertFalse(res["applied"])
        self.assertEqual(before, after)

    def test_apply_replaces_seed_daily_weekly_monthly_but_keeps_quarterly(self):
        conn = db.get_connection()
        self._flows(conn, ["2026-11-23", "2026-11-24", "2026-11-25"])
        res = lr.apply_live_reports(conn)
        self.assertTrue(res["applied"])
        rows = {r["report_id"]: dict(r) for r in conn.execute("SELECT * FROM research_reports")}
        conn.close()
        self.assertEqual(set(res["reports"]) - set(rows), set())
        by_freq = {}
        for r in rows.values():
            by_freq.setdefault(r["frequency"], []).append(r["text_source"])
        self.assertEqual(set(by_freq["每日"]), {"live"})
        self.assertEqual(set(by_freq["每週"]), {"live"})
        self.assertEqual(set(by_freq["每月"]), {"live"})
        self.assertEqual(set(by_freq["每季"]), {"seed"})                          # 季報沒有即時來源，維持手寫

    def test_monthly_revenue_is_recorded_and_not_overwritten_by_partial_month(self):
        conn = db.get_connection()
        conn.execute("DELETE FROM industry_monthly_revenue")
        for k in range(10):
            conn.execute("""INSERT OR REPLACE INTO live_company_fundamentals (company_code, company_name, market_type, official_industry,
                mapped_industry_id, data_ym, report_date, rev_current_thousand, rev_last_year_thousand, fetched_at, source_url)
                VALUES (?, 'n', 'TWSE', 'x', 'IND_SEMI_FOUNDRY', '11510', '1151110', 100, 50, 't', 'u')""", (f"90{k:02d}",))
        conn.commit()
        self.assertGreater(lr.record_monthly_revenue(conn), 0)
        row = conn.execute("SELECT * FROM industry_monthly_revenue WHERE data_ym = '11510'").fetchone()
        self.assertEqual((row["companies"], row["rev_thousand"], row["rev_last_year_thousand"]), (10, 1000.0, 500.0))
        # 12 月初：其中 7 家已換成 11 月，剩 3 家仍是 10 月 → 10 月的紀錄不可被只剩 3 家的部分資料蓋掉
        for k in range(7):
            conn.execute("DELETE FROM live_company_fundamentals WHERE company_code = ?", (f"90{k:02d}",))
            conn.execute("""INSERT INTO live_company_fundamentals (company_code, company_name, market_type, official_industry, mapped_industry_id,
                data_ym, report_date, rev_current_thousand, rev_last_year_thousand, fetched_at, source_url)
                VALUES (?, 'n', 'TWSE', 'x', 'IND_SEMI_FOUNDRY', '11511', '1151210', 120, 60, 't', 'u')""", (f"90{k:02d}",))
        conn.commit()
        lr.record_monthly_revenue(conn)
        oct_row = conn.execute("SELECT * FROM industry_monthly_revenue WHERE data_ym = '11510' AND industry_id = 'IND_SEMI_FOUNDRY'").fetchone()
        nov_row = conn.execute("SELECT * FROM industry_monthly_revenue WHERE data_ym = '11511' AND industry_id = 'IND_SEMI_FOUNDRY'").fetchone()
        conn.close()
        self.assertEqual(oct_row["companies"], 10)                            # 沒被蓋掉
        self.assertEqual(nov_row["companies"], 7)

    def test_rerun_same_day_is_idempotent_and_old_reports_are_trimmed(self):
        conn = db.get_connection()
        dates = [f"2026-11-{d:02d}" for d in (2, 3, 4, 5, 6, 9, 10, 11, 12)]
        for k in range(len(dates)):
            conn.execute("DELETE FROM institutional_flows")
            self._flows(conn, dates[: k + 1])
            lr.apply_live_reports(conn)
        lr.apply_live_reports(conn)                                             # 同一天再跑一次
        daily = [r[0] for r in conn.execute("SELECT report_id FROM research_reports WHERE frequency = '每日' ORDER BY 1")]
        conn.close()
        self.assertEqual(len(daily), lr.KEEP["每日"])
        self.assertEqual(daily[-1], "RPT_LIVE_DAILY_20261112")


# ---------------------------------------------------------------------------
def inst_row(ptype, label, d, frg=-10.0, itc=5.0, **kw):
    return {"flow_record_id": 1, "period_type": ptype, "period_label": label, "release_date": d, "market_scope": "TWSE",
            "foreign_net_billion": frg, "itc_net_billion": itc, "dealer_prop_billion": 1.0, "dealer_hedge_billion": 2.0,
            "total_3insti_billion": frg + itc + 3.0, "foreign_futures_oi_contracts": None, "margin_balance_billion": None,
            "top_buy_industries": "x", "top_sell_industries": "x", "source_id": "S", "notes": "n", **kw}


class TestInstitutionalView(unittest.TestCase):
    def rows(self):
        return [inst_row("DAILY", "2026-11-19 手寫", "2026-11-19", -999.0),
                inst_row("DAILY", "2026-11-20 手寫", "2026-11-20", -842.6),                         # 與官方同日 → 矛盾，不顯示
                inst_row("DAILY", "2026-11-20 (TWSE BFI82U 官方API直連)", "2026-11-20", -95.1),
                inst_row("DAILY", "2026-11-23 (TWSE BFI82U 官方API直連)", "2026-11-23", -289.5),
                inst_row("WEEKLY", "2026-W47 手寫", "2026-11-20", -2069.1),                          # 結束日落在官方區間 → 重疊
                inst_row("WEEKLY", "2026-W45 手寫", "2026-11-06", -2145.0),
                inst_row("MONTHLY", "2026-11 手寫 (截至11/20)", "2026-11-20", -5494.6),
                inst_row("MONTHLY", "2026-10 手寫", "2026-10-30", -1685.2)]

    def test_overlapping_handwritten_rows_removed_and_history_kept_and_labelled(self):
        out = lv.institutional_view(self.rows(), [], {})
        labels = {(r["text_source"], r["period_type"], r["period_label"][:7]) for r in out}
        self.assertNotIn(-842.6, [r["foreign_net_billion"] for r in out])
        self.assertNotIn(-2069.1, [r["foreign_net_billion"] for r in out])
        self.assertNotIn(-5494.6, [r["foreign_net_billion"] for r in out])
        self.assertIn(("seed", "DAILY", "2026-11"), labels)                     # 11/19 早於第一筆官方資料，保留為手寫歷史
        self.assertIn(("seed", "WEEKLY", "2026-W4"), labels)
        self.assertIn(("seed", "MONTHLY", "2026-10"), labels)
        self.assertEqual([r["period_label"][:10] for r in out if r["text_source"] == "live"], ["2026-11-23", "2026-11-20"])   # 新到舊

    def test_weekly_and_monthly_are_sums_with_day_counts(self):
        out = lv.institutional_view(self.rows(), [], {})
        wk = [r for r in out if r["period_type"] == "WEEKLY" and r["text_source"] == "computed"]
        mo = [r for r in out if r["period_type"] == "MONTHLY" and r["text_source"] == "computed"]
        self.assertEqual(len(mo), 1)
        self.assertAlmostEqual(mo[0]["foreign_net_billion"], -95.1 - 289.5, places=2)
        self.assertIn("僅 2 個交易日", mo[0]["period_label"])
        self.assertIn("非整月", mo[0]["period_label"])
        self.assertEqual(len(wk), 2)                                            # 11/20 屬 W47、11/23 屬 W48
        self.assertTrue(all("不是官方" in r["notes"] for r in wk + mo))

    def test_industry_amounts_fill_top_buy_sell(self):
        daily = [{"trade_date": "2026-11-23", "industry_id": "A", "foreign_billion": 10.0, "itc_billion": 5.0},
                 {"trade_date": "2026-11-23", "industry_id": "B", "foreign_billion": -30.0, "itc_billion": 0.0}]
        out = lv.institutional_view(self.rows(), daily, {"A": "產業甲", "B": "產業乙"})
        d = next(r for r in out if r["text_source"] == "live" and r["release_date"] == "2026-11-23")
        self.assertIn("+15.0 億", d["top_buy_industries"])
        self.assertIn("-30.0 億", d["top_sell_industries"])
        old = next(r for r in out if r["text_source"] == "live" and r["release_date"] == "2026-11-20")
        self.assertEqual(old["top_buy_industries"], "x")                        # 沒有該日產業資料就不編造

    def test_without_live_rows_everything_is_marked_seed(self):
        out = lv.institutional_view([inst_row("DAILY", "手寫", "2026-11-19")], [], {})
        self.assertEqual([r["text_source"] for r in out], ["seed"])


class TestMacroAndReportLabels(unittest.TestCase):
    def test_taiex_replaced_by_live_close_others_untouched(self):
        macro = [{"metric_code": "TW_TAIEX_INDEX", "cleaned_value": 38650.0, "period_covered": "2026-11-20"},
                 {"metric_code": "TW_CPI_YOY", "cleaned_value": 2.33, "period_covered": "2026-10"}]
        rows = index_rows("發行量加權股價指數", [1.0, 0.4], start=39000.0)
        out = lv.macro_with_live_taiex(macro, rows)
        t = next(m for m in out if m["metric_code"] == "TW_TAIEX_INDEX")
        self.assertAlmostEqual(t["cleaned_value"], 39000.0 * 1.01 * 1.004, places=2)
        self.assertEqual(t["period_covered"], "2026-11-21")
        self.assertAlmostEqual(t["prev_value"], 39000.0 * 1.01, places=2)
        self.assertIsNone(t["yoy_pct"])                                         # 沒有年增就是沒有，不寫 0
        self.assertEqual(next(m for m in out if m["metric_code"] == "TW_CPI_YOY")["cleaned_value"], 2.33)
        self.assertEqual(lv.macro_with_live_taiex(macro, []), macro)            # 沒有指數資料時原樣回傳

    def test_handwritten_reports_lose_the_verified_label(self):
        out = lv.label_reports([{"report_id": "a", "update_status": "已驗證最新發布 (Verified Final)", "text_source": "seed"},
                                {"report_id": "b", "update_status": "即時產生", "text_source": "live"}])
        self.assertIn("不會自動更新", out[0]["update_status"])
        self.assertNotIn("已驗證", out[0]["update_status"])
        self.assertEqual(out[1]["update_status"], "即時產生")


class TestWatchlistDatabase(unittest.TestCase):
    def setUp(self):
        db.init_database()
        conn = db.get_connection()
        for t in ("company_research_watchlist", "live_company_fundamentals", "live_stock_quotes"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        conn.close()
        seed_and_compute_all()

    def _load(self, conn, n=30):
        for k in range(n):
            code = f"{1000 + k}"
            yoy = 80 if k % 3 == 0 else (-30 if k % 3 == 1 else 40)
            conn.execute("""INSERT INTO live_company_fundamentals
                (company_code, company_name, market_type, official_industry, mapped_industry_id, data_ym, report_date,
                 rev_current_thousand, rev_prev_month_thousand, rev_last_year_thousand, rev_mom_pct, rev_yoy_pct,
                 cum_rev_current_thousand, cum_rev_last_year_thousand, cum_rev_yoy_pct, pe_ratio, pb_ratio, dividend_yield,
                 foreign_net_shares, itc_net_shares, dealer_net_shares, total_3insti_net_shares, insti_trade_date,
                 fetched_at, source_url, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (code, f"公司{k}", "TWSE", "電子業", "IND_AI_SERVER", "11510", "1151110", 1e8 - k, 1e8, 5e7, 3, yoy, 1e9, 6e8,
                          yoy - 5, 15.0 + k, 2.0, 3.0, 100_000, 50_000, 0, 0, "20261127", "t", "u", ""))
            conn.execute("INSERT INTO live_stock_quotes VALUES (?,?,?,?,?,?,?)", (code, "2026-11-27", "TWSE", 100.0, 0.5, 1e9, "t"))
        conn.commit()

    def test_replaces_seed_list_and_is_idempotent(self):
        conn = db.get_connection()
        self.assertEqual(conn.execute("SELECT COUNT(DISTINCT text_source) FROM company_research_watchlist").fetchone()[0], 1)
        self._load(conn)
        res = lw.apply_live_watchlist(conn)
        self.assertTrue(res["applied"])
        rows = conn.execute("SELECT * FROM company_research_watchlist").fetchall()
        self.assertTrue(rows and all(r["text_source"] == "live" for r in rows))
        self.assertEqual(len({r["ticker"] for r in rows}), len(rows))
        self.assertTrue(all(r["watchlist_category"] in lw.CATEGORIES for r in rows))
        n = len(rows)
        lw.apply_live_watchlist(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM company_research_watchlist").fetchone()[0], n)
        conn.close()

    def test_too_few_matches_keeps_the_original_list(self):
        conn = db.get_connection()
        self._load(conn, n=3)
        before = conn.execute("SELECT COUNT(*) FROM company_research_watchlist").fetchone()[0]
        res = lw.apply_live_watchlist(conn)
        after = conn.execute("SELECT COUNT(*) FROM company_research_watchlist WHERE text_source = 'seed'").fetchone()[0]
        conn.close()
        self.assertFalse(res["applied"])
        self.assertEqual(before, after)

    def test_no_live_data_changes_nothing(self):
        conn = db.get_connection()
        self.assertFalse(lw.apply_live_watchlist(conn)["applied"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
