# 內建排程：時間到了就自己執行
#
# 背景：Render 免費方案沒有 cron，時間相關的事情原本都寄生在「剛好有人打開某頁」上，
# 造成「時間到了卻沒發生」。這裡不依賴任何外部服務，作法是：
#
#   1. 每個進來的請求在 before_request 檢查「上次跑排程是多久以前」
#   2. 超過 TICK_INTERVAL 就把到期任務丟到背景執行緒跑（請求本身不會變慢）
#   3. UptimeRobot 本來就在定期 ping 防休眠 → 等於固定有心跳來驅動排程
#
# 所有任務都必須「可重複執行且結果相同」：漏跑一次不會壞、多跑一次也不會重複，
# 因為服務重啟後記憶體節流會歸零，任務有可能提前再跑一次。
import hmac
import threading
from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, request

from config import Config
from db import supabase

tasks_bp = Blueprint('tasks', __name__)

TAIPEI_TZ = timezone(timedelta(hours=8))

# 兩次排程之間至少間隔多久
TICK_INTERVAL = timedelta(minutes=15)

_last_run = None          # 上次觸發時間（記憶體，不跨 process）
_lock = threading.Lock()
_running = False


def _job_close_expired_courses():
    """報名截止時間已過但仍開放的課程 → 關閉"""
    from routes.courses import auto_close_expired_courses
    auto_close_expired_courses()
    return 'ok'


def _job_reading_nudge():
    """聖經速讀每天一則 —— 推他**自己的下一格**。

    ★ 自己管時段（09:00 起）和「今天發過沒有」，所以排程每 15 分鐘轉一次也只會發一則。
    """
    from routes import reading_nudge
    return reading_nudge.run()


def _job_warm_bible_chapters():
    """把速讀計畫的經文在**背景**抓回來 —— 不要讓讀的人去等。

    ★★ 量出來的：整份計畫 1190 章，快取只有 11% —— 89% 的「打開某一格」會在請求裡跑 3-4 次
      外部抓取，每次佔著一條 gunicorn 執行緒（總共 8 條）。速讀提醒又是每天 09:00 推給所有人，
      一百多支手機同時點進來 → 後面的請求排隊 → 「很慢」「500」。
    ★ 抓過就永遠不用再抓，所以這一支自己跑完就沒事（每次 40 章，約 27 次 tick）。
    """
    from routes import bible_text
    return bible_text.warm()


JOBS = [
    ('warm_bible_chapters', _job_warm_bible_chapters),
    ('reading_nudge', _job_reading_nudge),
    ('close_expired_courses', _job_close_expired_courses),
]


def run_jobs():
    """實際執行所有任務，單一任務失敗不影響其他任務"""
    results = {}
    for name, fn in JOBS:
        try:
            results[name] = fn()
        except Exception as exc:
            results[name] = {'error': str(exc)[:200]}
    return results


def _run_in_background():
    global _running
    try:
        run_jobs()
    finally:
        with _lock:
            _running = False


def maybe_run_scheduled_tasks():
    """由 before_request 呼叫：到時間就在背景跑排程，不阻塞這個請求"""
    global _last_run, _running
    now = datetime.now(TAIPEI_TZ)
    with _lock:
        if _running:
            return False
        if _last_run is not None and now - _last_run < TICK_INTERVAL:
            return False
        # 先記錄時間再啟動，避免同時湧入的請求重複觸發
        _last_run = now
        _running = True
    threading.Thread(target=_run_in_background, daemon=True).start()
    return True


def _authorized():
    token = request.args.get('token') or request.headers.get('X-Task-Token') or ''
    expected = Config.TASK_TOKEN or ''
    return bool(expected) and hmac.compare_digest(token, expected)


@tasks_bp.route('/tasks/tick', methods=['GET', 'POST'])
def tick():
    """手動立刻執行排程（測試或臨時補跑用）。

    平時不需要呼叫，排程本來就會自己跑；要用這個端點時設定 TASK_TOKEN 環境變數，
    再打 /tasks/tick?token=<TASK_TOKEN>。
    """
    if not Config.TASK_TOKEN:
        return jsonify({'error': '尚未設定 TASK_TOKEN 環境變數，手動觸發端點停用中'}), 503
    if not _authorized():
        return jsonify({'error': 'token 錯誤'}), 403

    global _last_run
    started = datetime.now(TAIPEI_TZ)
    results = run_jobs()
    _last_run = started
    return jsonify({
        'success': True,
        'ran_at': started.isoformat(),
        'took_ms': int((datetime.now(TAIPEI_TZ) - started).total_seconds() * 1000),
        'results': results,
    })


@tasks_bp.route('/tasks/status')
def status():
    """排程狀態（供後台顯示：上次跑的時間）"""
    return jsonify({
        'last_run': _last_run.isoformat() if _last_run else None,
        'interval_minutes': int(TICK_INTERVAL.total_seconds() // 60),
        'running': _running,
        'jobs': [name for name, _ in JOBS],
    })
