from flask import Blueprint, render_template, session, redirect, abort, request, url_for
from urllib.parse import quote
from routes.decorators import login_required
from db import supabase

bulletin_bp = Blueprint('bulletin', __name__)



@bulletin_bp.route('/bulletins')
@login_required
def bulletin_list():
    """週報列表頁"""
    # 撈所有週報，依日期倒序
    result = supabase.table('weekly_bulletins')\
        .select('*')\
        .order('bulletin_date', desc=True)\
        .execute()
    bulletins = result.data or []

    # 整理年份清單供篩選器使用
    years = sorted(set(b['bulletin_date'][:4] for b in bulletins), reverse=True)

    return render_template('bulletins.html', bulletins=bulletins, years=years)


@bulletin_bp.route('/bulletins/<bulletin_id>')
@login_required
def bulletin_view(bulletin_id):
    """週報閱讀頁（手機友善）"""
    result = supabase.table('weekly_bulletins')\
        .select('*').eq('id', bulletin_id).execute()
    if not result.data:
        abort(404)
    bulletin = result.data[0]
    viewer_url = f"https://docs.google.com/viewer?url={quote(bulletin['pdf_url'], safe='')}&embedded=true"
    return render_template('bulletin_view.html', bulletin=bulletin, viewer_url=viewer_url)
