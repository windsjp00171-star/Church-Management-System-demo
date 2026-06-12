"""帳號合併共用邏輯 — 將一個帳號的所有關聯紀錄移轉到另一個帳號。

供管理員整合（admin.py）與會友自助合併（profile.py）共用。
清單由 schema.sql 盤點產生：所有 REFERENCES users(id) 的欄位。
注意：diary_entries / diary_share_grants / admin_whitelist 以 line_user_id（文字）
為鍵，LINE 身份移轉後自動跟隨，無需在此處理。
"""
import logging
from db import supabase

logger = logging.getLogger(__name__)

# user_id 標準欄位的表
USER_ID_TABLES = [
    'cell_group_leaders', 'cell_members', 'course_attendance',
    'course_certificates', 'course_certifications', 'course_enrollments',
    'daily_verse_draws', 'group_members', 'leave_requests', 'notifications',
    'overtime_records', 'personal_events', 'prayer_comments',
    'prayer_reactions', 'prayers', 'registration_whitelist',
    'registrations', 'staff_profiles',
]

# 非標準欄位名的表：(表名, 欄位名)
ALT_COLUMNS = [
    ('church_events', 'created_by'),
    ('course_certificates', 'created_by'),
    ('course_certifications', 'created_by'),
    ('courses', 'created_by'),
    ('devotional_registration_logs', 'changed_by'),
    ('devotional_registrations', 'registered_by'),
    ('events', 'created_by'),
    ('files', 'owner_id'),
    ('folders', 'created_by'),
    ('leave_requests', 'reviewed_by'),
    ('material_transactions', 'created_by'),
    ('overtime_records', 'reviewed_by'),
    ('user_groups', 'created_by'),
    ('visitor_forms', 'created_by'),
    ('week_notes', 'created_by'),
    ('weekly_bulletins', 'created_by'),
]


def transfer_user_records(old_id: str, new_id: str) -> list:
    """把 old_id 名下所有關聯紀錄改掛到 new_id。

    個別表失敗不中斷（例如 staff_profiles 的 UNIQUE 衝突、複合主鍵重複），
    回傳失敗的表清單供呼叫端記錄。
    """
    failed = []
    for tbl in USER_ID_TABLES:
        try:
            supabase.table(tbl).update({'user_id': new_id}).eq('user_id', old_id).execute()
        except Exception:
            failed.append(tbl)
            logger.warning('帳號合併：%s 移轉失敗（可能為 UNIQUE 衝突）', tbl, exc_info=True)
    for tbl, col in ALT_COLUMNS:
        try:
            supabase.table(tbl).update({col: new_id}).eq(col, old_id).execute()
        except Exception:
            failed.append(f'{tbl}.{col}')
            logger.warning('帳號合併：%s.%s 移轉失敗', tbl, col, exc_info=True)
    return failed
