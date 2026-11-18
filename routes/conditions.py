"""跳題條件與必填：伺服器端求值（權威）

## 事故的形狀（還沒發生，但這裡就是它會發生的地方）

「未成年要填監護人」原本只有前端在管：跳題條件把欄位藏起來／顯示出來，
必填檢查也在前端。伺服器**從來沒有檢查過必填** —— `is_required` 只被
寫進資料庫、渲染到畫面上，沒有任何一個寫入點看過它。

那表示三種情況會讓一個未成年人**沒有監護人資料就報名成功**：

  1. JS 沒跑（舊瀏覽器、LINE WebView 的怪狀況、擋廣告的擴充套件）
  2. 有人直接打 API
  3. 前端的年齡還沒算回來就送出

而這三種的共同點是：**畫面正常、名冊正常**。要等出事那一天，
才發現名冊上那個未成年人的監護人欄位是空的。

跟身分證字號同一個理由（`_reject_bad_id_numbers`）：
前端擋得掉手誤，擋不掉「前端根本沒跑」。

## 為什麼必填要看得見才算

一個被跳題藏起來的欄位當然不能要求人填 —— 他根本看不到那一題。
所以必填檢查一定要先知道「這一題現在該不該出現」，也就是要在伺服器端
把跳題條件重新求一次值。這支模組就是那個求值器。

## ★ 索引的基準：trigger_sort_order 是「畫面上的第幾題」

不是 `event_fields.sort_order` 那個欄位的值。三份報名表單都是

    {% for field in fields if field.field_type != 'group' %}
      data-sort-order="{{ loop.index0 }}"

所以基準是「濾掉 group 之後、依 sort_order 排好的位置」。
過濾條件或排序跟前端不一樣的話，條件會指到**別的問題**上 ——
而畫面完全正常，只是某一題該出現的時候沒出現（或反過來）。

★ 特別注意排序：`_enforce_auto_tiers` 撈欄位時**沒有** `.order('sort_order')`，
  順序是資料庫給什麼算什麼。照抄那段的話，索引會跟前端對不上，
  而且是隨機對不上（今天對、明天不對）。所以這裡自己排一次。

## ★ 求值結果必須跟前端一模一樣

不一致的方向有兩種，都很糟：

  - 伺服器比前端寬鬆 → 防護等於沒有
  - 伺服器比前端嚴格 → 使用者被擋在一個他**看不到的欄位**上，
    錯誤訊息說「還沒填 監護人」，而畫面上根本沒有那一題

所以「條件壞掉」的每一種情況，這裡的行為都刻意對齊
`static/js/form-fields.js` 的 `evaluateConditions`：

  | 情況 | 前端 | 這裡 |
  |------|------|------|
  | 沒有 condition_json | 不動 → 顯示 | True |
  | JSON 壞掉 | `catch` → 不動 → 顯示 | True |
  | 找不到觸發問題 | `return` → 不動 → 顯示 | True |
  | 文字條件但沒有 trigger_value | `return` → 不動 → 顯示 | True |
  | 年齡算不出來 | 藏 | False |
  | 年齡上下限都沒設 | 藏 | False |

★ 「顯示」是壞掉時的預設，不是「隱藏」。藏起來的話，一個設定壞掉的
  條件會讓那題從報名表上消失而沒有人發現；顯示的話至少看得到。
  `tests/test_required_enforcement.py` 兩邊各守一次。
"""
import json


def _bound(v):
    """空白 → None（不限）。★ 0 是有效的界線，不可以用 falsy 判斷。"""
    if v is None or v == '':
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def form_fields(fields):
    """報名表上真的會出現的欄位，依畫面順序。索引 ＝ trigger_sort_order。

    group 是已經拿掉的舊型別（見 tests/test_group_column.py）。舊活動的
    資料庫裡還留著，三份報名表單都在迴圈就把它濾掉，所以它**不佔一格**。
    """
    ordered = [f for f in (fields or []) if f.get('field_type') != 'group']
    # sorted 是穩定排序，所以 sort_order 相同時維持原本的順序 ——
    # 跟前端拿到的（已經 .order('sort_order') 過的）結果一致。
    return sorted(ordered, key=lambda f: (f.get('sort_order') is None,
                                          0 if f.get('sort_order') is None else f.get('sort_order')))


def _answers_by_id(answers):
    out = {}
    for a in (answers or []):
        fid = a.get('field_id')
        if fid:
            out[fid] = str(a.get('answer') or '').strip()
    return out


def _is_visible(field, by_index, ans, basis):
    from routes.roc import age_on

    raw = field.get('condition_json')
    if not raw:
        return True
    cond = raw
    if isinstance(cond, str):
        try:
            cond = json.loads(cond)
        except (ValueError, TypeError):
            return True              # 前端 catch 之後也是維持顯示
    if not isinstance(cond, dict):
        return True

    #  ★ 「每個人都問」（`routes/guardian.everyone_condition`）。
    #
    #    它沒有 trigger，所以就算沒有這一行，下面「找不到觸發問題 → 顯示」
    #    也會給出同一個答案。**但那是靠壞掉時的預設行為剛好正確** ——
    #    哪天有人把那個預設收緊成「藏起來」（看起來很合理：一個指向
    #    空氣的條件本來就可疑），兒童營的監護人那一題會從報名表上
    #    整個消失，而後台完全看不出來。寫成明確的一條就不會。
    from routes.guardian import EVERYONE
    if cond.get('auto') == EVERYONE:
        return True

    idx = cond.get('trigger_sort_order')
    trigger = by_index.get(idx) if isinstance(idx, int) else None
    if trigger is None and cond.get('trigger_field_id'):
        # 舊資料可能只有 trigger_field_id（前端也還認這個 key）
        trigger = next((f for f in by_index.values()
                        if f.get('id') == cond['trigger_field_id']), None)
    if trigger is None:
        return True

    if cond.get('op') == 'age_between':
        # ★ 年齡在這裡自己算，不看送上來的任何東西。基準日是活動當日，
        #   跟身分別共用 routes/roc.age_on —— 那正是「只有一份實作」的意思。
        age = age_on(ans.get(trigger['id']) or '', basis)
        if age is None:
            return False
        lo, hi = _bound(cond.get('min')), _bound(cond.get('max'))
        if lo is None and hi is None:
            return False
        if lo is not None and age < lo:
            return False
        if hi is not None and age > hi:
            return False
        return True

    value = cond.get('trigger_value')
    if not value:
        return True
    return ans.get(trigger['id'], '') == value


def visibility(fields, answers, event):
    """每個欄位在這份答案下看不看得見 → {field_id: bool}"""
    from routes.auto_tier import event_basis_date

    ordered = form_fields(fields)
    by_index = dict(enumerate(ordered))
    ans = _answers_by_id(answers)
    basis = event_basis_date(event)
    return {f['id']: _is_visible(f, by_index, ans, basis) for f in ordered}


def _is_answered(field, value):
    """這一格算不算填了。

    ★ 監護人要**姓名和電話都有**才算。只驗非空的話，只填姓名就會通過 ——
      而名冊上那一列有名字沒電話，出事那天打不到人。
      規則跟前端的 isFieldFilled 是同一條（兩邊有測試對著同一組輸入）。
    """
    if not value:
        return False
    if field.get('field_type') == 'guardian':
        from routes.guardian import is_complete
        return is_complete(value)
    return True


def missing_required(fields, answers, event):
    """看得見、必填、卻沒填的欄位 → [欄位標籤]（依畫面順序）

    ★ 藏起來的必填欄位不算。那一題報名者根本看不到，
      擋他等於用一個他無從處理的理由把人擋在門外。
    """
    seen = visibility(fields, answers, event)
    ans = _answers_by_id(answers)
    return [f.get('label') or '（未命名欄位）'
            for f in form_fields(fields)
            if f.get('is_required') and seen.get(f['id'])
            and not _is_answered(f, ans.get(f['id']))]
