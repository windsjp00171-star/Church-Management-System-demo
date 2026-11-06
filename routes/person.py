"""「人」的建立與疑似重複檢查（users 表的單一入口之一）。

為什麼有這一支：手動建立會員（尚未註冊 LINE 的家人先開一個空容器，之後再用「整合 LINE」合併）
最常見的失誤是同一個人建兩次，之後合併時才發現要處理兩個容器。建立前先把「疑似同一個人」攤給管理員看。

規則：
- 只比姓名。系統沒有電話／身分證可比；同名的人不少，所以疑似重複只是『請你確認』，不是擋下來。
- 名字至少 3 個字才比『差一個字』（兩個字的名字差一個字太容易誤判）。
- 比對用的正規化（全形半形、空白、大小寫）與點名名冊共用同一支 norm_name。
"""
from db import supabase
from roll_call_logic import norm_name, within_one_edit

PAGE = 1000
MEMBER_TYPES = ('member', 'visitor')


def _all_people():
    """分頁讀完所有人（PostgREST 一次最多 1000 筆）。讀取失敗直接丟例外，不當成『沒有重複』。"""
    rows, offset = [], 0
    while True:
        batch = supabase.table('users').select('id, real_name, display_name, line_user_id, member_type')\
            .range(offset, offset + PAGE - 1).execute().data or []
        rows += batch
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def find_possible_duplicates(name, exclude_id=None):
    """回傳疑似同一個人的清單：[{'id','real_name','display_name','has_line','member_type','reason'}]"""
    key = norm_name(name)
    if not key:
        return []
    out = []
    for u in _all_people():
        if exclude_id and u['id'] == exclude_id:
            continue
        real, disp = norm_name(u.get('real_name')), norm_name(u.get('display_name'))
        if real == key or disp == key:
            reason = '姓名相同'
        elif len(key) >= 3 and len(real) >= 3 and within_one_edit(real, key):
            reason = '姓名只差一個字'
        else:
            continue
        out.append({'id': u['id'], 'real_name': u.get('real_name'), 'display_name': u.get('display_name'),
                    'has_line': bool(u.get('line_user_id')), 'member_type': u.get('member_type'),
                    'reason': reason})
    return out


def create_person(name, member_type='member', force=False):
    """建立沒有 LINE 帳號的人。回傳 ('created', row) 或 ('duplicates', [...])。
    有疑似重複且沒有 force → 不建立，把清單交回去讓管理員確認。"""
    name = (name or '').strip()
    if not name:
        raise ValueError('請輸入姓名')
    if member_type not in MEMBER_TYPES:
        raise ValueError('身分只能是會友或訪客')
    if not force:
        dups = find_possible_duplicates(name)
        if dups:
            return 'duplicates', dups
    res = supabase.table('users').insert({
        'real_name': name, 'display_name': name, 'member_type': member_type,
    }).execute()
    if not res.data:
        raise RuntimeError('建立失敗')
    return 'created', res.data[0]
