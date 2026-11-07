/* 在 node 裡真的跑一次 static/js/form-fields.js 的 evaluateConditions。
 *
 * ## 為什麼不用掃原始碼的斷言
 *
 * CLAUDE.md 寫過：掃原始碼的測試會被 docstring 裡的字串餵飽而自己通過。
 * 跳題條件的每一條規則（年齡不在範圍要藏、算不出來要藏但**不要清**、
 * 0 歲是有效的下限）都只有「真的跑一次」才驗得到 —— 這些全是
 * 「畫面正常、說的是假的」那一類，看程式碼看不出來。
 *
 * ## 這個 shim 只模擬 evaluateConditions 真的會碰到的東西
 *
 * 不是要寫一個瀏覽器。wrapper 的 children 用「選擇器字串 → 節點陣列」
 * 直接餵，所以測試裡看得出每一條斷言依賴哪一個選擇器。
 *
 * 輸出：一個 JSON，{情境名稱: 結果}。斷言寫在 tests/test_age_conditions.py，
 * 這樣每一條情境在 pytest 裡是獨立的一條，紅的時候知道是哪一條。
 */
'use strict';
const fs = require('fs');
const path = require('path');

// ── 最小 DOM ──────────────────────────
function node(extra) {
  return Object.assign({
    value: '',
    checked: false,
    textContent: '',
    style: {},
    dataset: {},
    classList: { contains: () => false },
    closest: () => null,
  }, extra || {});
}

function wrapper(spec) {
  const kids = spec.children || {};
  return {
    name: spec.name,
    dataset: spec.dataset || {},
    style: {},
    offsetParent: {},                    // isFieldVisible 用
    _kids: kids,
    querySelectorAll(sel) { return kids[sel] || []; },
    querySelector(sel) { return (kids[sel] || [])[0] || null; },
  };
}

function install(wrappers) {
  global.window = global;
  global.document = {
    querySelectorAll(sel) {
      return sel === '.field-wrapper' ? wrappers : [];
    },
    querySelector() { return null; },
    addEventListener() {},
    body: { dataset: {} },
  };
}

// form-fields.js 是一堆 IIFE，載入時就會把函式掛到 window 上
function loadModule() {
  const src = fs.readFileSync(
    path.join(__dirname, '..', '..', 'static', 'js', 'form-fields.js'), 'utf8');
  // eslint-disable-next-line no-new-func
  new Function(src)();
}

// ── 情境 ──────────────────────────
// 每個情境自己蓋一份 DOM，跑 evaluateConditions，回報看得到的結果。

function ageCond(extra) {
  return JSON.stringify(Object.assign(
    { trigger_sort_order: 0, op: 'age_between' }, extra));
}

/** 生日欄位（觸發問題）＋ 監護人欄位（被條件控制的那一題） */
function build(condJson, age, guardianAnswer) {
  const rocY = node({ value: '88' });
  const rocM = node({ value: '3' });
  const rocD = node({ value: '5' });
  const rocIso = node({ value: '1999-03-05' });
  const rocHint = node({ textContent: '＝ 西元 1999 年 3 月 5 日' });

  const birthday = wrapper({
    name: 'birthday',
    dataset: Object.assign({ sortOrder: '0', fieldId: 'f-birth', fieldType: 'birthday' },
      age === null ? {} : { age: String(age) }),
    children: {
      '.roc-y, .roc-m, .roc-d': [rocY, rocM, rocD],
      '.roc-hint': [rocHint],
      '[data-field-id]': [rocIso],
    },
  });

  const guardianInput = node({ value: guardianAnswer === undefined ? '' : guardianAnswer });
  const guardian = wrapper({
    name: 'guardian',
    dataset: { sortOrder: '1', fieldId: 'f-guard', fieldType: 'text',
               required: 'true', condition: condJson },
    children: { '[data-field-id]': [guardianInput] },
  });

  return { birthday, guardian, guardianInput, rocY, rocM, rocD, rocIso, rocHint };
}

function run(condJson, age, guardianAnswer) {
  const dom = build(condJson, age, guardianAnswer);
  install([dom.birthday, dom.guardian]);
  loadModule();
  window.evaluateConditions();
  return {
    guardian_display: dom.guardian.style.display,
    guardian_answer: dom.guardianInput.value,
    birthday_iso: dom.rocIso.value,
    birthday_roc_year: dom.rocY.value,
  };
}

const results = {};

// 15 歲、條件是「17 歲以下」→ 要顯示
results.in_range = run(ageCond({ max: 17 }), 15);

// 20 歲、同一條件 → 要藏起來，而且答案要清掉
results.out_of_range = run(ageCond({ max: 17 }), 20, '媽媽 0912345678');

// ★ 還不知道年齡（/compute-age 還沒回來）→ 藏，但**不可以清**。
//   清掉的話，修改報名時剛填回去的監護人答案會在使用者眼前消失。
results.age_unknown = run(ageCond({ max: 17 }), null, '媽媽 0912345678');

// ★ 0 歲是有效的下限。用 falsy 判斷 min 的話，0 會被當成「沒設」。
//   這裡**只設下限**才驗得到：min:0 加上 max 的話，掉了下限結果一樣
//   （下限 0 本來就擋不掉任何人），測試對這件事沒有鑑別力。
//   只設 min:0 時掉了它 → 上下限都沒設 → 條件不成立 → 那題會消失。
results.zero_lower_bound = run(ageCond({ min: 0 }), 5);

// ★ 上下限都沒設 ＝ 條件沒設定完。這時候「符合所有人」是最糟的解讀：
//   那題會對每個人跳出來，而後台看起來只是兩個空格
results.no_bounds = run(ageCond({ min: null, max: null }), 30);

// 只設下限：「65 歲以上」
results.min_only_hit = run(ageCond({ min: 65 }), 70);
results.min_only_miss = run(ageCond({ min: 65 }), 64);

// 邊界要含在內（17 歲以下 = 含 17 歲）
results.upper_boundary_included = run(ageCond({ max: 17 }), 17);
results.lower_boundary_included = run(ageCond({ min: 18 }), 18);

// ★ 「每個人都問」：沒有生日欄位、也算不出年齡，那一題照樣要出現，
//   而且**不可以把答案清掉**（清了的話修改報名時他填的監護人會消失）。
results.everyone_no_age = run(JSON.stringify({ auto: 'everyone' }), null,
                              '媽媽 0912345678');
//   連 18 歲以上的人也要看得到 —— 這正是它跟預設那條的差別。
results.everyone_adult = run(JSON.stringify({ auto: 'everyone' }), 40);

// ★ 舊的「比答案文字」條件不可以被年齡這條 guard 擋掉
(function () {
  const radio = node({ value: '孩童', checked: true });
  const trigger = wrapper({
    name: 'tier',
    dataset: { sortOrder: '0', fieldId: 'f-tier', fieldType: 'radio' },
    children: { 'input[type="radio"]:checked': [radio] },
  });
  const dep = wrapper({
    name: 'dep',
    dataset: { sortOrder: '1', fieldId: 'f-dep', fieldType: 'text',
               condition: JSON.stringify({ trigger_sort_order: 0, trigger_value: '孩童' }) },
    children: {},
  });
  install([trigger, dep]);
  loadModule();
  window.evaluateConditions();
  results.legacy_value_condition = { display: dep.style.display };
})();

// ★ 生日欄位自己被藏起來時：畫面上那三個民國框沒有 data-field-id，
//   不會被「清掉所有 [data-field-id]」那行清到。少了修正的話，
//   螢幕上還寫著民國88年3月5日，而送出的答案已經是空字串。
(function () {
  const rocY = node({ value: '88' });
  const rocM = node({ value: '3' });
  const rocD = node({ value: '5' });
  const rocIso = node({ value: '1999-03-05' });
  const rocHint = node({ textContent: '＝ 西元 1999 年 3 月 5 日' });
  const radio = node({ value: '不用', checked: true });

  const trigger = wrapper({
    name: 'needs_birthday',
    dataset: { sortOrder: '0', fieldId: 'f-ask', fieldType: 'radio' },
    children: { 'input[type="radio"]:checked': [radio] },
  });
  const birthday = wrapper({
    name: 'birthday',
    dataset: { sortOrder: '1', fieldId: 'f-birth', fieldType: 'birthday', age: '26',
               condition: JSON.stringify({ trigger_sort_order: 0, trigger_value: '要' }) },
    children: {
      '.roc-y, .roc-m, .roc-d': [rocY, rocM, rocD],
      '.roc-hint': [rocHint],
      '[data-field-id]': [rocIso],
    },
  });
  install([trigger, birthday]);
  loadModule();
  window.evaluateConditions();
  results.hidden_birthday = {
    display: birthday.style.display,
    iso: rocIso.value,
    roc_year: rocY.value,
    roc_month: rocM.value,
    hint: rocHint.textContent,
    age_left_over: birthday.dataset.age === undefined ? null : birthday.dataset.age,
  };
})();

/* ── 監護人：姓名／電話 ──────────────────────────
 *
 * ★ 這一段是給「JS 和 Python 對同一組輸入必須產生同一個結果」那條測試用的。
 *   兩邊各寫一份格式的話，症狀會是「畫面上填好了，伺服器說沒填」——
 *   而使用者盯著兩個明明有字的框，不知道系統在說什麼。
 */
(function () {
  install([]);
  loadModule();
  const fs2 = require('fs');
  const src = fs2.readFileSync(
    path.join(__dirname, '..', '..', 'static', 'js', 'fee-total.js'), 'utf8');
  // fee-total.js 會碰 document.addEventListener，上面的 shim 已經有了
  new Function(src)();

  const cases = JSON.parse(process.env.GUARDIAN_CASES || '[]');
  results.guardian = cases.map(function (c) {
    const composed = window.guardianCompose(c[0], c[1]);
    return {
      composed: composed,
      parsed: window.guardianParse(composed),
      complete: window.guardianIsComplete(composed),
    };
  });
})();

process.stdout.write(JSON.stringify(results, null, 2));
