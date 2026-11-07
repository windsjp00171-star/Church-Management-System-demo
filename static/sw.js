// Service Worker：目前只做「推播」，不攔截任何請求（不快取、不離線頁），所以不會改變既有頁面的載入行為。
//
// ★★ `push` 事件一定要顯示一則通知：收到推播卻不顯示（silent push），累犯會被瀏覽器
//    取消這個網站的推播權限，之後每一則都送不到，而且沒有任何錯誤。
// ★ 解析失敗也要顯示：payload 壞掉時退回一句通用的字。
self.addEventListener('install', () => { self.skipWaiting(); });
self.addEventListener('activate', event => { event.waitUntil(self.clients.claim()); });

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  event.waitUntil(
    self.registration.showNotification(data.title || '教會通知', {
      body: data.body || '',
      icon: '/static/icons/icon.svg',
      // ★ 同一則不要重複跳：同樣 tag 的通知會蓋掉前一則（排程重試時才不會看到兩三則一模一樣的）
      tag: data.url || 'church',
      data: { url: data.url || '/' },
    })
  );
});

// 點通知：優先跳到「已經開著的那個分頁」，每次都 openWindow 的話點五則就開五個分頁。
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if ('focus' in c && 'navigate' in c) {
          return c.focus().then(cc => cc.navigate(url)).catch(() => c.focus());
        }
      }
      return clients.openWindow ? clients.openWindow(url) : null;
    })
  );
});
