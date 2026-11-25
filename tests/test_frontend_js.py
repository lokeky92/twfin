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
