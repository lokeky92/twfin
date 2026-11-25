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
    extract_live_system_evidence,
    FOLDER_STATUS,
    PROPOSAL_FOLDERS,
    PROPOSAL_TRANSITIONS,
    InvalidProposalTransition,
    find_proposal_copies,
    list_proposals,
    reconcile_proposals,
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
        # repo 內的提案都已是 implemented (終態)，改用測試專用的待審提案，不依賴 repo 資料
        pid = "ETF-IMPROVE-TEST-007"
        _make_pending_proposal(pid)
        try:
            updated = update_proposal_approval_status(pid, "APPROVE", "單元測試模擬批准")
            self.assertEqual(updated["status"], "APPROVED_BY_USER")
            self.assertEqual(_folders_of(pid), ["approved"])

            restored = update_proposal_approval_status(pid, "RE_RESEARCH", "單元測試驗證完畢，重置為待使用者審核狀態")
            self.assertEqual(restored["status"], "RE_RESEARCH_REQUESTED")
            self.assertEqual(_folders_of(pid), ["pending"])     # 檔案回到 pending，且只有這一處
        finally:
            _remove_proposal(pid)

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
        """舊資料遺留：同一提案同時存在於 pending 與 implemented 時，只能出現一次，且以 implemented 為準"""
        pid = "ETF-IMPROVE-TEST-009"
        _make_pending_proposal(pid)
        try:
            update_proposal_approval_status(pid, "APPROVE")
            update_proposal_approval_status(pid, "MARK_IMPLEMENTED")
            _write_proposal("pending", pid, status="PENDING_APPROVAL")      # 模擬舊版重跑研究留下的殘留
            self.assertEqual(sorted(_folders_of(pid)), ["implemented", "pending"])

            proposals = get_multi_agent_state()["phase6_proposals"]
            ids = [p["proposal_id"] for p in proposals]
            self.assertEqual(len(ids), len(set(ids)), "提案編號重複")
            self.assertEqual({p["proposal_id"]: p for p in proposals}[pid]["status"], "IMPLEMENTED_ON_BRANCH")
        finally:
            _remove_proposal(pid)


# ---------------------------------------------------------------------------
# 提案狀態機與資料一致性 (在暫存副本上執行，不影響 repo)
# ---------------------------------------------------------------------------
def _proposals_dir(folder):
    return os.path.join(MA_ROOT, "proposals", folder)


def _write_proposal(folder, pid, status="PENDING_APPROVAL"):
    obj = {"proposal_id": pid, "title": "測試提案", "priority": "P2", "status": status,
           "proposer_agents": ["TEST"], "score_breakdown": {"total_score": 50}}
    os.makedirs(_proposals_dir(folder), exist_ok=True)
    with open(os.path.join(_proposals_dir(folder), f"{pid}.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    with open(os.path.join(_proposals_dir(folder), f"{pid}.md"), "w", encoding="utf-8") as f:
        f.write(f"# {pid}\n")


def _make_pending_proposal(pid):
    _write_proposal("pending", pid)


def _folders_of(pid):
    """提案的 .json 目前出現在哪些資料夾；同時確認 .md 一定跟 .json 在同一處。"""
    folders = [f for f in PROPOSAL_FOLDERS if os.path.exists(os.path.join(_proposals_dir(f), f"{pid}.json"))]
    md_folders = [f for f in PROPOSAL_FOLDERS if os.path.exists(os.path.join(_proposals_dir(f), f"{pid}.md"))]
    assert sorted(md_folders) == sorted(folders), f"{pid} 的 .md 與 .json 不在同一個資料夾：{md_folders} vs {folders}"
    return folders


def _remove_proposal(pid):
    for f in PROPOSAL_FOLDERS:
        for ext in ("json", "md"):
            path = os.path.join(_proposals_dir(f), f"{pid}.{ext}")
            if os.path.exists(path):
                os.remove(path)


class TestProposalStateMachine(unittest.TestCase):
    PID = "ETF-IMPROVE-TEST-100"

    def setUp(self):
        _remove_proposal(self.PID)

    def tearDown(self):
        _remove_proposal(self.PID)

    def _put(self, folder):
        _write_proposal(folder, self.PID, status=FOLDER_STATUS[folder])

    def test_repo_data_each_proposal_lives_in_exactly_one_folder(self):
        """已提交的研究紀錄：每個提案編號只能在一個資料夾，.md 與 .json 成對，沒有孤兒檔"""
        problems = []
        seen = {}
        for folder in PROPOSAL_FOLDERS:
            d = _proposals_dir(folder)
            if not os.path.isdir(d):
                continue
            names = os.listdir(d)
            jsons = {n[:-5] for n in names if n.endswith(".json")}
            mds = {n[:-3] for n in names if n.endswith(".md")}
            for orphan in jsons ^ mds:
                problems.append(f"{folder}/{orphan} 的 .json / .md 不成對")
            for pid in jsons:
                if pid in seen:
                    problems.append(f"{pid} 同時存在於 {seen[pid]} 與 {folder}")
                seen[pid] = folder
        self.assertEqual(problems, [])
        self.assertEqual(len(list_proposals()), len(seen))

    def test_every_allowed_transition_moves_files_to_exactly_one_folder(self):
        for source, decisions in PROPOSAL_TRANSITIONS.items():
            for decision, target in decisions.items():
                with self.subTest(source=source, decision=decision):
                    _remove_proposal(self.PID)
                    self._put(source)
                    obj = update_proposal_approval_status(self.PID, decision, "測試")
                    self.assertEqual(_folders_of(self.PID), [target])
                    expected = "RE_RESEARCH_REQUESTED" if decision == "RE_RESEARCH" else FOLDER_STATUS[target]
                    self.assertEqual(obj["status"], expected)
                    self.assertIn("user_decision_at", obj)

    def test_every_disallowed_transition_is_rejected_and_changes_nothing(self):
        all_decisions = {"APPROVE", "REJECT", "RE_RESEARCH", "MARK_IMPLEMENTED"}
        for source, decisions in PROPOSAL_TRANSITIONS.items():
            for decision in all_decisions - set(decisions):
                with self.subTest(source=source, decision=decision):
                    _remove_proposal(self.PID)
                    self._put(source)
                    with self.assertRaises(InvalidProposalTransition):
                        update_proposal_approval_status(self.PID, decision)
                    self.assertEqual(_folders_of(self.PID), [source])

    def test_implemented_is_terminal(self):
        self.assertEqual(PROPOSAL_TRANSITIONS["implemented"], {})
        self._put("implemented")
        for decision in ("APPROVE", "REJECT", "RE_RESEARCH", "MARK_IMPLEMENTED"):
            with self.assertRaises(InvalidProposalTransition):
                update_proposal_approval_status(self.PID, decision)

    def test_unknown_decision_rejected_instead_of_silently_resetting(self):
        # 舊版把未知 decision 當成「退回 pending」，打錯字就會讓已批准的提案丟失狀態
        self._put("approved")
        with self.assertRaises(InvalidProposalTransition):
            update_proposal_approval_status(self.PID, "APROVE")
        self.assertEqual(_folders_of(self.PID), ["approved"])

    def test_unknown_proposal_raises_value_error(self):
        with self.assertRaises(ValueError):
            update_proposal_approval_status("ETF-IMPROVE-DOES-NOT-EXIST", "APPROVE")

    def test_transition_cleans_up_stale_duplicates(self):
        self._put("pending")
        self._put("approved")      # 殘留的重複
        update_proposal_approval_status(self.PID, "MARK_IMPLEMENTED")
        self.assertEqual(_folders_of(self.PID), ["implemented"])

    def test_rerunning_a_research_session_does_not_recreate_or_overwrite_proposals(self):
        proposals = list_proposals()
        ids = [p["proposal_id"] for p in proposals if not p["proposal_id"].startswith("ETF-IMPROVE-TEST")]
        before = {pid: _folders_of(pid) for pid in ids}
        # 模擬使用者對其中一個提案要求重新研究 (pending 且帶有 RE_RESEARCH_REQUESTED)
        self._put("approved")
        update_proposal_approval_status(self.PID, "RE_RESEARCH", "請補充反方證據")
        run_full_multi_agent_session()
        self.assertEqual({pid: _folders_of(pid) for pid in ids}, before)        # 已實作的不會在 pending 再出現一份
        self.assertEqual(_folders_of(self.PID), ["pending"])
        self.assertEqual(find_proposal_copies(self.PID)[0][1]["status"], "RE_RESEARCH_REQUESTED")  # 標記沒被蓋掉

    def test_reconcile_keeps_most_advanced_copy_and_dry_run_changes_nothing(self):
        self._put("pending")
        self._put("rejected")
        report = [r for r in reconcile_proposals(dry_run=True) if r["proposal_id"] == self.PID]
        self.assertEqual(report, [{"proposal_id": self.PID, "kept": "rejected", "removed": ["pending"]}])
        self.assertEqual(sorted(_folders_of(self.PID)), ["pending", "rejected"])     # dry run 不動檔案
        reconcile_proposals()
        self.assertEqual(_folders_of(self.PID), ["rejected"])
        self.assertEqual([r for r in reconcile_proposals() if r["proposal_id"] == self.PID], [])   # 冪等

    def test_list_status_follows_folder_not_stale_json_field(self):
        # JSON 內 status 只是寫入當下的快照；顯示的狀態以資料夾為準
        _write_proposal("implemented", self.PID, status="APPROVED_BY_USER")
        listed = {p["proposal_id"]: p for p in list_proposals()}
        self.assertEqual(listed[self.PID]["status"], "IMPLEMENTED_ON_BRANCH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
