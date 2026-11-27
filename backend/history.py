"""
產業評分歷史快照：每次排程把「當下啟用模型」的各產業分數與預警等級存成一筆 (快照日, 產業, 模型版本)，
同一天重跑會覆蓋，不會重複累積。這是前瞻追蹤回測 (backtest.py) 的訊號來源：累積足夠天數後，
才能用快照日之後實際發生的行情檢驗預警與排名是否有預測力。

score_source 欄位標示快照當下的子分數來源：'live' = 由官方即時資料重算 (live_scoring.py)、'seed' = 內建種子值。
前瞻回測只採用 'live' 快照，種子分數不會被當成「預測」。
"""
import json

from db import get_connection, init_database
from common import now_tw
from scoring import classify_alert_level, effective_thresholds


def snapshot_industry_scores(snapshot_date=None):
    """寫入今日快照，回傳寫入的產業數。預警等級依當下生效的門檻判定並一併存下。"""
    init_database()
    conn = get_connection()
    cur = conn.cursor()
    snap = snapshot_date or now_tw().date().isoformat()
    cur.execute("SELECT version_id, thresholds_json FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        conn.close()
        return 0
    version = row["version_id"]
    th = effective_thresholds(json.loads(row["thresholds_json"]))
    cur.execute("""
        SELECT industry_id, model_version, total_weighted_score, score_capital_flow, score_fundamentals,
               score_future_growth, score_institutional, score_valuation, rotation_state, score_source
        FROM industry_rotation_scores WHERE model_version = ?
    """, (version,))
    n = 0
    for r in cur.fetchall():
        level = classify_alert_level(r["total_weighted_score"], r["score_capital_flow"], th)
        cur.execute("""
            INSERT OR REPLACE INTO industry_score_history
            (snapshot_date, industry_id, model_version, total_weighted_score, score_capital_flow, score_fundamentals,
             score_future_growth, score_institutional, score_valuation, rotation_state, alert_level, score_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (snap, r["industry_id"], r["model_version"], r["total_weighted_score"], r["score_capital_flow"],
              r["score_fundamentals"], r["score_future_growth"], r["score_institutional"], r["score_valuation"],
              r["rotation_state"], level, r["score_source"]))
        n += 1
    conn.commit()
    conn.close()
    return n


def history_summary():
    """給儀表板顯示：已累積幾天、哪一天開始。"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(DISTINCT snapshot_date) AS days, MIN(snapshot_date) AS first, MAX(snapshot_date) AS last "
                    "FROM industry_score_history")
        r = cur.fetchone()
        return {"days": r["days"] or 0, "first": r["first"], "last": r["last"]}
    except Exception:  # noqa: BLE001 — 舊資料庫尚未建表時不影響儀表板
        return {"days": 0, "first": None, "last": None}
    finally:
        conn.close()
