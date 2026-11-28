"""
產業評分歷史快照：每次排程把「當下啟用模型」的各產業分數與預警等級存成一筆 (快照日, 產業, 模型版本)，
同一天重跑會覆蓋，不會重複累積。這是前瞻追蹤回測 (backtest.py) 的訊號來源：累積足夠天數後，
才能用快照日之後實際發生的行情檢驗預警與排名是否有預測力。

score_source 欄位標示快照當下的子分數來源：'live' = 由官方即時資料重算 (live_scoring.py)、'seed' = 內建種子值。
前瞻回測兩種快照都納入 (都是「當時就記下」的紀錄)，但結果會揭露每個快照日的分數來源 (snapshot_sources)。
"""
import json

from db import get_connection, init_database
from common import now_tw
from scoring import classify_alert_level, effective_thresholds


def _latest_trade_date(cur):
    """即時評分用的是最新交易日的收盤資料；快照日用「資料日期」而不是執行日期，
    這樣週末／假日重跑不會把同一份資料記成新的一天 (灌水快照日數與樣本數)。沒有即時評分資料時回傳 None。"""
    try:
        r = cur.execute("SELECT MAX(trade_date) AS d FROM live_industry_daily").fetchone()
        live = cur.execute("SELECT COUNT(*) AS n FROM industry_rotation_scores WHERE score_source = 'live'").fetchone()
        return r["d"] if (r and r["d"] and live and live["n"]) else None
    except Exception:  # noqa: BLE001 — 舊資料庫尚未建表
        return None


def snapshot_industry_scores(snapshot_date=None):
    """寫入今日快照，回傳寫入的產業數。預警等級依當下生效的門檻判定並一併存下。"""
    init_database()
    conn = get_connection()
    cur = conn.cursor()
    snap = snapshot_date or _latest_trade_date(cur) or now_tw().date().isoformat()
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
    if not snapshot_date:
        # 清掉先前以「執行日期」記下、但日期晚於最新資料日的快照 (含未評分產業的 seed 來源列，不分來源) (例如週六凌晨重跑所產生的重複一天)
        conn.execute("DELETE FROM industry_score_history WHERE snapshot_date > ?", (snap,))   # 另開 cursor，不破壞上面尚未取出的查詢
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
