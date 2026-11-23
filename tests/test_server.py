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

    def test_static_assets_served(self):
        status, _ = self._get("/assets/app.js")
        self.assertEqual(status, 200)

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
        self.assertNotIn('src="assets/app.js"', html)
        self.assertIn('id="twfin-snapshot"', html)
        self.assertNotIn("</script><script>alert(1)", html)


if __name__ == "__main__":
    unittest.main()
