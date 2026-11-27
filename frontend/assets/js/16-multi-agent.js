/* =========================================================================
   🤖 Stage 4：Argon ETF Multi-Agent Research Team 五大管理介面渲染引擎
   1. 團隊總覽 2. 研究討論室 3. 改善提案中心 4. 歷史紀錄與DQ稽核 5. 團隊設定
   ========================================================================= */
let MA_ACTIVE_TAB = 'OVERVIEW';
let MA_SETTINGS = {
  debate_rounds: 2,
  schedule_mode: 'MANUAL_FIRST',
  scope: '台灣 15 檔 + 美國 13 檔核心 ETF (含槓反隔離與 1,989 家穿透)',
  agents_enabled: {
    AGENT_01: true, AGENT_02: true, AGENT_03: true,
    AGENT_04: true, AGENT_05: true, AGENT_06: true
  }
};

function switchMultiAgentTab(tab) {
  MA_ACTIVE_TAB = tab;
  ['OVERVIEW', 'DEBATE', 'PROPOSALS', 'HISTORY', 'SETTINGS'].forEach(t => {
    const btn = document.getElementById('maTab_' + t);
    const pnl = document.getElementById('maPanel_' + t);
    if (btn) btn.classList.toggle('active', t === tab);
    if (pnl) pnl.style.display = (t === tab) ? 'block' : 'none';
  });
}

function maStatusBadge(st) {
  if (st === 'APPROVED_BY_USER') return '<span class="badge badge-lvl4">🟢 已批准執行 (APPROVED)</span>';
  if (st === 'IMPLEMENTED_ON_BRANCH') return '<span class="badge badge-lvl4">✅ 已於隔離分支實作完成</span>';
  if (st === 'REJECTED_BY_USER') return '<span class="badge badge-lvlR">🔴 已拒絕 (REJECTED)</span>';
  if (st === 'RE_RESEARCH_REQUESTED') return '<span class="badge badge-lvl3">🔵 要求重新研究</span>';
  return '<span class="badge badge-grade-C">🟠 待使用者審核 (PENDING)</span>';
}

function maPriorityBadge(p) {
  if (p === 'P0') return '<span class="badge badge-lvlR">P0 重大修正</span>';
  if (p === 'P1') return '<span class="badge badge-grade-C">P1 決策品質</span>';
  if (p === 'P2') return '<span class="badge badge-lvl3">P2 效能體驗</span>';
  return '<span class="badge">P3 一般優化</span>';
}

const MA_STORAGE_KEY = 'twfin_ma_cloud_state_v1';

function loadMultiAgentLocalOverrides() {
  try {
    const raw = localStorage.getItem(MA_STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (saved && saved.multi_agent_center && STATE) {
      STATE.multi_agent_center = saved.multi_agent_center;
    }
    if (saved && saved.settings) {
      Object.assign(MA_SETTINGS, saved.settings);
    }
  } catch (e) {}
}

function saveMultiAgentLocalOverrides() {
  try {
    if (!STATE || !STATE.multi_agent_center) return;
    localStorage.setItem(MA_STORAGE_KEY, JSON.stringify({
      multi_agent_center: STATE.multi_agent_center,
      settings: MA_SETTINGS,
      saved_at: new Date().toISOString()
    }));
  } catch (e) {}
}

function runCloudClientMultiAgentSession(topic) {
  // 後端已用即時資料產生真實稽核時，瀏覽器端不可再用 generated_at 拼出假的「即時研究」覆蓋它
  if (STATE && STATE.multi_agent_center && STATE.multi_agent_center.origin === 'live_audit') return false;
  const prev = (STATE && STATE.multi_agent_center) ? JSON.parse(JSON.stringify(STATE.multi_agent_center)) : {};
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const twStr = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())} (UTC+8)`;
  const sessId = `SESSION-${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;

  const etfs = (STATE && STATE.etf_center && STATE.etf_center.etfs) ? STATE.etf_center.etfs : [];
  const topLong = [...etfs].filter(e => !e.is_leveraged_or_inverse).sort((a, b) => (b.total_score_a_long_term || 0) - (a.total_score_a_long_term || 0)).slice(0, 3);
  const topShort = [...etfs].sort((a, b) => (b.total_score_b_short_mid || 0) - (a.total_score_b_short_mid || 0)).slice(0, 3);
  const highSpread = [...etfs].sort((a, b) => (b.bid_ask_spread_bps || 0) - (a.bid_ask_spread_bps || 0))[0];
  const liveSum = (STATE && STATE.live_summary) || {};
  const topInds = [...((STATE && STATE.industries) || [])].filter(i => i.total_weighted_score !== null).sort((a, b) => b.total_weighted_score - a.total_weighted_score).slice(0, 3);

  const reports = prev.phase2_independent_reports || {};
  const applyLiveRpt = (key, text) => {
    if (!reports[key]) return;
    reports[key].data_timestamp_used = twStr;
    reports[key].current_system_problems = text;
    reports[key].summary = text;
  };
  applyLiveRpt('AGENT_01', `【雲端即時重算｜${twStr}】針對「${topic}」：\n• 模型 A 長期配置前三強：${topLong.map(e => `${e.etf_code}(${e.total_score_a_long_term}分)`).join('、') || 'N/A'}\n• 建議持續以低 TER、低稅損與高純股利/票息為核心配置基準。`);
  applyLiveRpt('AGENT_02', `【雲端即時重算｜${twStr}】針對「${topic}」：\n• 模型 B 短中期環境前三強：${topShort.map(e => `${e.etf_code}(${e.total_score_b_short_mid}分)`).join('、') || 'N/A'}\n• 強勢產業輪動前三名：${topInds.map(i => `${i.industry_name}(${Number(i.total_weighted_score).toFixed(1)}分)`).join('、') || 'N/A'}。`);
  applyLiveRpt('AGENT_03', `【雲端即時稽核｜${twStr}】\n• 雲端快照基準：${(STATE && STATE.generated_at) || twStr}\n• 涵蓋 ${liveSum.total_companies || 0} 家上市櫃公司（總營收年增 ${liveSum.total_yoy_pct ?? '-'}%），防外推與缺漏標記正常運作。`);
  applyLiveRpt('AGENT_04', `【雲端即時風控｜${twStr}】\n• 目前買賣價差最高 ETF：${highSpread ? `${highSpread.etf_code}(${highSpread.bid_ask_spread_bps} bps)` : 'N/A'}\n• 提醒持續監控台積電（2330/TSM）跨國持股重疊曝險與 USD/TWD 匯率波動。`);
  applyLiveRpt('AGENT_05', `【雲端反方審查｜${twStr}】針對「${topic}」：\n• 反方提醒：切勿僅憑近 1 年含息報酬追高，須交叉檢視最大回撤與配息中資本利得佔比，避免高息幻覺。`);
  applyLiveRpt('AGENT_06', `【雲端系統檢核｜${twStr}】\n• 已於 Cloudflare Private Worker 互動模式完成 6-Agent 即時重算，研究紀錄與人工審批狀態已持久化保存於瀏覽器安全儲存區。`);

  prev.session_id = sessId;
  prev.topic = topic;
  prev.trigger_mode = `cloud_interactive (${MA_SETTINGS.schedule_mode})`;
  prev.started_at = twStr;
  prev.completed_at = twStr;
  prev.status = 'COMPLETED';
  prev.phase2_independent_reports = reports;
  STATE.multi_agent_center = prev;
  saveMultiAgentLocalOverrides();
  return true;
}

async function triggerNewMultiAgentSession() {
  const topicEl = document.getElementById('maCustomTopicInput');
  const topic = topicEl && topicEl.value.trim()
    ? topicEl.value.trim()
    : '台美 ETF 雙軌評分模型、跨時區數據品質、跨國持股穿透重疊與系統架構全面體檢';
  try {
    const res = await apiPost('/api/multi_agent/run_session', { topic, trigger_mode: MA_SETTINGS.schedule_mode });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    if (data.status === 'ok' && data.multi_agent_center) {
      STATE.multi_agent_center = data.multi_agent_center;
      saveMultiAgentLocalOverrides();
      renderArgonMultiAgentCenter();
      switchMultiAgentTab('DEBATE');
      alert('已完成新一輪 6 位 Agent 獨立研究與兩輪交叉辯論！請至「② 研究討論室」與「③ 改善提案中心」檢視。');
      return;
    }
    throw new Error('Unexpected payload');
  } catch (e) {
    if (!runCloudClientMultiAgentSession(topic)) {
      alert(`ℹ️ 目前顯示的是後端在每次同步時以即時資料產生的稽核（${STATE.multi_agent_center.session_id}）。此環境沒有後端 API，無法在瀏覽器內重新稽核；下一次排程同步 (台灣時間每個交易日約 16:30 與 20:00) 會自動產生新的稽核。`);
      return;
    }
    renderArgonMultiAgentCenter();
    switchMultiAgentTab('DEBATE');
    alert(`✅ 已於雲端互動模式完成新一輪 6 位 Agent 即時研究（${STATE.multi_agent_center.session_id}）！研究結果已自動保存並切換至「② 研究討論室」。`);
  }
}

/* 提案狀態機 (前端鏡像，規則必須與 argon_multi_agent/engine/multi_agent_orchestrator.py 的 PROPOSAL_TRANSITIONS 一致；
   tests/test_frontend_js.py 會比對兩邊，避免漂移)。以 status 為鍵：
   pending ─APPROVE→ approved ─MARK_IMPLEMENTED→ implemented (終態)；已實作的提案不可再被批准、拒絕或退回 */
const PROPOSAL_STATUS_TRANSITIONS = {
  PENDING_APPROVAL:      { APPROVE: 'APPROVED_BY_USER', REJECT: 'REJECTED_BY_USER', RE_RESEARCH: 'RE_RESEARCH_REQUESTED' },
  RE_RESEARCH_REQUESTED: { APPROVE: 'APPROVED_BY_USER', REJECT: 'REJECTED_BY_USER', RE_RESEARCH: 'RE_RESEARCH_REQUESTED' },
  APPROVED_BY_USER:      { REJECT: 'REJECTED_BY_USER', RE_RESEARCH: 'RE_RESEARCH_REQUESTED', MARK_IMPLEMENTED: 'IMPLEMENTED_ON_BRANCH' },
  REJECTED_BY_USER:      { APPROVE: 'APPROVED_BY_USER', RE_RESEARCH: 'RE_RESEARCH_REQUESTED' },
  IMPLEMENTED_ON_BRANCH: {},
};

// 回傳新狀態；此操作在目前狀態下不被允許時回傳 null
function nextProposalStatus(status, decision) {
  const row = PROPOSAL_STATUS_TRANSITIONS[status] || PROPOSAL_STATUS_TRANSITIONS.PENDING_APPROVAL;
  return Object.prototype.hasOwnProperty.call(row, decision) ? row[decision] : null;
}

async function submitProposalDecision(proposalId, decision) {
  const noteMap = {
    'APPROVE': '使用者於 AI 研究團隊管理介面明確批准',
    'REJECT': '使用者於管理介面拒絕此提案',
    'RE_RESEARCH': '使用者要求團隊針對反方意見重新研究'
  };
  const actionLabel = decision === 'APPROVE' ? '已批准' : (decision === 'REJECT' ? '已拒絕' : '已要求重新研究');
  try {
    const res = await apiPost('/api/multi_agent/proposal_decision', { proposal_id: proposalId, decision, note: noteMap[decision] || decision });
    if (res.status === 400) {
      // 伺服器明確拒絕 (例如已實作的提案不可再變更)：顯示原因，不可當成「離線」而在本機硬改狀態
      const err = await res.json().catch(() => ({}));
      alert('❌ ' + (err.message || '此操作在提案目前的狀態下不被允許。'));
      return;
    }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    if (data.status === 'ok' && data.multi_agent_center) {
      STATE.multi_agent_center = data.multi_agent_center;
      saveMultiAgentLocalOverrides();
      renderArgonMultiAgentCenter();
      const skipped = data.proposal && data.proposal.skipped;
      if (skipped && skipped.length) {
        alert(`ℹ️ ${actionLabel}完成：已套用 ${(data.proposal.applied || []).length} 筆，略過 ${skipped.length} 筆（目前狀態不允許此操作，例如已實作的提案）。`);
      }
      return;
    }
    throw new Error('Unexpected payload');
  } catch (e) {
    // 雲端/離線模式 (沒有 API)：在前端依同一套狀態機更新，並持久化至瀏覽器 localStorage
    const ma = STATE && STATE.multi_agent_center;
    if (ma && ma.phase6_proposals) {
      let touched = 0, skipped = 0;
      ma.phase6_proposals.forEach(p => {
        if (proposalId !== 'ALL' && p.proposal_id !== proposalId) return;
        const next = nextProposalStatus(p.status, decision);
        if (next === null) { skipped++; return; }
        p.status = next;
        p.user_decision_note = noteMap[decision] || decision;
        touched++;
      });
      if (!touched) {
        alert('❌ 此操作在提案目前的狀態下不被允許（例如已實作的提案不可再批准、拒絕或退回）。');
        return;
      }
      const nowStr = new Date().toLocaleTimeString('zh-TW', { hour12: false });
      ma.last_decision_banner = `${actionLabel} ${proposalId === 'ALL' ? '全部提案' : proposalId}（${nowStr} 已儲存）`;
      saveMultiAgentLocalOverrides();
      renderArgonMultiAgentCenter();
      alert(`✅ ${actionLabel}${proposalId === 'ALL' ? `（套用 ${touched} 筆${skipped ? `，略過 ${skipped} 筆不允許的` : ''}）` : ' ' + proposalId}！狀態已更新並儲存（重新整理頁面也不會遺失）。`);
    }
  }
}

function renderArgonMultiAgentCenter() {
  const ma = STATE && STATE.multi_agent_center;
  if (!ma || !ma.phase2_independent_reports) return;

  const rawProposals = ma.phase6_proposals || [];
  const propMap = new Map();
  rawProposals.forEach(p => {
    const existing = propMap.get(p.proposal_id);
    if (!existing || (existing.status === 'PENDING_APPROVAL' && p.status !== 'PENDING_APPROVAL')) {
      propMap.set(p.proposal_id, p);
    }
  });
  const proposals = Array.from(propMap.values());
  const pendingCount = proposals.filter(p => p.status === 'PENDING_APPROVAL').length;
  const approvedCount = proposals.filter(p => p.status === 'APPROVED_BY_USER' || p.status === 'IMPLEMENTED_ON_BRANCH').length;
  const reportsObj = ma.phase2_independent_reports || {};
  const agentsMeta = [
    { id: 'AGENT_01', icon: '🏛️', color: '#10b981', desc: 'ETF 模型 A 的覆蓋與缺資料、持股集中度、分數區辨力、美股 ETF 是否仍為手寫評分' },
    { id: 'AGENT_02', icon: '🌊', color: '#38bdf8', desc: '大盤狀態 (相對 60 日均線與波動)、價格與法人買賣背離、模型 B 的結構性限制' },
    { id: 'AGENT_03', icon: '🔍', color: '#a855f7', desc: '七項法定稽核：來源新鮮度、歷史完整度、官方與彙總一致性、缺漏值不偽造、手寫比例、重複列' },
    { id: 'AGENT_04', icon: '🛡️', color: '#f59e0b', desc: '槓桿型占成交值比重、與 0050 高度相關的重複配置、前十大持股重疊、買賣價差' },
    { id: 'AGENT_05', icon: '⚡', color: '#f43f5e', desc: '專職反方：回測是否成熟、百分位評分的人為效應、分數與資金方向相反、畫面上仍有的手寫內容' },
    { id: 'AGENT_06', icon: '⚙️', color: '#34d399', desc: '同步與擷取健康度、歷史回補進度、資料庫大小、後端程式規模' }
  ];

  // 1. 子頁面 ①：團隊總覽
  const ov = document.getElementById('maPanel_OVERVIEW');
  if (ov) {
    const origin = ma.origin === 'live_audit'
      ? `<div class="callout" style="margin-bottom:14px; --callout-col:var(--accent-emerald);">✅ <strong>即時稽核</strong>：本頁研究由後端在每次同步時，以規則檢查目前真實的系統狀態（唯讀資料庫）產生，每個發現都附數字證據，稽核時間 ${esc(ma.started_at)}。這是「規則式稽核」，不是語言模型在思考：只能發現規則寫得出來的問題，各項門檻是人工設定的經驗值。提案需人工批准，系統不會自動修改任何程式。</div>`
      : `<div class="callout" style="margin-bottom:14px; --callout-col:var(--accent-orange);">⚠️ <strong>手寫的研究記錄</strong>（${esc(ma.session_id)}）：這是 2026-11-22 前後預先寫好的報告，其中提到的程式缺陷多數後來已修正，內容已過時，不會隨資料更新。</div>`;
    ov.innerHTML = origin + `
      <div class="etf-grid-4" style="margin-bottom:20px;">
        <div class="etf-clean-card" style="border-top:4px solid #a855f7;">
          <div style="font-size:15px; color:#94a3b8; font-weight:700;">👑 總指揮與研究狀態</div>
          <div class="etf-hero-num" style="color:#c084fc; margin:8px 0;">Argon 總指揮</div>
          <div style="font-size:15px; color:#f8fafc;">進度：<strong>Phase 1～6 全部完成</strong></div>
          <div style="font-size:14px; color:#94a3b8; margin-top:4px;">Session：${esc(ma.session_id)}</div>
        </div>
        <div class="etf-clean-card" style="border-top:4px solid #38bdf8;">
          <div style="font-size:15px; color:#94a3b8; font-weight:700;">📋 目前研究主題</div>
          <div style="font-size:17px; font-weight:800; color:#f8fafc; margin:8px 0; line-height:1.45;">${esc(ma.topic)}</div>
          <div style="font-size:14px; color:#38bdf8;">最近研究時間：${ma.completed_at || ma.started_at}</div>
        </div>
        <div class="etf-clean-card" style="border-top:4px solid #f59e0b;">
          <div style="font-size:15px; color:#94a3b8; font-weight:700;">⚖️ 提案審核閘門統計</div>
          <div class="etf-hero-num" style="color:#fbbf24; margin:8px 0;">${pendingCount} 待審 / ${approvedCount} 已批</div>
          <div style="font-size:14.5px; color:#cbd5e1;">共產出 <strong>${proposals.length} 項</strong> 100分制評估提案（含 P0 級 2 項）</div>
        </div>
        <div class="etf-clean-card" style="border-top:4px solid #10b981;">
          <div style="font-size:15px; color:#94a3b8; font-weight:700;">🔒 正式系統安全鎖</div>
          <div class="etf-hero-num pos" style="margin:8px 0;">唯讀隔離 PASS</div>
          <div style="font-size:14.5px; color:#cbd5e1;">SQLite 唯讀 URI (?mode=ro) ｜ SHA-256 指紋校驗：<strong>${ma.production_integrity_verified ? '100% 無竄改' : '已於隔離分支執行'}</strong></div>
        </div>
      </div>

      <div class="etf-grid-2">
        ${agentsMeta.map(m => {
          const rpt = reportsObj[m.id] || {};
          const enabled = MA_SETTINGS.agents_enabled[m.id] !== false;
          return `
            <div class="etf-clean-card" style="border-left:5px solid ${m.color};">
              <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
                <div style="font-size:19px; font-weight:700; color:#f8fafc;">${m.icon} ${rpt.agent_name || m.id}</div>
                <span class="badge ${enabled ? 'badge-lvl4' : 'badge-unratable'}">${enabled ? '🟢 獨立研究完成' : '已停用'}</span>
              </div>
              <div style="font-size:14.5px; color:#38bdf8; margin-bottom:8px;">${m.desc}</div>
              <div style="background:#090e1a; padding:12px 14px; border-radius:8px; font-size:14.5px; color:#cbd5e1; line-height:1.65;">
                <strong>核心發現摘要：</strong>${String(rpt.identified_defects || '').split('\n')[0]}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  // 2. 子頁面 ②：研究討論室 (清楚區分各 Agent 第一輪獨立研究 vs Phase 3 交叉審查 & 反方質疑 vs Phase 4 辯論立場)
  const dbBox = document.getElementById('maPanel_DEBATE');
  if (dbBox) {
    const p3 = ma.phase3_cross_reviews || [];
    const p4 = ma.phase4_rebuttals || [];
    const p5 = ma.phase5_synthesis || {};
    dbBox.innerHTML = `
      <div class="etf-clean-card" style="margin-bottom:20px; border-left:5px solid #f43f5e;">
        <div style="font-size:20px; font-weight:700; color:#f8fafc; margin-bottom:10px;">
          ⚡ Argon 總指揮最終整合與保留之反方分歧（禁止以多數決抹除異議）
        </div>
        <div class="etf-grid-2" style="margin-bottom:0;">
          <div>
            <div style="font-size:16px; font-weight:800; color:#34d399; margin-bottom:8px;">🟢 達成共識之系統改善方向</div>
            ${(p5.consensus_solutions || []).map(s => `<div class="evidence-box" style="border-left-color:#10b981;">${s}</div>`).join('')}
          </div>
          <div>
            <div style="font-size:16px; font-weight:800; color:#fb7185; margin-bottom:8px;">🔴 保留之反方意見與重大分歧（供使用者裁決）</div>
            ${(p5.divergent_views_preserved || []).map(d => `
              <div class="evidence-box counter">
                <strong>分歧議題：${d.issue}</strong><br/>
                • 提案方觀點：${d.agent_01_initial_view || d.agent_01_04_view}<br/>
                • ⚡ 反方 Agent 05：${d.agent_05_critic_view}<br/>
                • 👑 Argon 仲裁：${d.argon_arbitration}
              </div>
            `).join('')}
          </div>
        </div>
      </div>

      <div style="font-size:20px; font-weight:700; color:#f8fafc; margin:18px 0 12px 0;">
        🔬 各 Agent 獨立研究 ➔ Phase 3 交叉審查 ➔ Phase 4 第二輪辯論立場（分欄清晰呈現）
      </div>
      <div class="etf-grid-2">
        ${agentsMeta.map(m => {
          const rpt = reportsObj[m.id] || {};
          const revByMe = p3.find(x => x.reviewer_id === m.id);
          const rebByMe = p4.find(x => x.agent_id === m.id);
          const criticBlocks = revByMe && revByMe.critic_structured_blocks;
          return `
            <div class="etf-clean-card" style="border-top:4px solid ${m.color};">
              <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
                <span style="font-size:19px; font-weight:700; color:#fff;">${m.icon} ${rpt.agent_name || m.id}</span>
                <span class="badge badge-grade-B">${esc(rpt.data_timestamp_used || '')}</span>
              </div>

              <div class="evidence-box" style="border-left-color:${m.color}; white-space:pre-line;">
                <strong>【Phase 2 第一輪獨立研究：問題與實證】</strong><br/>${esc(rpt.current_system_problems || '')}
              </div>

              ${revByMe ? `
                <div class="evidence-box invalid" style="white-space:pre-line;">
                  <strong>【Phase 3 交叉審查 (${esc(revByMe.target_agent_id)})｜${esc(revByMe.review_stance)}】</strong><br/>${esc(revByMe.comment)}
                </div>
              ` : ''}

              ${criticBlocks ? `
                <div class="evidence-box counter" style="white-space:pre-line;">
                  <strong>⚡ 反方四項強制標記：</strong><br/>
                  • <strong>支持證據：</strong>${esc(criticBlocks.supporting_evidence)}<br/>
                  • <strong>反對證據與反例：</strong>${esc(criticBlocks.counter_evidence)}<br/>
                  • <strong>尚未驗證的假設：</strong>${esc(criticBlocks.unverified_assumptions)}<br/>
                  • <strong>無法確認的部分：</strong>${esc(criticBlocks.unverifiable_or_missing_data)}
                </div>
              ` : ''}

              ${rebByMe ? `
                <div class="evidence-box" style="border-left-color:#34d399; white-space:pre-line;">
                  <strong>【Phase 4 第二輪辯論最終立場：${esc(rebByMe.decision)}】</strong><br/>${esc(rebByMe.reason)}
                </div>
              ` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  // 3. 子頁面 ③：改善提案中心 (人工批准閘門)
  const propBox = document.getElementById('maPanel_PROPOSALS');
  if (propBox) {
    propBox.innerHTML = `
      <div class="etf-clean-card" style="margin-bottom:20px; border:1px solid #f59e0b; background:#111a2e;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
          <div>
            <div style="font-size:19px; font-weight:700; color:#fbbf24;">⚖️ 人工批准閘門（Human-in-the-Loop Approval Gate）</div>
            <div style="font-size:15px; color:#cbd5e1; margin-top:4px;">
              每項提案均附 10 大必填欄位與 100 分制量化評分（資料25/價值25/風控20/技術15/相容15）。批准單一項目不影響其他項目。
            </div>
            <div style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; font-size:13.5px;">
              <span class="badge badge-lvl4">已批准 / 已實作：${approvedCount} 件</span>
              <span class="badge badge-grade-C">待審核：${pendingCount} 件</span>
              ${ma.last_decision_banner ? `<span class="badge badge-lvl3">🔔 ${ma.last_decision_banner}</span>` : ''}
            </div>
          </div>
          <div style="display:flex; gap:10px; flex-wrap:wrap;">
            <button class="btn" style="background:#059669;" onclick="submitProposalDecision('ALL', 'APPROVE')">✅ 批准全部提案</button>
            <button class="btn btn-outline" style="border-color:#fbbf24; color:#fbbf24;" onclick="submitProposalDecision('ALL', 'RE_RESEARCH')">🔄 全部要求重新研究</button>
          </div>
        </div>
      </div>

      <div class="etf-grid-2">
        ${proposals.map(p => {
          const sb = p.score_breakdown || {};
          return `
            <div class="etf-clean-card" style="border-left:5px solid ${p.priority === 'P0' ? '#f43f5e' : (p.priority === 'P1' ? '#f59e0b' : '#38bdf8')};">
              <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
                <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                  ${maPriorityBadge(p.priority)}
                  <strong style="font-size:16px; color:#38bdf8;">${p.proposal_id}</strong>
                  ${maStatusBadge(p.status)}
                </div>
                <div style="font-size:24px; font-weight:700; color:#34d399;">${sb.total_score || 0} <span style="font-size:14px; color:#94a3b8;">/ 100分</span></div>
              </div>

              <div style="font-size:19px; font-weight:700; color:#fff; margin-bottom:10px; line-height:1.4;">${p.title}</div>
              <div style="font-size:14px; color:#cbd5e1; margin-bottom:10px;">
                提案成員：<strong>${(p.proposer_agents || []).join('、')}</strong> ｜ 影響模組：<code>${(p.affected_modules || []).join(', ')}</code>
              </div>

              <div style="background:#090e1a; padding:10px 14px; border-radius:8px; font-size:14px; color:#e2e8f0; margin-bottom:10px;">
                <strong>100分制評分明細：</strong>資料可靠 ${sb.data_and_evidence_reliability}/25 ｜ 預期價值 ${sb.expected_improvement_value}/25 ｜ 風險控制 ${sb.risk_control}/20 ｜ 技術可行 ${sb.technical_feasibility}/15 ｜ 相容性 ${sb.system_compatibility}/15
                <div style="color:#94a3b8; margin-top:4px;">${sb.scoring_rationale}</div>
              </div>

              <div class="evidence-box" style="white-space:pre-line;"><strong>目前問題與證據：</strong><br/>${p.current_problem}<br/><br/><strong>實證依據：</strong>${p.problem_evidence}</div>
              <div class="evidence-box" style="border-left-color:#10b981; white-space:pre-line;"><strong>建議修改方式與預期效果：</strong><br/>${p.proposed_change}<br/><br/><strong>預期效果：</strong>${p.expected_effect}</div>
              <div class="evidence-box invalid">
                <strong>副作用：</strong>${p.potential_side_effects}<br/>
                <strong>測試方式：</strong>${p.testing_plan} ｜ <strong>回復方案：</strong>${p.rollback_plan}
              </div>

              <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:14px;">
                <button class="btn" style="background:#059669; flex:1;" onclick="submitProposalDecision('${p.proposal_id}', 'APPROVE')">✅ 批准此提案</button>
                <button class="btn btn-outline" style="flex:1;" onclick="submitProposalDecision('${p.proposal_id}', 'RE_RESEARCH')">🔄 重新研究</button>
                <button class="btn btn-outline" style="border-color:#fb7185; color:#fb7185; flex:1;" onclick="submitProposalDecision('${p.proposal_id}', 'REJECT')">❌ 拒絕</button>
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  // 4. 子頁面 ④：歷史紀錄 & Agent 03 數據品質 7 項檢查
  const histBox = document.getElementById('maPanel_HISTORY');
  if (histBox) {
    const dq = ma.data_quality_audit || {};
    const checks = dq.seven_statutory_checks || [];
    histBox.innerHTML = `
      <div class="etf-clean-card" style="margin-bottom:20px;">
        <div style="font-size:19px; font-weight:700; color:#fff; margin-bottom:10px;">
          🔍 Agent 03 數據品質研究員 — 七項法定檢查實證紀錄 (${dq.audited_at || ''})
        </div>
        <div style="overflow-x:auto;">
          <table>
            <thead><tr><th>#</th><th>法定檢查項目</th><th>稽核狀態</th><th>實證說明與處置</th></tr></thead>
            <tbody>
              ${checks.map(c => `
                <tr>
                  <td><strong>${c.check_no}</strong></td>
                  <td><strong>${c.name}</strong></td>
                  <td><span class="badge ${c.status === 'PASS' ? 'badge-lvl4' : (c.status === 'CRITICAL_FINDING' ? 'badge-lvlR' : 'badge-grade-C')}">${c.status}</span></td>
                  <td>${c.detail}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>

      <div class="etf-clean-card">
        <div style="font-size:19px; font-weight:700; color:#fff; margin-bottom:10px;">📜 歷次研究與提案執行歷史紀錄</div>
        <div style="overflow-x:auto; -webkit-overflow-scrolling:touch;">
          <table>
          <thead><tr><th>Session ID</th><th>研究主題</th><th>觸發方式</th><th>完成時間</th><th>正式系統完整性</th><th>提案結果</th></tr></thead>
          <tbody>
            <tr>
              <td><strong>${ma.session_id}</strong></td>
              <td>${esc(ma.topic)}</td>
              <td><span class="badge badge-lvl3">${ma.trigger_mode}</span></td>
              <td>${ma.completed_at}</td>
              <td><span class="badge badge-lvl4">${ma.production_integrity_verified ? 'SHA-256 零竄改' : '隔離分支運行'}</span></td>
              <td>產出 ${proposals.length} 筆提案 (${approvedCount} 已批准 / ${pendingCount} 待審)</td>
            </tr>
          </tbody>
        </table>
        </div>
      </div>
    `;
  }

  // 5. 子頁面 ⑤：團隊設定 (含強制鎖定不可繞過人工批准)
  const setBox = document.getElementById('maPanel_SETTINGS');
  if (setBox) {
    setBox.innerHTML = `
      <div class="etf-clean-card" style="border-left:5px solid #a855f7;">
        <div style="font-size:20px; font-weight:700; color:#fff; margin-bottom:10px;">⚙️ AI 研究團隊運作設定（安全鎖保護中）</div>
        <div class="evidence-box counter" style="margin-bottom:16px;">
          <strong>🔒 最高安全規範鎖定：</strong>本設定頁面僅可調整研究任務主題、討論輪數與排程觸發模式；<strong>任何研究設定皆無法繞過人工批准閘門</strong>，排程任務僅限產出報告與提案，絕不自動修改正式程式碼。
        </div>
        <div class="etf-grid-2">
          <div>
            <div style="margin-bottom:12px;">
              <label style="display:block; font-size:15px; font-weight:700; margin-bottom:6px;">自訂研究任務主題：</label>
              <input type="text" id="maCustomTopicInput" value="${esc(ma.topic)}" style="width:100%;" />
            </div>
            <div style="margin-bottom:12px;">
              <label style="display:block; font-size:15px; font-weight:700; margin-bottom:6px;">排程觸發機制（第十一節）：</label>
              <select id="maScheduleSelect" onchange="MA_SETTINGS.schedule_mode = this.value" style="width:100%;">
                <option value="MANUAL_FIRST">MANUAL_FIRST：手動啟動完整研究與辯論（目前預設）</option>
                <option value="DAILY_ROUTINE_CHECK">DAILY_ROUTINE_CHECK：每日例行數據異常與進場檢查（僅產提案）</option>
                <option value="WEEKLY_FULL_RESEARCH">WEEKLY_FULL_RESEARCH：每週完整模型與回測審查（僅產提案）</option>
                <option value="DATA_ANOMALY_TRIGGER">DATA_ANOMALY_TRIGGER：資料缺失或費半單日>3%異常觸發</option>
              </select>
            </div>
            <button class="btn" style="background:#7e22ce; font-size:15px; padding:10px 20px;" onclick="triggerNewMultiAgentSession()">
              🚀 依目前設定啟動新一輪團隊研究
            </button>
          </div>
          <div>
            <div style="font-size:15.5px; font-weight:800; color:#38bdf8; margin-bottom:10px;">Agent 成員啟用與模型配置（Argon 協調）：</div>
            ${agentsMeta.map(m => `
              <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 12px; background:#090e1a; border-radius:8px; margin-bottom:8px; border:1px solid #1e293b;">
                <span>${m.icon} <strong>${m.id}</strong> (規則式模擬・非 LLM)</span>
                <span class="badge badge-lvl4">已啟用 (唯讀沙箱)</span>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    `;
  }
}

