/* =========================================================================
   無障礙增強層 (不改動既有渲染邏輯，以事件委派與 MutationObserver 補強)
   1. 以 onclick 當按鈕的 div/span/g 等元素：補上 role="button"、tabindex，Enter / 空白鍵可觸發
   2. 圖表 SVG：補上 role="img" 與說明文字 (裝飾性小圖示則隱藏)
   3. 分頁導覽 aria-selected / aria-current 與目前狀態同步
   4. 抽屜 (dialog)：開啟時移動焦點、Esc 關閉、關閉後焦點還原
   5. 尊重系統「減少動態效果」設定
   ========================================================================= */
(function () {
  'use strict';

  var NATIVE_INTERACTIVE = { A: 1, BUTTON: 1, INPUT: 1, SELECT: 1, TEXTAREA: 1, SUMMARY: 1 };

  function cleanText(el, max) {
    return (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, max || 80);
  }

  /* ---- 1. 可聚焦、可用鍵盤觸發 ---- */
  function enhanceClickables(root) {
    var nodes = root.querySelectorAll('[onclick]:not([data-a11y])');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      el.setAttribute('data-a11y', '1');
      if (NATIVE_INTERACTIVE[el.tagName]) continue;
      var tag = el.tagName.toLowerCase();
      // 桑基圖色帶 (path) 是滑鼠專用的裝飾性連線，同一資訊可由節點 (g) 取得；不加入 Tab 順序以免產生數十個停靠點
      if (tag === 'path' || tag === 'rect' && !cleanText(el)) continue;
      if (!el.hasAttribute('role')) el.setAttribute('role', 'button');
      if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
      if (tag === 'g' && !el.hasAttribute('aria-label')) {
        var t = cleanText(el, 100);
        if (t) el.setAttribute('aria-label', t);
      }
    }
  }

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
    var el = e.target;
    if (!el || el.nodeType !== 1 || NATIVE_INTERACTIVE[el.tagName]) return;
    if (el.getAttribute('role') !== 'button') return;
    e.preventDefault();   // 空白鍵不要捲動頁面
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
  });

  /* ---- 2. SVG 圖表說明 ---- */
  function describeNearest(svg) {
    for (var n = svg.parentElement; n && n !== document.body; n = n.parentElement) {
      var t = n.querySelector('.card-title, .etf-card-title, h2, h3, h4');
      if (t && !svg.contains(t)) return cleanText(t, 90);
    }
    return '';
  }
  function enhanceSvgs(root) {
    var svgs = root.querySelectorAll('svg:not([data-a11y])');
    for (var i = 0; i < svgs.length; i++) {
      var svg = svgs[i];
      svg.setAttribute('data-a11y', '1');
      if (svg.hasAttribute('aria-label') || svg.hasAttribute('aria-hidden') || svg.hasAttribute('role')) continue;
      var r = svg.getBoundingClientRect();
      if (r.width && r.width < 40 && r.height < 40) { svg.setAttribute('aria-hidden', 'true'); continue; }   // 小圖示：裝飾
      var title = svg.querySelector('title');
      var label = (title && cleanText(title)) || describeNearest(svg) || '資料圖表';
      svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', label + '（圖表；詳細數值請見下方表格或點選項目查看）');
    }
  }

  /* ---- 3. 導覽狀態同步 ---- */
  function syncNavState() {
    var modeBtns = document.querySelectorAll('.mode-btn');
    for (var i = 0; i < modeBtns.length; i++) {
      var b = modeBtns[i];
      b.setAttribute('role', 'tab');
      var on = /(^|\s)active-/.test(b.className);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.setAttribute('tabindex', on ? '0' : '-1');
    }
    var mob = document.querySelectorAll('.mob-nav-btn');
    for (var j = 0; j < mob.length; j++) {
      if (/(^|\s)active-/.test(mob[j].className)) mob[j].setAttribute('aria-current', 'page');
      else mob[j].removeAttribute('aria-current');
    }
    var tabs = document.querySelectorAll('.pro-tab');
    for (var k = 0; k < tabs.length; k++) {
      if (tabs[k].classList.contains('active')) tabs[k].setAttribute('aria-current', 'page');
      else tabs[k].removeAttribute('aria-current');
    }
  }
  // 方向鍵在 tablist 內切換 (WAI-ARIA tabs 慣例)
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    var cur = e.target;
    if (!cur || !cur.classList || !cur.classList.contains('mode-btn')) return;
    var all = Array.prototype.slice.call(document.querySelectorAll('.mode-btn'));
    var next = all[(all.indexOf(cur) + (e.key === 'ArrowRight' ? 1 : all.length - 1)) % all.length];
    if (next) { e.preventDefault(); next.focus(); next.click(); }
  });

  /* ---- 4. 抽屜焦點管理 ---- */
  var lastFocus = null;
  function wrapDrawer() {
    if (typeof openDrawer === 'function' && !openDrawer.__a11y) {
      var origOpen = openDrawer;
      openDrawer = function () {
        lastFocus = document.activeElement;
        var r = origOpen.apply(this, arguments);
        var panel = document.getElementById('drawerPanel');
        if (panel) setTimeout(function () { panel.focus({ preventScroll: true }); }, 0);
        return r;
      };
      openDrawer.__a11y = true;
    }
    if (typeof closeDrawer === 'function' && !closeDrawer.__a11y) {
      var origClose = closeDrawer;
      closeDrawer = function () {
        var r = origClose.apply(this, arguments);
        if (lastFocus && document.body.contains(lastFocus) && lastFocus.focus) lastFocus.focus({ preventScroll: true });
        lastFocus = null;
        return r;
      };
      closeDrawer.__a11y = true;
    }
  }
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var panel = document.getElementById('drawerPanel');
    if (panel && panel.classList.contains('open') && typeof closeDrawer === 'function') closeDrawer();
  });

  /* ---- 5. 系統「減少動態效果」→ 預設關閉桑基圖動畫 ---- */
  function applySystemMotionPreference() {
    try {
      if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches &&
          typeof REDUCED_MOTION !== 'undefined' && !REDUCED_MOTION && typeof toggleReducedMotion === 'function') {
        toggleReducedMotion();
      }
    } catch (e) { /* 舊瀏覽器不支援時忽略 */ }
  }

  /* ---- 啟動與動態內容 ---- */
  function enhanceAll() {
    enhanceClickables(document);
    enhanceSvgs(document);
    syncNavState();
  }

  var scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    // 不用 requestAnimationFrame：背景分頁會暫停它，導致 aria 狀態更新延遲
    setTimeout(function () { scheduled = false; enhanceAll(); }, 30);
  }

  function start() {
    wrapDrawer();
    enhanceAll();
    applySystemMotionPreference();
    // 內容由 innerHTML 重新渲染、分頁切換 (class 變動) 時重新補強
    new MutationObserver(schedule).observe(document.body, {
      childList: true, subtree: true, attributes: true, attributeFilter: ['class']
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
