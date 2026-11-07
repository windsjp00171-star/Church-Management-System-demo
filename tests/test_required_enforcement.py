"""必填：伺服器端也要驗（未成年的監護人就靠這個真的成立）

## 事故的形狀

`is_required` 原本只走到畫面上 —— **伺服器從來沒有看過它**。三種情況會讓
一個未成年人沒有監護人資料就報名成功：JS 沒跑、有人直接打 API、
年齡還沒算回來就送出。三種的共同點都是「畫面正常、名冊正常」。

跟身分證字號同一個理由（`_reject_bad_id_numbers`）：
前端擋得掉手誤，擋不掉「前端根本沒跑」。

## 要不要填由活動自己定

不是寫死的規則。教會旅遊會把監護人設成必填，別的場次不一定。
所以這裡驗的是「有勾必填的欄位有沒有被真的擋住」，
不是「監護人一定要填」。

## 兩個方向都要對

  - 伺服器比前端寬鬆 → 防護等於沒有
  - 伺服器比前端嚴格 → 使用者被擋在一個他**看不到的欄位**上，
    訊息說「還沒填 監護人」而畫面上根本沒有那一題

所以「條件壞掉」的每一種情況，下面都對著 static/js/form-fields.js
的 evaluateConditions 各驗一次。

★ mutation 驗過（把守的東西改壞，確認會紅）：
  - missing_required 不看 visibility（藏起來的必填也擋）
      → test_a_hidden_required_field_is_not_demanded 紅
  - form_fields 不濾掉 group
      → test_legacy_group_fields_do_not_take_an_index 紅
  - form_fields 不自己排序（照資料庫給的順序）
      → test_index_follows_sort_order_not_db_order 紅
  - _bound 改成 falsy 判斷
      → test_zero_is_a_real_lower_bound_on_the_server 紅
  - 條件壞掉時回 False（而不是 True）
      → test_broken_conditions_stay_visible_like_the_front_end 紅
  - 年齡改用送上來的答案而不是自己從生日算
      → test_age_is_recomputed_from_the_birthday_not_trusted 紅
  - 任何一個寫入點沒接上 _reject_missing_required
      → test_every_write_path_checks_required 紅
"""
import json

import pytest

from routes.conditions import form_fields, missing_required, visibility

EVENT = {'id': 'ev-1', 'event_start': '2026-09-01T08:00:00+08:00'}


def field(i, **kw):
    f = {'id': f'f{i}', 'label': f'第{i}題', 'field_type': 'text',
         'sort_order': i, 'is_required': False, 'condition_json': None}
    f.update(kw)
    return f


def age_cond(idx, **kw):
    return json.dumps(dict({'trigger_sort_order': idx, 'op': 'age_between'}, **kw))


def ans(*pairs):
    return [{'field_id': fid, 'answer': v} for fid, v in pairs]


# ── 生日 + 監護人：真正要解的那件事 ──────────────────────────

BIRTHDAY = field(0, field_type='birthday', label='出生年月日', is_required=True)
GUARDIAN = field(1, label='監護人姓名與電話', is_required=True,
                 condition_json=age_cond(0, min=None, max=17))
TRIP = [BIRTHDAY, GUARDIAN]


def test_a_minor_must_fill_in_the_guardian():
    """15 歲（活動當日）→ 監護人那題會出現 → 必填擋住。"""
    missing = missing_required(TRIP, ans(('f0', '2011-05-01')), EVENT)
    assert missing == ['監護人姓名與電話']


def test_an_adult_is_not_asked_for_a_guardian():
    """★ 反向。成年人被要求填一個畫面上沒出現的欄位的話，
    他會看到「還沒填 監護人」而找不到那一格 —— 那比不擋更糟。"""
    assert missing_required(TRIP, ans(('f0', '1990-05-01')), EVENT) == []


def test_a_minor_who_filled_it_in_passes():
    assert missing_required(
        TRIP, ans(('f0', '2011-05-01'), ('f1', '媽媽 0912345678')), EVENT) == []


def test_the_birthday_itself_is_still_required():
    """★ 這條是整條規則能不能成立的關鍵。

    不填生日 → 算不出年齡 → 監護人那題不出現 → 也就不必填。
    如果生日本身沒被擋住，「未成年要填監護人」就等於
    「不想填的人不要填生日就好」，而名冊上完全看不出來。
    （後台在存檔時也會擋這種設定組合，見 test_admin_blocks... 那條。）
    """
    assert missing_required(TRIP, [], EVENT) == ['出生年月日']


def test_age_is_measured_on_the_event_day_here_too():
    """活動當日剛好滿 18 → 不用監護人；用今天算的話還是 17。"""
    # 活動 2026-09-01，生日 2008-08-20 → 活動當日 18 歲
    assert missing_required(TRIP, ans(('f0', '2008-08-20')), EVENT) == []


def test_age_is_recomputed_from_the_birthday_not_trusted():
    """★ 送上來的東西一律不信。

    如果伺服器改成讀某個「年齡」答案，任何人都能送一個 30 上來
    讓監護人那題消失 —— 而畫面與名冊都完全正常。
    這裡送一個假的年齡欄位答案，結果必須完全不受影響。
    """
    fields = TRIP + [field(2, label='年齡', is_required=False)]
    missing = missing_required(
        fields, ans(('f0', '2011-05-01'), ('f2', '30')), EVENT)
    assert missing == ['監護人姓名與電話']


# ── 必填只對「看得見」的欄位成立 ──────────────────────────

def test_a_hidden_required_field_is_not_demanded():
    """被跳題藏起來的必填欄位不算 —— 那一題報名者根本看不到。"""
    fields = [field(0, field_type='radio', label='要不要訂餐'),
              field(1, label='素食或葷食', is_required=True,
                    condition_json=json.dumps(
                        {'trigger_sort_order': 0, 'trigger_value': '要'}))]
    assert missing_required(fields, ans(('f0', '不要')), EVENT) == []
    assert missing_required(fields, ans(('f0', '要')), EVENT) == ['素食或葷食']


def test_an_optional_field_is_never_demanded():
    fields = [field(0, label='備註', is_required=False)]
    assert missing_required(fields, [], EVENT) == []


def test_whitespace_is_not_an_answer():
    """空白鍵填的不算填 —— 名冊上那格看起來有東西，其實什麼都沒有。"""
    fields = [field(0, label='緊急聯絡人', is_required=True)]
    assert missing_required(fields, ans(('f0', '   ')), EVENT) == ['緊急聯絡人']


def test_missing_fields_come_back_in_screen_order():
    """訊息要照畫面順序講，不然使用者得自己在表單上跳來跳去找。"""
    fields = [field(0, label='姓名', is_required=True),
              field(1, label='電話', is_required=True),
              field(2, label='地址', is_required=True)]
    assert missing_required(fields, ans(('f1', '0912')), EVENT) == ['姓名', '地址']


# ── 索引基準：trigger_sort_order 是「畫面上的第幾題」 ──────────────────────────

def test_legacy_group_fields_do_not_take_an_index():
    """★ 舊的 group 欄位在三份報名表單都被迴圈濾掉，所以它不佔一格。

    伺服器沒濾的話，索引全部往後位移一格 —— 條件會指到**別的問題**上，
    而畫面完全正常，只是某一題該出現的時候沒出現。
    """
    fields = [field(0, field_type='group', label='小組別'),
              field(1, field_type='birthday', label='出生年月日'),
              field(2, label='監護人', is_required=True,
                    condition_json=age_cond(0, max=17))]   # 0 = 濾掉 group 之後的生日
    assert [f['id'] for f in form_fields(fields)] == ['f1', 'f2']
    assert missing_required(fields, ans(('f1', '2011-05-01')), EVENT) == ['監護人']


def test_index_follows_sort_order_not_db_order():
    """★ 資料庫回傳的順序不保證。

    _enforce_auto_tiers 撈欄位時就沒有 .order('sort_order')，照抄那段的話
    索引會**隨機**跟前端對不上（今天對、明天不對）。
    """
    a = field(0, field_type='birthday', label='出生年月日')
    b = field(1, label='監護人', is_required=True, condition_json=age_cond(0, max=17))
    shuffled = [b, a]                       # 資料庫先給了第二題
    assert [f['id'] for f in form_fields(shuffled)] == ['f0', 'f1']
    assert missing_required(shuffled, ans(('f0', '2011-05-01')), EVENT) == ['監護人']


# ── 條件壞掉時要跟前端一樣「維持顯示」 ──────────────────────────

@pytest.mark.parametrize('cond, why', [
    (None,                                    '沒有條件'),
    ('{壞掉的 json',                           'JSON 壞掉，前端 catch 之後不動'),
    (json.dumps({'trigger_sort_order': 99, 'trigger_value': 'x'}), '找不到觸發問題'),
    (json.dumps({'trigger_sort_order': 0}),    '文字條件但沒有 trigger_value'),
])
def test_broken_conditions_stay_visible_like_the_front_end(cond, why):
    """★ 壞掉時的預設是**顯示**，不是隱藏 —— 前端 evaluateConditions
    在這幾種情況都是 return（不碰 display，維持模板的預設＝看得見）。

    伺服器反過來當成隱藏的話，一個畫面上真的出現過、而且必填的欄位
    會在伺服器端被當成不存在 —— 防護悄悄消失。
    """
    fields = [field(0, field_type='radio', label='第一題'),
              field(1, label='必填題', is_required=True, condition_json=cond)]
    assert visibility(fields, [], EVENT)['f1'] is True, why
    assert missing_required(fields, [], EVENT) == ['必填題'], why


@pytest.mark.parametrize('cond', [
    {'min': None, 'max': None},     # 上下限都沒設 ＝ 沒設定完
])
def test_age_conditions_without_bounds_stay_hidden(cond):
    """★ 年齡條件是唯一「壞掉就藏起來」的一種，跟前端一致。

    解讀成「符合所有年齡」的話，那題會對每個人跳出來並要求填寫。
    """
    fields = [field(0, field_type='birthday', label='生日'),
              field(1, label='必填題', is_required=True,
                    condition_json=age_cond(0, **cond))]
    assert missing_required(fields, ans(('f0', '2011-05-01')), EVENT) == []


def test_unknown_age_hides_the_field_on_the_server_too():
    """生日沒填 → 年齡未知 → 那題不出現 → 不擋。

    （前端在「未知」時是藏但不清答案；伺服器只需要不擋。
      兩邊對外的行為一致：使用者不會被一個看不到的欄位擋住。）
    """
    fields = [field(0, field_type='birthday', label='生日'),
              field(1, label='監護人', is_required=True, condition_json=age_cond(0, max=17))]
    assert missing_required(fields, [], EVENT) == []


def test_zero_is_a_real_lower_bound_on_the_server():
    """★ 只設 min:0 —— 用 falsy 判斷的話會被當成「沒設下限」，
    於是上下限都沒設 → 那題被當成隱藏 → 必填悄悄失效。"""
    fields = [field(0, field_type='birthday', label='生日'),
              field(1, label='必填題', is_required=True, condition_json=age_cond(0, min=0))]
    assert missing_required(fields, ans(('f0', '2011-05-01')), EVENT) == ['必填題']


@pytest.mark.parametrize('birthday, expected', [
    ('2008-09-01', []),                  # 活動當日剛好 18 → 不用填
    ('2008-09-02', ['監護人']),           # 差一天，還沒滿 18 → 要填
])
def test_the_boundary_is_the_day_they_turn_eighteen(birthday, expected):
    """滿 18 歲那一天就不算未成年。差一天的兩個人要落在不同邊。"""
    fields = [field(0, field_type='birthday', label='生日'),
              field(1, label='監護人', is_required=True,
                    condition_json=age_cond(0, min=None, max=17))]
    assert missing_required(fields, ans(('f0', birthday)), EVENT) == expected


def test_no_event_date_does_not_crash():
    """活動還沒填日期 → age_on 退回今天。算得出來就好，不可以炸。"""
    fields = [field(0, field_type='birthday', label='生日'),
              field(1, label='監護人', is_required=True, condition_json=age_cond(0, max=17))]
    assert isinstance(
        missing_required(fields, ans(('f0', '2011-05-01')), {'id': 'e', 'event_start': None}),
        list)


def test_no_fields_at_all_is_fine():
    assert missing_required([], [], EVENT) == []
    assert missing_required(None, None, EVENT) == []


# ── 每一個寫入點都要接上 ──────────────────────────

def test_every_write_path_checks_required():
    """★ 漏掉一個寫入點，那個入口就是繞過必填的方法。

    用列舉而不是數次數 —— 數字對就過的話，新增寫入點時
    有人會把數字加一了事。
    """
    from tests.test_auto_tier import _answer_writers
    for path, fn in _answer_writers():
        assert '_reject_missing_required(' in fn, \
            f'{path} 有一個寫入答案的地方沒有驗必填'


def test_the_error_says_which_fields():
    """只講「請填寫所有必填欄位」的話，剛因為年齡跳出來的那一題
    使用者根本不知道在講哪一格。"""
    src = open('routes/event.py', encoding='utf-8').read()
    fn = src[src.index('def _reject_missing_required'):]
    fn = fn[:fn.index('\ndef ')]
    assert "'、'.join(missing)" in fn


# ── 後台擋掉「可以被繞過」的設定 ──────────────────────────

