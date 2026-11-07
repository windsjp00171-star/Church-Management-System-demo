/* 開啟手機通知（Web Push）
 *
 * ★★ 這一段的天花板不是程式，是**兩道門檻**：
 *   ① iOS 只有**加到主畫面的 PWA** 收得到推播（Safari 分頁收不到）
 *   ② 使用者要親手按「允許」
 *
 *   所以這支 JS 最重要的工作不是「訂閱」，是**在按不下去的時候
 *   把原因講清楚** —— 一顆按了沒反應的按鈕會讓人以為系統壞了，
 *   而實際上是他還沒把網站加到主畫面。
 *
 * ★ 權限對話框**一定要由使用者的手勢觸發**。一進站就問的話：
 *   多數人直覺按「不允許」，而**瀏覽器會記住那個拒絕** ——
 *   之後我們再也問不到他，要他自己去設定裡改回來。
 *   （這跟「加到主畫面」那條同一個道理：在他剛完成一件事之後才邀請。）
 */
(function () {
    'use strict';

    var PUBLIC_KEY = null;

    /* ★★ 每一個 await 都要有期限。
     *
     *   這一段踩過一次，而且症狀是最難查的那種：service worker 的 scope
     *   當時是 `/static/`，所以 `navigator.serviceWorker.ready` 在
     *   `/profile` 上**永遠不會 resolve，也永遠不會 reject** ——
     *   不是失敗，是**永遠停住**。使用者看到「處理中…」卡在那裡，
     *   console 一行錯誤都沒有，而伺服器那邊一筆訂閱都沒進來。
     *
     *   scope 已經修好了（改註冊 `/sw.js`），但「不會回來的 promise」
     *   這件事本身還會從別的地方冒出來：全新的裝置上 service worker
     *   還沒 activate、權限對話框被滑掉沒回答……
     *
     *   所以規則是：**使用者在等的每一步都要有期限**，
     *   到了就講一句他做得到的話，而不是無限期沉默。
     */
    function withDeadline(promise, ms, what) {
        var timer;
        /*  ★ 贏的那一邊出來之後**一定要把計時器清掉**。
               `Promise.race` 不會取消輸的那一邊 —— 不清的話每按一次
               就留一個最長 60 秒的計時器（連同它抓著的 closure）。
               ★ 這是測試抓到的：在 node 裡那個計時器會**把整個行程
                 留住**，一支跑 0.3 秒的測試變成等滿 60 秒。 */
        return Promise.race([
            promise,
            new Promise(function (_, reject) {
                timer = setTimeout(function () {
                    reject(new Error('TIMEOUT:' + what));
                }, ms);
            }),
        ]).finally(function () { clearTimeout(timer); });
    }

    /*  ★ 測試要跑得完，所以留一個覆寫的口。正式站不會設這個變數，
           所以線上跑的永遠是下面那組真的值。 */
    var OVERRIDE = (typeof window !== 'undefined' && window.__PUSH_TIMEOUTS__) || null;

    var TIMEOUTS = OVERRIDE || {
        key: 15000,        // 拿公鑰（Render 免費方案冷啟動會慢）
        permission: 60000, // 等他按「允許」—— 給長一點，人會猶豫
        sw: 10000,         // 等 service worker 就緒
        subscribe: 20000,  // 跟推播服務要一個 endpoint
    };

    function isStandalone() {
        return window.matchMedia('(display-mode: standalone)').matches
            || window.navigator.standalone === true;
    }

    function isIOS() {
        return /iPad|iPhone|iPod/.test(navigator.userAgent)
            || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    }

    /* base64url 字串 → Uint8Array（applicationServerKey 只收這個）*/
    function urlB64ToUint8Array(b64) {
        var padding = '='.repeat((4 - b64.length % 4) % 4);
        var raw = atob((b64 + padding).replace(/-/g, '+').replace(/_/g, '/'));
        var out = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
        return out;
    }

    /* 這台裝置現在是什麼狀態。**每一種都要能講出一句人話**。 */
    function state() {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
            //  ★ iOS 的 Safari 分頁就是走到這裡 —— 而那不是「不支援」，
            //    是「還沒加到主畫面」。兩句話要分開，不然他會放棄。
            if (isIOS() && !isStandalone()) return 'ios-needs-install';
            return 'unsupported';
        }
        if (Notification.permission === 'denied') return 'denied';
        if (Notification.permission === 'granted') return 'granted';
        return 'askable';
    }

    var MESSAGES = {
        'ios-needs-install':
            'iPhone 要先把這個網站「加到主畫面」，從桌面圖示打開才收得到通知'
            + '（這是 Apple 的限制，不是設定問題）。',
        'unsupported': '這個瀏覽器不支援推播通知。',
        'denied': '這台裝置之前選了「不允許通知」。要開啟的話，'
            + '請到瀏覽器的網站設定裡把通知改成允許 —— 我們沒辦法再問你一次。',
    };

    /*  這台已經開好了 → 把外面那一塊收成安靜的樣子。
     *  ★ 已經做完的事還在頁首大聲喊的話，下次他就不會再相信頁首那一塊了 ——
     *    而那正是我們最需要他看一眼的位置。 */
    /*  ★ 「傳一則測試通知」只在已經開啟的那台出現 —— 沒開啟就按的話
           一定失敗，而「按了說沒有裝置」看起來像功能壞了。 */
    function showTestBtn(on) {
        var t = document.getElementById('push-test');
        if (t) t.style.display = on ? '' : 'none';
    }

    async function sendTest(btn, msgEl) {
        btn.disabled = true;
        show(msgEl, '送出中…');
        try {
            var r = await withDeadline(fetch('/api/push/test', { method: 'POST' }),
                                       TIMEOUTS.key, 'test');
            var d = await r.json();
            if (d.success) {
                /*  ★ 講出**幾台**：他可能在電腦上按，而響的是手機。
                       只說「送出了」的話他會盯著眼前這台等。 */
                show(msgEl, '已經送出去了（' + (d.sent || 0) + ' 台裝置）。'
                          + '沒跳出來的話，多半是系統設定裡把這個網站的'
                          + '通知關掉了。', true);
            } else {
                /*  ★ 失敗要講原因（狀態碼），不是「傳送失敗」——
                       403 幾乎一定是金鑰對不起來，而那查得出來。 */
                show(msgEl, '送不出去：'
                          + (d.error || (d.problems || []).join('、')
                             || '不知道為什麼'));
            }
        } catch (e) {
            show(msgEl, '送不出去，請重新整理再試一次。');
        }
        btn.disabled = false;
    }

    function markOn(on) {
        showTestBtn(on);
        var block = document.getElementById('push-block');
        if (block) block.dataset.on = on ? '1' : '';
    }

    function show(el, text, ok) {
        if (!el) return;
        el.textContent = text || '';
        el.style.color = ok ? 'var(--green-ink, var(--green-ink, #1a5e3e))' : 'var(--text-3, #545a55)';
    }

    async function enable(btn, msgEl) {
        var st = state();
        if (st !== 'askable' && st !== 'granted') {
            show(msgEl, MESSAGES[st] || '這台裝置沒辦法開啟通知。');
            return;
        }
        btn.disabled = true;
        show(msgEl, '處理中…');
        try {
            if (!PUBLIC_KEY) {
                var r = await withDeadline(fetch('/api/push/key'), TIMEOUTS.key, 'key');
                var d = await r.json();
                if (!d.enabled || !d.key) {
                    show(msgEl, '系統還沒設定推播金鑰，請聯絡管理員。');
                    btn.disabled = false;
                    return;
                }
                PUBLIC_KEY = d.key;
            }
            /* ★ 這一行必須在使用者手勢的呼叫堆疊裡 —— 包進 setTimeout
                 的話 Safari 會直接忽略那個請求，而且不報錯。 */
            var perm = await withDeadline(Notification.requestPermission(),
                                          TIMEOUTS.permission, 'permission');
            if (perm !== 'granted') {
                show(msgEl, '你選了不允許。之後想開啟的話，'
                          + '要到瀏覽器的網站設定裡改（我們問不了第二次）。');
                btn.disabled = false;
                return;
            }
            var reg = await withDeadline(navigator.serviceWorker.ready,
                                         TIMEOUTS.sw, 'sw');
            var sub = await withDeadline(reg.pushManager.subscribe({
                userVisibleOnly: true,      // ★ 規定：收到推播一定要顯示通知
                applicationServerKey: urlB64ToUint8Array(PUBLIC_KEY),
            }), TIMEOUTS.subscribe, 'subscribe');
            var res = await withDeadline(fetch('/api/push/subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(sub.toJSON()),
            }), TIMEOUTS.key, 'save');
            if (!res.ok) throw new Error('save failed');
            /* ★★ 伺服器存好之後會**立刻推一則**，並且照實回報送不送得出去。
             *   這一則是他唯一能確認「真的收得到」的機會 —— 按完之後
             *   可能好幾天都沒有任何通知（那幾天本來就沒事），
             *   而「設定成功但今天沒事」和「每一則都 403」
             *   在畫面上長得一模一樣。
             * ★ 所以送不出去的時候**不可以說開好了**。 */
            var saved = {};
            try { saved = await res.json(); } catch (e) { saved = {}; }
            if (saved.test_sent) {
                show(msgEl, '✅ 開好了 —— 剛剛送了一則測試通知到這台裝置，'
                          + '看一下通知列。', true);
            } else if (saved.test_error) {
                show(msgEl, '⚠️ 訂閱存好了，但測試通知送不出去：'
                          + saved.test_error);
            } else {
                show(msgEl, '✅ 這台裝置已經開啟通知了', true);
            }
            btn.textContent = '已開啟';
            markOn(true);
        } catch (e) {
            /* ★ 失敗要講「可以做什麼」，不是「發生錯誤」。
             * ★ 而且逾時要講**卡在哪一步** —— 「開啟失敗」對想查的人
             *   等於沒講，而這一塊的問題多半只有一個人重現得出來。 */
            show(msgEl, TIMEOUT_HELP[stepOf(e)]
                     || '開啟失敗。如果是 iPhone，請確認是從桌面圖示打開的；'
                      + '其他情況請重新整理再試一次。');
            btn.disabled = false;
        }
    }

    /*  ★★ 對外曝一支，給「剛完成一件事」那幾個時刻用
           （`a2hs.js` 的 `markNextStepMoment`）。

        ★ 開啟的流程**只准有一份** —— 那一段裡有五個會靜默失敗
          的地方（沒金鑰、拒絕、SW 永遠不回來、訂閱失敗、存不進去），
          每一個都要講出他做得到的下一步。再寫一份简略版的話，
          那五種失敗在那五個時刻會變成「按了沒反應」。

        ★ 權限對話框一定要在**使用者點擊的同一個呼叫堆疊裡** ——
          呼叫端要在 click handler 裡直接呼叫這一支，不可以包進 setTimeout。 */
    window.enablePush = function (btn, msgEl) {
        return enable(btn, msgEl);
    };

    function stepOf(e) {
        var m = /^TIMEOUT:(\w+)$/.exec((e && e.message) || '');
        return m && m[1];
    }

    var TIMEOUT_HELP = {
        key: '連不上伺服器（等太久）。網路不穩或系統剛睡醒，'
           + '請過一下再按一次。',
        permission: '等不到你的回答。瀏覽器會跳一個「是否允許通知」的'
           + '詢問，按「允許」就好；沒看到的話請重新整理再按一次。',
        sw: '這個瀏覽器還沒準備好（等太久）。請**重新整理一次**再按 ——'
           + '第一次打開網站時偶爾會這樣。',
        subscribe: '跟通知服務連線逾時。請確認網路，然後再按一次。',
        save: '設定好了但**存不回伺服器**。請再按一次 ——'
           + '不然這台裝置收不到通知。',
    };

    async function disable(btn, msgEl) {
        try {
            var reg = await withDeadline(navigator.serviceWorker.ready,
                                         TIMEOUTS.sw, 'sw');
            var sub = await reg.pushManager.getSubscription();
            if (sub) {
                await fetch('/api/push/unsubscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint: sub.endpoint }),
                });
                await sub.unsubscribe();
            }
            show(msgEl, '這台裝置已關閉通知。');
            btn.textContent = '開啟手機通知';
            markOn(false);
            btn.disabled = false;
        } catch (e) {
            show(msgEl, '關不掉的話，請到瀏覽器的網站設定裡關閉通知。');
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var btn = document.getElementById('push-optin');
        var msgEl = document.getElementById('push-msg');
        //  ★ 這份現在全站都載（`window.enablePush` 要到處都叫得到），
        //    所以沒有那顆鈕的頁面只是不接線，不是錯誤。
        if (!btn) return;

        var st = state();
        /* ★ 已經訂閱的那台要**顯示成已開啟** —— 不然他每次來都看到
             「開啟通知」，會以為沒設定成功而一直按。 */
        if (st === 'granted' && navigator.serviceWorker) {
            navigator.serviceWorker.ready.then(function (reg) {
                return reg.pushManager.getSubscription();
            }).then(function (sub) {
                if (sub) {
                    btn.textContent = '關閉這台的通知';
                    btn.dataset.on = '1';
                    show(msgEl, '這台裝置已經開啟通知了', true);
                    markOn(true);
                }
            }).catch(function () {});
        } else if (MESSAGES[st]) {
            show(msgEl, MESSAGES[st]);
        }

        var testBtn = document.getElementById('push-test');
        if (testBtn) {
            testBtn.addEventListener('click', function () {
                sendTest(testBtn, msgEl);
            });
        }

        btn.addEventListener('click', function () {
            if (btn.dataset.on === '1') {
                btn.dataset.on = '';
                disable(btn, msgEl);
            } else {
                enable(btn, msgEl);
            }
        });
    });
})();
