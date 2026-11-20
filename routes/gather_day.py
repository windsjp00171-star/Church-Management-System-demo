"""小組聚會日（cell_groups.weekly_gather_day）的判讀，讀取一律走這裡。

資料裡有兩種寫法：舊資料與其他頁面用中文（「五」「週五」「星期五」），後台新增小組曾經存成數字
（"0"＝週日…"6"＝週六）。以前各處只認中文，數字的小組回報日期會被算成主日、畫面顯示「每週5聚會」。
"""

_CHARS = '一二三四五六日'          # 索引＝Python weekday（週一＝0）
_DIGITS = {'0': '日', '1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六'}


def day_char(value) -> str:
    """回傳「一」…「日」；看不懂（含空白）回空字串。"""
    s = '' if value is None else str(value).strip()
    if s in _DIGITS:
        return _DIGITS[s]
    for ch in _CHARS:
        if ch in s:
            return ch
    return '日' if '天' in s else ''


def weekday(value):
    """Python weekday（週一＝0…週日＝6）；看不懂回 None。"""
    ch = day_char(value)
    return _CHARS.index(ch) if ch else None


def label(value) -> str:
    """畫面用的「週五」；看不懂回空字串。"""
    ch = day_char(value)
    return f'週{ch}' if ch else ''
