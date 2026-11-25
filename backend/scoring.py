"""
產業輪動評分與預警分級的純函式 (無資料庫依賴，方便單元測試)。
"""

WEIGHT_KEYS = ("capital_flow", "fundamentals", "future_growth", "institutional", "valuation")

DEFAULT_WEIGHTS = {
    "capital_flow": 0.25,
    "fundamentals": 0.25,
    "future_growth": 0.20,
    "institutional": 0.15,
    "valuation": 0.15,
}

DEFAULT_THRESHOLDS = {
    "lvl4_min": 80.0,
    "lvl3_min": 72.0,
    "lvl2_min": 62.0,
    "lvlR_cap_max": 45.0,
}

# industry_rotation_scores 欄位名稱對應
SCORE_COLUMNS = {
    "capital_flow": "score_capital_flow",
    "fundamentals": "score_fundamentals",
    "future_growth": "score_future_growth",
    "institutional": "score_institutional",
    "valuation": "score_valuation",
}


def parse_weights(payload):
    """由 API payload 解析並驗證權重；總和需為 1.0 (容差 0.01)，每項需介於 0~1。"""
    weights = {}
    for key in WEIGHT_KEYS:
        try:
            value = float(payload.get(key, DEFAULT_WEIGHTS[key]))
        except (TypeError, ValueError):
            raise ValueError(f"權重 {key} 必須為數字")
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"權重 {key} 必須介於 0% ~ 100%，目前為 {value * 100:.1f}%")
        weights[key] = value
    total = round(sum(weights.values()), 4)
    if abs(total - 1.0) > 0.01:
        raise ValueError(f"權重總和必須為 100% (1.0)，目前為 {total * 100:.1f}%")
    return weights


def compute_weighted_total(row, weights):
    """
    依權重計算產業總分。資料不足 (任一子分數為 None 或狀態為 INSUFFICIENT_DATA) 時回傳 None，
    以免把缺漏當成 0 分而誤導排名。
    """
    if row.get("rotation_state") == "INSUFFICIENT_DATA":
        return None
    total = 0.0
    for key, col in SCORE_COLUMNS.items():
        score = row.get(col)
        if score is None:
            return None
        total += score * weights[key]
    return round(total, 2)


def classify_alert_level(total_score, capital_flow_score, thresholds=None):
    """
    依門檻判定預警等級。資金分數低於 R 門檻時優先判為 LEVEL R (撤退風險)。
    total_score 為 None 時回傳 None (不可評分)。
    """
    th = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        th.update(thresholds)
    if total_score is None:
        return None
    if capital_flow_score is not None and capital_flow_score < th["lvlR_cap_max"]:
        return "LEVEL R"
    if total_score >= th["lvl4_min"]:
        return "LEVEL 4"
    if total_score >= th["lvl3_min"]:
        return "LEVEL 3"
    if total_score >= th["lvl2_min"]:
        return "LEVEL 2"
    return "LEVEL 1"


def validate_thresholds(th):
    """門檻需滿足 L4 > L3 > L2，且都在 0~100 之間。"""
    for key, value in th.items():
        if not 0.0 <= value <= 100.0:
            raise ValueError(f"門檻 {key} 必須介於 0~100，目前為 {value}")
    if not th["lvl4_min"] > th["lvl3_min"] > th["lvl2_min"]:
        raise ValueError("門檻順序錯誤：必須滿足 LEVEL 4 > LEVEL 3 > LEVEL 2")
    return th


# ---------------------------------------------------------------------------
# 權重敏感度分析：權重是主觀設定，排名若因 ±5% 的權重微調就大幅變動，結論就不可靠。
# ---------------------------------------------------------------------------
import random
import statistics


def shift_weight(weights, key, delta):
    """把 key 的權重加上 delta (限制在 0~1)，並把相反的量依比例分攤給其他權重，總和維持 1.0。"""
    new_w = max(0.0, min(1.0, weights[key] + delta))
    applied = new_w - weights[key]
    others = [k for k in WEIGHT_KEYS if k != key]
    pool = sum(weights[k] for k in others)
    out = {key: new_w}
    for k in others:
        share = (weights[k] / pool) if pool > 0 else 1.0 / len(others)
        out[k] = max(0.0, weights[k] - applied * share)
    return _normalize(out)


def _normalize(weights):
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def _rank_scenario(rows, weights, thresholds):
    """回傳 {industry_id: (名次, 預警等級)}；資料不足的產業不參與排名。"""
    scored = []
    for r in rows:
        total = compute_weighted_total(r, weights)
        if total is not None:
            scored.append((total, r))
    scored.sort(key=lambda t: (-t[0], t[1]["industry_id"]))
    return {
        r["industry_id"]: (i + 1, classify_alert_level(total, r.get("score_capital_flow"), thresholds))
        for i, (total, r) in enumerate(scored)
    }


def _stability_label(rank_range, flip_pct):
    if rank_range <= 1 and flip_pct < 10:
        return "穩定"
    if rank_range >= 4 or flip_pct >= 30:
        return "不穩定"
    return "中等"


def sensitivity_analysis(rows, weights=None, thresholds=None, delta=0.05, trials=500, seed=20261125):
    """
    對目前權重做兩種擾動，觀察排名與預警等級的穩定度：
      1. 單一權重 ±delta (其餘依比例調整)，共 2×5 = 10 個情境
      2. 隨機擾動：每個權重各加 U(-delta, +delta) 後重新正規化，共 trials 個情境
    使用固定種子，同樣的輸入永遠得到同樣的結果 (網站快照不會每次都變)。
    rows 需含 industry_id、industry_name 與五個 score_* 欄位。
    """
    weights = weights or DEFAULT_WEIGHTS
    base = _rank_scenario(rows, weights, thresholds)
    if not base:
        return {"available": False, "reason": "沒有可評分的產業"}
    names = {r["industry_id"]: r.get("industry_name", r["industry_id"]) for r in rows}

    scenarios, labels = [], []
    for key in WEIGHT_KEYS:
        for sign in (-1, 1):
            scenarios.append(shift_weight(weights, key, sign * delta))
            labels.append((key, sign))
    one_at_a_time = len(scenarios)
    rng = random.Random(seed)
    for _ in range(trials):
        scenarios.append(_normalize({k: max(0.0, weights[k] + rng.uniform(-delta, delta)) for k in WEIGHT_KEYS}))
    results = [_rank_scenario(rows, w, thresholds) for w in scenarios]

    base_top1 = min(base, key=lambda i: base[i][0])
    base_top3 = {i for i, (rk, _) in base.items() if rk <= 3}
    n = len(results)

    industries = []
    for iid, (base_rank, base_level) in sorted(base.items(), key=lambda kv: kv[1][0]):
        ranks = [res[iid][0] for res in results]
        flips = sum(1 for res in results if res[iid][1] != base_level)
        flip_pct = round(flips * 100.0 / n, 1)
        rng_span = max(ranks) - min(ranks)
        industries.append({
            "industry_id": iid, "industry_name": names[iid],
            "base_rank": base_rank, "base_level": base_level,
            "min_rank": min(ranks), "max_rank": max(ranks),
            "rank_std": round(statistics.pstdev(ranks), 2),
            "top3_pct": round(sum(1 for x in ranks if x <= 3) * 100.0 / n, 1),
            "level_change_pct": flip_pct,
            "stability": _stability_label(rng_span, flip_pct),
        })

    by_weight = []
    for key in WEIGHT_KEYS:
        shifts = []
        for (k, sign), res in zip(labels, results[:one_at_a_time]):
            if k != key:
                continue
            for iid, (rk, _) in res.items():
                shifts.append((abs(rk - base[iid][0]), iid))
        worst = max(shifts) if shifts else (0, None)
        by_weight.append({"weight_key": key, "max_rank_shift": worst[0],
                          "most_affected": names.get(worst[1]) if worst[1] else None})

    return {
        "available": True,
        "delta_pct": round(delta * 100, 1),
        "scenario_count": n,
        "top1_same_pct": round(sum(1 for res in results if min(res, key=lambda i: res[i][0]) == base_top1) * 100.0 / n, 1),
        "top3_same_pct": round(sum(1 for res in results
                                   if {i for i, (rk, _) in res.items() if rk <= 3} == base_top3) * 100.0 / n, 1),
        "top1_name": names[base_top1],
        "unstable_count": sum(1 for x in industries if x["stability"] == "不穩定"),
        "industries": industries,
        "by_weight": by_weight,
    }


# ---------------------------------------------------------------------------
# 預警門檻敏感度分析：LEVEL 2/3/4 的分數線與 LEVEL R 的資金分數線同樣是主觀設定。
# 若某產業的總分剛好貼著門檻，它的預警等級就只是門檻選擇的結果，不是市場訊號。
# ---------------------------------------------------------------------------
THRESHOLD_KEYS = ("lvl4_min", "lvl3_min", "lvl2_min", "lvlR_cap_max")
THRESHOLD_LABELS = {
    "lvl4_min": "LEVEL 4 總分門檻", "lvl3_min": "LEVEL 3 總分門檻",
    "lvl2_min": "LEVEL 2 總分門檻", "lvlR_cap_max": "LEVEL R 資金分數上限",
}


def effective_thresholds(stored):
    """
    由資料庫存的 thresholds_json 取得「實際生效」的四個數值門檻。
    種子模型存的是描述文字 (沒有數值)，使用者經治理介面更新後數值放在 "numeric" 底下；
    缺漏或無法轉成數字的項目一律回到預設值。
    """
    th = dict(DEFAULT_THRESHOLDS)
    stored = stored if isinstance(stored, dict) else {}
    numeric = stored.get("numeric") if isinstance(stored.get("numeric"), dict) else stored
    for key in DEFAULT_THRESHOLDS:
        try:
            th[key] = float(numeric[key])
        except (KeyError, TypeError, ValueError):
            pass
    return th


def _thresholds_valid(th):
    try:
        validate_thresholds({k: th[k] for k in THRESHOLD_KEYS})
        return True
    except (ValueError, KeyError, TypeError):
        return False


def _boundary_margin(total, cap, th):
    """回傳 (距離最近門檻的分數, 該門檻代號)；只看「可能讓等級改變」的門檻。"""
    candidates = [(abs(total - th["lvl4_min"]), "lvl4_min"),
                  (abs(total - th["lvl3_min"]), "lvl3_min"),
                  (abs(total - th["lvl2_min"]), "lvl2_min")]
    if cap is not None:
        candidates.append((abs(cap - th["lvlR_cap_max"]), "lvlR_cap_max"))
    return min(candidates)


def threshold_sensitivity(rows, weights=None, thresholds=None, delta=2.0, trials=500, seed=20261126):
    """
    對目前預警門檻做兩種擾動，觀察各產業的預警等級穩不穩：
      1. 單一門檻 ±delta 分 (其餘不變)，共 2×4 = 8 個情境 (違反 L4 > L3 > L2 的情境略過)
      2. 隨機擾動：四個門檻各加 U(-delta, +delta)，不合法 (順序錯誤或超出 0~100) 時重抽，共 trials 個情境
    固定亂數種子，同樣輸入永遠得到同樣結果。
    rows 需含 industry_id、industry_name 與五個 score_* 欄位 (權重使用目前啟用的版本)。
    """
    weights = weights or DEFAULT_WEIGHTS
    base_th = effective_thresholds(thresholds)
    names, scored = {}, []
    for r in rows:
        total = compute_weighted_total(r, weights)
        if total is None:
            continue
        names[r["industry_id"]] = r.get("industry_name", r["industry_id"])
        scored.append((r["industry_id"], total, r.get("score_capital_flow")))
    if not scored:
        return {"available": False, "reason": "沒有可評分的產業"}

    scenarios, single = [], []
    for key in THRESHOLD_KEYS:
        for sign in (-1, 1):
            th = dict(base_th)
            th[key] = round(th[key] + sign * delta, 4)
            if _thresholds_valid(th):
                scenarios.append(th)
                single.append((key, sign, len(scenarios) - 1))
    rng = random.Random(seed)
    for _ in range(trials):
        for _attempt in range(20):
            th = {k: round(base_th[k] + rng.uniform(-delta, delta), 4) for k in THRESHOLD_KEYS}
            if _thresholds_valid(th):
                scenarios.append(th)
                break
    n = len(scenarios)

    def level(total, cap, th):
        return classify_alert_level(total, cap, th)

    industries = []
    for iid, total, cap in sorted(scored, key=lambda t: -t[1]):
        base_level = level(total, cap, base_th)
        levels = [level(total, cap, th) for th in scenarios]
        dist = {}
        for lv in levels:
            dist[lv] = dist.get(lv, 0) + 1
        change_pct = round(sum(1 for lv in levels if lv != base_level) * 100.0 / n, 1)
        margin, boundary = _boundary_margin(total, cap, base_th)
        if change_pct < 10:
            label = "穩定"
        elif change_pct >= 30:
            label = "不穩定"
        else:
            label = "中等"
        industries.append({
            "industry_id": iid, "industry_name": names[iid], "total_score": total, "capital_flow_score": cap,
            "base_level": base_level, "margin_points": round(margin, 2), "nearest_threshold": boundary,
            "level_distribution": {lv: round(c * 100.0 / n, 1) for lv, c in sorted(dist.items())},
            "level_change_pct": change_pct, "stability": label,
        })

    by_threshold = []
    for key in THRESHOLD_KEYS:
        affected = set()
        for k, _sign, idx in single:
            if k != key:
                continue
            for iid, total, cap in scored:
                if level(total, cap, scenarios[idx]) != level(total, cap, base_th):
                    affected.add(names[iid])
        by_threshold.append({"threshold_key": key, "label": THRESHOLD_LABELS[key], "value": base_th[key],
                             "affected_count": len(affected), "affected": sorted(affected)})

    unchanged = sum(1 for x in industries if x["level_change_pct"] == 0)
    return {
        "available": True,
        "delta_points": delta,
        "scenario_count": n,
        "thresholds": base_th,
        "industry_count": len(industries),
        "never_changes_count": unchanged,
        "unstable_count": sum(1 for x in industries if x["stability"] == "不穩定"),
        "near_boundary_count": sum(1 for x in industries if x["margin_points"] <= delta),
        "industries": industries,
        "by_threshold": by_threshold,
    }
