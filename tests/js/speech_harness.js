/* 在 node 裡真的跑一次 static/js/speech-queue.js
 *
 * ## 為什麼不能用掃原始碼的斷言
 *
 * 朗讀的失敗模式全部是「按了，然後就沒有然後了」——
 * 唸完第一節就停住、按停止再按朗讀沒有聲音、切到背景回來跳掉三節。
 * 這些**看程式碼看不出來**，而且畫面完全正常（按鈕還在、字還在）。
 *
 * 所以這裡用一個假的 speechSynthesis 真的跑，而且刻意重現
 * iOS Safari 那幾個行為：`onend` 不來、`cancel()` 之後馬上 `speak()`
 * 會被丟掉。
 *
 * 輸出 JSON，斷言寫在 tests/test_speech_queue.py（一個情境一條）。
 */
'use strict';
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(
    path.join(__dirname, '..', '..', 'static', 'js', 'speech-queue.js'), 'utf8');
//  ★ 走 module.exports 那條路：全域上的名字是 `speechWatchdogMs`
//    （避免跟別的腳本撞名），module.exports 才是 `watchdogMs`。
const mod = { exports: {} };
new Function('globalThis', 'module', src)({}, mod);
const { createSpeechQueue, watchdogMs } = mod.exports;

// ── 假的計時器：測試自己決定時間往前走多少 ──────────────
function makeClock() {
    let now = 0, seq = 1;
    const jobs = new Map();
    return {
        setTimer(fn, ms) { const id = seq++; jobs.set(id, { at: now + ms, fn }); return id; },
        clearTimer(id) { jobs.delete(id); },
        advance(ms) {
            const target = now + ms;
            let guard = 0;
            for (;;) {
                let next = null;
                for (const [id, j] of jobs) {
                    if (j.at <= target && (next === null || j.at < jobs.get(next).at)) next = id;
                }
                if (next === null || guard++ > 5000) break;
                const j = jobs.get(next);
                jobs.delete(next);
                now = j.at;
                j.fn();
            }
            now = target;
        },
        pending() { return jobs.size; },
    };
}

/* 假的 speechSynthesis。
 *   opts.fireEnd  : 唸完要不要發 onend（false ＝ 重現 iOS 那個坑）
 *   opts.dropAfterCancel : cancel() 之後**同一個 tick** 送進來的要不要丟掉
 */
function makeSynth(opts) {
    opts = opts || {};
    const spoken = [];
    let justCancelled = false;
    const api = {
        speaking: false,
        pending: false,
        spoken,
        dropped: 0,
        cancel() {
            justCancelled = true;
            api.speaking = false;
            api.pending = false;
        },
        speak(u) {
            if (opts.dropAfterCancel && justCancelled) { api.dropped++; return; }
            spoken.push(u.text);
            api.speaking = true;
            if (u.onstart) u.onstart();
            if (opts.fireEnd !== false) {
                api.speaking = false;
                if (u.onend) u.onend();
            }
            // fireEnd === false：就這樣掛著，永遠不發 onend（iOS 的坑）
        },
        //  模擬「cancel 的收尾結束了」
        settle() { justCancelled = false; },
    };
    return api;
}

function utteranceFor(text) {
    return { text: text, rate: 1, onstart: null, onend: null, onerror: null };
}

function build(synth, clock, texts) {
    const spokeAt = [];
    const q = createSpeechQueue({
        synth, texts: () => texts, utteranceFor,
        setTimer: clock.setTimer, clearTimer: clock.clearTimer,
        onSpeak: (i) => spokeAt.push(i),
        onStop: () => spokeAt.push('stop'),
    });
    return { q, spokeAt };
}

const T = ['第一節', '第二節', '第三節'];
const out = {};

// 1. 正常情況：一節接一節唸完，然後自己停
{
    const synth = makeSynth({});
    const { q, spokeAt } = build(synth, makeClock(), T);
    q.start();
    out.normal_run = { spoken: synth.spoken, highlights: spokeAt, speaking: q.isSpeaking() };
}

// 2. ★ onend 永遠不來（iOS）——看門狗要把它推下去
{
    const synth = makeSynth({ fireEnd: false });
    const clock = makeClock();
    const { q } = build(synth, clock, T);
    q.start();
    const afterStart = synth.spoken.slice();
    clock.advance(watchdogMs('第一節', 1) + 10);
    const after1 = synth.spoken.slice();
    clock.advance(watchdogMs('第二節', 1) + 10);
    clock.advance(watchdogMs('第三節', 1) + 10);
    out.onend_never_fires = {
        after_start: afterStart, after_one_watchdog: after1,
        all_spoken: synth.spoken, still_speaking: q.isSpeaking(),
    };
}

// 3. ★ 看門狗和 onend 同時到，不可以跳掉一節
{
    const synth = makeSynth({});          // onend 會來
    const clock = makeClock();
    const { q } = build(synth, clock, T);
    q.start();
    clock.advance(999999);                // 讓所有殘留的計時器都跑完
    out.watchdog_does_not_double_advance = { spoken: synth.spoken };
}

// 4. ★ cancel() 之後馬上 speak() 會被丟掉（iOS）——重開要隔一下
{
    const synth = makeSynth({ dropAfterCancel: true });
    const clock = makeClock();
    const { q } = build(synth, clock, T);
    synth.speaking = true;                // 假裝還在唸上一輪
    q.start();
    const immediate = synth.spoken.slice();
    synth.settle();                       // cancel 收尾完成
    clock.advance(500);
    out.restart_after_cancel = {
        spoken_immediately: immediate, dropped: synth.dropped,
        spoken_after_delay: synth.spoken,
    };
}

// 5. ★ 第一次（沒有東西在唸）要**同步**送出 —— iOS 的手勢規定
{
    const synth = makeSynth({ fireEnd: false });
    const clock = makeClock();
    const { q } = build(synth, clock, T);
    q.start();
    out.first_speak_is_synchronous = { spoken_before_any_timer: synth.spoken.slice() };
}

// 6. ★ utterance 要留著參考（不留會被 GC，事件全消失）
{
    const synth = makeSynth({ fireEnd: false });
    const { q } = build(synth, makeClock(), T);
    q.start();
    const cur = q._current();
    out.keeps_utterance_reference = { has_current: !!cur, text: cur && cur.text };
}

// 7. 停止：清乾淨、計時器不留、回到第一節
{
    const synth = makeSynth({ fireEnd: false });
    const clock = makeClock();
    const { q } = build(synth, clock, T);
    q.start();
    q.stop();
    out.stop_clears_everything = {
        speaking: q.isSpeaking(), index: q.index(),
        current: q._current(), timers_left: clock.pending(),
    };
}

// 8. 暫停之後接著唸 —— 從**同一節**繼續，不是從頭
{
    const synth = makeSynth({ fireEnd: false });
    const clock = makeClock();
    const { q } = build(synth, clock, T);
    q.start();
    clock.advance(watchdogMs('第一節', 1) + 10);   // 走到第二節
    const at = q.index();
    q.pause();
    synth.spoken.length = 0;
    q.start();
    out.resume_continues = { paused_at: at, after_resume: synth.spoken };
}

// 9. ★ 某一節出錯不可以讓後面全部沒聲音
{
    const clock = makeClock();
    const synth = makeSynth({});
    const origSpeak = synth.speak;
    synth.speak = function (u) {
        if (u.text === '第二節') { if (u.onerror) u.onerror(); return; }
        origSpeak.call(synth, u);
    };
    const { q } = build(synth, clock, T);
    q.start();
    clock.advance(999999);
    out.one_bad_verse_does_not_kill_the_rest = { spoken: synth.spoken };
}

// 10. 空白的那一節跳過，不要卡住
{
    const synth = makeSynth({});
    const clock = makeClock();
    const { q } = build(synth, clock, ['甲', '   ', '丙']);
    q.start();
    clock.advance(999999);
    out.blank_verses_are_skipped = { spoken: synth.spoken };
}

// 12. ★★ 看門狗先推了，**遲到的 onend** 才來 —— 不可以再推一次
//
//     真實瀏覽器的 onend 是非同步的。iOS 上它常常晚到（甚至在
//     下一節已經開始之後）。沒有比對「是哪一節結束了」的話，
//     那一下會把還沒唸的第三節直接跳過去。
{
    const held = [];                       // 手上留著每一個 utterance
    const spoken = [];
    const clock = makeClock();
    const synth = {
        speaking: false, pending: false,
        cancel() { },
        speak(u) { spoken.push(u.text); held.push(u); if (u.onstart) u.onstart(); },
    };
    const q = createSpeechQueue({
        synth, texts: () => T, utteranceFor,
        setTimer: clock.setTimer, clearTimer: clock.clearTimer,
    });
    q.start();                             // 唸第一節，onend 還沒來
    clock.advance(watchdogMs('第一節', 1) + 10);   // 看門狗推到第二節
    const afterWatchdog = spoken.slice();
    held[0].onend();                       // ★ 第一節的 onend 現在才遲到
    out.late_onend_does_not_skip = {
        after_watchdog: afterWatchdog,
        after_late_onend: spoken.slice(),
    };
}

// 11. 看門狗要比實際唸的時間**寬鬆很多**
out.watchdog_is_generous = {
    short: watchdogMs('神愛世人', 1),
    long: watchdogMs('十'.repeat(80), 1),
    faster_is_shorter: watchdogMs('十'.repeat(80), 2) < watchdogMs('十'.repeat(80), 1),
};

process.stdout.write(JSON.stringify(out, null, 1));
