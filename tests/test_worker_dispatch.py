"""
Cloudflare Worker 的準時排程觸發器測試：把 build_worker.py 的範本實際產生成 worker.mjs，
用 Node 搭配假的 fetch 驗證 GitHub workflow_dispatch 的呼叫內容、重試與失敗行為。(沒有 node 時略過)
"""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DRIVER = r"""
import { pathToFileURL } from 'node:url';
const mod = await import(pathToFileURL(process.argv[2]).href);
const { dispatchSync } = mod;
const logs = [];
const origLog = console.log, origErr = console.error;
console.log = (...a) => logs.push(a.join(' '));
console.error = (...a) => logs.push(a.join(' '));

const ENV = { GH_DISPATCH_TOKEN: 'SECRET-TOKEN-123', GH_REPO: 'owner/repo' };
const res = (status) => ({ status });
function makeFetch(seq) {
  const calls = [];
  const f = async (url, init) => {
    calls.push({ url, init });
    const b = seq[Math.min(calls.length - 1, seq.length - 1)];
    if (b === 'net') throw new Error('network down');
    return res(b);
  };
  f.calls = calls;
  return f;
}
const sleeps = [];
const sleep = async (ms) => { sleeps.push(ms); };
const out = {};

// 1. 未設定權杖 -> 不呼叫 fetch
let f = makeFetch([204]);
out.noToken = { r: await dispatchSync({ GH_REPO: 'owner/repo' }, f, sleep), calls: f.calls.length };
out.noRepo = { r: await dispatchSync({ GH_DISPATCH_TOKEN: 'x' }, f, sleep), calls: f.calls.length };

// 2. 成功：檢查請求內容
f = makeFetch([204]);
out.ok = { r: await dispatchSync(ENV, f, sleep), calls: f.calls.length };
const c = f.calls[0];
out.request = { url: c.url, method: c.init.method, body: c.init.body,
  auth: c.init.headers.Authorization, accept: c.init.headers.Accept, ua: c.init.headers['User-Agent'],
  apiVersion: c.init.headers['X-GitHub-Api-Version'] };

// 3. 自訂 workflow / ref
f = makeFetch([204]);
await dispatchSync({ ...ENV, GH_WORKFLOW: 'other.yml', GH_REF: 'dev' }, f, sleep);
out.custom = { url: f.calls[0].url, body: f.calls[0].init.body };

// 4. 4xx (權杖錯誤) 不重試；429 要重試
f = makeFetch([401]);
out.unauthorized = { r: await dispatchSync(ENV, f, sleep), calls: f.calls.length };
sleeps.length = 0;
f = makeFetch([429, 204]);
out.rateLimited = { r: await dispatchSync(ENV, f, sleep), calls: f.calls.length };

// 5. 5xx 重試，第 3 次成功；退避時間遞增
sleeps.length = 0;
f = makeFetch([500, 502, 204]);
out.retry = { r: await dispatchSync(ENV, f, sleep), calls: f.calls.length, sleeps: sleeps.slice() };

// 6. 一直失敗 (網路錯誤) -> 3 次後放棄
sleeps.length = 0;
f = makeFetch(['net']);
out.allFail = { r: await dispatchSync(ENV, f, sleep), calls: f.calls.length, sleeps: sleeps.slice() };

// 7. scheduled(): 成功 resolve、權限錯誤 reject、未設定時 resolve
async function runScheduled(env, status) {
  const orig = globalThis.fetch;
  globalThis.fetch = async () => res(status);
  let p = null;
  try {
    await mod.default.scheduled({}, env, { waitUntil: (x) => { p = x; } });
    await p;
    return 'resolved';
  } catch (e) { return 'rejected: ' + e.message; }
  finally { globalThis.fetch = orig; }
}
out.scheduledOk = await runScheduled(ENV, 204);
out.scheduledForbidden = await runScheduled(ENV, 403);
out.scheduledNoConfig = await runScheduled({}, 204);

// 8. 既有的私有存取 fetch 處理器仍可用 (未設定密碼時回 503)
const r = await mod.default.fetch(new Request('https://example.com/'), {});
out.fetchHandlerStatus = r.status;

// 9. 權杖不可出現在任何記錄中
out.tokenLeakedInLogs = logs.some((l) => l.includes('SECRET-TOKEN-123'));
console.log = origLog; console.error = origErr;
console.log(JSON.stringify(out));
"""


def _render_worker(tmpdir):
    spec = importlib.util.spec_from_file_location("build_worker", os.path.join(ROOT, "cloudflare", "build_worker.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    path = os.path.join(tmpdir, "worker.mjs")
    with open(path, "w", encoding="utf-8") as f:
        f.write(mod.WORKER_TEMPLATE.replace("__HTML_GZ_B64__", ""))
    return path


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過 Worker 測試")
class TestWorkerDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="twfin_worker_")
        worker = _render_worker(cls.tmp)
        driver = os.path.join(cls.tmp, "driver.mjs")
        with open(driver, "w", encoding="utf-8") as f:
            f.write(DRIVER)
        r = subprocess.run(["node", driver, worker], capture_output=True, text=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_skips_quietly_without_configuration(self):
        self.assertEqual(self.o["noToken"], {"r": {"ok": False, "skipped": True}, "calls": 0})
        self.assertEqual(self.o["noRepo"]["calls"], 0)

    def test_dispatch_request_is_correct(self):
        self.assertTrue(self.o["ok"]["r"]["ok"])
        rq = self.o["request"]
        self.assertEqual(rq["url"], "https://api.github.com/repos/owner/repo/actions/workflows/deploy_and_update.yml/dispatches")
        self.assertEqual(rq["method"], "POST")
        self.assertEqual(json.loads(rq["body"]), {"ref": "main"})
        self.assertEqual(rq["auth"], "Bearer SECRET-TOKEN-123")
        self.assertEqual(rq["accept"], "application/vnd.github+json")
        self.assertTrue(rq["ua"])                    # GitHub API 要求必須有 User-Agent
        self.assertTrue(rq["apiVersion"])

    def test_workflow_and_ref_overridable(self):
        self.assertIn("/workflows/other.yml/dispatches", self.o["custom"]["url"])
        self.assertEqual(json.loads(self.o["custom"]["body"]), {"ref": "dev"})

    def test_client_errors_are_not_retried_but_rate_limit_is(self):
        self.assertEqual(self.o["unauthorized"]["calls"], 1)
        self.assertFalse(self.o["unauthorized"]["r"]["ok"])
        self.assertEqual(self.o["unauthorized"]["r"]["status"], 401)
        self.assertEqual(self.o["rateLimited"]["calls"], 2)
        self.assertTrue(self.o["rateLimited"]["r"]["ok"])

    def test_server_errors_retry_with_growing_backoff(self):
        self.assertEqual(self.o["retry"]["calls"], 3)
        self.assertTrue(self.o["retry"]["r"]["ok"])
        self.assertEqual(self.o["retry"]["sleeps"], [2000, 4000])

    def test_gives_up_after_three_attempts(self):
        self.assertEqual(self.o["allFail"]["calls"], 3)
        self.assertFalse(self.o["allFail"]["r"]["ok"])
        self.assertEqual(self.o["allFail"]["sleeps"], [2000, 4000])

    def test_scheduled_handler_surfaces_failures(self):
        self.assertEqual(self.o["scheduledOk"], "resolved")
        self.assertTrue(self.o["scheduledForbidden"].startswith("rejected"))   # 讓 Cloudflare 後台顯示失敗
        self.assertEqual(self.o["scheduledNoConfig"], "resolved")              # 未設定不算錯誤

    def test_existing_private_gate_still_works(self):
        self.assertEqual(self.o["fetchHandlerStatus"], 503)

    def test_token_never_logged(self):
        self.assertFalse(self.o["tokenLeakedInLogs"])


class TestWorkerBuildComposesSingleFile(unittest.TestCase):
    """拆分部署後 docs/index.html 只有程式；Worker 只提供一個頁面，所以建置時要把 data.json 內嵌回去"""

    def _load_build_worker(self):
        spec = importlib.util.spec_from_file_location("build_worker_mod", os.path.join(ROOT, "cloudflare", "build_worker.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_compose_inlines_data_json_and_handles_legacy_single_file(self):
        from pathlib import Path
        bw = self._load_build_worker()
        tmp = Path(tempfile.mkdtemp(prefix="twfin_bw_"))
        try:
            bw.DOCS_HTML, bw.DOCS_DATA = tmp / "index.html", tmp / "data.json"
            bw.DOCS_HTML.write_text("<html><!-- twfin-snapshot-slot --><script>app()</script></html>", encoding="utf-8")
            bw.DOCS_DATA.write_text('{"generated_at": "2026-11-26"}', encoding="utf-8")
            html = bw.compose_html().decode("utf-8")
            self.assertIn('id="twfin-snapshot"', html)
            self.assertIn('"generated_at":"2026-11-26"', html)
            self.assertNotIn("twfin-snapshot-slot", html)

            # 舊格式 (資料已內嵌、沒有 data.json)：原樣使用
            legacy = '<html><script id="twfin-snapshot" type="application/json">{"a":1}</script></html>'
            bw.DOCS_HTML.write_text(legacy, encoding="utf-8")
            bw.DOCS_DATA.unlink()
            self.assertEqual(bw.compose_html().decode("utf-8"), legacy)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestWranglerConfig(unittest.TestCase):
    def test_cron_matches_intended_times_and_no_secret_in_file(self):
        with open(os.path.join(ROOT, "cloudflare", "wrangler.toml"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('"30 8 * * MON-FRI"', text)
        self.assertIn('"0 12 * * MON-FRI"', text)
        self.assertNotRegex(text, r"(?m)^\s*GH_DISPATCH_TOKEN\s*=")   # 機密不可寫進版本控制的檔案


if __name__ == "__main__":
    unittest.main()
