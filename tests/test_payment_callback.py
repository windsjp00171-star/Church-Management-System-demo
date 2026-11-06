"""綠界付款回呼：只有簽章正確且金鑰有設定才會把報名標成已付款。"""
import importlib
import sys
import types

import pytest

from fake_supabase import FakeSupabase

KEY, IV = 'hashkey', 'hashiv'


@pytest.fixture
def pay(monkeypatch):
    db = FakeSupabase(registrations=[{'id': 'r1', 'payment_note': 'ecpay:T123', 'payment_status': 'unpaid'}])
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=db))
    for n in ('routes.payment', 'settings_store'):
        sys.modules.pop(n, None)
    mod = importlib.import_module('routes.payment')
    # 替身沒有 like：自己補一個只比前綴的
    orig = db.table

    class Like:
        def __init__(self, q): self.q = q
        def __getattr__(self, a): return getattr(self.q, a)
        def like(self, col, pat):
            rows = [r for r in db.rows(self.q.table_name) if str(r.get(col, '')).startswith(pat.rstrip('%'))]
            return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=rows))
        def select(self, *a, **k): self.q.select(*a, **k); return self
    monkeypatch.setattr(db, 'table', lambda n: Like(orig(n)))
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(mod.payment_bp)
    yield types.SimpleNamespace(mod=mod, db=db, c=app.test_client(), set=lambda k, iv:
        monkeypatch.setattr(mod, '_get_gateway_settings', lambda: {'ecpay_hash_key': k, 'ecpay_hash_iv': iv}))
    for n in ('routes.payment', 'settings_store'):
        sys.modules.pop(n, None)


def _signed(mod, key, iv, **fields):
    data = {'MerchantTradeNo': 'T123', 'RtnCode': '1', **fields}
    data['CheckMacValue'] = mod._ecpay_checksum(dict(data), key, iv)
    return data


def _status(pay):
    return pay.db.rows('registrations')[0]['payment_status']


def test_valid_signature_marks_paid(pay):
    pay.set(KEY, IV)
    r = pay.c.post('/payment/ecpay/return', data=_signed(pay.mod, KEY, IV))
    assert r.data == b'1|OK' and _status(pay) == 'paid'


def test_wrong_signature_is_refused(pay):
    pay.set(KEY, IV)
    r = pay.c.post('/payment/ecpay/return', data=_signed(pay.mod, 'other', IV))
    assert r.data == b'0|Error' and _status(pay) == 'unpaid'


def test_unconfigured_keys_never_accept_a_callback(pay):
    """金鑰沒設（空字串）時，任何人都能算出同一個簽章；不可以因此被標成已付款。"""
    pay.set('', '')
    r = pay.c.post('/payment/ecpay/return', data=_signed(pay.mod, '', ''))
    assert r.data == b'0|Error' and _status(pay) == 'unpaid'


def test_uses_constant_time_compare():
    src = open('routes/payment.py', encoding='utf-8').read()
    assert 'hmac.compare_digest(received_mac' in src
