// 以假的 fetch / DOM 在 Node 內執行 frontend/assets/js/03-navigation.js 的資料載入流程，輸出各情境結果 (JSON)。
// 由 tests/test_frontend_js.py 呼叫；不需要瀏覽器。
const fs = require('fs');
const vm = require('vm');
const root = process.argv[2];
const src = ['01-core.js', '03-navigation.js']
  .map(f => fs.readFileSync(root + '/frontend/assets/js/' + f, 'utf8')).join('\n');

const SNAP = { generated_at: 'SNAPSHOT', active_model: { version_id: 'v1', weights: {}, thresholds: {} },
  data_provenance: { last_live_ingestion: 't1' }, warnings: [], industries: [{ total_weighted_score: 80 }] };
const SAME = { ...SNAP, generated_at: 'API-SAME' };
const CHANGED = { ...SNAP, generated_at: 'API-CHANGED', active_model: { version_id: 'v2', weights: {}, thresholds: {} } };

const ok = (data) => ({ status: 200, ct: 'application/json', json: data });
const rejectNet = { reject: true };

async function scenario(o) {
  let created = null, calls = 0, dataCalls = 0;
  const header = { parentNode: { insertBefore(el) { created = el; } } };
  const doc = {
    getElementById(id) {
      if (id === 'twfin-snapshot') return o.embedded ? { textContent: JSON.stringify(o.embedded) } : null;
      if (id === 'apiStatusBanner') return created;
      return null;
    },
    createElement() { return { style: {}, innerHTML: '', setAttribute() {}, id: '' }; },
    querySelector(sel) { return sel === 'header' ? header : null; },
  };
  const store = o.dismissed ? { twfin_api_banner_dismissed: '1' } : {};
  const ctx = {
    document: doc, console, AbortController, setTimeout, clearTimeout,
    location: { protocol: o.protocol || 'https:' },
    sessionStorage: { getItem: k => store[k] || null, setItem: (k, v) => { store[k] = v; } },
    fetch: async (url) => {
      if (String(url).includes('data.json')) {     // 拆分部署的資料檔 (預設不存在 = 404)
        dataCalls++;
        const d = o.dataFile || { status: 404, ct: 'text/html' };
        if (d.reject) throw new Error('network');
        return { ok: d.status >= 200 && d.status < 300, status: d.status,
          headers: { get: () => d.ct || '' }, json: async () => d.json };
      }
      const b = o.responses[Math.min(calls, o.responses.length - 1)];
      calls++;
      if (b.reject) throw new Error('network');
      return { ok: b.status >= 200 && b.status < 300, status: b.status,
        headers: { get: () => b.ct || '' }, json: async () => b.json };
    },
    __renders: 0,
  };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  vm.runInContext('renderAll = function () { __renders++; }', ctx);
  await ctx.loadDashboard();
  for (let i = 0; i < 40 && vm.runInContext('API_MODE', ctx) === 'waking'; i++) await new Promise(r => setTimeout(r, 25));
  return {
    renders: ctx.__renders, calls, dataCalls,
    mode: vm.runInContext('API_MODE', ctx), reason: vm.runInContext('API_REASON', ctx),
    stateGen: vm.runInContext('STATE && STATE.generated_at', ctx),
    bannerShown: !!(created && created.style.display !== 'none' && created.innerHTML),
    banner: created ? created.innerHTML : '',
  };
}

(async () => {
  const out = {};
  out.file = await scenario({ embedded: SNAP, protocol: 'file:', responses: [ok(SAME)] });
  out.sameData = await scenario({ embedded: SNAP, responses: [ok(SAME)] });
  out.changedData = await scenario({ embedded: SNAP, responses: [ok(CHANGED)] });
  out.static404 = await scenario({ embedded: SNAP, responses: [{ status: 404, ct: 'text/html' }] });
  out.staticHtml200 = await scenario({ embedded: SNAP, responses: [{ status: 200, ct: 'text/html; charset=utf-8', json: null }] });
  out.staticDismissed = await scenario({ embedded: SNAP, dismissed: true, responses: [{ status: 404, ct: 'text/html' }] });
  out.unreachable = await scenario({ embedded: SNAP, responses: [rejectNet] });
  out.wakesOnThird = await scenario({ embedded: SNAP, responses: [rejectNet, { status: 503, ct: '' }, ok(CHANGED)] });
  out.noSnapshotOk = await scenario({ embedded: null, responses: [ok(CHANGED)] });
  out.noSnapshotDown = await scenario({ embedded: null, responses: [rejectNet] });
  // 拆分部署：index.html 只有程式，資料在 data.json
  out.splitStatic = await scenario({ embedded: null, dataFile: ok(SNAP), responses: [{ status: 404, ct: 'text/html' }] });
  out.splitThenApi = await scenario({ embedded: null, dataFile: ok(SNAP), responses: [ok(CHANGED)] });
  out.splitDataHtml200 = await scenario({ embedded: null, dataFile: { status: 200, ct: 'text/html; charset=utf-8' }, responses: [ok(CHANGED)] });
  out.splitFileProtocol = await scenario({ embedded: null, protocol: 'file:', responses: [ok(CHANGED)] });
  out.embeddedSkipsDataFile = await scenario({ embedded: SNAP, dataFile: ok(CHANGED), responses: [{ status: 404, ct: 'text/html' }] });
  console.log(JSON.stringify(out));
})();
