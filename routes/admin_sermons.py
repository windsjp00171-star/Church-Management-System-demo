# 後台：主日信息
#
# 這一塊的管理工作很少 —— 影片是自動抓進來的。所以這一頁真正的職責是
# **讓「抓壞了」看得見**：排程在背景跑，失敗了不會有人知道，
# 而症狀是「主日信息停在上個月」，跟「這個月沒有錄影」長得一模一樣。
#
# 所以有一顆「立刻重新抓取」，當場跑一次並把結果照實講出來。

from flask import Blueprint, jsonify, render_template, request

import settings_store
from db import supabase
from routes.audit import log_action
from routes.decorators import admin_required

admin_sermons_bp = Blueprint('admin_sermons', __name__)


@admin_sermons_bp.route('/admin/sermons')
@admin_required
def admin_sermons():
    from routes import sermons as S

    block = settings_store.get('sermon_playlists') or ''
    sources = S.feed_sources(block)
    try:
        rows = S.recent(limit=60, include_hidden=True)
    except Exception:
        #  ★ 撈不到不可以變成 500：這一頁正是拿來查「怎麼了」的，
        #    它自己掛掉的話就沒有地方可以查了
        rows = None

    #  ★ 日期是從標題讀到的、還是退回上傳時間的 —— 見 S.date_source_report。
    #    命名哪天改了，這個數字會從 0 變成一整批，而畫面上完全正常。
    return render_template('admin/sermons.html',
                           sources=sources, sermons=rows, block=block,
                           dates=S.date_source_report(rows or []))


@admin_sermons_bp.route('/admin/sermons/playlists', methods=['POST'])
@admin_required
def admin_sermons_playlists():
    """存播放清單網址（一行一個）。

    ★ 存之前不擋格式：打錯的那一行由頁面上「抓取來源」逐行標出來（⛔），
      擋掉的話同工不知道哪一行有問題，只看到「存不進去」。
    """
    block = ((request.get_json(silent=True) or {}).get('block') or '').strip()
    try:
        settings_store.set('sermon_playlists', block)
    except Exception:
        return jsonify({'error': '存不進去，請再試一次'}), 500
    log_action('sermons.playlists', 'settings', 'sermon_playlists',
               {'lines': len([x for x in block.splitlines() if x.strip()])})
    return jsonify({'ok': True})


@admin_sermons_bp.route('/admin/sermons/refresh', methods=['POST'])
@admin_required
def admin_sermons_refresh():
    """立刻抓一輪，把結果照實回報。"""
    from routes import sermons as S
    try:
        result = S.refresh()
    except Exception as e:
        return jsonify({'ok': False,
                        'problems': [f'抓取整個失敗了（{type(e).__name__}）']}), 200
    #  ★ 一律回 200：有問題也是「跑完了，結果是這樣」。
    #    回 500 的話前端只會顯示一句籠統的錯誤，而 problems 裡
    #    那幾行才是真正有用的東西。
    return jsonify({'ok': not result['problems'], **result})


@admin_sermons_bp.route('/admin/sermons/<sermon_id>', methods=['POST'])
@admin_required
def admin_sermons_update(sermon_id):
    """同工補的資料：講員、經文、要不要藏起來。

    ★ 這三欄**永遠不會**被下一次抓取覆蓋 —— 補過的字被 YouTube 的標題
      洗掉的話，補的人下次來看只會覺得自己沒存到。

    ★ 但**標題會跟著 YouTube 更新**（`sermons.FEED_FIELDS`）——
      標題結尾的日期正是前台分組用的那個日期。
      原本是「一律不 update」，那擋得太寬：使用者在 YouTube 上改掉打錯的
      標題，系統這邊永遠停在舊的 —— 而講道日期是從標題結尾讀出來的，
      所以那一篇會永遠留在錯的那一週。
    """
    data = request.get_json() or {}
    patch = {}
    for col in ('speaker', 'scripture'):
        if col in data:
            patch[col] = (data.get(col) or '').strip() or None
    if 'is_hidden' in data:
        patch['is_hidden'] = bool(data['is_hidden'])
    if not patch:
        return jsonify({'error': '沒有要改的東西'}), 400

    from datetime import datetime, timezone
    patch['updated_at'] = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table('sermons').update(patch).eq('id', sermon_id).execute()
    except Exception:
        return jsonify({'error': '存不進去，請再試一次'}), 500
    return jsonify({'ok': True})
