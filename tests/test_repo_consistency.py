"""
跨平台一致性檢查：程式讀取的檔名必須與 git 中的實際大小寫完全相同。
Windows 檔案系統不分大小寫，Linux (GitHub Actions / Render) 會區分；
大小寫不一致會讓 Linux 上找不到檔案而重新產生整套研究紀錄。
"""
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise unittest.SkipTest("not a git checkout")
    return set(out.stdout.splitlines())


class TestCaseSensitiveFilenames(unittest.TestCase):
    def test_multi_agent_history_file_exact_case(self):
        tracked = _tracked_files()
        self.assertIn("argon_multi_agent/research/history/SESSION-20261122-001_full_record.json", tracked)

    def test_no_case_only_duplicates(self):
        seen = {}
        for path in _tracked_files():
            key = path.lower()
            self.assertNotIn(key, seen, f"大小寫不同的重複檔名：{seen.get(key)} / {path}")
            seen[key] = path

    def test_session_files_use_writer_case(self):
        # orchestrator 以 SESSION-xxxx / ETF-IMPROVE-xxxx 寫檔，不應存在小寫版本
        bad = [p for p in _tracked_files()
               if p.startswith("argon_multi_agent/")
               and (os.path.basename(p).startswith("session-") or os.path.basename(p).startswith("etf-improve-"))]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
