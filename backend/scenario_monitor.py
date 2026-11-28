"""
情境條件監控：把三個手寫情境 (樂觀／中性／悲觀) 的「成立條件」中可量化的部分，逐條用最新資料判定「成立／未成立／無資料」。

取代「樂觀 30%／中性 50%／悲觀 20%」這種撰寫者主觀設定的機率 — 那些數字沒有任何資料依據，這裡不產生機率，只回答：
「情境文字裡寫的條件，現在有幾條成立？」。

規則：
- 門檻逐字取自情境文字 (SCENARIO_CONDITIONS 的 source 欄記錄出處)，不新增、不調整。
- 每條都標示數值、日期與來源：'live' (官方資料自動更新) 或 'seed' (手寫數值，不會自動更新，且可能早已過期)。
  只有 live 的條件算作「已驗證」；seed 的條件照算但分開統計並標示，不混進已驗證的比例。
- 沒有資料來源的條件 (例如費半指數、外資期貨未平倉) 標示「無資料」，不猜測。
- 不產生任何情境機率或「目前最像哪個情境」的結論 — 條件之間彼此重疊 (例如三個情境都會用到美債殖利率)，加總成比例沒有統計意義。
"""
from live_pulse import live_daily_flows

# (id, 情境, 角色, 說明, 指標代碼, 運算, 門檻, 出處)  運算：'lt' 小於、'gt' 大於、'ge' 大於等於、'between' 區間 [lo, hi]
SCENARIO_CONDITIONS = [
    ("bull_us10y", "BULL", "trigger", "美國 10 年期公債殖利率回落至 4.5% 以下", "US_10Y_YIELD", "lt", 4.5, "樂觀情境 成立條件 1"),
    ("bull_dxy", "BULL", "trigger", "美元指數 DXY 低於 102", "INTL_DXY", "lt", 102.0, "樂觀情境 核心觀察指標"),
    ("bull_twd", "BULL", "trigger", "新台幣升破 32.3 (兌美元匯率低於 32.3)", "TW_USD_TWD", "lt", 32.3, "樂觀情境 核心觀察指標"),
    ("bull_sox", "BULL", "trigger", "費城半導體指數在 8,400 點以上止跌回穩", "INTL_SOX_INDEX", "ge", 8400.0, "樂觀情境 成立條件 2"),
    ("bull_foreign", "BULL", "trigger", "外資現貨由賣轉買 (近 5 個交易日外資累計淨買超)", "_FOREIGN_5D", "gt", 0.0, "樂觀情境 成立條件 2"),
    ("bull_inv", "BULL", "invalidation", "失效：美債 10 年期殖利率突破 5.25%", "US_10Y_YIELD", "gt", 5.25, "樂觀情境 失效條件"),
    ("base_us10y", "BASE", "trigger", "美債 10 年期殖利率於 4.8%~5.1% 震盪", "US_10Y_YIELD", "between", (4.8, 5.1), "中性情境 成立條件 1"),
    ("base_dxy", "BASE", "trigger", "美元指數維持 103~104", "INTL_DXY", "between", (103.0, 104.0), "中性情境 成立條件 1"),
    ("base_twd", "BASE", "trigger", "新台幣於 32.6~33.0 區間", "TW_USD_TWD", "between", (32.6, 33.0), "中性情境 成立條件 1"),
    ("base_taiex", "BASE", "trigger", "加權指數於 36,000~42,000 點箱型", "TW_TAIEX_INDEX", "between", (36000.0, 42000.0), "中性情境 成立條件 2"),
    ("base_ndc", "BASE", "trigger", "景氣燈號維持紅燈 (綜合判斷分數 38 分以上)", "TW_NDC_SCORE", "ge", 38.0, "中性情境 成立條件 3"),
    ("base_inv", "BASE", "invalidation", "失效：加權指數跌破 35,500 點", "TW_TAIEX_INDEX", "lt", 35500.0, "中性情境 失效條件"),
    ("bear_us10y", "BEAR", "trigger", "美債 10 年期殖利率飆破 5.3%", "US_10Y_YIELD", "gt", 5.3, "悲觀情境 成立條件 1"),
    ("bear_dxy", "BEAR", "trigger", "美元指數衝破 105", "INTL_DXY", "gt", 105.0, "悲觀情境 成立條件 1"),
    ("bear_twd", "BEAR", "trigger", "新台幣貶破 33.2", "TW_USD_TWD", "gt", 33.2, "悲觀情境 成立條件 1"),
    ("bear_sox", "BEAR", "trigger", "費城半導體指數跌破 7,800 點", "INTL_SOX_INDEX", "lt", 7800.0, "悲觀情境 成立條件 2"),
    ("bear_sell", "BEAR", "trigger", "外資單日賣超超過 800 億並連續出現 (近 5 個交易日內連續 2 天以上)", "_FOREIGN_SELL_STREAK", "ge", 2.0, "悲觀情境 核心觀察指標"),
    ("bear_inv", "BEAR", "invalidation", "失效：外銷訂單年增率仍在 40% 以上 (悲觀情境僅止於估值修正)", "TW_EXPORT_ORDERS", "yoy_ge", 40.0, "悲觀情境 失效條件"),
]
FOREIGN_SELL_THRESHOLD_BILLION = -800.0


def _judge(op, threshold, value):
    if value is None:
        return None
    if op == "lt":
        return value < threshold
    if op == "gt":
        return value > threshold
    if op in ("ge", "yoy_ge"):
        return value >= threshold
    if op == "between":
        return threshold[0] <= value <= threshold[1]
    return None


def _rule_text(op, th):
    if op == "between":
        return f"{th[0]:g} ~ {th[1]:g}"
    return {"lt": f"< {th:g}", "gt": f"> {th:g}", "ge": f"≥ {th:g}", "yoy_ge": f"年增率 ≥ {th:g}%"}[op]


def _is_live(m):
    return str(m.get("revision_version") or "").startswith("live") or m.get("metric_code") == "TW_TAIEX_INDEX"


def _foreign_series(flows):
    return [(r["date"], r["foreign"]) for r in flows if r.get("foreign") is not None]


def compute_scenario_monitor(dash):
    macro = {m["metric_code"]: m for m in (dash.get("macro_latest") or [])}
    flows = live_daily_flows(dash.get("institutional_flows"))
    fs = _foreign_series(flows)
    last5 = fs[-5:]
    derived = {}
    if len(last5) >= 3:
        derived["_FOREIGN_5D"] = (round(sum(v for _d, v in last5), 1), last5[-1][0], "live", "億元")
        streak = best = 0
        for _d, v in last5:
            streak = streak + 1 if v < FOREIGN_SELL_THRESHOLD_BILLION else 0
            best = max(best, streak)
        derived["_FOREIGN_SELL_STREAK"] = (float(best), last5[-1][0], "live", "天")
    conds = []
    for cid, scen, role, label, code, op, th, source in SCENARIO_CONDITIONS:
        value = as_of = src = unit = None
        if code in derived:
            value, as_of, src, unit = derived[code]
        elif code in macro:
            m = macro[code]
            value = m.get("yoy_pct") if op == "yoy_ge" else m.get("cleaned_value")
            as_of = m.get("period_covered")
            src = "live" if _is_live(m) else "seed"
            unit = m.get("unit")
        met = _judge(op, th, value)
        conds.append({"id": cid, "scenario": scen, "role": role, "label": label, "rule": _rule_text(op, th), "metric_code": code,
                      "value": value, "as_of": as_of, "source": src, "unit": unit, "met": met, "origin": source})
    summary = {}
    for scen in ("BULL", "BASE", "BEAR"):
        trig = [c for c in conds if c["scenario"] == scen and c["role"] == "trigger"]
        inv = [c for c in conds if c["scenario"] == scen and c["role"] == "invalidation"]
        summary[scen] = {
            "triggers_total": len(trig),
            "live_met": sum(1 for c in trig if c["met"] is True and c["source"] == "live"),
            "live_known": sum(1 for c in trig if c["met"] is not None and c["source"] == "live"),
            "seed_met": sum(1 for c in trig if c["met"] is True and c["source"] == "seed"),
            "seed_known": sum(1 for c in trig if c["met"] is not None and c["source"] == "seed"),
            "no_data": sum(1 for c in trig if c["met"] is None),
            "invalidation_hit": [c["id"] for c in inv if c["met"] is True],
        }
    return {"conditions": conds, "summary": summary, "flows_through": flows[-1]["date"] if flows else None,
            "note": "門檻逐字取自情境文字；只回答「條件現在成不成立」，不產生機率。手寫來源 (seed) 的數值不會自動更新，只供參考，不計入已驗證。"}
