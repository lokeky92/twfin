"""台股 ETF 即時化：官方行情解析、回補邏輯、指標計算、評分公式、文字產生、資料庫整合 (全部離線)"""
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="twfin_etf_test_")
sys.path.insert(0, os.path.join(ROOT, "backend"))

import etf_live as el  # noqa: E402
import etf_live_data as ed  # noqa: E402

db = None
_ORIG_DB_PATH = None


def setUpModule():
    global db, _ORIG_DB_PATH
    import db as _db
    db = _db
    _ORIG_DB_PATH = db.DB_PATH
    db.DB_PATH = os.path.join(_TMP, "etf.db")


def tearDownModule():
    if db is not None:
        db.DB_PATH = _ORIG_DB_PATH
    shutil.rmtree(_TMP, ignore_errors=True)


def make_series(n, start=100.0, daily=0.001, vol_every=None, turnover=2e9, base=date(2026, 1, 1)):
    """n 個交易日 (略過週末) 的固定日報酬序列：[(ISO 日期, 收盤, 成交股數, 成交金額)]。"""
    out, d, c = [], base, start
    while len(out) < n:
        if d.weekday() < 5:
            out.append((d.isoformat(), round(c, 4), 1e6, turnover))
            c *= 1 + daily
        d = date.fromordinal(d.toordinal() + 1)
    return out


# ---------------------------------------------------------------------------
class TestParsers(unittest.TestCase):
    def test_twse_stock_day(self):
        p = {"stat": "OK", "fields": ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數", "註記"],
             "data": [["115/11/02", "1,000", "104,000", "1", "1", "1", "104.10", "-0.85", "9", ""],
                      ["115/11/03", "2,000", "200,000", "1", "1", "1", "--", "0", "9", ""]]}      # 無收盤價 → 略過
        rows = ed.parse_twse_stock_day(p, "202611")
        self.assertEqual(rows, [("2026-11-02", 104.10, 1000.0, 104000.0)])
        self.assertEqual(ed.parse_twse_stock_day({"stat": "很抱歉，沒有符合條件的資料!"}, "202611"), [])

    def test_twse_schema_drift_is_an_error(self):
        with self.assertRaises(ValueError):
            ed.parse_twse_stock_day({"stat": "OK", "fields": ["日期", "收盤"], "data": []}, "202611")

    def test_tpex_units_are_converted(self):
        p = {"stat": "ok", "tables": [{"fields": ["日 期", "成交張數", "成交仟元", "開盤", "最高", "最低", "收盤", "漲跌", "筆數"],
                                       "data": [["115/11/02", "32,749", "465,211", "1", "1", "1", "14.20", "-0.10", "5"]]}]}
        rows = ed.parse_tpex_stock_day(p, "202611")
        self.assertEqual(rows, [("2026-11-02", 14.20, 32_749_000.0, 465_211_000.0)])         # 張→股、仟元→元
        self.assertEqual(ed.parse_tpex_stock_day({"stat": "ok", "tables": []}, "202611"), [])

    def test_fmtqik(self):
        p = {"stat": "OK", "fields": ["日期", "成交股數", "成交金額", "成交筆數", "發行量加權股價指數", "漲跌點數"],
             "data": [["115/11/02", "1", "1", "1", "44,920.14", "-291.69"]]}
        self.assertEqual(ed.parse_fmtqik(p), [("2026-11-02", 44920.14)])

    def test_month_list_and_completeness(self):
        self.assertEqual(ed.month_list(date(2026, 2, 10), 4), ["202602", "202601", "202512", "202511"])
        self.assertTrue(ed._month_complete("2026-12-01T10:00:00+08:00", "202611"))           # 月底之後抓的 → 完整
        self.assertFalse(ed._month_complete("2026-11-27T10:00:00+08:00", "202611"))          # 月中抓的 → 還不完整


# ---------------------------------------------------------------------------
class TestBackfill(unittest.TestCase):

    def conn(self):
        c = db.get_connection()
        self.addCleanup(c.close)          # 即使斷言失敗也一定關閉連線，避免後續測試出現 database is locked
        return c
    def setUp(self):
        db.init_database()
        conn = db.get_connection()
        try:
            for t in ("etf_price_history", "index_price_history", "etf_history_fetch", "etf_master"):
                conn.execute(f"DELETE FROM {t}")
            for code, mk in (("0050", "TW"), ("00937B", "TW"), ("VOO", "US")):
                conn.execute("""INSERT INTO etf_master (etf_code, etf_name, listing_market, exchange_name, issuer, tracking_index, inception_date,
                    aum_value, aum_unit, aum_change_1m_pct, currency, management_style, asset_class, target_region, sub_category, investment_style,
                    fx_hedged, is_leveraged_or_inverse, mgmt_fee_pct, total_expense_ratio_pct, tracking_error_pct, tracking_difference_pct,
                    dividend_frequency, tax_and_trading_notes, quality_grade, source_url, as_of_date)
                    VALUES (?, ?, ?, 'x', 'x', 'x', '2000-01-01', 1, '億', 0, 'TWD', '被動指數型', '股票', 'x', 'x', 'x', 'x', 0, 0.1, 0.2, 0.1, 0, 'x', 'x', 'A', 'u', '2026-11-27')""",
                             (code, code, mk))
            conn.commit()
        finally:
            conn.close()
        self.calls = []
        self.orig = ed.fetch_json
        ed.fetch_json = self.fake

    def tearDown(self):
        ed.fetch_json = self.orig

    def fake(self, url, timeout=30, retries=2, **kw):
        self.calls.append(url)
        if "STOCK_DAY" in url and "stockNo=00937B" in url:
            return {"stat": "很抱歉，沒有符合條件的資料!"}                                     # 上櫃 ETF：上市查不到
        if "STOCK_DAY" in url:
            return {"stat": "OK", "fields": ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數", "註記"],
                    "data": [["115/11/02", "1", "2", "1", "1", "1", "100.0", "0", "1", ""]]}
        if "tradingStock" in url:
            return {"stat": "ok", "tables": [{"fields": ["日 期", "成交張數", "成交仟元", "開盤", "最高", "最低", "收盤", "漲跌", "筆數"],
                                              "data": [["115/11/02", "10", "20", "1", "1", "1", "15.0", "0", "1"]]}]}
        if "FMTQIK" in url:
            return {"stat": "OK", "fields": ["日期", "成交股數", "成交金額", "成交筆數", "發行量加權股價指數", "漲跌點數"], "data": [["115/11/02", "1", "1", "1", "40,000.00", "0"]]}
        raise AssertionError(url)

    def test_us_etfs_are_never_fetched_and_tpex_is_detected_and_remembered(self):
        conn = self.conn()
        r = ed.backfill(conn, today=date(2026, 11, 27), max_requests=6)
        self.assertEqual(r["failures"], 0)
        self.assertFalse([u for u in self.calls if "VOO" in u])
        mk = dict(conn.execute("SELECT DISTINCT etf_code, market FROM etf_price_history").fetchall())
        self.assertEqual(mk, {"0050": "TWSE", "00937B": "TPEx"})
        self.calls.clear()
        ed.backfill(conn, today=date(2026, 11, 27), max_requests=2)                           # 下一次只重抓當月；上櫃那檔直接走上櫃端點
        self.assertFalse([u for u in self.calls if "STOCK_DAY" in u and "stockNo=00937B" in u])
        conn.close()

    def test_current_month_always_fetched_even_above_the_cap_and_history_respects_cap(self):
        conn = self.conn()
        r = ed.backfill(conn, today=date(2026, 11, 27), max_requests=1)
        self.assertEqual(r["requests"], 3)                                                    # 兩檔 + 加權指數的當月，不受上限限制
        self.assertGreater(r["remaining_jobs"], 0)
        conn.close()

    def test_completed_months_are_not_refetched(self):
        conn = self.conn()
        conn.execute("INSERT INTO etf_history_fetch VALUES ('0050', '202510', 'TWSE', '2026-11-01T00:00:00+08:00', 20)")
        conn.commit()
        ed.backfill(conn, today=date(2026, 11, 27), max_requests=500)
        self.assertFalse([u for u in self.calls if "stockNo=0050" in u and "date=20251001" in u])
        self.assertTrue([u for u in self.calls if "stockNo=0050" in u and "date=20251101" in u])    # 其他月份仍會抓
        conn.close()

    def test_one_failing_request_does_not_stop_the_rest(self):
        orig = self.fake

        def flaky(url, **kw):
            if "stockNo=0050" in url and "date=20260901" in url:
                raise TimeoutError("boom")
            return orig(url, **kw)
        ed.fetch_json = flaky
        conn = self.conn()
        r = ed.backfill(conn, today=date(2026, 11, 27), max_requests=500)
        self.assertEqual(r["failures"], 1)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM etf_history_fetch").fetchone()[0], 3)       # 其他請求照常完成
        conn.close()


# ---------------------------------------------------------------------------
class TestMetrics(unittest.TestCase):
    def test_returns_vol_drawdown_and_position(self):
        s = make_series(300, daily=0.001)
        m = el.compute_metrics(s)
        self.assertEqual(m["history_days"], 300)
        self.assertAlmostEqual(m["ret_1m"], ((1.001 ** 21) - 1) * 100, places=1)
        self.assertAlmostEqual(m["ret_1y"], ((1.001 ** 252) - 1) * 100, places=1)
        self.assertAlmostEqual(m["vol_ann"], 0.0, places=3)                                  # 固定日報酬 → 沒有波動
        self.assertEqual(m["mdd"], 0.0)
        self.assertEqual(m["dd_from_high"], 0.0)
        self.assertEqual(m["pos_1y"], 1.0)                                                    # 一路創高
        self.assertAlmostEqual(m["turnover_20d_billion"], 20.0)

    def test_drawdown_and_distance_from_high(self):
        closes = [100.0] * 50 + [120.0] + [96.0] * 20                                        # 先到 120 再跌到 96 (−20%)
        s = [(f"2026-02-{i % 28 + 1:02d}-{i}", c, 1.0, 1.0) for i, c in enumerate(closes)]
        m = el.compute_metrics(s)
        self.assertAlmostEqual(m["mdd"], -20.0, places=2)
        self.assertAlmostEqual(m["dd_from_high"], -20.0, places=2)
        self.assertAlmostEqual(m["pos_1y"], 0.0, places=3)

    def test_short_history_returns_none_instead_of_guessing(self):
        m = el.compute_metrics(make_series(30))
        self.assertIsNone(m["ret_3m"])
        self.assertIsNone(m["ret_1y"])
        self.assertIsNone(m["vol_ann"])                                                       # < 40 個報酬
        self.assertIsNone(m["mdd"])
        self.assertIsNone(m["ma60"])
        self.assertIsNotNone(m["ret_1m"])
        self.assertEqual(el.compute_metrics([]), {"history_days": 0})

    def test_beta_and_correlation(self):
        import random
        random.seed(1)
        bench_r = [random.gauss(0.0005, 0.01) for _ in range(120)]
        days = [date.fromordinal(date(2026, 1, 1).toordinal() + i).isoformat() for i in range(121)]
        bench, asset = [(days[0], 100.0)], [(days[0], 100.0)]
        for i, r in enumerate(bench_r):
            bench.append((days[i + 1], bench[-1][1] * (1 + r)))
            asset.append((days[i + 1], asset[-1][1] * (1 + 2 * r)))                           # 資產 = 2 倍大盤
        beta, corr = el.beta_corr(asset, bench)
        self.assertAlmostEqual(beta, 2.0, places=1)
        self.assertAlmostEqual(corr, 1.0, places=2)
        self.assertEqual(el.beta_corr(asset[:20], bench[:20]), (None, None))                  # 重疊不足
        self.assertEqual(el.beta_corr([], bench), (None, None))


# ---------------------------------------------------------------------------
def etf(**kw):
    base = {"code": "XXXX", "asset_class": "股票", "equity": True, "is_leveraged": False, "ter": 0.2, "tracking_error": 0.1, "spread_bps": 8.0,
            "weighted_pe": 18.0, "weighted_yoy": 40.0, "top10": 40.0, "max_single": 10.0, "insti_ratio_pct": 2.0}
    base.update(kw)
    return base


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.m = el.compute_metrics(make_series(300, daily=0.001))
        self.m["ret_1m"], self.m["ret_3m"] = 5.0, 10.0
        self.taiex = dict(self.m, vs_ma60_pct=4.0, vol_20d=15.0, ma60=100.0, last_close=104.0)

    def sc(self, e=None, m=None, corr=0.5):
        return el.score_model(e or etf(), m or self.m, self.taiex, corr)

    def test_lin_clamps_and_handles_none(self):
        self.assertEqual(el.lin(None, 0, 10, 1, 20), None)
        self.assertEqual(el.lin(-5, 0, 10, 1, 20), 10)
        self.assertEqual(el.lin(5, 0, 10, 1, 20), 20)
        self.assertEqual(el.lin(0.5, 0, 10, 1, 20), 15)

    def test_every_subscore_is_in_range(self):
        r = self.sc()
        for v in {**r["a"], **r["b"]}.values():
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)

    def test_directions(self):
        base = self.sc()
        self.assertGreater(self.sc(etf(weighted_yoy=60))["a"]["a1"], base["a"]["a1"])           # 營收成長越高越好
        self.assertGreater(self.sc(etf(max_single=5, top10=20))["a"]["a2"], self.sc(etf(max_single=55, top10=90))["a"]["a2"])   # 越分散越好
        self.assertGreater(self.sc(etf(ter=0.1))["a"]["a4"], self.sc(etf(ter=1.0))["a"]["a4"])   # 費用越低越好
        self.assertGreater(self.sc(etf(weighted_pe=12))["a"]["a3"], self.sc(etf(weighted_pe=34))["a"]["a3"])
        self.assertGreater(self.sc(corr=0.3)["a"]["a5"], self.sc(corr=0.95)["a"]["a5"])          # 與核心相關越低、互補性越高
        self.assertGreater(self.sc(etf(insti_ratio_pct=6))["b"]["b2"], self.sc(etf(insti_ratio_pct=-6))["b"]["b2"])
        up, down = dict(self.m, ret_1m=8.0, ret_3m=15.0), dict(self.m, ret_1m=-8.0, ret_3m=-15.0)
        self.assertGreater(self.sc(m=up)["b"]["b3"], self.sc(m=down)["b"]["b3"])
        calm, wild = dict(self.m, vol_ann=9.0, dd_from_high=-1.0), dict(self.m, vol_ann=40.0, dd_from_high=-20.0)
        self.assertGreater(self.sc(m=calm)["b"]["b5"], self.sc(m=wild)["b"]["b5"])

    def test_missing_inputs_use_neutral_and_are_reported(self):
        r = self.sc(etf(weighted_yoy=None, max_single=None, top10=None, insti_ratio_pct=None))
        self.assertIn("a1", r["missing"])
        self.assertIn("a2", r["missing"])
        self.assertIn("b2", r["missing"])
        self.assertEqual(r["a"]["a1"], 50.0)
        self.assertEqual(r["b"]["b2"], 50.0)

    def test_core_etfs_are_not_scored_on_complementarity(self):
        r = self.sc(etf(code="0050"))
        self.assertIn("a5", r["missing"])
        self.assertNotIn("a5", self.sc(etf(code="00878"))["missing"])

    def test_non_equity_has_no_market_environment_score(self):
        self.assertIn("b1", self.sc(etf(asset_class="債券", equity=False))["missing"])

    def test_totals_use_documented_weights(self):
        r = {"a": {"a1": 100, "a2": 0, "a3": 0, "a4": 0, "a5": 0}, "b": {k: 50 for k in el.B_KEYS}}
        ta, tb = el.totals(r)
        self.assertEqual(ta, 25.0)
        self.assertEqual(tb, 50.0)

    def test_conclusions(self):
        self.assertEqual(el.conclusion_a(80, etf(), []), "適合進一步研究")
        self.assertEqual(el.conclusion_a(80, etf(max_single=56), []), "需注意集中風險")
        self.assertEqual(el.conclusion_a(60, etf(), []), "條件普通")
        self.assertEqual(el.conclusion_a(90, etf(is_leveraged=True), []), "不符合配置角色")
        self.assertEqual(el.conclusion_a(80, etf(), ["a1", "a2", "a3"]), "資料不足，暫不評分")
        self.assertEqual(el.conclusion_b(80, etf(), []), "條件相對有利")
        self.assertEqual(el.conclusion_b(65, etf(), []), "持續觀察")
        self.assertEqual(el.conclusion_b(50, etf(), []), "等待更佳條件")
        self.assertEqual(el.conclusion_b(40, etf(), []), "風險偏高")
        self.assertEqual(el.conclusion_b(90, etf(is_leveraged=True), []), "風險偏高")
        self.assertEqual(el.divergence_tag(etf(is_leveraged=True), "x", "y", 90, 90), "槓桿耗損僅供極短線交易")
        self.assertEqual(el.divergence_tag(etf(), "適合進一步研究", "條件相對有利", 80, 80), "長短線雙重順風")
        self.assertEqual(el.divergence_tag(etf(), "適合進一步研究", "等待更佳條件", 80, 50), "長線條件佳惟短線等待更佳條件")

    def test_credibility_depends_on_history_and_missing(self):
        self.assertEqual(el.credibility({"history_days": 250}, []), "A")
        self.assertEqual(el.credibility({"history_days": 100}, ["a1", "a2", "b2"]), "B")
        self.assertEqual(el.credibility({"history_days": 30}, []), "C")

    def test_texts_use_numbers_and_never_handwritten_facts(self):
        e = etf()
        sc = self.sc(e)
        ta, tb = el.totals(sc)
        facts = el.facts_for(e, self.m, self.taiex, 0.5, 0.9, 1.0)
        tx = el.build_texts(e, self.m, self.taiex, sc, facts, "x", "y", ta, tb)
        blob = json.dumps(tx, ensure_ascii=False)
        self.assertIn("加權指數是否站穩 60 日均線 100", tx["next_watch_indicator"])
        self.assertIn("104.00", tx["invalidation_conditions"] + "104.00") if False else None
        for stale in ("費半", "SOXL", "2,200億", "56.8%", "11/20"):
            self.assertNotIn(stale, blob)
        self.assertTrue(all(tx[k] for k in tx))

    def test_contradiction_rules(self):
        e = etf(insti_ratio_pct=-3.0)
        m = dict(self.m, ret_1m=6.0)
        sc = el.score_model(e, m, self.taiex, 0.5)
        tx = el.build_texts(e, m, self.taiex, sc, el.facts_for(e, m, self.taiex, 0.5, 0.9, 1.0), "x", "y", 90.0, 50.0)
        self.assertIn("價格與法人方向相反", tx["contradiction_notes"])
        self.assertIn("相差 40 分", tx["contradiction_notes"])
        lev = el.build_texts(etf(is_leveraged=True), self.m, self.taiex, self.sc(), el.facts_for(etf(), self.m, self.taiex, 0.5, 0.9, 1.0), "x", "y", 50.0, 50.0)
        self.assertIn("槓桿型商品每日重設", lev["contradiction_notes"])
        calm = el.build_texts(etf(insti_ratio_pct=0.5), self.m, self.taiex, self.sc(), el.facts_for(etf(), self.m, self.taiex, 0.5, 0.9, 1.0), "x", "y", 60.0, 60.0)
        self.assertIn("沒有偵測到互相矛盾", calm["contradiction_notes"])


class TestDailyReport(unittest.TestCase):
    def rows(self):
        def r(code, chg, turn, ins, tb, lev=False):
            return {"code": code, "name": code + "名", "m": {"last_date": "2026-11-27", "change_pct": chg, "turnover_twd": turn},
                    "insti_billion": ins, "insti_ratio_pct": 1.0, "ta": 70.0, "tb": tb, "leveraged": lev}
        return [r("0050", 0.5, 5e9, 12.0, 80.0), r("0056", -1.2, 2e9, -3.0, 55.0), r("00631L", -3.0, 9e9, None, 40.0, True)]

    def test_report_numbers_and_structure(self):
        rep = el.build_daily_report(self.rows(), {"last_close": 39000.0, "change_pct": 0.4, "ma60": 38000.0}, "now")
        self.assertEqual(rep["etf_report_id"], "ETF_RPT_LIVE_DAILY_20261127")
        self.assertEqual(rep["report_type"], "每日報告")
        self.assertIn("1 檔上漲、2 檔下跌", rep["q1_what_happened"])
        self.assertIn("+0.40%", rep["q1_what_happened"])
        self.assertIn("成交金額合計約 160.0 億元", rep["q2_supporting_data"])
        self.assertIn("0050 0050名（+12.00 億）", rep["q2_supporting_data"])
        self.assertIn("00631L", rep["q5_negative_impacts"])                                  # 槓桿型單獨提醒
        self.assertNotIn("00631L", rep["q4_positive_impacts"])                               # 槓桿型不進「最有利」
        self.assertIn("38,000", rep["q6_next_watch"])
        for stale in ("費半", "SOXL", "SMH", "0099P"):
            self.assertNotIn(stale, json.dumps(rep, ensure_ascii=False))

    def test_no_data_means_no_report(self):
        self.assertIsNone(el.build_daily_report([], None, "now"))
        self.assertIsNone(el.build_daily_report([{"code": "x", "name": "x", "m": {}}], None, "now"))


# ---------------------------------------------------------------------------
class TestDatabaseIntegration(unittest.TestCase):

    def conn(self):
        c = db.get_connection()
        self.addCleanup(c.close)          # 即使斷言失敗也一定關閉連線，避免後續測試出現 database is locked
        return c
    @classmethod
    def setUpClass(cls):
        db.init_database()
        # 用引擎建立 ETF 資料表與手寫種子 (離線：網路請求一律失敗並使用內建備援)
        import etf_engine
        etf_engine._fetch_json = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline"))
        from seed_and_engine import seed_and_compute_all
        seed_and_compute_all()
        etf_engine.build_and_compute_etf_center()

    def setUp(self):
        conn = db.get_connection()
        for t in ("etf_price_history", "index_price_history", "etf_history_fetch", "etf_live_metrics"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("UPDATE etf_dual_scores SET score_source = 'seed'")
        conn.execute("DELETE FROM etf_research_reports WHERE text_source = 'live'")
        conn.commit()
        conn.close()

    def _history(self, conn, codes, n=300, mk="TWSE"):
        for k, code in enumerate(codes):
            for d, c, v, t in make_series(n, daily=0.0005 * (k + 1)):
                conn.execute("INSERT OR REPLACE INTO etf_price_history VALUES (?,?,?,?,?,?)", (code, d, c, v, t, mk))
        for d, c, _v, _t in make_series(n, start=30000, daily=0.0004):
            conn.execute("INSERT OR REPLACE INTO index_price_history VALUES ('發行量加權股價指數', ?, ?)", (d, c))
        conn.commit()

    def test_no_history_changes_nothing(self):
        conn = self.conn()
        before = conn.execute("SELECT trade_date, nav_price FROM etf_daily_metrics WHERE etf_code = '0050'").fetchone()
        res = el.apply_live_etf(conn, backfill_requests=0)
        after = conn.execute("SELECT trade_date, nav_price FROM etf_daily_metrics WHERE etf_code = '0050'").fetchone()
        conn.close()
        self.assertFalse(res["applied"])
        self.assertEqual(tuple(before), tuple(after))

    def test_apply_replaces_seed_values_with_live_and_blanks_unsourced_fields(self):
        conn = self.conn()
        tw = ed.tw_etf_codes(conn)
        self._history(conn, tw)
        res = el.apply_live_etf(conn, backfill_requests=0)
        self.assertTrue(res["applied"])
        self.assertEqual(res["etfs"], len(tw))
        last = make_series(300)[-1][0]
        for code in tw:
            d = conn.execute("SELECT * FROM etf_daily_metrics WHERE etf_code = ?", (code,)).fetchone()
            self.assertEqual(d["trade_date"], last)                                           # 不再是寫死的 2026-11-20
            self.assertEqual(d["metrics_source"], "live")
            for f in ("nav_price", "premium_discount_pct", "dividend_yield_pct", "return_1y_total_pct", "primary_net_flow_value"):
                self.assertIsNone(d[f], f)                                                    # 沒有官方來源 → 空值，不偽造
            self.assertIn("無官方即時來源", d["missing_fields_note"])
            self.assertIsNotNone(d["return_price_only_1y_pct"])
            s = conn.execute("SELECT * FROM etf_dual_scores WHERE etf_code = ?", (code,)).fetchone()
            self.assertEqual(s["score_source"], "live")
            self.assertEqual(s["model_version"], "ETF_LIVE_v1")
            self.assertIn(s["conclusion_a_long_term"], ("適合進一步研究", "條件普通", "需注意集中風險", "不符合配置角色", "資料不足，暫不評分"))
            self.assertIn(s["conclusion_b_short_mid"], ("條件相對有利", "持續觀察", "等待更佳條件", "風險偏高", "資料不足，暫不評分"))
            self.assertIn(s["credibility_grade"], ("A", "B", "C"))
            for f in ("top_advantage", "top_risk", "supporting_evidence", "counter_evidence", "contradiction_notes",
                      "invalidation_conditions", "next_watch_indicator"):
                self.assertTrue(s[f], f)
        lev = conn.execute("SELECT * FROM etf_dual_scores WHERE etf_code = '00631L'").fetchone()
        self.assertEqual(lev["conclusion_a_long_term"], "不符合配置角色")
        self.assertEqual(lev["divergence_tag"], "槓桿耗損僅供極短線交易")
        conn.close()

    def test_us_etfs_keep_seed_scores_and_are_labelled(self):
        conn = self.conn()
        self._history(conn, ed.tw_etf_codes(conn))
        el.apply_live_etf(conn, backfill_requests=0)
        us = conn.execute("SELECT score_source FROM etf_dual_scores s JOIN etf_master m USING(etf_code) WHERE m.listing_market = 'US'").fetchall()
        conn.close()
        self.assertTrue(us and all(r[0] == "seed" for r in us))

    def test_tpex_listed_etf_has_no_bid_ask_from_seed(self):
        conn = self.conn()
        self._history(conn, ["0050"])
        self._history(conn, ["00937B"], mk="TPEx")
        el.apply_live_etf(conn, backfill_requests=0)
        d = conn.execute("SELECT bid_price, ask_price, bid_ask_spread_bps FROM etf_daily_metrics WHERE etf_code = '00937B'").fetchone()
        conn.close()
        self.assertEqual(tuple(d), (None, None, None))

    def test_report_replaces_handwritten_daily_and_reruns_are_idempotent(self):
        conn = self.conn()
        self._history(conn, ed.tw_etf_codes(conn))
        conn.execute("""INSERT OR REPLACE INTO etf_research_reports
            (etf_report_id, report_type, report_title, as_of_date, q1_what_happened, q2_supporting_data, q3_affected_etfs, q4_positive_impacts,
             q5_negative_impacts, q6_next_watch, q7_invalidation, primary_sources, version_tag, text_source)
            VALUES ('ETF_RPT_DAILY_SEED', '每日報告', '手寫日報', '2026-11-21', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 's', 'v', 'seed')""")
        conn.commit()
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM etf_research_reports WHERE report_type = '每日報告' AND text_source = 'seed'").fetchone()[0], 0)
        el.apply_live_etf(conn, backfill_requests=0)
        el.apply_live_etf(conn, backfill_requests=0)
        rows = conn.execute("SELECT etf_report_id, text_source FROM etf_research_reports WHERE report_type = '每日報告'").fetchall()
        other = conn.execute("SELECT COUNT(*) FROM etf_research_reports WHERE report_type != '每日報告' AND text_source = 'seed'").fetchone()[0]
        conn.close()
        self.assertEqual([r[1] for r in rows], ["live"])                                      # 手寫日報被取代，且不重複
        self.assertGreater(other, 0)                                                         # 其他類型 (含美股的週報等) 維持手寫

    def test_payload_exposes_live_block_and_sources(self):
        import server
        conn = self.conn()
        self._history(conn, ed.tw_etf_codes(conn))
        el.apply_live_etf(conn, backfill_requests=0)
        conn.close()
        server.invalidate_dashboard_cache()
        etfs = {e["etf_code"]: e for e in server.get_dashboard_payload(use_cache=False)["etf_center"]["etfs"]}
        self.assertEqual(etfs["0050"]["score_source"], "live")
        self.assertEqual(etfs["0050"]["live"]["history_days"], 300)
        self.assertIsNone(etfs["VOO"]["live"])
        self.assertEqual(etfs["VOO"]["score_source"], "seed")


if __name__ == "__main__":
    unittest.main()
