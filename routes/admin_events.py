"""活動後台的純邏輯（不碰資料庫，測試可直接 import）

成熟版這個檔案還含引導式開活動的路由；這裡先只放存檔時要用的判斷。
"""


def _apply_guardian_conditions(fields):
    """監護人欄位：沒設條件就自動套用「未滿18歲才問」。

    ★ 預設不用設，但要設得了

      使用者的要求是「後台表單設定不要太複雜」—— 所以預設情況下管理員
      什麼都不用做：加欄位、型別選監護人、勾必填，結束。

      但**面板不能拿掉**。有些活動的規則本來就不一樣（兒童營可能全部
      都要填、水上活動可能是「選了獨木舟才問」）。拿掉的話那些活動
      就只能繞路，而繞路的做法一定比較差。

    ★ 所以規則是：自己設的優先，沒設才自動補。

      自動補上去的那條會帶 `auto: 'minor'` 印記。有印記的才會在存檔時
      重新產生 —— 因為欄位順序改過之後，舊的 trigger_sort_order 會指到
      別的問題上，而畫面完全正常。沒有印記的是管理員自己設的，一個字
      都不動；不然他每次存檔都會發現自己的設定被吃掉，而且沒有訊息。

    ★ trigger_sort_order 是「畫面上的第幾題」（濾掉舊的 group 型別、
      濾掉還沒打名字的空列），跟三份報名表單的 data-sort-order 一致。

    fields : 前端送上來的欄位陣列（會就地修改）
    回 錯誤訊息字串，沒問題回 None。
    """
    import json as _json

    from routes.field_types import AUTO_MINOR_TYPES
    from routes.guardian import MINOR, MINOR_MAX_AGE

    visible = [f for f in fields
               if f.get('label') and f.get('field_type') != 'group']
    guardians = [f for f in visible if f.get('field_type') in AUTO_MINOR_TYPES]
    if not guardians:
        return None

    def needs_auto(f):
        raw = f.get('condition_json')
        if not raw:
            return True                      # 沒設 → 自動補
        try:
            cond = raw if isinstance(raw, dict) else _json.loads(raw)
        except (ValueError, TypeError):
            return True
        #  有 minor 印記 → 是上次自動補的，重新產生（修正順序改過的 index）
        #
        #  ★ 比的是 `MINOR` 而不是「有沒有 auto 印記」。「每個人都問」
        #    （`auto: 'everyone'`）也是一個印記，但那是**管理員選的**，
        #    不是系統補的 —— 一起吃掉的話，他勾了「每個人都要填」、存檔，
        #    系統把「未滿18歲」補回去，而後台看起來設好了，
        #    只有 18 歲以上的人看不到那一題。
        return isinstance(cond, dict) and cond.get('auto') == MINOR

    targets = [f for f in guardians if needs_auto(f)]
    if not targets:
        return None                          # 全部都是管理員自己設的

    birthday_index = next(
        (i for i, f in enumerate(visible) if f.get('field_type') == 'birthday'), None)
    if birthday_index is None:
        # 沒有生日就算不出年齡 —— 那題會永遠不出現，而後台看起來設好了。
        # 訊息要講「該做什麼」，不是「哪裡錯了」。
        #  ★ 要把「每個人都要填」講出來 —— 兒童營那種活動根本不想問生日，
        #    只寫「請加一個出生日期欄位」的話，他會為了過這一關加一題
        #    他不需要的問題（然後那一題還會被填錯）。
        return ('「監護人」預設只問未滿18歲的人，需要靠出生日期判斷 —— '
                '請先加一個「出生日期」欄位，'
                '或在那一題勾「這一題每個人都要填」，'
                '或自己設一個跳題條件。')

    cond = _json.dumps({'trigger_sort_order': birthday_index,
                        'op': 'age_between', 'min': None,
                        'max': MINOR_MAX_AGE, 'auto': MINOR})
    for f in targets:
        f['condition_json'] = cond
    return None
