"""
儀表板 payload 的「即時化」後處理 (不改資料庫內容，只改輸出給畫面的資料)：

1. 三大法人表：官方逐日資料為主，加上由逐日加總出的週／月累計；手寫的種子列只保留「早於第一筆即時資料」的歷史期間，
   與即時資料重疊的手寫列 (數字會互相矛盾，例如同一天外資 −842.6 億 vs 官方 −95.1 億) 一律不顯示。
2. 總體指標：加權指數改用證交所最新收盤 (其餘總體指標沒有每日的免費官方來源，維持人工維護並顯示所屬期間)。
3. 固定研究報告：仍是手寫的 (季報) 明確標示「不會自動更新」，不再顯示「已驗證最新發布」。

純函式，無資料庫依賴，方便測試。
"""
from datetime import date

from live_pulse import SHORT_NAMES, index_series, live_daily_flows, to_iso_date

HAND_WRITTEN_STATUS = "手寫・不會自動更新（撰於 2026-11-22）"


def _week_key(iso):
    y, w, _ = date.fromisoformat(iso).isocalendar()
    return y, w


def _sg(x, nd=1):
    return f"{x:+,.{nd}f}"


def _industry_phrase(items, n=3):
    return "、".join(f"{SHORT_NAMES.get(i['id'], i['name'])} {_sg(i['v'])} 億" for i in items[:n]) or "無"


def _top_buy_sell(per_industry):
    """per_industry: [{id, name, v}] → (買超前三文字, 賣超前三文字)。"""
    buys = sorted((i for i in per_industry if i["v"] > 0), key=lambda i: -i["v"])
    sells = sorted((i for i in per_industry if i["v"] < 0), key=lambda i: i["v"])
    return _industry_phrase(buys), _industry_phrase(sells)


def _raw_live_rows(rows):
    out = {}
    for r in rows:
        if r.get("period_type") != "DAILY" or "官方API" not in str(r.get("period_label") or ""):
            continue
        d = to_iso_date(r.get("release_date"))
        if d:
            out[d] = r
    return [out[d] for d in sorted(out)]


def institutional_view(rows, daily_industry, names):
    """
    rows: institutional_flows 的資料列 (dict)。daily_industry: live_industry_daily 的資料列 (dict)。names: {industry_id: 名稱}。
    回傳要顯示的資料列 (dict 清單)，每列附 text_source: 'live' (官方逐日) / 'computed' (由逐日加總) / 'seed' (手寫歷史)。
    沒有任何官方逐日資料時，原樣回傳 (全部標為 seed)。
    """
    live = _raw_live_rows(rows)
    if not live:
        return [dict(r, text_source="seed") for r in rows]
    first_live = to_iso_date(live[0]["release_date"])

    by_date = {}
    for r in daily_industry or []:
        by_date.setdefault(r["trade_date"], []).append(
            {"id": r["industry_id"], "name": names.get(r["industry_id"], r["industry_id"]),
             "v": (r.get("foreign_billion") or 0.0) + (r.get("itc_billion") or 0.0)})

    out = []
    for r in reversed(live):          # 新到舊
        d = to_iso_date(r["release_date"])
        row = dict(r, text_source="live")
        if d in by_date:
            row["top_buy_industries"], row["top_sell_industries"] = _top_buy_sell(by_date[d])
            row["notes"] = f"{r.get('notes') or ''}｜產業買賣為外資+投信 (股數×收盤價)，依產業對照表彙總".strip("｜")
        out.append(row)

    def aggregate(group, kind, label, ind_rows):
        n = len(group)
        top_b, top_s = _top_buy_sell(ind_rows) if ind_rows else ("此區間尚未累積產業層級資料", "此區間尚未累積產業層級資料")
        return {
            "flow_record_id": None, "period_type": kind, "period_label": label, "release_date": group[-1]["release_date"],
            "market_scope": "TWSE 上市 (由官方逐日資料加總)",
            "foreign_net_billion": round(sum(g["foreign_net_billion"] for g in group), 2),
            "itc_net_billion": round(sum(g["itc_net_billion"] for g in group), 2),
            "dealer_prop_billion": round(sum(g["dealer_prop_billion"] for g in group), 2),
            "dealer_hedge_billion": round(sum(g["dealer_hedge_billion"] for g in group), 2),
            "total_3insti_billion": round(sum(g["total_3insti_billion"] for g in group), 2),
            "foreign_futures_oi_contracts": None, "margin_balance_billion": None,
            "top_buy_industries": top_b, "top_sell_industries": top_s, "source_id": "SRC_TWSE",
            "notes": f"由 {n} 個交易日的官方逐日資料加總，不是官方的週／月統計；只涵蓋有資料的交易日。", "text_source": "computed",
        }

    def industry_sum(dates):
        agg = {}
        for dt in dates:
            for it in by_date.get(dt, []):
                a = agg.setdefault(it["id"], {"id": it["id"], "name": it["name"], "v": 0.0})
                a["v"] += it["v"]
        return list(agg.values())

    weeks, months = {}, {}
    for r in live:
        d = to_iso_date(r["release_date"])
        weeks.setdefault(_week_key(d), []).append(r)
        months.setdefault(d[:7], []).append(r)
    agg_rows = []
    for (y, w), g in sorted(weeks.items(), reverse=True):
        ds = [to_iso_date(x["release_date"]) for x in g]
        label = f"{y}-W{w:02d}（{ds[0][5:]}~{ds[-1][5:]}，僅 {len(g)} 個交易日資料）"
        agg_rows.append(aggregate(g, "WEEKLY", label, industry_sum(ds)))
    for ym, g in sorted(months.items(), reverse=True):
        ds = [to_iso_date(x["release_date"]) for x in g]
        label = f"{ym}（{ds[0][5:]}~{ds[-1][5:]}，僅 {len(g)} 個交易日資料，非整月）"
        agg_rows.append(aggregate(g, "MONTHLY", label, industry_sum(ds)))
    out.extend(agg_rows)

    # 手寫的歷史列：只保留結束日早於第一筆即時資料的期間 (重疊的會與官方數字矛盾)
    for r in rows:
        if r in live or "官方API" in str(r.get("period_label") or ""):
            continue
        d = to_iso_date(r.get("release_date"))
        if d and first_live and d < first_live:
            out.append(dict(r, text_source="seed"))
    return out


def macro_with_live_taiex(macro_latest, live_indices):
    """把 TW_TAIEX_INDEX 換成證交所最新收盤 (單日漲跌)；找不到指數時原樣回傳。其餘總體指標不動。"""
    series = index_series(live_indices).get("發行量加權股價指數") or []
    if not series:
        return macro_latest
    last = series[-1]
    prev = series[-2] if len(series) >= 2 else None
    out = []
    for m in macro_latest:
        if m.get("metric_code") == "TW_TAIEX_INDEX":
            m = dict(m, raw_value=last[1], cleaned_value=last[1], period_covered=last[0], release_date=last[0],
                     prev_value=prev[1] if prev else None, mom_pct=last[2] if last[2] is not None else 0, yoy_pct=None,
                     quality_grade="A", observation_type="DIRECT_STAT",
                     notes="即時：證交所每日收盤指數；「期增」是單日漲跌，沒有年增資料。")
        out.append(m)
    return out


def label_reports(reports):
    """仍是手寫的報告 (沒有 text_source='live') 改標為不會自動更新，不再顯示「已驗證最新發布」。"""
    out = []
    for r in reports:
        if r.get("text_source") == "live":
            out.append(r)
        else:
            out.append(dict(r, update_status=HAND_WRITTEN_STATUS, text_source="seed"))
    return out
