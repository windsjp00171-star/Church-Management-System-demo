/* 首頁「本週點名」：點名字打勾（呼叫既有的 mark API）；週日第一次打開自動加上今天這一欄。 */
(function () {
  var msg = document.getElementById('rc-msg');
  function say(t) { if (msg) msg.textContent = t || ''; }
  function post(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) {
        return r.json().catch(function () { return { error: '連線失敗' }; }).then(function (j) {
          if (!r.ok || j.error) throw new Error(j.error || '操作失敗');
          return j;
        });
      });
  }
  function paint(btn, on) {
    btn.dataset.on = on ? '1' : '0';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.style.background = on ? '#dcfce7' : '#fff';
    btn.style.borderColor = on ? '#86efac' : '#e5e7eb';
    btn.querySelector('.rc-tick').textContent = on ? '✓' : '';
  }
  function recount() {
    var el = document.getElementById('rc-count');
    if (el) el.textContent = document.querySelectorAll('.rc-chip[data-on="1"]').length;
  }
  function addColumn() {
    return post('/api/roll-call/sheet/add-column', {})
      .then(function () { location.reload(); })
      .catch(function (e) { say(e.message); });
  }
  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest && ev.target.closest('.rc-chip');
    if (!btn || btn.disabled || btn.dataset.busy) return;
    var was = btn.dataset.on === '1', now = !was;
    btn.dataset.busy = '1';
    paint(btn, now); recount();                         // 先畫上去，手指離開就看到結果
    post('/api/roll-call/session/' + btn.dataset.sid + '/mark',
         { member_id: btn.dataset.mid, status: now ? 'present' : 'absent' })
      .then(function () { say(''); })
      .catch(function (e) { paint(btn, was); recount(); say(e.message); })   // 失敗要還原，不能讓畫面說謊
      .then(function () { delete btn.dataset.busy; });
  });
  var start = document.getElementById('rc-start');
  if (start) start.addEventListener('click', addColumn);
  if (window.RC_AUTO_ADD) addColumn();
})();
