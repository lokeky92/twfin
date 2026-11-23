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
