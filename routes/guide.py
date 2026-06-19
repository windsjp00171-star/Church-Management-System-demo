"""
聚焦式功能導覽（In-app Guided Tour）
====================================
系統內建、隨時可看的功能導覽：逐一聚焦各前台模組，一次專注一個，
附「前往體驗」連結。只呈現目前啟用的模組（依 Config 的 ENABLE_* 開關），
未啟用的模組自動不出現於導覽中。

路由：/guide
純前台、無資料庫依賴；任何登入使用者皆可使用。
"""
from flask import Blueprint, render_template, session, redirect, url_for
from config import Config

guide_bp = Blueprint('guide', __name__)


def _build_steps():
    """組出導覽步驟清單。每個步驟：
    key（對應 card_names 覆寫）、icon、預設名稱、對象、說明、體驗連結。
    依 Config.ENABLE_* 過濾未啟用模組。
    """
    steps = [
        # (enabled, key, icon, 預設名稱, 對象, 說明, 連結)
        (True, 'events', '🎉', '活動報名與簽到', '全會友',
         '瀏覽教會活動、線上報名；活動當天用手機掃 QR Code 即可簽到。',
         '/events'),
        (True, 'my_history', '🗂', '我的報名紀錄', '全會友',
         '查看自己報名過的活動與課程、繳費與簽到狀態。',
         '/my-history'),
        (Config.ENABLE_PRAYER, 'prayer', '🙏', '代禱麥田', '全會友',
         '張貼代禱事項、為彼此代禱按讚回應，可匿名；蒙應允後可標記見證。',
         '/prayer'),
        (True, 'diary', '📖', '天父日記', '全會友',
         '跟著讀經進度寫靈修日記，搭配 AI 反思引導幫助默想。',
         '/diary'),
        (Config.ENABLE_GOSPEL, 'gospel', '✝️', '福音探索', '慕道朋友',
         '認識信仰的 Q&A 卡片，也可留下聯絡方式由同工跟進關懷。',
         '/gospel'),
        (True, 'devotional', '📚', '禱讀本訂購', '全會友 / 小組',
         '查看當期禱讀本、由小組登記訂購數量，附簽收與領取管理。',
         '/devotional'),
        (True, 'cell_report', '🏠', '小組回報', '小組長',
         '小組長每週線上回報出席與組員四面向狀況，牧者後台可彙整查閱。',
         '/cell-report/portal'),
        (Config.ENABLE_CALENDAR, 'calendar', '📅', '教會行事曆', '全會友',
         '活動、課程、教會行事一頁總覽，掌握近期所有安排。',
         '/calendar'),
        (Config.ENABLE_COURSES, 'courses', '🎓', '門訓課程', '全會友',
         '瀏覽與報名門訓課程，系統自動追蹤出席與結業認證。',
         '/courses'),
        (Config.ENABLE_BULLETIN, 'bulletin', '📰', '每週週報', '全會友',
         '線上閱讀每週週報 PDF，不再錯過教會消息。',
         '/bulletins'),
        (bool(Config.R2_ENDPOINT), 'files', '🗄', '檔案分享', '同工 / 會友',
         '教會內部檔案、詩歌、講義的上傳與分享。',
         '/files'),
        (True, 'profile', '🙋', '個人主頁與資料', '全會友',
         '維護個人資料、設定自己的首頁顯示內容。',
         '/profile/homepage'),
    ]
    return [
        {'key': k, 'icon': icon, 'name': name, 'audience': aud,
         'desc': desc, 'url': url}
        for enabled, k, icon, name, aud, desc, url in steps if enabled
    ]


@guide_bp.get('/guide')
def guide():
    if not session.get('user_id'):
        return redirect(url_for('auth.login_page', next='/guide'))
    return render_template('guide.html', steps=_build_steps())
