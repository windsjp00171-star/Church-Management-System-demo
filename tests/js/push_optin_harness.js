/* 在 node 裡用假的瀏覽器真的跑一次 push-optin.js
 *
 * ★★ 為什麼不掃原始碼：
 *   掃原始碼看得到「有沒有寫這一行」，看不到「這一行會不會被走到」。
 *   把 `if (st === 'granted' …)` 改成 `if (false)` —— 整段還在檔案裡，
 *   於是所有掃字串的斷言都是綠的，而畫面上那顆鈕**永遠寫著「開啟手機通知」**，
 *   他會以為沒設定成功而一直按。（mutation 當場抓到的，不是推論。）
 *
 * ★ 這裡驗的是「接線有沒有接上」，不是「在 iPhone 上會動」——
 *   iOS 那兩道門檻（要裝成 PWA、要按允許）沒有任何模擬器驗得了。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const SRC = fs.readFileSync(
    path.join(__dirname, '..', '..', 'static', 'js', 'push-optin.js'), 'utf8');

/* ── 最小的瀏覽器替身 ───────────────────────────── */

function makeEl(id) {
    return {
        id, textContent: '', disabled: false, dataset: {},
        style: {}, _clicks: [],
        addEventListener(type, fn) { if (type === 'click') this._clicks.push(fn); },
        click() { this._clicks.forEach(fn => fn()); },
    };
}

function makeEnv(opts) {
    const btn = makeEl('push-optin');
    const msg = makeEl('push-msg');
    /*  ★ 外面那一塊（首頁橫幅／個人資料頁最上面那一格）。
           它「開好之後要安靜下來」是**行為**，不是有沒有寫那一行 ——
           把 markOn 的函式體挖空，掃原始碼的斷言全都還是綠的
           （mutation 當場抓到）。 */
    const block = makeEl('push-block');
    /*  ★ 「傳一則測試通知」那顆。推播是唯一一件「沒消息」和「壞掉了」
           長得一模一樣的事，所以這顆是它的自我驗證 ——
           而「有沒有畫出來」「按了打哪個端點」都是**行為**，掃原始碼看不到。 */
    const testBtn = makeEl('push-test');
    /*  ★ 模板裡它是 `style="display:none"` —— 替身要從同一個狀態開始，
           不然「只有開啟的那台才畫得出來」那條會永遠是綠的
           （undefined !== 'none'）。 */
    testBtn.style.display = 'none';
    const loaded = [];
    const calls = { requestPermission: 0, subscribe: 0, posted: [] };

    const subscription = opts.alreadySubscribed
        ? { endpoint: 'https://push.example/abc',
            toJSON() { return { endpoint: this.endpoint, keys: {} }; },
            unsubscribe: async () => true }
        : null;

    /*  ★ 「不支援」要用**沒有這個屬性**來表示，不是設成 undefined ——
           程式碼問的是 `'serviceWorker' in navigator`，而設成 undefined
           的鍵**仍然 in 得到**。這一段我第一版就寫錯了，
           於是 iOS 那個情境根本沒有走到它要驗的那條路。 */
    const navigator_ = { userAgent: opts.userAgent || 'node',
                         platform: 'Linux', maxTouchPoints: 0 };
    const window_ = { matchMedia: () => ({ matches: !!opts.standalone }) };
    /*  ★ 測試裡把逾時縮短，不然一條測試要真的等 10 秒。
           正式站不會設這個變數 —— 線上跑的是 push-optin.js 裡那組真的值。 */
    if (opts.fastTimeouts) {
        window_.__PUSH_TIMEOUTS__ = { key: 50, permission: 50, sw: 50,
                                      subscribe: 50, save: 50 };
    }
    if (opts.serviceWorker !== false) {
        navigator_.serviceWorker = {
            /*  ★ `hangOnReady` 重現正式站踩到的那個 bug：
                   service worker 註冊在 `/static/sw.js`，scope 是 `/static/`，
                   於是 `ready` 在 `/profile` 上**永遠不會 resolve 也不會
                   reject**。不是失敗，是永遠停住 —— 使用者看到
                   「處理中…」卡在那裡，console 一行錯誤都沒有。 */
            ready: opts.hangOnReady ? new Promise(() => {}) : Promise.resolve({
                pushManager: {
                    getSubscription: async () => subscription,
                    subscribe: async () => {
                        calls.subscribe++;
                        return { toJSON: () => ({ endpoint: 'https://push.example/new',
                                                  keys: { p256dh: 'p', auth: 'a' } }) };
                    },
                },
            }),
        };
        window_.PushManager = function () {};
    }

    const env = {
        document: {
            getElementById: id => (id === 'push-optin' ? btn
                                 : id === 'push-msg' ? msg
                                 : id === 'push-block' ? block
                                 : id === 'push-test' ? testBtn : null),
            addEventListener(type, fn) {
                if (type === 'DOMContentLoaded') loaded.push(fn);
            },
        },
        navigator: navigator_,
        window: window_,
        Notification: {
            permission: opts.permission || 'default',
            async requestPermission() {
                calls.requestPermission++;
                //  ★ `this` 才是 vm 裡的那個 Notification —— 直接寫
                //    `Notification.xxx` 會指到 harness 自己的模組作用域，
                //    而那裡沒有這個名字（第一版就是這樣 ReferenceError 的）。
                this.permission = opts.grantOnAsk === false ? 'denied' : 'granted';
                return this.permission;
            },
        },
        /*  ★ `setTimeout` 是 host API，**不是 JS 內建** ——
               `vm.createContext` 出來的沙箱裡沒有它。
               漏了的話，程式裡任何一個計時器都會變成 ReferenceError，
               而 push-optin.js 把例外接住了，於是症狀是
               「按了沒反應」而不是一行錯誤。（實際踩到才補的。） */
        setTimeout, clearTimeout,
        atob: s => Buffer.from(s, 'base64').toString('binary'),
        fetch: async (url, init) => {
            calls.posted.push(url);
            if (url === '/api/push/key') {
                return { ok: true, json: async () => ({ enabled: true, key: 'AAAA' }) };
            }
            if (url === '/api/push/subscribe') {
                /*  ★ 伺服器存好之後會立刻推一則，並且照實回報 ——
                       這裡把「送不出去」那一半也模擬得出來，
                       不然「失敗時不可以說開好了」那條守不到。 */
                return { ok: true, json: async () => ({
                    success: true,
                    test_sent: opts.welcomeFails ? false : true,
                    test_error: opts.welcomeFails ? '推播服務回 403' : '',
                }) };
            }
            if (url === '/api/push/test') {
                return { ok: true, json: async () => (
                    opts.testFails
                        ? { success: false, error: '推播服務回 403' }
                        : { success: true, devices: 2, sent: 2 }) };
            }
            return { ok: true, json: async () => ({ success: true }) };
        },
    };
    env.window.navigator = env.navigator;
    env.self = env.window;
    return { env, btn, msg, block, testBtn, loaded, calls };
}

async function run(opts) {
    const { env, btn, msg, block, testBtn, loaded, calls } = makeEnv(opts);
    const vm = require('vm');
    const ctx = vm.createContext(env);
    vm.runInContext(SRC, ctx);
    loaded.forEach(fn => fn());
    await settle();

    /*  ★ 「載入的時候問過權限沒有」要在**這裡**記下來 ——
           `calls` 是累加的，等按完再看就分不出那一次是誰觸發的。 */
    const afterLoad = { label: btn.textContent, msg: msg.textContent,
                        on: btn.dataset.on || '',
                        blockOn: block.dataset.on || '',
                        testShown: testBtn.style.display !== 'none',
                        asked: calls.requestPermission };

    if (opts.clickIt) {
        btn.click();
        await settle(opts.settleTicks || 20);
    }

    let afterTest = null;
    if (opts.clickTest) {
        testBtn.click();
        await settle();
        afterTest = { msg: msg.textContent, disabled: testBtn.disabled };
    }
    return {
        afterLoad,
        afterClick: { label: btn.textContent, msg: msg.textContent,
                      blockOn: block.dataset.on || '',
                      testShown: testBtn.style.display !== 'none',
                      disabled: btn.disabled },
        afterTest,
        calls,
    };
}

/*  把排隊中的工作跑完。
    ★ enable() 那條路上有五個 await（拿公鑰、問權限、等 SW、訂閱、回存），
      只讓出一個 tick 的話會**在流程跑完之前**就去讀畫面 ——
      而那看起來會像「功能沒接上」。 */
function settle(ticks = 20) {
    let p = Promise.resolve();
    for (let i = 0; i < ticks; i++) p = p.then(() => new Promise(r => setTimeout(r, 0)));
    return p;
}

(async () => {
    const out = {};
    out.already_subscribed = await run({ permission: 'granted', alreadySubscribed: true });
    out.fresh_device       = await run({ permission: 'default', clickIt: true });
    /*  ★ 這一個**一定要真的按下去** —— 不按的話，
           「拒絕過的裝置不可以再問一次」那道守衛就沒有被走到，
           而拿掉它測試照樣是綠的（mutation 抓到）。 */
    out.denied_device      = await run({ permission: 'denied', clickIt: true });
    /*  ★ 正式站踩過的那一個：`ready` 永遠不回來。
           逾時之後**按鈕一定要回來**，而且要講出卡在哪一步。 */
    out.sw_never_ready     = await run({ permission: 'granted', clickIt: true,
                                         hangOnReady: true, fastTimeouts: true,
                                         settleTicks: 200 });
    out.ios_safari_tab     = await run({
        serviceWorker: false, standalone: false,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
    });
    /*  ★ 訂閱存好了、但那一則測試推播送不出去 —— **不可以說開好了**。
           他會以為設定成功，然後等一個永遠不會來的通知。 */
    out.welcome_failed     = await run({ permission: 'default', clickIt: true,
                                         welcomeFails: true });
    /*  ★★ 關掉通知之後那顆測試鈕要**收起來**。
           少了這個情境的話，「只有開啟的那台才畫得出來」那條會靠
           模板的 `display:none` 自己通過 —— 把隱藏那一半挖掉照樣是綠的
           （mutation 當場抓到）。 */
    out.turned_off         = await run({ permission: 'granted',
                                         alreadySubscribed: true, clickIt: true });
    /*  ★ 已經開啟的那台按「傳一則測試通知」。 */
    out.test_ok            = await run({ permission: 'granted',
                                         alreadySubscribed: true, clickTest: true });
    out.test_failed        = await run({ permission: 'granted',
                                         alreadySubscribed: true, clickTest: true,
                                         testFails: true });
    process.stdout.write(JSON.stringify(out, null, 1));
})().catch(e => { console.error(e); process.exit(1); });
