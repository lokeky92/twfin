"""
前端腳本測試：
1. 匯出功能的 CSV 純函式 (需要 node，沒有安裝時略過)：UTF-8 BOM、跳脫、公式注入防護
2. index.html 的 inline 事件處理器 (onclick="foo()") 所呼叫的函式，必須在 assets/js/*.js 中有定義
   (拆檔或改名後漏掉函式，會在這裡而不是使用者按下按鈕時才發現)
"""
import glob
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "frontend", "assets", "js")

DRIVER = r"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync(process.argv[1], 'utf8');
const ctx = { STATE: { generated_at: '2026-11-25 22:15:39 (UTC+8)' }, console };
vm.createContext(ctx);
vm.runInContext(code + ';this.__x = { csvCell, buildCsv, exportFilename };', ctx);
const x = ctx.__x;
const out = {
  formula: x.csvCell('=1+1'), plus: x.csvCell('+cmd'), minusText: x.csvCell('-2+3'), at: x.csvCell('@SUM(A1)'),
  negNumber: x.csvCell(-5), zero: x.csvCell(0), nul: x.csvCell(null), nan: x.csvCell(NaN),
  comma: x.csvCell('a,b'), quote: x.csvCell('say "hi"'), newline: x.csvCell('a\nb'), trim: x.csvCell('  x '),
  csv: x.buildCsv([{ label: '名稱', value: r => r.n }, { label: '分數', value: r => r.s }], [{ n: '台積電', s: 88.4 }, { n: '=HYPERLINK("x")', s: null }]),
  fname: x.exportFilename('ranking', 'csv'),
};
ctx.STATE = {};
out.fnameNoDate = vm.runInContext('exportFilename("ranking", "csv")', ctx);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過前端 CSV 測試")
class TestExportCsv(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", DRIVER, os.path.join(JS_DIR, "20-export.js")],
                           capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.out = json.loads(r.stdout)

    def test_formula_injection_neutralised(self):
        self.assertEqual(self.out["formula"], "'=1+1")
        self.assertEqual(self.out["plus"], "'+cmd")
        self.assertEqual(self.out["minusText"], "'-2+3")
        self.assertEqual(self.out["at"], "'@SUM(A1)")

    def test_numbers_stay_numeric(self):
        self.assertEqual(self.out["negNumber"], "-5")   # 數字不能被加上單引號
        self.assertEqual(self.out["zero"], "0")
        self.assertEqual(self.out["nul"], "")
        self.assertEqual(self.out["nan"], "")

    def test_quoting_and_whitespace(self):
        self.assertEqual(self.out["comma"], '"a,b"')
        self.assertEqual(self.out["quote"], '"say ""hi"""')
        self.assertEqual(self.out["newline"], "a b")
        self.assertEqual(self.out["trim"], "x")

    def test_build_csv_bom_crlf_and_rows(self):
        csv = self.out["csv"]
        self.assertTrue(csv.startswith("﻿"))
        lines = csv.lstrip("﻿").split("\r\n")
        self.assertEqual(lines[0], "名稱,分數")
        self.assertEqual(lines[1], "台積電,88.4")
        self.assertEqual(lines[2], "\"'=HYPERLINK(\"\"x\"\")\",")   # 公式被中和，且含引號所以整格加引號
        self.assertEqual(lines[3], "")                            # 結尾換行

    def test_filename_uses_data_date(self):
        self.assertEqual(self.out["fname"], "twfin_ranking_20261125.csv")
        self.assertEqual(self.out["fnameNoDate"], "twfin_ranking_export.csv")


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過前端載入流程測試")
class TestDashboardLoadFlow(unittest.TestCase):
    """冷啟動 / 離線 / 純靜態託管的資料載入行為 (以假的 fetch 在 Node 內執行 03-navigation.js)"""

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", os.path.join(ROOT, "tests", "frontend_load_driver.js"), ROOT],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.s = json.loads(r.stdout)

    def test_file_protocol_uses_snapshot_without_any_request(self):
        s = self.s["file"]
        self.assertEqual((s["calls"], s["renders"], s["stateGen"]), (0, 1, "SNAPSHOT"))
        self.assertFalse(s["bannerShown"])

    def test_first_paint_does_not_wait_for_api(self):
        # 有內嵌快照時一定先 renderAll 一次 (第一個畫面)，API 是之後才補上的
        for name in ("sameData", "changedData", "wakesOnThird"):
            self.assertGreaterEqual(self.s[name]["renders"], 1, name)

    def test_unchanged_data_does_not_rerender_but_adopts_api_state(self):
        s = self.s["sameData"]
        self.assertEqual(s["renders"], 1)
        self.assertEqual(s["stateGen"], "API-SAME")
        self.assertEqual(s["mode"], "live")
        self.assertFalse(s["bannerShown"])

    def test_changed_data_rerenders_once(self):
        s = self.s["changedData"]
        self.assertEqual(s["renders"], 2)
        self.assertEqual(s["stateGen"], "API-CHANGED")

    def test_static_hosting_does_not_retry_and_shows_dismissible_note(self):
        for name in ("static404", "staticHtml200"):
            s = self.s[name]
            self.assertEqual(s["calls"], 1, name)        # 404 或回傳 HTML = 沒有 API，不必重試
            self.assertEqual(s["reason"], "no-api", name)
            self.assertTrue(s["bannerShown"], name)
            self.assertIn("雲端快照模式", s["banner"])
            self.assertIn("dismissApiBanner", s["banner"])
        self.assertFalse(self.s["staticDismissed"]["bannerShown"])   # 使用者關閉後不再顯示

    def test_unreachable_server_retries_three_times_then_offers_retry(self):
        s = self.s["unreachable"]
        self.assertEqual(s["calls"], 3)
        self.assertEqual(s["reason"], "unreachable")
        self.assertIn("連不上伺服器", s["banner"])
        self.assertIn("retryLoadDashboard", s["banner"])
        self.assertEqual(s["stateGen"], "SNAPSHOT")      # 仍保有快照畫面

    def test_server_waking_up_succeeds_on_third_attempt(self):
        s = self.s["wakesOnThird"]
        self.assertEqual(s["calls"], 3)
        self.assertEqual(s["mode"], "live")
        self.assertEqual(s["renders"], 2)
        self.assertFalse(s["bannerShown"])

    def test_without_snapshot_waits_for_api_and_reports_failure(self):
        ok = self.s["noSnapshotOk"]
        self.assertEqual((ok["renders"], ok["mode"]), (1, "live"))
        down = self.s["noSnapshotDown"]
        self.assertEqual(down["renders"], 0)
        self.assertTrue(down["bannerShown"])
        self.assertIn("無法連線到伺服器", down["banner"])
        self.assertIn("retryLoadDashboard", down["banner"])


PARITY_DRIVER = r"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync(process.argv[1], 'utf8');
const ctx = { console, document: { getElementById: () => null }, localStorage: {}, STATE: null };
vm.createContext(ctx);
vm.runInContext(code + ';this.__f = nextProposalStatus;', ctx);
const statuses = ['PENDING_APPROVAL', 'RE_RESEARCH_REQUESTED', 'APPROVED_BY_USER', 'REJECTED_BY_USER', 'IMPLEMENTED_ON_BRANCH'];
const decisions = ['APPROVE', 'REJECT', 'RE_RESEARCH', 'MARK_IMPLEMENTED', 'BOGUS'];
const out = {};
for (const s of statuses) for (const d of decisions) out[s + '|' + d] = ctx.__f(s, d);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過前端狀態機對照測試")
class TestProposalStateMachineParity(unittest.TestCase):
    """前端 (離線模式) 的提案狀態機必須與後端 PROPOSAL_TRANSITIONS 完全一致，否則兩邊會對同一操作給出不同結果"""

    def test_frontend_matches_backend_transitions(self):
        import sys
        sys.path.insert(0, ROOT)
        from argon_multi_agent.engine.multi_agent_orchestrator import FOLDER_STATUS, PROPOSAL_TRANSITIONS

        r = subprocess.run(["node", "-e", PARITY_DRIVER, os.path.join(JS_DIR, "16-multi-agent.js")],
                           capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        js = json.loads(r.stdout)

        # 前端以 status 為鍵；pending 資料夾對應兩種 status (一般待審 / 已要求重新研究)
        statuses_of_folder = {
            "pending": ["PENDING_APPROVAL", "RE_RESEARCH_REQUESTED"], "approved": ["APPROVED_BY_USER"],
            "rejected": ["REJECTED_BY_USER"], "implemented": ["IMPLEMENTED_ON_BRANCH"],
        }
        decisions = ["APPROVE", "REJECT", "RE_RESEARCH", "MARK_IMPLEMENTED", "BOGUS"]
        for folder, statuses in statuses_of_folder.items():
            for status in statuses:
                for decision in decisions:
                    target = PROPOSAL_TRANSITIONS[folder].get(decision)
                    expected = None if target is None else (
                        "RE_RESEARCH_REQUESTED" if decision == "RE_RESEARCH" else FOLDER_STATUS[target])
                    self.assertEqual(js[f"{status}|{decision}"], expected, f"{status} + {decision}")


class TestInlineHandlersDefined(unittest.TestCase):
    ALLOWED = {"alert", "confirm", "parseInt", "parseFloat", "String", "Number", "Boolean"}

    def test_every_inline_handler_function_exists(self):
        with open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8") as f:
            html = f.read()
        js = ""
        for path in sorted(glob.glob(os.path.join(JS_DIR, "*.js"))):
            with open(path, encoding="utf-8") as f:
                js += f.read() + "\n"
        defined = set(re.findall(r"(?:^|\n)\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", js))
        defined |= set(re.findall(r"(?:^|\n)(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\(|function)", js))

        missing = {}
        for m in re.finditer(r'\bon(?:click|change|input|keydown|keyup|submit)="([^"]*)"', html):
            handler = m.group(1)
            for name in re.findall(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(", handler):
                if name not in defined and name not in self.ALLOWED:
                    missing.setdefault(name, handler[:60])
        self.assertEqual(missing, {}, "index.html 的 inline 事件處理器呼叫了未定義的函式")


if __name__ == "__main__":
    unittest.main()
