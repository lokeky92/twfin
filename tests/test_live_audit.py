"""多代理即時稽核：規則與門檻、交叉審查／辯論／整合／提案的邏輯、人工決定不被覆蓋、唯讀與完整性、最新記錄的選擇 (全部離線、暫存目錄)"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

_TMP = tempfile.mkdtemp(prefix="twfin_audit_test_")
las = None
mao = None
db = None
_ORIG = {}


def setUpModule():
    global las, mao, db
    import db as _db
    from argon_multi_agent.engine import live_audit_session as _las, multi_agent_orchestrator as _mao
    las, mao, db = _las, _mao, _db
    _ORIG.update(ma_root=mao.MA_ROOT, mao_db=mao.DB_PATH, db=db.DB_PATH)
    mao.MA_ROOT = os.path.join(_TMP, "ma")
    db.DB_PATH = mao.DB_PATH = os.path.join(_TMP, "audit.db")
    from seed_and_engine import seed_and_compute_all
    seed_and_compute_all()
    import etf_engine                                   # 建立 ETF 資料表與種子 (離線：網路請求一律失敗並使用內建備援)
    _ORIG["etf_fetch"] = etf_engine._fetch_json
    etf_engine._fetch_json = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline"))
    etf_engine.build_and_compute_etf_center()


def tearDownModule():
    import etf_engine
    if "etf_fetch" in _ORIG:
        etf_engine._fetch_json = _ORIG["etf_fetch"]
    if mao is not None:
        mao.MA_ROOT, mao.DB_PATH, db.DB_PATH = _ORIG["ma_root"], _ORIG["mao_db"], _ORIG["db"]
    shutil.rmtree(_TMP, ignore_errors=True)


def etf(code, market="TW", lev=0, maxs=10.0, A=70.0, B=50.0, cb="持續觀察", miss=0.0, score_source="live", live=None, turn=1e9, spread=None, asset="股票"):
    return {"code": code, "name": code + "名", "market": market, "asset_class": asset, "lev": lev, "ter": 0.2, "spread": spread, "turn": turn,
            "trade_date": "2026-11-27", "top10": 40.0, "maxs": maxs, "A": A, "B": B, "ca": "條件普通", "cb": cb, "miss": miss, "cred": "A",
            "score_source": score_source, "nav": None, "prem": None, "msrc": "live", "live": live}


def ind(i, score, level="LEVEL 2", inst=1.0, yoy=40.0):
    return {"id": i, "name": i + "業", "score": score, "state": "B", "score_source": "live", "yoy": yoy, "level": level, "inst": inst}


def ev(**kw):
    base = {"now": "2026-11-27T22:00:00+08:00", "session_id": "SESSION-LIVE-TEST", "sources": [{"source_key": "a", "status": "OK", "data_date": "2026-11-27", "record_count": 1, "message": ""}],
            "etfs": [etf("0050"), etf("VOO", "US", score_source="seed")], "holdings": {}, "taiex": {"close": 39000.0, "ma60": 44000.0, "vs_ma60": -11.4, "vol20": 60.0},
            "industries": [ind(f"I{k}", 80 - k * 5) for k in range(8)], "last_industry_day": "2026-11-27", "snapshot_days": 1,
            "inventory": {"趨勢預警": {"live": 13}}, "official_flow": {"foreign_net_billion": -300.0, "itc_net_billion": 80.0},
            "dups": {"etf_daily_metrics": [], "trend_early_warnings": [], "industry_rotation_scores": []}, "audit_failures": [], "backfill_missing": 0,
            "db_mb": 2.0, "loc": {"a.py": 100, "b.py": 50}}
    base.update(kw)
    return base


def keys(fs):
    return [f["key"] for f in fs]


# ---------------------------------------------------------------------------
class TestFindingRules(unittest.TestCase):
    def test_us_seed_scores_flagged_only_when_present(self):
        self.assertIn("US_ETF_SEED_SCORES", keys(las.findings_01(ev())))
        self.assertNotIn("US_ETF_SEED_SCORES", keys(las.findings_01(ev(etfs=[etf("0050"), etf("VOO", "US", score_source="live")]))))

    def test_concentration_is_informational_not_a_defect(self):
        fs = las.findings_01(ev(etfs=[etf("0050", maxs=56.8)]))
        f = next(f for f in fs if f["key"] == "TW_CONCENTRATION")
        self.assertEqual(f["severity"], "INFO")
        self.assertIn("56.8%", f["evidence"])

    def test_flow_price_divergence_rule(self):
        live = {"ret_1m": 6.0, "insti_ratio_pct": -3.0}
        self.assertIn("FLOW_PRICE_DIVERGENCE", keys(las.findings_02(ev(etfs=[etf("0050", live=live)]))))
        self.assertNotIn("FLOW_PRICE_DIVERGENCE", keys(las.findings_02(ev(etfs=[etf("0050", live={"ret_1m": 6.0, "insti_ratio_pct": 2.0})]))))

    def test_uniformly_weak_needs_enough_samples(self):
        many = [etf(f"E{k}", cb="風險偏高", live={"ret_1m": 0, "insti_ratio_pct": 0}) for k in range(6)]
        self.assertIn("B_UNIFORMLY_WEAK", keys(las.findings_02(ev(etfs=many))))
        few = many[:3]
        self.assertNotIn("B_UNIFORMLY_WEAK", keys(las.findings_02(ev(etfs=few))))

    def test_leveraged_turnover_share(self):
        e = [etf("0050", turn=1e9, live={"turnover_twd": 1e9}), etf("00631L", lev=1, turn=1e9, live={"turnover_twd": 9e9})]
        f = next(f for f in las.findings_04(ev(etfs=e)) if f["key"] == "LEVERAGED_TURNOVER")
        self.assertEqual(f["severity"], "P1")
        self.assertIn("90%", f["evidence"])
        e2 = [etf("0050", live={"turnover_twd": 9e9}), etf("00631L", lev=1, live={"turnover_twd": 1e9})]
        self.assertNotIn("LEVERAGED_TURNOVER", keys(las.findings_04(ev(etfs=e2))))

    def test_redundancy_and_overlap_and_liquidity(self):
        e = [etf("0050", live={"corr_0050": 1.0}), etf("00XXX", live={"corr_0050": 0.995}), etf("00878", live={"corr_0050": 0.7}, spread=22.0)]
        hold = {"0050": {"2330": 56.8, "2317": 5.4}, "00XXX": {"2330": 56.9, "2317": 5.4}, "00878": {"2303": 4.8}}
        fs = las.findings_04(ev(etfs=e, holdings=hold))
        self.assertIn("REDUNDANT_WITH_CORE", keys(fs))
        self.assertIn("00XXX", next(f for f in fs if f["key"] == "REDUNDANT_WITH_CORE")["evidence"])
        self.assertNotIn("0050 (", next(f for f in fs if f["key"] == "REDUNDANT_WITH_CORE")["evidence"])   # 核心 ETF 本身不算
        self.assertIn("62%", next(f for f in fs if f["key"] == "HOLDING_OVERLAP")["evidence"])
        self.assertIn("00878", next(f for f in fs if f["key"] == "WIDE_SPREAD")["evidence"])

    def test_backtest_immature_threshold(self):
        self.assertIn("BACKTEST_IMMATURE", keys(las.findings_05(ev(snapshot_days=1))))
        self.assertNotIn("BACKTEST_IMMATURE", keys(las.findings_05(ev(snapshot_days=las.BACKTEST_MIN_DAYS))))

    def test_level_r_artifact_and_score_flow_contradiction(self):
        inds = [ind(f"I{k}", 80 - k * 8, level="LEVEL R" if k >= 3 else "LEVEL 2", inst=-5.0 if k == 0 else (3.0 if k == 7 else 0.0)) for k in range(8)]
        fs = las.findings_05(ev(industries=inds))
        self.assertIn("LEVEL_R_ARTIFACT", keys(fs))
        f = next(f for f in fs if f["key"] == "SCORE_VS_FLOW")
        self.assertIn("淨賣", f["evidence"])
        self.assertIn("淨買", f["evidence"])

    def test_seed_inventory_reported(self):
        fs = las.findings_05(ev(inventory={"趨勢預警": {"seed": 7}, "ETF 雙軌評分": {"seed": 13, "live": 15}}))
        f = next(f for f in fs if f["key"] == "SEED_STILL_SHOWN")
        self.assertIn("趨勢預警 7 列", f["evidence"])
        self.assertEqual(f["n"], 20)

    def test_engineering_findings(self):
        fs = las.findings_06(ev(audit_failures=[{"task_name": "X", "status": "FAILED", "message": ""}], backfill_missing=12, db_mb=80.0))
        self.assertEqual({"INGEST_FAILURES", "BACKFILL_PENDING", "DB_SIZE", "CODE_SIZE"}, set(keys(fs)))
        self.assertEqual(keys(las.findings_06(ev())), ["CODE_SIZE"])


class TestSevenChecks(unittest.TestCase):
    def status(self, **kw):
        return {c["check_no"]: c["status"] for c in las.checks_03(ev(**kw))}

    def test_all_pass_on_a_clean_state(self):
        e = ev(etfs=[etf("0050", live={"last_date": "2026-11-27", "history_days": 250})], industries=[ind("A", 70, inst=-300.0)])
        st = {c["check_no"]: c["status"] for c in las.checks_03(e)}
        self.assertEqual(set(st.values()), {"PASS"})
        self.assertEqual(len(st), 7)

    def test_each_failure_mode(self):
        self.assertEqual(self.status(sources=[{"source_key": "x", "status": "FAILED", "data_date": "", "record_count": 0, "message": ""}])[1], "WARNING")
        self.assertEqual(self.status(backfill_missing=5)[3], "WARNING")
        self.assertEqual(self.status(backfill_missing=None)[3], "WARNING")
        self.assertEqual(self.status(inventory={"ETF 雙軌評分": {"seed": 13}})[6], "WARNING")
        self.assertEqual(self.status(dups={"etf_daily_metrics": ["0050"], "trend_early_warnings": [], "industry_rotation_scores": []})[7], "FAIL")

    def test_fabricated_nav_is_a_failure(self):
        bad = etf("0050", live={"last_date": "2026-11-27", "history_days": 250})
        bad["nav"] = 92.3
        self.assertEqual(self.status(etfs=[bad])[5], "FAIL")
        ok = etf("0050", live={"last_date": "2026-11-27", "history_days": 250})
        self.assertEqual(self.status(etfs=[ok])[5], "PASS")

    def test_coverage_check_compares_with_official(self):
        low = self.status(industries=[ind("A", 70, inst=-50.0)])               # 官方 -220，只涵蓋 23%
        self.assertEqual(low[4], "WARNING")
        wrong_sign = self.status(industries=[ind("A", 70, inst=+250.0)])
        self.assertEqual(wrong_sign[4], "WARNING")


# ---------------------------------------------------------------------------
class TestDebateLogic(unittest.TestCase):
    def test_one_review_per_agent_targeting_the_next(self):
        f = las.collect_findings(ev())
        rev = las.phase3_reviews(f)
        self.assertEqual([r["reviewer_id"] for r in rev], [a for a, _, _ in las.AGENTS])
        self.assertEqual([r["target_agent_id"] for r in rev], [a for a, _, _ in las.AGENTS][1:] + ["AGENT_01"])
        crit = next(r for r in rev if r["reviewer_id"] == "AGENT_05")
        self.assertEqual(set(crit["critic_structured_blocks"]), {"supporting_evidence", "counter_evidence", "unverified_assumptions", "unverifiable_or_missing_data"})

    def test_insufficient_and_small_sample_are_questioned_and_downgraded_once(self):
        fs = {a: [] for a, _, _ in las.AGENTS}
        fs["AGENT_02"] = [las.F("K1", "AGENT_02", "P1", "樣本少的結論", "d", "e", "t", n=1)]
        fs["AGENT_03"] = [las.F("K2", "AGENT_03", "P0", "依賴不完整資料", "d", "e", "t", n=10, insufficient=True)]
        fs["AGENT_04"] = [las.F("K3", "AGENT_04", "P1", "樣本充足", "d", "e", "t", n=10)]
        rev = las.phase3_reviews(fs)
        by = {r["target_agent_id"]: r for r in rev}
        self.assertIn("樣本偏少", by["AGENT_02"]["review_stance"])
        self.assertIn("證據不足", by["AGENT_03"]["review_stance"])
        self.assertIn("SUPPORT", by["AGENT_04"]["review_stance"])
        self.assertIn("NO_FINDINGS", by["AGENT_01"]["review_stance"])
        reb = las.phase4_rebuttals(fs, rev)
        self.assertEqual(fs["AGENT_02"][0]["severity"], "P2")                    # P1 → P2
        self.assertEqual(fs["AGENT_03"][0]["severity"], "P1")                    # P0 → P1
        self.assertEqual(fs["AGENT_04"][0]["severity"], "P1")                    # 沒被質疑 → 不變
        d = {r["agent_id"]: r["decision"] for r in reb}
        self.assertTrue(d["AGENT_02"].startswith("MODIFY"))
        self.assertTrue(d["AGENT_04"].startswith("MAINTAIN"))
        self.assertIn("暫定", fs["AGENT_02"][0]["detail"])

    def test_gap_findings_are_listed_but_never_downgraded(self):
        fs = {a: [] for a, _, _ in las.AGENTS}
        fs["AGENT_03"] = [las.F("NAV", "AGENT_03", "P1", "缺淨值來源", "d", "e", "nav", n=15, gap=True)]
        rev = las.phase3_reviews(fs)
        las.phase4_rebuttals(fs, rev)
        self.assertEqual(fs["AGENT_03"][0]["severity"], "P1")
        syn = las.phase5_synthesis(fs, rev, ev())
        self.assertTrue(any("缺淨值來源" in s for s in syn["insufficient_evidence_areas"]))

    def test_independent_reports_are_the_pre_debate_version(self):
        f = las.collect_findings(ev())
        reports = las.phase2_reports(copy.deepcopy(f), ev())
        before = {a: [x["severity"] for x in fs] for a, fs in f.items()}
        las.phase4_rebuttals(f, las.phase3_reviews(f))
        after = {a: [x["severity"] for x in fs] for a, fs in f.items()}
        self.assertNotEqual(before, after)                                        # 辯論確實改變了嚴重度
        self.assertEqual({a: [x["severity"] for x in r["findings"]] for a, r in reports.items()}, before)   # 獨立報告不受影響

    def test_synthesis_is_html_safe_and_groups_cross_agent_topics(self):
        fs = {a: [] for a, _, _ in las.AGENTS}
        fs["AGENT_03"] = [las.F("A", "AGENT_03", "P2", "<b>手寫</b>", "d", "<i>e</i>", "seed_inventory", n=5)]
        fs["AGENT_05"] = [las.F("B", "AGENT_05", "P1", "仍有手寫", "d", "e", "seed_inventory", n=5)]
        syn = las.phase5_synthesis(fs, las.phase3_reviews(fs), ev())
        self.assertEqual(len(syn["consensus_solutions"]), 1)
        self.assertIn("03/05", syn["consensus_solutions"][0])
        self.assertNotIn("<b>", syn["consensus_solutions"][0])
        self.assertIn("&lt;b&gt;", syn["consensus_solutions"][0])


class TestProposals(unittest.TestCase):
    def test_only_actionable_non_info_findings_become_proposals(self):
        prop = {"change": "c", "modules": ["m"], "effect": "e", "side": "s", "difficulty": "低"}
        fs = {a: [] for a, _, _ in las.AGENTS}
        fs["AGENT_01"] = [las.F("OKP", "AGENT_01", "P1", "有提案", "d", "e", "t", n=10, proposal=prop),
                          las.F("INFO", "AGENT_01", "INFO", "僅資訊", "d", "e", "t", proposal=prop),
                          las.F("NOP", "AGENT_01", "P2", "沒提案", "d", "e", "t", n=10)]
        out = las.phase6_proposals(fs, ev())
        self.assertEqual([p["proposal_id"] for p in out], ["LIVE-IMPROVE-OKP"])
        p = out[0]
        sb = p["score_breakdown"]
        self.assertEqual(p["status"], "PENDING_APPROVAL")
        self.assertEqual(p["priority"], "P1")
        self.assertEqual(sb["total_score"], sum(sb[k] for k in ("data_and_evidence_reliability", "expected_improvement_value", "risk_control",
                                                                "technical_feasibility", "system_compatibility")))
        for required in ("title", "current_problem", "problem_evidence", "proposed_change", "expected_effect", "affected_modules",
                         "potential_side_effects", "implementation_difficulty", "testing_plan", "rollback_plan"):
            self.assertTrue(p[required], required)

    def test_weaker_evidence_scores_lower(self):
        prop = {"change": "c", "modules": ["m"], "effect": "e", "side": "s", "difficulty": "中"}
        strong = las.phase6_proposals({"A": [las.F("S", "AGENT_01", "P1", "t", "d", "e", "t", n=10, proposal=prop)]}, ev())[0]
        weak = las.phase6_proposals({"A": [las.F("W", "AGENT_01", "P1", "t", "d", "e", "t", n=10, insufficient=True, proposal=prop)]}, ev())[0]
        self.assertGreater(strong["score_breakdown"]["total_score"], weak["score_breakdown"]["total_score"])

    def test_at_most_six_proposals_highest_severity_first(self):
        prop = {"change": "c", "modules": ["m"], "effect": "e", "side": "s", "difficulty": "低"}
        fs = {"A": [las.F(f"K{i}", "AGENT_01", "P2", f"t{i}", "d", "e", "t", n=10, proposal=prop) for i in range(8)]
              + [las.F("TOP", "AGENT_01", "P0", "最高", "d", "e", "t", n=10, proposal=prop)]}
        out = las.phase6_proposals(fs, ev())
        self.assertEqual(len(out), 6)
        self.assertEqual(out[0]["proposal_id"], "LIVE-IMPROVE-TOP")


# ---------------------------------------------------------------------------
class TestFullSession(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(mao.MA_ROOT, ignore_errors=True)

    def test_session_writes_every_artifact_and_leaves_production_untouched(self):
        b = las.run_live_audit_session()
        self.assertTrue(b["production_integrity_verified"])
        self.assertEqual(b["origin"], "live_audit")
        self.assertEqual(set(b["phase2_independent_reports"]), {a for a, _, _ in las.AGENTS})
        self.assertEqual(len(b["phase3_cross_reviews"]), 6)
        self.assertEqual(len(b["phase4_rebuttals"]), 6)
        self.assertEqual(len(b["data_quality_audit"]["seven_statutory_checks"]), 7)
        sid = b["session_id"]
        for rel in (f"research/history/{sid}_full_record.json", f"discussions/debate_records/{sid}_debate.json",
                    f"evaluations/model_evaluations/{sid}_synthesis.json", f"evaluations/data_quality/{sid}_dq_audit.json",
                    f"research/completed/{sid}_AGENT_01.json"):
            self.assertTrue(os.path.exists(os.path.join(mao.MA_ROOT, rel)), rel)
        for r in b["phase2_independent_reports"].values():                       # 前端需要的欄位
            for k in ("agent_name", "data_timestamp_used", "current_system_problems", "research_evidence", "identified_defects",
                      "improvement_suggestions", "expected_effects", "potential_risks"):
                self.assertTrue(r[k], k)
        self.assertNotIn("_question", json.dumps(b))                             # 內部欄位不外洩

    def test_state_prefers_the_latest_live_session_and_labels_origin(self):
        mao.ensure_ma_directories()
        self.assertEqual(mao.get_multi_agent_state()["origin"], "handwritten")   # 沒有即時稽核時退回舊的手寫記錄 (並標明)
        shutil.rmtree(mao.MA_ROOT, ignore_errors=True)
        b = las.run_live_audit_session()
        st = mao.get_multi_agent_state()
        self.assertEqual(st["origin"], "live_audit")
        self.assertEqual(st["session_id"], b["session_id"])
        self.assertEqual(mao.current_session_id(), b["session_id"])

    def test_human_decisions_are_never_overwritten_or_recreated(self):
        b = las.run_live_audit_session()
        pid = next(p["proposal_id"] for p in b["phase6_proposals"])
        mao.update_proposal_approval_status(pid, "REJECT", "不需要")
        self.assertFalse(os.path.exists(os.path.join(mao.MA_ROOT, "proposals", "pending", pid + ".json")))
        b2 = las.run_live_audit_session()
        self.assertNotIn(pid, b2["new_proposals_written"])                       # 已被人工決定的不再建立
        self.assertFalse(os.path.exists(os.path.join(mao.MA_ROOT, "proposals", "pending", pid + ".json")))
        status = {p["proposal_id"]: p["status"] for p in mao.list_proposals()}
        self.assertEqual(status[pid], "REJECTED_BY_USER")
        self.assertEqual(len([1 for p in mao.list_proposals() if p["proposal_id"] == pid]), 1)

    def test_old_live_sessions_are_pruned(self):
        import time
        ids = []
        for _ in range(las.KEEP_SESSIONS + 2):
            ids.append(las.run_live_audit_session()["session_id"])
            time.sleep(1.05)                                                     # session id 以秒為單位
        hist = os.listdir(os.path.join(mao.MA_ROOT, "research", "history"))
        kept = [f.lower() for f in hist if f.lower().startswith("session-live-")]          # Windows 會把檔名寫成小寫
        self.assertEqual(len(kept), las.KEEP_SESSIONS)
        self.assertIn((ids[-1] + "_full_record.json").lower(), kept)
        self.assertNotIn((ids[0] + "_full_record.json").lower(), kept)
        left = [f for sub in ("research/completed", "discussions/debate_records", "evaluations/data_quality")
                for f in os.listdir(os.path.join(mao.MA_ROOT, *sub.split("/"))) if ids[0].lower() in f.lower()]
        self.assertEqual(left, [])                                                          # 舊的附屬檔案也一併清掉


class TestPipelineOrdering(unittest.TestCase):
    def test_audit_runs_after_every_live_step_and_before_export(self):
        """每次排程一開始都會重灌手寫種子列；稽核若太早執行，會把中途狀態誤判為重複／手寫 (實際發生過)。"""
        with open(os.path.join(ROOT, "backend", "run_pipeline.py"), encoding="utf-8") as f:
            src = f.read()
        order = ["seed_and_compute_all()", "run_live_ingestion()", "build_and_compute_etf_center(", "apply_live_etf()", "apply_live_macro()", "apply_live_scoring()",
                 "snapshot_industry_scores()", "apply_live_watchlist()", "apply_live_reports()", "run_live_audit_session()", "export_standalone()"]
        pos = [src.index(x, src.index("def main")) for x in order]
        self.assertEqual(pos, sorted(pos), "排程步驟順序錯誤：" + ", ".join(order))


class TestEvidenceGathering(unittest.TestCase):
    def test_empty_database_state_does_not_crash(self):
        conn = mao.get_readonly_db_connection()
        try:
            e = las.gather_evidence(conn)
        finally:
            conn.close()
        for k in ("sources", "etfs", "industries", "inventory", "dups", "loc"):
            self.assertIn(k, e)
        self.assertEqual(e["snapshot_days"], 0)
        las.collect_findings(e)                                                  # 不可丟例外

    def test_gathering_is_read_only(self):
        conn = mao.get_readonly_db_connection()
        try:
            las.gather_evidence(conn)
            with self.assertRaises(Exception):
                conn.execute("DELETE FROM etf_master")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
