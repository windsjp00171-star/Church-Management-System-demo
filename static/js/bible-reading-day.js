// 聖經速讀 — 一格的閱讀頁：朗讀 ＋ 讀完了
//
// ★ 朗讀用瀏覽器內建的 speechSynthesis：不用金鑰、不用付費、
//   一個字都不會上傳。裝置沒有中文語音時要**講出來** ——
//   按了沒反應會被當成功能壞了。
//
// ★ X-CSRF-Token 不用自己帶（csrf-fetch.js 已經包裝 fetch）。
(function () {
    'use strict';

    // ── 朗讀 ──────────────────────────────────────────
    var bar = document.getElementById('rd-bar');
    var playBtn = document.getElementById('rd-play');
    var stopBtn = document.getElementById('rd-stop');
    var gearBtn = document.getElementById('rd-gear');
    var panel = document.getElementById('rd-voice');
    var pickEl = document.getElementById('rd-voice-pick');
    var pitchEl = document.getElementById('rd-pitch');
    var rateEl = document.getElementById('rd-rate');
    var tryBtn = document.getElementById('rd-try');
    var tryMsg = document.getElementById('rd-try-msg');
    var msgEl = document.getElementById('rd-msg');
    var verses = Array.prototype.slice.call(document.querySelectorAll('.rd-verse[data-speak]'));

    var synth = window.speechSynthesis;
    //  ★ 「現在唸到哪、有沒有在唸」由 speech-queue.js 管，這裡不留第二份 ——
    //    兩份狀態遲早會不一樣，而症狀是「按暫停沒反應」。

    if (synth && verses.length) bar.hidden = false;

    // ── 記住他挑的聲音 ──────────────────────────────
    //
    // ★ 用 localStorage：這是**這台裝置**的偏好（聲音清單本來就因裝置而異），
    //   存到資料庫等於把「我在手機上挑的男聲」帶到一台沒有那個聲音的電腦上。
    //   ★ 讀寫都包 try —— 無痕視窗、關掉網站資料時存取本身會丟例外。
    var PREF = 'bibleVoice';
    function loadPref() {
        try { return JSON.parse(localStorage.getItem(PREF)) || {}; }
        catch (e) { return {}; }
    }
    function savePref(p) {
        try { localStorage.setItem(PREF, JSON.stringify(p)); } catch (e) { /* 存不了就算了 */ }
    }
    var pref = loadPref();
    if (pref.pitch) pitchEl.value = pref.pitch;
    if (pref.rate) rateEl.value = pref.rate;

    function zhVoices() {
        var vs = (synth && synth.getVoices && synth.getVoices()) || [];
        return vs.filter(function (v) { return /^zh/i.test(v.lang); });
    }

    //  ★ 沒有 gender 這個標準屬性 —— 只能從名字猜，而且**只拿來排序**，
    //    不拿來替他決定。猜錯的代價是排序不理想，不是聽到錯的聲音。
    var MALE_HINTS = /kangkang|yunyang|yunxi|yunjian|male|男|康康|雲揚|雲希|文昊|Liang|Zhiyu/i;

    function fillVoiceList() {
        if (!pickEl) return;
        var vs = zhVoices();
        //  語音清單是非同步載入的 —— 空的時候什麼都不要說（那是還沒載完）
        if (!vs.length) return;

        //  可能猜是男聲的排前面，方便他找
        vs.sort(function (a, b) {
            var am = MALE_HINTS.test(a.name) ? 0 : 1;
            var bm = MALE_HINTS.test(b.name) ? 0 : 1;
            return am - bm || a.name.localeCompare(b.name);
        });

        pickEl.innerHTML = '';
        vs.forEach(function (v) {
            var o = document.createElement('option');
            o.value = v.voiceURI;
            o.textContent = v.name + '（' + v.lang + '）' +
                            (MALE_HINTS.test(v.name) ? ' ♂' : '');
            pickEl.appendChild(o);
        });
        if (pref.voiceURI && vs.some(function (v) { return v.voiceURI === pref.voiceURI; })) {
            pickEl.value = pref.voiceURI;
        }
        msgEl.textContent = '';
    }

    function pickVoice() {
        var vs = zhVoices();
        if (!vs.length) return null;
        if (pickEl && pickEl.value) {
            var chosen = vs.filter(function (v) { return v.voiceURI === pickEl.value; });
            if (chosen.length) return chosen[0];
        }
        var tw = vs.filter(function (v) { return /^zh[-_]TW/i.test(v.lang); });
        return tw.length ? tw[0] : vs[0];
    }

    function warnIfNoChineseVoice() {
        // ★ 語音清單是**非同步**載入的，第一次問常常是空的。
        //   空的時候不可以就說「沒有中文語音」—— 那是還沒載完，不是沒有。
        var all = (synth && synth.getVoices && synth.getVoices()) || [];
        if (!all.length) return;
        if (!zhVoices().length) {
            msgEl.textContent = '這台裝置沒有中文語音，唸出來可能怪怪的';
        }
    }
    if (synth && synth.addEventListener) {
        synth.addEventListener('voiceschanged', function () {
            fillVoiceList();
            warnIfNoChineseVoice();
        });
    }
    fillVoiceList();
    warnIfNoChineseVoice();

    if (gearBtn) {
        gearBtn.addEventListener('click', function () {
            var open = panel.hidden;
            panel.hidden = !open;
            gearBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (open) fillVoiceList();   // 打開時再要一次，通常這時已經載完了
        });
    }

    function applyVoice(u) {
        u.lang = 'zh-TW';
        var v = pickVoice();
        if (v) { u.voice = v; u.lang = v.lang; }
        u.rate = parseFloat(rateEl.value) || 0.9;
        // ★ 「低沉」就是這個 —— pitch 調低會讓同一個聲音變低。
        //   它不會把女聲變成男聲，但這是**不用花錢、不用金鑰**能做到的部分。
        u.pitch = parseFloat(pitchEl.value) || 1;
        return u;
    }

    function rememberChoice() {
        savePref({
            voiceURI: pickEl ? pickEl.value : '',
            pitch: pitchEl.value,
            rate: rateEl.value,
        });
    }

    function highlight(i) {
        verses.forEach(function (el, k) { el.classList.toggle('speaking', k === i); });
        if (i >= 0 && verses[i]) {
            verses[i].scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
    }

    // ★★ 佇列本身在 static/js/speech-queue.js —— 抽出去是為了**測得到**。
    //    朗讀的失敗模式全部是「按了，然後就沒有然後了」，
    //    看程式碼看不出來，掃原始碼也驗不到。
    var queue = window.createSpeechQueue({
        synth: synth,
        texts: function () {
            return verses.map(function (el) { return el.getAttribute('data-speak') || ''; });
        },
        utteranceFor: function (text) {
            return applyVoice(new SpeechSynthesisUtterance(text));
        },
        onSpeak: highlight,
        onStop: function () {
            playBtn.textContent = '🔊 朗讀';
            stopBtn.disabled = true;
            highlight(-1);
        },
    });

    function start() {
        if (!synth) return;
        playBtn.textContent = '⏸ 暫停';
        stopBtn.disabled = false;
        msgEl.textContent = '';
        // ★ 這一行必須在使用者手勢的**同一個 tick** 裡 —— iOS 規定
        //   第一次 speak() 要跟著手勢走，包進 setTimeout 就永遠不會出聲。
        queue.start();
    }

    function pause() {
        queue.pause();
        playBtn.textContent = '🔊 接著唸';
    }

    if (playBtn) {
        playBtn.addEventListener('click', function () {
            if (queue.isSpeaking()) pause(); else start();
        });
    }
    if (stopBtn) stopBtn.addEventListener('click', function () { queue.stop(); });

    //  改設定：記住，而且從**現在這一節**重來（不要跳掉）
    [pickEl, pitchEl, rateEl].forEach(function (el) {
        if (!el) return;
        el.addEventListener('change', function () {
            rememberChoice();
            queue.restartHere();
        });
    });

    //  ★ 試聽：不用先開始整章才知道這個聲音對不對。
    //    沒有這一顆的話，他要調一次、播一次、停一次，調三輪就放棄了。
    var sampleUtterance = null;   // ★ 留參考，不然唸完之前就被 GC 掉（事件全消失）
    if (tryBtn) {
        tryBtn.addEventListener('click', function () {
            if (!synth) return;
            rememberChoice();
            var wasSpeaking = synth.speaking || synth.pending;
            queue.stop();

            var sample = (verses[0] && verses[0].getAttribute('data-speak')) ||
                         '耶和華是我的牧者，我必不至缺乏。';
            tryMsg.textContent = '播放中…';

            function say() {
                var u = applyVoice(new SpeechSynthesisUtterance(sample));
                sampleUtterance = u;
                u.onend = function () { tryMsg.textContent = ''; };
                u.onerror = function () { tryMsg.textContent = '這個聲音播不出來，換一個試試'; };
                synth.speak(u);
            }

            // ★ 沒有東西在唸的時候要**同一個 tick** 送出 —— iOS 規定
            //   第一次 speak() 得跟著使用者手勢走。
            //   正在唸的時候才需要等 cancel() 收尾（不等的話這一句會被丟掉）。
            if (wasSpeaking) setTimeout(say, 150); else say();
        });
    }

    // ★ 離開這一頁要停 —— 不停的話換頁之後聲音還在唸，
    //   而使用者找不到是哪裡在出聲。
    window.addEventListener('pagehide', function () { queue.stop(); });

    // ★★ iOS：切到背景（或鎖螢幕）時系統會把語音停住，但我們的看門狗
    //    還在跑 —— 回來的時候它已經「走過」好幾節了，而那幾節根本沒唸出來。
    //    所以離開畫面就先暫停，回來由使用者自己按「接著唸」。
    document.addEventListener('visibilitychange', function () {
        if (document.hidden && queue.isSpeaking()) {
            pause();
        }
    });


    // ── 讀完了 ────────────────────────────────────────
    var doneBtn = document.getElementById('rd-done');
    var afterEl = document.getElementById('rd-after');
    var countEl = document.getElementById('rd-count');
    var nextCard = document.getElementById('rd-next');
    var nextLabel = document.getElementById('rd-next-label');
    var nextSub = document.getElementById('rd-next-sub');
    var rereadCard = document.getElementById('rd-reread');
    if (!doneBtn) return;

    doneBtn.addEventListener('click', async function () {
        if (doneBtn.disabled) return;
        var want = doneBtn.dataset.done !== 'true';
        var was = doneBtn.textContent;
        doneBtn.disabled = true;
        doneBtn.textContent = '記錄中…';
        try {
            var res = await fetch('/reading/mark', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    day_no: parseInt(doneBtn.dataset.day, 10),
                    done: want,
                }),
            });
            var d = await res.json();
            if (!res.ok) throw new Error(d.error || '存不進去');

            doneBtn.dataset.done = want ? 'true' : 'false';
            doneBtn.classList.toggle('already', want);
            doneBtn.textContent = want ? '✓ 已經讀過了（再按一次可取消）' : '我讀完了';
            countEl.textContent = d.stats.done;
            //  ★ 打勾／取消之後一律收起「重讀下一格」：下一格讀沒讀過只有伺服器
            //    知道，前端不自己判斷（重新整理後由伺服器決定要不要再出現）。
            if (rereadCard) rereadCard.hidden = true;
            if (nextSub) nextSub.textContent = '繼續讀下一格';

            // ★ 記完之後要給下一步 —— 停在原地的話他不知道接下來去哪，
            //   而「接下來讀哪一格」正是這個計畫最常被放棄的地方。
            //
            // ★ 這裡**只更新模板那張卡**，不自己拼一段 HTML 出來
            //   （使用者定的：做卡片，不要做連結）。在這裡再拼一份版面的話，
            //   以後改樣式這一段不會跟，而兩邊各自看都正常。
            if (nextCard && nextLabel) {
                if (d.next) {
                    nextLabel.textContent = d.next.label;   // ★ 不用 innerHTML
                    nextCard.href = '/reading/' + d.next.day_no;
                    nextCard.hidden = false;
                } else {
                    nextCard.hidden = true;
                }
            }
            if (want && !d.next) {
                afterEl.style.display = 'block';
                afterEl.textContent = '整本讀完了 🎉';
            } else {
                afterEl.style.display = 'none';
            }
        } catch (e) {
            doneBtn.textContent = was;
            alert(e.message);
        } finally {
            doneBtn.disabled = false;
        }
    });

    // ── 我重讀完了（記一次）────────────────────────────
    //  ★ 放在「讀完了」之後：上面朗讀那一半一個字都不上傳（有測試以那行註解為界掃 fetch）。
    //    數字和日期用**伺服器回來的**，不在前端自己加一。
    (function () {
        var btn = document.getElementById('rd-reread-btn');
        var info = document.getElementById('rd-reread-info');
        if (!btn || !info) return;
        btn.addEventListener('click', function () {
            if (btn.disabled) return;
            btn.disabled = true;
            fetch('/reading/reread', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ day_no: parseInt(btn.dataset.day, 10) }),
            }).then(function (r) {
                return r.json().then(function (d) {
                    if (!r.ok) throw new Error(d.error || '存不進去');
                    return d;
                });
            }).then(function (d) {
                info.textContent = '已重讀 ' + d.count + ' 次' + (d.last ? '，最近一次 ' + d.last : '')
                    + (d.added ? '' : '（今天已經記過了）');
            }).catch(function (e) { alert(e.message); })
              .then(function () { btn.disabled = false; });
        });
    })();
})();
