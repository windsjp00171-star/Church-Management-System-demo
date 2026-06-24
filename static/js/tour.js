'use strict';
/**
 * SpotlightTour — 聚光燈教學導覽引擎
 *
 * API:
 *   SpotlightTour.start(steps, opts)  — 直接啟動
 *   SpotlightTour.auto(key, steps, opts) — 若 localStorage 未見過則啟動
 *   SpotlightTour.reset(key)          — 清除已讀記錄（允許重播）
 *
 * Step 物件:
 *   { sel: '#css-selector', title: '標題', body: '說明文字', spot: 8 }
 *   sel 為空字串 → 顯示置中卡（無聚光燈）
 *
 * opts 物件:
 *   { key: 'page-key', idleMs: 22000 }
 */
const SpotlightTour = (function () {

    let _steps = [], _idx = 0, _opts = {};
    let _idleTimer = null;
    let _hole, _tip, _banner, _overlay;
    let _domReady = false;

    /* ── DOM 初始化 ─────────────────────────────────────────── */
    function _ensureDom() {
        if (_domReady) return;
        _domReady = true;

        _overlay = _el('div', 'st-overlay', [
            'position:fixed', 'inset:0', 'z-index:9800', 'cursor:pointer',
            'display:none'
        ]);
        _overlay.addEventListener('click', function (e) {
            if (e.target === _overlay) { _resetIdle(); _next(); }
        });

        _hole = _el('div', 'st-hole', [
            'position:fixed', 'z-index:9801', 'border-radius:8px',
            'transition:left .25s,top .25s,width .25s,height .25s',
            'pointer-events:none',
            'box-shadow:0 0 0 9999px rgba(0,0,0,.6)',
            'display:none'
        ]);

        _tip = _el('div', 'st-tip', [
            'position:fixed', 'z-index:9810', 'background:#fff',
            'border-radius:14px', 'box-shadow:0 8px 32px rgba(0,0,0,.28)',
            'padding:20px 22px 16px', 'max-width:min(360px,92vw)',
            'min-width:240px', 'font-family:inherit', 'display:none'
        ]);

        _banner = _el('div', 'st-banner', [
            'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:9820',
            'background:#06C755', 'color:#fff',
            'display:none', 'align-items:center', 'justify-content:space-between',
            'padding:8px 16px', 'font-size:.85rem', 'font-weight:600',
            'box-shadow:0 2px 8px rgba(0,0,0,.2)'
        ]);
        _banner.innerHTML =
            '<span>📚 教學導覽進行中</span>' +
            '<button id="st-end" style="background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.4);' +
            'color:#fff;padding:4px 14px;border-radius:20px;cursor:pointer;font-size:.8rem;white-space:nowrap;">' +
            '結束導覽</button>';

        document.body.appendChild(_overlay);
        document.body.appendChild(_hole);
        document.body.appendChild(_tip);
        document.body.appendChild(_banner);

        document.getElementById('st-end').addEventListener('click', _end);
        document.addEventListener('keydown', _onKey);
    }

    function _el(tag, id, styles) {
        var e = document.createElement(tag);
        e.id = id;
        e.style.cssText = styles.join(';') + ';';
        return e;
    }

    /* ── 鍵盤 ────────────────────────────────────────────────── */
    function _onKey(e) {
        if (!_banner || _banner.style.display === 'none') return;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { _resetIdle(); _next(); }
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { _resetIdle(); _prev(); }
        else if (e.key === 'Escape') { _resetIdle(); _end(); }
    }

    /* ── 可見性偵測 ──────────────────────────────────────────── */
    function _isVisible(el) {
        if (!el) return false;
        if (!el.getClientRects || el.getClientRects().length === 0) return false;
        var s = window.getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
    }

    /* ── 步驟導航 ────────────────────────────────────────────── */
    function _showStep(idx) {
        // 找下一個可見步驟
        while (idx < _steps.length) {
            var s = _steps[idx];
            if (!s.sel) break; // 置中卡永遠顯示
            var el = document.querySelector(s.sel);
            if (_isVisible(el)) break;
            idx++;
        }
        if (idx >= _steps.length) { _end(); return; }
        _idx = idx;
        var step = _steps[idx];

        if (step.sel) {
            _positionSpot(document.querySelector(step.sel), step.spot !== undefined ? step.spot : 8);
        } else {
            _positionCenter();
        }
        _renderTip(step, idx);
        _resetIdle();
    }

    function _next() {
        var idx = _idx + 1;
        // 往後找可見步驟
        while (idx < _steps.length) {
            var s = _steps[idx];
            if (!s.sel) break;
            var el = document.querySelector(s.sel);
            if (_isVisible(el)) break;
            idx++;
        }
        _showStep(idx);
    }

    function _prev() {
        if (_idx <= 0) return;
        var idx = _idx - 1;
        while (idx > 0) {
            var s = _steps[idx];
            if (!s.sel) break;
            var el = document.querySelector(s.sel);
            if (_isVisible(el)) break;
            idx--;
        }
        _showStep(idx);
    }

    /* ── 定位：聚光燈 ────────────────────────────────────────── */
    function _positionSpot(el, padding) {
        if (!_isVisible(el)) { _positionCenter(); return; }
        var p = (padding !== undefined && padding !== null) ? padding : 8;

        function _apply() {
            var r = el.getBoundingClientRect();
            _hole.style.left   = (r.left - p) + 'px';
            _hole.style.top    = (r.top  - p) + 'px';
            _hole.style.width  = (r.width  + p * 2) + 'px';
            _hole.style.height = (r.height + p * 2) + 'px';
            _hole.style.display = 'block';
            _positionTip(r);
        }

        // Scroll into view then reposition
        el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        _apply();
        setTimeout(_apply, 380);
    }

    /* ── 定位：置中卡 ────────────────────────────────────────── */
    function _positionCenter() {
        _hole.style.display = 'none';
        _tip.style.transform = 'translate(-50%,-50%)';
        _tip.style.left   = '50%';
        _tip.style.top    = '50%';
        _tip.style.right  = 'auto';
        _tip.style.bottom = 'auto';
        _tip.style.display = 'block';
    }

    /* ── 定位：說明氣泡 ──────────────────────────────────────── */
    function _positionTip(r) {
        _tip.style.transform = '';
        var W = window.innerWidth;
        var H = window.innerHeight;
        var tipH = 200; // 估計高度
        var tipW = Math.min(360, W * 0.92);

        // 上方或下方
        if (r.bottom + tipH + 20 < H) {
            _tip.style.top    = (r.bottom + 16) + 'px';
            _tip.style.bottom = 'auto';
        } else {
            _tip.style.top    = 'auto';
            _tip.style.bottom = (H - r.top + 16) + 'px';
        }

        // 水平對齊：以目標左側對齊，夾在視窗內
        var left = Math.max(8, Math.min(r.left, W - tipW - 8));
        _tip.style.left  = left + 'px';
        _tip.style.right = 'auto';
        _tip.style.display = 'block';
    }

    /* ── 渲染說明氣泡 ────────────────────────────────────────── */
    function _renderTip(step, idx) {
        var total = _steps.length;
        var isFirst = (idx === 0);
        var isLast  = (idx === total - 1);

        // 進度點
        var dots = '';
        var dotLimit = Math.min(total, 20);
        for (var i = 0; i < dotLimit; i++) {
            dots += '<span style="display:inline-block;width:7px;height:7px;border-radius:50%;margin:0 2px;' +
                'background:' + (i === idx ? '#06C755' : '#e2e8f0') + ';transition:background .2s;"></span>';
        }

        _tip.innerHTML =
            (step.title
                ? '<div style="font-size:.7rem;color:#9ca3af;font-weight:700;margin-bottom:5px;letter-spacing:.06em;text-transform:uppercase;">' + _esc(step.title) + '</div>'
                : '') +
            '<p style="margin:0 0 14px;font-size:.91rem;color:#1a202c;line-height:1.68;">' + step.body + '</p>' +
            '<div style="display:flex;align-items:center;gap:8px;">' +
            (!isFirst
                ? '<button id="st-prev-btn" style="background:#f1f5f9;border:none;padding:7px 14px;border-radius:8px;cursor:pointer;font-size:.82rem;color:#475569;flex-shrink:0;">← 上一步</button>'
                : '') +
            '<div style="flex:1;text-align:center;">' + dots + '</div>' +
            '<button id="st-next-btn" style="background:#06C755;color:#fff;border:none;padding:7px 18px;border-radius:8px;cursor:pointer;font-size:.82rem;font-weight:700;flex-shrink:0;">' +
            (isLast ? '完成 ✓' : '下一步 →') + '</button>' +
            '</div>' +
            '<div style="text-align:center;margin-top:8px;">' +
            '<span style="font-size:.7rem;color:#cbd5e1;">' + (idx + 1) + ' / ' + total + '</span>' +
            '<button id="st-skip-btn" style="background:none;border:none;color:#cbd5e1;font-size:.7rem;cursor:pointer;margin-left:10px;text-decoration:underline;">略過導覽</button>' +
            '</div>';

        var nextBtn = document.getElementById('st-next-btn');
        if (nextBtn) nextBtn.addEventListener('click', function () {
            _resetIdle();
            if (isLast) _end(); else _next();
        });
        var prevBtn = document.getElementById('st-prev-btn');
        if (prevBtn) prevBtn.addEventListener('click', function () { _resetIdle(); _prev(); });
        var skipBtn = document.getElementById('st-skip-btn');
        if (skipBtn) skipBtn.addEventListener('click', function () { _end(); });
    }

    function _esc(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    /* ── 閒置計時 ────────────────────────────────────────────── */
    function _resetIdle() {
        _clearIdle();
        var ms = (_opts && _opts.idleMs) ? _opts.idleMs : 22000;
        _idleTimer = setTimeout(function () {
            _end();
            if (typeof showToast === 'function') {
                showToast('導覽已閒置自動結束，點「教學導覽」按鈕可重新開始', 'info');
            }
        }, ms);
    }

    function _clearIdle() {
        if (_idleTimer) { clearTimeout(_idleTimer); _idleTimer = null; }
    }

    /* ── 結束導覽 ────────────────────────────────────────────── */
    function _end() {
        _clearIdle();
        if (_hole)    { _hole.style.display    = 'none'; }
        if (_overlay) { _overlay.style.display = 'none'; }
        if (_tip)     { _tip.style.display     = 'none'; }
        if (_banner)  { _banner.style.display  = 'none'; }

        if (_opts && _opts.key) {
            localStorage.setItem('st_opened_' + _opts.key, '1');
        }

        // 重新顯示啟動按鈕（移除脈動）
        var lb = document.getElementById('tour-btn');
        if (lb) {
            lb.style.display = 'flex';
            lb.classList.remove('tour-pulse');
        }
        var hint = document.getElementById('tour-hint');
        if (hint) hint.style.display = 'none';
    }

    /* ── 公開 API ────────────────────────────────────────────── */
    function start(steps, opts) {
        _steps = steps || [];
        _opts  = opts  || {};
        if (!_steps.length) return;

        _ensureDom();

        _overlay.style.display = 'block';
        _banner.style.display  = 'flex';

        var lb = document.getElementById('tour-btn');
        if (lb) lb.style.display = 'none';

        _showStep(0);
    }

    function auto(key, steps, opts) {
        if (localStorage.getItem('st_opened_' + key)) return;
        opts     = opts || {};
        opts.key = key;
        start(steps, opts);
    }

    function reset(key) {
        localStorage.removeItem('st_opened_' + key);
    }

    return { start: start, auto: auto, reset: reset };
})();
