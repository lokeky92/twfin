"""
台灣經濟資金流向與產業趨勢預警研究中心 (Taiwan Capital Flow Intelligence & Industry Rotation System)
第六階段：正式運行自動化更新、資料品質異常監測、模型回測驗證與報告匯出 CLI 守護程序
用法：
  python backend/run_pipeline.py --all          # 執行全流程：DB初始化 -> 數據更新 -> 資料品質檢查 -> 評分預警 -> 回測驗證 -> 匯出雙模式儀表板
  python backend/run_pipeline.py --probe        # 執行官方 API 端點連線測試與離線備援檢查
  python backend/run_pipeline.py --health-report# 輸出正式運行系統健康度與監控報告
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_connection, init_database
from seed_and_engine import seed_and_compute_all
from phase2_to_6_engine import populate_phase2_to_phase6
from live_api_connector import run_live_ingestion
from etf_engine import build_and_compute_etf_center
from server import get_dashboard_payload, probe_live_sources
from export_standalone import export_standalone
from history import snapshot_industry_scores
from live_scoring import apply_live_scoring
from live_watchlist import apply_live_watchlist
from live_reports import apply_live_reports
from etf_live import apply_live_etf
from macro_live import apply_live_macro

def report_ingestion_health(statuses, critical):
    """把各來源狀態輸出成 GitHub Actions annotation；關鍵來源失敗回傳 1，讓排程失敗而不發佈過期資料。"""
    for key, status in sorted(statuses.items()):
        if status != "OK":
            print(f"::warning title=資料來源 {key} 狀態 {status}::請查看儀表板「資料新鮮度」面板或 data_source_status 表")
    if critical:
        print(f"::error title=關鍵資料來源失敗::{', '.join(critical)} 擷取失敗或沒有資料，已中止發佈以避免公佈過期數據")
        return 1
    return 0


def print_health_summary():
    d = get_dashboard_payload()
    print("=" * 88)
    print("【台灣經濟資金流向與產業趨勢預警研究中心｜Fable 5.2 全階段正式運行監控總覽】")
    print("=" * 88)
    print(f"• 系統時間：{d['generated_at']} ｜ 啟用模型版本：{d['active_model']['version_id']}")
    print(f"• 總體與國際指標數：{len(d['macro_latest'])} 項 ｜ 資產配置流向矩陣：{len(d['asset_flows'])} 條")
    print(f"• 產業分類總數：{len(d['industries'])} 類 (已評分 13 類 / 防呆攔截不可評分 1 類)")
    print(f"• 三大法人日/週/月/季籌碼紀錄：{len(d['institutional_flows'])} 筆")
    print(f"• 多因子提前預警訊號：{len(d['warnings'])} 則 ｜ 個股研究名單：{len(d['companies'])} 家")
    if d["backtest_runs"]:
        bt = d["backtest_runs"][0]
        print(f"• 樣本外歷史回測 ({bt['run_id']})：樣本數={bt['sample_count']} | 命中率={bt['hit_rate_pct']}% | "
              f"誤報率={bt['false_positive_pct']}% | 漏報率={bt['false_negative_pct']}% | "
              f"平均提前={bt['avg_lead_time_days']}天 | 超額報酬=+{bt['model_cum_excess_return_pct']}%")
    print(f"• 固定研究報告中心：{len(d['research_reports'])} 份 (含每日/每週/每月/每季完整報告)")
    print(f"• 資料品質與SLA異常檢查：{len(d['dq_checks'])} 項")
    for chk in d["dq_checks"]:
        print(f"   - [{chk['status']}] {chk['check_id']} ({chk['check_type']}): {chk['target_table_or_metric']}")
    print("=" * 88)

def main():
    parser = argparse.ArgumentParser(description="TWFin Capital Flow Intelligence Pipeline CLI")
    parser.add_argument("--all", action="store_true", help="Run full Phase 1-6 pipeline and export standalone dashboard")
    parser.add_argument("--probe", action="store_true", help="Probe external official APIs with failover logging")
    parser.add_argument("--health-report", action="store_true", help="Print production health report")
    args = parser.parse_args()

    if args.all or not (args.probe or args.health_report):
        seed_and_compute_all()
        populate_phase2_to_phase6()
        live_res = run_live_ingestion()
        shared_map = live_res.pop("shared_insti_map", None) if isinstance(live_res, dict) else None
        critical = live_res.get("critical_failures", []) if isinstance(live_res, dict) else []
        print("Live OpenAPI Ingestion:", live_res)
        build_and_compute_etf_center(shared_insti_map=shared_map)
        print("Live ETF (TW):", apply_live_etf())
        # 總體月統計 (央行／國發會／財政部／選用的 FRED)：失敗只記錄，保留既有資料，不讓整個同步失敗
        try:
            print("Live macro:", apply_live_macro())
        except Exception as _e:  # noqa: BLE001
            print(f"::warning title=總體資料更新失敗::{type(_e).__name__}: {_e}")
        print("Live industry scoring:", apply_live_scoring())
        print(f"Industry score snapshot rows: {snapshot_industry_scores()}")
        print("Live watchlist:", apply_live_watchlist())
        print("Live research reports:", apply_live_reports())
        # 多代理即時稽核 (唯讀資料庫)：必須在所有即時化步驟之後、匯出之前，才看得到「即將發布」的最終狀態
        # (每次排程一開始都會重灌手寫種子列，太早稽核會把中途狀態誤判成重複／手寫)；失敗只記錄，不讓整個同步失敗
        try:
            from argon_multi_agent.engine.live_audit_session import run_live_audit_session
            _b = run_live_audit_session()
            print("Live audit session:", _b["session_id"], "integrity:", _b["production_integrity_verified"], "proposals:", len(_b["phase6_proposals"]))
        except Exception as _e:  # noqa: BLE001
            print(f"::warning title=多代理即時稽核失敗::{type(_e).__name__}: {_e}")
        export_standalone()
        print_health_summary()
        sys.exit(report_ingestion_health(live_res.get("health", {}) if isinstance(live_res, dict) else {}, critical))
    elif args.probe:
        res = probe_live_sources()
        for r in res:
            print(f"[{r['status']}] {r['source_id']}: {r['message']}")
        export_standalone()
    elif args.health_report:
        print_health_summary()

if __name__ == "__main__":
    main()
