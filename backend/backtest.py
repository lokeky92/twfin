"""
前瞻追蹤回測 (Forward / live out-of-sample tracking)

為什麼是「前瞻」：模型分數的歷史無法事後重建 —— 分數由每日的營收、估值與法人資料重算，這些資料
只有最新一期；若拿今天的分數去「驗證」過去的行情，等於已經看過答案。所以唯一誠實的做法是：
從開始累積快照 (industry_score_history) 的那天起，每天記下當時的分數與預警等級，之後用實際發生的類股指數
報酬來檢驗。真正的樣本外 = 快照日之後才發生的行情。

方法 (全部可由資料庫重現，不含任何手寫數字)：
- 訊號：每日快照中各產業的綜合分數與預警等級。
- 進場：快照日「之後的第一個交易日」收盤 (快照在收盤後產生，當天收盤價無法成交，這樣不會偷看當天)。
- 報酬：進場後 H 個交易日的「類股報酬指數相對加權報酬指數」超額報酬 (H = 5 / 10 / 20)。
  使用含息的報酬指數，避免除息日扭曲。
- 尚未滿 H 個交易日的訊號不計入，只顯示「還需累積幾個交易日」。
- 評估：
  * 看多訊號 (LEVEL 3/4)：超額報酬 > 0 算命中；LEVEL R：超額報酬 < 0 算成功避險。
  * 截面 IC：每個快照日，產業總分與其後超額報酬的 Spearman 等級相關 (越高越好，0 代表沒有預測力)。
  * 高低分價差：總分前 3 名與後 3 名的平均超額報酬差。
- 樣本不足 (成熟訊號 < 30 筆或 IC 日數 < 20 天) 時照實標示，不當成結論。

只採用 score_source='live' 的快照 (見 history.py、live_scoring.py)：改為即時評分之前的快照用的是手寫種子分數，
拿來「驗證」沒有意義，所以不納入；樣本從第一個即時快照日開始累積。

限制：產業與類股指數只是近似對應 (見 INDUSTRY_INDEX_MAP)；5 項子分數皆為代理指標，
所以這主要在檢驗「目前這組排名」的持續性；相鄰快照日的報酬區間重疊，有效樣本比筆數少。
"""
import json
from bisect import bisect_right

from data_health import parse_date
from scoring import classify_alert_level, effective_thresholds

BENCHMARK_INDEX = "發行量加權股價報酬指數"
HORIZONS = (5, 10, 20)               # 交易日
MIN_SIGNALS_FOR_RATES = 30           # 命中率至少要有這麼多筆成熟訊號才算有意義
MIN_DATES_FOR_IC = 20                # IC 至少要有這麼多個快照日才算有意義
BULL_LEVELS = ("LEVEL 3", "LEVEL 4")
RISK_LEVEL = "LEVEL R"

# 本系統產業 -> 證交所類股 (報酬) 指數。多為「最接近」的近似，題材型產業 (散熱、CPO 等) 沒有專屬指數，
# 這個對照也會顯示在畫面上，讓使用者知道每個產業是用哪條指數檢驗的。
INDUSTRY_INDEX_MAP = {
    "IND_SEMI_FOUNDRY": "臺灣晶圓製造報酬指數",
    "IND_SEMI_EQUIP": "半導體類報酬指數",
    "IND_IC_DESIGN": "特選臺灣IC設計報酬指數",
    "IND_AI_SERVER": "電腦及週邊設備類報酬指數",
    "IND_THERMAL": "其他電子類報酬指數",
    "IND_CPO_NET": "通信網路類報酬指數",
    "IND_PCB_ABF": "電子零組件類報酬指數",
    "IND_FIN_HOLDING": "金融保險類報酬指數",
    "IND_SHIPPING": "航運類報酬指數",
    "IND_POWER_GREEN": "電機機械類報酬指數",
    "IND_CONSTRUCTION": "建材營造類報酬指數",
    "IND_STEEL_PLASTIC": "鋼鐵類報酬指數",
    "IND_MACH_AUTO": "汽車類報酬指數",
    "IND_BIO_RETAIL": "生技醫療類報酬指數",
}

CAVEATS = [
    "只統計快照日「之後」實際發生的行情 (前瞻追蹤)；模型分數的歷史無法事後重建，因此不提供事後回測。",
    "進場為快照日之後第一個交易日的收盤，報酬為相對加權報酬指數的超額報酬，且使用含息的報酬指數。",
    "產業與類股指數只是近似對應，題材型產業 (散熱、CPO 等) 沒有專屬指數。",
    "只統計即時評分 (官方資料重算) 的快照；5 項子分數都是代理指標；相鄰快照日的報酬區間重疊，有效樣本比筆數少。",
    "成熟訊號少於 30 筆或快照日少於 20 天時，數字只供觀察，不是結論。",
]


# ---------------------------------------------------------------------------
# 純函式 (不碰資料庫，方便測試)
# ---------------------------------------------------------------------------
def forward_relative_return(series, bench, signal_date, horizon):
    """
    series / bench: {date: close}。回傳 (超額報酬%, 進場日, 出場日)；尚未滿 horizon 個交易日回傳 None。
    進場 = 訊號日之後 (不含當天) 的第一個共同交易日；出場 = 進場後第 horizon 個共同交易日。
    """
    common = sorted(set(series) & set(bench))
    entry_i = bisect_right(common, signal_date)
    exit_i = entry_i + horizon
    if entry_i >= len(common) or exit_i >= len(common):
        return None
    e, x = common[entry_i], common[exit_i]
    if not (series[e] and series[x] and bench[e] and bench[x]):
        return None
    rel = ((series[x] / series[e] - 1.0) - (bench[x] / bench[e] - 1.0)) * 100.0
    return round(rel, 4), e, x


def _ranks(values):
    """平均等級 (處理同分)。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x, y):
    """Spearman 等級相關；樣本少於 3 或任一邊完全沒有變化時回傳 None。"""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sx = sum((a - mx) ** 2 for a in rx)
    sy = sum((b - my) ** 2 for b in ry)
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy) ** 0.5


def evaluate(snapshots, series_by_industry, bench, horizons=HORIZONS):
    """
    snapshots: [{snapshot_date(date), industry_id, total, level}]
    回傳 [{snapshot_date, industry_id, total, level, horizon, rel_pct, entry, exit}]  (只含已成熟的訊號)
    """
    out = []
    for s in snapshots:
        series = series_by_industry.get(s["industry_id"])
        if not series:
            continue
        for h in horizons:
            r = forward_relative_return(series, bench, s["snapshot_date"], h)
            if r is None:
                continue
            out.append({**s, "horizon": h, "rel_pct": r[0], "entry": r[1], "exit": r[2]})
    return out


def _mean(xs):
    return round(sum(xs) / len(xs), 3) if xs else None


def summarize_horizon(records, total_signals, horizon):
    rows = [r for r in records if r["horizon"] == horizon]
    by_date = {}
    for r in rows:
        by_date.setdefault(r["snapshot_date"], []).append(r)

    levels = []
    for lv in ("LEVEL 4", "LEVEL 3", "LEVEL 2", "LEVEL 1", RISK_LEVEL):
        sub = [r for r in rows if r["level"] == lv]
        if not sub:
            continue
        item = {"level": lv, "n": len(sub), "mean_rel_pct": _mean([r["rel_pct"] for r in sub]), "hit_rate_pct": None, "hit_definition": None}
        if lv in BULL_LEVELS:
            item["hit_rate_pct"] = round(100.0 * sum(1 for r in sub if r["rel_pct"] > 0) / len(sub), 1)
            item["hit_definition"] = "超額報酬 > 0"
        elif lv == RISK_LEVEL:
            item["hit_rate_pct"] = round(100.0 * sum(1 for r in sub if r["rel_pct"] < 0) / len(sub), 1)
            item["hit_definition"] = "超額報酬 < 0 (成功避險)"
        levels.append(item)

    ics, spreads = [], []
    for d, group in sorted(by_date.items()):
        if len(group) >= 8:
            ic = spearman([g["total"] for g in group], [g["rel_pct"] for g in group])
            if ic is not None:
                ics.append(ic)
        if len(group) >= 6:
            ordered = sorted(group, key=lambda g: g["total"], reverse=True)
            spreads.append(_mean([g["rel_pct"] for g in ordered[:3]]) - _mean([g["rel_pct"] for g in ordered[-3:]]))

    bull = [r for r in rows if r["level"] in BULL_LEVELS or r["level"] == RISK_LEVEL]
    return {
        "horizon": horizon,
        "matured_signals": len(rows),
        "pending_signals": max(0, total_signals - len(rows)),
        "matured_dates": len(by_date),
        "enough_for_rates": len(bull) >= MIN_SIGNALS_FOR_RATES,
        "enough_for_ic": len(ics) >= MIN_DATES_FOR_IC,
        "levels": levels,
        "ic": ({"mean": round(sum(ics) / len(ics), 3), "positive_pct": round(100.0 * sum(1 for i in ics if i > 0) / len(ics), 1),
                "dates": len(ics)} if ics else None),
        "top_bottom_spread_pct": (round(sum(spreads) / len(spreads), 3) if spreads else None),
        "spread_dates": len(spreads),
    }


# ---------------------------------------------------------------------------
# 資料庫存取
# ---------------------------------------------------------------------------
def _load_series(cur, names):
    out = {}
    for name in names:
        cur.execute("SELECT trade_date, close_index FROM live_market_indices WHERE index_name = ? AND close_index IS NOT NULL", (name,))
        series = {}
        for r in cur.fetchall():
            d = parse_date(r["trade_date"])
            if d is not None and r["close_index"]:
                series[d] = float(r["close_index"])
        out[name] = series
    return out


def load_inputs(conn):
    """
    讀取前瞻追蹤共用的輸入 (回測與規則模擬器共用)：
    回傳 (model, snapshots, series_by_industry, bench)；沒有啟用中的模型或舊資料庫尚未建表時回傳 None。
    """
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
        model = cur.fetchone()
        if not model:
            return None
        th = effective_thresholds(json.loads(model["thresholds_json"]))
        cur.execute("""
            SELECT h.*, t.industry_name FROM industry_score_history h
            LEFT JOIN industry_taxonomy t ON t.industry_id = h.industry_id
            WHERE h.model_version = ? AND h.total_weighted_score IS NOT NULL
              AND h.score_source = 'live'   -- 種子分數不是預測：只採用由官方即時資料算出的快照
            ORDER BY h.snapshot_date
        """, (model["version_id"],))
        rows = [dict(r) for r in cur.fetchall()]
    except Exception:  # noqa: BLE001 — 舊資料庫尚未建表
        return None

    snapshots = []
    for r in rows:
        d = parse_date(r["snapshot_date"])
        if d is None:
            continue
        level = r.get("alert_level") or classify_alert_level(r["total_weighted_score"], r["score_capital_flow"], th)
        snapshots.append({"snapshot_date": d, "industry_id": r["industry_id"], "industry_name": r.get("industry_name"),
                          "total": r["total_weighted_score"], "level": level})

    names = sorted(set(INDUSTRY_INDEX_MAP.values()) | {BENCHMARK_INDEX})
    series_all = _load_series(cur, names)
    bench = series_all.get(BENCHMARK_INDEX, {})
    series_by_industry = {iid: series_all.get(idx, {}) for iid, idx in INDUSTRY_INDEX_MAP.items()}
    return model, snapshots, series_by_industry, bench


def compute_live_backtest(conn):
    base = {"available": False, "caveats": CAVEATS, "horizons": list(HORIZONS), "min_signals": MIN_SIGNALS_FOR_RATES,
            "min_dates": MIN_DATES_FOR_IC, "benchmark": BENCHMARK_INDEX}
    loaded = load_inputs(conn)
    if loaded is None:
        return base
    model, snapshots, series_by_industry, bench = loaded

    snap_dates = sorted({s["snapshot_date"] for s in snapshots})
    index_dates = sorted(bench)
    first = snap_dates[0] if snap_dates else None
    days_after_first = len([d for d in index_dates if first and d > first])

    mapping = [{"industry_id": iid, "index_name": idx, "index_points": len(series_by_industry[iid])}
               for iid, idx in INDUSTRY_INDEX_MAP.items()]
    records = evaluate(snapshots, series_by_industry, bench)
    total_per_h = len([s for s in snapshots if series_by_industry.get(s["industry_id"])])

    horizons = []
    for h in HORIZONS:
        item = summarize_horizon(records, total_per_h, h)
        item["trading_days_needed"] = max(0, h + 1 - days_after_first)   # 進場日 + h 個交易日才有第一筆成熟訊號
        horizons.append(item)

    return {
        **base,
        "available": True,
        "model_version": model["version_id"],
        "snapshot_days": len(snap_dates),
        "first_snapshot": first.isoformat() if first else None,
        "last_snapshot": snap_dates[-1].isoformat() if snap_dates else None,
        "index_last_date": index_dates[-1].isoformat() if index_dates else None,
        "index_trading_days_after_first_snapshot": days_after_first,
        "signal_count": len(snapshots),
        "horizon_results": horizons,
        "mapping": mapping,
        "any_matured": any(h["matured_signals"] for h in horizons),
    }
