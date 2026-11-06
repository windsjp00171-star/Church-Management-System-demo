"""對真的 Postgres 執行 migration 與資料庫函式（環境沒有 Postgres 16 或不是 root 時略過）。"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

BIN = Path('/usr/lib/postgresql/16/bin')
ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(
    not (BIN / 'initdb').exists() or os.geteuid() != 0 or not shutil.which('psql'),
    reason='需要 root 與 Postgres 16')

A_IND, A_HEAD = '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000a2'
M1, M2, M_LEFT = (f'00000000-0000-0000-0000-0000000000b{i}' for i in (1, 2, 3))
S_IND, S_HEAD = '00000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-0000000000c2'


@pytest.fixture(scope='module')
def pg():
    base = tempfile.mkdtemp(prefix='pgtest')
    os.chmod(base, 0o777)
    run = lambda *a: subprocess.run(['runuser', '-u', 'postgres', '--', *a], capture_output=True)
    run(str(BIN / 'initdb'), '-D', f'{base}/data', '-A', 'trust')
    run(str(BIN / 'pg_ctl'), '-D', f'{base}/data', '-o', f'-p 55433 -k {base}', '-l', f'{base}/log', 'start')

    def psql(sql=None, file=None):
        args = ['psql', '-h', base, '-p', '55433', '-U', 'postgres', '-q', '-t', '-A']
        args += ['-f', file] if file else ['-c', sql]
        return subprocess.run(args, capture_output=True, text=True)

    assert psql(file=str(ROOT / 'migrations' / '009_roll_call.sql')).returncode == 0
    assert psql(file=str(ROOT / 'migrations' / '009_roll_call.sql')).returncode == 0   # 可重複執行
    psql(f"""INSERT INTO rc_meeting_types(id,name,record_mode) VALUES ('{A_IND}','主日','individual'),('{A_HEAD}','禱告會','headcount');
    INSERT INTO rc_members(id,name) VALUES ('{M1}','甲'),('{M2}','乙');
    INSERT INTO rc_members(id,name,status) VALUES ('{M_LEFT}','丙','left');
    INSERT INTO rc_sessions(id,type_id,starts_at) VALUES ('{S_IND}','{A_IND}',now()),('{S_HEAD}','{A_HEAD}',now());""")
    yield psql
    run(str(BIN / 'pg_ctl'), '-D', f'{base}/data', 'stop', '-m', 'immediate')
    shutil.rmtree(base, ignore_errors=True)


def save(pg, member, status, name='操作者', reason=None, sess=S_IND, backfill='false'):
    r = f"'{reason}'" if reason else 'NULL'
    return pg(f"select rc_save_record('{sess}','{member}','{status}',gen_random_uuid(),'{name}',{r},{backfill})")


def ok(res): assert res.returncode == 0, res.stderr
def bad(res, text):
    assert res.returncode != 0 and text in res.stderr, res.stderr


def test_flow_in_order(pg):
    ok(save(pg, M1, 'present'))                                   # 首次點名不需原因
    bad(save(pg, M1, 'absent'), '修改點名必須填寫原因')            # 守衛 3
    ok(save(pg, M1, 'absent', reason='填錯'))
    bad(save(pg, M1, 'maybe'), '無效的點名狀態')
    bad(save(pg, M1, 'late', name='  '), '操作者姓名不可為空')
    bad(save(pg, M_LEFT, 'present'), '已離開的成員不能新增點名')
    bad(save(pg, M1, 'present', sess=S_HEAD), '不是個人點名')
    ok(pg(f"select rc_lock_session('{S_IND}',gen_random_uuid(),'管理員')"))
    bad(save(pg, M2, 'present'), '場次已鎖定')                      # 守衛 7
    ok(save(pg, M2, 'present', name='管理員', reason='紙本補登', backfill='true'))


def test_counts_never_default_to_zero(pg):
    bad(pg(f"select rc_set_count('{S_HEAD}','headcount',NULL,gen_random_uuid(),'x')"), '人數不可空白')   # 守衛 25
    bad(pg(f"select rc_set_count('{S_HEAD}','headcount',-1,gen_random_uuid(),'x')"), '人數不可為負數')
    ok(pg(f"select rc_set_count('{S_HEAD}','headcount',0,gen_random_uuid(),'x')"))                      # 明確的 0 才是 0
    bad(pg(f"select rc_set_count('{S_HEAD}','headcount',5,gen_random_uuid(),'x')"), '必須填寫原因')


def test_every_write_left_an_audit_and_audit_is_append_only(pg):
    actions = pg('select string_agg(action, \',\' order by id) from rc_audit').stdout.strip()
    assert actions.startswith('mark,modify,lock,backfill'), actions                                    # 守衛 1
    for sql in ("update rc_audit set reason='x'", 'delete from rc_audit', 'truncate rc_audit'):         # 守衛 2
        bad(pg(sql), '只許追加')


def test_actor_name_survives_without_any_user_table(pg):
    assert pg("select to_regclass('users')").stdout.strip() == ''     # 測試庫根本沒有 users，點名照常運作
    assert pg("select count(*) from rc_audit where actor_name is null or actor_name = ''").stdout.strip() == '0'
