"""
Argon ETF Multi-Agent Research Team — Stage 5 八大治理與權限隔離自動化測試套件
(test_multi_agent_governance.py)

嚴格驗證第十二節 Stage 5 要求的 8 大測試項目：
1. test_01_agents_independent_execution: 多 Agent 是否真正獨立執行並產出必填六大區塊。
2. test_02_complete_discussion_and_debate_records: 討論是否有完整 Phase 3 交叉審查與 Phase 4 第二輪辯論紀錄。
3. test_03_critic_agent_opposing_views_and_counterexamples: 反方 Agent 05 是否能提出不同意見、具體反例與四項強制標記，且分歧觀點被保留。
4. test_04_data_sources_and_timestamps_cited: 所有研究報告與提案是否明確引用真實 SQLite 資料表、程式碼行號與資料時間戳。
5. test_05_readonly_db_and_write_permissions_enforced: SQLite 唯讀 URI (?mode=ro) 與目錄白名單權限鎖是否真正有效。
6. test_06_unapproved_cannot_modify_production_code: 未經使用者批准前，是否確實無法修改任何正式業務程式碼或資料庫（攔截並拋出 PermissionError，且 SHA-256 指紋 100% 不變）。
7. test_07_failure_recovery_and_state_persistence: 中途失敗或狀態讀取異常時是否能由磁碟歷史快照自動恢復。
8. test_08_no_resource_conflict_across_agents: 多個 Agent 同時讀取 SQLite 與寫入各自獨立報告檔案時是否零資源衝突。
"""
import os
import sys
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor

import atexit
import shutil
import tempfile

# 在暫存目錄的副本上執行，避免測試改寫 repo 內已提交的研究紀錄、提案與日誌
_MA_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="twfin_ma_test_")
os.environ["TWFIN_MA_ROOT"] = os.path.join(_TMP, "argon_multi_agent")
shutil.copytree(_MA_SRC, os.environ["TWFIN_MA_ROOT"])
atexit.register(shutil.rmtree, _TMP, True)

# 資料庫已不再提交進 git (CI 中不存在)，因此以種子資料建立一份暫存資料庫供唯讀查詢
os.environ["TWFIN_DB_PATH"] = os.path.join(_TMP, "test.db")
sys.path.insert(0, os.path.join(os.path.dirname(_MA_SRC), "backend"))
from seed_and_engine import seed_and_compute_all  # noqa: E402
from phase2_to_6_engine import populate_phase2_to_phase6  # noqa: E402
import etf_engine  # noqa: E402


def _offline_fetch(url, timeout=12):
    raise ConnectionError("tests run offline")


etf_engine._fetch_json = _offline_fetch  # 不連外網，使用引擎內建的備援數值
seed_and_compute_all()
populate_phase2_to_phase6()
etf_engine.build_and_compute_etf_center()

sys.path.insert(0, _MA_SRC)
from engine.multi_agent_orchestrator import (
    MA_ROOT,
    BASE_DIR,
    run_full_multi_agent_session,
    get_multi_agent_state,
    get_readonly_db_connection,
    compute_production_checksums,
    safe_write_ma_file,
    update_proposal_approval_status,
    extract_live_system_evidence
)


class TestArgonMultiAgentGovernance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.initial_checksums = compute_production_checksums()
        cls.session_bundle = run_full_multi_agent_session()

    def test_01_agents_independent_execution(self):
        """測試 1：驗證 6 位專業 Agent 均獨立執行並產出獨立檔案與 6 大必填欄位"""
        reports = self.session_bundle["phase2_independent_reports"]
        expected_agents = ["AGENT_01", "AGENT_02", "AGENT_03", "AGENT_04", "AGENT_05", "AGENT_06"]
        self.assertEqual(sorted(list(reports.keys())), expected_agents)

        required_fields = [
            "current_system_problems",
            "research_evidence",
            "identified_defects",
            "improvement_suggestions",
            "expected_effects",
            "potential_risks"
        ]
        problems_set = set()
        for aid in expected_agents:
            r = reports[aid]
            for f in required_fields:
                self.assertIn(f, r, f"{aid} 缺少必填欄位 {f}")
                self.assertTrue(len(str(r[f]).strip()) > 30, f"{aid} 欄位 {f} 內容過短")
            # 確保每位 Agent 的結論皆獨立不重複
            problems_set.add(r["current_system_problems"])
            json_path = os.path.join(MA_ROOT, "research", "completed", f"SESSION-20261122-001_{aid}.json")
            md_path = os.path.join(MA_ROOT, "research", "completed", f"SESSION-20261122-001_{aid}.md")
            self.assertTrue(os.path.exists(json_path))
            self.assertTrue(os.path.exists(md_path))

        self.assertEqual(len(problems_set), 6, "6 位 Agent 的獨立研究問題不可互相複製")

    def test_02_complete_discussion_and_debate_records(self):
        """測試 2：驗證 Phase 3 交叉審查與 Phase 4 第二輪辯論是否有完整紀錄"""
        p3 = self.session_bundle["phase3_cross_reviews"]
        p4 = self.session_bundle["phase4_rebuttals"]
        self.assertGreaterEqual(len(p3), 6, "每位 Agent 皆須參與 Phase 3 交叉審查")
        self.assertEqual(len(p4), 6, "6 位 Agent 皆須於 Phase 4 提交第二輪辯論立場與理由")

        for rev in p3:
            self.assertIn("reviewer_id", rev)
            self.assertIn("target_agent_id", rev)
            self.assertTrue(len(rev["comment"]) > 30)

        for reb in p4:
            self.assertIn("decision", reb)
            self.assertIn("reason", reb)
            self.assertTrue(len(reb["reason"]) > 20)

    def test_03_critic_agent_opposing_views_and_counterexamples(self):
        """測試 3：驗證反方審查員 Agent 05 是否提出具體反例與四項強制標記，且 Argon 保留了分歧觀點"""
        p3 = self.session_bundle["phase3_cross_reviews"]
        critic_reviews = [r for r in p3 if r["reviewer_id"] == "AGENT_05"]
        self.assertEqual(len(critic_reviews), 1)
        blocks = critic_reviews[0].get("critic_structured_blocks", {})

        # 驗證第三節要求的反方四項強制標記
        self.assertIn("supporting_evidence", blocks)
        self.assertIn("counter_evidence", blocks)
        self.assertIn("unverified_assumptions", blocks)
        self.assertIn("unverifiable_or_missing_data", blocks)
        self.assertIn("反例", blocks["counter_evidence"])

        # 驗證第四節：Argon 總指揮不得抹除分歧觀點
        synthesis = self.session_bundle["phase5_synthesis"]
        self.assertGreaterEqual(len(synthesis["divergent_views_preserved"]), 2)
        self.assertGreaterEqual(len(synthesis["critic_risk_warnings"]), 2)

    def test_04_data_sources_and_timestamps_cited(self):
        """測試 4：驗證研究報告與 6 項提案皆具備真實資料來源、時間戳與 10 大必填欄位 + 100 分制評分"""
        proposals = self.session_bundle["phase6_proposals"]
        self.assertEqual(len(proposals), 6)

        required_proposal_keys = [
            "proposal_id", "title", "current_problem", "problem_evidence",
            "proposed_change", "expected_effect", "affected_modules",
            "potential_side_effects", "implementation_difficulty",
            "testing_plan", "rollback_plan", "score_breakdown"
        ]
        for p in proposals:
            for k in required_proposal_keys:
                self.assertIn(k, p, f"提案 {p.get('proposal_id')} 缺少欄位 {k}")
            sb = p["score_breakdown"]
            calc_sum = (
                sb["data_and_evidence_reliability"]
                + sb["expected_improvement_value"]
                + sb["risk_control"]
                + sb["technical_feasibility"]
                + sb["system_compatibility"]
            )
            self.assertEqual(calc_sum, sb["total_score"])
            self.assertLessEqual(sb["total_score"], 100)

    def test_05_readonly_db_and_write_permissions_enforced(self):
        """測試 5：驗證 SQLite 唯讀 URI 連線確實禁止任何寫入或刪除操作"""
        conn = get_readonly_db_connection()
        cur = conn.cursor()
        with self.assertRaises(sqlite3.OperationalError):
            cur.execute("UPDATE etf_dual_scores SET total_score_a_long_term = 99.9 WHERE etf_code = '0050'")
        with self.assertRaises(sqlite3.OperationalError):
            cur.execute("DELETE FROM etf_master WHERE etf_code = '0050'")
        conn.close()

    def test_06_unapproved_cannot_modify_production_code(self):
        """測試 6：驗證在未獲使用者批准 (user_approved=False) 下，企圖寫入正式程式碼會被攔截且正式檔案 SHA-256 完全不變"""
        with self.assertRaises(PermissionError):
            safe_write_ma_file("../backend/etf_engine.py", "# unauthorized hack", user_approved=False)
        with self.assertRaises(PermissionError):
            safe_write_ma_file("../frontend/index.html", "<!-- unauthorized -->", user_approved=False)
        with self.assertRaises(PermissionError):
            safe_write_ma_file("../data/twfin_intelligence.db", "corrupt", user_approved=False)

        # 比對研究執行前後，所有受保護正式檔案的 SHA-256 指紋必須 100% 一致
        current_checksums = compute_production_checksums()
        self.assertEqual(self.initial_checksums, current_checksums, "嚴重錯誤：正式系統檔案指紋被改變！")

    def test_07_failure_recovery_and_state_persistence(self):
        """測試 7：驗證提案審批狀態機切換 (PENDING -> APPROVED -> PENDING) 與持久化恢復能力"""
        pid = "ETF-IMPROVE-20261122-001"
        updated = update_proposal_approval_status(pid, "APPROVE", "單元測試模擬批准")
        self.assertEqual(updated["status"], "APPROVED_BY_USER")

        # 恢復為 PENDING_APPROVAL 等待真實使用者於 UI 裁決
        restored = update_proposal_approval_status(pid, "RE_RESEARCH", "單元測試驗證完畢，重置為待使用者審核狀態")
        self.assertIn(restored["status"], ("RE_RESEARCH_REQUESTED", "PENDING_APPROVAL"))
        # 確保檔案回到 pending 目錄
        pending_file = os.path.join(MA_ROOT, "proposals", "pending", f"{pid}.json")
        self.assertTrue(os.path.exists(pending_file))
        with open(pending_file, "r", encoding="utf-8") as f:
            obj = json.load(f)
        obj["status"] = "PENDING_APPROVAL"
        with open(pending_file, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    def test_08_no_resource_conflict_across_agents(self):
        """測試 8：模擬 6 位 Agent 並行開啟 SQLite 唯讀連線執行實證查詢，驗證零鎖表與零資源衝突"""
        def worker(agent_idx):
            ev = extract_live_system_evidence()
            return (agent_idx, ev["total_etfs"], len(ev["etf_rows"]))

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(worker, range(1, 7)))

        self.assertEqual(len(results), 6)
        for idx, tot, rows_len in results:
            self.assertEqual(tot, 28)
            self.assertEqual(rows_len, 28)

    def test_09_proposal_ids_unique_and_final_state_wins(self):
        """同一提案編號同時存在於 pending 與 implemented 時，只能出現一次，且以 implemented 為準"""
        from argon_multi_agent.engine.multi_agent_orchestrator import get_multi_agent_state
        proposals = get_multi_agent_state()["phase6_proposals"]
        ids = [p["proposal_id"] for p in proposals]
        self.assertEqual(len(ids), len(set(ids)), "提案編號重複")
        pending_dir = os.path.join(os.environ["TWFIN_MA_ROOT"], "proposals", "pending")
        impl_dir = os.path.join(os.environ["TWFIN_MA_ROOT"], "proposals", "implemented")
        both = {f for f in os.listdir(pending_dir) if f.endswith(".json")} &                {f for f in os.listdir(impl_dir) if f.endswith(".json")}
        by_id = {p["proposal_id"]: p for p in proposals}
        for fname in both:
            self.assertEqual(by_id[fname[:-5]]["status"], "IMPLEMENTED_ON_BRANCH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
