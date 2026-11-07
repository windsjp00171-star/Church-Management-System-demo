"""測試用的臨時 Postgres（需 root 與 Postgres 16；沒有就讓呼叫端略過）。"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

BIN = Path('/usr/lib/postgresql/16/bin')
AVAILABLE = (BIN / 'initdb').exists() and os.geteuid() == 0 and bool(shutil.which('psql'))
SKIP_REASON = '需要 root 與 Postgres 16'


def start(port):
    """啟動臨時叢集，回傳 (psql 函式, 停止函式)。psql(sql=None, file=None) 回傳 CompletedProcess。"""
    base = tempfile.mkdtemp(prefix='pgtest')
    os.chmod(base, 0o777)
    run = lambda *a: subprocess.run(['runuser', '-u', 'postgres', '--', *a], capture_output=True)
    run(str(BIN / 'initdb'), '-D', f'{base}/data', '-A', 'trust')
    r = run(str(BIN / 'pg_ctl'), '-D', f'{base}/data', '-o', f'-p {port} -k {base}', '-l', f'{base}/log', '-w', 'start')
    # -w：等伺服器真的起來，不然機器忙的時候第一個 psql 會連不上；起不來就把原因講出來（不然只看到「連不上」）
    if r.returncode != 0:
        log = Path(f'{base}/log').read_text(errors='replace')[-800:] if Path(f'{base}/log').exists() else ''
        raise RuntimeError(f'臨時 Postgres 起不來（port {port}）：{r.stderr.decode(errors="replace")[-300:]}\n{log}')

    def psql(sql=None, file=None):
        args = ['psql', '-h', base, '-p', str(port), '-U', 'postgres', '-q', '-t', '-A', '-v', 'ON_ERROR_STOP=1']
        args += ['-f', file] if file else ['-c', sql]
        return subprocess.run(args, capture_output=True, text=True)

    def stop():
        run(str(BIN / 'pg_ctl'), '-D', f'{base}/data', 'stop', '-m', 'immediate')
        shutil.rmtree(base, ignore_errors=True)

    return psql, stop
