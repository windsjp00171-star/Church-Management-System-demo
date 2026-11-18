"""引導式開活動：問句、用途、以及「答案 → 草稿」

## 這在解什麼

使用者的原話：

> 今天就是我想開活動了，但是不知道怎麼使用這個表單系統，才需要引導不是嗎

會需要引導的人，是**想開活動、但不知道那張表單怎麼用**的人。所以這裡不是
把 25 個設定拆成 25 頁 —— 那只是把同一張紙撕開。設定分成三種，
只有第一種問他：

| | 怎麼處理 | 例子 |
|---|---|---|
| 他心裡有答案 | **問**，用他的話問 | 叫什麼、哪一天、多少人、收不收錢 |
| 他不知道、系統算得出來 | **不問**，系統做完講出來讓他否決 | 要不要加生日、監護人怎麼跳、哪些必填 |
| 他不知道、系統也不知道 | **不問**，給預設 | 保留名額、候補截止、簽到模式 |

★ 第三種他答不出來**不是因為他不懂，是因為那些問題現在還不存在**。
  「保留幾個位子給會友」要看到報名狀況才有答案。

## ★ 第二條規矩：每一題都要讓他知道「之後改得到」

使用者的原話：「只是讓他們的有地方可以回來改」。

不講的話每一題都變成不可逆的決定，他會在「報名截止日」這種小事上卡住 ——
而卡住的人不是慢慢想，是**整個退出去**。所以：

- 開場就講「建立之後每一項都還改得到」
- 「待定」是有效答案，而且**要寫出後果**（見 `PENDING_EFFECTS`）
- 建立完直接跳到那場活動的編輯頁 —— 「可以回來改」的那個地方就是它

## ★ 為什麼寫死在程式碼裡（使用者問過）

問句的**文字**可以搬進資料庫（`routes/site_settings.py` 那個模式），
但一題「做什麼」不行：「要保平安險」不是一行字，它要加身分證欄位、
加生日欄位、兩個都設必填。那是行為。

放進資料庫的話會變成「一列資料指向一個 handler」，而後台新增一個
沒有 handler 的用途 → 勾了什麼都不會發生，**畫面完全正常**。
更實際的理由：**測試只守得住 repo 裡的東西** ——
「每一個用途都要對到真的欄位型別」這種守衛，資料一搬走就失效。

★ 所以寫成**純資料的形狀**（沒有 lambda、沒有 if），
  哪天真的要搬進資料庫是直接搬，不用重寫。

## 誰產生草稿

`build_draft()` 是**純函式**：答案進去，`/admin/events/new` 吃的那個
payload 出來。前端只負責問問題和收答案，一個欄位都不自己拼 ——
自己拼一份的話，「要保險要加哪兩個欄位」就有兩份實作了。
"""
import json as _json

#  ★ 監護人的印記形狀只有一份。這裡 import 的是純函式的那個模組
#    （`routes/guardian.py` 只 import re），所以 `build_draft` 仍然
#    不碰資料庫 —— 那條測試守著。
from routes.guardian import everyone_condition

#  ── 欄位樣板 ──────────────────────────────────────
#
#  ★ label 是**報名者會看到的字**，所以定在這裡而不是散在各個用途裡：
#    同一個欄位被兩個用途要到時（生日：保險要、分級收費也要、監護人也要），
#    兩邊拼出不同的名字就會變成兩題。`_add()` 靠 key 去重。
FIELD_TEMPLATES = {
    'name':      {'label': '參加者姓名', 'field_type': 'text',      'is_required': True},
    'phone':     {'label': '連絡電話',   'field_type': 'text',      'is_required': False},
    'id_number': {'label': '身分證字號', 'field_type': 'id_number', 'is_required': True},
    'birthday':  {'label': '出生年月日', 'field_type': 'birthday',  'is_required': True},
    'guardian':  {'label': '監護人',     'field_type': 'guardian',  'is_required': True},
    'diet':      {'label': '飲食需求',   'field_type': 'radio',
                  'options': '葷食\n素食', 'is_required': False},
    'note':      {'label': '備註（要跟誰同車、同桌、其他需要說明的）',
                  'field_type': 'textarea', 'is_required': False},
    'tier':      {'label': '身分別',     'field_type': 'fee',       'is_required': True},
}


#  ── 用途 → 欄位 ───────────────────────────────────
#
#  ★★ 問「為什麼要拿資料」，不是給一張欄位清單讓他勾。
#
#     問用途才問得出「保險」，而「保險」才推得出身分證＋生日。
#     直接給欄位清單的話他會勾出一堆東西，然後**漏掉最重要的那兩個** ——
#     而名冊看起來完全正常，要到送保單那天才發現。
#
#  says : 加完之後要講出來的話。★ 系統做的推論一定要講，
#         默默加上去的話他不知道那個欄位為什麼在那裡，下次會想刪掉。
USES = [
    {'key': 'insurance', 'label': '要保平安險',
     'adds': ['id_number', 'birthday'],
     'says': '保險公司要身分證字號和出生日期，我把兩個都加上、都設必填。'
             '身分證會驗檢查碼，打錯的當場就知道。'},
    {'key': 'meal', 'label': '要訂餐，或要知道飲食需求',
     'adds': ['diet'],
     'says': '我加一題「飲食需求」。'
             '要按餐次分別收費的話，建立完在活動設定裡開「餐點訂購」。'},
    {'key': 'seating', 'label': '要排遊覽車、桌次、房間',
     'adds': ['note'],
     'says': '我加一題備註，讓他們自己寫要跟誰同車、同桌。'
             '這種需求寫死選項一定會漏，開放填比較實在。'},
    {'key': 'contact', 'label': '要能聯絡到他',
     'adds': ['phone'],
     'says': '我加一題連絡電話。臨時改地點、改時間的時候，'
             '站內通知送不到外部朋友 —— 那時候只剩這一格。'},
    {'key': 'guardian', 'label': '未成年的要留家長聯絡方式',
     'adds': ['guardian', 'birthday'],
     'says': '我加一題監護人（姓名和電話填在同一格），'
             '**只有未滿 18 歲的人會看到那題**。'
             '算年齡要用出生日期，所以生日也一起加上 —— 你不用自己設條件。'},
]

#  ★ 「每個人都要填家長聯絡方式」（兒童營、青少年營）＝ 監護人型別
#    ＋「每個人都問」的印記。
#
#    這裡原本走的是**兩個一般欄位**（「家長姓名」「家長電話」，也就是
#    Reborn 那場實際的做法）。理由不是偷懶：那時候監護人型別**表達不出**
#    「每個人都問」—— `_apply_guardian_conditions` 的規則是「沒設條件就
#    自動補上『未滿18歲才問』」，存下去會被自動加上年齡條件，
#    而畫面上看起來是好的。
#
#    那個洞補起來了（`routes/guardian.everyone_condition`），所以這條路
#    改回監護人型別 —— 兩個一般欄位少掉的東西是實的：
#
#      - 「兩格都填才算填了」不見了（只打名字也能過必填，
#        而名冊上那一列打不到人）
#      - 名冊、匯出、我的報名要各自把兩格拼回去
#      - 管理員之後想改條件，得記得**兩題都要改**
GUARDIAN_EVERYONE = {
    'label': '家長聯絡方式', 'field_type': 'guardian', 'is_required': True,
    #  印記的形狀只有一份 —— 這裡不自己拼一個 dict。
    'condition_json': _json.dumps(everyone_condition()),
}

USE_KEYS = [u['key'] for u in USES]


#  自己加題目時能選的型別。
#
#  ★ 只給三種，是刻意的：那是**不懂系統的人講得出來**的三種。
#    分級收費、出生日期、身分證、監護人不放進這個下拉 ——
#    它們已經由用途推出來了，放進來只會讓他在一個他分不清的清單裡選錯。
#
#  ★ 附帶好處：這三種**不參與任何一條依賴**
#    （見 `routes/setting_deps.py`），所以「自己加題目」這個出口
#    不會把前面整理好的依賴弄亂。
CUSTOM_TYPES = ('text', 'textarea', 'radio')


#  ── 「待定」的後果 ────────────────────────────────
#
#  ★★ 只寫「待定」兩個字的話，那件事會**靜靜地不發生**，
#     而後台每一格看起來都正常 —— 這個專案反覆出現的那個形狀。
#     所以按鈕上就要寫後果，最後的確認畫面再列一次。
PENDING_EFFECTS = {
    'reg_end':          '先不設報名截止，報名會一直開著。',
    #  ★ 系統本來就不會催繳（使用者定的，見 routes/reminders）——
    #    所以這裡只講「後台的名單上看不到期限」，不要暗示有提醒這回事。
    'payment_deadline': '先不設繳費期限，收款單上不會顯示要繳到哪一天。',
    'capacity':         '先不設人數上限，不會額滿，也不會有候補。',
}


#  ── 不問的那些，預設成什麼 ────────────────────────
#
#  ★ 「不問」不等於「不見了」—— 建立完在活動編輯頁全部改得到。
#    這張表是為了讓那句話有依據，不是憑印象講的。
DEFAULTS = {
    'is_open': True,
    'reminder_days': 3,
    'member_reserved': 0,
    'whitelist_enabled': False,
    'party_animation': False,
    'allow_open_checkin': False,
    #  ★ 代報是常態（小組長幫長輩報名），關著的話他幫第二個人報名會被擋，
    #    而那個錯誤訊息看起來像系統壞了。同一個人重複報名是靠
    #    `event._reject_duplicate_person` 擋的，不是靠這個開關。
    'allow_multiple': True,
}


def _add(fields, key, seen):
    """加一個欄位樣板，同一個 key 只加一次。

    ★ 去重是必要的不是保險：生日同時被「保險」「分級收費」「監護人」
      三條路要到，不去重的話表單上會有三題出生日期 ——
      而每一題都要填，報名者會以為自己看錯了。
    """
    if key in seen:
        return
    seen.add(key)
    fields.append(dict(FIELD_TEMPLATES[key]))


def _int0(v):
    """空值（None／空字串）明確算 0，其他照 int() 轉（結構守衛不准寫 `or 0`）。"""
    return 0 if v is None or v == '' else int(v)


def build_draft(answers):
    """答案 → `/admin/events/new` 吃的那個 payload。**純函式，不碰資料庫。**

    answers 的形狀（缺的一律當「沒回答」，不要爆炸）::

        {'title': '...', 'event_start': '2026-10-08T08:00',
         'event_end': None, 'location': '',
         'capacity': 120,  'capacity_pending': False,
         'waitlist': False,
         'fee_mode': 'none' | 'flat' | 'tiered',
         'fee': 0,
         'tiers': [{'label': '成人', 'price': 800}, ...],
         'tier_ages': {'孩童': [None, 12], '長者': [65, None]},
         'tier_special': '優待',
         'uses': ['insurance', 'seating'],
         'custom': [{'label': '從哪裡得知消息', 'field_type': 'radio',
                     'options': 'FB\n親友告知', 'is_required': False}],
         'guardian_scope': 'minor' | 'everyone',
         'reg_end': '2026-09-24T23:59', 'reg_end_pending': False,
         'payment_deadline': None, 'payment_deadline_pending': True,
         'checkin': False, 'open_checkin': False,
         'who': 'anyone' | 'members'}

    回 `{'event': {...}, 'fields': [...], 'said': [...], 'pending': [...]}`。
    `said` 是系統做過的推論（要顯示在確認畫面上），`pending` 是待定的項目。
    """
    a = answers or {}
    fields, seen, said = [], set(), []

    #  ★ 姓名不問，一律自動加，而且名字就叫「參加者姓名」。
    #    簽到名單和名冊都靠這一格認人 —— 代報的時候才不會整欄
    #    變成代報者的名字。
    _add(fields, 'name', seen)

    fee_mode = a.get('fee_mode') or 'none'

    #  分級收費：欄位 ＋ 依生日自動判定
    if fee_mode == 'tiered':
        tiers = [t for t in (a.get('tiers') or []) if (t.get('label') or '').strip()]
        if tiers:
            tier = dict(FIELD_TEMPLATES['tier'])
            tier['options'] = '\n'.join(
                f"{t['label'].strip()}|{_int0(t.get('price'))}" for t in tiers)
            auto = _auto_tier(a, tiers)
            if auto:
                tier['auto_tier'] = auto
                _add(fields, 'birthday', seen)
                said.append('分級收費要用年齡判斷，所以加了「出生年月日」——'
                            '報名的人不用自己選身分別，也就不會選錯。')
            fields.append(tier)
            seen.add('tier')

    #  用途 → 欄位
    everyone = a.get('guardian_scope') == 'everyone'
    for use in USES:
        if use['key'] not in (a.get('uses') or []):
            continue
        if use['key'] == 'guardian' and everyone:
            #  見 GUARDIAN_EVERYONE 上面那段。
            fields.append(dict(GUARDIAN_EVERYONE))
            said.append('這場是每個人都要填家長聯絡方式，'
                        '所以那一題我勾了「每個人都要填」——'
                        '「監護人」預設只問未滿 18 歲的人。')
            continue
        for key in use['adds']:
            _add(fields, key, seen)
        said.append(use['says'])

    #  誰可以報名：外部朋友沒有帳號，名冊要靠姓名＋電話認人
    if (a.get('who') or 'anyone') == 'anyone' and 'phone' not in seen:
        _add(fields, 'phone', seen)
        said.append('開放外部報名的話，名冊要靠姓名和電話認人'
                    '（連結弄丟時也是靠這兩個找回自己那一筆），所以加了連絡電話。')

    #  他自己加的題目 —— 一律排在最後，型別限 CUSTOM_TYPES
    for c in (a.get('custom') or []):
        label = (c.get('label') or '').strip()
        if not label:
            continue
        ftype = c.get('field_type') if c.get('field_type') in CUSTOM_TYPES else 'text'
        fields.append({'label': label, 'field_type': ftype,
                       'options': (c.get('options') or '').strip(),
                       'is_required': bool(c.get('is_required'))})

    #  ★ 監護人「只問未滿 18 歲」的那個條件**這裡一個字都不寫** ——
    #    它是存檔時由 `admin_events._apply_guardian_conditions` 自動掛的。
    #    在這裡再產生一份的話，trigger_sort_order 會有兩個來源，
    #    而它們對「第幾題」的算法只要差一號，那題就指到別的問題上，
    #    畫面上完全看不出來。

    return {
        'event': _event(a, fields),
        'fields': fields,
        'said': said,
        'pending': pending(a),
    }


def _auto_tier(a, tiers):
    """分級收費的「依生日自動判定」設定（`routes/auto_tier.py` 吃的形狀）。

    算不出來就回 None —— 沒有年齡範圍的話開著自動判定，
    每個人都會落到 fallback，那比不開更糟。
    """
    ages = {k: v for k, v in (a.get('tier_ages') or {}).items()
            if isinstance(v, (list, tuple)) and len(v) == 2
            and not (v[0] is None and v[1] is None)}
    if not ages:
        return None
    special = (a.get('tier_special') or '').strip()
    labels = [t['label'].strip() for t in tiers]
    #  ★ fallback 一定要明確指定：用「第一個沒設年齡範圍的」去推的話，
    #    管理員幫成人也填了範圍時，沒設範圍的就只剩自行申報那一項 ——
    #    落在範圍外的人會被自動標成「持證明者」。
    fallback = next((l for l in labels if l not in ages and l != special), None)
    if not fallback:
        return None
    out = {'enabled': True, 'fallback_label': fallback, 'ages': ages}
    if special:
        out['special_label'] = special
    return out


def _event(a, fields):
    """活動那一層的設定。"""
    ev = dict(DEFAULTS)
    ev.update({
        'title': (a.get('title') or '').strip(),
        'location': (a.get('location') or '').strip(),
        'description': (a.get('description') or '').strip(),
        'event_start': a.get('event_start') or None,
        'event_end': a.get('event_end') or None,
        #  ★ 報名開始不問 —— 九成的活動就是「現在開放」。
        #    留 None 等於沒有起始限制。
        'reg_start': None,
        'reg_end': None if a.get('reg_end_pending') else (a.get('reg_end') or None),
        'capacity': None if a.get('capacity_pending') else (a.get('capacity') or None),
        'waitlist_enabled': bool(a.get('waitlist')),
        'checkin_enabled': bool(a.get('checkin')),
        'allow_external_reg': (a.get('who') or 'anyone') == 'anyone',
        'fields': fields,
    })

    #  ★ 沒有上限就沒有「額滿」，候補永遠不會發生。
    #    引導式裡這一條是**順序**（沒上限就不問候補），這裡再收一次尾，
    #    因為答案可能是從別的地方拼出來的。
    if not ev['capacity']:
        ev['waitlist_enabled'] = False

    #  ★ 簽到沒開的話，「開放模式」不會被讀到 —— 不要留一個假的設定。
    if ev['checkin_enabled']:
        ev['checkin_mode'] = 'open' if a.get('open_checkin') else 'registered_only'
    else:
        ev['checkin_mode'] = 'registered_only'

    fee_mode = a.get('fee_mode') or 'none'
    #  ★ 三選一，所以基本費和分級收費不可能同時有值。
    #    那個「基本費 800 ＋ 成人 800 ＝ 收 1600」的坑，
    #    在引導式裡是被**問法**填掉的，不是被檢查擋掉的。
    ev['fee'] = _int0(a.get('fee')) if fee_mode == 'flat' else 0
    if fee_mode == 'none':
        ev['payment_deadline'] = None
    else:
        ev['payment_deadline'] = (None if a.get('payment_deadline_pending')
                                  else (a.get('payment_deadline') or None))
    return ev


def pending(answers):
    """待定的項目，附後果。回 `[{'key','label','effect'}, …]`。

    ★ 這份清單要出現在**最後的確認畫面**上。不列的話「待定」
      就變成一個安靜的洞：報名永遠不截止、繳費提醒永遠不發，
      而後台每一格看起來都正常。
    """
    a = answers or {}
    out = []
    for key, label in (('capacity', '人數上限'),
                       ('reg_end', '報名截止'),
                       ('payment_deadline', '繳費期限')):
        if not a.get(f'{key}_pending'):
            continue
        #  不收費的活動沒有繳費期限這件事，不要列一個他沒看過的東西
        if key == 'payment_deadline' and (a.get('fee_mode') or 'none') == 'none':
            continue
        out.append({'key': key, 'label': label, 'effect': PENDING_EFFECTS[key]})
    return out
