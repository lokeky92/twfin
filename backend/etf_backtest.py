"""
ETF 前瞻追蹤 (Forward tracking of the ETF A/B scores)

取代舊的手寫「ETF 模型回測」：那些數字是預先寫好的，沒有可重現的來源。這裡改成與產業前瞻追蹤相同的方法：
- 每次即時評分 (etf_live.apply_live_etf) 時，把當時的 A/B 分數與結論寫入 etf_score_history。
- 之後用「快照日之後實際發生的行情」檢驗：ETF 相對加權指數的超額報酬 (H = 5 / 10 / 20 個交易日)。
- 進場 = 快照日之後第一個共同交易日收盤；尚未成熟的訊號不計，只顯示還需累積幾個交易日。
- 檢驗兩個模型：
    模型 B (短中期)：結論 → 偽等級；「條件相對有利」超額報酬 > 0 算命中，「風險偏高」超額報酬 < 0 算成功避險。
    模型 A (長期)：「適合進一步研究」超額報酬 > 0 算命中 (長期模型本來就不是為 5~20 天設計，這裡只是誠實地檢驗它)。
  另提供每個快照日的截面 Spearman IC 與高低分價差 (ETF 檔數少，門檻較低：每日至少 8 檔)。
- 槓桿／反向型不納入 (它們的「風險偏高」是結構性的，會灌水命中率)。

報酬為「價格報酬」(不含配息)，基準是加權「價格」指數，兩者同口徑；配息會使 ETF 在除息日下跌，
所以高配息 ETF 會被系統性低估 —— 這是已知偏誤，畫面會標示。ETF 分割或反分割造成的單日大幅跳動
(超過 35%) 視為不連續點，該日報酬不計入。

樣本不足 (成熟訊號 < 30 筆或快照日 < 20 天) 時照實標示，不當成結論。
"""
from datetime import date

from backtest import HORIZONS, MIN_DATES_FOR_IC, MIN_SIGNALS_FOR_RATES, evaluate, summarize_horizon
from data_health import parse_date

BENCH_NAME = "發行量加權股價指數"
SPLIT_JUMP = 0.35
# 結論 → 偽等級 (借用產業追蹤的統計函式)；A / B 兩個模型各自一套
LEVEL_B = {"條件相對有利": "LEVEL 4", "持續觀察": "LEVEL 2", "等待更佳條件": "LEVEL 1", "風險偏高": "LEVEL R"}
LEVEL_A = {"適合進一步研究": "LEVEL 4", "條件普通": "LEVEL 2", "需注意集中風險": "LEVEL 1"}
LEVEL_LABEL = {
    "B": {"LEVEL 4": "條件相對有利", "LEVEL 2": "持續觀察", "LEVEL 1": "等待更佳條件", "LEVEL R": "風險偏高"},
    "A": {"LEVEL 4": "適合進一步研究", "LEVEL 2": "條件普通", "LEVEL 1": "需注意集中風險"},
}

CAVEATS = [
    "只統計快照日「之後」實際發生的行情；ETF 分數的歷史無法事後重建，因此不提供事後回測。",
    "報酬為價格報酬 (不含配息)，基準為加權價格指數 (同口徑)；配息使 ETF 在除息日下跌，高配息 ETF 會被系統性低估。",
    "進場為快照日之後第一個交易日的收盤；ETF 分割／反分割造成的單日大幅跳動視為不連續點，不計入報酬。",
    "槓桿／反向型不納入；ETF 檔數少且彼此高度相關 (多數與大盤連動)，有效樣本比筆數少。",
    "成熟訊號少於 30 筆或快照日少於 20 天時，數字只供觀察，不是結論。",
]


def adjusted_series(rows):
    """[(日期, 收盤)] → {date: 還原後的指數化價格}。單日變動超過 SPLIT_JUMP 視為分割／資料斷點，該日報酬當作 0。"""
    out, level, prev = {}, 100.0, None
    for d, c in sorted(rows):
        dt = parse_date(d)
        if dt is None or not c:
            continue
        if prev is not None:
            r = c / prev - 1.0
            if abs(r) <= SPLIT_JUMP:
                level *= 1.0 + r
        out[dt] = level
        prev = c
    return out


def build_snapshots(rows, model):
    """etf_score_history 列 → evaluate() 用的 snapshots。model: 'A' / 'B'。略過槓桿型與沒有對應等級的結論。"""
    mapping = LEVEL_B if model == "B" else LEVEL_A
    out = []
    for r in rows:
        if r["is_leveraged"]:
            continue
        d = parse_date(r["snapshot_date"])
        score = r["score_b"] if model == "B" else r["score_a"]
        level = mapping.get(r["conclusion_b"] if model == "B" else r["conclusion_a"])
        if d is None or score is None or level is None:
            continue
        out.append({"snapshot_date": d, "industry_id": r["etf_code"], "total": score, "level": level})
    return out


def _relabel(horizon_result, model):
    for lv in horizon_result["levels"]:
        lv["label"] = LEVEL_LABEL[model].get(lv["level"], lv["level"])
    return horizon_result


def compute_etf_forward(conn):
    base = {"available": False, "caveats": CAVEATS, "horizons": list(HORIZONS), "min_signals": MIN_SIGNALS_FOR_RATES,
            "min_dates": MIN_DATES_FOR_IC, "benchmark": BENCH_NAME, "snapshot_days": 0}
    try:
        cur = conn.cursor()
        rows = [dict(r) for r in cur.execute("SELECT * FROM etf_score_history ORDER BY snapshot_date")]
        bench_rows = [(r["trade_date"], r["close_index"]) for r in cur.execute(
            "SELECT trade_date, close_index FROM index_price_history WHERE index_name = ?", (BENCH_NAME,))]
        price_rows = {}
        for r in cur.execute("SELECT etf_code, trade_date, close_price FROM etf_price_history WHERE close_price IS NOT NULL"):
            price_rows.setdefault(r["etf_code"], []).append((r["trade_date"], r["close_price"]))
    except Exception:  # noqa: BLE001 — 舊資料庫尚未建表
        return base
    if not rows:
        return base

    bench = {parse_date(d): float(c) for d, c in bench_rows if parse_date(d) and c}
    series = {code: adjusted_series(rs) for code, rs in price_rows.items()}
    snap_dates = sorted({parse_date(r["snapshot_date"]) for r in rows if parse_date(r["snapshot_date"])})
    first = snap_dates[0]
    index_dates = sorted(bench)
    days_after_first = len([d for d in index_dates if d > first])

    models = {}
    for model in ("B", "A"):
        snaps = build_snapshots(rows, model)
        records = evaluate(snaps, series, bench)
        total = len([s for s in snaps if series.get(s["industry_id"])])
        hs = []
        for h in HORIZONS:
            item = summarize_horizon(records, total, h)
            item["trading_days_needed"] = max(0, h + 1 - days_after_first)
            hs.append(_relabel(item, model))
        models[model] = {"signal_count": len(snaps), "horizon_results": hs}

    n_etfs = len({r["etf_code"] for r in rows if not r["is_leveraged"]})
    return {
        **base,
        "available": True,
        "snapshot_days": len(snap_dates),
        "first_snapshot": first.isoformat(),
        "last_snapshot": snap_dates[-1].isoformat(),
        "index_last_date": index_dates[-1].isoformat() if index_dates else None,
        "index_trading_days_after_first_snapshot": days_after_first,
        "etf_count": n_etfs,
        "models": models,
        "any_matured": any(h["matured_signals"] for m in models.values() for h in m["horizon_results"]),
    }
