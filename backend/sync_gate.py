"""
排程閘門與延遲量測 (給 GitHub Actions 使用)

背景：GitHub 的 `schedule` 觸發不準時，實測常延遲 60~80 分鐘。解法是讓 Cloudflare Worker 的 cron
(準時) 以 workflow_dispatch 觸發同步，GitHub 自己的排程保留作為備援。兩者同時存在時，晚到的那一次
若發現資料庫剛更新過，就沒必要再抓一次官方 API，由本模組判斷後跳過。

規則：
- 只有 event == schedule 才可能被跳過；手動與 Cloudflare 觸發 (workflow_dispatch)、push 一律執行。
- 距離上次成功更新 (data-latest 資料庫附件的更新時間) 不到 min_gap 分鐘 → 跳過。
- 查不到上次更新時間 (首次、API 失敗) → 不跳過 (寧可多跑一次，也不要漏掉更新)。

同時把「排程預定時間 vs 實際啟動時間」寫進 step summary，方便長期追蹤延遲。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

DEFAULT_MIN_GAP_MINUTES = 90


def parse_iso(value):
    """解析 GitHub API 的 ISO 時間 (結尾 Z)；無法解析回傳 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_cron_time(cron):
    """'43 8 * * 1-5' -> (8, 43)；只支援「固定分、固定時」的簡單格式，其他回傳 None。"""
    parts = str(cron or "").split()
    if len(parts) != 5 or not (parts[0].isdigit() and parts[1].isdigit()):
        return None
    minute, hour = int(parts[0]), int(parts[1])
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        return None
    return hour, minute


def schedule_delay_minutes(cron, now):
    """排程預定時間 (UTC) 到 now 的延遲分鐘數；取最近一次已過的預定時間，跨午夜也正確。"""
    t = parse_cron_time(cron)
    if t is None:
        return None
    scheduled = now.replace(hour=t[0], minute=t[1], second=0, microsecond=0)
    if scheduled > now:   # 預定時間在「現在之後」代表指的是前一天
        scheduled -= timedelta(days=1)
    return round((now - scheduled).total_seconds() / 60.0, 1)


def should_skip(event_name, last_update_iso, now, min_gap_minutes=DEFAULT_MIN_GAP_MINUTES):
    """回傳 (skip: bool, reason: str)。"""
    if event_name != "schedule":
        return False, f"事件為 {event_name}，一律執行"
    last = parse_iso(last_update_iso)
    if last is None:
        return False, "查不到上次更新時間，照常執行"
    age_min = (now - last).total_seconds() / 60.0
    if age_min < 0:
        return False, "上次更新時間在未來 (時鐘異常)，照常執行"
    if age_min < min_gap_minutes:
        return True, f"資料庫 {age_min:.0f} 分鐘前才剛更新 (< {min_gap_minutes} 分鐘)，略過這次備援排程"
    return False, f"資料庫已 {age_min:.0f} 分鐘未更新，執行同步"


def _last_db_update(repo, tag, asset_name):
    """用 gh CLI 取得 data-latest 資料庫附件的更新時間；失敗回傳 None。"""
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{repo}/releases/tags/{tag}"],
            capture_output=True, text=True, encoding="utf-8", timeout=60, check=True,
        ).stdout
        for asset in json.loads(out).get("assets", []):
            if asset.get("name") == asset_name:
                return asset.get("updated_at")
    except Exception as exc:  # noqa: BLE001 — 查不到就照常執行
        print(f"::notice title=sync gate::無法取得上次更新時間 ({type(exc).__name__})，照常執行")
    return None


def _write(path_env, text):
    path = os.environ.get(path_env)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def main():
    for stream in (sys.stdout, sys.stderr):   # Windows 中文字碼頁 (cp950) 無法輸出 emoji，改成 UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-gap-minutes", type=int, default=DEFAULT_MIN_GAP_MINUTES)
    ap.add_argument("--tag", default=os.environ.get("DB_RELEASE_TAG", "data-latest"))
    ap.add_argument("--asset", default="twfin_intelligence.db")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    cron = os.environ.get("EVENT_SCHEDULE", "")

    last = _last_db_update(repo, args.tag, args.asset) if event == "schedule" and repo else None
    skip, reason = should_skip(event, last, now, args.min_gap_minutes)

    lines = [f"### 排程閘門", f"- 事件：`{event}`"]
    delay = schedule_delay_minutes(cron, now) if event == "schedule" else None
    if delay is not None:
        lines.append(f"- 排程 `{cron}` (UTC) 實際啟動延遲：**{delay} 分鐘**")
    lines.append(f"- 判定：{'⏭️ 跳過' if skip else '▶️ 執行'} — {reason}")
    print("\n".join(lines))
    _write("GITHUB_STEP_SUMMARY", "\n".join(lines) + "\n")
    _write("GITHUB_OUTPUT", f"skip={'true' if skip else 'false'}\n")
    if delay is not None:
        print(f"schedule_delay_minutes={delay}")


if __name__ == "__main__":
    main()
