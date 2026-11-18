// 主日信息：點一下就在**這一頁**播，不跳去 YouTube
//
// ★ 為什麼是「點了才載 iframe」（facade）
//   /sermons 一次列 60 部。每一部都先放一個 iframe 的話，等於一開頁就
//   同時載入 60 個 YouTube 播放器 —— 手機會卡到動不了，而且流量全花在
//   使用者根本不會看的 59 部上。所以先只放縮圖，按下去才換成播放器。
//
// ★ 有些影片不允許嵌入（上傳者關掉的話）。那時候 iframe 裡會是一片
//   「無法播放」，而我們這一頁看起來完全正常 —— 所以每一個位置都要
//   留一條「在 YouTube 開啟」的路。
(function () {
    'use strict';

    // youtube-nocookie：官方的隱私加強網域，沒播之前不會種追蹤 cookie。
    var BASE = 'https://www.youtube-nocookie.com/embed/';

    function embed(box) {
        var id = box.dataset.yt;
        if (!id || box.dataset.playing === 'true') return;
        box.dataset.playing = 'true';

        var frame = document.createElement('iframe');
        // autoplay 只在「使用者按了」之後才成立 —— 這裡就是那一下
        frame.src = BASE + encodeURIComponent(id) + '?autoplay=1&rel=0';
        frame.title = box.dataset.title || '主日信息';
        frame.allow = 'accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture';
        frame.allowFullscreen = true;
        frame.loading = 'lazy';
        frame.style.cssText = 'width:100%;aspect-ratio:16/9;border:0;display:block;' +
                              'border-radius:12px;background:var(--text-1, #1f2421);';

        box.innerHTML = '';
        box.appendChild(frame);
        box.style.cursor = 'default';
    }

    document.addEventListener('click', function (ev) {
        var box = ev.target.closest ? ev.target.closest('[data-yt]') : null;
        if (!box) return;
        // ★ 「在 YouTube 開啟」那條連結要讓它照常運作 ——
        //   攔下來的話，不能嵌入的影片就變成完全沒有路可以走。
        if (ev.target.closest('a')) return;
        ev.preventDefault();
        embed(box);
    });

    // 鍵盤也要能按（縮圖是 div，不是原生按鈕）
    document.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter' && ev.key !== ' ') return;
        var box = document.activeElement;
        if (box && box.dataset && box.dataset.yt) {
            ev.preventDefault();
            embed(box);
        }
    });
})();
