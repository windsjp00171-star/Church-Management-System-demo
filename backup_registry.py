"""備份／匯出登記表：每一張資料表都要在這裡表態 —— 備份，或排除（附理由）。

為什麼要有這張表：
  原本的匯出清單是手寫的，漏了十幾張表（稽核、點名、禱讀本、天父日記設定…），
  匯入順序也是另一份手寫清單，還混進了一個檢視表（只能讀、不能寫）。
  新增一張資料表卻忘了加進備份，**沒有任何地方會紅**，要到災難那天才發現沒有備份到。

規則：
  1. `schema.sql` 的每一張資料表，必須「在 TABLES 裡」或「在 EXCLUDED 裡（並寫理由）」，兩者之一。
  2. TABLES 的順序就是匯入順序：**父表在前、子表在後**（測試掃 schema 的外鍵逐一驗證）。
  3. 每張表登記它的主鍵（匯入時 upsert 的衝突欄位），測試對照 schema 的真實主鍵。
  4. 檢視表（VIEWS）是由別的表算出來的，不備份。
  5. 排除的表要有理由；理由是「隱私」時，要明講「超管匯出檔不應含有」。
"""

# (資料表, 匯出模組, upsert 衝突欄位)；順序＝匯入順序（父表在前）
TABLES = [
    # ── 會友與標籤 ──
    ('users', 'members', 'id'),
    ('groups', 'members', 'id'),
    ('user_groups', 'members', 'id'),
    ('group_members', 'members', 'group_id,user_id'),
    # ── 系統設定與首頁 ──
    ('settings', 'settings', 'key'),
    ('portal_card_settings', 'settings', 'id'),
    ('portal_links', 'settings', 'id'),
    ('portal_cards', 'settings', 'id'),
    # ── 活動 ──
    ('events', 'events', 'id'),
    ('event_fields', 'events', 'id'),
    ('registrations', 'events', 'id'),
    ('registration_answers', 'events', 'id'),
    ('registration_whitelist', 'events', 'id'),
    # ── 門訓學程與教材 ──
    ('course_categories', 'courses', 'id'),
    ('courses', 'courses', 'id'),
    ('course_sessions', 'courses', 'id'),
    ('course_enrollments', 'courses', 'id'),
    ('course_certifications', 'courses', 'id'),
    ('course_certificates', 'courses', 'id'),
    ('session_attendance', 'courses', 'id'),
    ('materials', 'courses', 'id'),
    ('material_transactions', 'courses', 'id'),
    # ── 小組回報 ──
    ('cell_groups', 'cell_groups', 'id'),
    ('cell_members', 'cell_groups', 'id'),
    ('cell_group_leaders', 'cell_groups', 'id'),
    ('cell_reports', 'cell_groups', 'id'),
    ('cell_attendance', 'cell_groups', 'id'),
    # ── 代禱 ──
    ('prayers', 'prayer', 'id'),
    ('prayer_comments', 'prayer', 'id'),
    ('prayer_reactions', 'prayer', 'id'),
    # ── 行事曆、週報 ──
    ('church_events', 'calendar', 'id'),
    ('personal_events', 'calendar', 'id'),
    ('weekly_bulletins', 'bulletin', 'id'),
    ('week_notes', 'bulletin', 'id'),
    # ── 福音探索 ──
    ('gospel_cards', 'gospel', 'id'),
    ('gospel_form_questions', 'gospel', 'id'),
    ('gospel_inquiries', 'gospel', 'id'),
    # ── 聚會人數 ──
    ('sunday_reports', 'meeting_reports', 'id'),
    ('children_sunday_reports', 'meeting_reports', 'id'),
    ('prayer_reports', 'meeting_reports', 'id'),
    ('morning_prayer_reports', 'meeting_reports', 'id'),
    ('custom_meeting_reports', 'meeting_reports', 'id'),
    # ── 全職同工差勤 ──
    ('staff_profiles', 'staff_leave_mgmt', 'id'),
    ('leave_requests', 'staff_leave_mgmt', 'id'),
    ('overtime_records', 'staff_leave_mgmt', 'id'),
    # ── 禱讀本 ──
    ('devotional_orders', 'devotional', 'id'),
    ('devotional_registrations', 'devotional', 'id'),
    ('devotional_registration_logs', 'devotional', 'id'),
    # ── 天父日記（只含設定與讀經進度表，不含私人日記）──
    ('diary_plan', 'diary_admin', 'id'),
    ('admin_whitelist', 'diary_admin', 'id'),
    ('pastor_whitelist', 'diary_admin', 'id'),
    # ── 每日經文 ──
    ('daily_verses', 'verses', 'id'),
    ('daily_verse_draws', 'verses', 'id'),
    ('verse_custom_themes', 'verses', 'id'),
    # ── 檔案與留名單（只含資料列；檔案本體在 R2／Supabase Storage，要另外備份）──
    ('folders', 'files', 'id'),
    ('files', 'files', 'id'),
    ('visitor_forms', 'visitor_forms', 'id'),
    ('group_discussions', 'discussions', 'id'),
    # ── 稽核 ──
    ('audit_logs', 'audit', 'id'),
    # ── 聚會點名（與使用者帳號脫鉤）──
    ('rc_meeting_types', 'roll_call', 'id'),
    ('rc_members', 'roll_call', 'id'),
    ('rc_sessions', 'roll_call', 'id'),
    ('rc_records', 'roll_call', 'id'),
    ('rc_guest_counts', 'roll_call', 'session_id'),
    ('rc_rate_rules', 'roll_call', 'id'),
    ('rc_audit', 'roll_call', 'id'),
]

# 刻意不備份的資料表（一定要寫理由）
EXCLUDED = {
    'diary_entries': '隱私：私人靈修日記，超管匯出檔不應含有。要保存請用 Supabase 專案層級的備份。',
    'diary_share_grants': '隱私：誰把日記分享給誰，屬於私人靈修資料，超管匯出檔不應含有。',
    'notifications': '暫時性資料：站內通知，可由系統重新產生，不值得備份。',
    'contact_leads': '展示站專用：洽詢表單紀錄，正式教會部署不會有。',
}

# 檢視表（由別的表算出來，不備份、也不能寫入）
VIEWS = {'material_stock'}

# 匯出模組的顯示資訊（標籤、說明、是否含敏感資料）；表的歸屬由 TABLES 決定
MODULE_META = {
    'members': ('👥 會友資料', '會友基本資料、標籤、分組歸屬（含 LINE ID，建議謹慎保管）', True),
    'settings': ('⚙️ 系統設定', '各種設定、首頁卡片、快捷連結', False),
    'events': ('📅 活動報名', '活動、自訂欄位、報名紀錄與答案', False),
    'courses': ('📚 門訓課程與教材', '課程、場次、報名、出席、認證、教材庫存與進出貨', False),
    'cell_groups': ('🏠 小組回報', '小組、組員、組長、每週回報單、出席記錄', False),
    'prayer': ('🙏 代禱麥田', '代禱事項、回應、回饋', False),
    'calendar': ('🗓 教會行事曆', '公共行事、個人私人事項', True),
    'bulletin': ('📰 每週週報', '週報記錄（不含 PDF 檔案本體）、週記事', False),
    'gospel': ('✝️ 福音探索', '福音卡、問卷題目、詢問記錄', False),
    'meeting_reports': ('📊 聚會人數', '各場聚會出席人數歷史統計', False),
    'staff_leave_mgmt': ('🕐 全職同工差勤', '全職同工資料、請假、加班', False),
    'devotional': ('📖 禱讀本訂購', '訂購、各小組登記、登記變更記錄', False),
    'diary_admin': ('📔 天父日記設定', '讀經進度表與管理員／牧者白名單（不含私人日記）', False),
    'verses': ('✨ 每日經文', '經文、抽經文紀錄、自訂主題', False),
    'files': ('📁 檔案分享', '資料夾與檔案資訊（檔案本體在 R2，要另外備份）', False),
    'visitor_forms': ('📋 留名單', '留名單紀錄（照片在 Supabase Storage，要另外備份）', False),
    'discussions': ('💬 小組討論', '小組討論影片設定', False),
    'audit': ('🧾 稽核日誌', '帳號、權限、合併等操作紀錄', False),
    'roll_call': ('📝 聚會點名', '點名名冊、場次、個人出席、出席率規則與稽核（稽核只能匯入空資料庫，不可覆寫）', True),
}

TABLE_NAMES = [t for t, _m, _c in TABLES]
CONFLICT = {t: c for t, _m, c in TABLES}
MODULE_OF = {t: m for t, m, _c in TABLES}


def export_modules():
    """給匯出頁面用：{模組 key: {label, description, warning, tables}}，表的順序＝匯入順序。"""
    out = {}
    for key, (label, desc, warn) in MODULE_META.items():
        out[key] = {'label': label, 'description': desc, 'warning': warn,
                    'tables': [t for t, m, _c in TABLES if m == key]}
        if not out[key]['warning']:
            del out[key]['warning']
    return out


def is_missing_table(exc) -> bool:
    """這個例外是「資料表還不存在」（例如那個模組的 migration 還沒跑）嗎？
    其他任何失敗（網路、權限、逾時）都不是 —— 那是「讀取失敗」，不可以當成「尚未啟用」。"""
    text = f'{getattr(exc, "code", "")} {exc}'
    return any(k in text for k in ('PGRST205', '42P01', 'does not exist', 'Could not find the table'))
