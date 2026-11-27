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


LIVE_UI_DRIVER = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const dir = process.argv[1];
const stubs = {};
function el(id) {
  return stubs[id] || (stubs[id] = { id, innerHTML: '', textContent: '', style: {}, value: '5', classList: { toggle(c, on) { this['_' + c] = on; } },
    parentNode: { insertBefore(n) { stubs[n.id] = n; } }, nextSibling: null, setAttribute(k, v) { this[k] = v; } });
}
const store = {};
const ctx = {
  console, window: {}, sessionStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } },
  document: { getElementById: el, createElement: () => ({ style: {}, setAttribute() {} }), querySelectorAll: () => [] },
  openDrawer() {}, buildSixQuestionsHtml: () => '',
};
vm.createContext(ctx);
for (const f of ['01-core.js', '06-heatmap-timeline.js', '07-leaderboards-stories.js', '23-live-sankey.js']) {
  vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx, { filename: f });
}
const run = code => vm.runInContext(code, ctx);

const mk = (id, name, total, state, src, lm) => ({
  industry_id: id, industry_name: name, total_weighted_score: total, rotation_state: state, score_source: src,
  as_of_date: '2026-11-27', rev_yoy_pct: 12.3, rel_strength_20d: null, rel_strength_60d: null, representative_companies: [],
  score_capital_flow: 40, score_fundamentals: 80, score_future_growth: 60, score_institutional: 50, score_valuation: 70,
  live_agg: {}, live_metrics: lm,
});
const lm = (yoy, f, i, d, rs) => ({ yoy, cum_yoy: yoy === null ? null : yoy - 5, accel: 5, rs_pct: rs, rs_days: 5, foreign_billion: f, itc_billion: i, dealer_billion: d,
  inst_net_billion: f + i, inst_ratio_pct: 1.2, price_coverage: 1, companies: 10, turnover_billion: 100 });
const inds = [
  mk('IND_SEMI_FOUNDRY', '半導體－晶圓代工', 77.3, 'A', 'live', lm(80, 10, 5, 0, 3)),
  mk('IND_AI_SERVER', '<img src=x onerror=alert(1)>', 60.1, 'B', 'live', lm(50, -20, 1, 0, -1)),
  mk('IND_THERMAL', '散熱', 50.0, 'C', 'live', lm(30, 2, 2, 0, 0.5)),
  mk('IND_IC_DESIGN', 'IC設計', 45.0, 'C', 'live', lm(40, 0, 0, 0, null)),
  mk('IND_SHIPPING', '航運', 35.0, 'D', 'live', lm(null, -3, -1, 0, -2)),
  mk('IND_FIN_HOLDING', '金融', 28.3, 'E', 'live', lm(-50, -11, 0, 0, -6)),
];
const out = {};

// 1. 熱度圖：即時分數
ctx.__inds = inds;
run("STATE = { industries: __inds, live_top_companies: [{ data_ym: '11510' }], live_sankey: { as_of: '2026-11-27' } }");
run("renderIndustryHeatmap()");
out.liveTiles = el('industryHeatmapGrid').innerHTML;
out.liveNote = el('heatmapSourceNote').textContent;

// 2. 歷史情境：不得把現在的分數配上手寫的歷史顏色
el('timelineRangeInput').value = '3';
run("renderIndustryHeatmap({ IND_SEMI_FOUNDRY: 'D' })");
out.histTiles = el('industryHeatmapGrid').innerHTML;
out.histNote = el('heatmapSourceNote').textContent;
el('timelineRangeInput').value = '5';

// 3. 種子分數 (沒有 live_metrics)：維持 20 日相對強弱，且 null 不可顯示成 +null
ctx.__seed = inds.map(i => ({ ...i, score_source: 'seed', live_metrics: null }));
run("STATE = { industries: __seed }");
run("renderIndustryHeatmap()");
out.seedTiles = el('industryHeatmapGrid').innerHTML;
out.seedNote = el('heatmapSourceNote').textContent;

// 4. 排行榜
run("STATE = { industries: __inds, live_top_companies: [{ data_ym: '11510' }], live_sankey: { as_of: '2026-11-27' } }");
run("renderSixLeaderboards()");
out.boards = el('sixLeaderboardsGrid').innerHTML;
out.boardsNote = el('sixBoardsNote').textContent;
run("STATE = { industries: __seed }");
run("renderSixLeaderboards()");
out.staticBoards = el('sixLeaderboardsGrid').innerHTML;
out.staticBoardsNote = el('sixBoardsNote').textContent;

// 5. 即時桑基
ctx.__ls = {
  available: true, as_of: '2026-11-27', unit: '億元', note: '近似說明',
  institutions: [{ key: 'foreign', label: '外資', buy: 10, sell: 31, net: -21 }, { key: 'itc', label: '投信', buy: 6, sell: 0, net: 6 }, { key: 'dealer', label: '自營商', buy: 0, sell: 0, net: 0 }],
  industries: [
    { id: 'A', name: '產業甲、其他', flows: { foreign: 10, itc: 5, dealer: 0 }, net: 15, buy: 15, sell: 0, turnover: 100, coverage: 1, companies: 5 },
    { id: 'B', name: '<b>乙</b>', flows: { foreign: -31, itc: 1, dealer: 0 }, net: -30, buy: 1, sell: 31, turnover: 200, coverage: 0.9, companies: 5 },
  ],
};
run("STATE = { live_sankey: __ls }");
run("initSankeyMode()");
out.sankeyHtml = el('liveSankeyContainer').innerHTML;
out.sankeyKpi = el('liveSankeyKpis').innerHTML;
out.sankeyMode1 = { live: el('sankeyLivePane').style.display, macro: el('sankeyMacroPane').style.display, saved: store.twfin_sankey_mode };
run("setSankeyMode('macro')");
out.sankeyMode2 = { live: el('sankeyLivePane').style.display, macro: el('sankeyMacroPane').style.display, saved: store.twfin_sankey_mode };
// 沒有即時資料 → 預設顯示總體背景，且圖區有明確提示
for (const k of Object.keys(store)) delete store[k];
run("STATE = { live_sankey: { available: false, industries: [] } }");
run("initSankeyMode()");
out.noLive = { html: el('liveSankeyContainer').innerHTML, mode: run('SANKEY_MODE'), macro: el('sankeyMacroPane').style.display };
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過即時畫面渲染測試")
class TestLiveHeatmapBoardsAndSankey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", LIVE_UI_DRIVER, JS_DIR], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    # --- 熱度圖 ---
    def test_live_tiles_show_live_score_and_relative_strength(self):
        t = self.o["liveTiles"]
        first = t.split('class="heat-tile')[1]                   # 第一個方塊 = 有即時指標的晶圓代工
        self.assertIn("77.3 分", first)
        self.assertIn("近 5 日相對大盤", first)
        self.assertNotIn("20 日相對強弱", first)
        self.assertIn("2026年10月 營收 YoY", first)
        self.assertIn("+3%", first)                              # 即時的相對強弱數字，不是舊的種子值
        self.assertIn("分數由官方即時資料重算", self.o["liveNote"])

    def test_missing_values_render_as_na_not_null(self):
        for html in (self.o["liveTiles"], self.o["seedTiles"]):
            self.assertNotIn("null", html)
            self.assertNotIn("undefined", html)
            self.assertNotIn("NaN", html)
        self.assertIn("N/A", self.o["liveTiles"])        # 航運的營收年增、IC 設計的相對強弱為空

    def test_history_period_does_not_pair_old_colors_with_current_scores(self):
        self.assertNotIn("77.3 分", self.o["histTiles"])
        self.assertIn("歷史情境", self.o["histTiles"])
        self.assertIn("歷史情境", self.o["histNote"])

    def test_seed_snapshot_is_labelled_as_not_updating(self):
        self.assertIn("20 日相對強弱", self.o["seedTiles"])
        self.assertIn("種子值", self.o["seedNote"])

    # --- 排行榜 ---
    def test_live_boards_have_no_hardcoded_scores_and_escape_names(self):
        b = self.o["boards"]
        self.assertEqual(b.count("lb-card"), 6)
        self.assertNotIn("88.4", b)
        self.assertNotIn("<img", b)                      # 產業名稱是動態文字，必須跳脫
        self.assertIn("&lt;img", b)
        self.assertIn("即時資料產生", self.o["boardsNote"])

    def test_live_boards_rank_by_the_right_quantity(self):
        b = self.o["boards"]
        # 第 6 榜 (即時評分最低)：金融 28.3 要出現在航運 35.0 之前
        board6 = b.split("6. ")[1]
        self.assertLess(board6.index("金融"), board6.index("航運"))
        # 第 1 榜只列「淨買超」的產業：金融 (淨賣) 不可在第 1 榜
        board1 = b.split("1. ")[1].split("2. ")[0]
        self.assertNotIn("金融", board1)
        self.assertIn("半導體", board1)

    def test_old_snapshot_falls_back_to_static_boards_with_warning(self):
        self.assertEqual(self.o["staticBoards"].count("lb-card"), 6)
        self.assertIn("不會隨資料更新", self.o["staticBoardsNote"])

    # --- 即時桑基 ---
    def test_sankey_draws_one_ribbon_per_nonzero_flow_and_escapes(self):
        h = self.o["sankeyHtml"]
        self.assertEqual(h.count('class="ls-rib"'), 4)            # 甲: 外資買、投信買；乙: 外資賣、投信買 (自營商皆 0)
        self.assertNotIn("<b>", h)
        self.assertIn("&lt;b&gt;乙&lt;/b&gt;", h)
        self.assertIn("外資 買超", h)
        self.assertIn("外資 賣超", h)
        self.assertNotIn("NaN", h)
        self.assertIn("−21", self.o["sankeyKpi"])                  # 外資淨賣用真正的負號顯示

    def test_sankey_mode_switch_and_default(self):
        self.assertEqual(self.o["sankeyMode1"], {"live": "block", "macro": "none", "saved": "live"})
        self.assertEqual(self.o["sankeyMode2"], {"live": "none", "macro": "block", "saved": "macro"})

    def test_sankey_without_live_data_shows_notice_and_macro_pane(self):
        n = self.o["noLive"]
        self.assertIn("沒有即時", n["html"])
        self.assertEqual(n["mode"], "macro")
        self.assertEqual(n["macro"], "block")


WARNINGS_DRIVER = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const dir = process.argv[1];
const stubs = {};
function el(id) {
  return stubs[id] || (stubs[id] = { id, innerHTML: '', textContent: '', style: {}, value: 'ALL',
    parentNode: { insertBefore(n) { stubs[n.id] = n; } } });
}
const ctx = { console, window: {}, document: { getElementById: el, createElement: () => ({ style: {} }) } };
vm.createContext(ctx);
for (const f of ['01-core.js', '08-pro-tables.js']) vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx, { filename: f });
const w = (id, lvl, src, text) => ({ warning_id: id, industry_name: '<b>產業</b>', alert_level: lvl, signal_category: '基本面居前', horizon: '中期',
  credibility_grade: 'A級', triggered_at: '2026-11-27', trigger_reason: text, raw_data_evidence: text, publisher: 'MOPS',
  counter_evidence: text, invalidation_conditions: text, missing_data_notes: text, text_source: src });
const out = {};
ctx.__live = [w('LIVE_A', 'LEVEL 3', 'live', '<img src=x onerror=alert(1)>'), w('LIVE_B', 'LEVEL R', 'live', '一般文字')];
vm.runInContext("STATE = { warnings: __live }; renderWarnings()", ctx);
out.live = el('warningsContainer').innerHTML; out.liveNote = el('warningsSourceNote').textContent;
ctx.__seed = [w('WARN_1', 'LEVEL 1', 'seed', '手寫')];
vm.runInContext("STATE = { warnings: __seed }; renderWarnings()", ctx);
out.seed = el('warningsContainer').innerHTML; out.seedNote = el('warningsSourceNote').textContent;
el('warningLevelFilter').value = 'LEVEL R';
vm.runInContext("STATE = { warnings: __live }; renderWarnings()", ctx);
out.filtered = el('warningsContainer').innerHTML;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過預警渲染測試")
class TestWarningsRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", WARNINGS_DRIVER, JS_DIR], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    def test_every_dynamic_field_is_escaped(self):
        h = self.o["live"]
        self.assertNotIn("<img", h)
        self.assertNotIn("<b>產業", h)
        self.assertIn("&lt;img", h)
        self.assertIn("&lt;b&gt;產業&lt;/b&gt;", h)

    def test_source_banner_distinguishes_live_from_handwritten(self):
        self.assertIn("2 則預警", self.o["liveNote"])
        self.assertIn("自動產生", self.o["liveNote"])
        self.assertIn("手寫", self.o["seedNote"])
        self.assertIn("不會隨資料更新", self.o["seedNote"])

    def test_level_filter_still_works(self):
        self.assertEqual(self.o["live"].count('class="card"'), 2)
        self.assertEqual(self.o["filtered"].count('class="card"'), 1)
        self.assertIn("LEVEL R", self.o["filtered"])


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
