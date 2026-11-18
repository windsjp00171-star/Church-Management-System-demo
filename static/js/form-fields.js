/* ══════════════════════════════════════════════════════════
   報名表單：讀答案、必填檢查、跳題條件 —— 三個入口共用這一份

   ## 為什麼一定要共用

   同一套表單有三個入口：會員報名（event_detail）、幫別人報名（同一頁的
   第二份表單）、外部報名（external_register）。原本每一份各寫各的，
   於是它們**已經長得不一樣了**，而且是靜靜地不一樣：

     ✗ 外部報名的收值只認 radio，不認 fee
       → 選了「成人 $800」，收到的答案是空字串
       → 必填檢查也一樣漏，於是永遠跳「請填寫所有必填欄位」，送不出去
       → 但右邊的應繳金額照樣顯示 $800，畫面完全正常
       （分級收費就是帶價格的單選，DOM 長得一模一樣，只有 data-field-type 不同）

     ✗ 外部報名的跳題用 cond.trigger_field_id 找觸發問題，
       但後台存進 condition_json 的只有 trigger_sort_order
       → 永遠找不到 → 整個跳題不生效 → 該藏的欄位一直露著
       → 而且它還是必填，於是又多擋一道

   兩個 bug 疊起來的結果：那場活動的外部報名根本報不了名，
   而使用者看到的只是「我明明都填了，它說我沒填」。

   ★ 所以這裡的規則是：**收值、必填、跳題只准有一份實作。**
     有測試在守（tests/test_form_fields.py），新的入口也要用這一份。

   ## 後台的預覽表單也用這一份

   「預覽」要能被信任，唯一的方法是它跑的就是報名者在跑的程式。
   自己另外寫一份的話，預覽會certify一個不存在的行為 ——
   那比沒有預覽更糟。
   ══════════════════════════════════════════════════════════ */

(function () {

  /** 這個欄位目前的答案（字串）。空字串＝沒填。 */
  window.getWrapperValue = function (wrapper) {
    if (!wrapper) return '';
    var type = wrapper.dataset.fieldType || 'text';

    // ★ 開了「依生日自動判定」的收費欄位沒有 radio，答案在隱藏欄位裡。
    //   這一段要排在 fee 分支之前 —— 不然會去找不存在的 radio，回空字串，
    //   而畫面上身分別顯示得好好的。
    var auto = wrapper.querySelector('.auto-tier .at-hidden');
    if (auto) return auto.value.trim();

    // ★ fee（分級收費）就是帶價格的單選，收值跟 radio 完全一樣。
    //   漏掉它會落到最後那個「找 input[data-field-id]」的分支，
    //   而 radio 沒有那個屬性 → 回空字串 → 這一題的答案永遠送不出去，
    //   畫面上卻選得到、看得見選中。
    if (type === 'radio' || type === 'fee') {
      var checked = wrapper.querySelector('input[type="radio"]:checked');
      if (!checked) return '';
      if (checked.value === '__other__') {
        var t = checked.closest('label');
        t = t && t.querySelector('.other-text');
        var v = t ? t.value.trim() : '';
        return v ? '其他：' + v : '其他';
      }
      return checked.value;
    }

    if (type === 'checkbox') {
      var boxes = wrapper.querySelectorAll('input[type="checkbox"]:checked');
      var out = [];
      for (var i = 0; i < boxes.length; i++) {
        var c = boxes[i];
        if (c.value === '__other__') {
          var lbl = c.closest('label');
          var ot = lbl && lbl.querySelector('.other-text');
          var ov = ot ? ot.value.trim() : '';
          if (ov) out.push('其他：' + ov);
        } else {
          out.push(c.value);
        }
      }
      return out.join('、');
    }

    // text / textarea / select / number / date / birthday / id_number
    // （birthday 的西元值在隱藏的 .roc-iso 上，它帶 data-field-id）
    var input = wrapper.querySelector(
      'select[data-field-id], input[data-field-id], textarea[data-field-id]'
    );
    return input ? input.value.trim() : '';
  };

  /** 必填有沒有填。★ 一定要走 getWrapperValue —— 另外寫一套判斷
      就是外部報名那個「選了卻說沒選」的來源。 */
  window.isFieldFilled = function (wrapper) {
    var value = window.getWrapperValue(wrapper);
    if (value === '') return false;
    // ★ 監護人只填一半等於沒填 —— 出事那天光有名字打不到人。
    //   這條規則跟伺服器的 routes/guardian.is_complete 是同一條；
    //   兩邊不一致的話，使用者會在畫面上看到「填好了」卻被伺服器擋下來，
    //   而錯誤訊息指著一個他覺得已經填完的欄位。
    if ((wrapper.dataset.fieldType || '') === 'guardian') {
      return window.guardianIsComplete(value);
    }
    return true;
  };

  /** 「其他（請填寫）」的文字框開合。
   *
   * ★ 這支原本**只定義在 external_register.html 裡**，而 event_detail.html
   *   （會員報名／幫別人報名兩份表單）也在 onchange 呼叫它 ——
   *   於是會員報名頁每次點「其他」都是 ReferenceError，文字框永遠不出現。
   *
   *   沒有人回報，因為畫面完全正常：那個選項選得到、看得見選中，
   *   只是旁邊該冒出來的輸入框沒有。使用者會以為「其他」就是不用填。
   *   而送出時 getWrapperValue 收到的是「其他」兩個字，名冊上就是「其他」——
   *   看起來像那個人真的只想填「其他」。
   *
   *   收進這裡的理由跟收值／必填／跳題一樣：**只准有一份**。
   */
  window.toggleOtherText = function (el) {
    var label = el && el.closest ? el.closest('label') : null;
    var box = label && label.querySelector('.other-text');
    if (!box) return;
    box.style.display = el.checked ? 'block' : 'none';
  };

  /** 一整個範圍裡的「其他」文字框都重算一次開合。
   *  預覽是整塊重畫的，沒有 onchange 可以掛，所以需要這個。 */
  window.syncOtherTexts = function (root) {
    (root || document).querySelectorAll('.other-text').forEach(function (t) {
      var label = t.closest('label');
      var box = label && label.querySelector('input[type=radio],input[type=checkbox]');
      t.style.display = box && box.checked ? 'block' : 'none';
    });
  };

  /** 這個 wrapper 現在看得見嗎（跳題藏起來的不算） */
  window.isFieldVisible = function (wrapper) {
    return wrapper.style.display !== 'none' && wrapper.offsetParent !== null;
  };

  function wrappersIn(root) {
    return Array.prototype.slice.call(
      (root || document).querySelectorAll('.field-wrapper'));
  }
  window.fieldWrappers = wrappersIn;

  /** cond.min/max 有沒有設（0 是有效的下限，不能用 falsy 判斷） */
  function bound(v) {
    return (v === null || v === undefined || v === '') ? null : Number(v);
  }

  /** 年齡條件成不成立。
   *
   * 年齡不是在這裡算的 —— 它由 /compute-age 算完寫在生日欄位的
   * dataset.age 上（見這支檔案下半部的 refreshAgeConditions）。
   *
   * ★ 算不出來（還沒填生日、網路失敗）一律回 false，也就是「不顯示」。
   *   反過來預設顯示的話，一個還不知道年齡的人會看到「未成年監護人」
   *   這一題並且被要求填 —— 而他可能根本是成年人。
   */
  function ageMatches(trigger, cond) {
    var raw = trigger.dataset.age;
    if (raw === undefined || raw === '') return false;
    var age = parseInt(raw, 10);
    if (isNaN(age)) return false;
    var lo = bound(cond.min), hi = bound(cond.max);
    // 上下限都沒設 ＝ 條件沒設定完。這時候「符合任何年齡」是最糟的
    // 解讀：那題會對所有人跳出來，而後台看起來只是兩個空格。
    if (lo === null && hi === null) return false;
    if (lo !== null && age < lo) return false;
    if (hi !== null && age > hi) return false;
    return true;
  }

  /** 依 condition_json 顯示／隱藏欄位。
   *
   * 兩種形狀：
   *   {trigger_sort_order, trigger_value}                  ← 比答案文字
   *   {trigger_sort_order, op:'age_between', min, max}     ← 比年齡
   *
   * 也接受舊資料可能有的 trigger_field_id —— 只認一種的話，另一種格式
   * 會靜靜地整個跳題失效（外部報名就是這樣壞了很久）。
   */
  window.evaluateConditions = function (root) {
    var all = wrappersIn(root);
    all.forEach(function (wrapper) {
      var condStr = wrapper.dataset.condition;
      if (!condStr) return;
      var cond;
      try { cond = JSON.parse(condStr); } catch (e) { return; }
      if (!cond) return;
      // ★ 「每個人都問」（後台在監護人那一題勾的，存成 {auto:'everyone'}）。
      //   它沒有 trigger，所以下面那個 guard 本來就會 return（＝維持顯示），
      //   結果是對的 —— 但那是**靠壞掉時的預設行為剛好正確**。
      //   寫成明確的一條，收緊那個預設時才不會把這一題安靜地弄不見。
      //   伺服器那邊有一模一樣的分支（routes/conditions._is_visible）。
      if (cond.auto === 'everyone') { wrapper.style.display = 'block'; return; }
      var isAge = cond.op === 'age_between';
      // ★ 這個 guard 要認得 age 條件。只擋 trigger_value 的話，
      //   年齡條件（本來就沒有 trigger_value）會在這裡整批被跳過 ——
      //   那題就變成永遠顯示，而後台設定看起來完全正常。
      if (!isAge && !cond.trigger_value) return;

      var trigger = null;
      if (cond.trigger_sort_order !== undefined && cond.trigger_sort_order !== null) {
        trigger = all.filter(function (w) {
          return String(w.dataset.sortOrder) === String(cond.trigger_sort_order);
        })[0];
      }
      if (!trigger && cond.trigger_field_id) {
        trigger = all.filter(function (w) {
          return w.dataset.fieldId === cond.trigger_field_id;
        })[0];
      }
      if (!trigger) return;

      var matched = isAge ? ageMatches(trigger, cond)
                          : window.getWrapperValue(trigger) === cond.trigger_value;
      wrapper.style.display = matched ? 'block' : 'none';

      // ★ 「還不知道年齡」不等於「條件不成立」。
      //
      //   年齡要等 /compute-age 回來才有，而 prefillFields（修改報名）是
      //   同步跑完的 —— 這時候年齡一定還是空的。當成不成立去清空的話，
      //   剛剛填回去的監護人答案會在使用者眼前被清掉，然後那題再冒出來
      //   變成空白，看起來像他自己沒填過。
      //
      //   所以：藏，但不清。等年齡回來再判一次，真的不成立那時才清。
      //   （這期間就算答案還在，collectFieldAnswers 也不會收看不見的欄位，
      //     所以不會送出使用者看不到的答案。）
      var ageUnknown = isAge &&
        (trigger.dataset.age === undefined || trigger.dataset.age === '');

      // 藏起來就清空 —— 留著的話那個答案還是會被送出（而且可能還帶價格），
      // 送出去的是一個使用者早就看不到的選擇。
      if (!matched && !ageUnknown) window.clearWrapper(wrapper);
    });
  };

  /** 把一格清乾淨（畫面上的、隱藏的、提示的，全部）。
   *
   * ★★ 兩個地方需要「清空一格」，而且**必須一模一樣**：
   *
   *   1. 跳題把它藏起來 —— 留著的話那個答案還是會被送出（而且可能
   *      還帶價格），送出去的是一個使用者早就看不到的選擇
   *   2. 後台編輯彈窗換一個人 —— 那個彈窗是**重複使用**的，
   *      不清的話上一位的答案會留在畫面上，而它旁邊那些已經換成
   *      這一位了。整格看起來完全正常，只是有一半是別人的資料。
   *
   * ★ 難就難在「畫面上的元素多半沒有 data-field-id」：生日真正送出的是
   *   隱藏的 .roc-iso，畫面上是三個民國年月日的框；監護人送出的是
   *   .gd-value，畫面上是姓名和電話兩格；自動判定的結果顯示在 .at-value。
   *   只清帶 data-field-id 的東西，等於**只清掉真的那一半** ——
   *   螢幕上寫著民國88年3月5日、送出的答案卻是空字串。
   */
  window.clearWrapper = function (wrapper) {
    wrapper.querySelectorAll('input[type="radio"], input[type="checkbox"]')
      .forEach(function (i) { i.checked = false; });
    wrapper.querySelectorAll('.other-text')
      .forEach(function (t) { t.value = ''; t.style.display = 'none'; });
    wrapper.querySelectorAll('[data-field-id]')
      .forEach(function (inp) { inp.value = ''; inp.style.borderColor = ''; });
    wrapper.querySelectorAll('.roc-y, .roc-m, .roc-d')
      .forEach(function (i) { i.value = ''; });
    wrapper.querySelectorAll('.gd-name, .gd-phone')
      .forEach(function (i) { i.value = ''; });
    wrapper.querySelectorAll('.gd-hint')
      .forEach(function (h) { h.style.display = 'none'; });
    wrapper.querySelectorAll('.roc-hint')
      .forEach(function (h) { h.textContent = ''; h.style.color = ''; });
    wrapper.querySelectorAll('.id-hint')
      .forEach(function (h) { h.textContent = ''; h.style.color = ''; });
    wrapper.querySelectorAll('.auto-tier').forEach(function (box) {
      if (typeof window.resetAutoTierDisplay === 'function') {
        window.resetAutoTierDisplay(box);
      }
    });
    // 生日被清掉 → 它算出來的年齡也不再成立，不能留著給別人比
    delete wrapper.dataset.age;
    // 之前被標紅的必填框，再出現時不該還紅著
    wrapper.style.outline = '';
  };

  /** 整份表單清乾淨。★ 後台編輯彈窗換一個人時一定要先跑這個 ——
   *  prefillFields 只填**有答案的**欄位，沒有的它會跳過（不是清空）。 */
  window.resetFields = function (root) {
    wrappersIn(root).forEach(window.clearWrapper);
  };

  /** 一份表單的所有答案：[{field_id, answer}]。看不見的欄位不收。 */
  window.collectFieldAnswers = function (root) {
    var out = [];
    wrappersIn(root).forEach(function (w) {
      if (!w.dataset.fieldId) return;
      if (!window.isFieldVisible(w)) return;
      out.push({ field_id: w.dataset.fieldId, answer: window.getWrapperValue(w) });
    });
    return out;
  };

  /** 這一格的欄位名稱（不含「必填」標記）。
   *
   * ★ 兩個地方會把欄位名稱印給報名者看：確認頁的摘要、必填沒填的錯誤訊息。
   *   兩邊本來各自寫 `label.textContent.replace('*','')` —— 那只對
   *   「標記剛好是一顆星號」成立。標記改成「必填」兩個字之後，
   *   兩邊會同時變成「參加者姓名 必填」「請填寫：出生日期 必填」。
   *
   *   而那**看起來不像壞掉**，只像有人中文沒寫好，所以不會有人回報。
   *   所以這件事只留一份實作，標記長什麼樣只有這裡知道。
   */
  window.fieldLabelText = function (wrapper) {
    var label = wrapper && wrapper.querySelector('.field-label, label');
    if (!label) return '';
    var copy = label.cloneNode(true);
    var tags = copy.querySelectorAll('.req-tag');
    for (var i = 0; i < tags.length; i++) tags[i].remove();
    return copy.textContent.trim();
  };

  /** 沒填的必填欄位（看得見的才算）。回 [欄位名稱]。 */
  window.missingRequiredFields = function (root) {
    var missing = [];
    wrappersIn(root).forEach(function (w) {
      if (w.dataset.required !== 'true') return;
      if (!window.isFieldVisible(w)) return;
      if (window.isFieldFilled(w)) return;
      missing.push(window.fieldLabelText(w) || '必填欄位');
    });
    return missing;
  };

})();

/* ══════════════════════════════════════════════════════════
   依生日自動判定身分別

   ★ 身分別**不是在這裡算的**。把生日丟給 /event/<id>/compute-tier，
     伺服器用 routes/auto_tier.py 算完回傳。

     前端自己算一份的話，兩份會開始各自演化 —— 而症狀是
     「畫面說成人、存進去卻是敬老」，兩邊都看起來完全正常。
     這個專案已經被這一類咬過好幾次（收值、跳題條件各寫一份）。
   ══════════════════════════════════════════════════════════ */
(function () {

  function currentBirthday(root) {
    // 生日欄位存的是西元（隱藏的 .roc-iso），畫面上填的是民國
    var el = (root || document).querySelector('.roc-iso');
    return el && el.value ? el.value : '';
  }

  var pending = null;

  /** 要打哪一支、送什麼。★ 只有「設定從哪裡來」不同 ——
   *  身分別怎麼算永遠是伺服器的 routes/auto_tier.resolve 那一份。
   *
   *  報名頁：活動存在資料庫裡 → /event/<id>/compute-tier
   *  後台預覽：活動可能還沒存、或設定改了還沒存 → 把草稿設定送上去。
   *    共用前者的話，預覽算的是**舊設定**而畫面完全正常 ——
   *    預覽 certify 一個不存在的行為，比沒有預覽更糟。
   */
  function tierRequest(birthday, specials) {
    var eventId = (window.APP_CONFIG && window.APP_CONFIG.eventId) ||
                  (document.body && document.body.dataset.eventId) || '';
    if (eventId) {
      return { url: '/event/' + eventId + '/compute-tier',
               body: { birthday: birthday, specials: specials } };
    }
    if (typeof window.previewTierPayload === 'function') {
      var payload = window.previewTierPayload(birthday, specials);
      if (payload) return { url: '/admin/events/preview-tier', body: payload };
    }
    return null;
  }

  window.refreshAutoTiers = function (root) {
    var scope = root || document;
    var boxes = scope.querySelectorAll('.auto-tier');
    if (!boxes.length) return;

    var birthday = currentBirthday(scope);
    var specials = {};
    for (var i = 0; i < boxes.length; i++) {
      var b = boxes[i];
      var sp = b.querySelector('.at-special');
      specials[b.dataset.atField] = !!(sp && sp.checked);
    }

    var req = tierRequest(birthday, specials);
    if (!req) return;

    // 沒填生日就不用問伺服器 —— 直接顯示「請先填生日」
    if (!birthday) {
      for (var j = 0; j < boxes.length; j++) applyTier(boxes[j], null);
      return;
    }

    clearTimeout(pending);
    pending = setTimeout(function () {
      fetch(req.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var tiers = (d && d.tiers) || {};
          var rules = (d && d.rules) || {};
          for (var k = 0; k < boxes.length; k++) {
            applyTier(boxes[k], tiers[boxes[k].dataset.atField]);
            // 「判定方式」那句話：報名頁是伺服器渲染好的，預覽沒有，
            // 所以由回應帶上來填。兩邊都走同一支 auto_tier.describe。
            var rule = boxes[k].querySelector('.at-rules');
            if (rule && rules[boxes[k].dataset.atField]) {
              rule.textContent = '判定方式：' + rules[boxes[k].dataset.atField]
                                 + '（以活動當日的年齡計算）';
              rule.style.display = '';
            }
          }
          if (typeof updateFeeTotal === 'function') updateFeeTotal();
          if (typeof evaluateConditions === 'function') evaluateConditions();
        })
        .catch(function () {
          // 連不上就維持「算不出來」的狀態 —— 不要留一個看起來算好了
          // 但其實是舊值的畫面
          for (var m = 0; m < boxes.length; m++) applyTier(boxes[m], null);
        });
    }, 250);
  };

  // 給 evaluateConditions 用：欄位被藏起來時要把顯示格一起退回「算不出來」。
  // 不退的話，畫面上還寫著「國小以下孩童 $500」，而隱藏的答案已經空了。
  window.resetAutoTierDisplay = function (box) { applyTier(box, null); };

  function applyTier(box, tier) {
    var valueEl = box.querySelector('.at-value');
    var priceEl = box.querySelector('.at-price');
    var noteEl = box.querySelector('.at-note');
    var cheapEl = box.querySelector('.at-cheaper');
    var hidden = box.querySelector('.at-hidden');
    var label = tier && tier.label;

    // ★ 「你勾的那一項比較貴，系統讓開了」—— 句子是伺服器組的
    //   （auto_tier.decide），這裡只負責顯示。不顯示的話，
    //   他勾了那一格什麼都沒變，看起來像勾選框壞了。
    if (cheapEl) {
      var why = (tier && tier.note) || '';
      cheapEl.textContent = why;
      cheapEl.style.display = why ? 'block' : 'none';
    }

    valueEl.textContent = label || '—';
    // ★ data-price 是 fee-total.js 讀的 —— 沒有它，金額永遠是 0，
    //   而畫面上身分別顯示得好好的
    if (label && tier.price !== null && tier.price !== undefined) {
      priceEl.textContent = '$' + tier.price;
      hidden.dataset.price = tier.price;
    } else {
      priceEl.textContent = '';
      delete hidden.dataset.price;
    }
    hidden.value = label || '';
    if (noteEl) {
      noteEl.style.display = label ? 'none' : 'block';
      if (!label && tier && tier.age !== null && tier.age !== undefined) {
        // 生日填了、年齡也算出來了，卻對不到任何身分別 —— 那是設定沒接好，
        // 一定要講出來，不然報名者只看到一個「—」不知道發生什麼事
        // 欄位名稱從 DOM 拿 —— 寫死「身分別」的話，欄位叫「票種」時
        // 這句錯誤訊息會講一個報名者沒看過的詞
        var what = box.dataset.fieldLabel || '項目';
        noteEl.textContent = '算出來是 ' + tier.age + ' 歲，但對不到任何'
                           + what + '，請聯絡教會行政。';
      } else if (!label) {
        noteEl.textContent = '請先填寫上面的出生日期，系統會自動判定。';
      }
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (document.querySelector('.auto-tier')) window.refreshAutoTiers();
  });
})();

/* ══════════════════════════════════════════════════════════
   依年齡的跳題條件（「未滿18歲才問監護人」）

   ## 為什麼不用「分級收費 + 自動判定」轉一手就好

   因為兩條界線的來源不一樣。收費分級的界線是收費決定的（例如 12 歲），
   監護人的界線是法律決定的（18 歲）。綁在一起等於強迫收費表為了一個
   跟收費無關的需求多切一刀。

   ## 為什麼不乾脆多問一題「成人／兒童」

   那題問的是系統已經知道的答案 —— 生日就在上面。多問一次唯一的新增
   結果是「生日說 15 歲、單選勾了成人」，於是監護人欄位不出現，名冊上
   那個人未成年而沒有監護人資料，**而且沒有任何地方會紅**。
   跟 auto_tier 的理由一樣：算得出來的就不要問，判斷正是出錯的地方。

   ## 年齡一樣由伺服器算

   打 /compute-age（同一支 routes/roc.age_on，跟身分別用的一模一樣），
   算完寫在生日欄位 wrapper 的 dataset.age 上，evaluateConditions 只比大小。
   前端自己減一份的話，症狀會是「身分別算成人、監護人欄位卻跳出來」。
   ══════════════════════════════════════════════════════════ */
(function () {

  /** 哪些 sort_order 被年齡條件當成觸發問題 */
  function ageTriggerOrders(scope) {
    var wanted = {};
    window.fieldWrappers(scope).forEach(function (w) {
      if (!w.dataset.condition) return;
      var c;
      try { c = JSON.parse(w.dataset.condition); } catch (e) { return; }
      if (c && c.op === 'age_between' &&
          c.trigger_sort_order !== undefined && c.trigger_sort_order !== null) {
        wanted[String(c.trigger_sort_order)] = true;
      }
    });
    return wanted;
  }

  var pending = null;

  window.refreshAgeConditions = function (root) {
    var scope = root || document;
    var wanted = ageTriggerOrders(scope);
    if (!Object.keys(wanted).length) return;      // 這張表單沒有年齡條件

    // 觸發問題指到的那幾個生日欄位
    var targets = window.fieldWrappers(scope).filter(function (w) {
      return wanted[String(w.dataset.sortOrder)] && w.querySelector('.roc-iso');
    });
    if (!targets.length) {
      // 條件指到一個不存在（或不是生日）的欄位 —— 那題等於永遠不顯示。
      // 後台的預覽會把這件事講出來，這裡只要不當掉就好。
      return;
    }

    var birthdays = {};
    targets.forEach(function (w) {
      var iso = w.querySelector('.roc-iso');
      if (iso && iso.value) birthdays[w.dataset.fieldId] = iso.value;
    });

    function clearAll() {
      targets.forEach(function (w) { delete w.dataset.age; });
      window.evaluateConditions(scope);
    }

    // 一個生日都還沒填 → 不用問伺服器
    if (!Object.keys(birthdays).length) return clearAll();

    var body = { birthdays: birthdays };
    var eventId = (window.APP_CONFIG && window.APP_CONFIG.eventId) ||
                  (document.body && document.body.dataset.eventId) || '';
    if (eventId) {
      body.event_id = eventId;      // 基準日由伺服器從活動撈，不信前端
    } else {
      // 後台預覽：活動還沒存，日期只在表單裡。沒有日期就退回今天
      // （age_on 的行為），預覽頁上會註明。
      body.basis = (window.PREVIEW_BASIS_DATE || '');
    }

    clearTimeout(pending);
    pending = setTimeout(function () {
      fetch('/compute-age', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var ages = (d && d.ages) || {};
          targets.forEach(function (w) {
            var a = ages[w.dataset.fieldId];
            if (a === null || a === undefined) delete w.dataset.age;
            else w.dataset.age = String(a);
          });
          window.evaluateConditions(scope);
        })
        .catch(function () {
          // 連不上就退回「算不出來」＝ 條件不成立。留著上一次的年齡的話，
          // 生日都改了那題還照舊顯示／不顯示，看起來完全正常。
          clearAll();
        });
    }, 250);
  };

  document.addEventListener('DOMContentLoaded', function () {
    window.refreshAgeConditions();
  });
})();

/* ══════════════════════════════════════════════════════════
   把既有答案填回表單（修改報名用）

   ★ 為什麼用 JS 統一做，不在模板裡每一種型別加 value=

     欄位渲染有三份（會員／代報／外部）。在模板裡做的話要改三份 × 九種型別，
     而漏掉任何一格的症狀都是「那一題變空白」—— 使用者按下確認修改之後
     那題就真的空了，而且畫面上看起來像他自己沒填。

   ★ 分級收費的自動判定欄位不用填：身分別是算出來的。
     但「特殊身分別」要還原 —— 那是他自己勾的，算不出來。
   ══════════════════════════════════════════════════════════ */
(function () {

  window.prefillFields = function (root, data) {
    if (!data) return;
    var scope = root || document;
    var wrappers = scope.querySelectorAll('.field-wrapper');

    for (var i = 0; i < wrappers.length; i++) {
      var w = wrappers[i];
      var fid = w.dataset.fieldId;
      if (!fid || !(fid in data)) continue;
      var val = data[fid];
      if (val === null || val === undefined) continue;
      val = String(val);
      var type = w.dataset.fieldType || 'text';

      // 自動判定的身分別：算出來的，不填。但特殊身分別要還原。
      var auto = w.querySelector('.auto-tier');
      if (auto) {
        var sp = auto.querySelector('.at-special');
        var specialLabel = auto.dataset.specialLabel || '';
        if (sp && specialLabel && val === specialLabel) sp.checked = true;
        continue;
      }

      if (type === 'radio' || type === 'fee') {
        setChecked(w, 'radio', [val]);
      } else if (type === 'checkbox') {
        setChecked(w, 'checkbox', val.split(/[、,]\s*/));
      } else if (type === 'birthday') {
        setBirthday(w, val);
      } else if (type === 'guardian') {
        setGuardian(w, val);
      } else {
        var el = w.querySelector('select[data-field-id], input[data-field-id],'
                                 + ' textarea[data-field-id]');
        if (el) {
          el.value = val;
          // 身分證有即時檢查，要讓它跑一次才會顯示「格式正確」
          if (typeof checkTwId === 'function' && el.classList.contains('id-input')) {
            checkTwId(el);
          }
        }
      }
    }

    // 填完才重跑一次 —— 順序反過來的話，跳題會用空的答案去判斷，
    // 把該顯示的欄位藏起來，而那些欄位裡剛填好的答案就跟著被清掉
    if (typeof evaluateConditions === 'function') evaluateConditions(scope);
    if (typeof refreshAutoTiers === 'function') refreshAutoTiers(scope);
    // 年齡條件也要重算 —— 少了這行，修改報名時「未滿18歲才問監護人」
    // 那題會照著空白的年齡判斷，把已經填好的監護人答案藏起來並清掉。
    if (typeof refreshAgeConditions === 'function') refreshAgeConditions(scope);
    if (typeof updateFeeTotal === 'function') updateFeeTotal();
  };

  function setChecked(wrapper, kind, values) {
    var inputs = wrapper.querySelectorAll('input[type="' + kind + '"]');
    for (var i = 0; i < inputs.length; i++) {
      if (values.indexOf(inputs[i].value) !== -1) inputs[i].checked = true;
    }
  }

  function setGuardian(wrapper, value) {
    // 存的是「姓名／電話」一格，畫面上是兩個框 —— 直接塞進其中一個的話，
    // 使用者會看到姓名欄裡寫著「王小明／0912345678」
    var parts = (typeof guardianParse === 'function')
      ? guardianParse(value) : [value, ''];
    var name = wrapper.querySelector('.gd-name');
    var phone = wrapper.querySelector('.gd-phone');
    if (name) name.value = parts[0];
    if (phone) phone.value = parts[1];
    if (name && typeof syncGuardian === 'function') syncGuardian(name);
  }

  function setBirthday(wrapper, iso) {
    // 存的是西元，畫面上填的是民國 —— 直接塞西元進去的話，
    // 使用者會看到「民國 2016 年」
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) return;
    var box = wrapper.querySelector('.roc-date');
    if (!box) return;
    var y = box.querySelector('.roc-y'),
        mo = box.querySelector('.roc-m'),
        d = box.querySelector('.roc-d') || box.querySelectorAll('input[type=number]')[2];
    if (y) y.value = parseInt(m[1], 10) - 1911;
    if (mo) mo.value = parseInt(m[2], 10);
    if (d) d.value = parseInt(m[3], 10);
    if (y && typeof syncRocDate === 'function') syncRocDate(y);
  }
})();
