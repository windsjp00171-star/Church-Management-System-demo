"""行程內快取（routes/cache.py）的行為，以及 settings_store 怎麼用它

「每一個 key 都有人 bust」由 test_cache_is_busted 掃；這裡守的是**行為**：
快取確實少打資料庫、失敗不被記住、寫入後立刻看得到、過期會重算。
"""
import time

import pytest

from routes import cache


def test_the_second_call_does_not_build_again():
    n = []
    assert cache.get('k', lambda: n.append(1) or ['v']) == ['v']
    assert cache.get('k', lambda: n.append(1) or ['x']) == ['v']
    assert len(n) == 1


def test_a_failed_build_is_not_remembered():
    """★ 把一次失敗記住的話，資料庫抖一下首頁就少一塊東西整整 TTL 那麼久。"""
    def boom():
        raise RuntimeError('Supabase 抖了一下')
    with pytest.raises(RuntimeError):
        cache.get('k', boom)
    assert cache.get('k', lambda: ['好了']) == ['好了']


def test_bust_makes_the_next_read_fresh():
    cache.get('k', lambda: 1)
    cache.bust('k')
    assert cache.get('k', lambda: 2) == 2


def test_an_expired_entry_is_rebuilt(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, 'time', lambda: now[0])
    cache.get('k', lambda: 1)
    now[0] += cache.DEFAULT_TTL - 1
    assert cache.get('k', lambda: 2) == 1
    now[0] += 2
    assert cache.get('k', lambda: 3) == 3


def test_busting_an_unknown_key_is_fine():
    cache.bust('nope')


# ── settings_store ──────────────────────────────

@pytest.fixture
def ss():
    import sys
    import types
    from tests.fake_supabase import FakeSupabase
    db = FakeSupabase(settings=[{'key': 'a', 'value': '1'}, {'key': 'b', 'value': '2'}])
    mod = types.ModuleType('db')
    mod.supabase = db
    sys.modules['db'] = mod
    sys.modules.pop('settings_store', None)
    import settings_store
    return settings_store, db


def test_settings_are_read_in_one_round_trip(ss):
    mod, db = ss
    calls = []
    real = db.table
    db.table = lambda name: calls.append(name) or real(name)
    assert [mod.get('a'), mod.get('b'), mod.get('a')] == ['1', '2', '1']
    assert calls == ['settings'], '三個 key 應該只查一趟'


def test_a_missing_key_falls_back_to_the_default(ss):
    mod, _ = ss
    assert mod.get('nope') is None
    assert mod.get('max_storage_gb') == '10'


def test_writing_a_setting_is_visible_immediately(ss):
    """★ 後台改完、前台看還是舊的 —— 這個專案最貴的那種 bug。set() 一定要 bust。"""
    mod, db = ss
    real = db.table

    class _Upsert:                      # 真的 settings 表主鍵是 key；替身的 upsert 只認 id，這裡照主鍵的行為補上
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            for r in db.rows('settings'):
                if r['key'] == self.payload['key']:
                    r['value'] = self.payload['value']

    class _Table:
        def __init__(self, name):
            self.q = real(name)

        def upsert(self, payload):
            return _Upsert(payload)

        def __getattr__(self, a):
            return getattr(self.q, a)

    db.table = lambda name: _Table(name)
    assert mod.get('a') == '1'
    mod.set('a', 9)
    assert mod.get('a') == '9'


def test_restoring_a_backup_clears_the_caches(fake_db):
    """匯入備份會直接 upsert 被快取的表，匯入完整份快取一起清。"""
    import zipfile, io
    from routes.data_transfer import import_bundle
    cache.get('settings_all', lambda: {'old': '1'})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('export_meta.json', '{}')
    import_bundle(zipfile.ZipFile(io.BytesIO(buf.getvalue())), upsert=lambda t, r: (0, None))
    assert cache.get('settings_all', lambda: {'fresh': '1'}) == {'fresh': '1'}
