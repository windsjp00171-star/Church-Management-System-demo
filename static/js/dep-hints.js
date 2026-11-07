/* 設定之間的依賴：即時提示（活動表單和課程表單共用這一份）
 *
 * ## 規則不在這裡
 *
 * 規則在 `routes/setting_deps.py`。這一支只做三件事：
 * 收草稿 → 送去問 → 把回來的字放到對的位置。
 *
 * ★ 為什麼不在前端判就好（快、不用連線）：那會變成第二份實作。
 *   改了規則畫面上不會跟，而**兩邊都看起來正常** ——
 *   這個專案整章在講的那個形狀。所以寧可多一趟。
 *
 * ## 位置的對照表在 HTML 裡
 *
 * `<div class="dep-hint" data-dep="<key>"></div>`。註冊表加一條，
 * 就在模板上開一格，這支 JS 一個字都不用動。
 *
 * ★ 「講在他改的那一格旁邊」是重點，不是排版偏好。存好了才 alert 的話，
 *   那一刻他的注意力已經在別的事情上，而且要再進來改一次。
 *
 * ## 為什麼抽出來
 *
 * 第二個表單（門訓課程）要用同一套。抽出來的時機是**第二個用的人出現時**
 * —— 只有一個實例時抽出來的抽象幾乎一定是錯的。
 *
 * 用法：
 *
 *     initDepHints({
 *       endpoint: '/admin/courses/check-deps',
 *       collect: () => ({ ...表單現在的值 }),
 *       action: (key) => '<button>…</button>',   // 選填
 *     });
 */

(function () {
  'use strict';

  var timer = null;
  var seq = 0;
  var busy = false;          // 收值的當下不要再排一次（見下面）
  var cfg = null;

  /** 排一次檢查。連打不會打爆伺服器（打字時每個字都會叫到）。 */
  function schedule() {
    // ★ 收值的過程本身可能觸發 input/change（例如活動表單的
    //   `syncOptionRows()` 會改隱藏欄位）。不擋的話就是**無窮迴圈**：
    //   每 400 毫秒自動送一次，永遠停不下來 —— 而畫面上完全正常，
    //   要打開 Network 面板才看得到。
    if (busy || !cfg) return;
    clearTimeout(timer);
    timer = setTimeout(run, 400);
  }

  function collect() {
    busy = true;
    try {
      return cfg.collect();
    } finally {
      busy = false;
    }
  }

  function run() {
    var mine = ++seq;
    var draft;
    try {
      draft = collect();
    } catch (e) {
      return;                // 收值壞掉只該少一段提示，不該弄壞表單
    }
    fetch(cfg.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(draft),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        // ★ 慢的那一份後到就丟掉 —— 不然畫面會倒退回幾個字之前的狀態，
        //   而使用者看到的是「我改好了它還在唸」。
        if (mine !== seq) return;
        render(data.deps || []);
      })
      .catch(function () {
        // ★ 連不上就**保留現況**，不要把已經顯示的提示清掉。
        //   清掉的話網路抖一下＝問題看起來被解決了。
      });
  }

  function render(deps) {
    var byKey = {};
    deps.forEach(function (d) { byKey[d.key] = d; });
    document.querySelectorAll('.dep-hint').forEach(function (box) {
      var d = byKey[box.dataset.dep];
      if (!d) { box.innerHTML = ''; box.classList.remove('blocks'); return; }
      box.classList.toggle('blocks', !!d.blocks);
      box.innerHTML = html(d.text) + (cfg.action ? cfg.action(d.key) : '');
    });
  }

  /** 伺服器回來的是純文字 —— **先跳脫再加粗**，順序不能反。
   *
   * ★ 註冊表的 `effect` 用 `**這樣**` 標重點（那份檔案本身是給人讀的
   *   Markdown 風格）。直接 innerHTML 的話畫面上會是兩顆星星；
   *   而先轉粗體再跳脫的話，`<strong>` 自己會被跳脫掉，一樣沒有作用。
   */
  function html(text) {
    var d = document.createElement('div');
    d.textContent = String(text == null ? '' : text);
    return d.innerHTML.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  }

  window.initDepHints = function (options) {
    cfg = options;
    window.syncDepHints = schedule;

    // ★ 編輯既有的東西時也要判一次 —— 只在「改動的當下」提示的話，
    //   已經設錯的那幾筆打開來完全沒有聲音，而那正是最需要被提醒的。
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', schedule);
    } else {
      schedule();
    }

    // ★ 全表單監聽，不是逐個欄位掛 onchange。
    //
    //   逐個掛的話**新加的東西一定會漏**（活動表單的自訂欄位是動態長出來
    //   的）。漏掉的症狀是那條提示對某些操作不出現 ——
    //   而畫面上完全看不出少了什麼。
    ['input', 'change'].forEach(function (evt) {
      document.addEventListener(evt, function (e) {
        if (e.target && e.target.closest && e.target.closest('.dep-hint')) return;
        schedule();
      }, true);
    });
  };
})();
