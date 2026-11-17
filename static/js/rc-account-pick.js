/* 點名名冊：帳號裡已經有「疑似同一個人」（還沒綁 LINE 的空殼帳號）時，請同工選 ——
 * 是他（連到那個帳號），還是不同人（另外建新帳號）。
 * ★ 系統不用姓名替人決定：猜錯的話，別人的點名紀錄會掛到這個帳號上。
 * ★ 用頁面上的大按鈕，不用瀏覽器的「確定／取消」框：那個框看不出「確定」是哪個意思，
 *   一連串跳出來按錯了也回不去。
 * 回傳 Promise：{link_user_id} / {new_account: true}；按「先不加」回 null（什麼都不做）。 */
function rcPickAccount(name, accounts) {
  return new Promise(resolve => {
    const esc = t => String(t == null ? '' : t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    const wrap = document.createElement('div');
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.setAttribute('aria-label', '是不是同一個人');
    wrap.style.cssText = 'position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;padding:16px;';
    const btn = 'display:block;width:100%;padding:14px;margin-top:10px;border-radius:10px;font-size:1rem;font-weight:700;cursor:pointer;';
    wrap.innerHTML = `<div style="background:#fff;border-radius:14px;padding:20px;max-width:420px;width:100%;">
      <p style="margin:0 0 6px;font-size:1.05rem;font-weight:700;">「${esc(name)}」是不是已經有帳號的這個人？</p>
      <p style="margin:0 0 6px;color:#6b7280;font-size:.9rem;">帳號裡有名字很像、還沒綁 LINE 的帳號。是同一個人就選他，避免同一個人變成兩個。</p>
      ${accounts.map(a => `<button type="button" data-pick="${esc(a.id)}" style="${btn}border:2px solid #16a34a;background:#f0fdf4;color:#15803d;">就是「${esc(a.name)}」<span style="font-weight:400;font-size:.85rem;">（${esc(a.reason)}）</span></button>`).join('')}
      <button type="button" data-pick="new" style="${btn}border:1px solid #c7d2fe;background:#fff;color:#4338ca;">不是，幫「${esc(name)}」另外建新的</button>
      <button type="button" data-pick="" style="${btn}border:0;background:transparent;color:#6b7280;font-weight:400;">先不加</button>
    </div>`;
    const done = v => { wrap.remove(); resolve(v); };
    wrap.addEventListener('click', e => {
      const b = e.target.closest('[data-pick]');
      if (!b) { if (e.target === wrap) done(null); return; }
      const v = b.dataset.pick;
      done(v === 'new' ? { new_account: true } : v ? { link_user_id: v } : null);
    });
    document.addEventListener('keydown', function onKey(e) {
      if (e.key === 'Escape') { document.removeEventListener('keydown', onKey); done(null); }
    });
    document.body.appendChild(wrap);
    const first = wrap.querySelector('[data-pick]');
    if (first) first.focus();
  });
}
