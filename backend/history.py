"""
產業評分歷史快照：每次排程把「當下啟用模型」的各產業分數存成一筆 (快照日, 產業, 模型版本)，
同一天重跑會覆蓋，不會重複累積。累積足夠天數後，才有辦法計算預警後的實際表現 (命中率回測)。

注意：目前部分子分數 (成長性、基本面等) 仍來自內建種子資料，快照分數在短期內變動有限，
真正會每日變動的是資金流向/法人/估值相關的即時資料。
"""
from db import get_connection, init_database
from common import now_tw


def snapshot_industry_scores(snapshot_date=None):
    """寫入今日快照，回傳寫入的產業數。"""
    init_database()
    conn = get_connection()
    cur = conn.cursor()
    snap = snapshot_date or now_tw().date().isoformat()
    cur.execute("SELECT version_id FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        conn.close()
        return 0
    version = row["version_id"]
    cur.execute("""
        INSERT OR REPLACE INTO industry_score_history
        (snapshot_date, industry_id, model_version, total_weighted_score, score_capital_flow, score_fundamentals,
         score_future_growth, score_institutional, score_valuation, rotation_state)
        SELECT ?, industry_id, model_version, total_weighted_score, score_capital_flow, score_fundamentals,
               score_future_growth, score_institutional, score_valuation, rotation_state
        FROM industry_rotation_scores WHERE model_version = ?
    """, (snap, version))
    n = cur.rowcount
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
