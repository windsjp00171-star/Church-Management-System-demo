"""活動自訂欄位的型別：單一來源，以及一句看得懂的錯誤訊息

## 事故

`event_fields.field_type` 在 Postgres 上有一條 CHECK 約束，是一份白名單。
程式端陸續加了三種新型別（出生日期、身分證字號、分級收費），後台下拉、
前台渲染、送出、名冊全部做好了、859 條測試全綠 —— **但沒有人記得去放寬
那條約束**。

結果那三種欄位在「使用者按下儲存的當下」才被擋掉，畫面上跳出：

    建立失敗：欄位建立失敗：{'message': 'new row for relation "event_fields"
    violates check constraint "event_fields_field_type_check"', 'code': '23514', …}

★ 為什麼測試抓不到：所有測試都 mock 掉 Supabase。**那是 mock 的固有盲區**
  —— 它驗的是「我們有沒有照計畫呼叫」，不是「資料庫會不會接受」。
  再多的單元測試也補不上這一格。

## 這個模組做兩件事（都是真的做得到的）

1. **單一來源** FIELD_TYPES。後台下拉、前台渲染都該對得上它，有測試在守。

2. **把資料庫的錯誤翻成人話**。上面那串訊息看不出「該做什麼」，
   translate_db_error() 會把它換成一句能照著做的：
   「資料庫還不認得『出生日期』這種欄位型別，需要放寬 event_fields 的
     CHECK 約束（見 migrations/2026_event_field_types.sql）」。

★ 刻意不做「啟動時查資料庫對帳」。PostgREST 讀不到 pg_constraint，
  要嘛另外開一個 RPC，要嘛那段程式會靜靜失敗然後回報「一切正常」——
  **一個永遠不會叫的警報比沒有警報更糟**，因為它會讓人以為有人在看。
"""

# ★ 單一來源。新增型別時：
#   1. 這裡加一行
#   2. 後台下拉加 <option>（兩份：既有欄位 / 新增欄位）
#   3. 前台三個報名表單加渲染分支
#   4. **資料庫的 CHECK 約束要放寬**（migrations/2026_event_field_types.sql）
#
#   第 4 步就是這次漏掉的那一步 —— 前三步做完畫面完全正常，
#   要等使用者按下儲存才會發現。
#
#   ★ migration 每次開一個新檔（不要改舊的）。測試會找**檔名最後**
#     那一份定義約束的 .sql 來比對，因為那才是資料庫的最終狀態。
FIELD_TYPES = {
    'text':      '文字',
    'textarea':  '長文字',
    'radio':     '單選',
    'checkbox':  '多選',
    'select':    '下拉選單',
    'number':    '數字',
    'date':      '日期',
    'fee':       '分級收費',
    'birthday':  '出生日期',
    'id_number': '身分證字號',
    'guardian':  '監護人',
}

# 「未滿18歲才問」由伺服器在存檔時自動掛條件（見 routes/admin_events.py 的
# _auto_guardian_condition），管理員不用碰跳題面板。
#
# ★ 為什麼不讓管理員自己設：做成一般欄位的話，姓名和電話要各設一次
#   一模一樣的年齡條件，而兩份設定遲早會不一樣 —— 那時候會變成
#   「姓名要填、電話不用填」，名冊上有名字沒電話。
AUTO_MINOR_TYPES = ('guardian',)

# 有選項可填的型別（後台顯示選項編輯器）
TYPES_WITH_OPTIONS = ('select', 'radio', 'checkbox', 'fee')

# 一格裡有不只一個輸入框的型別（收值／回填要特別處理）
COMPOSITE_TYPES = ('guardian',)

# 可以當跳題觸發問題的型別。
# ★ fee 一定要在裡面：它底下就是單選。漏掉的話「選了孩童才問監護人」
#   那種跳題就再也設不起來，而畫面上只是下拉裡少了一個選項。
#
# ★ birthday 比的是**年齡**（condition_json 的 op='age_between'），
#   不是答案文字。理由：生日的答案是 '2016-03-05' 這種字串，做字串相等
#   比對只會對「剛好在那一天出生」的一個人成立。
#
#   而它非有不可，是因為年齡界線和收費界線的來源不一樣 ——
#   收費分級可能切在 12 歲，監護人切在 18 歲。只能靠分級收費轉一手的話，
#   等於強迫收費表為了一個跟收費無關的需求多切一刀。
TRIGGER_TYPES = ('select', 'radio', 'fee', 'birthday')

# 這幾種觸發型別比的是年齡區間，不是答案文字（後台要換成兩個年齡框）
AGE_TRIGGER_TYPES = ('birthday',)

_CONSTRAINT_NAME = 'event_fields_field_type_check'


def translate_db_error(err, field_type=None):
    """把資料庫的原始錯誤換成一句能照著做的話。不認得就回 None。

    原始訊息（'violates check constraint …', code 23514）看得出「失敗了」，
    但看不出「該做什麼」—— 而看不出該做什麼的錯誤訊息，等於沒有訊息。
    """
    text = str(err)
    if _CONSTRAINT_NAME not in text:
        return None
    name = FIELD_TYPES.get(field_type, field_type or '這一種')
    return (f'資料庫還不認得「{name}」這種欄位型別。'
            f'需要放寬 event_fields 的 {_CONSTRAINT_NAME} 約束 —— '
            f'照 migrations/2026_event_field_types.sql 執行一次即可。')
