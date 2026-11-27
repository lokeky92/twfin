"""
API 伺服器整合測試：使用暫存 SQLite (TWFIN_DB_PATH) 與暫存多 Agent 目錄 (TWFIN_MA_ROOT)，
不連外網、不改動 repo 內的資料庫或研究紀錄。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="twfin_test_")
os.environ["TWFIN_DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["TWFIN_MA_ROOT"] = os.path.join(_TMP, "argon_multi_agent")
shutil.copytree(os.path.join(ROOT, "argon_multi_agent"), os.environ["TWFIN_MA_ROOT"])
os.environ["TWFIN_ADMIN_TOKEN"] = "test-token"

sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, ROOT)

import server  # noqa: E402
from export_standalone import build_bundle  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402
from seed_and_engine import seed_and_compute_all  # noqa: E402


class TestServerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_and_compute_all()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.TWFinRequestHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(_TMP, ignore_errors=True)

    def _post(self, path, body, token="test-token"):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Admin-Token"] = token
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=30) as resp:
            return resp.status, resp.read()

    def test_dashboard_and_provenance(self):
        status, body = self._get("/api/dashboard")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("data_provenance", data)
        self.assertIn("multi_agent_center", data)
        # 只有種子資料、沒有即時擷取紀錄時必須明確標示
        self.assertFalse(data["data_provenance"]["live_data_available"])

    def test_dashboard_has_live_home_pulse_that_degrades_without_live_data(self):
        """首頁 Q1~Q6 由即時資料產生；只有種子資料時每張卡都要降級成「資料不足」，不可沿用手寫敘事。"""
        _, body = self._get("/api/dashboard")
        pulse = json.loads(body)["home_pulse"]
        self.assertEqual(len(pulse["items"]), 6)
        for item in pulse["items"]:
            for key in ("q", "a", "sub", "color", "q6", "basis"):
                self.assertIn(key, item)
            self.assertEqual(len(item["q6"]), 6)
        self.assertTrue(all("資料不足" in it["a"] for it in pulse["items"]))

    def test_static_assets_served(self):
        # index.html 引用的每一支腳本都必須能被伺服器取得 (拆檔後漏列或打錯檔名會在這裡失敗)
        import re
        _, html = self._get("/")
        scripts = re.findall(r'<script src="([^"]+)"></script>', html.decode("utf-8"))
        self.assertGreater(len(scripts), 1)
        for rel in scripts:
            status, body = self._get("/" + rel)
            self.assertEqual(status, 200, rel)
            self.assertGreater(len(body), 0, rel)
        status, _ = self._get("/assets/app.css")
        self.assertEqual(status, 200)

    def _raw(self, path, headers=None):
        """回傳 (status, headers, body)；不自動解壓縮，304 也當成一般回應處理。"""
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_dashboard_gzip_when_accepted(self):
        import gzip
        status, headers, body = self._raw("/api/dashboard", {"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        self.assertEqual(headers.get("Vary"), "Accept-Encoding")
        data = json.loads(gzip.decompress(body))
        self.assertIn("data_provenance", data)
        # 壓縮後要明顯小於原始大小，否則代表沒有真的壓縮
        raw_status, raw_headers, raw_body = self._raw("/api/dashboard")
        self.assertIsNone(raw_headers.get("Content-Encoding"))
        self.assertLess(len(body), len(raw_body) / 2)

    def test_etag_revalidation_returns_304(self):
        _, headers, _ = self._raw("/api/dashboard")
        etag = headers.get("ETag")
        self.assertTrue(etag)
        self.assertEqual(headers.get("Cache-Control"), "no-cache")
        status, h2, body = self._raw("/api/dashboard", {"If-None-Match": etag})
        self.assertEqual(status, 304)
        self.assertEqual(body, b"")
        # 內容不同的 ETag 必須拿到完整內容
        status, _, body = self._raw("/api/dashboard", {"If-None-Match": '"stale"'})
        self.assertEqual(status, 200)
        self.assertGreater(len(body), 1000)

    def test_static_assets_compressed_with_etag(self):
        import gzip
        status, headers, body = self._raw("/assets/js/01-core.js", {"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        self.assertIn("javascript", headers.get("Content-Type", ""))
        self.assertIn(b"function esc", gzip.decompress(body))
        status, _, _ = self._raw("/assets/js/01-core.js", {"If-None-Match": headers.get("ETag")})
        self.assertEqual(status, 304)

    def test_missing_file_still_404_and_no_path_escape(self):
        status, _, _ = self._raw("/assets/js/does-not-exist.js")
        self.assertEqual(status, 404)
        status, _, body = self._raw("/..%2f..%2fREADME.md")
        self.assertNotEqual(status, 200)

    def test_health_reports_uptime(self):
        status, _, body = self._raw("/api/health")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertIn("uptime_sec", data)
        self.assertIn("dashboard_cache_ready", data)

    def _seed_pending_proposal(self, pid):
        root = os.path.join(os.environ["TWFIN_MA_ROOT"], "proposals", "pending")
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump({"proposal_id": pid, "title": "t", "priority": "P2", "status": "PENDING_APPROVAL",
                       "proposer_agents": ["T"], "score_breakdown": {"total_score": 1}}, f)
        with open(os.path.join(root, f"{pid}.md"), "w", encoding="utf-8") as f:
            f.write("# t\n")

    def test_proposal_decision_rejects_invalid_transition_with_400(self):
        # repo 內的提案都已 implemented (終態)，不可再被批准
        status, body = self._post("/api/multi_agent/proposal_decision",
                                  {"proposal_id": "ETF-IMPROVE-20261122-001", "decision": "APPROVE"})
        self.assertEqual(status, 400)
        self.assertIn("不允許", body["message"])
        status, body = self._post("/api/multi_agent/proposal_decision",
                                  {"proposal_id": "ETF-IMPROVE-20261122-001", "decision": "NOT_A_DECISION"})
        self.assertEqual(status, 400)

    def test_batch_decision_applies_where_allowed_and_reports_skipped(self):
        pid = "ETF-IMPROVE-TEST-BATCH"
        self._seed_pending_proposal(pid)
        status, body = self._post("/api/multi_agent/proposal_decision", {"proposal_id": "ALL", "decision": "APPROVE"})
        self.assertEqual(status, 200)
        res = body["proposal"]
        self.assertEqual(res["applied"], [pid])                       # 只有待審的那個被批准
        skipped_ids = {s["proposal_id"] for s in res["skipped"]}
        self.assertIn("ETF-IMPROVE-20261122-001", skipped_ids)        # 已實作的被略過，不會被改回 approved
        by_id = {p["proposal_id"]: p["status"] for p in body["multi_agent_center"]["phase6_proposals"]}
        self.assertEqual(by_id[pid], "APPROVED_BY_USER")
        self.assertEqual(by_id["ETF-IMPROVE-20261122-001"], "IMPLEMENTED_ON_BRANCH")

    def test_split_export_writes_app_shell_and_data_json(self):
        import export_standalone as ex
        tmp = tempfile.mkdtemp(prefix="twfin_docs_")
        saved = (ex.DOCS_DIR, ex.DOCS_INDEX_HTML, ex.DOCS_DATA_JSON)
        ex.DOCS_DIR, ex.DOCS_INDEX_HTML, ex.DOCS_DATA_JSON = tmp, os.path.join(tmp, "index.html"), os.path.join(tmp, "data.json")
        try:
            ex.export_standalone()
            with open(ex.DOCS_INDEX_HTML, encoding="utf-8") as f:
                shell = f.read()
            with open(ex.DOCS_DATA_JSON, encoding="utf-8") as f:
                data_text = f.read()
        finally:
            ex.DOCS_DIR, ex.DOCS_INDEX_HTML, ex.DOCS_DATA_JSON = saved
            shutil.rmtree(tmp, ignore_errors=True)
        # index.html：只有程式，不含資料，且保留插入點
        self.assertNotIn('id="twfin-snapshot"', shell)
        self.assertIn("<!-- twfin-snapshot-slot -->", shell)
        self.assertNotIn('src="assets/', shell)
        self.assertLess(len(shell), 700 * 1024)
        # data.json：合法 JSON、縮排輸出 (git diff 以行為單位)、結尾有換行
        data = json.loads(data_text)
        self.assertIn("data_provenance", data)
        self.assertGreater(data_text.count("\n"), 1000)
        self.assertTrue(data_text.endswith("\n"))
        # 兩者組合 = 單檔離線版
        from snapshot_bundle import inline_snapshot
        single = inline_snapshot(shell, data_text)
        self.assertIn('id="twfin-snapshot"', single)
        self.assertNotIn("twfin-snapshot-slot", single)
        embedded = single.split('id="twfin-snapshot" type="application/json">')[1].split("</script>")[0]
        self.assertEqual(json.loads(embedded.replace("<\\/", "</")), data)

    def test_inline_snapshot_edge_cases(self):
        from snapshot_bundle import SNAPSHOT_SLOT, inline_snapshot
        shell = f"<body>{SNAPSHOT_SLOT}<script>app()</script></body>"
        self.assertEqual(inline_snapshot(shell, None), shell)                       # 沒有資料：原樣
        legacy = '<body><script id="twfin-snapshot" type="application/json">{}</script></body>'
        self.assertEqual(inline_snapshot(legacy, '{"a":1}'), legacy)                # 舊格式單檔：原樣，不重複內嵌
        out = inline_snapshot(shell, {"x": "</script><script>alert(1)</script>"})
        self.assertNotIn("</script><script>alert(1)", out)                          # 資料中的 </script> 已跳脫
        self.assertEqual(out.count('id="twfin-snapshot"'), 1)
        self.assertLess(out.index("twfin-snapshot"), out.index("app()"))            # 快照在程式之前

    def test_server_composes_bundle_from_shell_and_data_json(self):
        from snapshot_bundle import SNAPSHOT_SLOT
        tmp = tempfile.mkdtemp(prefix="twfin_bundle_")
        shell_p, data_p = os.path.join(tmp, "index.html"), os.path.join(tmp, "data.json")
        with open(shell_p, "w", encoding="utf-8") as f:
            f.write(f"<html>{SNAPSHOT_SLOT}<script>app()</script></html>")
        with open(data_p, "w", encoding="utf-8") as f:
            f.write('{"generated_at": "v1"}')
        saved = (server.BUNDLE_PATH, server.DATA_JSON_PATH)
        server.BUNDLE_PATH, server.DATA_JSON_PATH = shell_p, data_p
        server._bundle_cache["key"] = None
        os.environ["TWFIN_SERVE_BUNDLE"] = "1"
        try:
            _, _, body = self._raw("/")
            self.assertIn(b'"generated_at":"v1"', body)
            self.assertNotIn(SNAPSHOT_SLOT.encode(), body)
            # data.json 更新後 (大小不同) 下一次請求就會組出新內容；ETag 也跟著變
            _, h1, _ = self._raw("/")
            with open(data_p, "w", encoding="utf-8") as f:
                f.write('{"generated_at": "version-2"}')
            _, h2, body2 = self._raw("/")
            self.assertIn(b'"generated_at":"version-2"', body2)
            self.assertNotEqual(h1.get("ETag"), h2.get("ETag"))
            # 沒有 data.json (例如舊部署)：原樣提供 index.html，不報錯
            os.remove(data_p)
            status, _, body3 = self._raw("/")
            self.assertEqual(status, 200)
            self.assertIn(SNAPSHOT_SLOT.encode(), body3)
        finally:
            os.environ.pop("TWFIN_SERVE_BUNDLE", None)
            server.BUNDLE_PATH, server.DATA_JSON_PATH = saved
            server._bundle_cache["key"] = None
            shutil.rmtree(tmp, ignore_errors=True)

    def test_head_requests_supported_without_body(self):
        # 保活監控 (UptimeRobot 等) 預設送 HEAD；必須回 200、有 Content-Length、且不能夾帶內容
        for path in ("/api/health", "/api/dashboard", "/"):
            req = urllib.request.Request(self.base + path, method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.assertEqual(resp.status, 200, path)
                self.assertEqual(resp.read(), b"", path)
                self.assertTrue(resp.headers.get("Content-Length"), path)

    def test_bundle_served_at_root_only_when_enabled(self):
        status, _, body = self._raw("/")
        self.assertIn(b"assets/js/01-core.js", body)           # 預設：開發用的多檔版
        self.assertNotIn(b'id="twfin-snapshot"', body)
        os.environ["TWFIN_SERVE_BUNDLE"] = "1"
        try:
            status, headers, body = self._raw("/")
            self.assertEqual(status, 200)
            self.assertIn(b'id="twfin-snapshot"', body)         # 啟用：單檔、已內嵌資料快照
            self.assertNotIn(b'src="assets/js/', body)
        finally:
            os.environ.pop("TWFIN_SERVE_BUNDLE", None)

    def test_post_responses_never_cached(self):
        status, body = self._post("/api/rescore", {}, token=None)
        self.assertEqual(status, 401)
        req = urllib.request.Request(self.base + "/api/rescore", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertIn("no-store", ctx.exception.headers.get("Cache-Control", ""))

    def test_write_requires_token(self):
        status, body = self._post("/api/rescore", {}, token=None)
        self.assertEqual(status, 401)
        status, _ = self._post("/api/rescore", {}, token="wrong")
        self.assertEqual(status, 401)

    def test_rescore_creates_unique_versions(self):
        w = {"capital_flow": 0.3, "fundamentals": 0.3, "future_growth": 0.2, "institutional": 0.1,
             "valuation": 0.1, "reason": "<script>alert(1)</script>"}
        s1, b1 = self._post("/api/rescore", w)
        s2, b2 = self._post("/api/rescore", w)
        self.assertEqual((s1, s2), (200, 200))
        self.assertNotEqual(b1["new_version"], b2["new_version"])
        self.assertEqual(b2["dashboard"]["active_model"]["version_id"], b2["new_version"])

    def test_rescore_rejects_bad_weights(self):
        status, body = self._post("/api/rescore", {"capital_flow": 0.9})
        self.assertEqual(status, 400)
        self.assertIn("權重總和", body["message"])

    def test_threshold_validation(self):
        status, _ = self._post("/api/update_governance",
                               {"action_type": "THRESHOLDS", "lvl4_min": 50, "lvl3_min": 72, "lvl2_min": 62})
        self.assertEqual(status, 400)
        status, body = self._post("/api/update_governance",
                                  {"action_type": "THRESHOLDS", "lvl4_min": 85, "lvl3_min": 75, "lvl2_min": 65,
                                   "lvlR_cap_max": 40, "reason": "test"})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["thresholds"]["numeric"]["lvl4_min"], 85.0)

    def test_sensitivity_payloads_follow_governance_thresholds(self):
        def dashboard():
            return json.loads(self._get("/api/dashboard")[1])
        d = dashboard()
        self.assertTrue(d["weight_sensitivity"]["available"])
        self.assertTrue(d["threshold_sensitivity"]["available"])
        try:
            status, _ = self._post("/api/update_governance",
                                   {"action_type": "THRESHOLDS", "lvl4_min": 88, "lvl3_min": 78, "lvl2_min": 66,
                                    "lvlR_cap_max": 42, "reason": "sensitivity test"})
            self.assertEqual(status, 200)
            d = dashboard()
            self.assertEqual(d["threshold_sensitivity"]["thresholds"]["lvl4_min"], 88.0)
            # 兩種敏感度分析的「目前等級」必須一致 (都以生效中的權重與門檻計算)
            ws = {x["industry_id"]: x["base_level"] for x in d["weight_sensitivity"]["industries"]}
            ts = {x["industry_id"]: x["base_level"] for x in d["threshold_sensitivity"]["industries"]}
            self.assertEqual(ws, ts)
        finally:
            self._post("/api/update_governance",
                       {"action_type": "THRESHOLDS", "lvl4_min": 80, "lvl3_min": 72, "lvl2_min": 62,
                        "lvlR_cap_max": 45, "reason": "restore defaults"})

    def test_company_mapping_validates_input(self):
        status, body = self._post("/api/update_governance",
                                  {"action_type": "COMPANY_MAPPING", "company_code": "2330",
                                   "mapped_industry_id": "IND_DOES_NOT_EXIST"})
        self.assertEqual(status, 400)

    def test_invalid_json_body(self):
        req = urllib.request.Request(self.base + "/api/rescore", data=b"{not json",
                                     headers={"X-Admin-Token": "test-token"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    def test_export_bundle_is_single_file_and_escapes_script(self):
        payload = server.get_dashboard_payload()
        payload["injection_probe"] = "</script><script>alert(1)</script>"
        html = build_bundle(payload)
        self.assertNotIn('href="assets/app.css"', html)
        self.assertNotIn('src="assets/', html)
        self.assertIn('id="twfin-snapshot"', html)
        self.assertNotIn("</script><script>alert(1)", html)


if __name__ == "__main__":
    unittest.main()
