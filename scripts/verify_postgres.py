"""Run the repository/API/browser checks against an isolated native PostgreSQL.

Uses portable binaries under .tools. No Windows service, firewall change,
remote database, or real Ressoa account is involved.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.tools'))
import psycopg


def main(migration_only=False,api_only=False):
    (ROOT/'verification').mkdir(exist_ok=True)
    binary=ROOT/'.tools'/'postgres'/'pgsql'/'bin'
    if not (binary/'postgres.exe').is_file():
        raise RuntimeError('Run python tests/prepare_postgres.py first.')
    with tempfile.TemporaryDirectory(prefix='ressoa-postgres-') as directory:
        temporary=Path(directory).resolve()
        if not temporary.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not temporary.name.startswith('ressoa-postgres-'):
            raise RuntimeError('Invalid temporary test directory.')
        password=secrets.token_urlsafe(32)
        secret_file=temporary/'test-password';secret_file.write_text(password,encoding='utf-8')
        data=temporary/'cluster';log=temporary/'postgres.log'
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        initialized=subprocess.run([str(binary/'initdb.exe'),'-D',str(data),'-U','codex','--encoding=UTF8','--locale=C','--auth=scram-sha-256','--pwfile='+str(secret_file)],capture_output=True,text=True,creationflags=flags)
        if initialized.returncode:
            raise RuntimeError('Could not initialize disposable PostgreSQL: '+initialized.stderr[-1200:])
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        with log.open('w') as output:
            server=subprocess.Popen([str(binary/'postgres.exe'),'-D',str(data),'-h','127.0.0.1','-p',str(port)],stdout=output,stderr=subprocess.STDOUT,creationflags=flags)
        admin=f'postgresql://codex:{password}@127.0.0.1:{port}/postgres?sslmode=disable'
        success=False
        try:
            for _ in range(100):
                if server.poll() is not None:raise RuntimeError('Disposable PostgreSQL exited before startup.')
                try:
                    with psycopg.connect(admin,connect_timeout=1):pass
                    break
                except psycopg.Error:time.sleep(.1)
            else:raise RuntimeError('Disposable PostgreSQL startup timed out.')
            environment=dict(os.environ,RESSOA_TEST_POSTGRES_ADMIN=admin,RESSOA_DISPOSABLE_POSTGRES='yes',PYTHONPATH=os.pathsep.join([str(ROOT/'.tools'),str(ROOT)]))
            environment.pop('DATABASE_URL',None);environment.pop('DATABASE_PATH',None);environment.pop('APP_ORIGIN',None)
            print('Native PostgreSQL ready on loopback; running disposable account/API checks.',flush=True)
            commands=[['scripts/verify_migration.py']] if migration_only else [['-m','unittest','discover','-s','tests','-v']] if api_only else [['-m','unittest','discover','-s','tests','-v'],['scripts/verify_accounts.py'],['scripts/verify_refinements.py'],['scripts/verify_people.py'],['scripts/verify_shared.py'],['scripts/verify_privacy.py'],['scripts/verify_feed.py'],['scripts/verify_editing.py']]
            for arguments in commands:
                subprocess.run([sys.executable,*arguments],cwd=ROOT,env=environment,check=True)
            success=True
        finally:
            stopped=subprocess.run([str(binary/'pg_ctl.exe'),'-D',str(data),'stop','-m','fast','-w'],capture_output=True,text=True,creationflags=flags)
            if stopped.returncode and server.poll() is None:
                server.terminate()
            server.wait(timeout=15)
        if success:
            report=dict(result='PASS',engine='native PostgreSQL 17',suites=['SQLite to PostgreSQL migration'] if migration_only else ['API accounts/privacy/concurrency'] if api_only else ['API accounts/privacy/concurrency','browser accounts','browser refinements','browser people','browser shared links','browser private profiles and lyric artwork','browser daily feed and republishing','browser edit decisions and saves'],remote_database_used=False,real_accounts_changed=False)
            (ROOT/'verification'/('migration-postgres-report.json' if migration_only else 'api-postgres-report.json' if api_only else 'postgres-report.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))


if __name__=='__main__':main('--migration-only' in sys.argv,'--api-only' in sys.argv)
