"""
歷史時間軸 (首頁「資金輪動時間軸」)：由 industry_score_history 的「真實快照」產生，取代原本 5 格手寫的歷史情境。

每個快照日一格：當天各產業的分數、狀態與預警等級、最熱／最冷的三個產業，以及和前一個快照日相比
分數升降最大的產業 (輪動)。文字全部由資料機械式產生，沒有手寫敘事，也沒有事後諸葛的「重大事件」。
快照只保存分數與等級，所以畫面上的歷史格不顯示營收與相對強弱 (那些是當下的即時資料，不是當時的)。
score_source：'seed' = 即時評分上線前的快照 (子分數是內建種子值)；'live' = 由官方資料重算。兩者都照實標示。
"""
from scoring import classify_alert_level, effective_thresholds
import json

MAX_POINTS = 120      # 最多保留最近幾個快照日 (payload 大小)


def build_timeline_history(conn, max_points=MAX_POINTS):
    cur = conn.cursor()
    try:
        model = cur.execute("SELECT * FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1").fetchone()
        if not model:
            return {"available": False, "points": []}
        th = effective_thresholds(json.loads(model["thresholds_json"]))
        names = {r["industry_id"]: r["industry_name"] for r in cur.execute("SELECT industry_id, industry_name FROM industry_taxonomy")}
        rows = [dict(r) for r in cur.execute(
            "SELECT * FROM industry_score_history WHERE model_version = ? ORDER BY snapshot_date", (model["version_id"],))]
    except Exception:  # noqa: BLE001 — 舊資料庫尚未建表
        return {"available": False, "points": []}
    out = build_points(rows, names, th, max_points)
    try:
        inst = [dict(r) for r in cur.execute(
            "SELECT trade_date, industry_id, foreign_billion, itc_billion FROM live_industry_daily ORDER BY trade_date")]
    except Exception:  # noqa: BLE001
        inst = []
    out["weekly"] = weekly_changes(out["points"], inst, names)
    return out


def build_points(rows, names, th, max_points=MAX_POINTS):
    by_day = {}
    for r in rows:
        by_day.setdefault(r["snapshot_date"], []).append(r)
    points, prev = [], None
    for day in sorted(by_day):
        group = by_day[day]
        scored = [r for r in group if r.get("total_weighted_score") is not None]
        sources = {r.get("score_source") or "seed" for r in group}
        source = "live" if "live" in sources else "seed"          # 同日若兩種都有 (同日重跑) 以 live 為準
        scores = {}
        for r in group:
            lv = r.get("alert_level") or (classify_alert_level(r["total_weighted_score"], r["score_capital_flow"], th)
                                          if r.get("total_weighted_score") is not None else None)
            scores[r["industry_id"]] = {"score": r.get("total_weighted_score"), "state": r.get("rotation_state"), "level": lv,
                                        "name": names.get(r["industry_id"], r["industry_id"])}
        ranked = sorted(scored, key=lambda r: -r["total_weighted_score"])
        nm = lambda r: names.get(r["industry_id"], r["industry_id"])   # noqa: E731
        hot = [{"name": nm(r), "score": round(r["total_weighted_score"], 1)} for r in ranked[:3]]
        cold = [{"name": nm(r), "score": round(r["total_weighted_score"], 1)} for r in reversed(ranked[-3:])]
        movers_up, movers_down = [], []
        if prev is not None:
            deltas = []
            for iid, cur_ in scores.items():
                p = prev.get(iid)
                if cur_["score"] is not None and p and p["score"] is not None:
                    deltas.append((cur_["score"] - p["score"], cur_["name"]))
            deltas.sort(reverse=True)
            movers_up = [{"name": n, "delta": round(d, 1)} for d, n in deltas[:3] if d > 0]
            movers_down = [{"name": n, "delta": round(d, 1)} for d, n in reversed(deltas[-3:]) if d < 0]
        levels = {}
        for v in scores.values():
            if v["level"]:
                levels[v["level"]] = levels.get(v["level"], 0) + 1
        points.append({
            "date": day, "source": source, "scored": len(scored), "total": len(group),
            "avg": round(sum(r["total_weighted_score"] for r in scored) / len(scored), 1) if scored else None,
            "scores": scores, "hot": hot, "cold": cold, "movers_up": movers_up, "movers_down": movers_down, "levels": levels,
            "has_prev": prev is not None,
        })
        prev = scores
    return {"available": bool(points), "points": points[-max_points:], "total_days": len(points)}


# ---------------------------------------------------------------------------
# 本週變化：最新快照 vs 約 5 個交易日前的快照 (+ 近 5 日 vs 前 5 日的外資＋投信買賣超)
# ---------------------------------------------------------------------------
WEEK = 5
LEVEL_RANK = {"LEVEL R": 0, "LEVEL 1": 1, "LEVEL 2": 2, "LEVEL 3": 3, "LEVEL 4": 4}


def weekly_changes(points, inst_rows, names, week=WEEK):
    if len(points) < 2:
        return {"available": False, "reason": "快照日不足 2 天，累積後才會顯示週變化"}
    cur_pt = points[-1]
    base_pt = points[max(0, len(points) - 1 - week)]
    gap = len(points) - 1 - points.index(base_pt)
    score_changes, level_changes = [], []
    for iid, c in cur_pt["scores"].items():
        b = base_pt["scores"].get(iid)
        if not b:
            continue
        if c["score"] is not None and b["score"] is not None:
            score_changes.append({"name": c["name"], "from": round(b["score"], 1), "to": round(c["score"], 1), "delta": round(c["score"] - b["score"], 1)})
        if c["level"] != b["level"] and (c["level"] or b["level"]):
            up = LEVEL_RANK.get(c["level"], -1) > LEVEL_RANK.get(b["level"], -1)
            level_changes.append({"name": c["name"], "from": b["level"], "to": c["level"], "direction": "up" if up else "down"})
    score_changes.sort(key=lambda r: -r["delta"])
    up = [r for r in score_changes if r["delta"] > 0][:3]
    down = [r for r in reversed(score_changes) if r["delta"] < 0][:3]

    by_day = {}
    for r in inst_rows:
        v = (r.get("foreign_billion") or 0) + (r.get("itc_billion") or 0)
        by_day.setdefault(r["trade_date"], {})[r["industry_id"]] = v
    days = sorted(by_day)
    inst = {"available": False}
    if len(days) >= 2:
        recent = days[-week:]
        prior = days[-2 * week:-week]
        tot = lambda ds: {i: sum(by_day[d].get(i, 0) for d in ds) for i in {i for d in ds for i in by_day[d]}}   # noqa: E731
        r5, p5 = tot(recent), tot(prior)
        rows = sorted(((names.get(i, i), round(v, 1), round(p5.get(i, 0), 1) if prior else None) for i, v in r5.items()), key=lambda t: -t[1])
        flips = [{"name": n, "recent": v, "prior": pv} for n, v, pv in rows if pv is not None and ((v > 0) != (pv > 0)) and abs(v) >= 1 and abs(pv) >= 1]
        inst = {"available": True, "days": len(recent), "from": recent[0], "to": recent[-1], "has_prior": bool(prior),
                "buy": [{"name": n, "value": v} for n, v, _ in rows if v > 0][:3],
                "sell": [{"name": n, "value": v} for n, v, _ in reversed(rows) if v < 0][:3], "flips": flips[:4]}
    return {"available": True, "from_date": base_pt["date"], "to_date": cur_pt["date"], "gap_days": gap,
            "mixed_scale": base_pt["source"] != cur_pt["source"], "from_source": base_pt["source"], "to_source": cur_pt["source"],
            "score_up": up, "score_down": down, "level_changes": level_changes, "inst": inst}
