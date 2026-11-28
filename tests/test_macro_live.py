"""總體月統計即時化：央行／國發會／財政部／FRED 解析、列組成、取代手寫列的規則、失敗時保留既有資料 (全部離線)"""
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import macro_live as ml  # noqa: E402

EF01 = {"meta": {"last_updated": "2026-10-28"},
        "data": {"structure": {"Table1": [{"data": "準備貨幣"}, {"data": "貨幣總計數-M1B"}, {"data": "貨幣總計數-M2"}],
                               "Table2": [{"data": "日平均"}, {"data": "期底"}], "Table3": [{"data": "金額"}, {"data": "年增率"}]},
                 "dataSets": [["2026M07", "1", "1.0", "1", "1.0", "300", "6.85", "300", "6.9", "700", "7.0", "700", "7.1"],
                              ["2026M08", "1", "1.0", "1", "1.0", "301", "7.02", "301", "7.0", "710", "7.1", "710", "7.2"],
                              ["2026M09", "1", "1.0", "1", "1.0", "310", "7.20", "310", "7.2", "713", "7.24", "712", "7.54"],
                              ["2026M10", "1", "-", "1", "-", "310", "-", "310", "-", "713", "-", "712", "-"]]}}
EF07 = {"meta": {"last_updated": "2026-10-28"},
        "data": {"structure": {"Table1": [{"data": "股票市場股價指數"}, {"data": "外匯存底(百萬美元)"}, {"data": "消費者物價指數年增率"}]},
                 "dataSets": [["2025M09", "40000", "500000", "1.80"], ["2026M08", "45000", "601904", "2.05"], ["2026M09", "46000", "600745", "2.73"]]}}
EF03 = {"meta": {"last_updated": "2026-10-28"},
        "data": {"structure": {"Table1": [{"data": "貨幣機構存款-合計"}, {"data": "貨幣機構存款-企業及個人存款-外匯存款"}],
                               "Table2": [{"data": "期底餘額"}, {"data": "年增率"}]},
                 "dataSets": [["2025M09", "650000", "7.0", "90000", "5.0"], ["2026M08", "700000", "8.0", "96488", "10.0"], ["2026M09", "707139", "8.42", "100591", "11.8"]]}}
EFA4 = {"meta": {"last_updated": "2026-10-28"},
        "data": {"structure": {"Table1": [{"data": "貨幣機構放款與投資(性質別)-合計"}, {"data": "貨幣機構放款與投資(性質別)-放款"}],
                               "Table2": [{"data": "期底餘額"}, {"data": "年增率"}]},
                 "dataSets": [["2026M08", "570000", "9.02", "470000", "8.0"], ["2026M09", "578592", "9.79", "481550", "9.1"]]}}
EH45 = {"meta": {"last_updated": "2026-10-28"},
        "data": {"structure": {"Table1": [{"data": "購屋貸款"}, {"data": "合計"}], "Table2": [{"data": "金額"}, {"data": "利率"}]},
                 "dataSets": [["2026M08", "57165", "2.31", "80000", "2.2"], ["2026M09", "69783", "2.315", "90874", "2.2"]]}}
BP01 = {"meta": {"last_updated": "2026-11-02"},
        "data": {"structure": {"Table1": [{"data": "新台幣NTD/USD"}, {"data": "日圓JPY/USD"}]},
                 "dataSets": [["20251030", "30.500", "150"], ["20261029", "32.492", "157"], ["20261030", "32.478", "157"]]}}


def ndc_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.csv", "name,schema\n景氣指標與燈號.csv,x\n")
        z.writestr("schema-景氣指標與燈號.csv", "name,title\nDate,Date\n")
        z.writestr("景氣指標與燈號.csv".encode("utf-8").decode("cp437"),
                   '"Date","領先指標綜合指數","景氣對策信號綜合分數","景氣對策信號"\n202608,1,40,紅\n202609,1,41,紅\n202610,1,40,紅\n198201,1,-,-\n'.encode("utf-8"))
        z.writestr("落後指標構成項目.csv".encode("utf-8").decode("cp437"),
                   '"Date","失業率(%)","五大銀行新承做放款平均利率(年息百分比)"\n202609,3.36,2.193\n202610,3.35,2.254\n'.encode("utf-8"))
    return buf.getvalue()


MOF_CSV = ('﻿"幣別","按美元計算/ 貿易總值","按美元計算/ 出口總值","按美元計算/ 進口總值","按美元計算/ 出(入)超"\n'
           '"114年",1,2,3,4\n"114年10月",100000.0,60878.5,39000.0,1\n"115年 9月",150768.934,87216.206,63552.728,23663.478\n'
           '"115年 10月",165645.605,96760.189,68885.416,27874.773\n')


class TestParsers(unittest.TestCase):
    def test_cbc_columns_by_label_not_position(self):
        self.assertEqual(ml.parse_cbc(EF01, "貨幣總計數-M1B", "日平均", "年增率"), [("2026-07", 6.85), ("2026-08", 7.02), ("2026-09", 7.2)])
        self.assertEqual(ml.parse_cbc(EF01, "貨幣總計數-M2", "期底", "年增率")[-1], ("2026-09", 7.54))
        self.assertEqual(ml.parse_cbc(EF07, "外匯存底(百萬美元)")[-1], ("2026-09", 600745.0))
        self.assertEqual(ml.parse_cbc(BP01, "新台幣NTD/USD")[-1], ("2026-10-30", 32.478))

    def test_cbc_missing_label_is_an_error(self):
        with self.assertRaises(ValueError):
            ml.parse_cbc(EF01, "不存在的欄位", "日平均", "年增率")
        with self.assertRaises(ValueError):
            ml.parse_cbc({"oops": 1}, "x")

    def test_period_formats(self):
        self.assertEqual(ml.cbc_period("2026M09"), "2026-09")
        self.assertEqual(ml.cbc_period("20261030"), "2026-10-30")
        self.assertIsNone(ml.cbc_period("abc"))

    def test_ndc_zip(self):
        r = ml.parse_ndc_zip(ndc_zip())
        self.assertEqual(r["score"], [("2026-08", 40.0, "紅"), ("2026-09", 41.0, "紅"), ("2026-10", 40.0, "紅")])      # '-' 略過
        self.assertEqual(r["five_rate"], [("2026-09", 2.193), ("2026-10", 2.254)])

    def test_mof_trade_monthly_rows_only(self):
        self.assertEqual(ml.parse_mof_trade(MOF_CSV), [("2025-10", 60878.5), ("2026-09", 87216.206), ("2026-10", 96760.189)])

    def test_fred_skips_missing_values_and_rejects_error_payload(self):
        p = {"observations": [{"date": "2026-11-25", "value": "."}, {"date": "2026-11-26", "value": "4.21"}]}
        self.assertEqual(ml.parse_fred(p), [("2026-11-26", 4.21)])
        with self.assertRaises(ValueError):
            ml.parse_fred({"error_code": 400, "error_message": "Bad Request"})


class TestBuildRows(unittest.TestCase):
    def test_yoy_rate(self):
        rows = ml.build_rows([("2026-08", 7.02), ("2026-09", 7.2)], "yoy_rate")
        self.assertEqual((rows[1]["raw"], rows[1]["prev"], rows[1]["mom"], rows[1]["yoy"]), (7.2, 7.02, 0.18, 7.2))
        self.assertIsNone(rows[0]["prev"])

    def test_level_yoy_from_same_series(self):
        pts = [("2025-09", 100.0), ("2026-08", 150.0), ("2026-09", 165.0)]
        r = ml.build_rows(pts, "level", scale=0.01)[-1]
        self.assertEqual(r["raw"], 1.65)
        self.assertEqual(r["mom"], 10.0)
        self.assertEqual(r["yoy"], 65.0)
        self.assertIsNone(ml.build_rows(pts, "level")[1]["yoy"])        # 2025-08 不存在 → 不硬算

    def test_daily_yoy_needs_nearby_year_ago_point(self):
        near = [("2025-10-30", 30.0), ("2026-10-30", 33.0)]
        self.assertEqual(ml.build_rows(near, "level")[-1]["yoy"], 10.0)
        far = [("2025-06-01", 30.0), ("2026-10-30", 33.0)]
        self.assertIsNone(ml.build_rows(far, "level")[-1]["yoy"])        # 一年前附近沒有資料 (缺口 > 10 天)

    def test_score_has_no_yoy_and_keep(self):
        rows = ml.build_rows([("2026-07", 39.0), ("2026-08", 40.0), ("2026-09", 41.0)], "score", keep=2)
        self.assertEqual([r["period"] for r in rows], ["2026-08", "2026-09"])
        self.assertEqual(rows[-1]["mom"], 1.0)
        self.assertIsNone(rows[-1]["yoy"])

    def test_spread(self):
        self.assertEqual(ml.spread_points([("a", 7.2), ("b", 7.0)], [("a", 7.24)]), [("a", -0.04)])


MOEA_CSV = ("\ufeff統計項目,地區代碼,地區別,資料期(民國年),統計值(金額),計量單位\n"
            + "".join(f"外銷訂單金額_美元,00,地區別總計,{ym},{v},百萬美元\n" for ym, v in (("11410", 69_400), ("11509", 114_210), ("11510", 123_820)))
            + "外銷訂單金額_美元,01,美國,11510,50000,百萬美元\n外銷訂單金額_美元,00,地區別總計,11513,1,百萬美元\n")


def fetchers(fail=()):
    def fj(url):
        for key, payload in (("EF01M01", EF01), ("EF07M01", EF07), ("BP01D01", BP01), ("EF03M01", EF03), ("EFA4M01", EFA4), ("EH45m01", EH45)):
            if key in url:
                if key in fail:
                    raise ConnectionError("down")
                return payload
        if "fred" in url:
            return {"observations": [{"date": "2026-11-25", "value": "4.30"}, {"date": "2026-11-26", "value": "4.35"}]}
        raise AssertionError(url)

    def fb(url):
        if "ndc" in url:
            if "NDC" in fail:
                raise ConnectionError("down")
            return ndc_zip()
        if "mof" in url:
            return MOF_CSV.encode("utf-8")
        if "moea" in url:
            if "MOEA" in fail:
                raise ConnectionError("down")
            return MOEA_CSV.encode("utf-8")
        raise AssertionError(url)
    return {"fetch_json_fn": fj, "fetch_bytes_fn": fb}


class TestGather(unittest.TestCase):
    def test_all_sources(self):
        specs, status = ml.gather(None, **fetchers())
        self.assertEqual(set(specs), {"TW_M1B_YOY", "TW_M2_YOY", "TW_M1B_M2_SPREAD", "TW_FX_RESERVES", "TW_CPI_YOY", "TW_USD_TWD",
                                      "TW_NDC_SCORE", "TW_FIVE_BANK_NEW_RATE", "TW_CUSTOMS_EXPORTS", "TW_EXPORT_ORDERS",
                                      "TW_FX_DEPOSIT_BAL", "TW_BANK_LOAN_INV_YOY", "TW_FIVE_BANK_MORTGAGE"})
        self.assertIn("略過", status["FRED"])                              # 沒有金鑰 → 略過，不假裝
        self.assertEqual(specs["TW_FX_RESERVES"]["rows"][-1]["raw"], 6007.45)       # 百萬美元 → 億美元
        self.assertEqual(specs["TW_CUSTOMS_EXPORTS"]["rows"][-1]["raw"], 967.6019)
        self.assertIn("紅燈", specs["TW_NDC_SCORE"]["rows"][-1]["note"])
        fd = specs["TW_FX_DEPOSIT_BAL"]["rows"][-1]
        self.assertEqual((fd["period"], fd["raw"], fd["yoy"]), ("2026-09", 10.0591, 11.77))       # 億元 → 兆元；年增由同序列一年前計算
        self.assertEqual(specs["TW_BANK_LOAN_INV_YOY"]["rows"][-1]["raw"], 9.79)                  # 本身就是年增率
        self.assertEqual(specs["TW_FIVE_BANK_MORTGAGE"]["rows"][-1]["raw"], 697.83)               # 百萬元 → 億元
        eo = specs["TW_EXPORT_ORDERS"]["rows"][-1]
        self.assertEqual((eo["period"], eo["raw"]), ("2026-10", 1238.2))              # 百萬美元 → 億美元，只取「地區別總計」，月份 13 的壞列略過
        self.assertEqual(eo["yoy"], 78.41)                                            # 與去年同月 69,400 比較
        self.assertEqual(specs["TW_M1B_YOY"]["release"], "2026-10-28")

    def test_fred_only_with_key_and_key_never_logged_in_status(self):
        specs, status = ml.gather("SECRETKEY", **fetchers())
        self.assertEqual({"US_10Y_YIELD", "US_FED_RATE_UPPER", "INTL_VIX", "INTL_USD_BROAD"} - set(specs), set())
        self.assertEqual(specs["US_10Y_YIELD"]["rows"][-1]["raw"], 4.35)
        self.assertNotIn("SECRETKEY", str(status))

    def test_moea_failure_is_recorded_without_touching_other_sources(self):
        specs, status = ml.gather(None, **fetchers(fail=("MOEA",)))
        self.assertIn("失敗", status["MOEA 外銷訂單"])
        self.assertNotIn("TW_EXPORT_ORDERS", specs)
        self.assertIn("TW_CUSTOMS_EXPORTS", specs)

    def test_one_source_failing_does_not_stop_others(self):
        specs, status = ml.gather(None, **fetchers(fail=("EF01M01", "NDC")))
        self.assertIn("失敗", status["CBC EF01M01"])
        self.assertNotIn("TW_M1B_YOY", specs)
        self.assertIn("TW_FX_RESERVES", specs)
        self.assertIn("TW_CUSTOMS_EXPORTS", specs)
        self.assertNotIn("TW_NDC_SCORE", specs)


class TestApply(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="twfin_macro_")
        import db
        cls.db = db
        cls.orig = db.DB_PATH
        db.DB_PATH = os.path.join(cls.tmp, "t.db")
        db.init_database()
        from seed_and_engine import seed_and_compute_all
        seed_and_compute_all()

    @classmethod
    def tearDownClass(cls):
        cls.db.DB_PATH = cls.orig
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from seed_and_engine import seed_and_compute_all
        seed_and_compute_all()                    # 每次排程都會重灌手寫列
        self.conn = self.db.get_connection()
        self.addCleanup(self.conn.close)

    def rows(self, code):
        return [dict(r) for r in self.conn.execute("SELECT * FROM macro_observations WHERE metric_code = ? ORDER BY period_covered", (code,))]

    def test_official_values_replace_handwritten_rows_in_their_period(self):
        before = self.rows("TW_FX_RESERVES")
        self.assertTrue(any(r["revision_version"].startswith("v1") for r in before))
        res = ml.apply_live_macro(self.conn, fetchers=fetchers())
        self.assertIn("TW_FX_RESERVES", res["applied"])
        rows = self.rows("TW_FX_RESERVES")
        by = {r["period_covered"]: r for r in rows}
        self.assertEqual(by["2026-09"]["raw_value"], 6007.45)                       # 官方值取代手寫的 5988.20
        self.assertTrue(by["2026-09"]["revision_version"].startswith("live"))
        self.assertIn("央行 EF07M01", by["2026-09"]["notes"])
        self.assertEqual(by["2026-10"]["raw_value"], 5964.37)                      # 官方還沒公布的期間：手寫列保留
        self.assertFalse(by["2026-10"]["revision_version"].startswith("live"))

    def test_rerun_is_idempotent_and_seed_reload_is_replaced_again(self):
        ml.apply_live_macro(self.conn, fetchers=fetchers())
        n1 = len(self.rows("TW_M1B_YOY"))
        from seed_and_engine import seed_and_compute_all
        seed_and_compute_all()                                                      # 排程又重灌手寫列
        self.conn.close()
        self.conn = self.db.get_connection()
        ml.apply_live_macro(self.conn, fetchers=fetchers())
        rows = self.rows("TW_M1B_YOY")
        self.assertEqual(len(rows), n1)
        periods = [r["period_covered"] for r in rows]
        self.assertEqual(len(periods), len(set(periods)))                          # 同一期間不會同時有手寫與官方兩列
        self.assertTrue(all(r["revision_version"].startswith("live") for r in rows if r["period_covered"] <= "2026-09"))

    def test_failure_keeps_previous_live_rows_and_seed(self):
        ml.apply_live_macro(self.conn, fetchers=fetchers())
        live_before = [r for r in self.rows("TW_M1B_YOY") if r["revision_version"].startswith("live")]
        res = ml.apply_live_macro(self.conn, fetchers=fetchers(fail=("EF01M01", "EF07M01", "BP01D01", "NDC")))
        self.assertNotIn("TW_M1B_YOY", res["applied"])
        live_after = [r for r in self.rows("TW_M1B_YOY") if r["revision_version"].startswith("live")]
        self.assertEqual(len(live_after), len(live_before))                         # 先前累積的官方列不會因為這次失敗而消失

    def test_fred_adds_new_metric_with_dictionary_row(self):
        os.environ["FRED_API_KEY"] = "k"
        try:
            res = ml.apply_live_macro(self.conn, fetchers=fetchers())
        finally:
            del os.environ["FRED_API_KEY"]
        self.assertIn("INTL_VIX", res["applied"])
        self.assertEqual(self.rows("INTL_VIX")[-1]["raw_value"], 4.35)
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM data_dictionary WHERE metric_code = 'INTL_VIX'").fetchone())

    def test_total_revenue_is_summed_from_live_company_data(self):
        for k in range(10):
            self.conn.execute("""INSERT OR REPLACE INTO live_company_fundamentals (company_code, company_name, market_type, official_industry,
                mapped_industry_id, data_ym, report_date, rev_current_thousand, rev_prev_month_thousand, rev_last_year_thousand, fetched_at, source_url)
                VALUES (?, 'n', 'TWSE', 'x', 'IND_SEMI_FOUNDRY', '11510', '1151110', 1e9, 0.5e9, 0.5e9, 't', 'u')""", (f"91{k:02d}",))
        self.conn.commit()
        res = ml.apply_live_macro(self.conn, fetchers=fetchers(fail=("EF01M01", "EF07M01", "BP01D01", "NDC")))
        self.assertIn("TW_MOPS_TOTAL_REV", res["applied"])
        r = self.rows("TW_MOPS_TOTAL_REV")[-1]
        self.assertEqual(r["period_covered"], "2026-10")
        self.assertGreater(r["raw_value"], 0)
        self.assertTrue(r["revision_version"].startswith("live"))
        self.conn.execute("DELETE FROM live_company_fundamentals WHERE company_code LIKE '91__'")
        self.conn.commit()

    def test_observation_type_follows_dictionary(self):
        ml.apply_live_macro(self.conn, fetchers=fetchers())
        r = [x for x in self.rows("TW_M1B_M2_SPREAD") if x["revision_version"].startswith("live")][-1]
        self.assertEqual(r["observation_type"], "PROXY_INDICATOR")


if __name__ == "__main__":
    unittest.main()
