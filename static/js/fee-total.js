/* ══════════════════════════════════════════════════════════
   分級收費：報名表單的即時應繳金額

   選項可以帶價格（後台打「成人|800」），前端把有價格的選項渲染成
   data-price。這裡負責把「選了什麼 → 要繳多少」即時算出來。

   ★ 為什麼要按表單分別計算
   同一頁上可能有兩份表單（自己報名 / 幫別人報名），欄位都在 DOM 裡，
   只是其中一份 display:none。整頁一起加總的話會把隱藏那份也算進去 ——
   而且畫面完全正常，只是金額莫名其妙多一倍。

   ★ 條件沒成立的欄位不算
   跳題隱藏的欄位（例如「監護人電話」）會被 evaluateConditions 清空，
   但如果它有標價又剛好還留著選取狀態，就會算到不該算的錢。
   ══════════════════════════════════════════════════════════ */

(function () {
  // 往上找到「包含這些欄位」的那一層，當作這份表單的範圍。
  // 不用寫死的選擇器，是因為三個報名頁的容器結構各自不同，
  // 寫死一個就會有頁面悄悄失效。
  function scopeOf(el) {
    var n = el.parentElement;
    while (n && !n.querySelector('.field-wrapper')) n = n.parentElement;
    return n || document;
  }

  function isHidden(wrapper) {
    return wrapper.style.display === 'none' || wrapper.offsetParent === null;
  }

  window.updateFeeTotal = function () {
    var boxes = document.querySelectorAll('.fee-total');
    for (var b = 0; b < boxes.length; b++) {
      var box = boxes[b];
      var scope = scopeOf(box);
      var total = parseInt(box.dataset.baseFee || '0', 10) || 0;
      var anyPriced = false;

      var wrappers = scope.querySelectorAll('.field-wrapper');
      for (var i = 0; i < wrappers.length; i++) {
        var w = wrappers[i];
        if (w.querySelector('[data-price]') || w.querySelector('.auto-tier')) anyPriced = true;
        if (isHidden(w)) continue;

        // radio / checkbox
        var checked = w.querySelectorAll('input[data-price]:checked');
        for (var j = 0; j < checked.length; j++) {
          total += parseInt(checked[j].dataset.price, 10) || 0;
        }
        // ★ 依生日自動判定的身分別：答案在隱藏欄位上，不是 :checked 的 radio。
        //   漏掉的話身分別顯示得好好的、金額卻永遠是 0 ——
        //   而那個人會照著畫面上的 $0 出門。
        var auto = w.querySelectorAll('.at-hidden[data-price]');
        for (var a = 0; a < auto.length; a++) {
          if (!auto[a].value) continue;      // 還沒算出來就不計
          total += parseInt(auto[a].dataset.price, 10) || 0;
        }
        // select
        var sels = w.querySelectorAll('select');
        for (var k = 0; k < sels.length; k++) {
          var opt = sels[k].options[sels[k].selectedIndex];
          if (opt && opt.dataset.price !== undefined) {
            total += parseInt(opt.dataset.price, 10) || 0;
          }
        }
      }

      // 沒有任何標價欄位就整列不出現 —— 不收費的活動不該看到「應繳 $0」
      box.style.display = anyPriced ? 'flex' : 'none';
      var val = box.querySelector('.fee-total-val');
      if (val) val.textContent = '$' + total;
    }
  };

  // 首次載入也要算一次：有預選值、或只有基本費用的情況
  document.addEventListener('DOMContentLoaded', window.updateFeeTotal);
})();

/* ══════════════════════════════════════════════════════════
   出生日期：收民國年，存西元

   台灣人多半記得民國年而不是西元年 —— 尤其長輩，問他西元幾年出生
   多半要現場算一次。所以輸入框收的是民國。

   ★ 但存進去的一定是西元（那個 hidden input）。
     民國是顯示格式不是資料：存成民國的話，之後每次算年齡、排序、
     或換一家保險公司改格式，都得先反轉一次；而且輸入端一定會出現
     有人填 111、有人填 民國111、有人填 2022。

   ★ 年份欄兩種都吃，不必問使用者。
     1~今年的民國年 → 民國；1912~今年 → 西元。
     兩個範圍不重疊（民國 1912 年是西元 3823 年），所以沒有一個數字
     同時說得通兩種解讀。「請選擇你要填西元還是民國」那種問法本身
     就會卡住人。

   規則要跟後端 routes/roc.py 的 normalize_year 一致。
   ══════════════════════════════════════════════════════════ */
(function () {
  var ROC_OFFSET = 1911;

  function thisYear() {
    // 台灣時間。用 UTC 的話台灣早上 8 點前會少一年，
    // 剛好今年出生的人（不會有）以及跨年那一刻會怪怪的。
    var now = new Date();
    return new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60000).getFullYear();
  }

  // 回西元年，認不出來回 null
  window.normalizeRocYear = function (raw) {
    var y = parseInt(String(raw == null ? '' : raw).trim(), 10);
    if (!isFinite(y)) return null;
    var ty = thisYear();
    if (y >= 1 && y <= ty - ROC_OFFSET) return y + ROC_OFFSET;   // 民國
    if (y >= ROC_OFFSET + 1 && y <= ty) return y;                // 西元
    return null;
  };

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  window.syncRocDate = function (el) {
    var box = el.closest('.roc-date');
    if (!box) return;
    var wrapper = box.parentElement;
    var iso = box.querySelector('.roc-iso');
    var hint = wrapper && wrapper.querySelector('.roc-hint');

    var rawY = box.querySelector('.roc-y').value;
    var y = window.normalizeRocYear(rawY);
    var m = parseInt(box.querySelector('.roc-m').value, 10);
    var d = parseInt(box.querySelector('.roc-d').value, 10);

    function fail(msg) {
      iso.value = '';                       // ★ 湊不出來就留空，不要送一個猜的日期出去
      // 生日不成立就沒有年齡 —— 自動判定要跟著退回「算不出來」，
      // 不能停在上一次算好的身分別（那會變成用舊生日的答案送出）
      if (typeof refreshAutoTiers === 'function') refreshAutoTiers();
      // 年齡條件跟身分別讀的是同一個生日 —— 漏掉這行的話，
      // 身分別會跟著生日變，而「未滿18歲才問監護人」那題不會動。
      if (typeof refreshAgeConditions === 'function') refreshAgeConditions();
      if (hint) {
        hint.textContent = msg || '';
        hint.style.color = msg ? 'var(--danger, #a8261e)' : '';
      }
    }

    if (!rawY && !box.querySelector('.roc-m').value && !box.querySelector('.roc-d').value) {
      return fail('');                      // 還沒開始填，不要罵人
    }
    if (y === null) return fail('年份看起來不對，請填民國年（例如 88）');
    if (!(m >= 1 && m <= 12)) return fail('月份要在 1～12 之間');
    if (!(d >= 1 && d <= 31)) return fail('日期要在 1～31 之間');

    // 2/30、平年的 2/29 這種：JS 的 Date 會自動跳到下個月，用這點反查
    var dt = new Date(y, m - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) {
      return fail('這一天不存在，請確認');
    }
    if (dt > new Date()) return fail('出生日期不能是未來');

    iso.value = y + '-' + pad(m) + '-' + pad(d);
    // ★ 生日填好了 → 重算身分別。少了這行，身分別永遠停在
    //   「請先填寫出生日期」，而生日明明就填好了。
    if (typeof refreshAutoTiers === 'function') refreshAutoTiers();
    if (typeof refreshAgeConditions === 'function') refreshAgeConditions();
    if (hint) {
      hint.style.color = '';
      // 回顯西元 —— 填的人自己確認有沒有被理解錯（尤其直接填西元的人）
      hint.textContent = '＝ 西元 ' + y + ' 年 ' + m + ' 月 ' + d + ' 日';
    }
  };

  /* ── 監護人：姓名＋電話 → 一格 ──────────────────────────
   *
   * ★ 格式（姓名／電話）跟 routes/guardian.py 是同一套。這裡負責畫面，
   *   伺服器收到之後會再正規化一次覆蓋掉 —— 所以就算這裡寫錯，
   *   存進資料庫的東西也不會是壞格式（跟 auto_tier 同一個做法）。
   *
   * ★ 分隔符號要從輸入裡拿掉。名字裡有一個斜線就會把電話切錯位置，
   *   而名冊上看起來只是那個人的電話怪怪的。
   */
  var GD_SEP = '／';

  function gdClean(v) {
    return String(v == null ? '' : v)
      .replace(/／/g, '').replace(/\//g, '')
      .replace(/\s+/g, ' ').trim();
  }

  window.guardianCompose = function (name, phone) {
    name = gdClean(name);
    phone = gdClean(phone);
    if (!name && !phone) return '';
    return name + GD_SEP + phone;
  };

  window.guardianParse = function (value) {
    var text = String(value == null ? '' : value).trim();
    if (!text) return ['', ''];
    var i = text.lastIndexOf(GD_SEP);
    if (i === -1) return [text, ''];      // 舊資料：整串當姓名，不要猜
    return [text.slice(0, i).trim(), text.slice(i + GD_SEP.length).trim()];
  };

  /** ★ 姓名和電話都要有才算填了（＝ routes/guardian.is_complete） */
  window.guardianIsComplete = function (value) {
    var parts = window.guardianParse(value);
    return !!(parts[0] && parts[1]);
  };

  window.syncGuardian = function (el) {
    var box = el.closest('.guardian-field');
    if (!box) return;
    var name = box.querySelector('.gd-name');
    var phone = box.querySelector('.gd-phone');
    var hidden = box.querySelector('.gd-value');
    var hint = box.querySelector('.gd-hint');
    var value = window.guardianCompose(name && name.value, phone && phone.value);
    if (hidden) hidden.value = value;
    // 只填一半的時候當場講，不要等按了送出才說「還沒填」——
    // 那時候他會以為是系統沒收到，因為兩個框裡明明有字
    if (hint) {
      var half = value !== '' && !window.guardianIsComplete(value);
      hint.style.display = half ? 'block' : 'none';
    }
    if (typeof evaluateConditions === 'function') evaluateConditions();
  };

  /* 有預填值（編輯既有報名）時把三個民國框填回去。
   *
   * ★ 為什麼要有這一步：送出的值在隱藏的 .roc-iso 上，畫面上那三個框
   *   **沒有 data-field-id** —— 所有「照 data-field-id 回填」的程式碼
   *   都碰不到它們。漏掉的話，有生日的人打開來三格是空的，
   *   看起來像他根本沒填過。
   *
   * ★ 為什麼是一支可以重複呼叫的函式，不是只掛 DOMContentLoaded：
   *   後台的「編輯報名資料」彈窗是**每次打開**才換一個人的答案，
   *   載入時跑一次蓋不到它。
   *
   * ★ 為什麼沒有 iso 值時要**清空**而不是跳過：同一個彈窗會輪流顯示
   *   不同的人。跳過的話，換一個沒填生日的人打開，上一位的生日還留在
   *   框裡，而隱藏的 .roc-iso 已經換人了 —— 畫面講的是別人的生日，
   *   而且不會有任何錯誤。
   */
  window.prefillRocDates = function (root) {
    var boxes = (root || document).querySelectorAll('.roc-date');
    for (var i = 0; i < boxes.length; i++) {
      var iso = boxes[i].querySelector('.roc-iso');
      var m = iso && /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.value);
      boxes[i].querySelector('.roc-y').value = m ? parseInt(m[1], 10) - ROC_OFFSET : '';
      boxes[i].querySelector('.roc-m').value = m ? parseInt(m[2], 10) : '';
      boxes[i].querySelector('.roc-d').value = m ? parseInt(m[3], 10) : '';
      // 順便重算 .roc-iso 和西元回顯。存了爛格式的舊資料會在這裡當場
      // 變成空白＋提示，而不是被原封不動存回去。
      window.syncRocDate(boxes[i].querySelector('.roc-y'));
    }
  };

  document.addEventListener('DOMContentLoaded', function () {
    window.prefillRocDates(document);
  });
})();

/* ══════════════════════════════════════════════════════════
   身分證字號：即時檢查

   保險名冊要這個，而**打錯一個字的後果是那個人根本沒被保到** ——
   不會有任何徵兆，要出事那一刻才發現。

   證號內建一位檢查碼，隨手打錯一個數字有九成會被算出來。這是少數
   「能在輸入當下就擋掉」的錯誤，不用它太可惜。

   ★ 規則要跟後端 routes/tw_id.py 一致。兩邊不一致的話，前端說「格式
     正確」但後端擋下來（或反過來）—— 而使用者只會看到送不出去。
   ══════════════════════════════════════════════════════════ */
(function () {
  // 內政部的字母對照表。不是規律的（I/O/W/X/Y/Z 特別跳號），
  // 不要「順手改成連續」。
  var L = {A:10,B:11,C:12,D:13,E:14,F:15,G:16,H:17,I:34,J:18,K:19,L:20,M:21,
           N:22,O:35,P:23,Q:24,R:25,S:26,T:27,U:28,V:29,W:32,X:30,Y:31,Z:33};
  var WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 1];

  window.normalizeTwId = function (v) {
    return String(v == null ? '' : v).replace(/\s+/g, '').toUpperCase();
  };

  window.isValidTwId = function (v) {
    var s = window.normalizeTwId(v);
    var second;
    if (/^[A-Z][1289]\d{8}$/.test(s)) {
      second = parseInt(s[1], 10);
    } else if (/^[A-Z][A-D]\d{8}$/.test(s)) {
      second = L[s[1]] % 10;              // 舊式居留證：第 2 碼是英文字母
    } else {
      return false;
    }
    var first = L[s[0]];
    if (first === undefined) return false;

    var total = Math.floor(first / 10) + (first % 10) * 9 + second * WEIGHTS[0];
    // ★ 只跑到 i=8。WEIGHTS 只有 8 個元素（索引 0–7），跑到 i=9 會拿到
    //   undefined → 整個和變 NaN → 所有號碼都被判成無效；而且 s[9] 會被
    //   算兩次。第一版就是這樣，1000 組隨機交叉比對抓到 48 組跟後端不一致。
    for (var i = 2; i <= 8; i++) total += parseInt(s[i], 10) * WEIGHTS[i - 1];
    total += parseInt(s[9], 10);          // 檢查碼本身，權重 1
    return total % 10 === 0;
  };

  window.checkTwId = function (input) {
    var hint = input.parentElement && input.parentElement.querySelector('.id-hint');
    var v = window.normalizeTwId(input.value);
    if (input.value !== v) input.value = v;      // 小寫、空白就地整理掉

    if (!hint) return;
    if (!v) {                                    // 還沒開始填，不要罵人
      hint.textContent = '';
      input.style.borderColor = '';
      return;
    }
    if (window.isValidTwId(v)) {
      hint.textContent = '✓ 格式正確';
      hint.style.color = 'var(--green-ink, var(--green-ink, #1a5e3e))';
      input.style.borderColor = 'var(--green-border, var(--green-border, #c6dccd))';
    } else if (v.length < 10) {
      hint.textContent = '還差 ' + (10 - v.length) + ' 碼';
      hint.style.color = 'var(--text-4, #5f655f)';
      input.style.borderColor = '';
    } else if (v.length > 10) {
      // 貼上時常見。講「檢查碼不對」會讓人去核對號碼本身，找錯方向。
      hint.textContent = '太長了，身分證字號是 10 碼';
      hint.style.color = 'var(--danger, #a8261e)';
      input.style.borderColor = 'var(--danger-border, #f0c7c3)';
    } else {
      // ★ 講「檢查碼不對」而不是「格式錯誤」—— 格式看起來明明是對的，
      //   只說格式錯會讓人一直盯著看不出問題在哪。
      hint.textContent = '這組號碼的檢查碼不對，請再核對一次';
      hint.style.color = 'var(--danger, #a8261e)';
      input.style.borderColor = 'var(--danger-border, #f0c7c3)';
    }
  };

  document.addEventListener('DOMContentLoaded', function () {
    var els = document.querySelectorAll('.id-input');
    for (var i = 0; i < els.length; i++) if (els[i].value) window.checkTwId(els[i]);
  });
})();
