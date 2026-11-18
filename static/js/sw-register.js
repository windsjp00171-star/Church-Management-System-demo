/* ══════════════════════════════════════════════════════════
   Service Worker 註冊

   ★★ 註冊的是 `/sw.js`（根目錄），**不是 `/static/sw.js`**。

   Service Worker 的 scope 預設是「那支檔案所在的目錄」。掛在
   `/static/sw.js` 的話 scope 就是 `/static/` —— 它**不控制任何一頁
   真正的頁面**，於是：

     - `navigator.serviceWorker.ready` 在 `/profile` 這種頁面上
       **永遠不會 resolve**（它等的是「控制這一頁的 SW」）
     - 而那不是失敗，是**永遠停住**：沒有錯誤、沒有逾時。
       使用者看到的是「處理中…」卡在那裡

   實際踩過：推播上線之後一筆訂閱都沒有，而使用者按了按鈕、
   畫面停在「處理中…」。
   ══════════════════════════════════════════════════════════ */

if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then(cleanUpOldScopes)
      .catch(function () { /* 註冊失敗不要把頁面帶走 */ });
  });
}

/* ★ 把舊的 `/static/` scope 註冊清掉。
     它不控制任何頁面，所以留著不會壞事 —— 但下一個人用開發者工具
     看到「有兩個 service worker」時，會完全查不出哪一個才算數。 */
function cleanUpOldScopes() {
  if (!navigator.serviceWorker.getRegistrations) return;
  navigator.serviceWorker.getRegistrations().then(function (regs) {
    regs.forEach(function (r) {
      try {
        if (new URL(r.scope).pathname !== '/') r.unregister();
      } catch (e) { /* scope 解析不了就別碰它 */ }
    });
  }).catch(function () {});
}
