"""Optional disposable PostgreSQL databases for local verification only."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import os
import uuid
from urllib.parse import urlsplit


def verification_source(sqlite_path):
    admin=os.getenv('RESSOA_TEST_POSTGRES_ADMIN')
    if not admin:return sqlite_path
    parsed=urlsplit(admin)
    if parsed.hostname not in ('127.0.0.1','localhost') or parsed.path!='/postgres' or os.getenv('RESSOA_DISPOSABLE_POSTGRES')!='yes':
        raise RuntimeError('PostgreSQL verification requires the isolated loopback test runner.')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    options=conninfo_to_dict(admin)
    if options.get('host') not in ('127.0.0.1','localhost') or options.get('hostaddr') not in (None,'127.0.0.1'):
        raise RuntimeError('Remote databases are never used by this test helper.')
    name='ressoa_test_'+uuid.uuid4().hex
    with psycopg.connect(admin,autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    return parsed._replace(path='/'+name).geturl()
