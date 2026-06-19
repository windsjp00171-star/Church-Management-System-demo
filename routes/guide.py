"""
聚焦式功能導覽（In-app Guided Tour）
====================================
系統內建、隨時可看的功能導覽：逐一聚焦各模組（前台 + 後台），一次專注一個，
附「前往體驗」連結。

呈現規則：
  - 前台模組：依 Config 的 ENABLE_* / R2 開關過濾未啟用者。
  - 後台模組：依登入者角色（管理員 / 超級管理員 / 財務）顯示對應步驟。
未啟用或無權限的模組自動不出現於導覽中。

路由：/guide
"""
from flask import Blueprint, render_template, session, redirect, url_for
from config import Config

guide_bp = Blueprint('guide', __name__)


def _front_steps():
    """前台模組（一般會友可見），依功能開關過濾。"""
    raw = [
        (True, 'events', '🎉', '活動報名與簽到', '全會友',
         '瀏覽教會活動、線上報名；活動當天用手機掃 QR Code 即可簽到。', '/events'),
        (True, 'my_history', '🗂', '我的報名紀錄', '全會友',
         '查看自己報名過的活動與課程、繳費與簽到狀態。', '/my-history'),
        (Config.ENABLE_PRAYER, 'prayer', '🙏', '代禱麥田', '全會友',
         '張貼代禱事項、為彼此代禱按讚回應，可匿名；蒙應允後可標記見證。', '/prayer'),
        (True, 'diary', '📖', '天父日記', '全會友',
         '跟著讀經進度寫靈修日記，搭配 AI 反思引導幫助默想。', '/diary'),
        (Config.ENABLE_GOSPEL, 'gospel', '✝️', '福音探索', '慕道朋友',
         '認識信仰的 Q&A 卡片，也可留下聯絡方式由同工跟進關懷。', '/gospel'),
        (True, 'devotional', '📚', '禱讀本訂購', '全會友 / 小組',
         '查看當期禱讀本、由小組登記訂購數量，附簽收與領取管理。', '/devotional'),
        (True, 'cell_report', '🏠', '小組回報', '小組長',
         '小組長每週線上回報出席與組員四面向狀況，牧者後台可彙整查閱。', '/cell-report/portal'),
        (Config.ENABLE_CALENDAR, 'calendar', '📅', '教會行事曆', '全會友',
         '活動、課程、教會行事一頁總覽，掌握近期所有安排。', '/calendar'),
        (Config.ENABLE_COURSES, 'courses', '🎓', '門訓課程', '全會友',
         '瀏覽與報名門訓課程，系統自動追蹤出席與結業認證。', '/courses'),
        (Config.ENABLE_BULLETIN, 'bulletin', '📰', '每週週報', '全會友',
         '線上閱讀每週週報 PDF，不再錯過教會消息。', '/bulletins'),
        (bool(Config.R2_ENDPOINT), 'files', '🗄', '檔案分享', '同工 / 會友',
         '教會內部檔案、詩歌、講義的上傳與分享。', '/files'),
        (True, 'profile', '🙋', '個人主頁與資料', '全會友',
         '維護個人資料、設定自己的首頁顯示內容。', '/profile/homepage'),
    ]
    return [
        {'section': '前台', 'key': k, 'icon': icon, 'name': name,
         'audience': aud, 'desc': desc, 'url': url}
        for enabled, k, icon, name, aud, desc, url in raw if enabled
    ]


def _admin_steps():
    """後台管理模組，依角色（管理員 / 超管 / 財務）過濾。"""
    is_admin = bool(session.get('is_admin') or session.get('is_super_admin'))
    if not is_admin:
        return []
    is_super = bool(session.get('is_super_admin'))

    # 財務權限（沿用後台判斷，失敗則退化為超管才可見）
    try:
        from routes.admin import _has_finance_access
        has_finance = _has_finance_access()
    except Exception:
        has_finance = is_super

    raw = [
        # (顯示條件, key, icon, 名稱, 對象, 說明, 連結)
        (True, 'a_events', '🎟', '活動管理', '管理員',
         '建立 / 編輯活動、設計自訂報名欄位、開啟簽到、即時簽到看板與名單匯出。', '/admin/events'),
        (Config.ENABLE_CALENDAR, 'a_calendar', '📅', '行事曆管理', '管理員',
         '建立教會行事、設定提醒、可一鍵通知全體會友。', '/admin/calendar'),
        (Config.ENABLE_GOSPEL, 'a_gospel', '✝️', '福音關懷後台', '管理員',
         '查看慕道朋友詢問、跟進關懷，並自訂福音探索 Q&A 內容。', '/admin/gospel'),
        (Config.ENABLE_VISITOR_FORMS, 'a_visitor', '📋', '留名單管理', '管理員',
         '管理新朋友留名單照片與資料。', '/admin/visitor-forms'),
        (Config.ENABLE_COURSES, 'a_courses', '📚', '門訓課程管理', '管理員',
         '課程與堂次、出席追蹤、學程認證、各小組門訓總覽。', '/admin/courses'),
        (Config.ENABLE_COURSES, 'a_materials', '📦', '教材庫存', '管理員',
         '教材進銷存追蹤與庫存記錄。', '/admin/materials'),
        (True, 'a_devotional', '📖', '禱讀本管理', '管理員',
         '開立訂購、上傳封面、設截止日、各小組登記與簽收管理。', '/admin/devotional'),
        (True, 'a_backup', '🗄', '資料備份中心', '管理員',
         '一鍵匯出各模組 CSV / 打包 ZIP / HTML 離線閱讀器 —— 教會資料自主的保險。', '/admin/backup'),
        # 財務
        (has_finance, 'a_payments', '🧾', '收款對帳報表', '財務',
         '付款明細、手續費估算、匯出 CSV；另含金流設定（綠界 / LINE Pay / 手動）。', '/admin/payments'),
        # 超級管理員
        (is_super, 'a_users', '👥', '會員管理', '超級管理員',
         '查看所有會友、設定服事標籤與權限、封鎖 / 解封帳號。', '/admin/users'),
        (is_super, 'a_groups', '🎼', '服事團隊', '超級管理員',
         '管理教會各服事部門 / 角色分類標籤。', '/admin/groups'),
        (is_super, 'a_cellgroups', '🏠', '牧養小組設定', '超級管理員',
         '建立小組、指派小組長、管理組員與自選申請審核。', '/admin/cell-groups'),
        (is_super, 'a_diary_admin', '📖', '天父日記後台', '超級管理員',
         '管理讀經進度、牧者白名單與日記後台白名單。', '/diary/admin'),
        (is_super, 'a_verses', '🎴', '每日經文', '超級管理員',
         '管理每日祝福經文庫。', '/admin/verses'),
        (is_super, 'a_portal', '🏠', '首頁內容設定', '超級管理員',
         '調整功能卡片、快捷連結、各小組首頁顯示預設。', '/admin/portal-cards'),
        (Config.ENABLE_BULLETIN and is_super, 'a_bulletins', '📰', '週報管理', '超級管理員',
         '上傳與管理每週週報 PDF。', '/admin/bulletins'),
        (is_super, 'a_discussions', '▶', '小組討論', '超級管理員',
         '排程本週影片與小組討論問題。', '/admin/group-discussions'),
        (is_super, 'a_announce', '📢', '公告廣播', '超級管理員',
         '一鍵發送站內通知給全體會友。', '/admin/announcements'),
        (is_super, 'a_attendance', '🗓', '差勤管理', '超級管理員',
         '全職同工請假 / 加班審核、特休補休時數管理。', '/admin/attendance'),
        (is_super, 'a_datatransfer', '🔄', '資料匯出 / 匯入', '超級管理員',
         '整庫 JSON 打包匯出與還原，用於備份或遷移到新教會。', '/admin/data-export'),
        (is_super, 'a_setup', '🧙', '部署精靈', '超級管理員',
         '檢視環境變數與資料表狀態，部署 / 維護時的健檢工具。', '/setup-wizard'),
    ]
    return [
        {'section': '後台', 'key': k, 'icon': icon, 'name': name,
         'audience': aud, 'desc': desc, 'url': url}
        for cond, k, icon, name, aud, desc, url in raw if cond
    ]


@guide_bp.get('/guide')
def guide():
    if not session.get('user_id'):
        return redirect(url_for('auth.login_page', next='/guide'))
    steps = _front_steps() + _admin_steps()
    return render_template('guide.html', steps=steps)
