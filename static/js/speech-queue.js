/* 一節一節唸下去的佇列 —— 抽出來是為了**測得到**
 *
 * ## 為什麼不留在 bible-reading-day.js 裡
 *
 * 朗讀的失敗模式全部是「按了，然後就沒有然後了」—— 看程式碼看不出來，
 * 掃原始碼的斷言也驗不到。抽成一支不碰 DOM 的模組，就可以在 node 裡
 * 用假的 speechSynthesis 真的跑一次（tests/js/speech_harness.js）。
 *
 * ## ★★ iOS Safari 三個會讓它靜靜停住的坑
 *
 * 1. **`onend` 不一定會來。** iOS（和某些 Chrome 版本）在 `cancel()` 之後、
 *    或畫面切到背景再回來時，`onend` 可能整個不觸發。而我們是靠 `onend`
 *    接下一節的 —— 不觸發就等於**唸完第一節就停住，畫面完全正常**。
 *    → 每一節都掛一個看門狗計時器，時間到就自己往下走。
 *
 * 2. **utterance 被垃圾回收就不再發事件。** 只把它丟給 `speak()` 而自己
 *    不留參考的話，瀏覽器可能在唸完之前就把它回收掉，事件全部消失。
 *    → 留一份參考在 `current`。
 *
 * 3. **`cancel()` 之後馬上 `speak()` 會被丟掉。** iOS 的佇列還在收尾，
 *    新的那一句直接消失 —— 按「停止」再按「朗讀」就沒有聲音了。
 *    → 中間隔一小段時間再送。
 *
 * ★ 看門狗要**寬鬆**：太短會跳掉還在唸的那一節（使用者會以為漏了經文），
 *   太長只是多一點空白。所以估算值抓實際的三倍以上。
 */
(function (global) {
    'use strict';

    //  一個中文字大約唸多久（毫秒）。rate=1 時約每秒 5-6 字，
    //  這裡刻意抓得比實際慢很多 —— 看門狗寧可晚不可早。
    var MS_PER_CHAR = 400;
    var FLOOR_MS = 8000;

    //  cancel() 之後要等多久才敢送下一句（iOS 的佇列在收尾）
    var RESTART_DELAY = 120;

    function watchdogMs(text, rate) {
        var r = rate > 0 ? rate : 1;
        return Math.round((String(text || '').length * MS_PER_CHAR) / r) + FLOOR_MS;
    }

    function createSpeechQueue(cfg) {
        var synth = cfg.synth;
        var setTimer = cfg.setTimer || setTimeout;
        var clearTimer = cfg.clearTimer || clearTimeout;

        var speaking = false;
        var idx = 0;
        var current = null;      // ★ 留參考，不然會被 GC 掉（坑 2）
        var timer = null;

        function texts() { return cfg.texts() || []; }

        function clearWatchdog() {
            if (timer !== null) { clearTimer(timer); timer = null; }
        }

        function advance(from) {
            //  ★ `from` 是「哪一節結束了」—— 比對過才往下走。
            //    不比對的話，看門狗和 onend 同時到會**跳掉一節**。
            if (!speaking || from !== idx) return;
            clearWatchdog();
            speak(idx + 1);
        }

        function speak(i) {
            clearWatchdog();
            var list = texts();
            if (!speaking || i >= list.length) { stop(); return; }
            idx = i;

            var text = String(list[i] == null ? '' : list[i]);
            if (!text.trim()) { speak(i + 1); return; }

            var u = cfg.utteranceFor(text);
            current = u;
            u.onstart = function () { if (cfg.onSpeak) cfg.onSpeak(i); };
            u.onend = function () { advance(i); };
            u.onerror = function () {
                //  ★ 出錯**不要整個停掉**，往下一節走 ——
                //    某一節唸不出來（奇怪的標點、太長）不該讓後面全部沒聲音。
                advance(i);
            };

            //  看門狗：`onend` 沒來的時候自己往下走（坑 1）
            timer = setTimer(function () {
                timer = null;
                advance(i);
            }, watchdogMs(text, u.rate));

            synth.speak(u);
        }

        function start(fromIndex) {
            if (typeof fromIndex === 'number') idx = fromIndex;
            speaking = true;
            //  ★ 先 cancel 清掉殘留，隔一下再送（坑 3）。
            //    ★ 但**第一次**要同步送出 —— iOS 規定第一次 speak() 必須
            //      在使用者手勢的那一個 tick 裡，放進 setTimeout 就失效了。
            if (synth.speaking || synth.pending) {
                synth.cancel();
                setTimer(function () { if (speaking) speak(idx); }, RESTART_DELAY);
            } else {
                speak(idx);
            }
        }

        function pause() {
            speaking = false;
            clearWatchdog();
            current = null;
            synth.cancel();
        }

        function stop() {
            speaking = false;
            clearWatchdog();
            current = null;
            idx = 0;
            synth.cancel();
            if (cfg.onStop) cfg.onStop();
        }

        function restartHere() {
            //  改了聲音／速度：從**現在這一節**重來，不要跳掉
            if (!speaking) return;
            clearWatchdog();
            synth.cancel();
            setTimer(function () { if (speaking) speak(idx); }, RESTART_DELAY);
        }

        return {
            start: start,
            pause: pause,
            stop: stop,
            restartHere: restartHere,
            isSpeaking: function () { return speaking; },
            index: function () { return idx; },
            //  測試看得到目前握著的 utterance（坑 2 的守衛）
            _current: function () { return current; },
        };
    }

    global.createSpeechQueue = createSpeechQueue;
    global.speechWatchdogMs = watchdogMs;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { createSpeechQueue: createSpeechQueue, watchdogMs: watchdogMs };
    }
})(typeof window !== 'undefined' ? window : globalThis);
