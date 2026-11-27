"""
固定研究報告 (每日／每週／每月)：由即時資料機械式產生，取代 seed 裡 2026-11-22 手寫的報告。

每次排程產生：
  - 每日日報：當日三大法人、大盤、產業分數與法人買賣金額、預警等級分布、個股篩選
  - 每週週報：本週 (ISO 週) 逐日法人、大盤、產業累計法人買賣金額、評分變化 (資料天數不足時照實標示)
  - 每月月報：最新一期 MOPS 月營收的產業排名、當月累計法人、評分變化、預警分布
每季季報沒有可用的即時來源 (需要總體與財報資料)，維持手寫並在畫面標示「不會更新」。

所有數字來自資料庫，文字由規則組成；不含新聞、事件或分析師觀點。
「反方證據」由規則偵測資料裡互相矛盾的地方 (例如法人賣超但大盤上漲)；沒有就明說沒有。
純函式在前半 (build_*)，資料庫存取在 apply_live_reports。
"""
import json
from datetime import date

from live_pulse import MARKET_INDEX, SHORT_NAMES, FOREIGN_SELL_ALERT_BILLION, index_series, live_daily_flows, to_iso_date, window_return

PRICE_INDEX = "發行量加權股價指數"
KEEP = {"每日": 7, "每週": 4, "每月": 3}      # 各頻率保留最近幾份
SOURCES = "證交所 BFI82U／T86／個股行情、櫃買三大法人與行情、MOPS 月營收（官方 OpenAPI）"
LIMITS = ("本報告由機械式規則依即時資料自動產生，不是分析師撰寫；5 項評分子分數皆為代理指標 (沒有財報獲利、毛利率、資本支出或分析師預估)，"
          "且是相對其他產業的百分位；法人金額 = 淨買賣股數 × 當日收盤價 (近似)。")


def _sg(x, nd=1, unit=""):
    return "N/A" if x is None else f"{x:+,.{nd}f}{unit}"


def _name(i):
    return SHORT_NAMES.get(i.get("id")) or i.get("name") or i.get("id")


def _top(items, key, n=3, reverse=True):
    return sorted((i for i in items if key(i) is not None), key=key, reverse=reverse)[:n]


def _score_txt(i):
    return f"{i['score']:.1f} 分"


def _score_num(i):
    return f"{i['score']:.1f}"


def _fmt_inds(items, fmt):
    return "、".join(f"{_name(i)}（{fmt(i)}）" for i in items) or "無"


def _market(idx, days):
    for nm in (PRICE_INDEX, MARKET_INDEX):
        r = window_return(idx.get(nm), days)
        if r:
            last = idx[nm][-1]
            return {"name": nm, "close": last[1], "day_pct": last[2], "win": r}
    return None


def _levels_text(inds):
    by = {}
    for i in inds:
        by.setdefault(i.get("level") or "—", []).append(i)
    order = ("LEVEL 4", "LEVEL 3", "LEVEL 2", "LEVEL 1", "LEVEL R")
    parts = [f"{lv}：{_fmt_inds(by[lv], lambda x: x.get('signal') or '')}" for lv in order if lv in by]
    return "；".join(parts) or "沒有預警資料"


def _contradictions(flows, mkt, inds):
    out = []
    if flows and mkt:
        day = flows[-1]
        if day["total"] < 0 and (mkt["day_pct"] or 0) > 0:
            out.append(f"當日三大法人合計賣超 {abs(day['total']):.1f} 億，但大盤 {mkt['name']} 當日仍上漲 {mkt['day_pct']:+.2f}%，賣壓沒有壓倒買盤。")
        if day["total"] > 0 and (mkt["day_pct"] or 0) < 0:
            out.append(f"當日三大法人合計買超 {day['total']:.1f} 億，但大盤當日下跌 {mkt['day_pct']:+.2f}%，買盤沒有擋住賣壓。")
        win = flows[-5:]
        if len(win) >= 3 and all(r["foreign"] < 0 for r in win) and mkt["win"]["pct"] > 0:
            out.append(f"外資近 {len(win)} 日全部賣超 (合計 {sum(r['foreign'] for r in win):.0f} 億)，但大盤同期累計 {mkt['win']['pct']:+.2f}%。")
    scored = [i for i in inds if i.get("score") is not None]
    if scored:
        best = max(scored, key=lambda i: i["score"])
        worst = min(scored, key=lambda i: i["score"])
        bm = best.get("metrics") or {}
        wm = worst.get("metrics") or {}
        if bm.get("inst_net_billion") is not None and bm["inst_net_billion"] < 0:
            out.append(f"分數最高的 {_name(best)} ({best['score']:.1f}) 當日外資+投信淨賣超 {abs(bm['inst_net_billion']):.1f} 億，分數與法人買賣方向相反。")
        if wm.get("inst_net_billion") is not None and wm["inst_net_billion"] > 0:
            out.append(f"分數最低的 {_name(worst)} ({worst['score']:.1f}) 當日外資+投信淨買超 {wm['inst_net_billion']:.1f} 億，分數與法人買賣方向相反。")
    return out[:4] or ["本期資料裡沒有偵測到明顯互相矛盾的訊號 (不代表沒有風險，只是這幾項規則沒有被觸發)。"]


def _tracking(flows, inds, next_note):
    out = []
    if flows:
        win = flows[-5:]
        tot = sum(r["foreign"] for r in win)
        out.append(f"外資近 {len(win)} 日合計是否回到 {FOREIGN_SELL_ALERT_BILLION:,.0f} 億以上 (目前 {tot:+,.0f} 億)。")
    scored = [i for i in inds if i.get("score") is not None]
    if scored:
        best = max(scored, key=lambda i: i["score"])
        worst = min(scored, key=lambda i: i["score"])
        out.append(f"分數最高 ({_name(best)}) 與最低 ({_name(worst)}) 的產業是否在下一個交易日維持原位。")
    out.append(next_note)
    return " ".join(f"{k + 1}. {t}" for k, t in enumerate(out))


def _base(freq, rid, title, cutoff, now_iso, summary, findings, counter, tracking, tag):
    return {"report_id": rid, "frequency": freq, "report_title": title, "as_of_cutoff_date": cutoff, "published_at": now_iso,
            "update_status": "即時產生（官方資料，機械式規則）", "primary_sources": SOURCES, "executive_summary": summary,
            "key_findings_json": json.dumps(findings, ensure_ascii=False), "assumptions_and_limits": LIMITS,
            "counter_evidence": "反方證據：" + " ".join(counter), "tracking_indicators": tracking, "version_tag": tag}


def build_daily(ctx):
    flows, idx, inds = ctx["flows"], ctx["idx"], ctx["inds"]
    if not flows:
        return None
    day = flows[-1]
    d = day["date"]
    mkt = _market(idx, 5)
    win = flows[-5:]
    scored = [i for i in inds if i.get("score") is not None]
    top, bot = _top(scored, lambda i: i["score"]), _top(scored, lambda i: i["score"], reverse=False)
    buy = [i for i in _top(inds, lambda i: (i.get("metrics") or {}).get("inst_net_billion")) if i["metrics"]["inst_net_billion"] > 0]
    sell = [i for i in _top(inds, lambda i: (i.get("metrics") or {}).get("inst_net_billion"), reverse=False) if i["metrics"]["inst_net_billion"] < 0]
    m = lambda i: (i.get("metrics") or {}).get("inst_net_billion")   # noqa: E731

    mk_txt = (f"大盤 {mkt['name']} 收 {mkt['close']:,.2f}，當日 {_sg(mkt['day_pct'], 2, '%')}；{mkt['win']['from'][5:]}~{mkt['win']['to'][5:]} 累計 {_sg(mkt['win']['pct'], 2, '%')}。"
              if mkt else "大盤指數資料不足。")
    s1 = (f"{d} 三大法人合計 {_sg(day['total'])} 億元：外資 {_sg(day['foreign'])}、投信 {_sg(day['itc'])}、自營商 {_sg(day['dealer'])}。"
          f"近 {len(win)} 個交易日合計 {_sg(sum(r['total'] for r in win), 0)} 億（外資 {_sg(sum(r['foreign'] for r in win), 0)}、投信 {_sg(sum(r['itc'] for r in win), 0)}）。{mk_txt}")
    s2 = (f"即時評分最高：{_fmt_inds(top, _score_txt)}；最低：{_fmt_inds(bot, _score_txt)}。"
          f"法人當日淨買超最多：{_fmt_inds(buy, lambda i: _sg(m(i), 1, ' 億'))}；淨賣超最多：{_fmt_inds(sell, lambda i: _sg(m(i), 1, ' 億'))}。")
    s3 = _levels_text(inds)
    picks = ctx.get("picks") or []
    pri = [p for p in picks if p["watchlist_category"] == "優先研究"][:5]
    s4 = ("、".join(f"{p['ticker']} {p['company_name']}（營收年增 {_sg(p['rev_yoy_pct'], 1, '%')}）" for p in pri)
          or "目前沒有同時符合「營收強、估值合理、法人買超、月增為正」的個股。")
    findings = [{"section": "一、三大法人與大盤", "content": s1}, {"section": "二、產業分數與法人買賣金額", "content": s2},
                {"section": "三、預警等級分布", "content": s3}, {"section": "四、個股篩選（優先研究）", "content": s4}]
    summary = (f"{d} 三大法人合計 {_sg(day['total'])} 億（外資 {_sg(day['foreign'])}、投信 {_sg(day['itc'])}）；"
               + (f"大盤當日 {_sg(mkt['day_pct'], 2, '%')}；" if mkt else "")
               + (f"即時評分最高 {_name(top[0])} {top[0]['score']:.1f}、最低 {_name(bot[0])} {bot[0]['score']:.1f}。" if top and bot else ""))
    return _base("每日", f"RPT_LIVE_DAILY_{d.replace('-', '')}", f"【每日資金盤後日報】{d}", f"{d} 盤後", ctx["now"], summary, findings,
                 _contradictions(flows, mkt, inds), _tracking(flows, inds, "下一個交易日收盤後 (約 17:30) 重新產生。"), f"live-D-{d}")


def _week_key(iso):
    y, w, _ = date.fromisoformat(iso).isocalendar()
    return y, w


def build_weekly(ctx):
    flows, idx, inds = ctx["flows"], ctx["idx"], ctx["inds"]
    if not flows:
        return None
    y, w = _week_key(flows[-1]["date"])
    wk = [r for r in flows if _week_key(r["date"]) == (y, w)]
    first, last = wk[0]["date"], wk[-1]["date"]
    mkt = _market(idx, len(wk))
    daily_line = "、".join(f"{r['date'][5:]} {_sg(r['total'], 0)}" for r in wk)
    s1 = (f"{y} 年第 {w} 週（{first[5:]}~{last[5:]}，共 {len(wk)} 個交易日有資料）三大法人合計 {_sg(sum(r['total'] for r in wk), 0)} 億元："
          f"外資 {_sg(sum(r['foreign'] for r in wk), 0)}、投信 {_sg(sum(r['itc'] for r in wk), 0)}、自營商 {_sg(sum(r['dealer'] for r in wk), 0)}。逐日合計（億）：{daily_line}。"
          + (f"大盤 {_sg(mkt['win']['pct'], 2, '%')}（{mkt['win']['from'][5:]}~{mkt['win']['to'][5:]}）。" if mkt else ""))
    rows = [r for r in ctx["daily_ind"] if _week_key(r["trade_date"]) == (y, w)]
    days = sorted({r["trade_date"] for r in rows})
    agg = {}
    for r in rows:
        a = agg.setdefault(r["industry_id"], 0.0)
        agg[r["industry_id"]] = a + (r["foreign_billion"] or 0) + (r["itc_billion"] or 0)
    named = [{"id": k, "name": k, "v": v} for k, v in agg.items()]
    if named:
        b, s = _top(named, lambda i: i["v"]), _top(named, lambda i: i["v"], reverse=False)
        s2 = (f"本週產業累計外資+投信淨買賣（僅累積 {len(days)} 個交易日的產業資料）：買超最多 "
              f"{_fmt_inds([x for x in b if x['v'] > 0], lambda i: _sg(i['v'], 1, ' 億'))}；賣超最多 {_fmt_inds([x for x in s if x['v'] < 0], lambda i: _sg(i['v'], 1, ' 億'))}。")
    else:
        s2 = "本週還沒有累積產業層級的法人買賣金額資料 (從導入即時評分的那一天起才開始記錄)。"
    hist = [h for h in ctx["history"] if _week_key(h["snapshot_date"]) == (y, w)]
    hd = sorted({h["snapshot_date"] for h in hist})
    if len(hd) >= 2:
        f0 = {h["industry_id"]: h["total_weighted_score"] for h in hist if h["snapshot_date"] == hd[0]}
        f1 = {h["industry_id"]: h["total_weighted_score"] for h in hist if h["snapshot_date"] == hd[-1]}
        ch = [{"id": k, "name": k, "v": f1[k] - f0[k]} for k in f1 if k in f0 and f1[k] is not None and f0[k] is not None]
        up, dn = _top(ch, lambda i: i["v"]), _top(ch, lambda i: i["v"], reverse=False)
        s3 = f"評分變化（{hd[0][5:]}→{hd[-1][5:]}）：上升最多 {_fmt_inds(up, lambda i: _sg(i['v'], 1))}；下降最多 {_fmt_inds(dn, lambda i: _sg(i['v'], 1))}。"
    else:
        s3 = f"本週只有 {len(hd)} 天的即時評分快照，尚不足以比較評分變化。"
    findings = [{"section": "一、本週三大法人與大盤", "content": s1}, {"section": "二、產業累計法人買賣金額", "content": s2},
                {"section": "三、評分變化", "content": s3}, {"section": "四、目前預警等級分布", "content": _levels_text(inds)}]
    summary = f"{y} 年第 {w} 週（{first[5:]}~{last[5:]}）三大法人合計 {_sg(sum(r['total'] for r in wk), 0)} 億，外資 {_sg(sum(r['foreign'] for r in wk), 0)}、投信 {_sg(sum(r['itc'] for r in wk), 0)}；僅涵蓋 {len(wk)} 個交易日。"
    return _base("每週", f"RPT_LIVE_WEEKLY_{y}W{w:02d}", f"【每週資金輪動週報】{y} 年第 {w} 週（{first[5:]}~{last[5:]}）", f"{last} 盤後（{y}-W{w:02d}）",
                 ctx["now"], summary, findings, _contradictions(wk, mkt, inds), _tracking(flows, inds, "下週一至週五每日更新；週五收盤後為完整週報。"), f"live-W-{y}W{w:02d}")


def build_monthly(ctx):
    flows, idx, inds = ctx["flows"], ctx["idx"], ctx["inds"]
    if not flows:
        return None
    ym = flows[-1]["date"][:7]
    mo = [r for r in flows if r["date"][:7] == ym]
    rev = ctx.get("revenue") or {}
    ranked = [i for i in inds if (i.get("metrics") or {}).get("yoy") is not None]
    top = _top(ranked, lambda i: i["metrics"]["yoy"])
    bot = _top(ranked, lambda i: i["metrics"]["yoy"], reverse=False)
    s1 = (f"{rev.get('label', '最新月')}全市場 {rev.get('companies', 'N/A')} 家上市櫃公司營收 {rev.get('total_trillion', 'N/A')} 兆元，年增 {_sg(rev.get('yoy_pct'), 1, '%')}。"
          f"產業營收年增最高：{_fmt_inds(top, lambda i: _sg(i['metrics']['yoy'], 1, '%'))}；最低：{_fmt_inds(bot, lambda i: _sg(i['metrics']['yoy'], 1, '%'))}。")
    mkt = _market(idx, len(mo))
    s2 = (f"{ym} 月累計（{mo[0]['date'][5:]}~{mo[-1]['date'][5:]}，僅 {len(mo)} 個交易日有資料，非整月）三大法人合計 {_sg(sum(r['total'] for r in mo), 0)} 億："
          f"外資 {_sg(sum(r['foreign'] for r in mo), 0)}、投信 {_sg(sum(r['itc'] for r in mo), 0)}、自營商 {_sg(sum(r['dealer'] for r in mo), 0)}。"
          + (f"大盤同期 {_sg(mkt['win']['pct'], 2, '%')}。" if mkt else ""))
    scored = [i for i in inds if i.get("score") is not None]
    s3 = (f"目前即時評分前三：{_fmt_inds(_top(scored, lambda i: i['score']), _score_num)}；後三："
          f"{_fmt_inds(_top(scored, lambda i: i['score'], reverse=False), _score_num)}。")
    findings = [{"section": "一、最新月營收與產業排名", "content": s1}, {"section": "二、當月累計三大法人", "content": s2},
                {"section": "三、產業評分", "content": s3}, {"section": "四、預警等級分布", "content": _levels_text(inds)}]
    summary = f"{rev.get('label', '最新月')}營收 {rev.get('total_trillion', 'N/A')} 兆、年增 {_sg(rev.get('yoy_pct'), 1, '%')}；{ym} 月累計三大法人 {_sg(sum(r['total'] for r in mo), 0)} 億（{len(mo)} 個交易日）。"
    y, mth = ym.split("-")
    return _base("每月", f"RPT_LIVE_MONTHLY_{y}{mth}", f"【每月營收與資金月報】{y} 年 {int(mth)} 月", f"{mo[-1]['date']} 盤後（營收為{rev.get('label', '最新月')}）",
                 ctx["now"], summary, findings, _contradictions(mo, mkt, inds),
                 _tracking(flows, inds, "每月 10 日前公布下一期月營收後，月報的營收段落會更新。"), f"live-M-{ym}")


# ---------------------------------------------------------------------------
# 資料庫存取
# ---------------------------------------------------------------------------
def gather_context(conn):
    from live_scoring import compute_industry_metrics, load_inputs

    cur = conn.cursor()
    cur.execute("SELECT * FROM institutional_flows")
    flows = live_daily_flows([dict(r) for r in cur.fetchall()])
    cur.execute("SELECT index_name, trade_date, close_index, change_pct FROM live_market_indices")
    idx = index_series([dict(r) for r in cur.fetchall()])
    cur.execute("SELECT version_id FROM model_governance_configs WHERE active = 1 ORDER BY created_at DESC LIMIT 1")
    version = cur.fetchone()["version_id"]
    comps, turn, rr, info = load_inputs(conn)
    metrics = compute_industry_metrics(comps, turn, rr)
    cur.execute("SELECT industry_id, industry_name FROM industry_taxonomy")
    names = {r["industry_id"]: r["industry_name"] for r in cur.fetchall()}
    cur.execute("SELECT industry_id, total_weighted_score, rotation_state, score_source FROM industry_rotation_scores WHERE model_version = ?", (version,))
    scores = {r["industry_id"]: dict(r) for r in cur.fetchall()}
    cur.execute("SELECT industry_id, alert_level, signal_category, text_source FROM trend_early_warnings")
    warns = {r["industry_id"]: dict(r) for r in cur.fetchall()}
    inds = []
    for k, m in metrics.items():
        sc = scores.get(k, {})
        live = sc.get("score_source") == "live"
        inds.append({"id": k, "name": names.get(k, k), "metrics": m, "score": sc.get("total_weighted_score") if live else None,
                     "state": sc.get("rotation_state"), "level": (warns.get(k) or {}).get("alert_level") if live else None,
                     "signal": (warns.get(k) or {}).get("signal_category") if live else None})
    cur.execute("SELECT * FROM live_industry_daily")
    daily_ind = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT snapshot_date, industry_id, total_weighted_score FROM industry_score_history WHERE score_source = 'live' AND model_version = ?", (version,))
    history = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM company_research_watchlist WHERE text_source = 'live'")
    picks = [dict(r) for r in cur.fetchall()]
    cur.execute("""SELECT COUNT(*) n, ROUND(SUM(rev_current_thousand)/1e9, 4) t, ROUND(SUM(rev_last_year_thousand)/1e9, 4) ly, MAX(data_ym) ym
                   FROM live_company_fundamentals""")
    r = cur.fetchone()
    ym = str(r["ym"] or "")
    rev = {"companies": r["n"], "total_trillion": r["t"], "yoy_pct": ((r["t"] / r["ly"] - 1) * 100) if r["ly"] else None,
           "label": f"{int(ym[:-2]) + 1911} 年 {int(ym[-2:])} 月" if ym.isdigit() and len(ym) >= 4 else "最新月"}
    from common import now_iso
    return {"flows": flows, "idx": idx, "inds": inds, "daily_ind": daily_ind, "history": history, "picks": picks, "revenue": rev,
            "now": now_iso()}


def apply_live_reports(conn=None):
    """產生並寫入每日／週／月報；舊的手寫同頻率報告被取代，各頻率只保留最近幾份。沒有法人資料時不動。"""
    from db import get_connection

    own = conn is None
    conn = conn or get_connection()
    try:
        ctx = gather_context(conn)
        reports = [r for r in (build_daily(ctx), build_weekly(ctx), build_monthly(ctx)) if r]
        if not reports:
            return {"applied": False, "reason": "沒有即時法人資料"}
        cur = conn.cursor()
        for freq in {r["frequency"] for r in reports}:
            cur.execute("DELETE FROM research_reports WHERE frequency = ? AND text_source = 'seed'", (freq,))
        for r in reports:
            cur.execute("""
                INSERT OR REPLACE INTO research_reports
                (report_id, frequency, report_title, as_of_cutoff_date, published_at, update_status, primary_sources, executive_summary,
                 key_findings_json, assumptions_and_limits, counter_evidence, tracking_indicators, version_tag, text_source)
                VALUES (:report_id, :frequency, :report_title, :as_of_cutoff_date, :published_at, :update_status, :primary_sources,
                        :executive_summary, :key_findings_json, :assumptions_and_limits, :counter_evidence, :tracking_indicators, :version_tag, 'live')
            """, r)
        for freq, keep in KEEP.items():
            cur.execute("""DELETE FROM research_reports WHERE frequency = ? AND text_source = 'live' AND report_id NOT IN
                           (SELECT report_id FROM research_reports WHERE frequency = ? AND text_source = 'live'
                            ORDER BY report_id DESC LIMIT ?)""", (freq, freq, keep))
        conn.commit()
        return {"applied": True, "reports": [r["report_id"] for r in reports]}
    finally:
        if own:
            conn.close()
