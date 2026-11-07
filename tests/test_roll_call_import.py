"""名冊匯入：先預覽、疑似重複要人確認、同名一律不自動合併、伺服器不信任前端分類。"""
import io

import pytest

from roll_call_logic import names_from_upload, norm_name, plan_import

EXIST = [{'name': '王小明', 'status': 'active'}, {'name': '陳大文', 'status': 'left'},
         {'name': 'John Smith', 'status': 'active'}]


def _by(plan):
    return {r['name']: r['status'] for r in plan['rows']}


def test_classification():
    p = plan_import('王小明\n陳大文\n王曉明\n李小華\n李小華\n  李　小華 \n', EXIST)
    kept = {r['name']: r['status'] for r in p['rows'] if r['status'] != 'dup_in_file'}
    assert kept == {'王小明': 'same', '陳大文': 'same_left', '王曉明': 'similar', '李小華': 'new'}
    assert [r['status'] for r in p['rows']].count('dup_in_file') == 2     # 同批重複（含全形空白寫法）


def test_width_case_and_spaces_do_not_hide_a_duplicate():
    assert _by(plan_import('ｊｏｈｎ　smith\n', EXIST)) == {'ｊｏｈｎ　smith': 'same'}
    assert norm_name(' 王 小明 ') == '王小明'


def test_two_char_names_are_not_called_similar():
    assert _by(plan_import('王明\n', [{'name': '李明', 'status': 'active'}])) == {'王明': 'new'}


def test_similar_inside_the_same_batch_is_flagged_once_not_dropped():
    st = _by(plan_import('王小明\n王曉明\n', []))
    assert st == {'王小明': 'new', '王曉明': 'similar'}


def test_cap_is_reported():
    p = plan_import('\n'.join(f'人{i:04d}x' for i in range(2105)), [])
    assert p['truncated'] and len(p['rows']) == 2000


def test_upload_parsing():
    assert names_from_upload('姓名,電話\n王小明,0912\n李小華\n'.encode('utf-8-sig')) == '王小明\n李小華'
    assert names_from_upload('陳大文\n'.encode('cp950')) == '陳大文'
    with pytest.raises(ValueError):
        names_from_upload(b'\xff\xfe\x00\x81\x81\x81\x81')


# ── 路由 ──
def post(c, url, body):
    return c.post(url, json=body)


def test_preview_never_writes(fake_db, client_as):
    fake_db.tables['rc_members'] = list(EXIST)
    r = post(client_as(is_admin=True), '/api/admin/roll-call/members/preview', {'names': '王曉明\n李小華'})
    d = r.get_json()['data']
    assert {x['name']: x['status'] for x in d['rows']} == {'王曉明': 'similar', '李小華': 'new'}
    assert not [w for w in fake_db.writes if w[0] == 'rc_members']


def test_preview_accepts_a_csv_upload(fake_db, client_as):
    r = client_as(is_admin=True).post('/api/admin/roll-call/members/preview',
                                      data={'file': (io.BytesIO('姓名\n李小華\n'.encode('utf-8-sig')), 'n.csv')},
                                      content_type='multipart/form-data')
    assert [x['name'] for x in r.get_json()['data']['rows']] == ['李小華']


def test_oversize_upload_is_refused(fake_db, client_as):
    r = client_as(is_admin=True).post('/api/admin/roll-call/members/preview',
                                      data={'file': (io.BytesIO(b'a\n' * 600_000), 'n.csv')},
                                      content_type='multipart/form-data')
    assert r.status_code == 400


def test_similar_is_added_only_when_the_admin_confirms_it(fake_db, client_as):
    fake_db.tables['rc_members'] = list(EXIST)
    c = client_as(is_admin=True)
    r = post(c, '/api/admin/roll-call/members', {'names': '王曉明\n李小華'})
    assert r.get_json()['data']['added'] == 1
    assert [x['name'] for x in r.get_json()['data']['skipped']] == ['王曉明']
    r = post(c, '/api/admin/roll-call/members', {'names': '王曉明', 'confirm_similar': ['王曉明']})
    assert r.get_json()['data']['added'] == 1


def test_same_name_is_never_added_even_if_the_client_says_confirmed(fake_db, client_as):
    fake_db.tables['rc_members'] = list(EXIST)
    r = post(client_as(is_admin=True), '/api/admin/roll-call/members',
             {'names': '王小明\n陳大文', 'confirm_similar': ['王小明', '陳大文']})
    assert r.get_json()['data']['added'] == 0
    assert not [w for w in fake_db.writes if w[0] == 'rc_members']


def test_import_is_audited_with_counts_only(fake_db, client_as):
    post(client_as(is_admin=True), '/api/admin/roll-call/members', {'names': '李小華\n張三豐'})
    logged = [w for w in fake_db.writes if w[0] == 'audit_logs']
    assert logged and logged[0][2]['action'] == 'roll_call.members_import'
    assert logged[0][2]['detail'] == {'added': 2, 'skipped': 0, 'truncated': None}


def test_only_admins_can_import(fake_db, client_as):
    assert post(client_as(), '/api/admin/roll-call/members', {'names': 'x'}).status_code == 403
    assert post(client_as(), '/api/admin/roll-call/members/preview', {'names': 'x'}).status_code == 403
