"""首頁 Q1~Q6 即時摘要：日期解析、資料過濾、規則分支、HTML 跳脫、缺資料降級 (純函式，不連資料庫與外網)"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import live_pulse as lp  # noqa: E402


def flow(date, frg, itc, total, label="官方API直連", ptype="DAILY"):
    return {"period_type": ptype, "period_label": f"{date} (TWSE BFI82U {label})", "release_date": date,
            "foreign_net_billion": frg, "itc_net_billion": itc, "total_3insti_billion": total,
            "foreign_futures_oi_contracts": None, "margin_balance_billion": None}


def ind(iid, yoy, frg, itc, n=10, score=70.0):
    return {"industry_id": iid, "industry_name": iid, "total_weighted_score": score, "as_of_date": "2026-11-21",
            "live_agg": {"company_count": n, "agg_yoy_pct": yoy, "sum_foreign_shares": frg, "sum_itc_shares": itc, "avg_pe": 20}}


def idx(name, rows):
    return [{"index_name": name, "trade_date": d, "close_index": c, "change_pct": p} for d, c, p in rows]


def comp(code, name, yoy=80, cum=50, mom=5, pe=20, net=1000, ind_id="IND_X"):
    return {"company_code": code, "company_name": name, "mapped_industry_id": ind_id, "data_ym": "11510",
            "rev_yoy_pct": yoy, "cum_rev_yoy_pct": cum, "rev_mom_pct": mom, "pe_ratio": pe,
            "total_3insti_net_shares": net, "insti_trade_date": "20261127"}


class TestHelpers(unittest.TestCase):
    def test_to_iso_date_formats(self):
        self.assertEqual(lp.to_iso_date("1151126"), "2026-11-26")
        self.assertEqual(lp.to_iso_date("20261126"), "2026-11-26")
        self.assertEqual(lp.to_iso_date("2026-11-26"), "2026-11-26")
        self.assertIsNone(lp.to_iso_date(None))
        self.assertIsNone(lp.to_iso_date("abc"))

    def test_ym_label(self):
        self.assertEqual(lp._ym_label("11510"), "2026年10月")
        self.assertEqual(lp._ym_label(None), "最新月")

    def test_pct_rank_ties_and_edges(self):
        self.assertEqual(lp._pct_rank([]), [])
        self.assertEqual(lp._pct_rank([5]), [0.5])
        self.assertEqual(lp._pct_rank([1, 2, 3]), [0.0, 0.5, 1.0])
        self.assertEqual(lp._pct_rank([1, 1, 3]), [0.25, 0.25, 1.0])

    def test_html_is_escaped(self):
        self.assertEqual(lp._e("A&B <script>"), "A&amp;B &lt;script&gt;")

    def test_fmt_drops_float_tail(self):
        self.assertEqual(lp._fmt(68.5398), "68.54")
        self.assertEqual(lp._fmt(103.97), "103.97")


class TestDataSelection(unittest.TestCase):
    def test_flows_only_official_rows_deduped_sorted(self):
        rows = [flow("2026-11-24", -1, 2, -3), flow("2026-11-23", 1, 1, 2),
                flow("2026-11-23", 9, 9, 99),   # 同一天重複 → 只留一筆
                flow("2026-11-20", -842.6, 168.9, -900.6, label="手寫種子"),   # 種子列不採用
                flow("2026-11-25", 1, 1, 2, ptype="WEEKLY")]
        out = lp.live_daily_flows(rows)
        self.assertEqual([r["date"] for r in out], ["2026-11-23", "2026-11-24"])
        self.assertAlmostEqual(out[1]["dealer"], -3 - (-1) - 2)

    def test_flows_skip_incomplete_rows(self):
        self.assertEqual(lp.live_daily_flows([flow("2026-11-24", None, 2, -3)]), [])

    def test_manual_stats_report_their_own_date(self):
        rows = [dict(flow("2026-11-20", 0, 0, 0), margin_balance_billion=8300.0),
                dict(flow("2026-11-24", 0, 0, 0), margin_balance_billion=8343.0, foreign_futures_oi_contracts=-98650),
                flow("2026-11-27", 0, 0, 0)]   # 最新一天沒有人工欄位 → 不可被當成最新值
        m = lp.manual_market_stats(rows)
        self.assertEqual(m["margin_balance_billion"], ("2026-11-24", 8343.0))
        self.assertEqual(m["foreign_futures_oi_contracts"], ("2026-11-24", -98650))

    def test_window_return_includes_first_day_change(self):
        # 前收 100 → 11-20 跌 10% 收 90 → 11-21 漲 10% 收 99；窗內累計應為 -1%
        s = lp.index_series(idx("X", [("1151120", 90.0, -10.0), ("1151121", 99.0, 10.0)]))["X"]
        r = lp.window_return(s, 5)
        self.assertAlmostEqual(r["pct"], -1.0, places=6)
        self.assertEqual((r["from"], r["to"], r["days"]), ("2026-11-20", "2026-11-21", 2))

    def test_window_return_without_change_pct_uses_closes(self):
        s = lp.index_series(idx("X", [("1151120", 100.0, None), ("1151121", 110.0, None)]))["X"]
        r = lp.window_return(s, 5)
        self.assertAlmostEqual(r["pct"], 10.0)
        self.assertEqual(r["days"], 1)
        self.assertIsNone(lp.window_return([], 5))

    def test_industry_table_ranking_and_exclusions(self):
        inds = [ind("A", 80, 500_000, 500_000), ind("B", 10, -500_000, -500_000), ind("C", 40, 0, 0),
                ind("TINY", 999, 9e9, 9e9, n=1),             # 公司數不足 → 不排名
                dict(ind("NOAGG", 0, 0, 0), live_agg=None)]  # 沒有即時彙總 → 不排名
        table = lp.industry_live_table(inds)
        self.assertEqual([r["id"] for r in table], ["A", "C", "B"])
        self.assertEqual(table[0]["heat"], 100.0)
        self.assertEqual(table[-1]["heat"], 0.0)


class TestCards(unittest.TestCase):
    def pulse(self, **kw):
        base = {"institutional_flows": [], "live_indices": [], "industries": [], "live_top_companies": [],
                "live_summary": {"total_companies": 100, "total_rev_trillion": 1.2, "total_yoy_pct": 10.0}, "macro_latest": []}
        base.update(kw)
        return lp.compute_home_pulse(base)

    def test_no_live_data_degrades_every_card(self):
        p = self.pulse()
        self.assertEqual(len(p["items"]), 6)
        for it in p["items"]:
            self.assertIn("資料不足", it["a"])
            self.assertEqual(len(it["q6"]), 6)
        self.assertIsNone(p["flows_through"])

    def test_q1_three_branches(self):
        def q1(rows):
            return self.pulse(institutional_flows=rows)["items"][0]["a"]
        self.assertIn("淨買超", q1([flow("2026-11-24", 100, 50, 160)]))
        self.assertIn("外資賣超、投信買超", q1([flow("2026-11-24", -300, 50, -250)]))
        self.assertIn("同步賣超", q1([flow("2026-11-24", -300, -50, -350)]))

    def test_q1_uses_only_last_five_days(self):
        rows = [flow(f"2026-11-{d:02d}", 0, 0, -1000) for d in range(10, 16)] + \
               [flow(f"2026-11-{d:02d}", 10, 10, 20) for d in range(16, 21)]
        it = self.pulse(institutional_flows=rows)["items"][0]
        self.assertIn("淨買超", it["a"])   # 早期的大額賣超不在窗內
        self.assertIn("近 5 日合計 +100 億", it["sub"])

    def test_q6_triggers(self):
        calm = self.pulse(institutional_flows=[flow("2026-11-24", 10, 5, 15)],
                          live_indices=idx(lp.MARKET_INDEX, [("1151123", 100, 0.5), ("1151124", 101, 1.0)]))
        self.assertIn("平靜", calm["items"][5]["a"])
        hot = self.pulse(institutional_flows=[flow("2026-11-24", -1500, 5, -1495)],
                         live_indices=idx(lp.MARKET_INDEX, [("1151123", 100, -1.0), ("1151124", 90, -10.0)]))
        a = hot["items"][5]["a"]
        self.assertIn("外資提款", a)
        self.assertIn("大盤回檔", a)
        self.assertIn("單日急跌", a)

    def test_q6_manual_context_is_labelled_and_dated(self):
        rows = [dict(flow("2026-11-24", 0, 0, 0), margin_balance_billion=8343.0)]
        it = self.pulse(institutional_flows=rows, live_indices=idx(lp.MARKET_INDEX, [("1151124", 100, 0.1)]))["items"][5]
        self.assertIn("人工維護，截至 11-24", it["q6"][2])

    def test_q3_q4_use_live_ranking_and_escape_names(self):
        inds = [ind("IND_A", 90, 9e5, 9e5), ind("IND_B", 50, 0, 0), ind("IND_C", 20, -1e5, -1e5), ind("IND_D", -30, -9e5, -9e5)]
        inds[0]["industry_name"] = "<b>A</b>"
        p = self.pulse(industries=inds, live_top_companies=[comp("1", "x")])
        self.assertIn("IND_D", p["items"][3]["a"])   # 熱度最低者出現在降溫
        self.assertNotIn("<b>", "".join(it["a"] + it["sub"] + "".join(it["q6"]) for it in p["items"]))

    def test_q3_hot_industry_leads_card(self):
        inds = [ind("IND_X1", 90, 9e5, 9e5), ind("IND_X2", 50, 0, 0), ind("IND_X3", 20, -1e5, -1e5), ind("IND_X4", -30, -9e5, -9e5)]
        p = self.pulse(industries=inds, live_top_companies=[comp("1", "x")])
        self.assertTrue(p["items"][2]["a"].startswith("🔥 IND_X1"))

    def test_q5_filters_and_escapes(self):
        comps = [comp("1111", "高成長&甲", yoy=120), comp("2222", "估值過高", pe=80), comp("3333", "營收月減", mom=-1),
                 comp("4444", "法人賣超", net=-5), comp("5555", "年增不足", yoy=10), comp("6666", "累計不足", cum=5),
                 comp("7777", "本益比缺值", pe=None)]
        it = self.pulse(live_top_companies=comps)["items"][4]
        self.assertIn("高成長&amp;甲", it["a"])
        for bad in ("估值過高", "營收月減", "法人賣超", "年增不足", "累計不足", "本益比缺值"):
            self.assertNotIn(bad, it["q6"][0])

    def test_q5_empty_result_is_explicit(self):
        it = self.pulse(live_top_companies=[comp("1", "x", yoy=1)])["items"][4]
        self.assertIn("沒有同時符合條件", it["a"])

    def test_single_card_failure_does_not_break_page(self):
        # live_top_companies 內含壞資料 (字串) 觸發例外 → 只有該卡降級，其餘照常
        p = self.pulse(institutional_flows=[flow("2026-11-24", 1, 1, 2)], live_top_companies=["not-a-dict"])
        self.assertEqual(len(p["items"]), 6)
        self.assertIn("淨買超", p["items"][0]["a"])
        self.assertIn("資料不足", p["items"][4]["a"])


if __name__ == "__main__":
    unittest.main()
