"""
規則模擬器 (前瞻、固定規則)：把「依排名或預警等級進出場」的規則，用累積的每日評分快照加上真實類股報酬指數價格，
計算若照做會得到什麼績效，並和基準比較。

設計原則 (避免做出「看起來很準、其實沒用」的東西)：
- 只用快照日之後才發生的行情；不回頭拿現有分數去湊歷史曲線。
- 規則與參數在程式裡寫死 (前 3 名、LEVEL 3/4、每週調整、單邊成本 0.2%)，畫面上不提供調參數，
  避免看到結果後反覆調整而過度擬合。若要改，必須是有理由的程式修改，且新規則的績效從修改日起重新累積。
- 每個規則都和兩個基準並排：加權報酬指數 (買進持有)、全部可評分產業等權重 (同樣每週調整、同樣扣成本)。
  後者用來分辨「選產業的能力」與「單純押注類股」。
- 結果只是檢驗規則，不是買賣建議；期數不足 (預設 < 26 週) 時明確標示樣本不足。

規則：
  A「前 N 名輪動」：每週決策日持有總分最高的 3 個產業，等權重。
  B「依預警等級」：每週決策日持有預警等級為 LEVEL 3 / 4 的產業，等權重；沒有任何符合時持有現金。
時間線 (無未來資料)：
  決策日 = 每個「已結束的 ISO 週」中最後一個快照日 (最新快照所在的那一週尚未結算，不計入，所以過去結果不會被追溯改寫)；
  進場 = 決策日之後第一個交易日的收盤；持有到下一次進場。持有期間不再調整 (權重自然漂移)。
成本：每次調整，買進與賣出的成交金額各乘以單邊成本 (手續費 + 證交稅 + 滑價的保守估計 0.2%)，現金不計成本。
注意：類股指數本身不能直接買進，實際要用 ETF 或個股近似，會有追蹤誤差與溢價折價。
"""
from bisect import bisect_right

from backtest import BENCHMARK_INDEX, INDUSTRY_INDEX_MAP, load_inputs

TOP_N = 3
BULL_LEVELS = ("LEVEL 3", "LEVEL 4")
COST_ONE_WAY = 0.002          # 單邊成本 (比例)
MIN_PERIODS = 26              # 完整調整週期少於這個數字時標示樣本不足 (約半年)
REBALANCE = "每週"

CAVEATS = [
    "規則與參數固定、不可調整，避免看到結果後反覆調參數造成過度擬合；改規則時績效從修改日起重新累積。",
    "只統計決策日之後實際發生的行情；決策日是每週最後一個快照日，隔天收盤進場。",
    "每次調整依買進與賣出成交金額扣單邊成本 0.2% (手續費、證交稅與滑價的保守估計)。",
    "使用含息的類股報酬指數，指數本身不能直接買進，實務上要用 ETF 或個股近似，會有追蹤誤差與溢價折價。",
    "快照由兩種分數組成：開始即時評分之前的快照 (營收與法人輸入是官方資料，但 5 項子分數是內建種子值) 與之後的即時評分快照 (5 項子分數皆為代理指標，且是相對其他產業的百分位)；"
    "兩者尺度不同，規則 A 與 B 的持股會隨分數來源改變，績效差異同時反映選股規則、分數來源與產業本身的行情，請看「快照組成」。",
    "期數少於 26 週時，績效數字只供觀察，不是結論；這只是檢驗規則，不是買賣建議。",
]


# ---------------------------------------------------------------------------
# 純函式
# ---------------------------------------------------------------------------
def weekly_decision_dates(snapshot_dates):
    """每個「已結束的 ISO 週」最後一個快照日；最新快照所在的那一週尚未結算，不計入。"""
    ds = sorted(set(snapshot_dates))
    if not ds:
        return []
    current_week = ds[-1].isocalendar()[:2]
    last_in_week = {}
    for d in ds:
        last_in_week[d.isocalendar()[:2]] = d       # 由小到大掃過，後面的覆蓋前面的 = 該週最後一天
    return [d for wk, d in sorted(last_in_week.items()) if wk != current_week]


def rule_top_n(rows, n=TOP_N):
    """rows: 該決策日的快照列 [{industry_id, total, level}]；回傳 {industry_id: 權重}。"""
    ranked = sorted(rows, key=lambda r: (-r["total"], r["industry_id"]))[:n]
    return {r["industry_id"]: 1.0 / len(ranked) for r in ranked} if ranked else {}


def rule_alert_levels(rows):
    held = [r for r in rows if r["level"] in BULL_LEVELS]
    return {r["industry_id"]: 1.0 / len(held) for r in held} if held else {}


def rule_equal_weight_all(rows):
    return {r["industry_id"]: 1.0 / len(rows) for r in rows} if rows else {}


def _filled(series, dates):
    """把價格序列對齊到 dates，缺的日期沿用前一個收盤 (開頭缺的略過)。"""
    out, last = {}, None
    for d in dates:
        if d in series and series[d]:
            last = series[d]
        if last is not None:
            out[d] = last
    return out


def simulate(schedule, prices, dates, cost=COST_ONE_WAY):
    """
    schedule: [(進場日, {資產: 目標權重})]，依日期排序；prices: {資產: {日期: 收盤}}；dates: 排序後的交易日。
    持有期間不調整 (權重隨價格漂移)；調整時對「各資產成交金額」(買進 + 賣出) 乘單邊成本，現金不計成本。
    回傳 {"curve": [(日期, NAV)], "turnovers": [每次調整成交金額/NAV], "entries": [進場日], "nav_at_entry": {日期: NAV}}。
    """
    if not schedule:
        return {"curve": [], "turnovers": [], "entries": [], "nav_at_entry": {}}
    filled = {a: _filled(p, dates) for a, p in prices.items()}
    sched = {e: w for e, w in schedule}
    first = schedule[0][0]
    holdings, cash = {}, 1.0
    curve, turnovers, nav_at_entry, entries = [], [], {}, []
    prev = None
    for d in dates:
        if d < first:
            continue
        if prev is not None:
            for a in list(holdings):
                fa = filled.get(a, {})
                if prev in fa and d in fa:
                    holdings[a] *= fa[d] / fa[prev]
        nav = cash + sum(holdings.values())
        if d in sched:
            targets = {a: w * nav for a, w in sched[d].items() if a in filled and d in filled[a]}
            traded = sum(abs(targets.get(a, 0.0) - holdings.get(a, 0.0)) for a in set(targets) | set(holdings))
            fee = cost * traded
            nav_after = nav - fee
            scale = nav_after / nav if nav else 1.0
            holdings = {a: v * scale for a, v in targets.items()}
            cash = nav_after - sum(holdings.values())
            turnovers.append(traded / nav if nav else 0.0)
            entries.append(d)
            nav = nav_after
            nav_at_entry[d] = nav
        curve.append((d, nav))
        prev = d
    return {"curve": curve, "turnovers": turnovers, "entries": entries, "nav_at_entry": nav_at_entry}


def max_drawdown_pct(curve):
    peak, worst = None, 0.0
    for _, v in curve:
        peak = v if peak is None else max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return round(worst * 100.0, 3)


def metrics(sim, bench_sim):
    curve = sim["curve"]
    if not curve:
        return None
    total = (curve[-1][1] / 1.0 - 1.0) * 100.0
    bench_total = (bench_sim["curve"][-1][1] - 1.0) * 100.0 if bench_sim["curve"] else None
    entries = sim["entries"]
    wins = periods = 0
    for a, b in zip(entries, entries[1:]):
        periods += 1
        s_ret = sim["nav_at_entry"][b] / sim["nav_at_entry"][a] - 1.0
        bc = dict(bench_sim["curve"])
        if a in bc and b in bc:
            if s_ret > bc[b] / bc[a] - 1.0:
                wins += 1
    turn = [t / 2.0 for t in sim["turnovers"][1:]]   # 單邊換手 = (買進 + 賣出成交金額) / 2；第一次是由現金建立部位，不算換手
    return {
        "total_return_pct": round(total, 3),
        "vs_benchmark_pp": (round(total - bench_total, 3) if bench_total is not None else None),
        "max_drawdown_pct": max_drawdown_pct(curve),
        "rebalances": len(entries),
        "complete_periods": periods,
        "win_rate_pct": (round(100.0 * wins / periods, 1) if periods else None),
        "avg_turnover_pct": (round(100.0 * sum(turn) / len(turn), 1) if turn else None),
        "enough": periods >= MIN_PERIODS,
    }


# ---------------------------------------------------------------------------
# 整合：由資料庫計算
# ---------------------------------------------------------------------------
def compute_strategy_sim(conn):
    base = {"available": False, "caveats": CAVEATS,
            "params": {"top_n": TOP_N, "levels": list(BULL_LEVELS), "rebalance": REBALANCE,
                       "cost_one_way_pct": COST_ONE_WAY * 100, "min_periods": MIN_PERIODS, "benchmark": BENCHMARK_INDEX}}
    loaded = load_inputs(conn)
    if loaded is None:
        return base
    _model, snapshots, series_by_industry, bench = loaded
    universe = {iid for iid, s in series_by_industry.items() if s}
    by_date = {}
    for s in snapshots:
        if s["industry_id"] in universe:
            by_date.setdefault(s["snapshot_date"], []).append(s)

    dates = sorted(bench)
    decisions = weekly_decision_dates(by_date)
    rules = [("top_n", f"規則 A：前 {TOP_N} 名輪動", rule_top_n),
             ("alert", "規則 B：持有 LEVEL 3/4 (其餘現金)", rule_alert_levels)]
    schedules = {k: [] for k, _, _ in rules}
    schedules["equal"] = []
    holdings_now = {}
    for T in decisions:
        i = bisect_right(dates, T)
        if i >= len(dates):
            continue                       # 進場日 (決策日之後第一個交易日) 還沒有資料
        entry = dates[i]
        rows = by_date[T]
        for key, _name, fn in rules:
            w = fn(rows)
            schedules[key].append((entry, w))
            holdings_now[key] = {"decision_date": T.isoformat(), "entry_date": entry.isoformat(), "weights": w}
        schedules["equal"].append((entry, rule_equal_weight_all(rows)))

    from backtest import snapshot_sources
    out = {**base, "available": True, "snapshot_days": len(by_date), "snapshot_sources": snapshot_sources(snapshots),
           "decision_dates": [d.isoformat() for d in decisions],
           "current_week_pending": bool(by_date),
           "first_entry": None, "last_date": dates[-1].isoformat() if dates else None,
           "strategies": [], "curve": None, "holdings_now": holdings_now}
    if not schedules["top_n"]:
        return out

    first_entry = schedules["top_n"][0][0]
    out["first_entry"] = first_entry.isoformat()
    prices = {iid: series_by_industry[iid] for iid in universe}
    prices[BENCHMARK_INDEX] = bench
    sims = {k: simulate(sched, prices, dates) for k, sched in schedules.items()}
    sims["bench"] = simulate([(first_entry, {BENCHMARK_INDEX: 1.0})], prices, dates)

    def entry(key, name, kind):
        m = metrics(sims[key], sims["bench"])
        return {"key": key, "name": name, "kind": kind, **(m or {})}

    out["strategies"] = (
        [entry(k, n, "rule") for k, n, _ in rules]
        + [entry("equal", "基準：全部可評分產業等權重 (同樣每週調整、同樣扣成本)", "baseline"),
           entry("bench", f"基準：{BENCHMARK_INDEX} 買進持有 (同樣扣一次進場成本)", "baseline")])
    curve_dates = [d for d, _ in sims["bench"]["curve"]]
    out["curve"] = {"dates": [d.isoformat() for d in curve_dates],
                    "series": {k: [round(dict(sims[k]["curve"]).get(d, float("nan")) * 100.0, 3) for d in curve_dates]
                               for k in ("top_n", "alert", "equal", "bench")}}
    out["max_complete_periods"] = max((s.get("complete_periods") or 0) for s in out["strategies"])
    return out
