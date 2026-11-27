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


PRO_TABLES_DRIVER = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const dir = process.argv[1];
const stubs = {};
function el(id) {
  return stubs[id] || (stubs[id] = { id, innerHTML: '', textContent: '', style: {}, value: 'ALL', tagName: 'DIV',
    parentNode: { insertBefore(n) { stubs[n.id] = n; } } });
}
const ctx = { console, window: {}, document: { getElementById: el, createElement: () => ({ style: {} }) }, renderLiveTopCompanies() {} };
vm.createContext(ctx);
for (const f of ['01-core.js', '08-pro-tables.js']) vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx, { filename: f });
const run = c => vm.runInContext(c, ctx);
const out = {};

// 三大法人
const row = (src, type, label, extra) => Object.assign({ period_type: type, period_label: label, release_date: '2026-11-27', foreign_net_billion: -296.28,
  itc_net_billion: 85.19, dealer_prop_billion: 1, dealer_hedge_billion: 2, total_3insti_billion: -213.04, foreign_futures_oi_contracts: null,
  margin_balance_billion: null, top_buy_industries: '<b>買</b>', top_sell_industries: '賣', notes: '備註', text_source: src }, extra || {});
ctx.__insti = [row('live', 'DAILY', '2026-11-27 官方'), row('computed', 'WEEKLY', '2026-W48'), row('seed', 'DAILY', '2026-11-19 手寫', { foreign_net_billion: null })];
run("STATE = { institutional_flows: __insti }; renderInstiFlows()");
out.insti = el('instiFlowsBody').innerHTML; out.instiNote = el('instiSourceNote').textContent;
ctx.__insti2 = [row('seed', 'DAILY', '手寫')];
run("STATE = { institutional_flows: __insti2 }; renderInstiFlows()");
out.instiSeedNote = el('instiSourceNote').textContent;

// 個股名單
const comp = (src, name) => ({ ticker: '1111', company_name: name, industry_name: '產業', supply_chain_position: '電子', watchlist_category: '優先研究',
  latest_rev_period: '2026-10', latest_rev_billion_twd: null, rev_mom_pct: null, rev_yoy_pct: 80.5, pe_ratio_status: 'P/E 10', institutional_ownership_trend: '買',
  bull_case: name, bear_case: '無', valuation_risk: '無', invalidation_condition: '無', as_of_date: '2026-11-27', publisher: 'MOPS', text_source: src });
ctx.__c = [comp('live', '<img src=x onerror=alert(1)>')];
run("STATE = { companies: __c }; renderCompanies()");
out.comp = el('companiesContainer').innerHTML; out.compNote = el('companiesSourceNote').textContent;
ctx.__c2 = [comp('seed', '手寫')];
run("STATE = { companies: __c2 }; renderCompanies()");
out.compSeedNote = el('companiesSourceNote').textContent;

// 報告
const rep = (src, title) => ({ report_title: title, frequency: '每日', version_tag: 'v1', update_status: '即時產生', as_of_cutoff_date: '2026-11-27', primary_sources: '官方',
  executive_summary: '<script>x</script>', key_findings: [{ section: '一', content: '<b>內容</b>' }], counter_evidence: '反', assumptions_and_limits: '限', tracking_indicators: '追', text_source: src });
ctx.__r = [rep('live', '日報'), rep('seed', '季報')];
run("STATE = { research_reports: __r }; renderReports()");
out.rep = el('reportsContainer').innerHTML; out.repNote = el('reportsSourceNote').textContent;
ctx.__r2 = [rep('seed', '手寫')];
run("STATE = { research_reports: __r2 }; renderReports()");
out.repSeedNote = el('reportsSourceNote').textContent;

// 總體指標：年增為 null 不可顯示 null
ctx.__m = [{ metric_code: 'TW_TAIEX_INDEX', module_id: 'M01', observation_type: 'DIRECT_STAT', metric_name: '加權指數', quality_grade: 'A', cleaned_value: 39308.08, unit: '點',
  prev_value: 39151.81, mom_pct: 0.4, yoy_pct: null, notes: '即時', period_covered: '2026-11-27', release_date: '2026-11-27', source_url: 'u', publisher: 'p', revision_version: 'v' }];
run("STATE = { macro_latest: __m }; renderMacroCards()");
out.macro = el('macroCardsContainer').innerHTML; out.macroNote = el('macroSourceNote').textContent;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過專業表格渲染測試")
class TestProTablesRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PRO_TABLES_DRIVER, JS_DIR], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    def test_institutional_rows_show_their_source_and_escape(self):
        h = self.o["insti"]
        self.assertIn("官方逐日", h)
        self.assertIn("由逐日加總", h)
        self.assertIn("手寫歷史", h)
        self.assertNotIn("<b>買", h)
        self.assertIn("&lt;b&gt;買&lt;/b&gt;", h)
        self.assertIn("N/A", h)                                   # 手寫歷史列的外資為空 → 不可顯示 null
        self.assertNotIn("null", h)
        self.assertIn("官方逐日", self.o["instiNote"])
        self.assertIn("手寫歷史", self.o["instiNote"])
        self.assertIn("已不顯示", self.o["instiNote"])               # 與官方重疊的手寫列要說明被拿掉了
        self.assertIn("不會隨資料更新", self.o["instiSeedNote"])

    def test_companies_escape_and_tolerate_missing_numbers(self):
        h = self.o["comp"]
        self.assertNotIn("<img", h)
        self.assertIn("&lt;img", h)
        self.assertNotIn("null", h)
        self.assertIn("N/A", h)
        self.assertIn("機械式篩選", self.o["compNote"])
        self.assertIn("人工挑選", self.o["compSeedNote"])

    def test_reports_escape_and_label_each_source(self):
        h = self.o["rep"]
        self.assertNotIn("<script>", h)
        self.assertNotIn("<b>內容", h)
        self.assertIn("&lt;script&gt;", h)
        self.assertIn("badge-grade-A", h)                        # 即時報告
        self.assertIn("badge-grade-C", h)                        # 手寫報告
        self.assertIn("每季報告需要總體與財報資料", self.o["repNote"])
        self.assertIn("不會隨資料更新", self.o["repSeedNote"])

    def test_macro_card_handles_missing_yoy(self):
        m = self.o["macro"]
        self.assertIn("年增：N/A", m)
        self.assertNotIn("null", m)
        self.assertIn("加權指數為證交所每日收盤", self.o["macroNote"])


ETF_UI_DRIVER = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const dir = process.argv[1];
const ctx = { console, window: {}, document: { getElementById: () => null, createElement: () => ({ style: {} }) } };
vm.createContext(ctx);
for (const f of ['01-core.js', '09-etf-center.js']) vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx, { filename: f });
const run = c => vm.runInContext(c, ctx);
const out = {};
out.nums = run("[fmtEtfNum(null), fmtEtfNum(undefined), fmtEtfNum(NaN), fmtEtfNum(1.234, true, 1), fmtEtfNum(-1.234, true, 1), fmtEtfNum(0, true), fmtEtfPct(null), fmtEtfPct(2.5, true, 1), fmtEtfPct(-3, false)]");
out.badgeLive = run("etfLiveBadge({ score_source: 'live' })");
out.badgeSeed = run("etfLiveBadge({ score_source: 'seed' })");
out.noLive = run("etfLiveMetricsHtml({ live: null })");
ctx.__e = { live: { last_date: '2026-11-27', history_days: 250, ret_1m: 1.234, ret_3m: null, ret_6m: -2.5, ret_1y: 20, vol_ann: 18.2, mdd: -12.3, dd_from_high: -4.5,
  beta: 1.02, corr_taiex: 0.99, corr_0050: null, insti_billion: -3.456, insti_ratio_pct: -0.21, turnover_20d_billion: 12.3 } };
out.live = run("etfLiveMetricsHtml(__e)");
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過 ETF 畫面測試")
class TestEtfUiHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", ETF_UI_DRIVER, JS_DIR], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    def test_missing_numbers_render_as_na_never_null(self):
        self.assertEqual(self.o["nums"], ["N/A", "N/A", "N/A", "+1.2", "-1.2", "+0", "N/A", "+2.5%", "-3%"])

    def test_source_badges(self):
        self.assertIn("即時評分", self.o["badgeLive"])
        self.assertIn("手寫評分", self.o["badgeSeed"])

    def test_live_metrics_block(self):
        self.assertEqual(self.o["noLive"], "")                       # 美股 ETF 沒有即時指標區塊
        h = self.o["live"]
        self.assertIn("官方逐日行情，2026-11-27", h)
        self.assertIn("1 月 +1.2%", h)
        self.assertIn("3 月 N/A", h)                                  # 資料不足不可印成 null
        self.assertIn("與 0050 相關 N/A", h)
        self.assertIn("-3.46 億元", h)
        self.assertIn("不含息", h)
        self.assertIn("沒有官方即時來源", h)
        self.assertNotIn("null", h)
        self.assertNotIn("NaN", h)


MA_UI_DRIVER = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const dir = process.argv[1];
const stubs = {};
function el(id) {
  return stubs[id] || (stubs[id] = { id, innerHTML: '', textContent: '', style: {}, value: '', classList: { add() {}, remove() {}, toggle() {} },
    parentNode: { insertBefore() {} }, querySelectorAll: () => [] });
}
const store = {};
const ctx = { console, window: { addEventListener() {} }, localStorage: { getItem: k => store[k] || null, setItem: (k, v) => { store[k] = v; } },
  document: { getElementById: el, createElement: () => ({ style: {} }), querySelectorAll: () => [], addEventListener() {} },
  alert() {}, apiPost: async () => { throw new Error('no api'); } };
vm.createContext(ctx);
for (const f of ['01-core.js', '16-multi-agent.js']) vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx, { filename: f });
const run = c => vm.runInContext(c, ctx);
const rpt = id => ({ agent_name: id, data_timestamp_used: 't', current_system_problems: '<script>x</script>', research_evidence: 'e', identified_defects: 'd',
  improvement_suggestions: 's', expected_effects: 'x', potential_risks: 'r' });
const mk = origin => ({ session_id: 'SESSION-LIVE-1', origin, started_at: '2026-11-27T22:00:00+08:00', topic: 't',
  phase2_independent_reports: Object.fromEntries(['AGENT_01', 'AGENT_02', 'AGENT_03', 'AGENT_04', 'AGENT_05', 'AGENT_06'].map(a => [a, rpt(a)])),
  phase3_cross_reviews: [{ reviewer_id: 'AGENT_01', target_agent_id: 'AGENT_02', review_stance: '<b>支持</b>', comment: '<img src=x onerror=alert(1)>' }],
  phase4_rebuttals: [], phase5_synthesis: {}, phase6_proposals: [] });
const out = {};
ctx.__live = mk('live_audit');
run("STATE = { multi_agent_center: __live }");
const before = JSON.stringify(ctx.__live.phase2_independent_reports.AGENT_01);
out.guard = run("runCloudClientMultiAgentSession('主題')");                          // 真實稽核存在時，瀏覽器不可再用假資料覆蓋
out.unchanged = JSON.stringify(run("STATE.multi_agent_center").phase2_independent_reports.AGENT_01) === before;
ctx.__hand = mk('handwritten');
run("STATE = { multi_agent_center: __hand, generated_at: 'G', etf_center: { etfs: [] }, industries: [], live_summary: {} }");
out.handSim = run("runCloudClientMultiAgentSession('主題')");                         // 手寫記錄時維持原行為
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過多代理畫面測試")
class TestMultiAgentUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", MA_UI_DRIVER, JS_DIR], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    def test_browser_simulation_never_overwrites_a_real_audit(self):
        self.assertFalse(self.o["guard"])
        self.assertTrue(self.o["unchanged"])

    def test_handwritten_record_keeps_previous_behaviour(self):
        self.assertTrue(self.o["handSim"])


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過快照組成說明測試")
class TestSnapshotCompositionNote(unittest.TestCase):
    DRIVER = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const ctx = { console, window: {}, document: { getElementById: () => null, createElement: () => ({ style: {} }) } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(process.argv[1], '01-core.js'), 'utf8'), ctx);
const run = c => vm.runInContext(c, ctx);
console.log(JSON.stringify({
  mixed: run("snapshotCompositionHtml({ seed: ['2026-11-25', '2026-11-26'], live: ['2026-11-27'] })"),
  empty: run("snapshotCompositionHtml(null)"),
  liveOnly: run("snapshotCompositionHtml({ seed: [], live: ['2026-11-27'] })"),
  escaped: run("snapshotCompositionHtml({ seed: ['<b>x</b>'], live: [] })"),
}));
"""

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", cls.DRIVER, JS_DIR], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    def test_mixed_composition_names_each_group_and_discloses_the_difference(self):
        h = self.o["mixed"]
        self.assertIn("舊模型 2 天（11-25、11-26", h)
        self.assertIn("即時評分 1 天（11-27", h)
        self.assertIn("內建種子值", h)
        self.assertIn("尺度與方法不同", h)

    def test_missing_data_renders_nothing_and_values_are_escaped(self):
        self.assertEqual(self.o["empty"], "")
        self.assertIn("舊模型 0 天（無", self.o["liveOnly"])
        self.assertNotIn("<b>", self.o["escaped"])


ETF_CHARTS_DRIVER = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const dir = process.argv[1];
const stubs = {};
function el(id) {
  return stubs[id] || (stubs[id] = { id, innerHTML: '', textContent: '', style: {}, value: 'ALL', tagName: 'DIV', options: [], children: [], dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false }, appendChild() {}, addEventListener() {}, setAttribute() {}, getAttribute: () => null,
    querySelectorAll: () => [], parentNode: { insertBefore(n) { stubs[n.id] = n; } } });
}
const ctx = { console, window: {}, localStorage: { getItem: () => null, setItem() {} }, alert() {},
  document: { getElementById: el, createElement: () => ({ style: {}, classList: { add() {} } }), querySelectorAll: () => [], addEventListener() {} } };
vm.createContext(ctx);
for (const f of ['01-core.js', '09-etf-center.js', '10-etf-proposal-helpers.js', '11-etf-lists.js', '12-etf-charts.js', '13-etf-compare.js', '14-etf-portfolio.js', '15-etf-reports.js'])
  vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx, { filename: f });
const run = c => vm.runInContext(c, ctx);

const mk = (code, market, src, extra) => Object.assign({ etf_code: code, etf_name: code + '名<i>', listing_market: market, score_source: src, is_leveraged_or_inverse: 0,
  total_score_a_long_term: 60, total_score_b_short_mid: 40, conclusion_a_long_term: '條件普通', conclusion_b_short_mid: '風險偏高',
  primary_net_flow_value: null, return_1y_total_pct: null, twd_adjusted_1y_return_pct: null, annualized_volatility_pct: null, live: null }, extra || {});
const curve = (start, n, step) => Array.from({ length: n }, (_, i) => [`2026-0${1 + Math.floor(i / 10)}-${String(1 + (i % 10) * 2).padStart(2, '0')}`, start + i * step]);
ctx.__etfs = [
  mk('0050', 'TW', 'live', { live: { curve: curve(100, 30, 1), history_days: 260 }, total_score_a_long_term: 63.1, total_score_b_short_mid: 43.7 }),
  mk('0056', 'TW', 'live', { live: { curve: curve(50, 30, -0.5), history_days: 260 }, total_score_a_long_term: 69.2, total_score_b_short_mid: 37.8 }),
  mk('00631L', 'TW', 'live', { is_leveraged_or_inverse: 1, live: { curve: curve(10, 30, 0.1), history_days: 260 } }),
  mk('VOO', 'US', 'seed', { total_score_a_long_term: 91.9, total_score_b_short_mid: 68.8, conclusion_b_short_mid: '持續觀察', primary_net_flow_value: 68.5,
    return_1y_total_pct: 28.4, annualized_volatility_pct: 14.6 }),
  mk('SMH', 'US', 'seed', { total_score_a_long_term: 74.6, total_score_b_short_mid: 57, conclusion_b_short_mid: '等待更佳條件', primary_net_flow_value: -14.5,
    return_1y_total_pct: 44.5, annualized_volatility_pct: 32.4 }),
];
const out = {};
run("STATE = { etf_center: { etfs: __etfs } }");

// 圖 4：只畫真實走勢
run("ETF_PERF_HORIZON = '1Y'; renderChart4PerfCurve()");
out.c4 = el('etfChart4PerfCurveBox').innerHTML;
run("ETF_PERF_HORIZON = '3Y'; renderChart4PerfCurve()");
out.c43y = el('etfChart4PerfCurveBox').innerHTML;
run("ETF_PERF_HORIZON = '1Y'");

// 圖 7：沒有數字的不可畫成 0
run("renderChart7RiskReturn()");
out.c7 = el('etfChart7ScatterBox').innerHTML; out.c7note = el('etfChart7Note').textContent;

// 圖 1：沒有申贖數字的不可畫成 0
run("renderChart1Flows()");
out.c1 = el('etfChart1FlowsBox').innerHTML; out.c1note = el('etfChart1Note').textContent;

// 圖 2 / 3：依分數來源分開排名
run("renderChart2And3Scores()");
out.c2 = el('etfChart2LongScoreBox').innerHTML; out.c3 = el('etfChart3ShortScoreBox').innerHTML;

// 決策摘要：依來源分開 (其餘區塊的渲染函式換成空函式，只驗證這裡要測的部分；圖表函式上面已單獨執行過)
for (const fn of ['renderEtfLists', 'renderChart1Flows', 'renderChart2And3Scores', 'renderChart4PerfCurve', 'renderChart5HoldingsDist',
                  'renderEtfComparator', 'renderChart7RiskReturn', 'renderUserPortfolioAnalysis', 'renderEtfReportsAndBacktests', 'renderArgonMultiAgentCenter']) {
  run(`${fn} = function () {}`);
}
run("renderEtfDecisionCenter()");
out.sec2 = el('etfSec2DecisionSummary').innerHTML; out.sec2note = el('etfSec2Note').textContent;
out.sec1note = el('etfSec1Note').textContent; out.sec4note = el('etfSec4Note').textContent;
out.spark = run("etfSparkline([['2026-01-02', 100], ['2026-01-03', 110], ['2026-01-04', 105]])");
out.sparkEmpty = run("etfSparkline([['2026-01-02', 100]])");
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過 ETF 圖表執行測試")
class TestEtfChartsExecute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", ETF_CHARTS_DRIVER, JS_DIR], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    def test_performance_chart_draws_only_real_curves(self):
        c4 = self.o["c4"]
        self.assertEqual(c4.count("<polyline"), 2)                       # 0050、0056 有真實走勢；槓桿型不在比較清單；美股沒有官方歷史，不畫
        self.assertNotIn("00631L", c4)
        self.assertNotIn("VOO", c4)
        self.assertNotIn("SMH", c4)
        self.assertIn("自 01-01", c4)                                    # 標明走勢起點
        self.assertIn("沒有 3 年或 5 年的實際走勢", self.o["c43y"])        # 3Y/5Y 不外推
        self.assertNotIn("<polyline", self.o["c43y"])

    def test_scatter_and_flow_charts_skip_missing_numbers(self):
        for key in ("c7", "c1"):
            self.assertNotIn("NaN", self.o[key])
            self.assertNotIn("null", self.o[key])
        self.assertIn("VOO", self.o["c7"])
        self.assertNotIn("0050", self.o["c7"])                           # 台股沒有含息報酬 → 未畫入，而不是畫在 0%
        self.assertIn("未畫入", self.o["c7note"])
        self.assertIn("VOO", self.o["c1"])
        self.assertNotIn("0050", self.o["c1"])
        self.assertIn("未畫入", self.o["c1note"])

    def test_rankings_are_split_by_score_source_and_escape_names(self):
        for key in ("c2", "c3"):
            h = self.o[key]
            self.assertIn("台股（即時評分）", h)
            self.assertIn("美股（手寫評分", h)
            self.assertLess(h.index("台股（即時評分）"), h.index("美股（手寫評分"))
            self.assertNotIn("<i>", h)
            self.assertIn("&lt;i&gt;", h)
        a = self.o["c2"]
        tw, us = a.split("美股（手寫評分")[0], a.split("美股（手寫評分")[1]
        self.assertIn("0056", tw)
        self.assertNotIn("VOO", tw)                                      # 美股不會混進台股的排名
        self.assertIn("VOO", us)
        self.assertNotIn("00631L", a)                                    # 長期配置排名不含槓桿型

    def test_decision_summary_never_compares_the_two_score_scales(self):
        h = self.o["sec2"]
        self.assertIn("台股（即時公式評分）", h)
        self.assertIn("美股（手寫評分，不會更新）", h)
        self.assertNotIn("11/20 費半", h)                                # 手寫的事件敘述已移除
        self.assertNotIn("<i>", h)
        self.assertIn("分開呈現", self.o["sec2note"])
        self.assertIn("手寫", self.o["sec1note"])
        self.assertIn("手寫", self.o["sec4note"])

    def test_sparkline(self):
        self.assertIn("<polyline", self.o["spark"])
        self.assertEqual(self.o["sparkEmpty"], "")


@unittest.skipUnless(shutil.which("node"), "node 未安裝，略過桑基圖標籤與未評分方塊測試")
class TestSankeyLabelsAndUnscoredTiles(unittest.TestCase):
    DRIVER = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const dir = process.argv[1];
const stubs = {};
function el(id) {
  return stubs[id] || (stubs[id] = { id, innerHTML: '', textContent: '', style: {}, value: '5', classList: { toggle() {} }, parentNode: { insertBefore(n) { stubs[n.id] = n; } }, setAttribute() {} });
}
const ctx = { console, window: {}, sessionStorage: { getItem: () => null, setItem() {} },
  document: { getElementById: el, createElement: () => ({ style: {} }), querySelectorAll: () => [] } };
vm.createContext(ctx);
for (const f of ['01-core.js', '06-heatmap-timeline.js', '23-live-sankey.js']) vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx, { filename: f });
const run = c => vm.runInContext(c, ctx);
const out = {};

// 桑基圖：一個大產業 + 八個極小的產業 (節點很矮，標籤原本會疊在一起)
const inds = [{ id: 'BIG', name: '大產業', flows: { foreign: -100, itc: 0, dealer: 0 }, net: -100, buy: 0, sell: 100, turnover: 1, coverage: 1, companies: 9 }];
for (let k = 0; k < 8; k++) inds.unshift({ id: 'S' + k, name: '小' + k, flows: { foreign: 0.5 + k * 0.1, itc: 0, dealer: 0 }, net: 0.5, buy: 0.5, sell: 0, turnover: 1, coverage: 1, companies: 9 });
ctx.__ls = { available: true, as_of: '2026-11-27', unit: '億元', note: 'n',
  institutions: [{ key: 'foreign', label: '外資', buy: 6, sell: 100, net: -94 }, { key: 'itc', label: '投信', buy: 0, sell: 0, net: 0 }, { key: 'dealer', label: '自營商', buy: 0, sell: 0, net: 0 }], industries: inds };
run("STATE = { live_sankey: __ls }; renderLiveSankey()");
const svg = el('liveSankeyContainer').innerHTML;
out.labelYs = [...svg.matchAll(/<text x="5\d\d(?:\.\d+)?" y="([\d.]+)" font-size="12.5"/g)].map(m => +m[1]);
out.viewH = +svg.match(/viewBox="0 0 \d+ (\d+)"/)[1];

// 熱度圖：未評分的產業 (score_source = seed) 仍有即時營收與相對強弱 → 不可顯示手寫的舊數字
ctx.__inds = [{ industry_id: 'IND_BIO_RETAIL', industry_name: '生技', total_weighted_score: null, rotation_state: 'INSUFFICIENT_DATA', score_source: 'seed',
  rev_yoy_pct: 8.4, rel_strength_20d: 0.5, rel_strength_60d: null, as_of_date: '2026-11-21', representative_companies: [], live_agg: {},
  live_metrics: { yoy: 58.9, rs_pct: -6.62, rs_days: 6, foreign_billion: 0, itc_billion: 0, dealer_billion: 0, inst_net_billion: 0, inst_ratio_pct: 0, price_coverage: 1, companies: 497, turnover_billion: 1 } }];
run("STATE = { industries: __inds, live_top_companies: [{ data_ym: '11510' }] }; renderIndustryHeatmap()");
const tile = el('industryHeatmapGrid').innerHTML.split('class="heat-tile').find(t => t.includes('生技醫療')) || '';
out.tile = tile;
console.log(JSON.stringify(out));
"""

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", cls.DRIVER, JS_DIR], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError("node 執行失敗：" + r.stderr)
        cls.o = json.loads(r.stdout)

    def test_industry_labels_never_overlap(self):
        ys = self.o["labelYs"]
        self.assertEqual(len(ys), 9)
        for a, b in zip(ys, ys[1:]):
            self.assertGreaterEqual(b - a, 14.9, "標籤垂直間距不足，會互相重疊")
        self.assertGreater(self.o["viewH"], ys[-1])               # 畫布高度要容納被往下推的最後一個標籤

    def test_unscored_tile_shows_live_numbers_not_handwritten_ones(self):
        t = self.o["tile"]
        self.assertIn("+58.9%", t)                                 # 即時營收年增，不是手寫的 +8.4%
        self.assertNotIn("+8.4%", t)
        self.assertIn("近 6 日相對大盤", t)
        self.assertNotIn("20 日相對強弱", t)
        self.assertNotIn("+0.5%", t)
        self.assertIn("觀察中", t)                                  # 仍然不評分


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
