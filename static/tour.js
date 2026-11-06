/* 聚焦式教學（全域共用）。步驟以 data-tour 屬性綁定，不用 id / class。
   用法：RollTour.start([{ target: 'xxx', text: '說明' }, ...])
   無障礙：尊重 prefers-reduced-motion；不遮擋操作（高亮只用外框，不攔截點擊）。 */
(function () {
  var idx = 0, steps = [], box = null;
  function el(t) { return document.querySelector('[data-tour="' + t + '"]'); }
  function clear() {
    var old = document.querySelector('[data-tour-active]');
    if (old) { old.removeAttribute('data-tour-active'); old.style.outline = ''; old.style.outlineOffset = ''; }
  }
  function show() {
    clear();
    var s = steps[idx], t = el(s.target);
    if (t) {
      t.setAttribute('data-tour-active', '1');
      t.style.outline = '3px solid #4F46E5'; t.style.outlineOffset = '3px';
      var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
      t.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
    }
    box.querySelector('[data-tour-text]').textContent = s.text;
    box.querySelector('[data-tour-count]').textContent = (idx + 1) + ' / ' + steps.length;
    box.querySelector('[data-tour-prev]').disabled = idx === 0;
    box.querySelector('[data-tour-next]').textContent = idx === steps.length - 1 ? '完成' : '下一步';
  }
  function end() { clear(); if (box) { box.remove(); box = null; } }
  window.RollTour = {
    start: function (list) {
      end(); steps = list.filter(function (s) { return el(s.target); }); idx = 0;
      if (!steps.length) return;
      box = document.createElement('div');
      box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', '操作教學');
      box.style.cssText = 'position:fixed;left:12px;right:12px;bottom:12px;z-index:9999;background:#fff;' +
        'border:1px solid #c7d2fe;border-radius:12px;padding:14px 16px;box-shadow:0 4px 16px rgba(0,0,0,.18);' +
        'max-width:520px;margin:0 auto;font-size:1rem;line-height:1.6;';
      box.innerHTML = '<div data-tour-text style="margin-bottom:10px;"></div>' +
        '<div style="display:flex;gap:8px;align-items:center;">' +
        '<span data-tour-count style="color:#666;font-size:.85rem;flex:1;"></span>' +
        '<button type="button" data-tour-close style="padding:10px 14px;border:1px solid #ccc;background:#fff;border-radius:8px;">跳過</button>' +
        '<button type="button" data-tour-prev style="padding:10px 14px;border:1px solid #ccc;background:#fff;border-radius:8px;">上一步</button>' +
        '<button type="button" data-tour-next style="padding:10px 16px;border:0;background:#4F46E5;color:#fff;border-radius:8px;font-weight:bold;"></button></div>';
      document.body.appendChild(box);
      box.querySelector('[data-tour-close]').onclick = end;
      box.querySelector('[data-tour-prev]').onclick = function () { if (idx > 0) { idx--; show(); } };
      box.querySelector('[data-tour-next]').onclick = function () { if (idx < steps.length - 1) { idx++; show(); } else end(); };
      show();
    }
  };
})();
