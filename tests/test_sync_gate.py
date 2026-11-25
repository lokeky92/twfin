"""排程閘門與延遲量測的純函式測試 (不連網)"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from sync_gate import parse_cron_time, parse_iso, schedule_delay_minutes, should_skip  # noqa: E402


def utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class TestParse(unittest.TestCase):
    def test_cron_time(self):
        self.assertEqual(parse_cron_time("43 8 * * 1-5"), (8, 43))
        self.assertEqual(parse_cron_time("17 12 * * 1-5"), (12, 17))
        self.assertIsNone(parse_cron_time("*/5 * * * *"))
        self.assertIsNone(parse_cron_time("60 8 * * *"))
        self.assertIsNone(parse_cron_time(""))
        self.assertIsNone(parse_cron_time(None))

    def test_iso(self):
        self.assertEqual(parse_iso("2026-11-25T08:45:00Z"), utc(2026, 11, 25, 8, 45))
        self.assertIsNone(parse_iso(""))
        self.assertIsNone(parse_iso("not a date"))


class TestDelay(unittest.TestCase):
    def test_delay_same_day(self):
        # 排程 08:43 UTC，實際 09:52 啟動
        self.assertEqual(schedule_delay_minutes("43 8 * * 1-5", utc(2026, 11, 25, 9, 52)), 69.0)

    def test_delay_across_midnight(self):
        # 排程 23:50 UTC，隔天 00:20 才啟動 -> 30 分鐘，而不是 -1410
        self.assertEqual(schedule_delay_minutes("50 23 * * *", utc(2026, 11, 26, 0, 20)), 30.0)

    def test_unsupported_cron_returns_none(self):
        self.assertIsNone(schedule_delay_minutes("*/5 * * * *", utc(2026, 11, 25, 9, 0)))


class TestShouldSkip(unittest.TestCase):
    NOW = utc(2026, 11, 25, 9, 52)

    def test_non_schedule_events_always_run(self):
        for ev in ("workflow_dispatch", "push", "repository_dispatch"):
            skip, _ = should_skip(ev, "2026-11-25T09:50:00Z", self.NOW)
            self.assertFalse(skip, ev)

    def test_scheduled_run_skipped_when_dispatch_just_updated_data(self):
        # Cloudflare 於 08:45 準時觸發並更新；GitHub 備援排程 09:52 才到 (67 分鐘後)
        skip, reason = should_skip("schedule", "2026-11-25T08:45:00Z", self.NOW)
        self.assertTrue(skip)
        self.assertIn("略過", reason)

    def test_scheduled_run_executes_when_data_is_old(self):
        # 上次更新是昨天 -> 必須執行
        skip, _ = should_skip("schedule", "2026-11-24T12:20:00Z", self.NOW)
        self.assertFalse(skip)

    def test_two_daily_slots_do_not_block_each_other(self):
        # 08:43 與 12:17 兩個時段相隔 3.5 小時，後者不應被前者的更新擋掉
        skip, _ = should_skip("schedule", "2026-11-25T08:45:00Z", utc(2026, 11, 25, 12, 20))
        self.assertFalse(skip)

    def test_boundary_is_exclusive(self):
        skip, _ = should_skip("schedule", "2026-11-25T08:22:00Z", self.NOW, min_gap_minutes=90)  # 剛好 90 分鐘
        self.assertFalse(skip)

    def test_fail_open_when_last_update_unknown_or_in_future(self):
        self.assertFalse(should_skip("schedule", None, self.NOW)[0])
        self.assertFalse(should_skip("schedule", "garbage", self.NOW)[0])
        self.assertFalse(should_skip("schedule", "2026-11-25T11:00:00Z", self.NOW)[0])


if __name__ == "__main__":
    unittest.main()
