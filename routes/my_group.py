"""「這個人是哪一組」只有一份：牧養小組（`cell_groups` ＋ 已確認的 `cell_members`）。

以前另有一份「主標籤小組」（`groups.is_primary`，存在 `users.group_tags` 裡），兩邊組別可能不一樣，
而禱讀本、門訓名單、首頁版面、收費提醒各讀各的。2026-11-17 起一律讀這裡。
（`groups` 只剩服事團隊／副標籤：同工判斷、權限矩陣、檔案權限照舊。）
"""
import logging

from flask import session

from db import supabase

log = logging.getLogger(__name__)


def names():
    """所有啟用中的牧養小組名稱（依名稱排序）；讀不到回空的。"""
    try:
        rows = supabase.table('cell_groups').select('name').eq('is_active', True).order('name').execute().data or []
    except Exception:                                        # noqa: BLE001
        log.warning('讀牧養小組失敗', exc_info=True)
        return []
    return [r['name'] for r in rows if r.get('name')]


def of_users(user_ids):
    """`{user_id: 小組名稱}`；只算管理員確認過、還在組裡的。一個人只在一組（取第一筆）。"""
    ids = [u for u in dict.fromkeys(user_ids or []) if u]
    if not ids:
        return {}
    try:
        rows = supabase.table('cell_members').select('user_id, cell_groups(name, is_active)')\
            .in_('user_id', ids).eq('is_active', True).eq('is_confirmed', True).execute().data or []
    except Exception:                                        # noqa: BLE001
        log.warning('讀小組成員失敗', exc_info=True)
        return {}
    out = {}
    for r in rows:
        g = r.get('cell_groups') or {}
        if g.get('name') and g.get('is_active', True) and r['user_id'] not in out:
            out[r['user_id']] = g['name']
    return out


def mine():
    """登入者的小組名稱；沒有回 None。"""
    uid = session.get('user_id')
    return of_users([uid]).get(uid) if uid else None
