"""稽核日誌工具 — 記錄關鍵管理與帳號操作，供超管查詢追溯。"""
import logging
from flask import session
from db import supabase

logger = logging.getLogger(__name__)

ACTION_LABELS = {
    # 帳號
    'user.create':           '新增手動帳號',
    'user.merge_line_admin': '管理員整合 LINE',
    'user.merge_line_self':  '會友自助合併 LINE',
    'user.block':            '封鎖帳號',
    'user.unblock':          '解封帳號',
    'user.set_admin':        '設為管理員',
    'user.remove_admin':     '移除管理員',
    'user.set_super_admin':  '設為超管',
    'user.remove_super_admin': '移除超管',
    'user.set_pastor':       '設為牧者',
    'user.remove_pastor':    '移除牧者',
    'user.set_staff':        '設為同工',
    'user.remove_staff':     '移除同工',
    # 活動
    'event.delete':          '刪除活動',
}


def log_action(action: str, target_type: str = None, target_id=None, detail: dict = None):
    """記錄一筆稽核日誌；失敗時僅記 log，不中斷主流程。"""
    try:
        supabase.table('audit_logs').insert({
            'actor_id':    session.get('user_id'),
            'actor_name':  session.get('real_name') or session.get('display_name') or '未知',
            'action':      action,
            'target_type': target_type,
            'target_id':   str(target_id) if target_id else None,
            'detail':      detail,
        }).execute()
    except Exception:
        logger.warning('稽核日誌寫入失敗 action=%s', action, exc_info=True)
