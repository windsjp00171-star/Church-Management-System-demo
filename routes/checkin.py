# 電子簽到路由
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from db import supabase
from datetime import datetime, timezone, timedelta

checkin_bp = Blueprint('checkin', __name__)


def is_valid_checkin_date(event):
    """檢查今天是否在活動有效簽到日期內（台灣時間 UTC+8）"""
    if not event.get('event_start'):
        return True  # 沒設定開始時間 → 不限制

    taipei_tz = timezone(timedelta(hours=8))
    now_taipei = datetime.now(taipei_tz)

    try:
        start_str = event['event_start']
        if start_str.endswith('Z'):
            start_str = start_str[:-1] + '+00:00'
        event_start = datetime.fromisoformat(start_str)
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=timezone.utc)
        start_date = event_start.astimezone(taipei_tz).date()

        if event.get('event_end'):
            end_str = event['event_end']
            if end_str.endswith('Z'):
                end_str = end_str[:-1] + '+00:00'
            event_end = datetime.fromisoformat(end_str)
            if event_end.tzinfo is None:
                event_end = event_end.replace(tzinfo=timezone.utc)
            end_date = event_end.astimezone(taipei_tz).date()
            return start_date <= now_taipei.date() <= end_date
        else:
            # 只有開始時間 → 活動當天有效
            return now_taipei.date() == start_date
    except Exception:
        return True  # 解析失敗 → 不限制


def _mask_name(name: str) -> str:
    """姓名打碼：保留第一個字，中間全打碼，保留最後一個字"""
    if not name:
        return ''
    if len(name) <= 1:
        return name
    if len(name) == 2:
        return name[0] + '●'
    return name[0] + '●' * (len(name) - 2) + name[-1]


@checkin_bp.route('/checkin/<event_id>/<token>')
def checkin_page(event_id, token):
    """電子簽到頁面（手機掃碼後看到這頁）"""
    # 撈活動資料（未登入也需要先確認活動存在與 token 正確）
    event_result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not event_result.data:
        return render_template('checkin.html', event=None, error='找不到此活動')
    event = event_result.data[0]

    if event.get('checkin_token') != token:
        return render_template('checkin.html', event=event, error='這個 QR Code 連結無效')

    if not event.get('checkin_enabled'):
        return render_template('checkin.html', event=event, error='此活動尚未開啟電子簽到功能')

    if not is_valid_checkin_date(event):
        return render_template('checkin.html', event=event,
            error='電子簽到只在活動當天開放，請在正確日期再試')

    # 未登入：開放外部報名 → 身分選擇頁；否則 → LINE 登入
    if not session.get('user_id'):
        if event.get('allow_external_reg'):
            return render_template('checkin_identity.html', event=event,
                event_id=event_id, token=token)
        session['next_url'] = request.url
        return redirect(url_for('auth.login_page'))

    user_id = session['user_id']

    # ── 撈此使用者在此活動的所有報名紀錄 ──────────────────────────
    all_regs_result = supabase.table('registrations')\
        .select('*')\
        .eq('event_id', event_id)\
        .eq('user_id', user_id)\
        .execute()
    all_regs = all_regs_result.data or []

    # 篩出 registered 狀態（正式報名）
    registered_regs = [r for r in all_regs if r.get('status') == 'registered']

    # ── 僅限報名者模式：沒有 registered 紀錄就擋掉 ──
    if event.get('checkin_mode') == 'registered_only' and not registered_regs:
        return render_template('checkin.html',
            event=event, can_checkin=False, error=None,
            no_register_error='此活動僅限已報名的弟兄姊妹簽到。\n如您尚未報名，請先完成報名再來簽到。')

    # ── 全開放模式 + 沒有任何紀錄 ──
    if not registered_regs:
        walk_in = next((r for r in all_regs if r.get('status') == 'walk_in'), None)
        already_checked_in = bool(walk_in and walk_in.get('checked_in'))

        # ⚡ 掃碼即自動簽到：不需進確認頁，直接完成
        if event.get('allow_open_checkin') and not already_checked_in:
            now_utc = datetime.now(timezone.utc).isoformat()
            if walk_in:
                supabase.table('registrations').update({
                    'checked_in': True,
                    'checked_in_at': now_utc,
                }).eq('id', walk_in['id']).execute()
            else:
                supabase.table('registrations').insert({
                    'event_id': event_id,
                    'user_id': user_id,
                    'status': 'walk_in',
                    'checked_in': True,
                    'checked_in_at': now_utc,
                    'payment_status': 'unpaid',
                }).execute()
            return render_template('checkin.html',
                event=event, reg=None,
                already_checked_in=False,
                auto_checked_in=True,
                is_admin=session.get('is_admin', False),
                can_checkin=True, no_register_error=None, error=None)

        return render_template('checkin.html',
            event=event, reg=walk_in,
            already_checked_in=already_checked_in,
            auto_checked_in=False,
            is_admin=session.get('is_admin', False),
            can_checkin=True, no_register_error=None, error=None)

    # ── 只有一筆 registered ──
    if len(registered_regs) == 1:
        reg = registered_regs[0]
        already_checked_in = bool(reg.get('checked_in'))

        # ⚡ 掃碼即自動簽到
        if event.get('allow_open_checkin') and not already_checked_in:
            supabase.table('registrations').update({
                'checked_in': True,
                'checked_in_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', reg['id']).execute()
            return render_template('checkin.html',
                event=event, reg=reg,
                already_checked_in=False,
                auto_checked_in=True,
                is_admin=session.get('is_admin', False),
                can_checkin=True, no_register_error=None, error=None)

        return render_template('checkin.html',
            event=event, reg=reg,
            already_checked_in=already_checked_in,
            auto_checked_in=False,
            is_admin=session.get('is_admin', False),
            can_checkin=True, no_register_error=None, error=None)

    # ── 多筆 registered：撈每筆的答案，讓使用者選擇要簽哪一筆 ──
    reg_ids = [r['id'] for r in registered_regs]
    answers_result = supabase.table('registration_answers')\
        .select('registration_id, answer, event_fields(label, field_type, sort_order)')\
        .in_('registration_id', reg_ids)\
        .execute()

    # 整理 { reg_id: [ {label, answer} ] }
    answer_map = {}
    exact  = {}  # label == '參加者姓名'
    fuzzy  = {}  # label 含 姓名/名字/名稱
    text_f = {}  # fallback: first text field
    for ans in (answers_result.data or []):
        rid   = ans['registration_id']
        field = ans.get('event_fields') or {}
        label = field.get('label', '欄位')
        ftype = field.get('field_type', '')
        order = field.get('sort_order', 9999)
        val   = (ans.get('answer') or '').strip()
        if rid not in answer_map:
            answer_map[rid] = []
        answer_map[rid].append({'label': label, 'answer': ans['answer']})
        if val:
            if label == '參加者姓名':
                exact[rid] = val
            elif any(kw in label for kw in ('姓名', '名字', '名稱')):
                if rid not in fuzzy or order < fuzzy[rid][0]:
                    fuzzy[rid] = (order, val)
            if ftype == 'text':
                if rid not in text_f or order < text_f[rid][0]:
                    text_f[rid] = (order, val)
    name_map = {}
    for rid in set(list(exact) + list(fuzzy) + list(text_f)):
        if rid in exact:
            name_map[rid] = exact[rid]
        elif rid in fuzzy:
            name_map[rid] = fuzzy[rid][1]
        else:
            name_map[rid] = text_f[rid][1]

    return render_template('checkin.html',
        event=event,
        multi_regs=registered_regs,
        answer_map=answer_map,
        name_map=name_map,
        is_admin=session.get('is_admin', False),
        error=None)


@checkin_bp.route('/checkin/<event_id>/<token>/confirm', methods=['POST'])
def checkin_confirm(event_id, token):
    """執行簽到（POST）"""
    if not session.get('user_id'):
        return jsonify({'error': '請先登入'}), 401

    # 驗證活動與 token
    event_result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not event_result.data:
        return jsonify({'error': '找不到此活動'}), 404
    event = event_result.data[0]

    if event.get('checkin_token') != token:
        return jsonify({'error': '無效的簽到連結'}), 400

    if not event.get('checkin_enabled'):
        return jsonify({'error': '此活動未開啟電子簽到'}), 400

    if not is_valid_checkin_date(event):
        return jsonify({'error': '不在活動當天，無法簽到'}), 400

    user_id = session['user_id']
    data = request.get_json() or {}
    target_reg_id = data.get('reg_id')  # 多筆報名時由前端指定要簽哪一筆

    if target_reg_id:
        # 指定特定報名紀錄簽到
        reg_result = supabase.table('registrations')\
            .select('*')\
            .eq('id', target_reg_id)\
            .eq('event_id', event_id)\
            .eq('user_id', user_id)\
            .execute()
        if not reg_result.data:
            return jsonify({'error': '找不到此報名紀錄'}), 404
        reg = reg_result.data[0]
        if reg.get('checked_in'):
            return jsonify({'error': '此筆報名已完成簽到'}), 400
        if event.get('checkin_mode') == 'registered_only' and reg.get('status') != 'registered':
            return jsonify({'error': '此報名狀態無法簽到'}), 400
        supabase.table('registrations').update({
            'checked_in': True,
            'checked_in_at': datetime.now(timezone.utc).isoformat(),
        }).eq('id', reg['id']).execute()
    else:
        # 單筆邏輯：查此使用者所有紀錄
        reg_result = supabase.table('registrations')\
            .select('*')\
            .eq('event_id', event_id)\
            .eq('user_id', user_id)\
            .execute()
        all_regs = reg_result.data or []
        registered_regs = [r for r in all_regs if r.get('status') == 'registered']

        if registered_regs:
            reg = registered_regs[0]
            if reg.get('checked_in'):
                return jsonify({'error': '您已經完成簽到了！'}), 400
            if event.get('checkin_mode') == 'registered_only' and reg.get('status') != 'registered':
                return jsonify({'error': '您尚未正式報名，無法簽到'}), 400
            supabase.table('registrations').update({
                'checked_in': True,
                'checked_in_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', reg['id']).execute()
        else:
            if event.get('checkin_mode') == 'registered_only':
                return jsonify({'error': '您尚未報名此活動，無法簽到'}), 400
            # 全開放模式：建立或更新現場到場紀錄
            walk_in = next((r for r in all_regs if r.get('status') == 'walk_in'), None)
            if walk_in:
                if walk_in.get('checked_in'):
                    return jsonify({'error': '您已經完成簽到了！'}), 400
                supabase.table('registrations').update({
                    'checked_in': True,
                    'checked_in_at': datetime.now(timezone.utc).isoformat(),
                }).eq('id', walk_in['id']).execute()
            else:
                supabase.table('registrations').insert({
                    'event_id': event_id,
                    'user_id': user_id,
                    'status': 'walk_in',
                    'checked_in': True,
                    'checked_in_at': datetime.now(timezone.utc).isoformat(),
                    'payment_status': 'unpaid',
                }).execute()

    return jsonify({'success': True})


# ───────────────────────────────────────────────
# 同工代簽：搜尋 + 執行（不需後台，但需 is_admin）
# ───────────────────────────────────────────────

@checkin_bp.route('/checkin/<event_id>/<token>/proxy-search')
def checkin_proxy_search(event_id, token):
    """同工在簽到頁搜尋會友（代簽用）"""
    if not session.get('user_id'):
        return jsonify({'error': '請先登入'}), 401
    if not session.get('is_admin'):
        return jsonify({'error': '無權限'}), 403

    # 驗證 token
    event_result = supabase.table('events')\
        .select('checkin_token').eq('id', event_id).execute()
    if not event_result.data or event_result.data[0]['checkin_token'] != token:
        return jsonify({'error': '無效連結'}), 400

    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    results = []

    # ── 一般會友：搜尋 users 表（分兩次查詢避免 filter 字串注入）──
    pattern = f'%{q}%'
    u1 = supabase.table('users').select('id, display_name, real_name, picture_url')\
        .ilike('display_name', pattern).limit(10).execute().data or []
    u2 = supabase.table('users').select('id, display_name, real_name, picture_url')\
        .ilike('real_name', pattern).limit(10).execute().data or []
    seen_ids = {u['id'] for u in u1}
    users = u1 + [u for u in u2 if u['id'] not in seen_ids]

    if users:
        user_ids = [u['id'] for u in users]
        regs = supabase.table('registrations')\
            .select('id, user_id, status, checked_in')\
            .eq('event_id', event_id)\
            .in_('user_id', user_ids)\
            .in_('status', ['registered', 'walk_in'])\
            .execute().data or []
        reg_map = {r['user_id']: r for r in regs}
        for u in users:
            reg = reg_map.get(u['id'])
            results.append({
                'user_id': u['id'],
                'name': u.get('real_name') or u.get('display_name') or '—',
                'picture_url': u.get('picture_url') or '',
                'reg_id': reg['id'] if reg else None,
                'checked_in': reg['checked_in'] if reg else False,
                'is_external': False,
            })

    # ── 外部報名者：搜尋 registrations.guest_name ──
    ext_regs = supabase.table('registrations')\
        .select('id, guest_name, checked_in, status')\
        .eq('event_id', event_id)\
        .eq('source', 'external')\
        .in_('status', ['registered', 'waitlisted'])\
        .ilike('guest_name', f'%{q}%')\
        .limit(10).execute().data or []
    for r in ext_regs:
        results.append({
            'user_id': None,
            'name': r.get('guest_name') or '外部來賓',
            'picture_url': '',
            'reg_id': r['id'],
            'checked_in': r.get('checked_in', False),
            'is_external': True,
        })

    return jsonify(results)


@checkin_bp.route('/checkin/<event_id>/<token>/proxy', methods=['POST'])
def checkin_proxy(event_id, token):
    """同工在簽到頁代替會友簽到"""
    if not session.get('user_id'):
        return jsonify({'error': '請先登入'}), 401
    if not session.get('is_admin'):
        return jsonify({'error': '無權限'}), 403

    # 驗證 token，同時撈完整活動資料供後續使用
    event_result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not event_result.data or event_result.data[0]['checkin_token'] != token:
        return jsonify({'error': '無效連結'}), 400
    event = event_result.data[0]

    body = request.get_json() or {}
    user_id = body.get('user_id')
    reg_id = body.get('reg_id')

    # 外部報名者只傳 reg_id，一般會友至少要有 user_id 或 reg_id
    if not user_id and not reg_id:
        return jsonify({'error': '缺少識別資訊'}), 400

    now_utc = datetime.now(timezone.utc).isoformat()

    if reg_id:
        # 已有報名紀錄（含外部報名者）→ 先確認狀態合法再簽到
        reg_result = supabase.table('registrations')\
            .select('id, status, checked_in, source')\
            .eq('id', reg_id)\
            .eq('event_id', event_id)\
            .execute().data or []
        if not reg_result:
            return jsonify({'error': '找不到報名紀錄'}), 404
        reg = reg_result[0]
        if reg.get('checked_in'):
            return jsonify({'error': '此人已完成簽到'}), 400
        if event.get('checkin_mode') == 'registered_only' and reg.get('status') != 'registered':
            return jsonify({'error': '此報名狀態無法簽到（僅限已報名者）'}), 400
        supabase.table('registrations')\
            .update({'checked_in': True, 'checked_in_at': now_utc})\
            .eq('id', reg_id).execute()
    else:
        # 無報名紀錄 → 僅限開放模式才能建立 walk_in
        if event.get('checkin_mode') == 'registered_only':
            return jsonify({'error': '此活動僅限已報名者簽到，請先為此人完成報名'}), 400
        existing = supabase.table('registrations')\
            .select('id, status, checked_in')\
            .eq('event_id', event_id)\
            .eq('user_id', user_id)\
            .eq('status', 'walk_in')\
            .execute().data or []
        walk_in = existing[0] if existing else None
        if walk_in:
            if walk_in['checked_in']:
                return jsonify({'error': '此人已完成簽到'}), 400
            supabase.table('registrations')\
                .update({'checked_in': True, 'checked_in_at': now_utc})\
                .eq('id', walk_in['id']).execute()
        else:
            supabase.table('registrations').insert({
                'event_id': event_id,
                'user_id': user_id,
                'status': 'walk_in',
                'checked_in': True,
                'checked_in_at': now_utc,
                'source': 'proxy',
            }).execute()

    return jsonify({'success': True})


# ───────────────────────────────────────────────
# 外部人士簽到：打碼清單 + 點選確認
# ───────────────────────────────────────────────

@checkin_bp.route('/checkin/<event_id>/<token>/external')
def checkin_external_list(event_id, token):
    """顯示外部報名者打碼清單，供外部人士點選簽到"""
    event_result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not event_result.data:
        return render_template('checkin.html', event=None, error='找不到此活動')
    event = event_result.data[0]

    if event.get('checkin_token') != token:
        return render_template('checkin.html', event=event, error='這個 QR Code 連結無效')

    if not event.get('checkin_enabled'):
        return render_template('checkin.html', event=event, error='此活動尚未開啟電子簽到功能')

    if not is_valid_checkin_date(event):
        return render_template('checkin.html', event=event,
            error='電子簽到只在活動當天開放，請在正確日期再試')

    if not event.get('allow_external_reg'):
        return render_template('checkin.html', event=event, error='此活動不開放外部簽到')

    # 撈全部報名者（不限 source），外部朋友可能是代報或管理員補登
    regs = supabase.table('registrations')\
        .select('id, user_id, guest_name, checked_in')\
        .eq('event_id', event_id)\
        .eq('status', 'registered')\
        .order('created_at')\
        .execute().data or []

    # 用 LINE 用戶真實姓名補齊
    user_map = {}
    user_ids = list({r['user_id'] for r in regs if r.get('user_id')})
    if user_ids:
        users = supabase.table('users')\
            .select('id, real_name, display_name')\
            .in_('id', user_ids).execute().data or []
        for u in users:
            user_map[u['id']] = u

    # 用報名答案覆蓋（代報情境取參加者姓名）
    reg_ids = [r['id'] for r in regs]
    name_override_map = {}
    if reg_ids:
        ans_res = supabase.table('registration_answers')\
            .select('registration_id, answer, event_fields(label, field_type, sort_order)')\
            .in_('registration_id', reg_ids).execute()
        exact = {}; fuzzy = {}; text_f = {}
        for ans in (ans_res.data or []):
            rid   = ans['registration_id']
            field = ans.get('event_fields') or {}
            label = field.get('label', '')
            ftype = field.get('field_type', '')
            order = field.get('sort_order', 9999)
            val   = (ans.get('answer') or '').strip()
            if not val:
                continue
            if label == '參加者姓名':
                exact[rid] = val
            elif any(kw in label for kw in ('姓名', '名字', '名稱')):
                if rid not in fuzzy or order < fuzzy[rid][0]:
                    fuzzy[rid] = (order, val)
            if ftype == 'text':
                if rid not in text_f or order < text_f[rid][0]:
                    text_f[rid] = (order, val)
        for rid in set(list(exact) + list(fuzzy) + list(text_f)):
            name_override_map[rid] = (
                exact.get(rid)
                or (fuzzy[rid][1] if rid in fuzzy else None)
                or text_f[rid][1]
            )

    for r in regs:
        user = user_map.get(r.get('user_id'), {})
        name = (
            name_override_map.get(r['id'])
            or r.get('guest_name')
            or user.get('real_name')
            or user.get('display_name')
            or ''
        )
        r['masked_name'] = _mask_name(name)
        r['_display_name'] = name  # 保留給模板搜尋用（不顯示原文）

    return render_template('checkin_external.html',
        event=event, regs=regs, token=token)


@checkin_bp.route('/checkin/<event_id>/<token>/external-confirm', methods=['POST'])
def checkin_external_confirm(event_id, token):
    """外部人士點選自己的名字完成簽到"""
    event_result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not event_result.data:
        return jsonify({'error': '找不到此活動'}), 404
    event = event_result.data[0]

    if event.get('checkin_token') != token:
        return jsonify({'error': '無效的簽到連結'}), 400

    if not event.get('checkin_enabled') or not event.get('allow_external_reg'):
        return jsonify({'error': '此活動不開放外部簽到'}), 400

    if not is_valid_checkin_date(event):
        return jsonify({'error': '不在活動當天，無法簽到'}), 400

    data = request.get_json() or {}
    reg_id = data.get('reg_id')
    if not reg_id:
        return jsonify({'error': '缺少報名 ID'}), 400

    reg_result = supabase.table('registrations')\
        .select('id, status, checked_in')\
        .eq('id', reg_id)\
        .eq('event_id', event_id)\
        .execute().data or []

    if not reg_result:
        return jsonify({'error': '找不到此報名紀錄'}), 404

    reg = reg_result[0]
    if reg.get('checked_in'):
        return jsonify({'already': True, 'message': '此筆報名已完成簽到'}), 200

    supabase.table('registrations').update({
        'checked_in': True,
        'checked_in_at': datetime.now(timezone.utc).isoformat(),
    }).eq('id', reg_id).execute()

    return jsonify({'success': True})
