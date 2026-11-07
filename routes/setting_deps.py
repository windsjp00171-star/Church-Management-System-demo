"""設定之間的關係：一張註冊表，一份事實

## 這在解什麼

開一場活動要做 24 個決定，其中有 11 條是「這個設定要另一個先成立」。
而系統原本對它們給了**四種完全不同的待遇**：

| 待遇 | 幾條 | 例子 |
|---|---|---|
| 即時就講 | 1 | 基本費和分級收費會相加（`fee-conflict` 提示框）|
| 存檔時擋下來 | 2 | 監護人要有出生日期欄位 |
| 存好了才說 | 1 | 外部報名要有姓名／電話欄位（`external_form_warnings`）|
| **完全不講** | **7** | 開放候補但沒設人數上限、自動判定但沒有生日欄位…… |

★ 這四種待遇**不是設計出來的**，是一次一次補出來的 —— 每次有人踩到，
  就在那個地方補一句話。所以**待遇的輕重跟後果的嚴重程度沒有關係**：
  最沉默的那幾條後果最重。

  - 開放候補 ＋ 沒有人數上限 → `seat_verdict` 永遠回「還有位子」
    → **候補永遠不會發生**，而後台那個勾勾是打著的
  - 依生日自動判定 ＋ 沒有生日欄位 → 每個人都落到 `fallback_label`
    → **孩童被收成人價**，而名冊上每一格都正常

## 為什麼要做成註冊表，而不是逐條補 if

同一條規則有四個地方要用：**引導式問答的分支**、**表單上的即時提示**、
**存檔時的檢查**、**小舟的回答**。四份實作的話，改了一份另外三份
不會跟 —— 而這個專案已經有一整章在講那件事。

★ 而且它會自己守自己：新增一個設定卻沒登記依賴，
  `tests/test_setting_deps.py` 會紅 —— 那正是這七條當初形成的方式。

## ★ 形狀是通用的，不綁活動

使用者：「未來其實我想把這樣的模式推進去系統全域」。所以每一列都帶
`module`。目前登記了兩個：

| 模組 | 幾條 | 為什麼是它 |
|---|---|---|
| `events` | 11 | 第一個做的 |
| `courses` | 7 | **它真的有人在用**：2 門課、14 堂次、71 筆報名、<br>164 筆出席、265 張完訓、42 筆教材領用 —— 跟活動同一個量級 |

★ 挑第二個模組時是**先查使用量再決定**的，不是憑「感覺哪個比較複雜」。
  禱讀本、週報、行事曆那種一張表幾個欄位、彼此不相干的，
  盤點了也沒有依賴可登記。沒登記的模組是**還沒盤點**或**本來就沒有**，
  兩者要分清楚。

## ★ `effect` 寫的是「後果」，不是「規則」

    ✗ 「開放候補需要設定人數上限」   ← 這是規則，他已經知道了
    ✓ 「沒設上限就不會額滿，候補永遠不會發生」← 這是後果，他不知道

規則式的訊息讀起來像系統在挑剔；後果式的才讓人知道**為什麼要理它**。
`tests/test_setting_deps.py` 有一條在守這個。

## 誰去查資料庫

`applies` 和 `met` 都是**純函式** —— 它們只讀傳進來的 `ctx`。
要資料庫的東西（例如有沒有主標籤小組）由呼叫端先撈好放進 ctx。

★ 純的理由不是好看：這些 predicate 之後要在**引導式問答的當下**跑，
  那時候活動還不存在、什麼都還沒存。會自己查資料庫的 predicate
  在那個情境下不是回錯答案，就是根本跑不起來。
"""
from typing import Callable, NamedTuple

#  關係的兩種形狀。
#  - needs   ：A 打開了，但 B 沒成立 → A 靜靜地不生效
#  - conflict：A 和 B 都成立，而它們互相影響的方式跟直覺相反
NEEDS = 'needs'
CONFLICT = 'conflict'
#  mismatch：兩個**數字**對不上（A 是手填的，B 是系統算出來的）。
#
#  ★ 為什麼要第三種形狀：前兩種的句型都預設那個設定是**開關**
#    （「開了 X 但還沒有 Y」）。課程這邊有幾個是數字 ——
#    「開了『共 N 堂』」根本不是中文，而讀起來怪的提醒沒有人會理它。
MISMATCH = 'mismatch'


class Dep(NamedTuple):
    """一條設定之間的關係。

    module  : 哪一個模組（`events` / 未來的 `courses` …）
    key     : 程式用的識別，同一個模組裡唯一
    label   : 這個設定給人看的名字
    needs   : 它需要什麼（給人看的名字）。可以是字串，也可以是
              `ctx -> 字串` 的函式 —— 訊息裡要寫出「系統認得哪些名稱」
              這種**從別的單一來源長出來**的內容時用得到。
              ★ 寫死一份的話，`NAME_LABELS` 加了一個叫法，
                提醒還是只列舊的 —— 他照著改也不會生效。
    effect  : **沒有的話會怎樣** —— 寫後果，不要寫規則
    applies : ctx -> bool，這個設定有沒有被打開
    met     : ctx -> bool，依賴滿足了沒
    kind    : NEEDS / CONFLICT
    blocks  : 要不要擋存檔。★ 預設 False（只講不擋）——
              活動常常編一半先存起來，擋下來會把人卡在一個
              他還沒要處理的問題上。
    """
    module: str
    key: str
    label: str
    needs: str
    effect: str
    applies: Callable
    met: Callable
    kind: str = NEEDS
    blocks: bool = False


# ── ctx 的形狀（活動）──────────────────────────────
#
#   {'event':  {...},           # 活動列（或表單送上來的 dict）
#    'fields': [...],           # 自訂欄位
#    'primary_groups': [...]}   # 主標籤小組名稱（呼叫端先撈好）
#
# ★ 缺哪一項就當「空的」處理，不要爆炸 —— 引導式問答的中途，
#   ctx 本來就是一半一半的。

def _ev(ctx):
    return (ctx or {}).get('event') or {}


def _fields(ctx):
    return (ctx or {}).get('fields') or []


def _has_type(ctx, ftype):
    return any(f.get('field_type') == ftype for f in _fields(ctx))


def _priced_fields(ctx):
    from routes.event_fields import has_prices
    return [f for f in _fields(ctx) if has_prices(f.get('options'))]


def _auto_tier_on(ctx):
    from routes.auto_tier import is_enabled
    return any(is_enabled(f.get('auto_tier')) for f in _fields(ctx))


def _labels(ctx):
    return {(f.get('label') or '').strip() for f in _fields(ctx)}


def _condition_rows(ctx):
    """跳題條件的索引基準 —— 跟報名表單、伺服器一致：有名字、非 group。

    ★ 這個基準只有一份（見 `routes/conditions.py` 和
      `tests/test_condition_index_survives_editing.py`）。
      自己再濾一次的話，索引會差一號 —— 而那正是那個 bug 的形狀。
    """
    return [f for f in _fields(ctx)
            if (f.get('label') or '').strip()
            and f.get('field_type') != 'group']


def _cond_of(field):
    import json
    raw = field.get('condition_json')
    if not raw:
        return None
    try:
        return raw if isinstance(raw, dict) else json.loads(raw)
    except (ValueError, TypeError):
        return None


def _required_age_jumps(ctx):
    """必填、而且靠年齡才出現的那幾個欄位。"""
    out = []
    for f in _fields(ctx):
        if not f.get('is_required'):
            continue
        cond = _cond_of(f)
        if cond and cond.get('op') == 'age_between':
            out.append(f)
    return out


def _trigger_of(ctx, field):
    """這個欄位的條件指到哪一題（指不到回 None）。"""
    cond = _cond_of(field) or {}
    idx = cond.get('trigger_sort_order')
    rows = _condition_rows(ctx)
    if not isinstance(idx, int) or not (0 <= idx < len(rows)):
        return None
    return rows[idx]


def _int(v):
    try:
        return 0 if v is None or v == '' else int(v)   # 空值明確算 0（結構守衛不准寫 `or 0`）
    except (TypeError, ValueError):
        return 0


# ── ctx 的形狀（門訓課程）──────────────────────────
#
#   {'course':   {...},        # 課程列（或表單送上來的 dict）
#    'sessions': [...],        # 這門課實際建立的堂次
#    'whitelist_count': 0,     # 白名單人數（呼叫端先撈好）
#    'linked_material': {...}, # 課程類別連動到的教材，沒有就 None
#    'saved': True}            # 這門課存在資料庫裡了嗎
#
# ★ 跟活動那半邊一樣：缺哪一項就當「空的」，不要爆炸。
#
# ★★ `saved` 為什麼要有：**還沒存的課，堂次和白名單一定是空的** ——
#    但那是「還沒排」，不是「設定錯了」。分不出來的話，
#    他剛按下「新增學程」、才勾了缺勤上限，畫面就開始唸他還沒排堂次。
#    第一次用的人會以為自己做錯了什麼。
#    （這是測試抓到的，我原本在註解裡寫了這件事但沒有實作。）

def _co(ctx):
    return (ctx or {}).get('course') or {}


def _sessions(ctx):
    return (ctx or {}).get('sessions') or []


def _saved(ctx):
    """這門課已經存在資料庫裡了嗎（沒有的話，撈不到的東西不算缺）。"""
    return bool((ctx or {}).get('saved'))


def _material_price(ctx):
    """類別連動到的教材售價；沒有連動回 None。

    ★ 回 None 和回 0 是**兩件事**：沒有連動（手填的金額會生效）
      跟連動到一本免費的書（手填的不生效）不一樣。
      混在一起的話，免費教材那一種會少講一句該講的話。
    """
    mat = (ctx or {}).get('linked_material')
    if not mat:
        return None
    return _int(mat.get('selling_price'))


DEPENDENCIES = [
    # ══ 名額 ══════════════════════════════════════
    Dep(
        module='events', key='waitlist_needs_capacity',
        label='開放候補名單', needs='人數上限',
        effect='沒設人數上限就永遠不會額滿，候補永遠不會發生 —— '
               '而這個勾是打著的，看起來已經開了。',
        applies=lambda c: bool(_ev(c).get('waitlist_enabled')),
        met=lambda c: bool(_ev(c).get('capacity')),
    ),
    # shortcut: 成熟版還有「會友保留名額要先有人數上限」一條；這個 repo 沒有保留名額設定，沒搬。
    Dep(
        module='events', key='waitlist_deadline_needs_waitlist',
        label='候補截止時間', needs='開放候補名單',
        effect='候補沒開的話這個時間不會被讀到 —— 設了一個截止時間，'
               '而系統從頭到尾不會看它。',
        applies=lambda c: bool(_ev(c).get('waitlist_deadline')),
        met=lambda c: bool(_ev(c).get('waitlist_enabled')),
    ),

    # ══ 收費 ══════════════════════════════════════
    Dep(
        module='events', key='auto_tier_needs_birthday',
        label='依生日自動判定身分別', needs='「出生日期」欄位',
        effect='算不出年齡的話每個人都會落到預設那一級（通常是「成人」）'
               '—— 孩童被收成人價，而名冊上每一格都正常。',
        applies=_auto_tier_on,
        met=lambda c: _has_type(c, 'birthday'),
    ),
    Dep(
        module='events', key='fee_adds_to_tiers',
        label='基本費用', needs='分級收費（兩者相加）',
        effect='基本費和分級收費是**相加**的。基本費 800 加上「成人 800」'
               '＝ 收 1600。只想用分級收費的話，基本費要設 0。',
        applies=lambda c: _int(_ev(c).get('fee')) > 0 and bool(_priced_fields(c)),
        #  ★ 這一條是「提醒」不是「缺東西」—— 它永遠不會被滿足，
        #    只要兩邊都有值就一直要講。
        met=lambda c: False,
        kind=CONFLICT,
    ),
    Dep(
        module='events', key='money_needs_primary_groups',
        label='跟會友收費', needs='至少一個主標籤小組',
        effect='沒有主標籤小組的話，每一筆的收款歸屬都算不出來 —— '
               '全部落進「未分組（教會行政）」，小組收款單一張都發不出去。'
               '代報的那幾筆也會歸錯組。',
        applies=lambda c: (_int(_ev(c).get('fee')) > 0
                           or bool(_priced_fields(c))),
        met=lambda c: bool((c or {}).get('primary_groups')),
    ),

    # ══ 外部報名 ═══════════════════════════════════
    #
    # shortcut: 成熟版在這裡有兩條（外部報名要有認得的「姓名」「電話」欄位），這個 repo 的
    #   外部報名頁自己固定問姓名、沒有電話那一格，條件不成立，所以沒搬；
    #   哪天外部報名改成跟成熟版一樣靠欄位標籤認人，再把那兩條補回來。

    # ══ 欄位之間 ═══════════════════════════════════
    Dep(
        module='events', key='guardian_needs_birthday',
        label='監護人欄位', needs='「出生日期」欄位',
        effect='監護人預設只問未滿 18 歲的人，要靠出生日期判斷年齡。'
               '算不出來的話那一題永遠不出現 —— 未成年沒有監護人資料，'
               '而後台看起來設好了。',
        #  ★ 勾了「這一題每個人都要填」的不算 —— 它不靠年齡判斷，
        #    所以不需要出生日期。照樣提醒的話，畫面上會出現一條紅色的
        #    「擋存檔」提示，而伺服器其實讓他存了 ——
        #    他會為了消掉那行字，加一題他不需要的出生日期。
        applies=lambda c: any(f.get('field_type') in _auto_minor_types()
                              and not _asks_everyone(f)
                              for f in _fields(c)),
        met=lambda c: _has_type(c, 'birthday'),
        #  ★★ 這是唯一擋存檔的一條，而且是**既有行為**
        #    （`_apply_guardian_conditions` 早就在擋）。
        #    登記進來是為了讓引導式和提示也看得到它 ——
        #    不是為了改變它。
        blocks=True,
    ),

    Dep(
        module='events', key='required_age_jump_needs_required_birthday',
        label='必填、而且依年齡才出現的欄位', needs='觸發它的生日欄位也設成必填',
        effect='不填生日就算不出年齡，那一題不會出現，也就不用填了 —— '
               '「未成年一定要填監護人」變成「不想填的人不要填生日就好」，'
               '而後台看起來設定得好好的。',
        applies=lambda c: bool(_required_age_jumps(c)),
        met=lambda c: all(
            _trigger_of(c, f) is None or _trigger_of(c, f).get('is_required')
            for f in _required_age_jumps(c)),
    ),

    # ══ 簽到 ═══════════════════════════════════════
    Dep(
        module='events', key='checkin_options_need_checkin',
        label='簽到模式 / 允許現場加入', needs='開啟電子簽到',
        effect='簽到沒開的話，這些設定不會被讀到，也不會產生 QR Code。',
        applies=lambda c: (_ev(c).get('allow_open_checkin')
                           or _ev(c).get('checkin_mode') == 'open'),
        met=lambda c: bool(_ev(c).get('checkin_enabled')),
    ),

    # ══════════════════════════════════════════════
    # 門訓課程
    # ══════════════════════════════════════════════
    #
    # ★ 為什麼是課程當第二個模組：不是因為它「感覺比較複雜」，
    #   是因為**它真的有人在用**。盤點時的實際數字：
    #   2 門課、14 堂次、71 筆報名、164 筆出席、265 張完訓、42 筆教材領用 ——
    #   跟活動同一個量級。
    #
    # ★ 下面七條都追到實際的判斷式，不是憑印象列的。

    # ── 堂次 ──────────────────────────────────
    Dep(
        module='courses', key='total_sessions_matches_real_sessions',
        label='共 N 堂',
        needs=lambda c: (f'寫的是 {_int(_co(c).get("total_sessions"))} 堂，'
                         f'實際排了 {len(_sessions(c))} 堂'),
        kind=MISMATCH,
        effect='這是**手填的**，跟實際排的堂次沒有連動。'
               '學程列表、詳情頁、我的記錄印的是這個數字，'
               '而「我的學程」的進度條和缺勤判定用的是**實際堂次** —— '
               '同一個學員的進度在兩頁會不一樣，而兩邊看起來都正常。',
        #  ★ 還沒排堂次時不講：那只是「還沒建」，不是設定錯了。
        applies=lambda c: bool(_sessions(c)) and _int(_co(c).get('total_sessions')),
        met=lambda c: _int(_co(c).get('total_sessions')) == len(_sessions(c)),
    ),
    Dep(
        module='courses', key='absence_limit_needs_sessions',
        label='缺勤上限', needs='先排好堂次',
        effect='缺勤是拿「已經上過的堂次」去算的。一堂都還沒排的話，'
               '缺勤永遠是 0 —— 這個上限永遠不會觸發，而後台看起來設好了。',
        applies=lambda c: (_saved(c)
                           and _co(c).get('absence_limit') is not None),
        met=lambda c: bool(_sessions(c)),
    ),
    Dep(
        module='courses', key='absence_limit_below_total',
        label='缺勤上限',
        needs=lambda c: (f'設成 {_int(_co(c).get("absence_limit"))}，'
                         f'而總共只有 {len(_sessions(c))} 堂'),
        kind=MISMATCH,
        effect='上限跟總堂數一樣多（或更多）的話，**任何人都不可能超標** —— '
               '一堂都沒來的人也還在標準內。這個限制等於沒設。',
        applies=lambda c: (_co(c).get('absence_limit') is not None
                           and bool(_sessions(c))),
        met=lambda c: _int(_co(c).get('absence_limit')) < len(_sessions(c)),
    ),

    # ── 教材費 ─────────────────────────────────
    Dep(
        module='courses', key='material_fee_needs_material_flag',
        label='教材費', needs='勾「這門課需要教材」',
        effect='沒勾的話，報名時根本不會問學員要不要買教材 —— '
               '**這筆錢一毛都收不到**，而後台的金額欄位填得好好的。',
        applies=lambda c: _int(_co(c).get('material_fee')) > 0,
        met=lambda c: bool(_co(c).get('has_material')),
    ),
    Dep(
        module='courses', key='material_fee_is_overridden_by_the_material',
        label='教材費',
        needs=lambda c: f'教材本身的售價（目前 {_material_price(c)} 元）',
        effect='進行中的課，教材費是**跟著教材當下的售價走**的 —— '
               '這樣改一次定價，所有還在收費的班就同步了。'
               '所以這裡填的數字不會生效（除非課程已經完結）。'
               '要改價錢請去「教材管理」改那本書。',
        applies=lambda c: (bool(_co(c).get('has_material'))
                           and _material_price(c) is not None
                           and _int(_co(c).get('material_fee'))
                           != _material_price(c)),
        #  ★ 只在**兩個數字不一樣**時才講。一樣的時候沒有意外，
        #    每次都跳的話他看兩次就不看了。
        met=lambda c: False,
        kind=CONFLICT,
    ),

    # ── 報名資格 ───────────────────────────────
    Dep(
        module='courses', key='whitelist_needs_names',
        label='限定白名單報名', needs='白名單裡至少有一個人',
        effect='名單是空的話**沒有人報得進來**，而他們看到的是'
               '「你不在此學程的報名名單中，請聯絡管理員」—— '
               '看起來像他們自己的問題，於是不會有人來問。',
        applies=lambda c: _saved(c) and bool(_co(c).get('whitelist_enabled')),
        met=lambda c: _int((c or {}).get('whitelist_count')) > 0,
    ),
    Dep(
        module='courses', key='prerequisite_course_is_ignored',
        label='先修學程', needs='先修類別（兩個只有一個會生效）',
        effect='兩個都設的話**只有「先修類別」生效**，先修學程會被忽略。'
               '（那是刻意的：類別是新版的做法，學程是舊版留著相容用的。）',
        applies=lambda c: bool(_co(c).get('prerequisite_course_id')
                               and _co(c).get('prerequisite_category_id')),
        met=lambda c: False,
        kind=CONFLICT,
    ),
]


def _auto_minor_types():
    from routes.field_types import AUTO_MINOR_TYPES
    return AUTO_MINOR_TYPES


def _asks_everyone(field):
    """這一題勾了「每個人都要填」嗎（＝不靠年齡判斷）。

    ★ 判斷只有一份（`routes/guardian.condition_mark`）—— 在這裡自己
      比一次 `'everyone'` 的話，印記換形狀時這條會安靜地繼續用舊的比。
    """
    from routes.guardian import EVERYONE, condition_mark
    return condition_mark(field.get('condition_json')) == EVERYONE


def unmet(module, ctx):
    """這個 ctx 底下，哪幾條關係現在成立但沒被滿足。

    回 `[Dep, …]`，照 `DEPENDENCIES` 的順序（＝畫面上出現的順序，
    不是嚴重程度）。

    ★ predicate 丟例外時**當成「沒問題」跳過**，不要讓整個存檔壞掉。
      一條提示壞了不該讓人存不了活動 —— 那是加值的東西
      （跟小舟、稽核日誌同一個原則）。
    """
    out = []
    for dep in DEPENDENCIES:
        if dep.module != module:
            continue
        try:
            if dep.applies(ctx) and not dep.met(ctx):
                out.append(dep)
        except Exception:
            continue
    return out


def entries(module, ctx):
    """`unmet` 的結果加上「給人看的那句話」，帶著 `key`。

    ★ 為什麼要帶 key：表單上的即時提示要把每一句話放到**對應的設定旁邊**
      （勾候補的那一格旁邊講候補的事）。只回字串的話，前端只能全部堆在
      一個地方 —— 而那正是「存好了才跳 alert」在做的事，換個位置而已。

    ★ 字怎麼寫只有這裡一份（`messages` 也是呼叫這支）。前端自己拼一份的話，
      改了 `effect` 畫面上不會跟，而兩邊看起來都正常。
    """
    out = []
    for dep in unmet(module, ctx):
        needs = dep.needs(ctx) if callable(dep.needs) else dep.needs
        if dep.kind == CONFLICT:
            text = f'⚠️ 「{dep.label}」和{needs}同時設定了。{dep.effect}'
        elif dep.kind == MISMATCH:
            #  `needs` 在這一種是**一整句話**，不是一個名詞
            text = f'⚠️ 「{dep.label}」{needs}。{dep.effect}'
        else:
            text = f'⚠️ 開了「{dep.label}」但還沒有{needs}。{dep.effect}'
        out.append({'key': dep.key, 'label': dep.label,
                    'text': text, 'blocks': dep.blocks})
    return out


def messages(module, ctx):
    """給人看的字串清單。**一律「設定 → 需要 → 後果」三段**。

    ★ 只講「缺了什麼」的話，他不知道要不要理它。後果那一段才是
      讓他決定「現在處理」還是「我知道，故意的」的依據。
    """
    return [e['text'] for e in entries(module, ctx)]


def blocking(module, ctx):
    """裡面**該擋存檔**的那幾條。"""
    return [d for d in unmet(module, ctx) if d.blocks]
