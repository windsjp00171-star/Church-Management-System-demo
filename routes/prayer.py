# 代禱牆系統路由
from flask import Blueprint, render_template, request, session, redirect, jsonify, url_for
from datetime import datetime, timezone
from config import Config
from supabase import create_client

supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
prayer_bp = Blueprint('prayer', __name__)

EMOJIS = ['🙏', '❤️', '🕯️', '✨', '💪']

CATEGORIES = {
    'health':   '🏥 健康',
    'family':   '🏠 家庭',
    'work':     '💼 工作',
    'spiritual':'🕊️ 靈命',
    'other':    '🌾 其他',
}

def wheat_stage(reaction_count, status):
    """根據回應數回傳麥子成長階段"""
    if status == 'answered':
        return {'emoji': '🌾', 'label': '蒙應允', 'glow': True}
    if reaction_count == 0:
        return {'emoji': '🌰', 'label': '種子', 'glow': False}
    if reaction_count <= 3:
        return {'emoji': '🌱', 'label': '發芽', 'glow': False}
    if reaction_count <= 9:
        return {'emoji': '🌿', 'label': '生長', 'glow': False}
    return {'emoji': '🌾', 'label': '成熟', 'glow': False}


def get_user_display(user_id, is_anonymous):
    """取得顯示名稱"""
    if is_anonymous:
        return '匿名', None
    try:
        r = supabase.table('users').select('real_name,display_name,picture_url').eq('id', user_id).single().execute()
        u = r.data or {}
        name = u.get('real_name') or u.get('display_name') or '未知'
        return name, u.get('picture_url')
    except Exception:
        return '未知', None


# ── 新代禱數量 API（導覽列紅點用）──────────────────────────────────────────
@prayer_bp.route('/api/prayer/new-count')
def new_count():
    if not session.get('user_id'):
        return jsonify({'count': 0})
    try:
        last_visit = session.get('last_prayer_visit')
        if not last_visit:
            # 從未造訪過，算最近 3 天的
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        else:
            cutoff = last_visit
        r = supabase.table('prayers').select('id', count='exact')\
            .eq('status', 'active').gt('created_at', cutoff).execute()
        return jsonify({'count': r.count or 0})
    except Exception:
        return jsonify({'count': 0})


# ── 主頁：麥田牆 ──────────────────────────────────────────
@prayer_bp.route('/prayer')
def index():
    if not session.get('user_id'):
        session['next_url'] = request.url
        return redirect(url_for('auth.login_page'))

    # 記錄本次瀏覽時間（離開後才算「已看過」）
    session['last_prayer_visit'] = datetime.now(timezone.utc).isoformat()

    status_filter = request.args.get('status', 'active')

    try:
        q = supabase.table('prayers').select('*').order('created_at', desc=True)
        if status_filter == 'answered':
            q = q.eq('status', 'answered')
        elif status_filter == 'all':
            q = q.neq('status', 'archived')
        else:
            q = q.eq('status', 'active')

        prayers = q.execute().data or []

        # 取得目前使用者的所有回應（一次查完）
        my_reactions = {}
        if prayers:
            prayer_ids = [p['id'] for p in prayers]
            rr = supabase.table('prayer_reactions')\
                .select('prayer_id,emoji')\
                .eq('user_id', session['user_id'])\
                .in_('prayer_id', prayer_ids).execute()
            for row in (rr.data or []):
                my_reactions.setdefault(row['prayer_id'], set()).add(row['emoji'])

        # 每則代禱加入顯示資訊
        for p in prayers:
            name, pic = get_user_display(p['user_id'], p.get('is_anonymous', False))
            p['display_name'] = name
            p['picture_url'] = pic
            p['stage'] = wheat_stage(p.get('reaction_count', 0), p['status'])
            p['my_reactions'] = my_reactions.get(p['id'], set())
            p['is_mine'] = p['user_id'] == session['user_id']
            p['category_label'] = CATEGORIES.get(p.get('category', 'other'), '🌾 其他')

    except Exception as e:
        prayers = []
        print(f'[prayer] index error: {e}')

    return render_template('prayer/index.html',
        prayers=prayers,
        status_filter=status_filter,
        emojis=EMOJIS,
        categories=CATEGORIES,
        is_super_admin=session.get('is_super_admin', False),
    )


# ── 發出新代禱 ──────────────────────────────────────────
@prayer_bp.route('/prayer/new', methods=['POST'])
def new_prayer():
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': '請先登入'}), 401

    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    category = data.get('category', 'other')
    is_anonymous = bool(data.get('is_anonymous', False))

    if not title:
        return jsonify({'success': False, 'error': '請填寫代禱標題'})

    if category not in CATEGORIES:
        category = 'other'

    try:
        r = supabase.table('prayers').insert({
            'user_id': session['user_id'],
            'title': title,
            'content': content or None,
            'category': category,
            'is_anonymous': is_anonymous,
            'status': 'active',
            'reaction_count': 0,
            'comment_count': 0,
        }).execute()
        return jsonify({'success': True, 'id': r.data[0]['id']})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 表情回應（切換）──────────────────────────────────────────
@prayer_bp.route('/prayer/<prayer_id>/react', methods=['POST'])
def react(prayer_id):
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': '請先登入'}), 401

    data = request.get_json() or {}
    emoji = data.get('emoji', '')
    if emoji not in EMOJIS:
        return jsonify({'success': False, 'error': '無效的表情'})

    uid = session['user_id']
    try:
        # 檢查是否已回應過這個 emoji
        existing = supabase.table('prayer_reactions')\
            .select('id').eq('prayer_id', prayer_id)\
            .eq('user_id', uid).eq('emoji', emoji).execute()

        if existing.data:
            # 已有 → 刪除（取消回應）
            supabase.table('prayer_reactions').delete()\
                .eq('prayer_id', prayer_id).eq('user_id', uid).eq('emoji', emoji).execute()
            action = 'removed'
        else:
            # 沒有 → 新增
            supabase.table('prayer_reactions').insert({
                'prayer_id': prayer_id,
                'user_id': uid,
                'emoji': emoji,
            }).execute()
            action = 'added'

        # 更新 reaction_count
        count_r = supabase.table('prayer_reactions')\
            .select('id', count='exact').eq('prayer_id', prayer_id).execute()
        total = count_r.count or 0
        supabase.table('prayers').update({'reaction_count': total})\
            .eq('id', prayer_id).execute()

        # 取得各 emoji 數量
        all_r = supabase.table('prayer_reactions')\
            .select('emoji').eq('prayer_id', prayer_id).execute()
        emoji_counts = {}
        for row in (all_r.data or []):
            emoji_counts[row['emoji']] = emoji_counts.get(row['emoji'], 0) + 1

        stage = wheat_stage(total, 'active')

        return jsonify({
            'success': True,
            'action': action,
            'reaction_count': total,
            'emoji_counts': emoji_counts,
            'stage': stage,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 取得留言 ──────────────────────────────────────────
@prayer_bp.route('/prayer/<prayer_id>/comments')
def get_comments(prayer_id):
    if not session.get('user_id'):
        return jsonify({'success': False}), 401
    try:
        r = supabase.table('prayer_comments')\
            .select('*').eq('prayer_id', prayer_id)\
            .order('created_at').execute()
        comments = r.data or []

        # 補上顯示名稱
        for c in comments:
            name, pic = get_user_display(c['user_id'], c.get('is_anonymous', False))
            c['display_name'] = name
            c['picture_url'] = pic
            c['is_mine'] = c['user_id'] == session['user_id']

        return jsonify({'success': True, 'comments': comments})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 新增留言 ──────────────────────────────────────────
@prayer_bp.route('/prayer/<prayer_id>/comment', methods=['POST'])
def add_comment(prayer_id):
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': '請先登入'}), 401

    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    is_anonymous = bool(data.get('is_anonymous', False))

    if not content:
        return jsonify({'success': False, 'error': '留言不能空白'})

    try:
        supabase.table('prayer_comments').insert({
            'prayer_id': prayer_id,
            'user_id': session['user_id'],
            'content': content,
            'is_anonymous': is_anonymous,
        }).execute()

        # 更新 comment_count
        count_r = supabase.table('prayer_comments')\
            .select('id', count='exact').eq('prayer_id', prayer_id).execute()
        supabase.table('prayers').update({'comment_count': count_r.count or 0})\
            .eq('id', prayer_id).execute()

        name, pic = get_user_display(session['user_id'], is_anonymous)
        return jsonify({
            'success': True,
            'display_name': name,
            'picture_url': pic,
            'content': content,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 標記蒙應允 ──────────────────────────────────────────
@prayer_bp.route('/prayer/<prayer_id>/answered', methods=['POST'])
def mark_answered(prayer_id):
    if not session.get('user_id'):
        return jsonify({'success': False}), 401
    try:
        # 只有本人可以標記蒙應允
        p = supabase.table('prayers').select('user_id').eq('id', prayer_id).single().execute()
        if not p.data or p.data['user_id'] != session['user_id']:
            return jsonify({'success': False, 'error': '只有本人才能標記蒙應允'})

        supabase.table('prayers').update({
            'status': 'answered',
            'answered_at': 'now()',
        }).eq('id', prayer_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 刪除代禱 ──────────────────────────────────────────
@prayer_bp.route('/prayer/<prayer_id>/delete', methods=['POST'])
def delete_prayer(prayer_id):
    if not session.get('user_id'):
        return jsonify({'success': False}), 401
    try:
        p = supabase.table('prayers').select('user_id').eq('id', prayer_id).single().execute()
        if not p.data:
            return jsonify({'success': False, 'error': '找不到代禱事項'})

        uid = session['user_id']
        is_super = session.get('is_super_admin', False)
        is_admin = session.get('is_admin', False)
        is_owner = p.data['user_id'] == uid

        if not (is_owner or is_super or is_admin):
            return jsonify({'success': False, 'error': '無權限刪除'})

        supabase.table('prayers').delete().eq('id', prayer_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 取得各 emoji 數量（給前端初始化用）──────────────────────────────────────────
@prayer_bp.route('/prayer/<prayer_id>/reactions-count')
def reactions_count(prayer_id):
    if not session.get('user_id'):
        return jsonify({'success': False}), 401
    try:
        r = supabase.table('prayer_reactions')\
            .select('emoji').eq('prayer_id', prayer_id).execute()
        emoji_counts = {}
        for row in (r.data or []):
            emoji_counts[row['emoji']] = emoji_counts.get(row['emoji'], 0) + 1
        return jsonify({'success': True, 'emoji_counts': emoji_counts})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 封存代禱 ──────────────────────────────────────────
@prayer_bp.route('/prayer/<prayer_id>/archive', methods=['POST'])
def archive_prayer(prayer_id):
    if not session.get('user_id'):
        return jsonify({'success': False}), 401
    try:
        p = supabase.table('prayers').select('user_id').eq('id', prayer_id).single().execute()
        if not p.data:
            return jsonify({'success': False, 'error': '找不到'})

        uid = session['user_id']
        is_super = session.get('is_super_admin', False)
        is_owner = p.data['user_id'] == uid

        if not (is_owner or is_super):
            return jsonify({'success': False, 'error': '無權限'})

        supabase.table('prayers').update({
            'status': 'archived',
            'archived_at': 'now()',
        }).eq('id', prayer_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
