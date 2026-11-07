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
  function norm(t) { return (t || '').normalize('NFKC').toLowerCase().replace(/\s+/g, ''); }
  var search = document.getElementById('rc-search');
  if (search) search.addEventListener('input', function () {
    var q = norm(search.value), shown = 0;
    document.querySelectorAll('.rc-chip').forEach(function (c) {
      var hit = !q || norm(c.dataset.name).indexOf(q) !== -1;
      c.style.display = hit ? '' : 'none';
      if (hit) shown++;
    });
    var none = document.getElementById('rc-none');
    if (none) none.style.display = (q && !shown) ? '' : 'none';
    var nq = document.getElementById('rc-none-q'); if (nq) nq.textContent = search.value.trim();
    var nn = document.getElementById('rc-newname');
    if (nn && q && !shown) nn.value = search.value.trim();      // 找不到就把打的字帶到新朋友欄
  });
  var nb = document.getElementById('rc-newbtn');
  function addNewcomer(confirmed) {
    var name = (document.getElementById('rc-newname').value || '').trim();
    if (!name) { say('請輸入姓名'); return; }
    fetch('/api/roll-call/members/quick-add', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, session_id: nb.dataset.sid || null, confirm: confirmed === true }) })
      .then(function (r) { return r.json().catch(function () { return { error: '連線失敗' }; }).then(function (j) { return [r, j]; }); })
      .then(function (rj) {
        var r = rj[0], j = rj[1];
        if (r.status === 409 && j.data && j.data.similar) {
          if (confirm('名冊裡有「' + j.data.similar + '」，跟「' + name + '」很像。確定是不同的人，要新增嗎？')) addNewcomer(true);
          return;
        }
        if (!r.ok || j.error) { say(j.error || '新增失敗'); return; }
        location.reload();
      });
  }
  if (nb) nb.addEventListener('click', function () { addNewcomer(); });
  var start = document.getElementById('rc-start');
  if (start) start.addEventListener('click', addColumn);
  if (window.RC_AUTO_ADD) addColumn();
})();
