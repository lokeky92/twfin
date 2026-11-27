"""
趨勢預警中心：由即時評分機械式產生每個產業的預警說明 (取代 seed_and_engine.py 裡 2026-11-22 手寫的 7 則文字)。

原本的預警只有 7 則手寫文字，引用當時的營收與新聞 (例如「奇鋐10月營收221.03億」)，之後不會更新，
等級雖已能跟著分數走，但說明文字仍停在舊時點，會和即時分數互相矛盾。

這裡改成：每次排程對每個「已用即時資料評分」的產業各產生一則預警，所有欄位都來自 live_scoring 算出的數字：
  - 等級：由 scoring.classify_alert_level 依啟用版本的門檻判定 (這裡不在文字裡寫等級，治理頁改門檻後文字不會過期)
  - 訊號類別：由 5 項子分數的組合規則判定 (見 classify_signal)
  - 觸發原因 / 原始數據證據 / 反方證據 / 失效條件 / 缺失資料：全部由當期數字組成
不含任何事件敘事、新聞、分析師觀點；也不推測原因。說明文字是機械式規則產生的，會在缺失資料欄明確寫出。

純函式，無資料庫依賴，方便測試。
"""

HIGH, LOW = 65.0, 45.0     # 子分數 (15~95 的相對百分位分數) 的「居前」與「落後」門檻
ONE_OFF_GAP_PP = 40.0      # 單月年增與累計年增相差達此值 (百分點) 時，提醒單月可能是一次性因素


def _pct(x, nd=1):
    return "N/A" if x is None else f"{x:+.{nd}f}%"


def _bn(x):
    return "N/A" if x is None else f"{x:+,.1f} 億"


def classify_signal(scores):
    """回傳 (訊號類別, 期間, 一句話描述)。只用 5 項子分數的高低組合，不推測原因。"""
    cf, fu, fg, ins = scores["capital_flow"], scores["fundamentals"], scores["future_growth"], scores["institutional"]
    strong_fund = fu >= HIGH or fg >= HIGH
    if strong_fund and cf >= HIGH:
        return ("基本面與資金同步居前", "短期(依當日法人與近期相對強弱)至中期(依累計營收動能)",
                "營收動能與資金面同時排名居前。")
    if strong_fund and cf <= LOW:
        return ("基本面居前、資金流向偏弱", "中期(依累計營收動能)",
                "營收年增排名居前，但資金流向排名偏弱。")
    if strong_fund:
        return ("基本面居前、資金面中性", "中期(依累計營收動能)",
                "營收年增排名居前，資金流向在中段，尚無明顯的資金確認或背離。")
    if cf >= HIGH and not strong_fund:
        return ("資金居前、基本面排名未居前(留意追價風險)", "短期(依當日法人與近期相對強弱)",
                "資金與法人買盤排名居前，但營收動能排名未居前 (不代表營收衰退，請看營收年增數字)。")
    if cf <= LOW and fu <= LOW and fg <= LOW:
        return ("資金與基本面同步落後(撤退風險)", "短期(依當日法人與近期相對強弱)至中期",
                "資金流向、營收與成長動能都排名落後。")
    if cf <= LOW:
        return ("資金流向落後", "短期(依當日法人與近期相對強弱)",
                "資金流向排名落後，但基本面沒有同步轉弱。")
    return ("多空分歧、無明顯單向訊號", "短期至中期", "各項分數互有高低，沒有明顯單向訊號。")


def _score_line(scores, labels):
    return "／".join(f"{labels[k]} {scores[k]:.0f}" for k in ("capital_flow", "fundamentals", "future_growth", "institutional", "valuation"))


def build_warning(industry_id, name, m, res, total, level, n_ranked, leaning_up, labels, limitations, now_iso):
    """
    m: live_scoring.compute_industry_metrics 的單一產業指標；res: score_industries 的單一產業結果；
    total: 總分；level: 預警等級 (LEVEL 1~4 / LEVEL R)；n_ranked: 參與排名的產業數；leaning_up: 總分是否高於產業中位數。
    回傳可直接寫入 trend_early_warnings 的 dict。
    """
    sc = res["scores"]
    category, horizon, sentence = classify_signal(sc)

    trigger = (f"{name}：即時評分 {total:.1f} 分（{_score_line(sc, labels)}；皆為相對其他 {n_ranked} 個產業的百分位分數）。{sentence}")

    evidence_parts = [
        f"單月營收年增 {_pct(m['yoy'])}、累計營收年增 {_pct(m['cum_yoy'])}、營收加速度 {_pct(m['accel'])}（旗下 {m['companies']} 家公司，營收 {m['rev_billion']:,.1f} 億 vs 去年同月 {m['rev_ly_billion']:,.1f} 億）",
        f"法人當日淨買賣：外資 {_bn(m['foreign_billion'])}、投信 {_bn(m['itc_billion'])}、自營商 {_bn(m['dealer_billion'])}"
        + (f"（外資+投信占產業成交值 {m['inst_ratio_pct']:+.2f}%）" if m["inst_ratio_pct"] is not None else ""),
        ("近 %d 日相對大盤 %s" % (m["rs_days"], _pct(m["rs_pct"], 2))) if m["rs_pct"] is not None else "類股相對強弱資料不足",
        ("本益比中位數 %.1f 倍" % m["pe_median"] if m["pe_median"] is not None else "本益比 N/A")
        + (f"、PEG 代理 {m['peg']:.2f}" if m["peg"] is not None else ""),
    ]
    if m["share_change_pct"] is not None:
        evidence_parts.append(f"成交值占比相對前幾日均值 {_pct(m['share_change_pct'])}")
    evidence = "；".join(evidence_parts) + "。"

    # 反方證據：訊號偏多就列「低於門檻」的最弱項目，偏空就列「高於門檻」的最強項目；沒有就明說，不硬湊
    ranked = sorted(sc, key=lambda k: sc[k], reverse=True)
    if leaning_up:
        weak = [k for k in ranked[::-1][:2] if sc[k] < HIGH]
        counter = ("；".join(f"{labels[k]} {sc[k]:.0f} 分" for k in weak) + "，相對其他產業偏弱，是偏多訊號的反面。") if weak             else "各項分數都在中上，沒有明顯落後的項目。"
    else:
        strong = [k for k in ranked[:2] if sc[k] > LOW]
        counter = ("；".join(f"{labels[k]} {sc[k]:.0f} 分" for k in strong) + "，相對其他產業並不弱，是偏空訊號的反面。") if strong             else "各項分數都偏低，沒有明顯居前的項目。"

    if leaning_up:
        floor = max(m["yoy"] / 2, 0) if m["yoy"] is not None else 0
        invalid = (f"下個月營收年增由 {_pct(m['yoy'])} 掉到 {floor:.0f}% 以下、或法人淨買賣轉為連續賣超、"
                   "或相對大盤轉為落後，即時評分會下降、此訊號失效。")
    else:
        invalid = (f"下個月營收年增由 {_pct(m['yoy'])} 明顯回升、或法人淨買賣轉為連續買超、"
                   "或相對大盤轉為領先，即時評分會上升、此訊號失效。")

    missing = [labels[k] for k in res["missing"]]
    notes = ["本則預警由機械式規則依即時評分自動產生，不是分析師撰寫；每個交易日收盤後重算。", limitations]
    if missing:
        notes.append(f"本次缺少：{'、'.join(missing)}（以 50 分中性值代入）。")
    if m["price_coverage"] < 0.999:
        notes.append(f"法人金額只涵蓋有收盤價的公司（覆蓋率 {m['price_coverage'] * 100:.0f}%）。")
    if m["share_change_pct"] is None:
        notes.append("成交值占比變化需至少 2 天歷史，目前尚不足。")
    if m["yoy"] is not None and m["cum_yoy"] is not None and abs(m["yoy"] - m["cum_yoy"]) >= ONE_OFF_GAP_PP:
        notes.append(f"單月營收年增 {_pct(m['yoy'])} 與累計年增 {_pct(m['cum_yoy'])} 相差 {abs(m['yoy'] - m['cum_yoy']):.0f} 個百分點，"
                     "單月可能受一次性或認列時點影響（金融、營建等產業常見），不宜單看一個月。")

    return {
        "warning_id": f"LIVE_{industry_id}",
        "industry_id": industry_id,
        "alert_level": level,
        "signal_category": category,
        "horizon": horizon,
        "trigger_reason": trigger,
        "raw_data_evidence": evidence,
        "triggered_at": now_iso,
        "source_id": "SRC_MOPS",
        "credibility_grade": "A級官方數據（代理指標）" if not missing else f"B級（缺 {len(missing)} 項子分數）",
        "missing_data_notes": " ".join(notes),
        "counter_evidence": counter,
        "invalidation_conditions": invalid,
    }
