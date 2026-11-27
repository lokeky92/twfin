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

    def test_split_deploy_loads_data_json_then_paints_before_api(self):
        # 拆分部署：index.html 沒有內嵌快照，先 fetch data.json 畫第一個畫面，再向 API 更新
        s = self.s["splitThenApi"]
        self.assertEqual(s["dataCalls"], 1)
        self.assertEqual(s["renders"], 2)               # 先用 data.json 畫一次，API 資料有變再畫一次
        self.assertEqual((s["mode"], s["stateGen"]), ("live", "API-CHANGED"))

    def test_split_deploy_on_static_hosting_has_no_api_but_still_renders(self):
        s = self.s["splitStatic"]
        self.assertEqual((s["dataCalls"], s["calls"], s["renders"]), (1, 1, 1))   # 404 不重試
        self.assertEqual(s["stateGen"], "SNAPSHOT")
        self.assertEqual(s["reason"], "no-api")
        self.assertIn("雲端快照模式", s["banner"])

    def test_html_returned_for_data_json_is_treated_as_missing(self):
        # 靜態託管常把不存在的路徑導回 index.html；不可把它當成 JSON，應退回等待 API
        s = self.s["splitDataHtml200"]
        self.assertEqual(s["renders"], 1)
        self.assertEqual((s["mode"], s["stateGen"]), ("live", "API-CHANGED"))

    def test_opening_split_page_as_file_explains_the_single_file_version(self):
        s = self.s["splitFileProtocol"]
        self.assertEqual((s["dataCalls"], s["calls"], s["renders"]), (0, 0, 0))   # file:// 不發任何請求
        self.assertTrue(s["bannerShown"])
        self.assertIn("單檔離線版", s["banner"])
        self.assertIn("--single", s["banner"])

    def test_embedded_snapshot_never_fetches_data_json(self):
        self.assertEqual(self.s["embeddedSkipsDataFile"]["dataCalls"], 0)
        self.assertEqual(self.s["embeddedSkipsDataFile"]["stateGen"], "SNAPSHOT")

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


SENS_DRIVER = r"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync(process.argv[1], 'utf8');

const WS = { available: true, delta_pct: 5.0, scenario_count: 510, industries: [
  { industry_id: 'A', base_rank: 2, min_rank: 1, max_rank: 3, top3_pct: 80.5, level_change_pct: 12.5, stability: '中等' }] };
const TS = { available: true, delta_points: 2.0, scenario_count: 508,
  by_threshold: [{ threshold_key: 'lvl4_min', label: 'LEVEL 4 總分門檻' }],
  industries: [{ industry_id: 'A', base_level: 'LEVEL 4', margin_points: 0.35, nearest_threshold: 'lvl4_min',
    level_change_pct: 41.1, stability: '不穩定' }] };
const IND_A = { industry_id: 'A', industry_name: '產業A', major_category: '科技', rotation_state: 'B', total_weighted_score: 80.5 };
const IND_U = { industry_id: 'U', industry_name: '不可評分', major_category: '其他', rotation_state: 'INSUFFICIENT_DATA', total_weighted_score: null };

async function run(state) {
  let cap = null;
  const ctx = { console, Blob, STATE: state, alert: () => {},
    document: { getElementById: () => ({ value: 'ALL' }) },
    getVisibleIndustries: () => [IND_A, IND_U] };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  vm.runInContext('downloadBlob = function (n, b) { __cap = { n: n, b: b }; }', ctx);
  vm.runInContext('exportIndustriesCsv()', ctx);
  const c = vm.runInContext('__cap', ctx);
  return { name: c.n, text: await c.b.text(), join: vm.runInContext('joinSensitivity(STATE)', ctx) };
}

(async () => {
  const base = { generated_at: '2026-11-26 10:00:00', active_model: { version_id: 'v1' } };
  const out = {};
  out.full = await run({ ...base, weight_sensitivity: WS, threshold_sensitivity: TS });
  out.none = await run({ ...base });
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過敏感度匯出測試")
class TestSensitivityInExports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", SENS_DRIVER, os.path.join(JS_DIR, "20-export.js")],
                           capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    @staticmethod
    def _rows(text):
        import csv
        import io
        return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))

    def test_join_merges_weight_and_threshold_by_industry(self):
        j = self.o["full"]["join"]
        self.assertEqual(set(j), {"A"})
        self.assertEqual(j["A"]["w"]["base_rank"], 2)
        self.assertEqual(j["A"]["t"]["base_level"], "LEVEL 4")

    def test_csv_has_sensitivity_columns_with_values(self):
        rows = {r["產業"]: r for r in self._rows(self.o["full"]["text"])}
        a = rows["產業A"]
        self.assertEqual(a["基準名次(全部產業)"], "2")
        self.assertEqual((a["權重擾動最佳名次"], a["權重擾動最差名次"]), ("1", "3"))
        self.assertEqual(a["權重擾動進入前三名機率(%)"], "80.5")
        self.assertEqual(a["權重敏感度穩定度"], "中等")
        self.assertEqual(a["目前預警等級"], "LEVEL 4")
        self.assertEqual(a["距最近預警門檻(分)"], "0.35")
        self.assertEqual(a["最近預警門檻"], "LEVEL 4 總分門檻")      # 顯示名稱而不是內部代號
        self.assertEqual(a["門檻擾動預警等級變動機率(%)"], "41.1")
        self.assertEqual(a["門檻敏感度穩定度"], "不穩定")
        self.assertEqual(a["敏感度設定"], "權重±5%(510種情境)；門檻±2分(508種情境)")

    def test_unrated_industry_has_empty_sensitivity_cells(self):
        u = {r["產業"]: r for r in self._rows(self.o["full"]["text"])}["不可評分"]
        for col in ("基準名次(全部產業)", "權重敏感度穩定度", "距最近預警門檻(分)", "門檻敏感度穩定度"):
            self.assertEqual(u[col], "", col)

    def test_export_still_works_without_sensitivity_payload(self):
        rows = self._rows(self.o["none"]["text"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["權重敏感度穩定度"], "")
        self.assertEqual(rows[0]["敏感度設定"], "")
        self.assertEqual(rows[0]["資料基準時間"], "2026-11-26 10:00:00")
        self.assertEqual(self.o["none"]["join"], {})

    def test_existing_columns_unchanged_and_meta_columns_stay_last(self):
        header = list(self._rows(self.o["full"]["text"])[0].keys())
        self.assertEqual(header[0], "排名")
        self.assertEqual(header[-2:], ["資料基準時間", "模型版本"])
        self.assertEqual(len(header), len(set(header)))


PULSE_DRIVER = r"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync(process.argv[1], 'utf8');
function el() { return { innerHTML: '', textContent: '', style: {}, parentNode: { insertBefore(n) { els[n.id] = n; } }, nextSibling: null }; }
const els = { tenSecPulseGrid: el() };
const ctx = {
  console, window: {},
  document: { getElementById: id => els[id] || null, createElement: () => el() },
  openDrawer(badge, title, sub, html) { ctx.__drawer = { badge, title, sub, html }; },
  buildSixQuestionsHtml: (a, b, c, d, e, f, meta) => [a, b, c, d, e, f, meta].join('|'),
  STATE: null,
};
vm.createContext(ctx);
vm.runInContext(code + ';this.__f = { renderTenSecPulse, openPulseDrawer };', ctx);
const mk = (n, tag) => ({ q: `Q${n}`, a: `A${n}${tag}`, sub: `S${n}`, color: '#fff', q6: ['a', 'b', 'c', 'd', 'e', 'f'], basis: `BASIS${n}` });
const out = {};
// 1. 有 home_pulse：用即時卡片，並顯示資料日期；抽屜頁尾用該卡的 basis
ctx.STATE = { generated_at: 'G', home_pulse: { flows_through: '2026-11-27', items: [1, 2, 3, 4, 5, 6].map(n => mk(n, 'LIVE')) } };
ctx.__f.renderTenSecPulse();
out.liveGrid = els.tenSecPulseGrid.innerHTML;
out.liveNote = els.pulseLiveNote.textContent;
ctx.__f.openPulseDrawer(2);
out.liveDrawer = ctx.__drawer.html;
// 2. 沒有 home_pulse (舊快照)：退回靜態卡片，並明確警告不會更新
ctx.STATE = { generated_at: 'G' };
ctx.__f.renderTenSecPulse();
out.staticGrid = els.tenSecPulseGrid.innerHTML;
out.staticNote = els.pulseLiveNote.textContent;
ctx.__f.openPulseDrawer(0);
out.staticDrawer = ctx.__drawer.html;
// 3. home_pulse 張數不對 (壞資料)：不採用，退回靜態
ctx.STATE = { generated_at: 'G', home_pulse: { items: [mk(1, 'BAD')] } };
ctx.__f.renderTenSecPulse();
out.badGrid = els.tenSecPulseGrid.innerHTML;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過首頁摘要渲染測試")
class TestHomePulseRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PULSE_DRIVER, os.path.join(JS_DIR, "04-overview.js")],
                           capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    def test_live_cards_rendered_with_date_note(self):
        self.assertEqual(self.o["liveGrid"].count("pulse-pill"), 6)
        self.assertIn("A3LIVE", self.o["liveGrid"])
        self.assertIn("2026-11-27", self.o["liveNote"])
        self.assertIn("自動產生", self.o["liveNote"])

    def test_live_drawer_uses_card_basis_not_static_sources(self):
        self.assertIn("BASIS3", self.o["liveDrawer"])
        self.assertNotIn("中央銀行(2026-09/10)", self.o["liveDrawer"])

    def test_old_snapshot_falls_back_to_static_with_warning(self):
        self.assertEqual(self.o["staticGrid"].count("pulse-pill"), 6)
        self.assertNotIn("LIVE", self.o["staticGrid"])
        self.assertIn("不會隨資料更新", self.o["staticNote"])
        self.assertIn("不隨資料更新", self.o["staticDrawer"])

    def test_malformed_home_pulse_is_ignored(self):
        self.assertNotIn("BAD", self.o["badGrid"])
        self.assertEqual(self.o["badGrid"].count("pulse-pill"), 6)


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
