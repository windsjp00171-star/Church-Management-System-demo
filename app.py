# Flask 主程式 — 整合型教會行政系統
from flask import Flask, session, request, redirect, url_for, jsonify, g
import hmac
import secrets
import time
import uuid
from config import Config

# 門戶卡片名稱快取（60 秒 TTL，跨請求共用）
_card_names_cache: dict = {'data': None, 'ts': 0.0}

def _get_card_names() -> dict:
    now = time.time()
    if _card_names_cache['data'] is not None and (now - _card_names_cache['ts']) < 60:
        return _card_names_cache['data']
    try:
        from db import supabase as _sb
        rows = _sb.table('portal_card_settings').select('key,name').not_.is_('name', 'null').execute().data or []
        names = {r['key']: r['name'] for r in rows}
        _card_names_cache['data'] = names
        _card_names_cache['ts'] = now
        return names
    except Exception:
        return {}
from routes.auth import auth_bp
from routes.event import event_bp
from routes.admin import admin_bp
from routes.checkin import checkin_bp
from routes.profile import profile_bp
from routes.notifications import notifications_bp


def create_app():
    Config._validate()

    if Config.SENTRY_DSN:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(
            dsn=Config.SENTRY_DSN,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=False,
        )

    app = Flask(__name__)
    app.config.from_object(Config)

    # ── 核心模組（永遠啟用）────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(event_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(checkin_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(notifications_bp)

    # ── 可選模組（透過環境變數控制）──────────────────────────
    if Config.ENABLE_COURSES:
        from routes.courses import courses_bp
        app.register_blueprint(courses_bp)

    if Config.ENABLE_CALENDAR:
        from routes.calendar import calendar_bp
        app.register_blueprint(calendar_bp)

    if Config.ENABLE_BULLETIN:
        from routes.bulletin import bulletin_bp
        app.register_blueprint(bulletin_bp)

    if Config.ENABLE_PRAYER:
        from routes.prayer import prayer_bp
        app.register_blueprint(prayer_bp)

    if Config.ENABLE_GOSPEL:
        from routes.gospel import gospel_bp
        app.register_blueprint(gospel_bp)

    if Config.ENABLE_VISITOR_FORMS:
        from routes.visitor_forms import visitor_forms_bp
        app.register_blueprint(visitor_forms_bp)

    # ── 整合模組：檔案分享（church-data-hub）────────────────
    from routes.files import files_bp
    from extensions import limiter
    limiter.init_app(app)
    app.register_blueprint(files_bp)

    # ── 整合模組：天父日記（tianfu-diary）────────────────────
    from routes.diary import diary_bp
    app.register_blueprint(diary_bp)

    # ── 整合模組：小組回報（cell_reporter）───────────────────
    from routes.cell_report import cell_report_bp
    app.register_blueprint(cell_report_bp)

    # ── 同工首頁 ──────────────────────────────────────────────
    from routes.staff import staff_bp
    app.register_blueprint(staff_bp)

    # ── 部署精靈 ──────────────────────────────────────────────
    from routes.setup_wizard import setup_wizard_bp
    app.register_blueprint(setup_wizard_bp)

    # ── 更新日誌 ──────────────────────────────────────────────
    from routes.changelog import changelog_bp
    app.register_blueprint(changelog_bp)

    # ── 差勤系統 ──────────────────────────────────────────────
    from routes.attendance import attendance_bp
    app.register_blueprint(attendance_bp)

    # ── 資料匯出 / 匯入 ────────────────────────────────────────
    from routes.data_transfer import data_transfer_bp
    app.register_blueprint(data_transfer_bp)

    # ── 數位遺囑備份模塊 ───────────────────────────────────────
    from routes.backup import backup_bp
    app.register_blueprint(backup_bp)

    # ── 聚焦式功能導覽 ─────────────────────────────────────────
    from routes.guide import guide_bp
    app.register_blueprint(guide_bp)

    # ── 互動式教學 ─────────────────────────────────────────────
    from routes.tutorial import tutorial_bp
    app.register_blueprint(tutorial_bp)

    # ── 禱讀本訂購 ─────────────────────────────────────────────
    from routes.devotional import devotional_bp
    app.register_blueprint(devotional_bp)

    # ── 線上金流 ───────────────────────────────────────────────
    from routes.payment import payment_bp
    app.register_blueprint(payment_bp)

    # ── 強制補填個人資料 ──────────────────────────────────────
    SKIP_FORCE_SETUP = {
        'profile.setup',
        'profile.onboarding',      # 首次登入引導頁（auth 登入後的導向目標）
        'profile.merge_confirm',   # 自助帳號合併（發生在 real_name 尚未寫入前）
        'auth.login',
        'auth.callback',
        'auth.logout',
        'auth.login_page',
        'auth.force_relogin',  # session 自救，避免重導死循環
        'static',
        'event.event_detail',
        'event.event_external_form',
        'event.event_external_register',
        'checkin.checkin_page',
        'checkin.checkin_external_list',
        'checkin.checkin_external_confirm',
        # 公開報告（小組回報，無需登入）
        'cell_report.sunday',
        'cell_report.children',
        'cell_report.prayer',
        'cell_report.morning_prayer',
        # 部署精靈（初始設定時尚未有 real_name）
        'setup_wizard.index',
        'setup_wizard.db_status',
    }

    # ── 請求追蹤代碼（錯誤頁／log／Sentry 三方對應）──────────
    @app.before_request
    def assign_request_id():
        g.request_id = uuid.uuid4().hex[:8]
        if Config.SENTRY_DSN:
            try:
                import sentry_sdk
                sentry_sdk.set_tag('error_code', g.request_id)
            except Exception:
                pass

    # 伺服器端 callback 路徑豁免（ECPay/LinePay 由金流平台直接 POST）
    _CSRF_EXEMPT_PREFIXES = (
        '/payment/ecpay/return',
        '/payment/linepay/',
        '/auth/callback',
        '/auth/liff-login',
        '/auth/contact',
    )

    @app.before_request
    def global_csrf_protect():
        if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
            return
        if not session.get('user_id'):
            return  # 公開端點（外部報名、金流回呼等）不強制 CSRF
        path = request.path
        if any(path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES):
            return
        token = request.headers.get('X-CSRF-Token') or request.form.get('_csrf_token')
        expected = session.get('_csrf_token')
        if not expected or not token or not hmac.compare_digest(str(token), str(expected)):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'CSRF token 驗證失敗，請重新整理頁面'}), 403
            return redirect(request.referrer or '/')

    @app.before_request
    def force_profile_setup():
        if not session.get('user_id'):
            return
        endpoint = request.endpoint or ''
        if endpoint in SKIP_FORCE_SETUP or endpoint.startswith('static'):
            return
        # 帳號被刪除／合併後 session 殘留 → 導向自助重登
        # _user_verified 旗標讓 DB 檢查每個 session 只跑一次
        if not session.get('_user_verified'):
            try:
                from db import supabase as _sb
                row = _sb.table('users').select('id')\
                    .eq('id', session['user_id']).execute().data
            except Exception:
                row = [True]  # DB 暫時無法連線時不誤殺 session
            if not row:
                session.clear()
                return redirect(url_for('auth.force_relogin'))
            session['_user_verified'] = True
        if session.get('real_name'):
            return
        return redirect(url_for('profile.setup'))
    # ──────────────────────────────────────────────────────────

    # ── Jinja2 全域：CSRF token ───────────────────────────────
    def get_csrf_token():
        if '_csrf_token' not in session:
            session['_csrf_token'] = secrets.token_hex(24)
        return session['_csrf_token']

    app.jinja_env.globals['csrf_token']        = get_csrf_token
    app.jinja_env.globals['line_liff_id']      = Config.LINE_LIFF_ID
    app.jinja_env.globals['church_name']       = Config.CHURCH_NAME
    app.jinja_env.globals['church_short_name'] = Config.CHURCH_SHORT_NAME or Config.CHURCH_NAME
    app.jinja_env.globals['privacy_policy_url'] = Config.PRIVACY_POLICY_URL

    # ── Context processor：門戶卡片名稱（全域可用） ───────────
    @app.context_processor
    def inject_card_names():
        return {'card_names': _get_card_names()}

    # ── Context processor：天父日記需要的全域變數 ─────────────
    @app.context_processor
    def inject_diary_globals():
        import os
        from datetime import datetime, timezone, timedelta
        user_id = session.get('user_id')
        line_id = session.get('line_id', '')
        current_user = {
            'line_user_id': line_id,
            'display_name': session.get('real_name', ''),
            'picture_url': session.get('picture_url', ''),
        } if user_id else None

        admin_ids_raw = os.environ.get('ADMIN_LINE_USER_IDS', '')
        admin_ids = [s.strip() for s in admin_ids_raw.split(',') if s.strip()]
        show_bootstrap = bool(current_user and not admin_ids)

        return {
            'current_user': current_user,
            'app_name': Config.CHURCH_NAME,
            'app_tagline': '整合型教會行政系統',
            'show_bootstrap': show_bootstrap,
        }

    # ── Jinja2 filter：台灣時間 ───────────────────────────────
    from datetime import datetime, timezone, timedelta as _td

    def _taipei_time(s, fmt='%Y-%m-%d %H:%M'):
        if not s:
            return ''
        try:
            s = str(s)
            if s.endswith('Z'):
                s = s[:-1] + '+00:00'
            elif '+00' in s and not s.endswith('+00:00'):
                s = s.split('+')[0] + '+00:00'
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone(_td(hours=8)))
            return dt.strftime(fmt)
        except Exception:
            return str(s)[:16].replace('T', ' ')

    app.jinja_env.filters['taipei_time'] = _taipei_time

    # ── 錯誤頁面 ──────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template as _rt
        return _rt('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template as _rt
        code = getattr(g, 'request_id', '')
        # 把錯誤代碼與完整 traceback 一起寫入 log，方便用代碼直接搜尋
        app.logger.error(
            '[500] 錯誤代碼=%s path=%s method=%s',
            code, request.path, request.method, exc_info=True,
        )
        return _rt('errors/500.html', error_code=code), 500

    # ── 健康檢查（供 Render / 監控使用）──────────────────────
    @app.route('/health')
    def health():
        return jsonify({'status': 'ok'})

    # ── PWA manifest ─────────────────────────────────────────
    @app.route('/manifest.json')
    def pwa_manifest():
        name = Config.CHURCH_NAME
        short = Config.CHURCH_SHORT_NAME or name
        return jsonify({
            'name': name,
            'short_name': short,
            'description': f'{name} 整合型教會行政系統',
            'start_url': '/',
            'display': 'standalone',
            'background_color': '#f5f5f5',
            'theme_color': '#06C755',
            'lang': 'zh-TW',
            'icons': [
                {
                    'src': '/static/icons/icon.svg',
                    'sizes': 'any',
                    'type': 'image/svg+xml',
                    'purpose': 'any maskable',
                }
            ],
        })

    # ── 健康檢查端點（UptimeRobot 保活 / 監控用，不查資料庫）──────
    @app.route('/healthz')
    def healthz():
        return jsonify({'status': 'ok'}), 200

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
