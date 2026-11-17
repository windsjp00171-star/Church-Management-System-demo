/* 點名名冊：帳號裡已經有「疑似同一個人」時，請同工選 —— 是他（連到那個帳號），還是不同人（另外建空殼帳號）。
 * ★ 系統不用姓名替人決定：猜錯的話，別人的點名紀錄會掛到這個帳號上。
 * 回傳要額外送給伺服器的欄位：{link_user_id} / {new_account: true}；同工兩個都取消就回 null（什麼都不做）。 */
function rcPickAccount(name, accounts) {
  for (const a of accounts) {
    const tag = '還沒綁 LINE 的帳號，' + (a.reason || '');
    if (confirm('帳號裡已經有「' + a.name + '」（' + tag + '）。\n\n是同一個人嗎？\n按「確定」＝就是他（連到這個帳號）\n按「取消」＝不是他')) {
      return { link_user_id: a.id };
    }
  }
  if (confirm('都不是的話，要幫「' + name + '」另外建一個新帳號嗎？（之後他自己用 LINE 註冊，管理員可以合併）')) {
    return { new_account: true };
  }
  return null;
}
