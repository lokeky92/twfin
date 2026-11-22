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
        print("Live OpenAPI Ingestion:", live_res)
        build_and_compute_etf_center()
        export_standalone()
        print_health_summary()
    elif args.probe:
        res = probe_live_sources()
        for r in res:
            print(f"[{r['status']}] {r['source_id']}: {r['message']}")
        export_standalone()
    elif args.health_report:
        print_health_summary()

if __name__ == "__main__":
    main()
